# 2026.11.19(sooyeon.choi) 추가 - 단일 출처 평가 데이터셋(법령 조항 / 일반 문서) + 시험 데이터셋 다운로드
"""설계: docs/design/reports/eval-law-testset-design-v1.0.md

- 배분: 조항(섹션) 단위로 고르게, 부칙·짧은 본문 제외, 별표는 보충, 같은 (청크, variant)는 한 번만
- 단일 출처 검사: 답변 숫자·조항 번호가 근거 본문에 있어야 함
- 생성 흐름: 고아 포인트 제외, 검사 실패 자리는 대체 후보로 채움, 같은 청크 두 번째 질문은 첫 질문 뒤
- 다운로드: 질의·정답 근거·요약 시트, 일괄 질의 업로드·정답 파일과 호환
"""

import asyncio
import json
from collections import Counter
from io import BytesIO

import pytest
from openpyxl import load_workbook

from app.evaluation.dataset import single_source as ss


def _law_chunk(doc, idx, path, body="가" * 120, filename="중대재해 처벌 등에 관한 법률(법률)(제17907호).pdf", page=1):
    header = " > ".join(path)
    return {
        "chunk_id": f"{doc}-{idx}", "document_id": doc, "chunk_index": idx, "page_number": page,
        "original_filename": filename, "header_path": path, "section_title": path[-1] if path else None,
        "text": f"{header}\n\n### {path[-1]} (제목)\n{body}" if path else body,
    }


def _law_document(doc, articles, filename, *, supplement=2, annexes=0, start_index=0):
    """제1장 > 제1조 … 제N조, 부칙(제1조부터 다시), 별표."""
    chunks = []
    idx = start_index
    for number in range(1, articles + 1):
        chunks.append(_law_chunk(doc, idx, [f"제{1 + number // 10}장", f"제{number}조"], filename=filename, page=number))
        idx += 1
    for number in range(1, supplement + 1):
        chunks.append(_law_chunk(doc, idx, [f"제{1 + articles // 10}장", f"제{number}조"], filename=filename))
        idx += 1
    for number in range(1, annexes + 1):
        chunks.append(_law_chunk(doc, idx, [f"별표 {number}"], filename=filename))
        idx += 1
    return chunks


# ── 메타데이터 해석 ─────────────────────────────────────────────────────────

def test_header_path_and_law_name_parsing():
    assert ss.header_path_list({"header_path": ["제2장", "제4조"]}) == ["제2장", "제4조"]
    assert ss.header_path_list({"header_path": "['제2장', '제4조']"}) == ["제2장", "제4조"]
    assert ss.header_path_list({"header_path": '["별표 1"]'}) == ["별표 1"]
    assert ss.header_path_list({"header_path": "제2장 > 제4조"}) == ["제2장", "제4조"]
    assert ss.header_path_list({"header_path": "[]"}) == []
    assert ss.law_name_from_filename("산업안전보건법 시행령(대통령령)(제34603호)(20260626).pdf") == "산업안전보건법 시행령"
    assert ss.law_name_from_filename("중대재해 처벌 등에 관한 법률(법률)(제17907호)(20220127).pdf") == "중대재해 처벌 등에 관한 법률"


def test_build_law_units_excludes_supplement_short_and_header_only_chunks():
    chunks = _law_document("law", 8, "중대재해처벌법(법률).pdf", supplement=2, annexes=1)
    chunks.append(_law_chunk("law", 50, ["제1장", "제3조"], body="짧음"))           # 머리글·제목만 있는 조각
    chunks.append({**_law_chunk("law", 51, []), "section_title": None})               # 조항 정보 없음
    articles, annexes, skipped = ss.build_law_units(chunks, min_body_chars=80)
    assert [unit["label"] for unit in articles] == [f"제{n}조" for n in range(1, 9)]
    assert [unit["label"] for unit in annexes] == ["별표 1"]
    assert skipped == {"supplement": 3, "no_article": 1}  # 부칙 제1·2조 + 부칙 뒤 짧은 제3조(부칙으로 처리)
    assert articles[0]["law_name"] == "중대재해처벌법"


def test_build_law_units_orders_law_before_enforcement_decree():
    decree = _law_document("decree", 3, "중대재해처벌법 시행령(대통령령).pdf", supplement=0)
    law = _law_document("law", 3, "중대재해처벌법(법률).pdf", supplement=0)
    articles, _, _ = ss.build_law_units(decree + law)
    assert [unit["document_id"] for unit in articles] == ["law"] * 3 + ["decree"] * 3


# ── 배분 ────────────────────────────────────────────────────────────────────

def test_plan_spreads_evenly_when_articles_exceed_target():
    articles, _, _ = ss.build_law_units(_law_document("law", 105, "산업안전보건법(법률).pdf", supplement=0))
    plan = ss.plan_single_source_jobs(articles, 60)
    primary = plan[:60]
    numbers = sorted(int(job["unit"]["label"][1:-1]) for job in primary)
    assert len(set(numbers)) == 60                                   # 조항당 1개
    assert max(b - a for a, b in zip(numbers, numbers[1:])) <= 2      # 같은 간격(1.75조마다 1개)
    chapters = Counter(job["unit"]["header_path"][0] for job in primary)
    total_by_chapter = Counter(unit["header_path"][0] for unit in articles)
    for chapter, count in total_by_chapter.items():                   # 장별 분포 = 조항 수 비율 ±1
        assert abs(chapters[chapter] - count * 60 / 105) <= 1
    # 대체 후보: 남은 조항 45개(첫 질문) → 같은 청크 두 번째 질문 105개 순
    assert len(plan) == 210
    assert {job["variant"] for job in plan[60:105]} == {0} and {job["variant"] for job in plan[105:]} == {1}


def test_plan_rounds_then_annex_then_second_question():
    # 제1~20조(제1~10조는 청크 2개: 2바퀴째 후보, 본문이 짧은 쪽), 별표 3개
    chunks = []
    for n in range(1, 21):
        path = [f"제{1 + n // 10}장", f"제{n}조"]
        chunks.append(_law_chunk("law", n * 2, path))
        if n <= 10:
            chunks.append(_law_chunk("law", n * 2 + 1, path, body="나" * 90))
    chunks += [_law_chunk("law", 100 + n, [f"별표 {n}"]) for n in range(1, 4)]
    articles, annexes, _ = ss.build_law_units(chunks)
    plan = ss.plan_single_source_jobs(articles, 40, supplement_units=annexes, max_questions_per_chunk=2)
    primary = plan[:40]
    kinds = Counter((job["unit"]["kind"], job["variant"]) for job in primary)
    assert (kinds[("article", 0)], kinds[("annex", 0)]) == (30, 3)          # 1바퀴 20 + 2바퀴 10 + 별표 3
    assert kinds[("article", 1)] + kinds[("annex", 1)] == 7                 # 모자란 7개는 같은 청크 두 번째 질문
    assert len({(job["chunk"]["chunk_id"], job["variant"]) for job in plan}) == len(plan)  # 중복 없음
    first_round = [job for job in primary[:20]]
    assert all(job["chunk"]["text"].count("가") == 120 for job in first_round)            # 1바퀴는 본문이 긴 청크
    assert ss.plan_single_source_jobs(articles, 40, supplement_units=annexes, max_questions_per_chunk=1)[39:] == []


def test_mention_flags_follow_ratio_evenly():
    flags = ss.mention_article_flags(60, 0.3)
    assert sum(flags) == 18
    assert all(sum(flags[i:i + 10]) == 3 for i in range(0, 60, 10))
    assert sum(ss.mention_article_flags(10, 0)) == 0 and sum(ss.mention_article_flags(10, 1)) == 10


def test_section_units_for_general_documents():
    chunks = [
        {"chunk_id": "a1", "document_id": "a", "chunk_index": 0, "original_filename": "b.pdf", "text": "가" * 250, "section_title": "1. 개요"},
        {"chunk_id": "a2", "document_id": "a", "chunk_index": 1, "original_filename": "b.pdf", "text": "가" * 300, "section_title": "1. 개요"},
        {"chunk_id": "a3", "document_id": "a", "chunk_index": 2, "original_filename": "b.pdf", "text": "가" * 250, "page_number": 7},
        {"chunk_id": "a4", "document_id": "a", "chunk_index": 3, "original_filename": "b.pdf", "text": "짧음"},
        {"chunk_id": "z1", "document_id": "z", "chunk_index": 0, "original_filename": "a.pdf", "text": "가" * 250, "header_path": ["2장", "2.1"]},
    ]
    units, skipped = ss.build_section_units(chunks, min_chars=200)
    assert [(u["document_id"], u["label"], [c["chunk_id"] for c in u["chunks"]]) for u in units] == [
        ("z", "2.1", ["z1"]), ("a", "1. 개요", ["a2", "a1"]), ("a", "p.7", ["a3"]),
    ]
    assert skipped == {"short": 1}


# ── 단일 출처 검사 ──────────────────────────────────────────────────────────

def test_check_single_source_numbers_and_article_refs():
    text = "제2장 > 제6조\n\n① 제4조를 위반하여 사망에 이르게 한 사람은 1년 이상의 징역 또는 10억원 이하의 벌금에 처한다."
    assert ss.check_single_source("제6조의 처벌은?", "1년 이상의 징역 또는 10억원 이하의 벌금입니다.", text) is None
    assert ss.check_single_source("처벌은?", "7년 이하의 징역입니다.", text) == "답변의 숫자 '7'가 근거 본문에 없음"
    assert ss.check_single_source("제5조와 비교하면?", "1년 이상입니다.", text) == "근거 본문에 없는 조항 '제5조' 언급"
    assert ss.check_single_source("제 6 조 처벌은?", "10억 원 이하 벌금입니다.", text) is None  # 띄어쓰기 무시


# ── 생성 흐름 (가짜 LLM·청크 저장소·저장소) ────────────────────────────────

class _FakeRepo:
    def __init__(self, active):
        self.active = active
        self.items = []
        self.status = None
        self.progress = None

    def active_chunk_versions(self, collection_id):
        return self.active

    def update_dataset_status(self, dataset_id, status, error_message=None):
        self.status = (status, error_message)

    def update_dataset_progress(self, dataset_id, done, total):
        self.progress = (done, total)

    def insert_qa_item(self, **kwargs):
        self.items.append(kwargs)
        return len(self.items)


def _run_generation(monkeypatch, chunks, active, gen_config, answer_for):
    import app.evaluation.dataset.generator as gen

    prompts = []

    class FakeStore:
        async def scroll_chunks(self, collection_name):
            return chunks

    class FakeLLM:
        def __init__(self, **kwargs):
            pass

        async def chat(self, messages, **kwargs):
            prompt = messages[-1]["content"]
            prompts.append(prompt)
            question, answer = answer_for(prompt)
            return json.dumps({"question": question, "answer": answer}, ensure_ascii=False)

    async def fake_validate(retriever, question, gold_ids, collection_name):
        return 3

    monkeypatch.setattr(gen, "EvalChunkStore", FakeStore)
    monkeypatch.setattr(gen, "EvalLLM", FakeLLM)
    monkeypatch.setattr(gen, "EvalRetriever", lambda: object())
    monkeypatch.setattr(gen, "self_validate", fake_validate)
    repo = _FakeRepo(active)
    dataset = {"collection_id": 9, "qdrant_name": "law_coll"}
    asyncio.run(gen._run_single_source_generation(repo, 1, dataset, "law_coll", gen_config))
    return repo, prompts


def _article_of(prompt):
    return prompt.split("[조항] ", 1)[1].split("\n", 1)[0]


def test_single_source_generation_law_flow(monkeypatch):
    chunks = _law_document("law", 6, "중대재해처벌법(법률).pdf", supplement=1)
    orphan = _law_chunk("old", 0, ["제1장", "제1조"], filename="옛 등록본.pdf")
    active = {c["chunk_id"]: 1 for c in chunks}

    def answer_for(prompt):
        article = _article_of(prompt)
        if article == "제2조":
            return "정의 조항에서 정한 용어는 무엇인가요?", "777개입니다."  # 항상 단일 출처 검사 실패 → 대체 후보
        if article == "제3조" and "[재생성 지시]" not in prompt:
            return "적용 범위는 무엇인가요?", "5명 미만입니다."             # 1회 실패 후 재생성 성공
        if "[이미 만든 질문" in prompt:
            return f"{article}의 예외는 무엇인가요?", "본문의 예외 조건입니다."
        return f"{article}에서 정한 의무는 무엇인가요?", "본문에 정한 의무입니다."

    repo, prompts = _run_generation(monkeypatch, chunks + [orphan], active, {
        "generation_mode": "law_article", "target_count": 8, "article_ref_ratio": 0.5,
        "max_questions_per_chunk": 2, "concurrency": 1,
    }, answer_for)

    assert repo.status == ("review", None)
    assert len(repo.items) == 8
    assert all(item["question_type"] == "law" and len(item["gold_chunk_ids"]) == 1 for item in repo.items)
    used = Counter(item["gold_chunk_ids"][0] for item in repo.items)
    assert "old-0" not in used                                    # 고아 포인트 제외
    assert "law-1" not in used                                    # 제2조: 검사 실패 → 대체
    assert max(used.values()) == 2                                 # 같은 청크 최대 2문항
    metas = [item["source_meta"] for item in repo.items]
    assert {m["article"] for m in metas} == {"제1조", "제3조", "제4조", "제5조", "제6조"}
    assert all(m["law_name"] == "중대재해처벌법" and m["version_no"] == 1 for m in metas)
    assert sum(m["article_mentioned"] for m in metas) == 4         # 8자리 × 0.5
    assert any("[재생성 지시]" in p and "'5'" in p for p in prompts)
    second = [m for m in metas if m["variant"] == 1]
    assert second and all("[이미 만든 질문" in p for p in prompts if "의 예외는" in p)


def test_single_source_generation_fails_without_active_chunks(monkeypatch):
    chunks = _law_document("law", 2, "법.pdf", supplement=0)
    repo, _ = _run_generation(monkeypatch, chunks, {}, {"generation_mode": "law_article"}, lambda p: ("q", "a"))
    assert repo.status == ("failed", "컬렉션에 활성 문서 청크가 없습니다")


def test_section_mode_uses_general_prompt_and_type(monkeypatch):
    chunks = [
        {"chunk_id": f"g{i}", "document_id": "g", "chunk_index": i, "original_filename": "안내서.pdf",
         "text": f"섹션 {i} 본문 " + "가" * 250, "section_title": f"{i}. 절"}
        for i in range(4)
    ]
    repo, prompts = _run_generation(
        monkeypatch, chunks, {c["chunk_id"]: 2 for c in chunks},
        {"generation_mode": "single_section", "target_count": 4, "concurrency": 2},
        lambda p: ("작업 기준은 무엇인가요?", "본문 기준입니다."),
    )
    assert len(repo.items) == 4 and {i["question_type"] for i in repo.items} == {"general"}
    assert all("[문서] 안내서.pdf" in p and "[조항]" not in p for p in prompts)


# ── 시험 데이터셋 다운로드 ──────────────────────────────────────────────────

def _testset_items():
    def item(qa_id, unit_order, article, chunk_id, page, variant=0):
        return {
            "qa_id": qa_id, "question": f"질문 {qa_id}", "gold_answer": f"답변 {qa_id}",
            "question_type": "law", "review_status": "approved", "self_valid_rank": 4,
            "tags": json.dumps(["legal_reference"]), "gold_document_ids": json.dumps(["law"]),
            "gold_chunk_ids": json.dumps([chunk_id]), "gold_chunk_texts": json.dumps([f"근거 {qa_id}"]),
            "source_meta_json": json.dumps({
                "law_name": "중대재해처벌법", "original_filename": "중대재해처벌법.pdf", "article": article,
                "header_path": ["제2장", article], "page_number": page, "document_id": "law", "version_no": 1,
                "unit_order": unit_order, "chunk_index": unit_order, "variant": variant,
            }, ensure_ascii=False),
        }
    return [item(10, 2, "제6조", "p-6", 2), item(11, 0, "제4조", "p-4", 2), item(12, 0, "제4조", "=p", 2, variant=1)]


def test_testset_workbook_sheets_order_and_compatibility():
    from app.evaluation.batch.file_reader import read_query_file
    from app.evaluation.batch.gold_matcher import read_gold_file
    from app.evaluation.excel_exporter import build_testset_workbook

    dataset = {"dataset_id": 3, "name": "중처 시험", "collection_name": "AIE_중대재해처벌법",
               "gen_config_json": json.dumps({"generation_mode": "law_article", "query_id_prefix": "중처",
                                              "llm_model": "gemma-4-31B-it-FP8", "target_count": 60})}
    content = build_testset_workbook(dataset, _testset_items(), {"law": 1}).getvalue()
    workbook = load_workbook(BytesIO(content))
    assert workbook.sheetnames == ["질의", "정답 근거", "검수 정보", "요약"]
    review = [[c.value for c in row] for row in workbook["검수 정보"].iter_rows()]
    assert review[0][:4] == ["질의ID", "QA ID", "유형", "검수 상태"]
    assert review[1][:4] == ["중처-001", 11, "법령", "approved"] and review[1][6] == 4
    queries = [[c.value for c in row] for row in workbook["질의"].iter_rows()]
    assert queries[0] == ["질의ID", "질의문", "정답 답변"]
    assert [row[:2] for row in queries[1:]] == [["중처-001", "질문 11"], ["중처-002", "질문 12"], ["중처-003", "질문 10"]]
    gold = [[c.value for c in row] for row in workbook["정답 근거"].iter_rows()]
    assert gold[0] == ["질의ID", "근거순번", "근거 문서명", "근거 조항", "페이지", "청크ID", "근거 내용"]
    assert gold[1] == ["중처-001", 1, "중대재해처벌법.pdf", "제4조", 2, "p-4", "근거 11"]
    assert gold[2][5] == "'=p"                                           # 수식 주입 방지
    summary = {row[0].value: row[1].value for row in workbook["요약"].iter_rows()}
    assert summary["생성 방식"] == "법령 조항 단일 출처" and summary["생성 모델"] == "gemma-4-31B-it-FP8"
    assert summary["버전 확인"] == "생성 당시 문서 버전과 같음"
    assert summary["  중대재해처벌법"] == 3 and summary["  중대재해처벌법 · 제2장"] == 3

    # 일괄 질의 업로드(첫 시트)·정답 파일('정답 근거' 시트)로 그대로 읽힌다
    parsed = read_query_file("t.xlsx", content, max_rows=500, max_chars=2000)
    assert [row["query_key"] for row in parsed.items] == ["중처-001", "중처-002", "중처-003"]
    evidences, errors = read_gold_file("t.xlsx", content, ["중처-001", "중처-002", "중처-003"])
    assert errors == [] and evidences[0]["chunk_ids"] == ["p-4"] and evidences[0]["source_loc"] == "제4조 · p.2"

    stale = load_workbook(BytesIO(build_testset_workbook(dataset, _testset_items(), {"law": 2}).getvalue()))
    assert {row[0].value: row[1].value for row in stale["요약"].iter_rows()}["버전 확인"].startswith("경고: 생성 이후 문서 버전이 바뀐 질의 3건")


def test_testset_download_api(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.repositories import database
    from app.repositories.evaluation_repository import EvalRepository
    from app.routes.evaluation import router as eval_router
    from app.utils.security import get_current_admin

    database._db_manager = None
    database.DatabaseManager._instance = None
    dataset_id = None
    try:
        db = database.get_database_manager()
        db.execute_update("INSERT INTO tb_collections (display_name, qdrant_name) VALUES (?, ?)", ("법령", "testset_api"))
        collection_id = db.execute_query(
            "SELECT collection_id FROM tb_collections WHERE qdrant_name = ?", ("testset_api",))[0]["collection_id"]
        repo = EvalRepository()
        dataset_id = repo.create_dataset("법령 시험", collection_id, {"generation_mode": "law_article", "query_id_prefix": "산안"})
        qa_id = repo.insert_qa_item(  # 0013: question_type 'law' 허용
            dataset_id=dataset_id, question="질문", gold_answer="답변", gold_chunk_ids=["p1"],
            gold_document_ids=["missing-doc"], gold_chunk_texts=["근거"], question_type="law",
            source_meta={"article": "제4조", "page_number": 3, "document_id": "missing-doc", "version_no": 1},
        )
        app = FastAPI()
        app.include_router(eval_router, prefix="/api")
        app.dependency_overrides[get_current_admin] = lambda: {"admin_id": "admin"}
        client = TestClient(app)
        assert client.get(f"/api/eval/datasets/{dataset_id}/test-set.xlsx").status_code == 400  # 승인 전
        repo.update_qa_item(qa_id, review_status="approved")
        response = client.get(f"/api/eval/datasets/{dataset_id}/test-set.xlsx")
        assert response.status_code == 200
        assert 'filename="eval_testset_' in response.headers["content-disposition"]
        workbook = load_workbook(BytesIO(response.content))
        assert workbook["질의"]["A2"].value == "산안-001"
        assert workbook["정답 근거"]["D2"].value == "제4조"
        summary = {row[0].value: row[1].value for row in workbook["요약"].iter_rows()}
        assert summary["버전 확인"].startswith("경고")                       # 문서가 DB에 없음(삭제)
        assert client.get("/api/eval/datasets/99999/test-set.xlsx").status_code == 404
        bad = client.post("/api/eval/datasets", json={"name": "x", "collection_id": collection_id,
                                                       "gen_config": {"generation_mode": "unknown"}})
        assert bad.status_code == 400
    finally:
        # 'law' 문항이 남으면 다음 세션의 alembic downgrade(0013 보호 조건)가 막힌다
        if dataset_id is not None:
            EvalRepository().delete_dataset(dataset_id)
        manager = database.DatabaseManager._instance
        if manager is not None:
            manager.close_all_connections()
        database._db_manager = None
        database.DatabaseManager._instance = None


# ── 2026.11.19(sooyeon.choi) 추가 - '검색 확인 필요' 문항 같은 근거로 다시 생성 ──────────

class _RegenRepo:
    def __init__(self):
        self.replaced = None

    def replace_generated_qa(self, qa_id, **kwargs):
        self.replaced = (qa_id, kwargs)


def _regen_item(question_type="law"):
    return {
        "qa_id": 7, "question": "처음 질문은 무엇인가요?", "question_type": question_type,
        "gold_chunk_ids": json.dumps(["p-4"]),
        "gold_chunk_texts": json.dumps(["제2장 > 제4조\n\n① 사업주는 안전보건관리체계를 구축하여야 한다."], ensure_ascii=False),
        "source_meta_json": json.dumps({"law_name": "중대재해처벌법", "article": "제4조", "article_mentioned": True,
                                        "original_filename": "중대재해처벌법.pdf"}, ensure_ascii=False),
    }


def _patch_regen(monkeypatch, answers, rank=2):
    import app.evaluation.dataset.generator as gen

    prompts = []
    queue = list(answers)

    class FakeLLM:
        def __init__(self, **kwargs):
            pass

        async def chat(self, messages, **kwargs):
            prompts.append(messages[-1]["content"])
            question, answer = queue.pop(0)
            return json.dumps({"question": question, "answer": answer}, ensure_ascii=False)

    async def fake_validate(retriever, question, gold_ids, collection_name):
        assert gold_ids == ["p-4"]
        return rank

    monkeypatch.setattr(gen, "EvalLLM", FakeLLM)
    monkeypatch.setattr(gen, "EvalRetriever", lambda: object())
    monkeypatch.setattr(gen, "self_validate", fake_validate)
    return gen, prompts


def test_regenerate_uses_same_chunk_previous_question_and_resets_review(monkeypatch):
    gen, prompts = _patch_regen(monkeypatch, [
        ("중대재해처벌법 제4조에서 사업주가 갖춰야 할 것은?", "7가지입니다."),          # 숫자 검사 실패 → 재생성
        ("중대재해처벌법 제4조에서 사업주가 구축할 체계는?", "안전보건관리체계입니다."),
    ])
    repo = _RegenRepo()
    result = asyncio.run(gen.regenerate_single_source_item(repo, _regen_item(), "law_coll", {"llm_backend": "vllm"}))
    assert result["self_valid_rank"] == 2 and result["review_status"] == "pending"
    qa_id, saved = repo.replaced
    assert qa_id == 7 and saved["question"].endswith("구축할 체계는?")
    assert saved["source_meta"]["regenerate_count"] == 1
    assert saved["source_meta"]["previous_questions"] == ["처음 질문은 무엇인가요?"]
    assert "[이미 만든 질문" in prompts[0] and "처음 질문은 무엇인가요?" in prompts[0]
    assert '"중대재해처벌법 제4조"을(를) 직접 언급' in prompts[0]               # 언급 여부 유지
    assert "[재생성 지시]" in prompts[1]


def test_regenerate_fails_when_single_source_check_never_passes(monkeypatch):
    gen, _ = _patch_regen(monkeypatch, [("사업주가 갖출 것은 무엇인가요?", "7가지입니다."), ("사업주가 갖출 것은 무엇인가요?", "9가지입니다.")])
    repo = _RegenRepo()
    with pytest.raises(gen.RegenerationError, match="단일 출처 검사"):
        asyncio.run(gen.regenerate_single_source_item(repo, _regen_item(), "law_coll", {}))
    assert repo.replaced is None                                                # 기존 문항 유지


def test_regenerate_api_guards(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import app.evaluation.dataset.generator as gen
    from app.repositories import database
    from app.repositories.evaluation_repository import EvalRepository
    from app.routes.evaluation import router as eval_router
    from app.utils.security import get_current_admin

    database._db_manager = None
    database.DatabaseManager._instance = None
    dataset_id = None
    try:
        db = database.get_database_manager()
        db.execute_update("INSERT INTO tb_collections (display_name, qdrant_name) VALUES (?, ?)", ("법령", "regen_api"))
        collection_id = db.execute_query(
            "SELECT collection_id FROM tb_collections WHERE qdrant_name = ?", ("regen_api",))[0]["collection_id"]
        repo = EvalRepository()
        dataset_id = repo.create_dataset("법령", collection_id, {"generation_mode": "law_article", "llm_backend": "vllm"})
        repo.update_dataset_status(dataset_id, "review")
        common = dict(dataset_id=dataset_id, gold_answer="a", gold_chunk_ids=["p-4"], gold_document_ids=["d"],
                      gold_chunk_texts=["근거"])
        undetected = repo.insert_qa_item(question="q1", question_type="law", self_valid_rank=None, **common)
        detected = repo.insert_qa_item(question="q2", question_type="law", self_valid_rank=3, **common)
        typed = repo.insert_qa_item(question="q3", question_type="factual", self_valid_rank=None, **common)

        async def fake_regen(repo_, item, collection_name, config):
            assert collection_name == "regen_api" and config["vllm_api_url"]
            return {"qa_id": item["qa_id"], "self_valid_rank": 1, "review_status": "pending"}

        monkeypatch.setattr(gen, "regenerate_single_source_item", fake_regen)
        app = FastAPI()
        app.include_router(eval_router, prefix="/api")
        app.dependency_overrides[get_current_admin] = lambda: {"admin_id": "admin"}
        client = TestClient(app)
        assert client.post("/api/eval/items/99999/regenerate").status_code == 404
        assert client.post(f"/api/eval/items/{typed}/regenerate").status_code == 400      # 유형별 생성 문항
        assert client.post(f"/api/eval/items/{detected}/regenerate").status_code == 409   # 검색 확인 필요 아님
        ok = client.post(f"/api/eval/items/{undetected}/regenerate")
        assert ok.status_code == 200, ok.text
        assert ok.json()["self_valid_rank"] == 1
    finally:
        if dataset_id is not None:
            EvalRepository().delete_dataset(dataset_id)
        manager = database.DatabaseManager._instance
        if manager is not None:
            manager.close_all_connections()
        database._db_manager = None
        database.DatabaseManager._instance = None

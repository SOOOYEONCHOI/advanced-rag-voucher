"""시험 대응 일괄 질의 테스트 (2026.11.18(sooyeon.choi) 추가, eval-batch-query-design-v1.0.md 11장).

라이브 LLM/Qdrant 없이 검증한다. RAGService.query()는 가짜 서비스로 바꾼다.
  - 파일 읽기(인코딩·열 이름·오류 행), 본문 정리, 단계별 시간·백분위·요약
  - CSV(UTF-8 BOM·수식 주입 방지)·xlsx 구성
  - 저장소·실행기(워밍업 제외, 오류·시간 초과, 취소 시 완료분 보존)
  - API(설정 꺼짐 404, 파일 오류 400, 실행 중 다운로드·삭제 409, 결과 다운로드)
  - 재랭킹 전 검색 상위 N 요약(중복 제거)
"""

import asyncio
import csv
import io
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook

from app.models.data_models import ChunkSummary, Citation
from app.repositories import database


@pytest.fixture(autouse=True)
def reset_database_singletons():
    database._db_manager = None
    database.DatabaseManager._instance = None
    yield
    manager = database.DatabaseManager._instance
    if manager is not None:
        manager.close_all_connections()
    database._db_manager = None
    database.DatabaseManager._instance = None


def _batch_settings(**overrides):
    """일부 기존 테스트가 수집 단계에서 app.core.config를 stub으로 바꿔 두므로 필요한 설정만 직접 주입한다."""
    values = dict(
        eval_batch_query_enabled=True, eval_batch_max_rows=500, eval_batch_warmup_count=3,
        eval_batch_retry_count=0, eval_batch_query_timeout_s=120.0, eval_batch_top_n_record=10,
        eval_batch_gold_match_threshold=0.5, eval_batch_upload_max_mb=10, eval_batch_query_max_chars=2000,
        vllm_model_name="local-llm", embedding_model_name="embed", candidate_top_k=40,
        reranker_top_k=10, context_top_k=6, relevance_threshold=0.25, retrieval_engine="qdrant_hybrid",
    )
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.fixture
def batch_settings(monkeypatch):
    from app.evaluation.batch import runner
    import app.routes.eval_batch as route_module

    settings = _batch_settings()
    monkeypatch.setattr(runner, "get_settings", lambda: settings)
    monkeypatch.setattr(route_module, "get_settings", lambda: settings)
    return settings


def _xlsx_bytes(rows):
    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


# ── 파일 읽기 ────────────────────────────────────────────────────────────────

def test_read_query_file_csv_bom_cp949_and_xlsx():
    from app.evaluation.batch.file_reader import read_query_file

    text = "질의ID,질의문\nQ001,볼트 체결 토크는?\nQ002,에어 공구 점검 주기는?\n"
    for content in (text.encode("utf-8-sig"), text.encode("cp949")):
        result = read_query_file("q.csv", content, max_rows=500, max_chars=2000)
        assert result.errors == []
        assert result.items == [
            {"query_key": "Q001", "query_text": "볼트 체결 토크는?"},
            {"query_key": "Q002", "query_text": "에어 공구 점검 주기는?"},
        ]

    xlsx = _xlsx_bytes([["query_id", "Question"], [1, "숫자 ID 질의"], [None, None]])
    result = read_query_file("q.xlsx", xlsx, max_rows=500, max_chars=2000)
    assert result.items == [{"query_key": "1", "query_text": "숫자 ID 질의"}]


def test_read_query_file_reports_row_errors():
    from app.evaluation.batch.file_reader import QueryFileError, read_query_file

    content = "질의ID,질의문\nQ1,첫 질의\nQ1,중복 질의\nQ3,\n,ID 없음\nQ5,아주 긴 질의입니다\n".encode("utf-8")
    result = read_query_file("q.csv", content, max_rows=500, max_chars=5)
    reasons = [(e["row"], e["column"], e["reason"]) for e in result.errors]
    assert (3, "질의ID", "중복(2행과 같음)") in reasons
    assert (4, "질의문", "빈 값") in reasons
    assert (5, "질의ID", "빈 값") in reasons
    assert (6, "질의문", "5자 초과") in reasons

    many = "질의ID,질의문\n" + "".join(f"Q{i},질의 {i}\n" for i in range(4))
    assert read_query_file("q.csv", many.encode(), max_rows=3, max_chars=100).errors[-1]["reason"].startswith("질의는 최대 3건")

    with pytest.raises(QueryFileError):
        read_query_file("q.csv", "번호,내용\n1,a\n".encode(), max_rows=10, max_chars=10)
    with pytest.raises(QueryFileError):
        read_query_file("q.txt", b"x", max_rows=10, max_chars=10)


# ── 본문 정리 · 시간 · 요약 ──────────────────────────────────────────────────

def test_clean_answer_text_removes_citations_images_and_markdown():
    from app.evaluation.batch.text_clean import clean_answer_text

    raw = "## 체결 절차\n\n1. **볼트**를 체결합니다 [1][IMG:img_01].\n- 토크는 `25N·m` 입니다 [2, 3].\n> 참고"
    assert clean_answer_text(raw) == "체결 절차\n\n1. 볼트를 체결합니다.\n토크는 25N·m 입니다.\n참고"
    assert clean_answer_text("") == ""


def test_stage_timings_and_summary_statistics():
    from app.evaluation.batch.runner import compute_summary, percentile, stage_timings

    timing = {"validate_input_s": 0.01, "retrieve_s": 0.5, "rerank_s": 0.2, "generate_answer_s": 3.0, "format_citations_s": 0.05}
    assert stage_timings(timing) == {"search_ms": 510, "rerank_ms": 200, "generate_ms": 3050}
    assert stage_timings({}) == {"search_ms": None, "rerank_ms": None, "generate_ms": None}

    assert percentile([1, 2, 3, 4], 50) == pytest.approx(2.5)
    assert percentile([10], 90) == 10

    rows = [
        {"status": "ok", "outcome_code": "success", "response_ms": 1000, "timing_json": {"first_token_ms": 400}},
        {"status": "ok", "outcome_code": "success", "response_ms": 3000, "timing_json": {"first_token_ms": 800}},
        {"status": "ok", "outcome_code": "no_context", "response_ms": 500, "timing_json": {"first_token_ms": None}},
        {"status": "error", "outcome_code": "timeout", "response_ms": None},
        {"status": "pending", "response_ms": None},
    ]
    summary = compute_summary(rows)
    assert (summary["total"], summary["done"], summary["ok"], summary["error"], summary["not_run"]) == (5, 4, 3, 1, 1)
    assert summary["response_ms"] is None
    assert summary["response_time_status"] == "incomplete"
    assert summary["response_time_missing"] == 2
    assert summary["response_ms_success"]["mean"] == pytest.approx(1500.0)
    assert summary["response_ms_by_outcome"]["success"]["count"] == 2
    assert summary["recall_at_10"] is None
    assert summary["first_token_ms"]["count"] == 2 and summary["first_token_ms"]["mean"] == pytest.approx(600.0)


def _fake_response(answer="체결합니다 [1].", outcome="success", ms=1234.4):
    chunk = ChunkSummary(
        chunk_id="doc1:1:k#0", document_id="doc1", document_name="조립.xlsx", text="볼트 체결",
        score=0.9, sheet_name="09", step_no=3, rank=1,
    )
    return SimpleNamespace(
        answer=answer,
        outcome_code=outcome,
        citations=[Citation(citation_id="1", document_id="doc1", original_filename="조립.xlsx",
                            chunk_text="볼트 체결", sheet_name="09", referenced_in_answer=True)],
        chunks=[chunk],
        retrieved_chunks=[chunk],
        processing_time_ms=ms,
        timing={"retrieve_s": 0.1},
        log_id=None,
        first_token_ms=ms / 2,
    )


def test_build_item_fields_maps_response_and_error_outcomes():
    from app.evaluation.batch.runner import build_item_fields

    fields = build_item_fields(_fake_response(), top_n=10)
    assert fields["status"] == "ok"
    assert fields["response_ms"] == 1234
    assert fields["timing_json"]["first_token_ms"] == pytest.approx(617.2)
    assert fields["answer_plain"] == "체결합니다."
    assert fields["retrieved_top_json"][0]["sheet_name"] == "09"
    assert fields["retrieved_top_json"][0]["step_no"] == 3
    assert fields["citations_json"][0]["filename"] == "조립.xlsx"

    failed = build_item_fields(_fake_response(answer="오류", outcome="llm_error"), top_n=10)
    assert failed["status"] == "error" and failed["error_message"] == "llm_error"


# ── CSV · xlsx ───────────────────────────────────────────────────────────────

def _items():
    return [
        {
            "seq": 1, "query_key": "Q001", "query_text": "=SUM(A1)", "status": "ok",
            "outcome_code": "success", "answer_text": "답변 [1]", "answer_plain": "답변",
            "citations_json": [{"citation_id": "1", "filename": "조립.xlsx", "sheet_name": "09", "chunk_text": "근거"}],
            "retrieved_top_json": [{"rank": 1, "chunk_id": "c1", "filename": "조립.xlsx", "step_no": 3}],
            "reranked_top_json": [{"rank": 1, "chunk_id": "c1", "filename": "조립.xlsx", "score": 0.91234}],
            "response_ms": 9000,
            "timing_json": {"retrieve_s": 1.0, "rerank_s": 0.5, "generate_answer_s": 7.0, "first_token_ms": 2500.0},
            "error_message": None, "finished_at": "2026-11-18T10:00:00+09:00",
        },
        {
            "seq": 2, "query_key": "Q002", "query_text": "두 번째", "status": "error", "outcome_code": "timeout",
            "answer_text": None, "answer_plain": None, "citations_json": None, "retrieved_top_json": None,
            "reranked_top_json": None, "response_ms": None, "timing_json": None,
            "error_message": "제한 시간 120초 초과", "finished_at": None,
        },
    ]


def test_results_csv_has_bom_headers_and_blocks_formula_injection():
    from app.evaluation.batch.exporter import RESULT_HEADERS, build_results_csv

    content = build_results_csv(_items())
    assert content.startswith(b"\xef\xbb\xbf")
    rows = list(csv.reader(io.StringIO(content.decode("utf-8-sig"))))
    assert rows[0] == RESULT_HEADERS and len(RESULT_HEADERS) == 24
    first = dict(zip(rows[0], rows[1]))
    assert first["질의문"] == "'=SUM(A1)"
    assert first["결과유형"] == "답변"
    assert first["인용 출처"] == "[1] 조립.xlsx › 09"
    assert first["검색 상위10"] == "1. 조립.xlsx › 단계 3 [c1]"
    assert first["재랭킹 상위10"] == "1. 조립.xlsx [c1] (0.9123)"
    assert (first["검색(ms)"], first["재랭킹(ms)"], first["답변생성(ms)"]) == ("1000", "500", "7000")
    assert first["첫 토큰(ms)"] == "2500.0" and first["NDCG@5"] == ""
    second = dict(zip(rows[0], rows[2]))
    assert (second["상태"], second["결과유형"], second["오류내용"]) == ("오류", "오류", "제한 시간 120초 초과")
    fields = build_results_csv([{
        **_items()[0], "status": "error", "outcome_code": "llm_error",
        "timing_json": {"stage_statuses": {"retrieval": "ok", "rerank": "error", "answer": "error"}},
    }])
    exported = list(csv.DictReader(io.StringIO(fields.decode("utf-8-sig"))))[0]
    assert [exported[key] for key in ("검색 상태", "재랭킹 상태", "답변 생성 상태")] == ["정상", "오류", "오류"]


def test_results_xlsx_has_summary_and_result_sheets():
    from app.evaluation.batch.exporter import build_results_xlsx

    job = {
        "job_id": 7, "name": "시험", "collection_name": "coll", "status": "completed", "warmup_count": 3,
        "config_json": {"llm_model": "local-llm", "candidate_top_k": 40}, "total_count": 2,
        "summary_json": {"total": 2, "ok": 1, "error": 1, "not_run": 0,
                         "response_ms": {"mean": 9000.0, "p50": 9000.0, "p90": 9000.0, "p95": 9000.0, "max": 9000},
                         "first_token_ms": {"mean": 2500.0, "p50": 2500.0, "p90": 2500.0, "p95": 2500.0, "max": 2500.0}},
    }
    workbook = load_workbook(io.BytesIO(build_results_xlsx(job, _items())))
    assert workbook.sheetnames == ["요약", "질의별 결과"]
    summary = {row[0].value: row[1].value for row in workbook["요약"].iter_rows()}
    assert summary["응답시간 평균(ms)"] == 9000
    assert summary["오류 건수"] == 1
    assert summary["Recall@10 · NDCG@5"] == "정답 근거 확정 전"
    assert summary["첫 토큰 평균(ms)"] == 2500
    assert workbook["질의별 결과"].max_row == 3


# ── 재랭킹 전 상위 N 요약 ────────────────────────────────────────────────────

def test_summarize_ranked_chunks_dedupes_and_limits():
    pytest.importorskip("langgraph")  # rag_service는 그래프(langgraph)를 import한다 — 컨테이너에서 실행
    from app.services.rag_service import _summarize_ranked_chunks

    chunks = [
        {"chunk_id": "a", "document_id": "d", "text": "A", "score": 0.9, "metadata": {"filename": "f", "sheet_name": "S", "step_no": 2}},
        {"chunk_id": "a", "document_id": "d", "text": "A", "score": 0.8, "metadata": {}},
        {"chunk_id": "b", "document_id": "d", "text": "B", "score": 0.7, "metadata": {"step_no": "x"}},
        {"chunk_id": "c", "document_id": "d", "text": "C", "score": 0.6, "metadata": {}},
    ]
    summaries = _summarize_ranked_chunks(chunks, 2)
    assert [(s.chunk_id, s.rank) for s in summaries] == [("a", 1), ("b", 2)]
    assert summaries[0].sheet_name == "S" and summaries[0].step_no == 2
    assert summaries[1].step_no is None


# ── 저장소 · 실행기 ──────────────────────────────────────────────────────────

def _seed_collection():
    db = database.get_database_manager()
    db.execute_update(
        "INSERT INTO tb_collections (display_name, qdrant_name) VALUES (?, ?)", ("시험 컬렉션", "batch_coll"),
    )


def _create_job(repo, n=3, warmup=0):
    return repo.create_job(
        name="시험", collection_name="batch_coll",
        items=[{"query_key": f"Q{i}", "query_text": f"질의 {i}"} for i in range(1, n + 1)],
        warmup_count=warmup, config={"llm_model": "local"}, doc_versions={}, created_by="admin",
    )


class _FakeService:
    def __init__(self, behaviors=None, on_call=None):
        self.calls = []
        self.behaviors = behaviors or {}
        self.on_call = on_call

    async def query(self, *, query, user_id, collection_name, input_mode, capture_retrieval):
        assert input_mode == "batch_eval" and capture_retrieval is True and collection_name == "batch_coll"
        self.calls.append(query)
        if self.on_call:
            self.on_call(len(self.calls))
        behavior = self.behaviors.get(query)
        if behavior == "raise":
            raise RuntimeError("boom")
        if behavior == "timeout":
            raise asyncio.TimeoutError()
        return _fake_response(ms=1000.0 * len(self.calls))


def test_run_job_excludes_warmup_and_keeps_going_after_errors(monkeypatch, batch_settings):
    from app.evaluation.batch import runner
    from app.repositories.eval_batch_repository import EvalBatchRepository

    _seed_collection()
    repo = EvalBatchRepository()
    job_id = _create_job(repo, n=3, warmup=1)
    service = _FakeService({"질의 2": "raise", "질의 3": "timeout"})
    monkeypatch.setattr(runner, "_get_rag_service", lambda: service)
    clock = iter([0.0, 2.0, 10.0, 13.0, 20.0, 140.0])
    monkeypatch.setattr(runner, "time", SimpleNamespace(perf_counter=lambda: next(clock)))

    assert repo.claim_next_pending() == job_id
    asyncio.run(runner.run_job(job_id, repo))

    assert service.calls == ["질의 1", "질의 1", "질의 2", "질의 3"]  # 워밍업 1건 + 본 실행 3건
    job = repo.get_job(job_id)
    assert job["status"] == "completed"
    assert (job["done_count"], job["error_count"]) == (3, 2)
    items = repo.list_items(job_id)
    assert items[0]["status"] == "ok" and items[0]["response_ms"] == 2000  # 워밍업 결과는 저장하지 않음
    assert items[1]["status"] == "error" and items[1]["error_message"].startswith("RuntimeError")
    assert items[2]["outcome_code"] == "timeout"
    assert [row["response_ms"] for row in items] == [2000, 3000, 120000]
    assert job["summary_json"]["response_ms"]["mean"] == pytest.approx(41666.7)
    assert job["summary_json"]["response_ms"]["count"] == 3
    assert job["summary_json"]["error"] == 2


def test_summary_includes_error_times_and_rejects_missing_measurements():
    from app.evaluation.batch.runner import compute_summary

    rows = [
        {"status": "ok", "response_ms": 1000},
        {"status": "error", "outcome_code": "timeout", "response_ms": 9000},
    ]
    summary = compute_summary(rows)
    assert summary["response_ms"]["mean"] == 5000
    assert summary["response_ms"]["count"] == 2
    assert summary["response_time_status"] == "complete"
    assert summary["response_ms_success"]["mean"] == 1000
    for invalid in (None, -1, float("nan"), float("inf"), True):
        incomplete = compute_summary([*rows, {"status": "error", "response_ms": invalid}])
        assert incomplete["response_ms"] is None
        assert incomplete["response_time_missing"] == 1


@pytest.mark.parametrize("rerank_status,ndcg", [("ok", 1.0), ("error", 0.0), ("skipped", 0.0)])
def test_search_metrics_survive_answer_failure(rerank_status, ndcg):
    from app.evaluation.batch.recall import compute_recall
    from app.evaluation.batch.runner import build_item_fields

    response = _fake_response(answer="", outcome="llm_error")
    response.stage_statuses = {"retrieval": "ok", "rerank": rerank_status, "answer": "error"}
    fields = build_item_fields(response, 10)
    fields["query_key"] = "Q1"
    result = compute_recall([fields], [{"query_key": "Q1", "match_status": "confirmed",
                                      "confirmed_ids": ["doc1:1:k#0"]}])
    assert result["value"] == 1.0
    assert result["ndcg"] == ndcg
    assert result["item_errors"] == 1


def test_run_job_stops_on_cancel_and_preserves_done_items(monkeypatch, batch_settings):
    from app.evaluation.batch import runner
    from app.repositories.eval_batch_repository import EvalBatchRepository

    _seed_collection()
    repo = EvalBatchRepository()
    job_id = _create_job(repo, n=3)
    service = _FakeService(on_call=lambda n: repo.finish_job(job_id, "cancelled") if n == 1 else None)
    monkeypatch.setattr(runner, "_get_rag_service", lambda: service)

    repo.claim_next_pending()
    asyncio.run(runner.run_job(job_id, repo))

    assert service.calls == ["질의 1"]
    job = repo.get_job(job_id)
    assert job["status"] == "cancelled"
    assert job["summary_json"]["done"] == 1 and job["summary_json"]["not_run"] == 2


def test_warmup_failure_fails_job(monkeypatch, batch_settings):
    from app.evaluation.batch import runner
    from app.repositories.eval_batch_repository import EvalBatchRepository

    _seed_collection()
    repo = EvalBatchRepository()
    job_id = _create_job(repo, n=2, warmup=1)
    monkeypatch.setattr(runner, "_get_rag_service", lambda: _FakeService({"질의 1": "raise"}))
    repo.claim_next_pending()
    asyncio.run(runner.run_job(job_id, repo))
    job = repo.get_job(job_id)
    assert job["status"] == "failed" and job["error_message"] == "워밍업 실패: RuntimeError"
    assert job["done_count"] == 0


def test_claim_allows_single_running_job_and_restart_cleanup():
    from app.repositories.eval_batch_repository import EvalBatchRepository

    _seed_collection()
    repo = EvalBatchRepository()
    first, second = _create_job(repo), _create_job(repo)
    assert repo.claim_next_pending() == first
    assert repo.claim_next_pending() is None  # 실행 중 작업이 있으면 대기(F-03)
    assert repo.queue_position(second) == 1
    assert repo.mark_interrupted_jobs_failed() == 1
    assert repo.get_job(first)["error_message"] == "서버 재시작으로 중단됨(완료 0건 보존)"
    assert repo.claim_next_pending() == second


# ── API ──────────────────────────────────────────────────────────────────────

@pytest.fixture
def batch_client(monkeypatch, batch_settings):
    from app.evaluation.batch import runner
    from app.routes.eval_batch import router
    from app.utils.security import get_current_admin

    _seed_collection()
    monkeypatch.setattr(runner, "kick", lambda: None)  # 백그라운드 실행 없이 API 계약만 검증

    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_current_admin] = lambda: {"admin_id": "admin", "is_superadmin": False}
    return TestClient(app)


def _upload(client, text="질의ID,질의문\nQ1,첫 질의\nQ2,둘째 질의\n", collection="batch_coll"):
    return client.post(
        "/api/eval/batch-jobs",
        data={"collection_name": collection, "name": "시험 2"},
        files={"file": ("q.csv", text.encode("utf-8-sig"), "text/csv")},
    )


def test_batch_api_returns_404_when_disabled(monkeypatch, batch_settings):
    from app.routes.eval_batch import router

    batch_settings.eval_batch_query_enabled = False
    app = FastAPI()
    app.include_router(router, prefix="/api")
    assert TestClient(app).get("/api/eval/batch-jobs").status_code == 404


def test_batch_api_create_status_cancel_delete_flow(batch_client):
    bad = _upload(batch_client, text="질의ID,질의문\nQ1,\n")
    assert bad.status_code == 400
    assert bad.json()["detail"]["errors"][0]["reason"] == "빈 값"
    assert _upload(batch_client, collection="none").status_code == 404

    created = _upload(batch_client)
    assert created.status_code == 202, created.text
    job_id = created.json()["job_id"]
    assert created.json()["total"] == 2

    status = batch_client.get(f"/api/eval/batch-jobs/{job_id}").json()
    assert status["status"] == "pending" and status["done"] == 0
    assert status["config"]["candidate_top_k"] is not None
    assert batch_client.get("/api/eval/batch-jobs").json()["items"][0]["job_id"] == job_id

    assert batch_client.get(f"/api/eval/batch-jobs/{job_id}/results.csv").status_code == 409
    assert batch_client.delete(f"/api/eval/batch-jobs/{job_id}").status_code == 409

    assert batch_client.post(f"/api/eval/batch-jobs/{job_id}/cancel").json()["status"] == "cancelled"
    assert batch_client.post(f"/api/eval/batch-jobs/{job_id}/cancel").status_code == 409

    csv_resp = batch_client.get(f"/api/eval/batch-jobs/{job_id}/results.csv")
    assert csv_resp.status_code == 200
    assert csv_resp.content.startswith(b"\xef\xbb\xbf")
    assert "attachment" in csv_resp.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(csv_resp.content.decode("utf-8-sig"))))
    assert [r[1] for r in rows[1:]] == ["Q1", "Q2"] and rows[1][3] == "미실행"
    xlsx_resp = batch_client.get(f"/api/eval/batch-jobs/{job_id}/results.xlsx")
    assert load_workbook(io.BytesIO(xlsx_resp.content)).sheetnames == ["요약", "질의별 결과"]

    assert batch_client.delete(f"/api/eval/batch-jobs/{job_id}").json() == {"deleted": True}
    assert batch_client.get(f"/api/eval/batch-jobs/{job_id}").status_code == 404


def test_batch_eval_input_mode_is_allowed_and_excluded_from_stats():
    # test_stats_api.py가 수집 단계에서 sys.modules의 stats_repository를 stub으로 바꿔 두므로 원본 파일을 직접 로드한다
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "app" / "repositories" / "stats_repository.py"
    spec = importlib.util.spec_from_file_location("_batch_stats_repository_check", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    StatsRepository = module.StatsRepository

    db = database.get_database_manager()
    try:
        for mode in ("text", "batch_eval"):
            db.execute_update(
                "INSERT INTO tb_query_logs (user_id, query_text, input_mode) VALUES (?, ?, ?)",
                ("admin", f"{mode} 질의", mode),
            )
        assert StatsRepository().count_queries("2000-01-01T00:00:00+09:00", "2100-01-01T00:00:00+09:00") == 1
    finally:
        # 0012 downgrade는 batch_eval 로그가 있으면 중단한다(conftest가 세션 시작 때 base로 내림) → 직접 정리
        db.execute_update("DELETE FROM tb_query_logs WHERE input_mode = 'batch_eval'")


# ── RAGService.query 일괄 질의 옵션 (2026.11.18(sooyeon.choi) 추가) ─────────

def test_rag_service_batch_eval_skips_history_and_captures_retrieval(monkeypatch):
    pytest.importorskip("langgraph")
    import app.services.rag_service as rag_module

    class FakeRecorder:
        def __init__(self, repository):
            pass

        async def record(self, record, state, **kwargs):
            FakeRecorder.input_mode = record.input_mode
            FakeRecorder.session_id = record.session_id
            return 21

    class FakeMeta:
        stored = []

        def get_session_by_collection(self, user_id, name):
            raise AssertionError("batch_eval은 세션을 조회하지 않는다")

        def store_query_context(self, context):
            FakeMeta.stored.append(context)

    settings = SimpleNamespace(max_query_top_k=20, context_top_k=5, max_citation_results=5,
                               relevance_threshold=0.5, eval_batch_top_n_record=10)
    monkeypatch.setattr(rag_module, "get_settings", lambda: settings)
    monkeypatch.setattr(rag_module, "QueryRecorder", FakeRecorder)
    monkeypatch.setattr(rag_module, "MetadataRepository", lambda *_: FakeMeta())
    monkeypatch.setattr(rag_module, "_resolve_collection_id", lambda *_: 3)
    monkeypatch.setattr(rag_module, "CollectionRepository",
                        lambda *_: SimpleNamespace(get_by_id=lambda _id: SimpleNamespace(display_name="주제")))

    retrieved = [
        {"chunk_id": f"c{i}", "document_id": "d", "text": "t", "score": 1 - i / 100,
         "metadata": {"filename": "f.xlsx", "sheet_name": "09", "step_no": i}}
        for i in range(15)
    ]
    output = {
        "generated_answer": "답변 [1]", "final_context": "ctx", "should_retrieve": True, "outcome_code": "success",
        "retrieved_chunks": retrieved, "reranked_chunks": retrieved[:3],
        "citations": [{"citation_id": 1, "document_id": "d", "original_filename": "f.xlsx", "chunk_text": "t"}],
    }

    class FakeGraph:
        async def ainvoke(self, state):
            return {**state, **output}

    service = object.__new__(rag_module.RAGService)
    service._current_graph = lambda: FakeGraph()

    response = asyncio.run(service.query(
        query="질문", user_id="admin", collection_name="c",
        input_mode="batch_eval", capture_retrieval=True,
    ))
    assert FakeMeta.stored == []                      # 대화 이력 저장 안 함
    assert FakeRecorder.input_mode == "batch_eval" and FakeRecorder.session_id is None
    assert len(response.retrieved_chunks) == 10       # 재랭킹 전 상위 10
    assert response.retrieved_chunks[0].step_no == 0 and response.retrieved_chunks[9].rank == 10
    assert response.chunks[0].rank == 1 and response.chunks[0].sheet_name == "09"
    assert response.outcome_code == "success"

    # 기본(capture_retrieval=False)은 기존 응답과 같다(빈 목록·위치 필드 None)
    class TextMeta(FakeMeta):
        def get_session_by_collection(self, user_id, name):
            return SimpleNamespace(session_id="s1", collection_id=3)

        def get_query_context(self, session_id):
            return None

    monkeypatch.setattr(rag_module, "MetadataRepository", lambda *_: TextMeta())
    plain = asyncio.run(service.query(query="질문", user_id="u1", collection_name="c"))
    assert plain.retrieved_chunks == []
    assert plain.chunks[0].rank is None and plain.chunks[0].sheet_name is None
    assert len(FakeMeta.stored) == 1                  # 일반 질의는 대화 이력 저장


# ── 정답 근거 대조 · Recall@10 (2026.11.18(sooyeon.choi) 추가, 설계 6.7·7장) ──

def test_gold_matching_rules():
    from app.evaluation.batch.gold_matcher import (
        containment, find_documents, match_all, normalize_doc_name, normalize_text, parse_step_no,
    )

    assert normalize_doc_name("조립 절차서(Rev.3).xlsx") == normalize_doc_name("조립절차서 v2")
    assert normalize_text("ＡＢＣ　1-2") == "abc12"
    assert parse_step_no("09 시트 / 3단계") == 3 and parse_step_no("Step 12") == 12 and parse_step_no("p.3") is None
    assert containment(normalize_text("볼트를 25N·m로 체결"), normalize_text("먼저 볼트를 25N·m로 체결한다")) == 1.0
    assert containment("토크", "토크값") == 1.0  # 6자 미만은 포함 여부

    documents = [
        {"document_id": "d1", "original_filename": "조립 절차서.xlsx", "title": None, "version_no": 2},
        {"document_id": "d2", "original_filename": "점검 기준.xlsx", "title": None, "version_no": 1},
    ]
    assert find_documents("조립 절차서(Rev.2)", documents)[1] == "exact"
    assert find_documents("없는 문서", documents)[1] == "none"
    chunks = [
        {"chunk_id": "d1:2:09:step:3#0", "document_id": "d1", "sheet_name": "09", "step_no": 3,
         "chunk_text": "3단계 볼트를 25N·m로 체결한다. 와셔를 먼저 끼운다."},
        {"chunk_id": "d1:2:09:step:4#0", "document_id": "d1", "sheet_name": "09", "step_no": 4,
         "chunk_text": "4단계 커버를 덮는다."},
        {"chunk_id": "d2:1:c1#0", "document_id": "d2", "sheet_name": None, "step_no": None,
         "chunk_text": "볼트를 25N·m로 체결한다."},
    ]
    matched = match_all([
        {"query_key": "Q1", "evidence_seq": 1, "source_doc": "조립 절차서", "source_loc": "09 / 3단계",
         "evidence_text": "볼트를 25N·m로 체결한다"},
        {"query_key": "Q2", "evidence_seq": 1, "source_doc": "조립 절차서", "source_loc": "09 / 4단계",
         "evidence_text": "와셔를 먼저 끼운다"},  # 위치(4단계)에는 없음 → 문서 전체로 되돌려 찾음
        {"query_key": "Q3", "evidence_seq": 1, "source_doc": "조립 절차서", "source_loc": None,
         "evidence_text": "전혀 관계없는 문장입니다"},
    ], documents, chunks, 0.5)
    assert matched[0]["match_status"] == "auto"
    assert matched[0]["matched_json"]["auto_ids"] == ["d1:2:09:step:3#0"]  # 다른 문서(d2)는 후보 아님
    assert matched[0]["matched_json"]["location_used"] is True
    assert matched[1]["matched_json"]["auto_ids"] == ["d1:2:09:step:3#0"]
    assert matched[1]["matched_json"]["location_used"] is False
    assert matched[2]["match_status"] == "unmatched" and matched[2]["matched_json"]["auto_ids"] == []
    assert len(matched[2]["matched_json"]["candidates"]) == 2  # 참고 후보(문서 청크 2개)


def test_read_gold_file_validates_rows():
    from app.evaluation.batch.gold_matcher import read_gold_file

    content = (
        "질의ID,근거순번,근거 문서명,근거 위치,근거 내용\n"
        "Q1,,조립,09,근거 하나\nQ1,,조립,09,근거 둘\nQX,1,조립,,없는 질의\nQ2,1,조립,,\nQ2,a,조립,,x\n"
    ).encode("utf-8-sig")
    evidences, errors = read_gold_file("g.csv", content, ["Q1", "Q2"])
    assert [(e["query_key"], e["evidence_seq"]) for e in evidences] == [("Q1", 1), ("Q1", 2)]
    assert [e["reason"] for e in errors] == ["작업에 없는 질의ID", "빈 값", "숫자가 아님"]


def test_compute_recall_basis_exclusions_errors_and_version_mismatch():
    from app.evaluation.batch.recall import compute_recall, parse_chunk_ids

    items = [
        {"query_key": "Q1", "status": "ok",
         "retrieved_top_json": [{"chunk_id": "x"}, {"chunk_id": "d:1:a#0"}],
         "reranked_top_json": [{"chunk_id": "x"}]},
        {"query_key": "Q2", "status": "ok", "retrieved_top_json": [{"chunk_id": "x"}], "reranked_top_json": []},
        {"query_key": "Q3", "status": "error", "retrieved_top_json": None},
        {"query_key": "Q4", "status": "ok", "retrieved_top_json": []},
        {"query_key": "Q5", "status": "ok", "retrieved_top_json": []},
    ]
    gold = [
        {"query_key": "Q1", "match_status": "confirmed", "confirmed_ids": ["d:1:a#0"]},
        {"query_key": "Q1", "match_status": "excluded", "confirmed_ids": ["x"]},  # 제외 근거는 정답 아님
        {"query_key": "Q2", "match_status": "confirmed", "confirmed_ids": ["d:2:b#0"]},
        {"query_key": "Q3", "match_status": "confirmed", "confirmed_ids": ["d:1:c#0"]},
        {"query_key": "Q4", "match_status": "excluded", "confirmed_ids": ["d:1:a#0"]},
    ]
    # 2026.11.19(sooyeon.choi) 수정 - 청크 버전은 DB 조회 결과(chunk_versions)로, 분모는 전체 질의 수
    chunk_versions = {"d:1:a#0": ("d", 1), "d:2:b#0": ("d", 2), "d:1:c#0": ("d", 1)}
    result = compute_recall(items, gold, doc_versions={"d": 1}, chunk_versions=chunk_versions)
    assert (result["hit"], result["evaluated"], result["excluded"], result["item_errors"]) == (1, 3, 2, 1)
    assert result["total"] == 5
    assert result["value"] == pytest.approx(0.2)  # 1 / 전체 5 (정답 없음·제외·오류는 미적중)
    assert result["per_query"]["Q1"] == {"hit": 1, "rank": 2, "ndcg": 0.0, "reason": None, "version_mismatch": False}
    assert result["per_query"]["Q3"]["ndcg"] == 0.0  # 실행 오류 질의는 0
    assert result["per_query"]["Q2"]["version_mismatch"] is True
    assert result["per_query"]["Q5"] == {"hit": 0, "rank": None, "ndcg": 0.0, "reason": "no_gold"}
    assert compute_recall(items, gold)["version_mismatch"] == 0  # 버전 정보가 없으면 판단하지 않음
    assert compute_recall(items, gold, basis="reranked")["hit"] == 0
    assert parse_chunk_ids("a#0, b#1\nc#2  a#0") == ["a#0", "b#1", "c#2"]


# 2026.11.19(sooyeon.choi) 수정 - 정답 청크ID = Qdrant 포인트 ID(검색 결과와 같은 ID)
POINT_1 = "11111111-1111-4111-8111-111111111111"
POINT_2 = "22222222-2222-4222-8222-222222222222"


def _seed_gold_documents():
    db = database.get_database_manager()
    cid = db.execute_query(
        "SELECT collection_id FROM tb_collections WHERE qdrant_name = ?", ("batch_coll",)
    )[0]["collection_id"]
    db.execute_update(
        """INSERT INTO tb_documents (document_id, collection_id, original_filename, source_path, status, version_no)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("doc1", cid, "조립 절차서.xlsx", "/tmp/s.xlsx", "ready", 1),
    )
    db.execute_update(
        "INSERT INTO tb_document_versions (document_id, version_no, source_path) VALUES (?, ?, ?)",
        ("doc1", 1, "/tmp/s.xlsx"),
    )
    for chunk_id, point_id, step, text in (("doc1:1:09:step:1#0", POINT_1, 1, "볼트를 25N·m로 체결한다."),
                                           ("doc1:1:09:step:2#0", POINT_2, 2, "커버를 덮고 나사를 조인다.")):
        db.execute_update(
            """INSERT INTO tb_chunks (chunk_id, document_id, version_no, collection_id, point_id, source_key,
                                      part_no, point_type, sheet_name, step_no, chunk_text)
               VALUES (?, ?, 1, ?, ?::uuid, ?, 0, 'text', '09', ?, ?)""",
            (chunk_id, "doc1", cid, point_id, f"09:step:{step}", step, text),
        )


def _post_review(client, job_id, workbook):
    buffer = io.BytesIO()
    workbook.save(buffer)
    return client.post(
        f"/api/eval/batch-jobs/{job_id}/gold-review",
        files={"file": ("r.xlsx", buffer.getvalue(), "application/octet-stream")},
    )


def test_batch_api_gold_review_confirm_and_recall_flow(batch_client):
    from app.repositories.eval_batch_repository import EvalBatchRepository

    _seed_gold_documents()
    job_id = _upload(batch_client).json()["job_id"]
    repo = EvalBatchRepository()
    for item, top in zip(repo.list_items(job_id), (["x", POINT_1], ["y"])):
        repo.save_item_result(job_id, item["item_id"], {
            "status": "ok", "outcome_code": "success", "answer_text": "a", "answer_plain": "a",
            "retrieved_top_json": [{"rank": i + 1, "chunk_id": c} for i, c in enumerate(top)],
            "reranked_top_json": [], "response_ms": 100, "timing_json": {},
        })
    repo.finish_job(job_id, "completed", summary={"total": 2, "ok": 2, "error": 0})

    assert batch_client.get(f"/api/eval/batch-jobs/{job_id}/gold-review.xlsx").status_code == 409
    bad = batch_client.post(
        f"/api/eval/batch-jobs/{job_id}/gold",
        files={"file": ("g.csv", "질의ID,근거 문서명,근거 내용\nQ9,조립,x\n".encode("utf-8-sig"), "text/csv")},
    )
    assert bad.status_code == 400

    gold_csv = (
        "질의ID,근거순번,근거 문서명,근거 위치,근거 내용\n"
        "Q1,1,조립 절차서,09 1단계,볼트를 25N·m로 체결한다\n"
        "Q2,1,조립 절차서,09 2단계,커버를 덮고 나사를 조인다\n"
    ).encode("utf-8-sig")
    uploaded = batch_client.post(f"/api/eval/batch-jobs/{job_id}/gold", files={"file": ("g.csv", gold_csv, "text/csv")})
    assert uploaded.status_code == 200, uploaded.text
    assert (uploaded.json()["auto"], uploaded.json()["unmatched"]) == (2, 0)
    assert batch_client.get(f"/api/eval/batch-jobs/{job_id}/recall").status_code == 409  # 확정 전

    review = load_workbook(io.BytesIO(batch_client.get(f"/api/eval/batch-jobs/{job_id}/gold-review.xlsx").content))
    assert review.sheetnames == ["검토", "후보 상세", "안내"]
    sheet = review["검토"]
    headers = [c.value for c in sheet[1]]
    ids_col = headers.index("확정 청크ID") + 1
    assert sheet.cell(2, ids_col).value == POINT_1
    assert sheet.cell(3, ids_col).value == POINT_2

    sheet.cell(3, ids_col).value = "doc1:1:09:step:2#0"  # DB 청크 키(포인트 ID 아님)·없는 ID는 거부
    assert _post_review(batch_client, job_id, review).status_code == 400

    sheet.cell(3, ids_col).value = POINT_2
    confirmed = _post_review(batch_client, job_id, review)
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["recall_at_10"]["value"] == pytest.approx(0.5)  # Q1 적중(2위), Q2 미적중

    status = batch_client.get(f"/api/eval/batch-jobs/{job_id}").json()
    assert status["gold_status"] == "confirmed" and status["summary"]["recall_at_10"]["hit"] == 1
    detail = batch_client.get(f"/api/eval/batch-jobs/{job_id}/recall", params={"basis": "reranked"}).json()
    assert detail["hit"] == 0 and detail["per_query"]["Q1"]["hit"] == 0
    assert batch_client.get(f"/api/eval/batch-jobs/{job_id}/recall", params={"k": 20}).status_code == 400

    rows = list(csv.reader(io.StringIO(
        batch_client.get(f"/api/eval/batch-jobs/{job_id}/results.csv").content.decode("utf-8-sig"))))
    header = rows[0]
    assert rows[1][header.index("Recall@10 적중")] == "1" and rows[1][header.index("정답 적중 순위")] == "2"
    assert rows[2][header.index("Recall@10 적중")] == "0"



def test_compute_recall_ndcg_at_5_uses_reranked_results():
    # 2026.11.18(sooyeon.choi) 추가 - NDCG@5는 basis와 무관하게 재랭킹 후 상위 5 기준
    import math

    from app.evaluation.batch.recall import compute_recall

    items = [
        {"query_key": "Q1", "status": "ok", "retrieved_top_json": [],
         "reranked_top_json": [{"chunk_id": "g1"}, {"chunk_id": "x"}, {"chunk_id": "g2"}]},
        {"query_key": "Q2", "status": "ok", "retrieved_top_json": [],
         "reranked_top_json": [{"chunk_id": c} for c in ("a", "b", "c", "d", "e", "g3")]},  # 6위 → 0
    ]
    gold = [
        {"query_key": "Q1", "match_status": "confirmed", "confirmed_ids": ["g1", "g2"]},
        {"query_key": "Q2", "match_status": "confirmed", "confirmed_ids": ["g3"]},
    ]
    result = compute_recall(items, gold)
    q1 = (1 + 1 / math.log2(4)) / (1 + 1 / math.log2(3))
    assert result["per_query"]["Q1"]["ndcg"] == pytest.approx(round(q1, 4))
    assert result["per_query"]["Q2"]["ndcg"] == 0.0
    assert result["ndcg"] == pytest.approx(round(q1 / 2, 4))
    assert result["ndcg_k"] == 5


def test_rag_service_first_token_ms_from_generate_timing(monkeypatch):
    # 2026.11.18(sooyeon.choi) 추가 - 요청 시작 → LLM 첫 토큰(ms), timing에서 시각 키는 제거
    pytest.importorskip("langgraph")
    import app.services.rag_service as rag_module
    from app.graphs.nodes.generate_answer import FIRST_TOKEN_AT_KEY

    class FakeRecorder:
        def __init__(self, repository):
            pass

        async def record(self, record, state, **kwargs):
            return 1

    settings = SimpleNamespace(max_query_top_k=20, context_top_k=5, max_citation_results=5,
                               relevance_threshold=0.5, eval_batch_top_n_record=10)
    monkeypatch.setattr(rag_module, "get_settings", lambda: settings)
    monkeypatch.setattr(rag_module, "QueryRecorder", FakeRecorder)
    monkeypatch.setattr(rag_module, "MetadataRepository", lambda *_: SimpleNamespace())
    monkeypatch.setattr(rag_module, "_resolve_collection_id", lambda *_: 3)
    monkeypatch.setattr(rag_module, "CollectionRepository",
                        lambda *_: SimpleNamespace(get_by_id=lambda _id: SimpleNamespace(display_name="주제")))
    import itertools

    def fake_clock():
        clock = itertools.chain([1000.0], itertools.repeat(1003.0))  # 서비스 시작 1000s, 이후 1003s
        return lambda: next(clock)

    monkeypatch.setattr(rag_module.time, "time", fake_clock())

    class FakeGraph:
        def __init__(self, timing):
            self.timing = timing

        async def ainvoke(self, state):
            return {**state, "generated_answer": "답변", "outcome_code": "success", "timing": dict(self.timing)}

    service = object.__new__(rag_module.RAGService)
    service._current_graph = lambda: FakeGraph({"generate_answer_s": 2.0, FIRST_TOKEN_AT_KEY: 1000.75})
    response = asyncio.run(service.query(query="질문", user_id="admin", collection_name="c", input_mode="batch_eval"))
    assert response.first_token_ms == pytest.approx(750.0)
    assert FIRST_TOKEN_AT_KEY not in response.timing and response.timing["generate_answer_s"] == 2.0

    monkeypatch.setattr(rag_module.time, "time", fake_clock())
    service._current_graph = lambda: FakeGraph({"guardrail_s": 0.1})  # 답변 생성 안 함
    assert asyncio.run(service.query(query="질문", user_id="admin", collection_name="c",
                                     input_mode="batch_eval")).first_token_ms is None


# ── 2026.11.19(sooyeon.choi) 추가 - 정답 청크ID 직접 지정(시험 데이터셋 '정답 근거' 시트) ──────

def test_read_gold_file_accepts_chunk_ids_article_page_and_testset_sheet():
    from openpyxl import Workbook

    from app.evaluation.batch.gold_matcher import read_gold_file

    workbook = Workbook()
    workbook.active.title = "질의"
    workbook.active.append(["질의ID", "질의문", "정답 답변"])
    sheet = workbook.create_sheet("정답 근거")
    sheet.append(["질의ID", "근거순번", "근거 문서명", "근거 조항", "페이지", "청크ID", "근거 내용"])
    sheet.append(["Q1", 1, "중대재해처벌법.pdf", "제4조", 2, f"{POINT_1}, {POINT_2}", ""])
    sheet.append(["Q2", 1, "중대재해처벌법.pdf", "", None, "", ""])  # 청크ID·근거 내용 모두 없음
    buffer = io.BytesIO()
    workbook.save(buffer)
    evidences, errors = read_gold_file("t.xlsx", buffer.getvalue(), ["Q1", "Q2"])
    assert evidences == [{
        "query_key": "Q1", "evidence_seq": 1, "source_doc": "중대재해처벌법.pdf",
        "source_loc": "제4조 · p.2", "evidence_text": "", "chunk_ids": [POINT_1, POINT_2],
    }]
    assert [(e["row"], e["column"]) for e in errors] == [(3, "근거 내용")]


def _completed_job_with_results(batch_client):
    from app.repositories.eval_batch_repository import EvalBatchRepository

    _seed_gold_documents()
    job_id = _upload(batch_client).json()["job_id"]
    repo = EvalBatchRepository()
    for item, top in zip(repo.list_items(job_id), ([POINT_2, POINT_1], ["y"])):
        repo.save_item_result(job_id, item["item_id"], {
            "status": "ok", "outcome_code": "success", "answer_text": "a", "answer_plain": "a",
            "retrieved_top_json": [{"rank": i + 1, "chunk_id": c} for i, c in enumerate(top)],
            "reranked_top_json": [{"rank": 1, "chunk_id": POINT_1}],
            "response_ms": 100, "timing_json": {},
        })
    repo.finish_job(job_id, "completed", summary={"total": 2, "ok": 2, "error": 0})
    return job_id


def test_batch_api_gold_with_chunk_ids_confirms_without_review(batch_client):
    job_id = _completed_job_with_results(batch_client)
    gold_csv = (
        "질의ID,근거순번,근거 문서명,근거 조항,페이지,청크ID,근거 내용\n"
        f"Q1,1,조립 절차서,제1조,1,{POINT_1},볼트\n"
        f"Q2,1,조립 절차서,제2조,1,{POINT_2},커버\n"
    ).encode("utf-8-sig")
    resp = batch_client.post(f"/api/eval/batch-jobs/{job_id}/gold", files={"file": ("g.csv", gold_csv, "text/csv")})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["gold_status"], body["confirmed"], body["auto"]) == ("confirmed", 2, 0)
    # Q1 적중(2위), Q2 미적중 → 1/2. NDCG@5: Q1 재랭킹 1위 = 1.0, Q2 = 0 → 0.5
    assert body["recall_at_10"]["value"] == pytest.approx(0.5)
    assert body["recall_at_10"]["ndcg"] == pytest.approx(0.5)
    assert body["recall_at_10"]["total"] == 2 and body["recall_at_10"]["version_mismatch"] == 0
    status = batch_client.get(f"/api/eval/batch-jobs/{job_id}").json()
    assert status["gold_status"] == "confirmed"


def test_batch_api_gold_rejects_unknown_chunk_ids(batch_client):
    job_id = _completed_job_with_results(batch_client)
    gold_csv = (
        "질의ID,근거 문서명,청크ID\n"
        f"Q1,조립 절차서,{POINT_1}\n"
        "Q2,조립 절차서,doc1:1:09:step:2#0\n"  # DB 청크 키는 검색 결과 ID가 아니므로 거부
    ).encode("utf-8-sig")
    resp = batch_client.post(f"/api/eval/batch-jobs/{job_id}/gold", files={"file": ("g.csv", gold_csv, "text/csv")})
    assert resp.status_code == 400
    assert "컬렉션에 없는 청크ID 1건" in resp.json()["detail"]["errors"][0]["reason"]

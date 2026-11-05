"""Phase 4-A 답변 사진 (2026.10.19, R4-3 / F-4-03·F-4-04 / SC-01·SC-03 / UI-03·UI-04).

10-12 이전 판(옛 tb_image_placements 기준) 테스트를 현행 Phase 2 테이블(tb_spreadsheet_resources) 기준으로 다시 썼다.
- 후보 수집: 청크 payload resource_ids → 같은 문서·현재 버전의 표시 가능한 사진, 역할·질의어 정렬, 같은 이미지 1건,
  연결 사진이 없는 excel_ingest 표 청크는 같은 시트·행 범위 사진, 삭제·연결 안 함·장식·emf·다른 문서·이전 버전 제외
- 인용 검증: 후보에 없는 [IMG:x] 제거(완료 기준), 최대 장수, Step 사진 자동 첨부, 근거 없음 답변엔 자동 첨부 안 함
- 노드: collect_answer_images(설정 끔·프롬프트 예산), format_citations(정리된 답변·answer_images)
- 스트리밍: images SSE 이벤트, 대화 이력에 사진 저장
DB는 PostgreSQL 테스트 DB(사진 행 직접 입력), 외부 서버 없음.
"""
from __future__ import annotations

import asyncio
import importlib
import json
import sys
from types import SimpleNamespace

import pytest

# 일부 기존 테스트가 수집 단계에서 sys.modules["app.core.config"]를 stub(Settings 없음)으로 바꿔 둔다.
# 이 파일의 import 동안만 실제 설정 모듈을 쓰고, 끝나면 stub을 되돌려 다른 테스트에 영향을 주지 않는다.
_config_stub = sys.modules.get("app.core.config")
if _config_stub is not None and not hasattr(_config_stub, "Settings"):
    sys.modules.pop("app.core.config")
    importlib.import_module("app.core.config")
try:
    from app.graphs.images import (
        collect_image_candidates,
        image_prompt_block,
        public_images,
        validate_answer_images,
    )
    from app.graphs.nodes.collect_answer_images import collect_answer_images, context_with_images
    from app.graphs.nodes.format_citations import format_citations
    from app.repositories.database import get_database_manager

    # app.graphs.nodes 패키지가 같은 이름의 노드 함수를 다시 내보내므로 모듈은 importlib로 가져온다
    collect_node = importlib.import_module("app.graphs.nodes.collect_answer_images")
finally:
    if _config_stub is not None and not hasattr(_config_stub, "Settings"):
        sys.modules["app.core.config"] = _config_stub

# ── 순수 함수 ─────────────────────────────────────────────────────────────

CANDIDATES = [
    {"ref": "aaa111", "resource_id": "d1-v1-i0001", "document_id": "d1", "title": "FAN Step 6 Step 사진",
     "role": "step_photo", "sheet_name": "FAN", "from_cell": "C18", "to_cell": "C19", "step_no": 6,
     "context_no": 1, "query_match": 0},
    {"ref": "bbb222", "resource_id": "d1-v1-i0002", "document_id": "d1", "title": "FAN 도면",
     "role": "drawing", "sheet_name": "FAN", "from_cell": "H3", "to_cell": None, "step_no": None,
     "context_no": 2, "query_match": 0},
]


def test_validate_keeps_only_candidate_ids_and_strips_invented_ones():
    answer = "REACT FAN을 체결합니다[1] [IMG:aaa111]. 도면은 다음과 같습니다 [IMG:zzz999]. 끝[IMG:bbb222]"
    cleaned, images = validate_answer_images(answer, CANDIDATES)
    assert "[IMG:zzz999]" not in cleaned and "[IMG:aaa111]" in cleaned and "[IMG:bbb222]" in cleaned
    assert "다음과 같습니다." in cleaned
    assert [i["resource_id"] for i in images] == ["d1-v1-i0001", "d1-v1-i0002"]
    assert all(i["cited"] for i in images)


def test_validate_limits_images_and_auto_attaches_step_photo():
    cleaned, images = validate_answer_images("A [IMG:aaa111] B [IMG:bbb222]", CANDIDATES, max_images=1)
    assert [i["ref"] for i in images] == ["aaa111"] and "[IMG:bbb222]" not in cleaned
    assert validate_answer_images("A [IMG:aaa111]", CANDIDATES, max_images=0) == ("A ", [])

    step_chunk = [{"metadata": {"step_no": 6}}]
    _, auto = validate_answer_images("조립 순서입니다[1].", CANDIDATES, context_chunks=step_chunk)
    assert [(i["ref"], i["cited"]) for i in auto] == [("aaa111", False)]
    _, off = validate_answer_images("조립 순서입니다[1].", CANDIDATES, context_chunks=step_chunk, auto_step_image=False)
    assert off == []
    _, other = validate_answer_images("요약입니다[1].", CANDIDATES, context_chunks=[{"metadata": {}}])
    assert other == []


def test_validate_attaches_single_clear_query_match():
    parts = [{**CANDIDATES[1], "ref": "p1", "query_match": 2}, {**CANDIDATES[1], "ref": "p2", "query_match": 1}]
    _, images = validate_answer_images("품번은 MEC21103입니다[1].", parts, context_chunks=[{"metadata": {}}])
    assert [i["ref"] for i in images] == ["p1"]
    tie = [{**parts[0]}, {**parts[0], "ref": "p3"}]
    assert validate_answer_images("품번[1].", tie, context_chunks=[{"metadata": {}}])[1] == []


def test_prompt_block_and_public_fields():
    block = image_prompt_block(CANDIDATES)
    assert block.startswith("[관련 이미지 후보]")
    assert "[IMG:aaa111] FAN Step 6 Step 사진 (문서 [1] C18:C19)" in block
    assert "[IMG:bbb222] FAN 도면 (문서 [2] H3)" in block
    assert image_prompt_block([]) == ""
    assert context_with_images("CTX", []) == "CTX"
    assert context_with_images("CTX", CANDIDATES).startswith("CTX\n\n[관련 이미지 후보]")
    public = public_images([{**CANDIDATES[0], "cited": True, "resource_path": "documents/x", "query_match": 3}])
    assert "resource_path" not in public[0] and "query_match" not in public[0] and public[0]["cited"] is True


def test_candidate_lookup_failure_does_not_break_answer():
    class Broken:
        def execute_query(self, *args):
            raise RuntimeError("db down")

    chunk = {"chunk_id": "c", "document_id": "d", "metadata": {"resource_ids": ["r1"]}}
    assert collect_image_candidates([chunk], db=Broken()) == []
    assert collect_image_candidates([chunk], limit=0, db=Broken()) == []


# ── DB: 사진 행 ───────────────────────────────────────────────────────────

def _document(db, document_id: str, *, version_no: int = 1, deleted: bool = False) -> None:
    from excel_ingest_fakes import ensure_collection

    db.execute_update(
        "INSERT INTO tb_documents (document_id, collection_id, source_path, original_filename, version_no, deleted_at)"
        " VALUES (?, ?, ?, ?, ?, " + ("now()" if deleted else "NULL") + ")",
        (document_id, ensure_collection("documents"), f"/x/{document_id}.xlsx", f"{document_id}.xlsx", version_no),
    )


def _resource(db, document_id: str, seq: int, **kw) -> str:
    row = {
        "resource_id": f"{document_id}-v{kw.get('version_no', 1)}-i{seq:04d}", "document_id": document_id,
        "parse_job_id": "job", "resource_type": "image", "resource_path": f"documents/{document_id}/r{seq}.png",
        "content_hash": f"sha256:{seq:02d}" + "ab" * 31, "mime_type": "image/png", "file_size": 10,
        "sheet_name": "09 FAN", "from_cell": f"B{10 + seq}", "to_cell": f"D{11 + seq}", "status": "committed",
        "version_no": 1, "role_cd": "step_photo", "step_no": 6, "step_title": "REACT FAN 조립",
        "surrounding_text": "REACT FAN 조립 체크포인트", "link_confidence": 0.9, "review_status": "auto",
        "in_print_area": True,
    }
    row.update(kw)
    columns = ", ".join(row)
    db.execute_update(f"INSERT INTO tb_spreadsheet_resources ({columns}) VALUES ({', '.join('?' * len(row))})",
                      tuple(row.values()))
    return row["resource_id"]


def _chunk(document_id: str, resource_ids=(), **meta) -> dict:
    metadata = {"document_id": document_id, "sheet_name": "09 FAN", "version_no": 1,
                "processing_engine": "excel_ingest", "resource_ids": list(resource_ids), **meta}
    return {"chunk_id": f"{document_id}-c", "document_id": document_id, "text": "본문", "score": 0.9,
            "metadata": metadata}


def test_candidates_filter_and_order_on_real_rows():
    db = get_database_manager()
    _document(db, "doc-a")
    _document(db, "doc-b")
    step = _resource(db, "doc-a", 1)
    detail = _resource(db, "doc-a", 2, role_cd="detail_view", step_title=None, surrounding_text="확대")
    drawing = _resource(db, "doc-a", 3, role_cd="drawing", step_no=None, step_title=None,
                        surrounding_text="REACT FAN 도면 조립")
    same_image = _resource(db, "doc-a", 4, content_hash=f"sha256:01{'ab' * 31}")   # step과 같은 이미지
    excluded = [
        _resource(db, "doc-a", 5, mime_type="image/emf"),
        _resource(db, "doc-a", 6, role_cd="decoration"),
        _resource(db, "doc-a", 7, review_status="unlinked"),
        _resource(db, "doc-a", 8, status="deleted"),
        _resource(db, "doc-a", 9, version_no=2),                                   # 현재 버전(1)이 아님
    ]
    other_doc = _resource(db, "doc-b", 1)
    analyzed = _resource(db, "doc-a", 10, status="analysis_completed", content_hash="sha256:" + "cd" * 32,
                         role_cd="part_photo", step_no=None, step_title=None, surrounding_text="재생 FAN 부품")

    chunk = _chunk("doc-a", [detail, step, drawing, same_image, *excluded, other_doc, analyzed], step_no=6)
    candidates = collect_image_candidates([chunk], query="REACT FAN 조립 체크포인트")
    ids = [c["resource_id"] for c in candidates]
    # 질의어 일치 수(Step 사진 4 > 도면 3 > 부품 사진 1 > 확대도 0) 순. 같은 이미지(same_image)는 1건, 분석 끝난 사진도 표시
    assert ids == [step, drawing, analyzed, detail]
    assert not set(ids) & {*excluded, other_doc, same_image}
    first = candidates[0]
    assert first["title"] == "09 FAN Step 6 REACT FAN 조립 Step 사진"
    assert (first["context_no"], first["original_filename"], first["from_cell"]) == (1, "doc-a.xlsx", "B11")
    assert len(first["ref"]) == 6 and len({c["ref"] for c in candidates}) == len(candidates)
    assert candidates[2]["title"] == "09 FAN 부품 사진 - 재생 FAN 부품"

    # 다른 문서 청크에 섞인 resource_id는 그 문서 사진이 아니면 쓰지 않는다
    assert collect_image_candidates([_chunk("doc-b", [step])]) == []
    # 문서가 삭제되면 사진도 후보에서 빠진다
    db.execute_update("UPDATE tb_documents SET deleted_at = now() WHERE document_id = 'doc-a'")
    assert collect_image_candidates([chunk]) == []


def test_table_chunk_without_links_uses_rows_in_range():
    db = get_database_manager()
    _document(db, "doc-t")
    inside = _resource(db, "doc-t", 1, role_cd="part_photo", step_no=None, from_cell="C12",
                       surrounding_text="재생 FAN MEC21103")
    _resource(db, "doc-t", 2, role_cd="part_photo", step_no=None, from_cell="C40")             # 범위 밖
    _resource(db, "doc-t", 3, role_cd="part_photo", step_no=None, from_cell="C13", in_print_area=False)
    table = _chunk("doc-t", source_range="10:20", content_type="table_section")
    assert [c["resource_id"] for c in collect_image_candidates([table], query="재생 FAN 품번")] == [inside]
    assert collect_image_candidates([_chunk("doc-t", source_range="50:60")]) == []
    assert collect_image_candidates([_chunk("doc-t", source_range="10:20", processing_engine="docling")]) == []


def test_resource_list_api_fields_match_answer_images(tmp_path):
    """사진 목록 API(출처 패널 "연결된 이미지", UI-05)가 답변 사진과 같은 제목·역할·표시 가능 여부를 준다."""
    from app.repositories.spreadsheet_resource_repository import SpreadsheetResourceRepository
    from app.services.spreadsheet_resource_service import SpreadsheetResourceService

    db = get_database_manager()
    _document(db, "doc-l")
    step = _resource(db, "doc-l", 1)
    part = _resource(db, "doc-l", 2, role_cd="part_photo", step_no=None, step_title=None,
                     surrounding_text="재생 FAN MEC21103", in_print_area=False)
    deco = _resource(db, "doc-l", 3, role_cd="decoration")
    emf = _resource(db, "doc-l", 4, mime_type="image/emf")
    unlinked = _resource(db, "doc-l", 5, review_status="unlinked")
    _resource(db, "doc-l", 6, status="deleted")                                      # 목록에서 빠짐(기존 동작)

    service = SpreadsheetResourceService(tmp_path, SpreadsheetResourceRepository(db), 1024)
    items = {item["resource_id"]: item for item in service.list_document_resources("doc-l")}
    assert set(items) == {step, part, deco, emf, unlinked}
    assert items[step]["title"] == "09 FAN Step 6 REACT FAN 조립 Step 사진"
    assert (items[step]["role"], items[step]["step_no"], items[step]["version_no"]) == ("step_photo", 6, 1)
    assert items[part]["title"] == "09 FAN 부품 사진 - 재생 FAN MEC21103"
    assert items[part]["in_print_area"] is False and items[step]["in_print_area"] is True
    assert {rid for rid, item in items.items() if item["displayable"]} == {step, part}
    # 답변 사진 후보와 같은 제목 규칙
    candidate = collect_image_candidates([_chunk("doc-l", [step])])[0]
    assert candidate["title"] == items[step]["title"]
    assert "resource_path" not in items[step] and items[step]["download_url"] == f"/api/spreadsheet-resources/{step}"


# ── 노드 ──────────────────────────────────────────────────────────────────

def _node_settings(**kw):
    base = dict(answer_images_enabled=True, rag_image_candidates=8, rag_max_images=4, answer_image_auto_attach=True,
                max_citation_results=5, vllm_max_model_len=8192, vllm_max_tokens=2048)
    return SimpleNamespace(**{**base, **kw})


@pytest.mark.asyncio
async def test_collect_node_respects_setting_and_prompt_budget(monkeypatch):
    calls = []
    monkeypatch.setattr(collect_node, "collect_image_candidates",
                        lambda chunks, limit, query: calls.append((limit, query)) or list(CANDIDATES))
    state = {"context_chunks": [_chunk("d1")], "original_query": "FAN 조립", "final_context": "CTX",
             "context_chunk_count": 1, "timing": {}}
    off = await collect_answer_images(state, deps=SimpleNamespace(settings=_node_settings(answer_images_enabled=False)))
    assert off["image_candidates"] == [] and calls == []
    on = await collect_answer_images(state, deps=SimpleNamespace(settings=_node_settings(rag_image_candidates=3)))
    assert [c["ref"] for c in on["image_candidates"]] == ["aaa111", "bbb222"] and calls == [(3, "FAN 조립")]
    # 사진 목록을 붙여 예산을 넘으면 뒤 후보부터 뺀다(후보 줄은 "\n[IMG:"로 시작)
    monkeypatch.setattr(collect_node, "prompt_fits", lambda s, q, context, n: context.count("\n[IMG:") <= 1)
    trimmed = await collect_answer_images(state, deps=SimpleNamespace(settings=_node_settings()))
    assert [c["ref"] for c in trimmed["image_candidates"]] == ["aaa111"]


@pytest.mark.asyncio
async def test_format_citations_returns_cleaned_answer_and_images():
    chunk = {"chunk_id": "c1", "document_id": "d1", "text": "Step 6 REACT FAN 조립", "score": 0.9,
             "metadata": {"original_filename": "NEOCON.xlsx", "step_no": 6, "sheet_name": "FAN"}}
    state = {
        "generated_answer": "REACT FAN을 조립합니다[1][IMG:aaa111][IMG:nope00].",
        "context_chunks": [chunk], "image_candidates": CANDIDATES, "original_query": "FAN 조립",
        "preprocess_result": {}, "citation_limit": 5, "outcome_code": "success", "timing": {},
    }
    result = await format_citations(state, deps=SimpleNamespace(settings=_node_settings()))
    assert result["generated_answer"] == "REACT FAN을 조립합니다[1][IMG:aaa111]."
    assert [(i["resource_id"], i["cited"]) for i in result["answer_images"]] == [("d1-v1-i0001", True)]
    assert result["citations"][0]["citation_id"] == 1

    # 기능을 끄면 태그는 모두 지우고 사진은 없다(기존 응답과 같은 모양)
    off = await format_citations(state, deps=SimpleNamespace(settings=_node_settings(answer_images_enabled=False)))
    assert off["generated_answer"] == "REACT FAN을 조립합니다[1]." and off["answer_images"] == []
    # 근거 없음 답변에는 자동 첨부하지 않는다
    no_context = {**state, "generated_answer": "문서에서 찾지 못했습니다.", "outcome_code": "no_context"}
    result = await format_citations(no_context, deps=SimpleNamespace(settings=_node_settings()))
    assert result["answer_images"] == [] and "generated_answer" not in result
    # 인용이 없는 Step 답변은 Step 사진 1장 자동 첨부
    plain = {**state, "generated_answer": "REACT FAN을 조립합니다[1]."}
    result = await format_citations(plain, deps=SimpleNamespace(settings=_node_settings()))
    assert [(i["ref"], i["cited"]) for i in result["answer_images"]] == [("aaa111", False)]


# ── 스트리밍 SSE·대화 이력 ────────────────────────────────────────────────

def test_stream_sends_images_and_saves_them_in_history(monkeypatch):
    pytest.importorskip("langgraph")
    import app.services.rag_service as rag_service_module
    from app.services.rag_service import RAGService

    images = public_images([{**CANDIDATES[0], "cited": True}])

    class FakeGraph:
        async def astream_events(self, state, version):
            yield {"event": "on_custom_event", "name": "rag_token", "data": {"token": "조립[IMG:aaa111][IMG:x]"}}
            yield {"event": "on_chain_end", "name": "LangGraph", "parent_ids": [], "data": {"output": {
                **state, "generated_answer": "조립[IMG:aaa111]", "citations": [], "answer_images": images}}}

    stored = []

    class FakeRepository:
        def get_session_by_collection(self, user_id, name):
            return None

        def get_query_context(self, session_id):
            return None

        def store_query_context(self, context):
            stored.append(context)

    class FakeRecorder:
        def __init__(self, repository):
            pass

        async def record(self, record, state, **kwargs):
            assert kwargs["answer"] == "조립[IMG:aaa111]"
            return 9

    settings = SimpleNamespace(sqlite_db_path=":memory:", max_query_top_k=20, context_top_k=5,
                               max_citation_results=5, relevance_threshold=0.5)
    monkeypatch.setattr(rag_service_module, "get_settings", lambda: settings)
    monkeypatch.setattr(rag_service_module, "MetadataRepository", lambda *_: FakeRepository())
    monkeypatch.setattr(rag_service_module, "QueryRecorder", FakeRecorder)
    monkeypatch.setattr(rag_service_module, "_resolve_collection_id", lambda *_: 3)
    monkeypatch.setattr(rag_service_module, "CollectionRepository",
                        lambda *_: SimpleNamespace(get_by_id=lambda _id: SimpleNamespace(display_name="NEOCON")))
    service = object.__new__(RAGService)
    service._current_graph = lambda: FakeGraph()

    async def collect():
        return [json.loads(e.removeprefix("data: ").strip())
                async for e in service.query_stream(query="질문", user_id="u1", collection_name="neocon")]

    events = asyncio.run(collect())
    assert [e["type"] for e in events] == ["token", "citations", "images", "meta", "done"]
    assert events[2]["data"] == images
    history = stored[0].conversation_history
    assert history[-1] == {"role": "assistant", "content": "조립[IMG:aaa111]", "citations": [], "images": images}


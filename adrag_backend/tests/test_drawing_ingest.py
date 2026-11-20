"""도면 적재 통합 테스트 — 파이프라인 저장·재시도·새 버전·업로드/결과/검수 API (2026.11.12(sooyeon.choi) 도면 파싱 기능 추가).

DB는 PostgreSQL 테스트 DB. 임베딩·Qdrant는 호출되면 실패하는 가짜로 바꿔 "검색 데이터 저장 0"을 확인한다.
도면은 합성 DXF(tests/drawing_fakes.py), DWG 변환은 가짜 변환기 스크립트.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.ingest.drawing.common import DrawingError
from app.repositories.database import get_database_manager
from app.routes import drawings, ingest
from app.services import drawing_pipeline, ingest_pipeline
from app.services.drawing_pipeline import DrawingIngestPipeline
from app.utils.security import get_current_principal
from drawing_fakes import fake_converter_script, fake_dwg, make_drawing


class _Forbidden:
    """임베딩·검색 데이터 저장소 대역 — 어떤 메서드든 부르면 실패."""

    def __init__(self, name):
        self._name = name

    def __getattr__(self, attr):
        raise AssertionError(f"도면 적재 중 {self._name}.{attr} 호출")


@pytest.fixture
def env(tmp_path, monkeypatch):
    from excel_ingest_fakes import make_ingest_service

    db = get_database_manager()
    for user_id in ("owner", "other"):
        db.execute_update("INSERT INTO tb_users (user_id, user_pwd, role) VALUES (?, 'x', 'user')", (user_id,))
    dxf = make_drawing(tmp_path / "conveyor_module.dxf")
    settings = SimpleNamespace(
        uploaded_files_base_dir=str(tmp_path / "instance" / "data"), drawing_template_dir="",
        md_save_dir=str(tmp_path / "md"), drawing_md_keep_last=5, drawing_render_max_px=800,
        drawing_render_timeout_sec=120, libredwg_bin=str(fake_converter_script(tmp_path / "dwg2dxf", dxf_source=dxf)),
        dwg_convert_timeout_sec=30, dwg_convert_max_mem_mb=2048, drawing_parse_mode="backend",
        drawing_max_upload_mb=1, excel_parse_mode="docling", document_version_replace_enabled=True,
        document_version_restore_enabled=False, resource_delivery="pull", max_chunk_size=800,
    )
    monkeypatch.setattr(drawing_pipeline, "get_settings", lambda: settings)
    monkeypatch.setattr(ingest_pipeline, "get_settings", lambda: settings)
    monkeypatch.setattr(ingest, "get_settings", lambda: settings)
    monkeypatch.setattr(drawings, "get_settings", lambda: settings)

    service = make_ingest_service(tmp_path / "xl_res", tmp_path / "chunk", vector_repo=_Forbidden("vector_repo"))
    service.embedding_client = _Forbidden("embedding_client")
    service.kiwi_bm25_encoder = _Forbidden("kiwi_bm25_encoder")
    service.sparse_encoder = _Forbidden("sparse_encoder")

    queued = []

    async def enqueue(job_id):
        queued.append(job_id)

    principal = dict(user_id="owner", is_admin=False)
    permissions = {"owner": ["documents"], "other": ["documents"]}
    monkeypatch.setattr(ingest, "MetadataRepository", lambda *_: SimpleNamespace(
        get_user_permissions=lambda uid: SimpleNamespace(
            accessible_collections=permissions.get(uid, []), max_security_level="public")
    ))
    monkeypatch.setattr(ingest, "get_ingest_job_manager", lambda: SimpleNamespace(enqueue=enqueue))
    real_service = ingest.IngestService

    def _list_service():
        svc = object.__new__(real_service)
        svc.db, svc.doc_repo = db, ingest.DocumentRepository()
        svc.collection_repo = real_service.list_documents.__globals__["CollectionRepository"]()
        return svc

    monkeypatch.setattr(ingest, "IngestService", _list_service)
    app = FastAPI()
    app.include_router(ingest.router, prefix="/api")
    app.include_router(drawings.router, prefix="/api")
    app.dependency_overrides[get_current_principal] = lambda: principal
    with TestClient(app) as client:
        yield SimpleNamespace(service=service, db=db, client=client, queued=queued, principal=principal,
                              settings=settings, tmp=tmp_path, dxf=dxf)


def _request(path: Path, **extra):
    return {"file_path": str(path), "filename": path.name, "collection_name": "documents",
            "parser_type": "drawing_ingest", "document_type": "drawing", "job_id": None,
            "uploaded_by": "owner", "product_model": path.stem, **extra}


def _run(env, request, **kwargs):
    return asyncio.run(DrawingIngestPipeline().run(env.service, request, **kwargs))


def _one(env, sql, params=()):
    rows = env.db.execute_query(sql, params)
    return dict(rows[0]) if rows else None


# ── 파이프라인 ──────────────────────────────────────────────────────────

def test_dxf_ingest_stores_metadata_images_without_search_data(env):
    result = _run(env, _request(env.dxf))
    document_id = result["document_id"]
    assert result["doc_type"] == "drawing" and result["chunk_count"] == 0
    assert result["drawing"]["part_no"] == "DW-100200" and result["drawing"]["needs_review"] is False

    doc = _one(env, "SELECT doc_type, doc_key, parser_type, chunk_count, total_pages, status, product_model, title "
                    "FROM tb_documents WHERE document_id = ?", (document_id,))
    assert doc["doc_type"] == "drawing" and doc["doc_key"] == "DW-100200" and doc["parser_type"] == "drawing_ingest"
    assert (doc["chunk_count"], doc["total_pages"], doc["status"]) == (0, 1, "ready")
    assert doc["product_model"] == "conveyor_module"  # 모델명은 파일명 기본값 유지
    version = _one(env, "SELECT status, processing_engine, revision_label, summary_json, vector_storage_state, "
                        "embedding_profile_id FROM tb_document_versions WHERE document_id = ?", (document_id,))
    assert version["status"] == "active" and version["processing_engine"] == "drawing_ingest"
    assert version["revision_label"] == "B.2"
    assert version["embedding_profile_id"] is None  # 봉인하지 않음(복원 대상 아님)
    summary = version["summary_json"]
    drawing = (json.loads(summary) if isinstance(summary, str) else summary)["drawing"]
    assert drawing["review"] == {"status": "pending"} and drawing["search_status"] == "not_indexed"
    assert set(drawing["images"]["crops"]) == {"title_block", "bom", "revision"}
    assert _one(env, "SELECT count(*) AS n FROM tb_chunks WHERE document_id = ?", (document_id,))["n"] == 0

    roles = sorted(r[0] for r in env.db.execute_query(
        "SELECT role_cd FROM tb_spreadsheet_resources WHERE document_id = ?", (document_id,)))
    assert roles == ["drawing", "drawing_crop", "drawing_crop", "drawing_crop", "drawing_preview"]
    for (path,) in env.db.execute_query(
            "SELECT resource_path FROM tb_spreadsheet_resources WHERE document_id = ?", (document_id,)):
        assert env.service.resource_service.resolve_relative_path(path).exists()
    assert list((env.tmp / "md" / "drawing" / "DW-100200").glob("*/summary.md"))
    events = [r[0] for r in env.db.execute_query(
        "SELECT operation_type FROM tb_document_version_activations WHERE document_id = ?", (document_id,))]
    assert events == ["upload"]


def test_dwg_ingest_through_converter(env):
    dwg = fake_dwg(env.tmp / "belt_part.dwg")
    result = _run(env, _request(dwg))
    ir_path = env.tmp / "instance" / "data" / "drawing" / result["document_id"] / "v1" / "derived" / "drawing_ir.json"
    ir = json.loads(ir_path.read_text(encoding="utf-8"))
    assert ir["source"]["format"] == "dwg" and ir["source"]["converter"]["name"] == "libredwg"
    assert {w["code"] for w in ir["warnings"]} >= {"W_CONVERTER_WARN"}
    assert result["drawing"]["info_count"] >= 1


def test_convert_failure_leaves_nothing(env, monkeypatch):
    env.settings.libredwg_bin = str(fake_converter_script(env.tmp / "broken", mode="fail", dxf_source=env.dxf))
    with pytest.raises(DrawingError) as exc:
        _run(env, _request(fake_dwg(env.tmp / "bad.dwg")))
    assert exc.value.error_code == "E_CONVERT_FAILED"
    assert _one(env, "SELECT count(*) AS n FROM tb_documents")["n"] == 0
    assert _one(env, "SELECT count(*) AS n FROM tb_spreadsheet_resources")["n"] == 0


def test_store_failure_resumes_without_reconverting(env, monkeypatch):
    calls = {"convert": 0, "store": 0}
    real_convert, real_store = drawing_pipeline.convert_step, drawing_pipeline.DrawingStoreStep._store

    def counting_convert(*a, **k):
        calls["convert"] += 1
        return real_convert(*a, **k)

    def flaky_store(service, context):
        calls["store"] += 1
        if calls["store"] == 1:
            raise RuntimeError("일시 오류")
        return real_store(service, context)

    monkeypatch.setattr(drawing_pipeline, "convert_step", counting_convert)
    monkeypatch.setattr(drawing_pipeline.DrawingStoreStep, "_store", staticmethod(flaky_store))
    checkpoint = str(env.tmp / "job.checkpoint")
    with pytest.raises(RuntimeError):
        _run(env, _request(env.dxf), checkpoint_path=checkpoint)
    assert _one(env, "SELECT count(*) AS n FROM tb_documents")["n"] == 0
    result = _run(env, _request(env.dxf), checkpoint_path=checkpoint, resume_from="drawing_store")
    assert calls == {"convert": 1, "store": 2}
    assert result["drawing"]["part_no"] == "DW-100200"


def test_same_part_no_is_reported_not_replaced(env):
    first = _run(env, _request(env.dxf))
    copy = env.tmp / "copy_of_drawing.dxf"
    copy.write_bytes(env.dxf.read_bytes())
    second = _run(env, _request(copy))
    assert second["document_id"] != first["document_id"]
    same = second["drawing"]["same_part_no_documents"]
    assert [d["document_id"] for d in same] == [first["document_id"]]
    assert _one(env, "SELECT count(*) AS n FROM tb_documents WHERE deleted_at IS NULL")["n"] == 2


def test_job_table_accepts_drawing_steps(env):
    """작업 관리자가 단계마다 tb_ingest_jobs.current_step을 기록한다(제약 ck_tb_ingest_jobs_current_step, 0010)."""
    repo = ingest.IngestJobRepository()
    repo.create("job-drawing-steps", _request(env.dxf), "owner")
    for step in drawing_pipeline.DRAWING_STEPS:
        repo.update("job-drawing-steps", status="running", step=step)
        assert repo.get("job-drawing-steps")["current_step"] == step


# ── API ───────────────────────────────────────────────────────────────

def test_upload_route_off_and_backend(env):
    env.settings.drawing_parse_mode = "off"
    files = {"file": ("a.dwg", b"AC1015" + b"\x00" * 100, "application/octet-stream")}
    assert env.client.post("/api/ingest/upload", files=files).status_code == 400
    assert env.client.get("/api/ingest/options").json()["drawing_ingest_extensions"] == []

    env.settings.drawing_parse_mode = "backend"
    options = env.client.get("/api/ingest/options").json()
    assert options["drawing_ingest_extensions"] == ["dwg", "dxf"] and options["drawing_max_upload_mb"] == 1
    res = env.client.post("/api/ingest/upload", data={"document_type": "law", "parser_type": "pdfplumber"},
                          files={"file": ("a.dwg", b"AC1015" + b"\x00" * 100, "application/octet-stream")})
    assert res.status_code == 202
    job = ingest.IngestJobRepository().get(res.json()["job_id"])
    assert job["request"]["document_type"] == "drawing" and job["request"]["parser_type"] == "drawing_ingest"
    bad = env.client.post("/api/ingest/upload", files={"file": ("x.dwg", b"plain text", "text/plain")})
    assert bad.status_code == 400 and "E_UNSUPPORTED_FORMAT" in bad.json()["detail"]
    big = env.client.post("/api/ingest/upload", files={"file": ("big.dwg", b"AC1015" + b"\x00" * (1024 * 1024 + 10),
                                                                 "application/octet-stream")})
    assert big.status_code == 413
    assert len(env.queued) == 1


def test_document_list_result_and_review(env):
    document_id = _run(env, _request(env.dxf))["document_id"]
    docs = {d["document_id"]: d for d in env.client.get("/api/ingest/documents").json()["documents"]}
    assert docs[document_id]["drawing"] == {
        "part_no": "DW-100200", "part_name": "ASSY_SAMPLE MODULE", "rev": "B.2", "sheet_size": "A3",
        "warn_count": 1, "needs_review": False, "review_status": "pending", "search_status": "not_indexed",
    }

    result = env.client.get(f"/api/ingest/documents/{document_id}/versions/1/drawing-result").json()
    assert result["can_review"] is True and result["title_block"]["fields"]["part_no"] == "DW-100200"
    assert [t["kind"] for t in result["tables"]] == ["bom", "revision"]
    assert result["images"]["full"] and result["processing"]["stats"]["text_count"] > 0

    env.principal.update(user_id="other", is_admin=False)  # 다른 사용자: 보기만
    assert env.client.get(f"/api/ingest/documents/{document_id}/versions/1/drawing-result").json()["can_review"] is False
    assert env.client.post(f"/api/ingest/documents/{document_id}/versions/1/drawing-review").status_code == 403

    env.principal.update(user_id="owner")
    done = env.client.post(f"/api/ingest/documents/{document_id}/versions/1/drawing-review").json()
    assert done["review"]["status"] == "reviewed" and done["review"]["reviewer"] == "owner"
    docs = {d["document_id"]: d for d in env.client.get("/api/ingest/documents").json()["documents"]}
    assert docs[document_id]["drawing"]["review_status"] == "reviewed"
    assert env.client.delete(f"/api/ingest/documents/{document_id}/versions/1/drawing-review").json()["review"]["status"] == "pending"
    messages = [r[0] for r in env.db.execute_query(
        "SELECT event_message FROM tb_document_events WHERE document_id = ? AND event_type = 'update' ORDER BY event_id",
        (document_id,))]
    assert messages == ["도면 검수 완료", "도면 검수 취소"]

    env.principal.update(user_id="nobody")  # 열람 권한 없음: 존재 숨김
    assert env.client.get(f"/api/ingest/documents/{document_id}/versions/1/drawing-result").status_code == 404


def test_review_missing_fields_requires_confirm(env):
    path = make_drawing(env.tmp / "no_rev.dxf", title_overrides={"REVISION": None})
    document_id = _run(env, _request(path))["document_id"]
    url = f"/api/ingest/documents/{document_id}/versions/1/drawing-review"
    res = env.client.post(url)
    assert res.status_code == 409 and res.json()["detail"]["missing_fields"] == ["revision"]
    ok = env.client.post(url, json={"confirm_missing": True})
    assert ok.status_code == 200 and ok.json()["review"]["status"] == "reviewed"


def test_new_version_and_restore_blocked(env):
    document_id = _run(env, _request(env.dxf))["document_id"]
    wrong = env.client.post(f"/api/ingest/documents/{document_id}/versions",
                            files={"file": ("sop.xlsx", b"PK\x03\x04", "application/octet-stream")})
    assert wrong.status_code == 400
    same = env.client.post(f"/api/ingest/documents/{document_id}/versions",
                           files={"file": ("same.dxf", env.dxf.read_bytes(), "application/octet-stream")})
    assert same.status_code == 409  # 현재 버전과 같은 파일(기존 규칙)
    rev_c = make_drawing(env.tmp / "conveyor_rev_c.dxf", title_overrides={"REVISION": "C.1"})
    res = env.client.post(f"/api/ingest/documents/{document_id}/versions",
                          files={"file": (rev_c.name, rev_c.read_bytes(), "application/octet-stream")})
    assert res.status_code == 202, res.text
    job = ingest.IngestJobRepository().get(res.json()["job_id"])
    assert job["request"]["document_type"] == "drawing"
    asyncio.run(DrawingIngestPipeline().run(env.service, {**job["request"], "job_id": res.json()["job_id"]}))
    versions = [(r[0], r[1]) for r in env.db.execute_query(
        "SELECT version_no, status FROM tb_document_versions WHERE document_id = ? ORDER BY version_no", (document_id,))]
    assert versions == [(1, "retired"), (2, "active")]
    assert _one(env, "SELECT pending_job_id FROM tb_documents WHERE document_id = ?", (document_id,))["pending_job_id"] is None

    history = env.client.get(f"/api/ingest/documents/{document_id}/versions").json()
    assert history["restore_supported"] is False
    old = next(v for v in history["versions"] if v["version_no"] == 1)
    assert old["can_restore"] is False and old["restore_block_code"] == "DRAWING_NOT_SUPPORTED"

    pdf_doc = env.client.post("/api/ingest/documents/does-not-matter/versions",
                              files={"file": ("x.dwg", b"AC1015", "application/octet-stream")})
    assert pdf_doc.status_code == 404

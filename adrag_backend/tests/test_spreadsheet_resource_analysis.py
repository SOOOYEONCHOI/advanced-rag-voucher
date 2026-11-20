"""단계 8 resource marker와 OCR/VLM 분석 연결 계약 테스트."""

# 2026.08.27(sooyeon.choi) 추가 - REQ-MEDIA-004/005 회귀 테스트
from io import BytesIO
import hashlib
import json

import pytest
from fastapi import HTTPException
from starlette.datastructures import Headers, UploadFile

from app.parsers.chunkers.spreadsheet import SpreadsheetChunker
from app.parsers.config import ChunkingConfig
from app.parsers.models import LCDocument
from app.repositories.database import DatabaseManager
from app.repositories.spreadsheet_resource_repository import SpreadsheetResourceRepository
from app.services import spreadsheet_resource_service as resource_service_module
from app.services.spreadsheet_resource_service import (
    ResourceConflictError,
    SpreadsheetResourceService,
)


IMAGE_BYTES = b"image-bytes"


def _ensure_document(db, document_id="doc-1"):
    """2026.10.01 추가 - Phase 2: placement는 문서·버전 행을 FK로 참조한다."""
    collection_id = db.execute_query(
        "INSERT INTO tb_collections (display_name, qdrant_name) VALUES ('parts', 'parts') RETURNING collection_id"
    )[0][0]
    db.execute_update(
        "INSERT INTO tb_documents (document_id, collection_id, source_path, status) VALUES (?,?,?,'ready')",
        (document_id, collection_id, f"data/{document_id}.xlsx"),
    )
    db.execute_update(
        "INSERT INTO tb_document_versions (document_id, version_no, source_path) VALUES (?, 1, 'p')", (document_id,)  # 2026.10.16 수정 - 0003 컬럼명
    )


def _service(tmp_path):
    DatabaseManager._instance = None
    db = DatabaseManager()
    _ensure_document(db)
    service = SpreadsheetResourceService(
        tmp_path / "storage",
        SpreadsheetResourceRepository(db=db),
        max_upload_bytes=1024,
    )
    return service, db


def _close(db):
    db.close_all_connections()
    DatabaseManager._instance = None
    resource_service_module._ACTIVE_PARSE_JOBS.clear()


def _upload(content=IMAGE_BYTES):
    return UploadFile(
        file=BytesIO(content),
        filename="untrusted-name.png",
        headers=Headers({"content-type": "image/png"}),
    )


def _metadata(resource_id="resource-1", resource_type="image"):
    return {
        "resource_id": resource_id,
        "document_id": "doc-1",
        "resource_type": resource_type,
        "content_hash": "sha256:" + hashlib.sha256(IMAGE_BYTES).hexdigest(),
        "mime_type": "image/png",
        "sheet_id": "sheet-1",
        "sheet_name": "부품",
        "from_cell": "D2",
        "to_cell": "D2",
        "linked_block_id": "sheet-1:block-1",
        "linked_record_ids": ["sheet-1:row-2"],
        "surrounding_range": "A2:E2",
        "surrounding_text": "품명 팬 품번 nc-fan-01",
    }


async def _committed_resource(service, resource_id="resource-1", resource_type="image"):
    await service.stage_upload(
        _upload(), parse_job_id="job-1", metadata=_metadata(resource_id, resource_type)
    )
    service.commit_parse_job("job-1", "doc-1")
    return service.repository.get(resource_id)


# ── REQ-MEDIA-004 resource marker ─────────────────────────────────────────

def _sheet_document(resource_ids):
    return LCDocument(
        page_content="",
        metadata={
            "sheet_id": "sheet-1",
            "sheet_index": 1,
            "sheet_name": "부품",
            "schema_version": "1.0",
            "structured_ir": {"blocks": [{
                "block_id": "sheet-1:block-1",
                "block_index": 1,
                "block_type": "record_table",
                "source_range": "A1:B2",
                "headers": ["품명", "사진"],
                "resource_ids": resource_ids,
                "records": [{
                    "record_id": "sheet-1:row-2",
                    "source_range": "A2:B2",
                    "row_start": 2,
                    "row_end": 2,
                    "values": ["모터", ""],
                    "resource_ids": resource_ids,
                }],
            }]},
        },
    )


def test_marker_appears_in_display_markdown_only():
    config = ChunkingConfig(spreadsheet_summary_chunks=False)
    chunk = SpreadsheetChunker(config).split_documents([_sheet_document(["resource-1"])])[0]

    assert "⟦RESOURCE:resource-1⟧" in chunk.metadata["display_markdown"]
    assert "resource-1" not in chunk.page_content
    assert "RESOURCE:" not in chunk.page_content
    assert chunk.metadata["resource_ids"] == ["resource-1"]


def test_chunk_without_resources_has_no_marker():
    config = ChunkingConfig(spreadsheet_summary_chunks=False)
    chunk = SpreadsheetChunker(config).split_documents([_sheet_document([])])[0]

    assert "⟦RESOURCE:" not in chunk.metadata["display_markdown"]


# ── REQ-MEDIA-005 분석 연결 계약 ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_image_resource_commits_as_analysis_pending(tmp_path):
    service, db = _service(tmp_path)
    try:
        image = await _committed_resource(service, "resource-image", "image")
        await service.stage_upload(
            _upload(), parse_job_id="job-2", metadata=_metadata("resource-chart", "chart")
        )
        service.commit_parse_job("job-2", "doc-1")
        chart = service.repository.get("resource-chart")

        # 이미지에는 텍스트가 없으므로 분석 대기, 차트는 IR에 이미 구조가 남아 committed
        assert image["status"] == "analysis_pending"
        assert chart["status"] == "committed"
    finally:
        _close(db)


@pytest.mark.asyncio
async def test_analysis_versions_are_preserved_without_touching_original(tmp_path):
    service, db = _service(tmp_path)
    try:
        resource = await _committed_resource(service)
        original = service.resolve_relative_path(resource["resource_path"])

        first = service.register_analysis(
            "resource-1",
            {
                "method": "ocr",
                "model": "fake-ocr",
                "model_version": "1.0",
                "prompt_version": "p1",
                "pipeline_version": "2026.08",
                "status": "completed",
                "text": "NC-FAN-01",
                "confidence": 0.95,
            },
            result_document={"blocks": [{"text": "NC-FAN-01"}]},
        )
        second = service.register_analysis(
            "resource-1",
            {"method": "vlm", "model": "fake-vlm", "status": "completed", "text": "냉각팬 사진"},
            result_document={"caption": "냉각팬 사진"},
        )

        assert (first["analysis_version"], second["analysis_version"]) == (1, 2)
        assert [item["method"] for item in service.list_analyses("resource-1")] == ["ocr", "vlm"]
        assert service.read_analysis_result("resource-1", 1) == {"blocks": [{"text": "NC-FAN-01"}]}
        assert service.read_analysis_result("resource-1", 2) == {"caption": "냉각팬 사진"}
        # 원본 파일과 경로는 그대로 유지된다.
        assert original.read_bytes() == IMAGE_BYTES
        assert service.repository.get("resource-1")["resource_path"] == resource["resource_path"]
        assert service.repository.get("resource-1")["content_hash"] == resource["content_hash"]
    finally:
        _close(db)


@pytest.mark.asyncio
async def test_analysis_status_drives_resource_status(tmp_path):
    service, db = _service(tmp_path)
    try:
        await _committed_resource(service)

        service.register_analysis("resource-1", {"method": "vlm", "status": "processing"})
        assert service.repository.get("resource-1")["status"] == "analysis_processing"

        service.register_analysis("resource-1", {"method": "vlm", "status": "failed"})
        assert service.repository.get("resource-1")["status"] == "analysis_failed"

        service.register_analysis("resource-1", {"method": "vlm", "status": "completed"})
        assert service.repository.get("resource-1")["status"] == "analysis_completed"
    finally:
        _close(db)


@pytest.mark.asyncio
async def test_analysis_rejects_invalid_input_and_duplicate_version(tmp_path):
    service, db = _service(tmp_path)
    try:
        await _committed_resource(service)

        with pytest.raises(ValueError, match="method"):
            service.register_analysis("resource-1", {"method": "guess"})
        with pytest.raises(ValueError, match="status"):
            service.register_analysis("resource-1", {"method": "ocr", "status": "done"})
        with pytest.raises(ValueError, match="confidence"):
            service.register_analysis("resource-1", {"method": "ocr", "confidence": 1.5})
        with pytest.raises(FileNotFoundError):
            service.register_analysis("missing-resource", {"method": "ocr"})

        service.register_analysis(
            "resource-1", {"method": "ocr", "analysis_version": 1}, result_document={"a": 1}
        )
        with pytest.raises(ResourceConflictError):
            service.register_analysis(
                "resource-1", {"method": "ocr", "analysis_version": 1}, result_document={"a": 2}
            )
    finally:
        _close(db)


@pytest.mark.skip(reason="2026.10.16 - 옛 계보(10-01) 설계 검증: 해시 공유 assets/ 저장·삭제 시 배치 행 삭제. Phase 2 결정 P2-5(공유 저장 안 함, 원본은 documents/{doc}/resources/…)·삭제는 status='deleted'와 다름")
@pytest.mark.asyncio
async def test_document_deletion_removes_analyses_and_files(tmp_path):
    service, db = _service(tmp_path)
    try:
        await _committed_resource(service)
        service.register_analysis(
            "resource-1", {"method": "ocr", "status": "completed"}, result_document={"text": "x"}
        )
        analyses_dir = service.resolve_relative_path(
            "documents/doc-1/resources/resource-1/analyses"
        )
        assert analyses_dir.exists()

        service.delete_document_resources("doc-1")

        assert not analyses_dir.exists()
        assert service.list_analyses("resource-1") == []
        # 2026.10.01 수정 - placement 행은 삭제 시 지운다(공유 asset은 유지).
        assert service.repository.get("resource-1") is None
    finally:
        _close(db)


# ── API 계약 ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_internal_analysis_api_requires_key_and_returns_version(monkeypatch, tmp_path):
    from app.routes import spreadsheet_resources as resource_routes

    service, db = _service(tmp_path)
    await _committed_resource(service)
    monkeypatch.setattr(resource_routes, "_service", lambda: service)
    monkeypatch.setattr(
        resource_routes,
        "get_settings",
        lambda: type("Settings", (), {"resource_internal_api_key": "secret"})(),
    )
    payload = {
        "method": "vlm",
        "model": "mock-vlm",
        "status": "completed",
        "text": "냉각팬 조립 상태",
        "confidence": 0.88,
        "result": {"caption": "냉각팬 조립 상태"},
    }
    try:
        with pytest.raises(HTTPException) as unauthorized:
            await resource_routes.register_resource_analysis(
                "resource-1", payload=payload, x_internal_api_key="wrong"
            )
        assert unauthorized.value.status_code == 401

        response = await resource_routes.register_resource_analysis(
            "resource-1", payload=payload, x_internal_api_key="secret"
        )
        analysis = response["analysis"]
        assert analysis["analysis_version"] == 1
        assert analysis["method"] == "vlm"
        assert analysis["result_path"] == (
            "documents/doc-1/resources/resource-1/analyses/1/result.json"
        )
        stored = service.resolve_relative_path(analysis["result_path"])
        assert json.loads(stored.read_text(encoding="utf-8")) == {"caption": "냉각팬 조립 상태"}

        with pytest.raises(HTTPException) as missing:
            await resource_routes.register_resource_analysis(
                "resource-none", payload=payload, x_internal_api_key="secret"
            )
        assert missing.value.status_code == 404
    finally:
        _close(db)


@pytest.mark.asyncio
async def test_analysis_listing_applies_document_permission(monkeypatch, tmp_path):
    from app.routes import spreadsheet_resources as resource_routes

    service, db = _service(tmp_path)
    await _committed_resource(service)
    service.register_analysis(
        "resource-1", {"method": "ocr", "status": "completed", "text": "NC-FAN-01"}
    )
    monkeypatch.setattr(resource_routes, "_service", lambda: service)
    monkeypatch.setattr(
        resource_routes,
        "get_settings",
        lambda: type("Settings", (), {"instance_dir": str(tmp_path)})(),
    )
    monkeypatch.setattr(
        resource_routes,
        "get_database_manager",
        lambda *_: type("DB", (), {"execute_query": lambda self, query, params: [{
            "security_level": "public", "source_collection": "parts"
        }]})(),
    )
    monkeypatch.setattr(
        resource_routes,
        "MetadataRepository",
        lambda *_: type("Metadata", (), {"get_user_permissions": lambda self, user_id: None})(),
    )
    try:
        with pytest.raises(HTTPException) as denied:
            await resource_routes.list_resource_analyses(
                "resource-1", principal={"user_id": "user-1", "is_admin": False}
            )
        assert denied.value.status_code == 403

        response = await resource_routes.list_resource_analyses(
            "resource-1", principal={"user_id": "admin", "is_admin": True}
        )
        assert response["total"] == 1
        assert response["resource_status"] == "analysis_completed"
        assert response["analyses"][0]["text"] == "NC-FAN-01"
        # 서버 절대 경로는 응답에 노출하지 않는다.
        assert str(service.root) not in json.dumps(response, ensure_ascii=False)
    finally:
        _close(db)

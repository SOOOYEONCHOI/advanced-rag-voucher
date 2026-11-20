"""Spreadsheet resource 저장, commit, rollback 계약 테스트."""

# 2026.08.27(sooyeon.choi) 추가 - 단계 6 resource 회귀 테스트
from io import BytesIO
import hashlib
import json
import os
import sys
import types
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from starlette.datastructures import Headers, UploadFile

from app.repositories.database import DatabaseManager
from app.repositories.spreadsheet_resource_repository import SpreadsheetResourceRepository
from app.services import spreadsheet_resource_service as resource_service_module
from app.services.spreadsheet_resource_service import ResourceConflictError, SpreadsheetResourceService


def _ensure_document(db, document_id="doc-1"):
    """2026.10.01 추가 - Phase 2: placement는 문서·버전 행을 FK로 참조하므로 commit 전에 만든다."""
    db.execute_update(
        "INSERT INTO tb_collections (display_name, qdrant_name) VALUES ('parts', 'parts') "
        "ON CONFLICT DO NOTHING"
    )
    collection_id = db.execute_query("SELECT collection_id FROM tb_collections WHERE qdrant_name='parts'")[0][0]
    db.execute_update(
        "INSERT INTO tb_documents (document_id, collection_id, source_path, status) VALUES (?,?,?,'ready') "
        "ON CONFLICT DO NOTHING",
        (document_id, collection_id, f"data/{document_id}.xlsx"),
    )
    # 2026.10.16 수정 - Phase 2: 확정 리소스는 문서 행만 참조한다(버전 행은 파이프라인이 만든다)


def _service(tmp_path):
    DatabaseManager._instance = None
    db = DatabaseManager()
    _ensure_document(db)
    return SpreadsheetResourceService(
        tmp_path / "storage",
        SpreadsheetResourceRepository(db=db),
        max_upload_bytes=1024,
    ), db


def _close(db):
    db.close_all_connections()
    DatabaseManager._instance = None
    # 2026.08.27(sooyeon.choi) 추가 - 프로세스 전역 실행 중 job 레지스트리를 테스트 간 초기화
    resource_service_module._ACTIVE_PARSE_JOBS.clear()


def _upload(content=b"image-bytes", mime_type="image/png"):
    return UploadFile(
        file=BytesIO(content),
        filename="untrusted-name.png",
        headers=Headers({"content-type": mime_type}),
    )


def _metadata(content=b"image-bytes", resource_id="resource-1"):
    return {
        "resource_id": resource_id,
        "document_id": "doc-1",
        "resource_type": "image",
        "content_hash": "sha256:" + hashlib.sha256(content).hexdigest(),
        "mime_type": "image/png",
        "sheet_id": "sheet-1",
        "sheet_name": "부품",
        "from_cell": "D2",
        "to_cell": "D4",
        "linked_block_id": "sheet-1:block-1",
        "linked_record_ids": ["sheet-1:row-2"],
        "surrounding_range": "A1:F5",
        "surrounding_text": "모터 사진",
    }


@pytest.mark.skip(reason="2026.10.16 - 옛 계보(10-01) 설계 검증: 해시 공유 assets/ 저장·삭제 시 배치 행 삭제. Phase 2 결정 P2-5(공유 저장 안 함, 원본은 documents/{doc}/resources/…)·삭제는 status='deleted'와 다름")
@pytest.mark.asyncio
async def test_stage_commit_and_lookup_use_relative_paths(tmp_path):
    service, db = _service(tmp_path)
    try:
        staged = await service.stage_upload(
            _upload(), parse_job_id="parse-job-1", metadata=_metadata()
        )
        assert staged["status"] == "staging"
        assert not os.path.isabs(staged["resource_path"])
        assert staged["linked_record_ids"] == ["sheet-1:row-2"]

        committed = service.commit_parse_job("parse-job-1", "doc-1")[0]
        # 2026.08.27(sooyeon.choi) 수정 - 단계 8 이미지 resource는 분석 대기 상태로 commit된다.
        assert committed["status"] == "analysis_pending"
        # 2026.10.01 수정 - Phase 2 F04: 파일은 해시 기준 공유 asset 위치에 둔다.
        digest = hashlib.sha256(b"image-bytes").hexdigest()
        assert committed["resource_path"] == f"assets/{digest[:2]}/{digest}.png"
        metadata, path = service.resolve_resource("resource-1")
        assert metadata["sheet_name"] == "부품"
        assert path.read_bytes() == b"image-bytes"
        assert not service.resolve_relative_path("staging/parse-job-1").exists()
    finally:
        _close(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("extension", ["bmp", "emf", "wmf"])
async def test_parser_image_formats_preserve_original_on_commit(tmp_path, extension):
    service, db = _service(tmp_path)
    try:
        mime_type = f"image/{extension}"
        metadata = {**_metadata(), "mime_type": mime_type}
        await service.stage_upload(
            _upload(mime_type=mime_type), parse_job_id="parse-job-1", metadata=metadata
        )
        service.commit_parse_job("parse-job-1", "doc-1")
        stored, path = service.resolve_resource("resource-1")
        assert stored["mime_type"] == mime_type
        assert path.suffix == f".{extension}"
        assert path.read_bytes() == b"image-bytes"
    finally:
        _close(db)


@pytest.mark.asyncio
async def test_upload_is_idempotent_but_rejects_different_hash(tmp_path):
    service, db = _service(tmp_path)
    try:
        first = await service.stage_upload(_upload(), parse_job_id="parse-job-1", metadata=_metadata())
        second = await service.stage_upload(_upload(), parse_job_id="parse-job-1", metadata=_metadata())
        assert second["resource_path"] == first["resource_path"]

        with pytest.raises(ResourceConflictError):
            await service.stage_upload(
                _upload(b"different"),
                parse_job_id="parse-job-1",
                metadata=_metadata(b"different"),
            )
    finally:
        _close(db)


@pytest.mark.asyncio
async def test_hash_mime_size_and_path_traversal_are_rejected(tmp_path):
    service, db = _service(tmp_path)
    try:
        wrong_hash = _metadata()
        wrong_hash["content_hash"] = "sha256:" + "0" * 64
        with pytest.raises(ValueError, match="hash"):
            await service.stage_upload(_upload(), parse_job_id="parse-job-1", metadata=wrong_hash)
        with pytest.raises(ValueError, match="MIME"):
            await service.stage_upload(
                _upload(mime_type="text/plain"), parse_job_id="parse-job-1", metadata=_metadata()
            )
        with pytest.raises(ValueError, match="path traversal"):
            service.resolve_relative_path("../outside.png")
        with pytest.raises(ValueError, match="최대 업로드"):
            await service.stage_upload(
                _upload(b"x" * 2048), parse_job_id="parse-job-2", metadata=_metadata(b"x" * 2048, "resource-2")
            )
    finally:
        _close(db)


@pytest.mark.skip(reason="2026.10.16 - 옛 계보(10-01) 설계 검증: 해시 공유 assets/ 저장·삭제 시 배치 행 삭제. Phase 2 결정 P2-5(공유 저장 안 함, 원본은 documents/{doc}/resources/…)·삭제는 status='deleted'와 다름")
@pytest.mark.asyncio
async def test_rollback_delete_and_ttl_cleanup_remove_only_target(tmp_path):
    service, db = _service(tmp_path)
    try:
        await service.stage_upload(_upload(), parse_job_id="old-job", metadata=_metadata())
        old_dir = service.resolve_relative_path("staging/old-job")
        old_time = (datetime.now() - timedelta(hours=48)).timestamp()
        os.utime(old_dir, (old_time, old_time))
        assert service.cleanup_expired_staging(24, active_parse_job_ids={"active-job"}) == 1
        assert service.repository.get("resource-1") is None

        await service.stage_upload(
            _upload(), parse_job_id="parse-job-2", metadata=_metadata(resource_id="resource-2")
        )
        service.commit_parse_job("parse-job-2", "doc-1")
        service.delete_document_resources("doc-1")
        # 2026.10.01 수정 - placement는 삭제 시 행을 지운다(asset 파일은 공유라 유지 → cleanup이 정리).
        assert service.repository.get("resource-2") is None
        with pytest.raises(FileNotFoundError):
            service.resolve_resource("resource-2")
    finally:
        _close(db)


@pytest.mark.asyncio
async def test_internal_upload_api_auth_hash_and_metadata(monkeypatch, tmp_path):
    # CI 경량 환경에 python-multipart runtime이 없어 FastAPI의 import 확인만 충족한다.
    multipart = types.ModuleType("multipart")
    multipart.__version__ = "0.0.9"
    multipart_parser = types.ModuleType("multipart.multipart")
    multipart_parser.parse_options_header = lambda value: (value, {})
    monkeypatch.setitem(sys.modules, "multipart", multipart)
    monkeypatch.setitem(sys.modules, "multipart.multipart", multipart_parser)
    from app.routes import spreadsheet_resources as resource_routes

    service, db = _service(tmp_path)
    monkeypatch.setattr(resource_routes, "_service", lambda: service)
    monkeypatch.setattr(
        resource_routes,
        "get_settings",
        lambda: type("Settings", (), {"resource_internal_api_key": "secret"})(),
    )
    content = b"api-image"
    data = {
        **_metadata(content),
        "linked_record_ids": '["sheet-1:row-2"]',
    }
    try:
        with pytest.raises(HTTPException) as unauthorized:
            await resource_routes.upload_resource(
                parse_job_id="parse-job-api",
                file=_upload(content),
                x_internal_api_key="wrong",
                **data,
            )
        assert unauthorized.value.status_code == 401

        response = await resource_routes.upload_resource(
            parse_job_id="parse-job-api",
            file=_upload(content),
            x_internal_api_key="secret",
            **data,
        )
        assert response["resource"]["parse_job_id"] == "parse-job-api"
        assert response["resource"]["sheet_name"] == "부품"

        with pytest.raises(HTTPException) as invalid_id:
            await resource_routes.upload_resource(
                parse_job_id="parse-job-api",
                file=_upload(content),
                x_internal_api_key="secret",
                **{**data, "resource_id": "../escape"},
            )
        assert invalid_id.value.status_code == 400
    finally:
        _close(db)


@pytest.mark.asyncio
async def test_download_applies_document_permission_and_hides_absolute_path(monkeypatch, tmp_path):
    from app.routes import spreadsheet_resources as resource_routes

    service, db = _service(tmp_path)
    await service.stage_upload(
        _upload(), parse_job_id="download-job", metadata=_metadata(resource_id="resource-download")
    )
    service.commit_parse_job("download-job", "doc-1")
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
            await resource_routes.download_resource(
                "resource-download", principal={"user_id": "user-1", "is_admin": False}
            )
        assert denied.value.status_code == 403

        response = await resource_routes.download_resource(
            "resource-download", principal={"user_id": "admin", "is_admin": True}
        )
        assert response.filename == "resource-download.png"
        assert str(service.root) not in response.headers.get("content-disposition", "")
    finally:
        _close(db)


# 2026.08.27(sooyeon.choi) 추가 - 실행 중 job staging은 TTL cleanup에서 제외한다.
@pytest.mark.asyncio
async def test_cleanup_keeps_running_job_and_removes_dead_job(tmp_path):
    service, db = _service(tmp_path)
    try:
        await service.stage_upload(_upload(), parse_job_id="running-job", metadata=_metadata())
        staging_dir = service.resolve_relative_path("staging/running-job")
        old_time = (datetime.now() - timedelta(hours=48)).timestamp()
        os.utime(staging_dir, (old_time, old_time))

        assert "running-job" in SpreadsheetResourceService.active_parse_job_ids()
        assert service.cleanup_expired_staging(24) == 0
        assert staging_dir.exists()
        # 2026.10.16 수정 - Phase 2(P2-13): staging 행은 staging 테이블에서 조회
        assert service.repository.get_staging("resource-1")["status"] == "staging"

        # 등록 후 TTL을 넘긴 job은 죽은 job으로 보고 정리 대상에 포함한다.
        resource_service_module._ACTIVE_PARSE_JOBS["running-job"] = (
            datetime.now(timezone.utc) - timedelta(hours=48)
        )
        assert service.cleanup_expired_staging(24) == 1
        assert not staging_dir.exists()
        assert service.repository.get("resource-1") is None
    finally:
        _close(db)


# 2026.08.27(sooyeon.choi) 추가 - commit/rollback 시 실행 중 job 표시를 해제한다.
@pytest.mark.asyncio
async def test_commit_and_rollback_release_active_job(tmp_path):
    service, db = _service(tmp_path)
    try:
        await service.stage_upload(_upload(), parse_job_id="job-commit", metadata=_metadata())
        service.commit_parse_job("job-commit", "doc-1")
        assert "job-commit" not in SpreadsheetResourceService.active_parse_job_ids()

        await service.stage_upload(
            _upload(), parse_job_id="job-rollback", metadata=_metadata(resource_id="resource-2")
        )
        service.rollback_parse_job("job-rollback")
        assert "job-rollback" not in SpreadsheetResourceService.active_parse_job_ids()
        assert service.repository.get("resource-2") is None
    finally:
        _close(db)


# 2026.08.27(sooyeon.choi) 추가 - 같은 parse job에 다른 document ID를 섞으면 conflict로 거부한다.
@pytest.mark.asyncio
async def test_upload_rejects_mixed_document_id_in_one_job(tmp_path):
    service, db = _service(tmp_path)
    try:
        await service.stage_upload(_upload(), parse_job_id="mixed-job", metadata=_metadata())
        other = {**_metadata(resource_id="resource-2"), "document_id": "doc-2"}
        with pytest.raises(ResourceConflictError):
            await service.stage_upload(_upload(), parse_job_id="mixed-job", metadata=other)
    finally:
        _close(db)


# 2026.08.27(sooyeon.choi) 추가 - 삭제 실패는 재시도 가능한 상태로 남고 cleanup이 재처리한다.
@pytest.mark.skip(reason="2026.10.16 - 옛 계보(10-01) 설계 검증: 해시 공유 assets/ 저장·삭제 시 배치 행 삭제. Phase 2 결정 P2-5(공유 저장 안 함, 원본은 documents/{doc}/resources/…)·삭제는 status='deleted'와 다름")
@pytest.mark.asyncio
async def test_delete_failure_stays_retryable_until_cleanup(monkeypatch, tmp_path):
    service, db = _service(tmp_path)
    try:
        await service.stage_upload(_upload(), parse_job_id="delete-job", metadata=_metadata())
        service.commit_parse_job("delete-job", "doc-1")
        # 2026.10.01 수정 - 문서 폴더에는 분석 결과만 남는다(원본은 공유 asset).
        document_root = service.resolve_relative_path("documents/doc-1")
        (document_root / "resources" / "resource-1" / "analyses").mkdir(parents=True)

        def _fail(*args, **kwargs):
            raise OSError("파일이 사용 중입니다.")

        monkeypatch.setattr(resource_service_module.shutil, "rmtree", _fail)
        assert service.delete_document_resources("doc-1") == "pending"
        # 삭제 실패 시 placement를 지우지 않아 재시도 대상으로 남는다.
        assert service.repository.get("resource-1")["status"] == "analysis_pending"
        assert document_root.exists()

        monkeypatch.undo()
        # 문서가 삭제(soft delete)된 뒤 cleanup이 남은 placement를 재처리한다.
        db.execute_update("UPDATE tb_documents SET deleted_at = now() WHERE document_id = 'doc-1'")
        # 고아 디렉터리도 같은 cleanup에서 함께 제거한다.
        orphan = service.resolve_relative_path("documents/ghost-doc/resources")
        orphan.mkdir(parents=True)
        result = service.retry_pending_deletions()
        assert result == {"retried_documents": 1, "removed_orphan_dirs": 1}
        assert not document_root.exists()
        assert not orphan.parent.exists()
        assert service.repository.get("resource-1") is None
    finally:
        _close(db)


# 2026.08.27(sooyeon.choi) 추가 - document resource 목록 조회 권한과 경로 비노출 검증
@pytest.mark.asyncio
async def test_list_api_applies_permission_and_hides_absolute_path(monkeypatch, tmp_path):
    from app.routes import spreadsheet_resources as resource_routes

    service, db = _service(tmp_path)
    await service.stage_upload(_upload(), parse_job_id="list-job", metadata=_metadata())
    service.commit_parse_job("list-job", "doc-1")
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
            await resource_routes.list_document_resources(
                "doc-1", principal={"user_id": "user-1", "is_admin": False}
            )
        assert denied.value.status_code == 403

        response = await resource_routes.list_document_resources(
            "doc-1", principal={"user_id": "admin", "is_admin": True}
        )
        assert response["total"] == 1
        item = response["resources"][0]
        assert item["download_url"] == "/api/spreadsheet-resources/resource-1"
        assert item["sheet_name"] == "부품"
        assert item["linked_record_ids"] == ["sheet-1:row-2"]
        assert "resource_path" not in item
        assert str(service.root) not in json.dumps(response, ensure_ascii=False)
    finally:
        _close(db)


# 2026.08.27(sooyeon.choi) 추가 - 서로 다른 서버를 모사한 HTTP multipart 업로드 통합 테스트
@pytest.mark.asyncio
async def test_internal_upload_http_integration(monkeypatch, tmp_path):
    pytest.importorskip("multipart", reason="python-multipart 미설치 환경에서는 건너뛴다.")
    import httpx
    from fastapi import FastAPI

    from app.routes import spreadsheet_resources as resource_routes

    service, db = _service(tmp_path)
    monkeypatch.setattr(resource_routes, "_service", lambda: service)
    monkeypatch.setattr(
        resource_routes,
        "get_settings",
        lambda: type("Settings", (), {"resource_internal_api_key": "secret"})(),
    )
    app = FastAPI()
    app.include_router(resource_routes.router)

    content = b"http-image"
    form = {
        "resource_id": "resource-http",
        "document_id": "doc-1",
        "resource_type": "image",
        "content_hash": "sha256:" + hashlib.sha256(content).hexdigest(),
        "mime_type": "image/png",
        "sheet_name": "부품",
        "linked_record_ids": '["sheet-1:row-2"]',
    }
    url = "/internal/ingest-jobs/http-job/resources"
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://backend") as client:
            unauthorized = await client.post(
                url,
                headers={"X-INTERNAL-API-KEY": "wrong"},
                data=form,
                files={"file": ("untrusted-name.png", content, "image/png")},
            )
            assert unauthorized.status_code == 401

            created = await client.post(
                url,
                headers={"X-INTERNAL-API-KEY": "secret"},
                data=form,
                files={"file": ("untrusted-name.png", content, "image/png")},
            )
            assert created.status_code == 201
            resource = created.json()["resource"]
            assert resource["resource_path"] == "staging/http-job/originals/resource-http.png"
            assert not os.path.isabs(resource["resource_path"])

            mismatch = await client.post(
                url,
                headers={"X-INTERNAL-API-KEY": "secret"},
                data={**form, "resource_id": "resource-http-2"},
                files={"file": ("untrusted-name.png", b"other-bytes", "image/png")},
            )
            assert mismatch.status_code == 400

            traversal = await client.post(
                url,
                headers={"X-INTERNAL-API-KEY": "secret"},
                data={**form, "resource_id": "../../etc/passwd"},
                files={"file": ("untrusted-name.png", content, "image/png")},
            )
            assert traversal.status_code == 400

            conflict = await client.post(
                url,
                headers={"X-INTERNAL-API-KEY": "secret"},
                data={**form, "content_hash": "sha256:" + hashlib.sha256(b"changed").hexdigest()},
                files={"file": ("untrusted-name.png", b"changed", "image/png")},
            )
            assert conflict.status_code == 409
    finally:
        _close(db)


# 2026.08.27(sooyeon.choi) 추가 - ingest 성공/실패 시 resource commit·rollback 연결 검증
@pytest.mark.skip(reason="2026.10.16 - 옛 계보 Phase 3 응답 형식(version·previous_version)과 문자열 collection_id stub 전제. Phase 3(개정본 전환) 재구현 때 현재 설계로 고쳐 되살린다")
@pytest.mark.asyncio
async def test_pipeline_commits_on_success_and_preserves_after_downstream_failure(tmp_path):
    from app.services.ingest_pipeline import ChunkStep, IndexStep, IngestContext, IngestPipeline

    service, db = _service(tmp_path)

    class _Chunk:
        def __init__(self, parse_job_id):
            self.metadata = {"parse_job_id": parse_job_id}
            self.page_content = "시트: 부품"

    class _ChunkWriter:
        def write(self, **kwargs):
            return None

    class _StubIngestService:
        """IndexStep이 사용하는 최소 인터페이스만 제공하는 ingest service 대역."""

        def __init__(self, resource_service, parse_job_id):
            self.resource_service = resource_service
            self._parse_job_id = parse_job_id
            self._chunk_writer = _ChunkWriter()

        def _parse_and_chunk(self, *args, **kwargs):
            return {
                "chunks": [_Chunk(self._parse_job_id)],
                "doc_type": "spreadsheet",
                "total_pages": 1,
            }

        def _build_points(self, **kwargs):
            return []

        def _store_vector(self, *args, **kwargs):
            return None

        def _save_history(self, **kwargs):
            return None

        def _build_response(self, *args, **kwargs):
            return {"status": "success"}

    collection_config = types.SimpleNamespace(qdrant_name="parts", collection_id="col-1")
    request = {"file_path": "sample.xlsx", "filename": "sample.xlsx", "collection_name": "parts"}

    class _FailingStep:
        name = "index"

        async def run(self, service, context):
            raise RuntimeError("Qdrant 적재 실패")

    try:
        # 성공 경로: IndexStep이 staging resource를 commit한다.
        await service.stage_upload(_upload(), parse_job_id="ok-job", metadata=_metadata())
        stub = _StubIngestService(service, "ok-job")
        context = IngestContext(request=request, document_id="doc-1")
        await ChunkStep().run(stub, context)
        assert context.data["parse_job_ids"] == ["ok-job"]
        assert "ok-job" in SpreadsheetResourceService.active_parse_job_ids()
        context.data.update(
            collection_config=collection_config,
            stored_path="stored/sample.xlsx",
            stored_filename="sample.xlsx",
            file_size=10,
            embeddings=[[0.1]],
            semantic_results=None,
            kiwi_bm25_documents=[],
            sparse_vectors=None,
        )
        await IndexStep().run(stub, context)
        # 2026.10.08 수정 - Phase 3: 응답에 적재 버전이 추가된다
        assert context.data["result"] == {"status": "success", "version": 1, "previous_version": None}
        assert service.repository.get("resource-1")["status"] == "analysis_pending"
        assert "ok-job" not in SpreadsheetResourceService.active_parse_job_ids()

        # resource 전송 이후 실패 경로: 재시도를 위해 staging을 보존한다.
        await service.stage_upload(
            _upload(), parse_job_id="fail-job", metadata=_metadata(resource_id="resource-2")
        )
        pipeline = IngestPipeline()
        pipeline.steps = (ChunkStep(), _FailingStep())
        with pytest.raises(RuntimeError):
            await pipeline.run(_StubIngestService(service, "fail-job"), request)
        assert service.repository.get("resource-2")["status"] == "staging"
        assert service.resolve_relative_path("staging/fail-job").exists()
        assert "fail-job" in SpreadsheetResourceService.active_parse_job_ids()
    finally:
        _close(db)

"""Excel 정형 파싱 전 구간 통합 테스트 (REQ-TEST-004).

Excel upload → parser → resource upload → structured IR → spreadsheet chunker
→ mock embedding → Qdrant payload → citation API 를 한 번에 통과시키고,
요구사항이 지정한 6종 실패 주입에서 고아 resource가 남지 않는지 검증한다.

parser는 별도 서버이므로 docling-parser를 **별도 프로세스**로 실행해 IR JSON과
resource 원본을 만들고, 그 산출물만 backend 경로에 투입한다.
"""

# 2026.08.27(sooyeon.choi) 추가 - REQ-TEST-004 전 구간 통합 테스트
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from datetime import datetime, timedelta
import base64
import hashlib
import json
import os
import subprocess
import sys

import pytest
from starlette.datastructures import Headers, UploadFile

from app.graphs.nodes.assemble_context import assemble_context
from app.graphs.nodes.format_citations import format_citations
from app.models.data_models import CollectionConfig
from app.parsers.chunkers.spreadsheet import SpreadsheetChunker
from app.parsers.config import ChunkingConfig
from app.parsers.loaders.docling_loader import DoclingApiLoader
from app.parsers.spreadsheet_contract import SpreadsheetContractError
from app.parsers.utils.spreadsheet_converter import spreadsheet_to_documents
from app.repositories import database as database_module
from app.repositories.database import DatabaseManager
from app.repositories.document_repository import DocumentRepository
from app.repositories.spreadsheet_resource_repository import SpreadsheetResourceRepository
from app.services import spreadsheet_resource_service as resource_service_module
from app.services.ingest_pipeline import IngestPipeline
from app.services.ingest_service import ChunkResultWriter, FileStorageManager, IngestService
from app.services.spreadsheet_resource_service import SpreadsheetResourceService
from app.repositories.ingest_record_repository import IngestRecordRepository


PARSER_ROOT = Path(__file__).resolve().parents[2] / "docling-parser"
PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
DOCUMENT_ID = "doc-integration"
COLLECTION = "parts"

pytestmark = pytest.mark.skipif(
    not (PARSER_ROOT / "app" / "spreadsheets" / "parser.py").exists(),
    reason="docling-parser 소스가 없으면 두 서버 통합 경로를 재현할 수 없다.",
)


# ── parser 서버 (별도 프로세스) ────────────────────────────────────────────

_PARSER_SCRIPT = """
import json, sys
sys.path.insert(0, sys.argv[1])
from app.spreadsheets.parser import OpenpyxlExcelParser

result = OpenpyxlExcelParser().parse(
    sys.argv[2], output_format="json", document_id=sys.argv[3], resource_root=sys.argv[4]
)
Path = __import__("pathlib").Path
Path(sys.argv[5]).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
"""


def _build_workbook(path: Path, image_path: Path) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    from openpyxl.drawing.image import Image

    workbook = openpyxl.Workbook()
    workbook.calculation.fullCalcOnLoad = False
    sheet = workbook.active
    sheet.title = "핵심 부품"
    sheet["A1"] = "구분"
    sheet["B1"] = "2026년 상반기"
    sheet["A2"] = "품명"
    sheet["B2"] = "수량"
    sheet["C2"] = "단가"
    sheet["D2"] = "금액"
    sheet.merge_cells("B1:D1")
    sheet.merge_cells("A1:A2")
    # 단가는 캐시값이 있는 통화 셀(표시값 formatter), 금액은 수식 셀(수식 manifest)
    sheet.append(["모터", 2, 1000, "=B3*C3"])
    sheet.append(["펌프", 3, 2000, "=B4*C4"])
    for coordinate in ("C3", "C4"):
        sheet[coordinate].number_format = '"₩"#,##0'
    sheet.add_image(Image(str(image_path)), "F3")
    workbook.save(path)
    workbook.close()


def _run_parser(tmp_path: Path, *, document_id: str = DOCUMENT_ID) -> tuple[dict, Path, Path]:
    """docling-parser를 별도 프로세스로 실행해 IR JSON과 resource 원본을 만든다."""
    image_path = tmp_path / "part.png"
    image_path.write_bytes(PNG_1PX)
    workbook_path = tmp_path / "parts.xlsx"
    _build_workbook(workbook_path, image_path)

    parser_resource_root = tmp_path / "parser_resources"
    output_path = tmp_path / "parser_output.json"
    completed = subprocess.run(
        [
            sys.executable, "-c", _PARSER_SCRIPT,
            str(PARSER_ROOT), str(workbook_path), document_id,
            str(parser_resource_root), str(output_path),
        ],
        cwd=str(PARSER_ROOT),
        capture_output=True,
        text=True,
        timeout=180,
    )
    if completed.returncode != 0:
        pytest.skip(f"parser 프로세스를 실행할 수 없다: {completed.stderr[-500:]}")
    return json.loads(output_path.read_text(encoding="utf-8")), workbook_path, parser_resource_root


# ── backend 조립 ───────────────────────────────────────────────────────────

class _FakeEmbeddingClient:
    """mock embedding: 청크 수와 차원만 계약대로 맞춘다."""

    def __init__(self, fail: bool = False):
        self.fail = fail

    async def embed_texts(self, texts):
        if self.fail:
            raise RuntimeError("embedding 서버 오류")
        return [[float(len(text) % 7), 0.5, 0.25] for text in texts]


class _FakeKiwiEncoder:
    version = "test-1"

    def encode_document(self, text):
        from qdrant_client.models import SparseVector

        return SparseVector(indices=[1, 2], values=[1.0, 0.5])

    def normalize_document(self, text):
        return text


class _FakeVectorRepository:
    def __init__(self, fail_upsert: bool = False):
        self.fail_upsert = fail_upsert
        self.collections: dict[str, int] = {}
        self.points: dict[str, list] = {}
        self.deleted: list[tuple[str, str]] = []

    def ensure_collection(self, collection_name, vector_size):
        self.collections[collection_name] = vector_size

    def upsert_points(self, collection_name, points, batch_size=None):
        if self.fail_upsert:
            raise RuntimeError("Qdrant upsert 실패")
        self.points.setdefault(collection_name, []).extend(points)

    def delete_by_document_id(self, document_id, collection_name):
        self.deleted.append((document_id, collection_name))
        remaining = [
            point for point in self.points.get(collection_name, [])
            if point.payload.get("document_id") != document_id
        ]
        self.points[collection_name] = remaining
        return True


class _FakeCollectionRepository:
    def get_by_qdrant_name(self, name):
        if name != COLLECTION:
            return None
        return CollectionConfig(
            collection_id=1, display_name="부품", qdrant_name=COLLECTION, is_active=True
        )


def _service(tmp_path, *, embedding_fail=False, upsert_fail=False):
    """무거운 외부 클라이언트를 제외하고 실제 ingest 경로만 조립한다."""
    DatabaseManager._instance = None
    database_module._db_manager = None
    instance_dir = tmp_path / "instance"
    db_path = instance_dir / "db" / "metadata.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    database = DatabaseManager()
    database.execute_update(
        """INSERT INTO tb_collections(collection_id, display_name, description, qdrant_name, is_active)
           VALUES(1, '부품', '', ?, TRUE)""",
        (COLLECTION,),
    )
    database.execute_update(
        """INSERT INTO tb_users(user_id, user_pwd, user_name, role)
           VALUES('tester', 'x', '통합테스터', 'admin')""",
    )

    service = IngestService.__new__(IngestService)
    service.settings = SimpleNamespace(
        instance_dir=str(db_path),
        kiwi_bm25_vector_name="kiwi_bm25",
        enable_semantic_enrichment=False,
        resource_storage_root=str(tmp_path / "xl_res"),
        resource_max_upload_bytes=10 * 1024 * 1024,
        resource_staging_ttl_hours=24,
    )
    service.db = database
    service.doc_repo = DocumentRepository(str(db_path))
    service.collection_repo = _FakeCollectionRepository()
    service.embedding_client = _FakeEmbeddingClient(fail=embedding_fail)
    service.kiwi_bm25_encoder = _FakeKiwiEncoder()
    service.sparse_encoder = SimpleNamespace(is_enabled=False)
    service.vector_repo = _FakeVectorRepository(fail_upsert=upsert_fail)
    service._chunk_writer = ChunkResultWriter(instance_dir / "chunk")
    service._file_manager = FileStorageManager(instance_dir / "data")
    service.resource_service = SpreadsheetResourceService(
        root=tmp_path / "xl_res",
        repository=SpreadsheetResourceRepository(db=database),
        max_upload_bytes=10 * 1024 * 1024,
    )
    # 2026.10.01 추가 - Phase 2 문서 버전·청크 기록(placement FK 대상)
    service.record_repo = IngestRecordRepository(db=database)
    return service, database


def _close(database):
    database.close_all_connections()
    DatabaseManager._instance = None
    database_module._db_manager = None
    resource_service_module._ACTIVE_PARSE_JOBS.clear()


async def _upload_resources(service, parser_output, parse_job_id, *, corrupt_hash=False):
    """parser → backend 내부 업로드 API 계약대로 resource를 전송한다."""
    uploaded = []
    for resource in parser_output["resources"]:
        payload = Path(resource["local_path"]).read_bytes()
        content_hash = resource["content_hash"]
        if corrupt_hash:
            content_hash = "sha256:" + hashlib.sha256(b"tampered").hexdigest()
        upload = UploadFile(
            file=BytesIO(payload),
            filename="untrusted-name.bin",
            headers=Headers({"content-type": resource["mime_type"]}),
        )
        uploaded.append(await service.resource_service.stage_upload(
            upload,
            parse_job_id=parse_job_id,
            metadata={
                "resource_id": resource["resource_id"],
                "document_id": resource["document_id"],
                "resource_type": resource["resource_type"],
                "content_hash": content_hash,
                "mime_type": resource["mime_type"],
                "sheet_id": resource["sheet_id"],
                "sheet_name": resource["sheet_name"],
                "from_cell": resource["from_cell"],
                "to_cell": resource["to_cell"],
                "linked_block_id": resource["linked_block_id"],
                "linked_record_ids": resource["linked_record_ids"],
                "surrounding_range": resource["surrounding_range"],
                "surrounding_text": resource["surrounding_text"],
            },
        ))
    return uploaded


def _parse_result(parser_output, workbook_path, parse_job_id):
    """structured IR 검증 → 시트 변환 → spreadsheet 청킹까지 실제 경로로 수행한다."""
    loader = DoclingApiLoader.__new__(DoclingApiLoader)
    md_meta = loader._map_spreadsheet_result(parser_output, str(workbook_path), "xlsx")
    for item in md_meta:
        item["metadata"]["parse_job_id"] = parse_job_id
    documents = spreadsheet_to_documents(md_meta, source_path=str(workbook_path))
    config = ChunkingConfig(spreadsheet_summary_chunks=False)
    chunks = SpreadsheetChunker(config).split_documents(documents)
    return {
        "chunks": chunks,
        "total_pages": len(md_meta),
        "chunk_count": len(chunks),
        "is_law": False,
        "is_manual": False,
        "doc_type": "spreadsheet",
        "file_type": "xlsx",
    }


async def _ingest(service, parser_output, workbook_path, parse_job_id):
    parse_result = _parse_result(parser_output, workbook_path, parse_job_id)
    service._parse_and_chunk = lambda *args, **kwargs: parse_result
    # backend가 document_id를 먼저 정해 parser에 넘기는 계약(REQ-MAP-001)을 재현한다.
    with patch("app.services.ingest_pipeline.uuid4", lambda: DOCUMENT_ID):
        return await IngestPipeline().run(
            service,
            {
                "file_path": str(workbook_path),
                "filename": workbook_path.name,
                "collection_name": COLLECTION,
                "parser_type": "docling",
                "uploaded_by": "tester",
                "security_level": "public",
            },
        )


# ── 정상 경로 ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_excel_pipeline_reaches_qdrant_payload_and_citation(tmp_path):
    parser_output, workbook_path, _ = _run_parser(tmp_path)
    service, database = _service(tmp_path)
    try:
        # 1. parser 산출물 계약: IR + resource 원본
        assert parser_output["schema_name"] == "StructuredSpreadsheet"
        assert parser_output["metadata"]["image_count"] == 1
        resource_id = parser_output["resources"][0]["resource_id"]

        # 2. resource upload (parser → backend staging)
        staged = await _upload_resources(service, parser_output, "job-ok")
        assert staged[0]["status"] == "staging"
        assert staged[0]["resource_path"].startswith("staging/job-ok/")

        # 3~6. IR 검증 → 청킹 → mock embedding → Qdrant 적재
        response = await _ingest(service, parser_output, workbook_path, "job-ok")
        document_id = response["document_id"]
        stored_document = service.doc_repo.get_by_id(document_id)
        assert stored_document is not None and stored_document.doc_type == "spreadsheet"
        points = service.vector_repo.points[COLLECTION]
        assert response["chunk_count"] == len(points) > 0

        # Qdrant payload에서 원본 위치를 역추적할 수 있다.
        payload = points[0].payload
        assert payload["document_type"] == "spreadsheet"
        assert payload["sheet_name"] == "핵심 부품"
        assert payload["source_range"]
        assert payload["chunk_key"].startswith("sheet-1:block-1:")
        assert payload["record_count"] == len(payload["record_ids"])
        assert payload["header_paths"][0] == ["구분"]
        assert payload["formula_count"] >= 1
        assert payload["formula_manifest"][0]["formula"].startswith("=")
        assert "structured_ir" not in payload and "cells" not in payload

        # 표시값 formatter 결과(number_format 적용)가 display Markdown에 반영된다.
        display_markdowns = " ".join(item.payload["display_markdown"] for item in points)
        assert "₩1,000" in display_markdowns and "₩2,000" in display_markdowns
        # 수식 셀은 캐시값이 없어 표시값이 비고, 수식은 manifest로 남는다.
        assert payload["formula_cache_status"] in {"missing", "stale", "available"}

        # resource marker는 display에만 남고 embedding text에는 ID가 없다.
        resource_payload = next(
            item.payload for item in points if item.payload.get("resource_ids")
        )
        assert f"⟦RESOURCE:{resource_id}⟧" in resource_payload["display_markdown"]
        assert resource_id not in resource_payload["text"]

        # resource는 commit되어 공유 asset 위치로 이동하고 분석 대기 상태가 된다.
        # (2026.10.01 수정 - Phase 2 F04: 파일은 해시 기준 assets/, 배치는 placement)
        committed = service.resource_service.repository.get(resource_id)
        assert committed["status"] == "analysis_pending"
        assert committed["resource_path"].startswith("assets/")
        assert committed["document_id"] == document_id
        # 공통 청크 레코드(tb_chunks)가 Qdrant point와 같은 ID·키로 남는다.
        counts = service.record_repo.count_by_document(document_id)
        assert counts == {"versions": 1, "chunks": len(points), "flow_graphs": 0, "placements": 1}
        assert service.resource_service.resolve_relative_path(
            committed["resource_path"]
        ).read_bytes() == PNG_1PX
        assert not service.resource_service.resolve_relative_path("staging/job-ok").exists()

        # 7. citation API: payload가 그대로 인용 응답으로 이어진다.
        citation = await _citation_from_payload(resource_payload)
        assert citation["document_type"] == "spreadsheet"
        assert citation["sheet_name"] == "핵심 부품"
        assert citation["source_range"] == resource_payload["source_range"]
        assert citation["resource_ids"] == resource_payload["resource_ids"]
        assert citation["display_markdown"].startswith("| ")
    finally:
        _close(database)


async def _citation_from_payload(payload):
    chunk = {
        "chunk_id": payload["chunk_id"],
        "document_id": payload["document_id"],
        "text": payload["text"],
        "score": 0.9,
        "metadata": payload,
    }
    settings = SimpleNamespace(
        max_context_chars=10_000,
        relevance_threshold=0.1,
        context_max_chunks_per_document=3,
        max_citation_results=1,
    )
    with (
        patch("app.graphs.nodes.assemble_context.get_settings", return_value=settings),
        patch(
            "app.graphs.nodes.assemble_context.get_retrieval_config",
            return_value=SimpleNamespace(context_top_k=1),
        ),
        patch("app.graphs.utils.get_settings", return_value=SimpleNamespace(rag_diagnostic_log=False)),
    ):
        context = await assemble_context({
            "reranked_chunks": [chunk],
            "citation_limit": 1,
            "relevance_threshold": 0.1,
            "timing": {},
        })
    assert payload["sheet_name"] in context["final_context"]

    with (
        patch("app.graphs.nodes.format_citations.get_settings", return_value=settings),
        patch("app.graphs.nodes.format_citations.ManualDisplayService"),
    ):
        result = await format_citations({
            "generated_answer": "근거는 [1] 입니다.",
            "context_chunks": context["context_chunks"],
            "context_chunk_count": len(context["context_chunks"]),
            "citation_limit": 1,
            "original_query": "모터 금액",
            "preprocess_result": {},
            "timing": {},
        })
    return result["citations"][0]


# ── 실패 주입 ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_parser_failure_leaves_no_backend_resource(tmp_path):
    """parser 실패: backend는 IR을 받지 못하고 staging/DB 어디에도 흔적이 없다."""
    parser_output, workbook_path, _ = _run_parser(tmp_path)
    service, database = _service(tmp_path)
    try:
        await _upload_resources(service, parser_output, "job-parser-fail")

        def _explode(*args, **kwargs):
            raise RuntimeError("parser 서버 오류")

        service._parse_and_chunk = _explode
        with (
            patch("app.services.ingest_pipeline.uuid4", lambda: DOCUMENT_ID),
            pytest.raises(RuntimeError, match="parser 서버 오류"),
        ):
            await IngestPipeline().run(
                service,
                {
                    "file_path": str(workbook_path),
                    "filename": workbook_path.name,
                    "collection_name": COLLECTION,
                    "uploaded_by": "tester",
                },
            )

        # parse_job_id를 알 수 없으므로 TTL cleanup이 staging을 회수한다.
        staging = service.resource_service.resolve_relative_path("staging/job-parser-fail")
        assert staging.exists()
        expired = (datetime.now() - timedelta(hours=48)).timestamp()
        os.utime(staging, (expired, expired))
        service.resource_service.mark_job_finished("job-parser-fail")
        assert service.resource_service.cleanup_expired_staging(24) == 1
        assert service.resource_service.repository.list_by_parse_job("job-parser-fail") == []
        assert service.vector_repo.points == {}
    finally:
        _close(database)


@pytest.mark.asyncio
async def test_resource_upload_hash_mismatch_is_rejected(tmp_path):
    parser_output, _, _ = _run_parser(tmp_path)
    service, database = _service(tmp_path)
    try:
        with pytest.raises(ValueError, match="content hash"):
            await _upload_resources(service, parser_output, "job-hash", corrupt_hash=True)

        resource_id = parser_output["resources"][0]["resource_id"]
        assert service.resource_service.repository.get(resource_id) is None
        staging = service.resource_service.resolve_relative_path("staging/job-hash/originals")
        assert not any(staging.iterdir()) if staging.exists() else True
    finally:
        _close(database)


@pytest.mark.asyncio
async def test_ir_validation_failure_stops_before_chunking(tmp_path):
    parser_output, workbook_path, _ = _run_parser(tmp_path)
    service, database = _service(tmp_path)
    try:
        await _upload_resources(service, parser_output, "job-ir")
        broken = {**parser_output, "schema_version": "9.0"}

        with pytest.raises(SpreadsheetContractError, match="major version"):
            _parse_result(broken, workbook_path, "job-ir")

        assert service.vector_repo.points == {}
        assert service.resource_service.repository.get(
            parser_output["resources"][0]["resource_id"]
        )["status"] == "staging"
    finally:
        _close(database)


@pytest.mark.asyncio
async def test_embedding_failure_preserves_staged_resources(tmp_path):
    parser_output, workbook_path, _ = _run_parser(tmp_path)
    service, database = _service(tmp_path, embedding_fail=True)
    resource_id = parser_output["resources"][0]["resource_id"]
    try:
        await _upload_resources(service, parser_output, "job-embed")

        with pytest.raises(RuntimeError, match="embedding 서버 오류"):
            await _ingest(service, parser_output, workbook_path, "job-embed")

        assert service.resource_service.repository.get(resource_id)["status"] == "staging"
        assert service.resource_service.resolve_relative_path("staging/job-embed").exists()
        assert service.vector_repo.points == {}
        assert "job-embed" in SpreadsheetResourceService.active_parse_job_ids()
    finally:
        _close(database)


@pytest.mark.asyncio
async def test_qdrant_failure_preserves_resources_and_rolls_back_points(tmp_path):
    parser_output, workbook_path, _ = _run_parser(tmp_path)
    service, database = _service(tmp_path, upsert_fail=True)
    resource_id = parser_output["resources"][0]["resource_id"]
    try:
        await _upload_resources(service, parser_output, "job-qdrant")

        with pytest.raises(RuntimeError, match="Qdrant upsert 실패"):
            await _ingest(service, parser_output, workbook_path, "job-qdrant")

        assert service.resource_service.repository.get(resource_id)["status"] == "staging"
        assert service.resource_service.resolve_relative_path("staging/job-qdrant").exists()
        assert service.vector_repo.points.get(COLLECTION) in (None, [])
        documents_root = service.resource_service.resolve_relative_path("documents")
        assert not documents_root.exists() or not any(documents_root.iterdir())
    finally:
        _close(database)


@pytest.mark.asyncio
async def test_resource_delete_failure_is_retried_without_orphans(tmp_path):
    parser_output, workbook_path, _ = _run_parser(tmp_path)
    service, database = _service(tmp_path)
    resource_id = parser_output["resources"][0]["resource_id"]
    try:
        await _upload_resources(service, parser_output, "job-delete")
        response = await _ingest(service, parser_output, workbook_path, "job-delete")
        document_id = response["document_id"]
        # 2026.10.01 수정 - 문서 폴더에는 분석 결과가 쌓인다(원본은 공유 asset).
        service.resource_service.register_analysis(
            resource_id, {"method": "ocr", "status": "completed"}, result_document={"text": "x"}
        )
        document_root = service.resource_service.resolve_relative_path(f"documents/{document_id}")
        assert document_root.exists()

        def _fail(*args, **kwargs):
            raise OSError("파일이 사용 중입니다.")

        with patch.object(resource_service_module.shutil, "rmtree", _fail):
            assert service.resource_service.delete_document_resources(document_id) == "pending"
        assert service.resource_service.repository.get(resource_id)["status"] != "deleted"
        assert document_root.exists()

        # 문서를 삭제 처리한 뒤 정리 job이 남은 resource를 회수한다.
        service.doc_repo.soft_delete(document_id)
        summary = service.resource_service.retry_pending_deletions()

        assert summary["retried_documents"] == 1
        assert not document_root.exists()
        assert service.resource_service.repository.get(resource_id) is None
        assert service.resource_service.list_analyses(resource_id) == []
    finally:
        _close(database)

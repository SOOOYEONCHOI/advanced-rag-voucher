"""Phase 1 - EXCEL_PARSE_MODE 분기, 파일 판별, excel_ingest 연동 단위 테스트.

2026.10.16 수정 - Phase 1 재구현 기준으로 갱신: 적재 결과는 문서 행(tb_documents)으로 확인하고(버전·청크 기록은 Phase 2),
업로드 대기 폴더는 현재 코드 위치(app/core/storage_paths.get_ingest_queue_dir, UPLOADED_FILES_BASE_DIR 기준)를 따른다.

테스트용 xlsx는 openpyxl로 생성한다. docling-parser·Qdrant는 호출하지 않는다
(2026.10.01 Phase 2: 파이프라인 끝까지 도는 테스트는 PostgreSQL 테스트 DB에 기록한다).
"""

import io
import zipfile
from pathlib import Path
from types import SimpleNamespace

import openpyxl
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.storage_paths import get_ingest_queue_dir
from app.ingest import excel_runner
from app.ingest.file_router import (
    ROUTE_DOCLING,
    ROUTE_EXCEL_INGEST,
    ExcelFileRejected,
    resolve_parse_route,
)
from app.parsers import processor
from app.parsers.loaders import docling_loader
from app.routes import ingest
from app.services import ingest_pipeline
from app.services.ingest_pipeline import ChunkStep, IngestContext, IngestPipeline
from app.repositories.database import get_database_manager
from app.utils.security import get_current_principal

_OLE2 = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def make_workbook(path: Path) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "작업표준"
    ws.append(["No", "작업내용", "Check Point"])
    ws.append([1, "FAN 모듈 조립", "볼트 체결 토크 확인"])
    ws.append([2, "배선 정리", "케이블 타이 고정"])
    wb.create_sheet("기준표").append(["항목", "기준"])
    wb.save(path)
    return path


def backend_settings(md_dir: Path, mode: str = "backend"):
    return SimpleNamespace(
        excel_parse_mode=mode,
        md_save_dir=str(md_dir),
        excel_md_keep_last=5,
        excel_xls_convert_timeout=120,
        resource_delivery="pull",
    )


@pytest.fixture
def forbid_docling(monkeypatch):
    """docling 로더가 한 번이라도 호출되면 기록한다."""
    calls = []

    def factory():
        calls.append("factory")
        raise AssertionError("docling loader must not be used")

    def load(*args, **kwargs):
        calls.append("load")
        raise AssertionError("docling load must not be called")

    monkeypatch.setitem(processor.PARSER_REGISTRY, "docling", factory)
    monkeypatch.setattr(docling_loader.DoclingApiLoader, "load", load)
    return calls


# ── 파일 판별 ────────────────────────────────────────────────────────────────

def test_docling_mode_routes_everything_to_docling(tmp_path):
    xlsx = make_workbook(tmp_path / "a.xlsx")
    assert resolve_parse_route(str(xlsx), "docling").handler == ROUTE_DOCLING


@pytest.mark.parametrize("name", ["a.xlsx", "a.xlsm"])
def test_backend_mode_routes_ooxml_excel_to_excel_ingest(tmp_path, name):
    path = make_workbook(tmp_path / name)
    route = resolve_parse_route(str(path), "backend")
    assert route.handler == ROUTE_EXCEL_INGEST


@pytest.mark.parametrize("name", ["doc.pdf", "book.xltx", "slide.pptx"])
def test_backend_mode_keeps_other_formats_on_docling(tmp_path, name):
    path = tmp_path / name
    path.write_bytes(b"%PDF-1.7 fixture")
    assert resolve_parse_route(str(path), "backend").handler == ROUTE_DOCLING


def test_extension_mismatch_is_rejected_as_invalid_format(tmp_path):
    fake = tmp_path / "fake.xlsx"
    fake.write_bytes(b"%PDF-1.7 not a workbook")
    with pytest.raises(ExcelFileRejected) as exc:
        resolve_parse_route(str(fake), "backend")
    assert exc.value.reason == "invalid_format"


def test_zip_without_spreadsheetml_is_rejected(tmp_path):
    fake = tmp_path / "doc.xlsx"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types>wordprocessingml</Types>")
    fake.write_bytes(buffer.getvalue())
    with pytest.raises(ExcelFileRejected) as exc:
        resolve_parse_route(str(fake), "backend")
    assert exc.value.reason == "invalid_format"


def test_encrypted_ooxml_is_rejected_as_encrypted(tmp_path):
    encrypted = tmp_path / "secret.xlsx"
    encrypted.write_bytes(_OLE2 + b"\x00" * 64 + "EncryptedPackage".encode("utf-16-le"))
    with pytest.raises(ExcelFileRejected) as exc:
        resolve_parse_route(str(encrypted), "backend")
    assert exc.value.reason == "encrypted"


def test_xls_requires_ole2_signature(tmp_path):
    ok = tmp_path / "legacy.xls"
    ok.write_bytes(_OLE2 + b"\x00" * 32)
    assert resolve_parse_route(str(ok), "backend").handler == ROUTE_EXCEL_INGEST
    bad = tmp_path / "bad.xls"
    make_workbook(bad)  # 실제로는 ZIP(xlsx)
    with pytest.raises(ExcelFileRejected):
        resolve_parse_route(str(bad), "backend")


# ── excel_runner ─────────────────────────────────────────────────────────────

def test_run_excel_ingest_writes_md_under_md_save_dir(tmp_path):
    xlsx = make_workbook(tmp_path / "작업 표준서.xlsx")
    md_root = tmp_path / "parsed_md"
    output = excel_runner.run_excel_ingest(str(xlsx), "작업 표준서.xlsx", "job-1", str(md_root))

    expected = md_root / "excel" / "작업_표준서" / "job-1"
    assert Path(output.md_dir) == expected
    for name in ("00_summary.md", "chunks.md", "ir.json"):
        assert (expected / name).is_file()
    assert (expected / "sheets").is_dir() and (expected / "images").is_dir()
    assert len(list((expected / "sheets").iterdir())) == 2
    assert (md_root / "excel" / "작업_표준서" / "LATEST").read_text() == "job-1"
    assert output.summary()["sheet_count"] == 2


def test_empty_md_save_dir_skips_md_output(tmp_path):
    xlsx = make_workbook(tmp_path / "a.xlsx")
    output = excel_runner.run_excel_ingest(str(xlsx), "a.xlsx", "job-1", "")
    assert output.md_dir is None
    assert output.summary()["sheet_count"] == 2


def test_md_export_failure_only_warns(tmp_path, monkeypatch, caplog):
    xlsx = make_workbook(tmp_path / "a.xlsx")

    def broken(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(excel_runner, "export_markdown", broken)
    output = excel_runner.run_excel_ingest(str(xlsx), "a.xlsx", "job-1", str(tmp_path / "md"))
    assert output.md_dir is None
    assert output.summary()["chunk_count"] == len(output.result.chunks)
    assert "md_export" in caplog.text


def test_xls_without_libreoffice_fails_with_clear_error(tmp_path, monkeypatch):
    xls = tmp_path / "legacy.xls"
    xls.write_bytes(_OLE2 + b"\x00" * 32)
    monkeypatch.setattr(excel_runner, "find_soffice", lambda: None)
    with pytest.raises(excel_runner.ExcelIngestError, match="LibreOffice"):
        excel_runner.run_excel_ingest(str(xls), "legacy.xls", "job-1", str(tmp_path / "md"))


# ── 파이프라인 분기 ───────────────────────────────────────────────────────────

class StubService:
    """ParseStep이 쓰는 최소 인터페이스와 docling 경로 호출 기록."""

    def __init__(self, tmp_path):
        self.parse_and_chunk_calls = 0
        self._tmp = tmp_path

        async def save(src, filename, document_id):
            return f"stored_{document_id}", f"instance/data/{document_id}", 1

        self._file_manager = SimpleNamespace(save=save)

    def _validate_collection(self, name):
        return SimpleNamespace(qdrant_name=name, collection_id=1)

    def _parse_and_chunk(self, *args, **kwargs):
        self.parse_and_chunk_calls += 1
        return {"chunks": []}


def _request(path: Path, job_id="job-1"):
    return {
        "file_path": str(path),
        "filename": path.name,
        "collection_name": "documents",
        "parser_type": "docling",
        "document_type": "auto",
        "job_id": job_id,
    }


@pytest.mark.asyncio
async def test_backend_mode_xlsx_skips_docling_and_indexes(tmp_path, monkeypatch, forbid_docling):
    # 2026.10.01 수정 - Phase 2: backend 모드 엑셀도 임베딩·적재까지 진행한다.
    from excel_ingest_fakes import make_ingest_service

    monkeypatch.setattr(ingest_pipeline, "get_settings", lambda: backend_settings(tmp_path / "md"))
    xlsx = make_workbook(tmp_path / "book.xlsx")
    service = make_ingest_service(tmp_path / "xl_res", tmp_path / "chunk")
    service._parse_and_chunk = lambda *a, **k: (_ for _ in ()).throw(AssertionError("docling 경로 호출"))

    result = await IngestPipeline().run(service, _request(xlsx))

    assert forbid_docling == []
    assert result["processing_engine"] == "excel_ingest"
    assert Path(result["excel_ingest"]["md_dir"]) == tmp_path / "md" / "excel" / "book" / "job-1"
    points = service.vector_repo.points["documents"]
    assert len(points) == result["chunk_count"] > 0
    assert {p.payload["processing_engine"] for p in points} == {"excel_ingest"}
    assert {p.payload["sheet_name"] for p in points} == {"작업표준", "기준표"}
    assert all(p.payload["document_type"] == "spreadsheet" and p.payload["text"] for p in points)
    # 2026.10.16 수정 - Phase 1: 문서 행에 처리기 이름이 남는다(버전·청크 테이블은 Phase 2)
    row = get_database_manager().execute_query(
        "SELECT parser_type, doc_type, chunk_count, total_pages FROM tb_documents WHERE document_id = ?",
        (result["document_id"],),
    )[0]
    assert (row["parser_type"], row["doc_type"], row["chunk_count"], row["total_pages"]) == (
        "excel_ingest", "spreadsheet", len(points), 2
    )


@pytest.mark.asyncio
async def test_docling_mode_keeps_existing_xlsx_path(tmp_path, monkeypatch):
    monkeypatch.setattr(ingest_pipeline, "get_settings", lambda: backend_settings(tmp_path / "md", mode="docling"))
    xlsx = make_workbook(tmp_path / "book.xlsx")
    service = StubService(tmp_path)
    context = IngestContext(request=_request(xlsx))

    await ChunkStep().run(service, context)

    assert service.parse_and_chunk_calls == 1
    assert "excel_ingest" not in context.data
    assert not (tmp_path / "md" / "excel").exists()


@pytest.mark.asyncio
async def test_pdf_goes_to_docling_even_in_backend_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(ingest_pipeline, "get_settings", lambda: backend_settings(tmp_path / "md"))
    pdf = tmp_path / "manual.pdf"
    pdf.write_bytes(b"%PDF-1.7 fixture")
    service = StubService(tmp_path)
    context = IngestContext(request=_request(pdf))

    await ChunkStep().run(service, context)

    assert service.parse_and_chunk_calls == 1
    assert "excel_records" not in context.data


# ── 업로드 API ────────────────────────────────────────────────────────────────

@pytest.fixture
def upload_client(monkeypatch, tmp_path):
    # 2026.10.08 수정 - Phase 3: job은 실제 테스트 DB 큐에 만들고, 컬렉션 행이 있어야 업로드를 받는다.
    from test_multi_document_upload import seed_upload_db, upload_settings

    jobs = {}
    state = {"mode": "docling"}

    async def enqueue(job_id):
        jobs[job_id] = ingest.IngestJobRepository().get(job_id)["request"]

    seed_upload_db("owner")
    monkeypatch.setattr(
        ingest,
        "get_settings",
        lambda: upload_settings(tmp_path, excel_parse_mode=state["mode"]),
    )
    monkeypatch.setattr(ingest, "MetadataRepository", lambda *_: SimpleNamespace(get_user_permissions=lambda _: None))
    monkeypatch.setattr(ingest, "get_ingest_job_manager", lambda: SimpleNamespace(enqueue=enqueue))
    app = FastAPI()
    app.include_router(ingest.router, prefix="/api")
    app.dependency_overrides[get_current_principal] = lambda: dict(user_id="owner", is_admin=True)
    queue_dir = get_ingest_queue_dir(upload_settings(tmp_path))
    with TestClient(app) as client:
        yield client, jobs, state, queue_dir


def _xlsx_bytes(tmp_path) -> bytes:
    return make_workbook(tmp_path / "upload.xlsx").read_bytes()


def test_docling_mode_still_rejects_xls(upload_client):
    client, jobs, state, _ = upload_client
    response = client.post("/api/ingest/upload", files={"file": ("old.xls", _OLE2 + b"\x00" * 32)})
    assert response.status_code == 400
    assert jobs == {}


def test_backend_mode_accepts_xls_and_xlsx(upload_client, tmp_path):
    client, jobs, state, _ = upload_client
    state["mode"] = "backend"
    assert client.post("/api/ingest/upload", files={"file": ("old.xls", _OLE2 + b"\x00" * 32)}).status_code == 202
    assert client.post("/api/ingest/upload", files={"file": ("new.xlsx", _xlsx_bytes(tmp_path))}).status_code == 202
    assert len(jobs) == 2


def test_backend_mode_rejects_disguised_excel_and_removes_temp_file(upload_client):
    client, jobs, state, queue_dir = upload_client
    state["mode"] = "backend"
    response = client.post("/api/ingest/upload", files={"file": ("fake.xlsx", b"%PDF-1.7 not excel")})
    assert response.status_code == 400
    assert "rejected(invalid_format)" in response.json()["detail"]
    assert jobs == {}
    assert list(queue_dir.iterdir()) == []

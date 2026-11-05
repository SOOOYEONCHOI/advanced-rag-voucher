"""Phase 2 - 청크·이미지 적재 연결 테스트 (2026.10.01).

- excel_ingest 청크 → 적재 Document 변환(분할·결정적 키·메타)
- 마이그레이션 0002: 기존 resource → asset/placement/staging 분해·이관과 되돌리기
- 문서 삭제: 버전·청크·placement 삭제, asset 유지 → 참조가 없어지면 cleanup이 정리, 이관 asset 이동
- docling 경로도 같은 청크 레코드(tb_chunks)·결정적 point ID를 쓴다(A-2)
테스트용 xlsx는 openpyxl로 생성한다. 임베딩·Qdrant는 가짜, DB는 PostgreSQL 테스트 DB.
"""
from __future__ import annotations

import hashlib
import io
from pathlib import Path
from types import SimpleNamespace

import openpyxl
import pytest
from alembic import command
from openpyxl.drawing.image import Image as XLImage
from PIL import Image

from app.ingest.chunk_records import assign_chunk_keys, point_id
from app.ingest.excel_indexer import build_excel_documents, build_placement_rows, split_chunk_text
from app.ingest.excel_runner import run_excel_ingest
from app.parsers.models import LCDocument
from app.repositories.database import get_database_manager
from app.services import ingest_pipeline
from app.services.ingest_pipeline import IngestPipeline
from excel_ingest_fakes import make_ingest_service


def _png(color) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (40, 30), color).save(buffer, format="PNG")
    return buffer.getvalue()


def make_sop_workbook(path: Path, tmp_path: Path) -> Path:
    """SOP 시트(사진 열 + Step 2개) — 같은 사진을 두 Step에 배치해 asset 공유를 만든다."""
    photo = tmp_path / "photo.png"
    photo.write_bytes(_png("red"))
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "FAN Module 조립"
    ws.append(["작성 일자", "2025.02.17"])
    ws.append(["No", "사진", "작업 내용", "Check Point"])
    ws.append([1, "", "COVER 조립", "볼트 체결 " + "토크 확인 " * 120])
    ws.append([2, "", "REACT FAN", "방진고무 M6 S/P NUT 체결"])
    for row in (3, 4):
        ws.row_dimensions[row].height = 60
        ws.add_image(XLImage(str(photo)), f"B{row}")
    wb.save(path)
    return path


def backend_settings(md_dir: Path):
    return SimpleNamespace(
        excel_parse_mode="backend", md_save_dir=str(md_dir), excel_md_keep_last=5,
        excel_xls_convert_timeout=120, resource_delivery="pull", max_chunk_size=300,
    )


# ── 청크 변환 ────────────────────────────────────────────────────────────────

def test_split_keeps_path_header_and_limit():
    text = "[모델 > 시트 > Step 1]\n" + "\n".join(f"항목 {i}: " + "가" * 50 for i in range(20)) + "\n" + "나" * 500
    parts = split_chunk_text(text, 200)
    assert len(parts) > 1
    assert all(len(p) <= 200 for p in parts)
    assert all(p.startswith("[모델 > 시트 > Step 1]\n") for p in parts)
    # 머리줄을 뺀 본문은 손실 없이 이어 붙는다(줄바꿈 위치만 달라질 수 있음)
    body = "".join(p.split("\n", 1)[1].replace("\n", "") for p in parts)
    assert body == text.split("\n", 1)[1].replace("\n", "")
    assert split_chunk_text("짧은 청크", 200) == ["짧은 청크"]


def test_excel_documents_have_deterministic_keys_and_metadata(tmp_path):
    xlsx = make_sop_workbook(tmp_path / "sop.xlsx", tmp_path)
    output = run_excel_ingest(str(xlsx), "sop.xlsx", "run-1", "", model="NEOCON C2")
    docs = build_excel_documents(output, version=1, max_chars=300, model="NEOCON C2")
    again = build_excel_documents(output, version=1, max_chars=300, model="NEOCON C2")

    keys = [d.metadata["chunk_key"] for d in docs]
    assert keys == [d.metadata["chunk_key"] for d in again]
    assert len(set(keys)) == len(keys)
    assert all(len(d.page_content) <= 300 for d in docs)
    # 긴 Step 1은 조각으로 나뉘고 조각마다 Step 메타를 유지한다.
    step1 = [d for d in docs if d.metadata["source_chunk_id"].endswith(":step:1")]
    assert len(step1) > 1 and {d.metadata["part_count"] for d in step1} == {len(step1)}
    assert all(d.metadata["step_no"] == 1 and d.metadata["section_type"] == "sop" for d in step1)
    step2 = next(d for d in docs if d.metadata["source_chunk_id"].endswith(":step:2"))
    sha = hashlib.sha256(_png("red")).hexdigest()
    assert step2.metadata["image_ids"] == [sha]           # 16자 short ID → 전체 sha256
    assert step2.metadata["model"] == "NEOCON C2" and step2.metadata["doc_key"] == "sop"
    assert step2.page_content.startswith("[NEOCON C2 > FAN Module 조립 > Step 2.")

    placements = build_placement_rows(output, document_id="doc-x", version=1)
    assert len(placements) == 2 and {p["image_id"] for p in placements} == {sha}
    assert len({p["placement_id"] for p in placements}) == 2
    assert {p["step_no"] for p in placements} == {1, 2}
    assert placements == build_placement_rows(output, document_id="doc-x", version=1)


def test_chunk_keys_are_unique_and_point_ids_deterministic():
    keys = assign_chunk_keys([{"chunk_key": "a"}, {"chunk_key": "a"}, {}, None])
    assert keys == ["a", "a~2", "c00002", "c00003"]
    assert point_id("doc", 1, "a") == point_id("doc", 1, "a") != point_id("doc", 2, "a")


# ── 파이프라인 적재·재적재·삭제 ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pipeline_indexes_excel_and_reingest_adds_no_assets(tmp_path, monkeypatch):
    monkeypatch.setattr(ingest_pipeline, "get_settings", lambda: backend_settings(tmp_path / "md"))
    xlsx = make_sop_workbook(tmp_path / "sop.xlsx", tmp_path)
    service = make_ingest_service(tmp_path / "xl_res", tmp_path / "chunk")
    request = {
        "file_path": str(xlsx), "filename": "sop.xlsx", "collection_name": "documents",
        "parser_type": "docling", "document_type": "auto", "job_id": "job-1", "model": "NEOCON C2",
        "uploaded_by": "admin",
    }

    first = await IngestPipeline().run(service, request)
    db = get_database_manager()
    doc = db.execute_query(
        "SELECT doc_key, model, active_version, parser_type FROM tb_documents WHERE document_id=?",
        (first["document_id"],),
    )[0]
    assert (doc["doc_key"], doc["model"], doc["active_version"], doc["parser_type"]) == (
        "sop", "NEOCON C2", 1, "excel_ingest"
    )
    version = db.execute_query(
        "SELECT processing_engine, file_sha256, created_by FROM tb_document_versions WHERE document_id=?",
        (first["document_id"],),
    )[0]
    assert version["processing_engine"] == "excel_ingest"
    assert version["file_sha256"] == hashlib.sha256(xlsx.read_bytes()).hexdigest()
    assert version["created_by"] == "admin"
    assert first["excel_ingest"]["new_asset_count"] == 1

    points = service.vector_repo.points["documents"]
    chunk_rows = db.execute_query(
        "SELECT chunk_id, chunk_key, location, image_ids FROM tb_chunks WHERE document_id=? ORDER BY chunk_index",
        (first["document_id"],),
    )
    assert [r["chunk_id"] for r in chunk_rows] == [str(p.id) for p in points]
    assert all(p.payload["version"] == 1 and p.payload["model"] == "NEOCON C2" for p in points)

    # 같은 파일을 다른 컬렉션에 적재(같은 컬렉션은 Phase 3부터 duplicate로 건너뜀): 이미지 asset은 공유
    other = make_ingest_service(tmp_path / "xl_res", tmp_path / "chunk", collection="manuals",
                                vector_repo=service.vector_repo)
    second = await IngestPipeline().run(other, {**request, "job_id": "job-2", "collection_name": "manuals"})
    assert second["excel_ingest"]["new_asset_count"] == 0
    assert db.execute_query("SELECT count(*) FROM tb_image_assets")[0][0] == 1
    assert db.execute_query("SELECT count(*) FROM tb_image_placements")[0][0] == 4

    # 문서 삭제: 버전·청크·placement 삭제, asset은 다른 문서가 쓰고 있어 유지
    service.delete_document(first["document_id"])
    counts = service.record_repo.count_by_document(first["document_id"])
    assert counts == {"versions": 0, "chunks": 0, "flow_graphs": 0, "placements": 0}
    assert db.execute_query("SELECT count(*) FROM tb_image_assets")[0][0] == 1

    # 마지막 문서까지 지우면 asset은 참조가 없어지고 cleanup이 파일과 행을 정리한다.
    other.delete_document(second["document_id"])
    asset_files = list((tmp_path / "xl_res" / "assets").glob("*/*"))
    assert len(asset_files) == 1
    assert service.resource_service.cleanup_unreferenced_assets(ttl_hours=24) == 0  # 생성 직후는 유예
    db.execute_update("UPDATE tb_image_assets SET created_at = now() - interval '2 days'")
    assert service.resource_service.cleanup_unreferenced_assets(ttl_hours=24) == 1
    assert db.execute_query("SELECT count(*) FROM tb_image_assets")[0][0] == 0
    assert not asset_files[0].exists()


@pytest.mark.asyncio
async def test_docling_path_writes_common_chunk_records(tmp_path, monkeypatch):
    """A-2: docling 결과(PDF)도 같은 청크 레코드·결정적 ID로 기록된다."""
    monkeypatch.setattr(
        ingest_pipeline, "get_settings",
        lambda: SimpleNamespace(excel_parse_mode="docling", resource_delivery="pull"),
    )
    pdf = tmp_path / "manual.pdf"
    pdf.write_bytes(b"%PDF-1.7 fixture")
    service = make_ingest_service(tmp_path / "xl_res", tmp_path / "chunk")
    chunks = [
        LCDocument(page_content="1장 개요", metadata={"page": 1, "section_title": "개요"}),
        LCDocument(page_content="2장 절차", metadata={"page": 2, "section_title": "절차"}),
    ]
    service._parse_and_chunk = lambda *a, **k: {
        "chunks": chunks, "doc_type": "general", "total_pages": 2, "chunk_count": 2,
        "is_law": False, "is_manual": False,
    }
    result = await IngestPipeline().run(service, {
        "file_path": str(pdf), "filename": "manual.pdf", "collection_name": "documents",
        "parser_type": "docling", "document_type": "auto",
    })
    db = get_database_manager()
    rows = db.execute_query(
        "SELECT chunk_id, chunk_key, page_number, location FROM tb_chunks WHERE document_id=? ORDER BY chunk_index",
        (result["document_id"],),
    )
    assert [r["chunk_key"] for r in rows] == ["c00000", "c00001"]
    assert [r["chunk_id"] for r in rows] == [point_id(result["document_id"], 1, k) for k in ("c00000", "c00001")]
    assert [r["page_number"] for r in rows] == [1, 2]
    engine = db.execute_query(
        "SELECT processing_engine FROM tb_document_versions WHERE document_id=?", (result["document_id"],)
    )[0][0]
    assert engine == "docling"
    assert "excel_ingest" not in result


# ── 마이그레이션 0002 데이터 이관 ─────────────────────────────────────────────

def test_0002_decomposes_legacy_resources_and_downgrade_restores(postgres_schema):
    db = get_database_manager()
    command.downgrade(postgres_schema, "0001_baseline")
    try:
        h1, h2 = "a" * 64, "b" * 64
        db.execute_update("INSERT INTO tb_collections (collection_id, display_name, qdrant_name) VALUES (1, 'c', 'c')")
        db.execute_update(
            "INSERT INTO tb_documents (document_id, collection_id, source_path, status) VALUES "
            "('doc-1', 1, 'p1', 'ready'), ('doc-2', 1, 'p2', 'ready')"
        )
        db.execute_update(
            "INSERT INTO tb_documents (document_id, collection_id, source_path, status, deleted_at) "
            "VALUES ('doc-gone', 1, 'p3', 'deleted', now())"
        )
        resources = [
            # (id, doc, job, type, path, hash, status)
            ("r1", "doc-1", "job-1", "image", f"documents/doc-1/resources/r1/original/{h1}.png", h1, "analysis_pending"),
            ("r2", "doc-2", "job-2", "image", f"documents/doc-2/resources/r2/original/{h1}.png", h1, "committed"),
            ("r3", "doc-1", "job-1", "shape", f"documents/doc-1/resources/r3/original/{h2}.xml", h2, "committed"),
            ("r4", "doc-gone", "job-3", "image", f"documents/doc-gone/x/{h2}.png", h2, "deleted"),
            ("r5", "doc-new", "job-4", "image", "staging/job-4/originals/r5.png", h2, "staging"),
        ]
        for rid, doc, job, rtype, path, digest, status in resources:
            db.execute_update(
                """INSERT INTO tb_spreadsheet_resources (resource_id, document_id, parse_job_id, resource_type,
                   resource_path, content_hash, mime_type, file_size, sheet_name, from_cell, to_cell,
                   linked_record_ids, surrounding_text, status)
                   VALUES (?,?,?,?,?,?,?,10,'시트','A1','B2','["row-1"]','주변 글',?)""",
                (rid, doc, job, rtype, path, f"sha256:{digest}",
                 "application/xml" if rtype == "shape" else "image/png", status),
            )
        db.execute_update(
            """INSERT INTO tb_spreadsheet_resource_analyses (analysis_id, resource_id, document_id,
               analysis_version, method, status) VALUES ('a1', 'r1', 'doc-1', 1, 'ocr', 'completed')"""
        )

        command.upgrade(postgres_schema, "head")

        assert db.execute_query("SELECT count(*) FROM tb_image_assets")[0][0] == 2
        placements = {
            r["placement_id"]: dict(r)
            for r in db.execute_query("SELECT * FROM tb_image_placements ORDER BY placement_id")
        }
        assert set(placements) == {"r1", "r2", "r3"}               # deleted 행(r4)은 옮기지 않는다
        assert placements["r1"]["image_id"] == placements["r2"]["image_id"] == h1   # 같은 해시 = asset 1건
        assert placements["r1"]["context_text"] == "주변 글"
        assert db.execute_query("SELECT resource_id FROM tb_resource_staging")[0][0] == "r5"
        assert db.execute_query(
            "SELECT count(*) FROM tb_document_versions WHERE status='active'"
        )[0][0] == 2                                                  # 삭제된 문서는 버전 없음
        assert db.execute_query("SELECT active_version FROM tb_documents WHERE document_id='doc-1'")[0][0] == 1
        # 분석 결과는 placement FK로 이어진다(placement 삭제 시 함께 삭제)
        db.execute_update("DELETE FROM tb_image_placements WHERE placement_id='r1'")
        assert db.execute_query("SELECT count(*) FROM tb_spreadsheet_resource_analyses")[0][0] == 0

        command.downgrade(postgres_schema, "0001_baseline")
        restored = {
            r["resource_id"]: r["status"]
            for r in db.execute_query("SELECT resource_id, status FROM tb_spreadsheet_resources")
        }
        assert restored == {"r2": "committed", "r3": "committed", "r5": "staging"}
    finally:
        command.upgrade(postgres_schema, "head")


@pytest.mark.asyncio
async def test_delete_relocates_migrated_asset_shared_by_other_document(tmp_path):
    """이관 asset이 삭제 대상 문서 폴더에 있으면 공유 위치로 옮긴 뒤 폴더를 지운다."""
    service = make_ingest_service(tmp_path / "xl_res", tmp_path / "chunk")
    db = get_database_manager()
    collection_id = db.execute_query("SELECT collection_id FROM tb_collections WHERE qdrant_name='documents'")[0][0]
    data = _png("blue")
    digest = hashlib.sha256(data).hexdigest()
    legacy = f"documents/doc-a/resources/r1/original/{digest}.png"
    legacy_path = service.resource_service.resolve_relative_path(legacy)
    legacy_path.parent.mkdir(parents=True)
    legacy_path.write_bytes(data)
    for doc in ("doc-a", "doc-b"):
        db.execute_update(
            "INSERT INTO tb_documents (document_id, collection_id, source_path, status) VALUES (?,?,?,'ready')",
            (doc, collection_id, f"p/{doc}"),
        )
        db.execute_update("INSERT INTO tb_document_versions (document_id, version) VALUES (?, 1)", (doc,))
    service.resource_service.repository.insert_assets([{
        "image_id": digest, "storage_path": legacy, "media_type": "image/png", "format": "png", "bytes": len(data),
    }])
    for rid, doc in (("r1", "doc-a"), ("r2", "doc-b")):
        service.resource_service.repository.insert_placements([{
            "placement_id": rid, "image_id": digest, "document_id": doc, "version": 1,
            "source": "docling_parser", "resource_type": "image", "status": "committed",
        }])

    assert service.resource_service.delete_document_resources("doc-a") == "deleted"
    assert not service.resource_service.resolve_relative_path("documents/doc-a").exists()
    metadata, path = service.resource_service.resolve_resource("r2")
    assert metadata["resource_path"] == f"assets/{digest[:2]}/{digest}.png"
    assert path.read_bytes() == data

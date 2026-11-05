"""Phase 2 적재 기록 단위 테스트 (2026.10.16, reports/phase-2-plan.md P2-6·P2-7·P2-9).

- docling 경로 문서도 버전 v1·청크 행이 남는다(완료 기준 5).
- 청크 분할(머리말 반복), 버전 무관 키 중복 처리, 결정적 포인트 ID.
"""
from types import SimpleNamespace

import pytest

from app.ingest.excel_chunks import excel_chunks_to_documents, split_text
from app.ingest.records import assign_chunk_identity, point_id_for
from app.parsers.models import LCDocument
from app.repositories.database import get_database_manager
from app.services import ingest_pipeline
from app.services.ingest_pipeline import IngestPipeline


def test_split_repeats_header_and_respects_limit():
    text = "[모델 > 시트 > 표]\n(열: A | B)\n" + "\n".join(f"행 {i} 값 " + "가" * 30 for i in range(40))
    parts = split_text(text, 300)
    assert len(parts) > 1 and all(len(p) <= 300 for p in parts)
    assert all(p.startswith("[모델 > 시트 > 표]\n(열: A | B)\n") for p in parts)
    assert "\n".join(p.split("\n", 2)[2] for p in parts) == text.split("\n", 2)[2]  # 행 손실 없음
    assert split_text("짧은 글", 300) == ["짧은 글"]


def test_duplicate_source_keys_become_unique_and_images_skipped():
    chunks = [
        {"chunk_id": "doc:09:step:0", "sheet": "S", "content_type": "step", "text": "a", "meta": {}},
        {"chunk_id": "doc:09:step:0", "sheet": "S", "content_type": "step", "text": "b", "meta": {}},
        {"chunk_id": "doc:09:image:x", "sheet": "S", "content_type": "image", "text": "img", "meta": {}},
    ]
    docs = excel_chunks_to_documents(chunks, resource_lookup=lambda sheet, ids: ["r1"])
    assert [d.metadata["source_key"] for d in docs] == ["09:step:0", "09:step:0~2"]
    assert all(d.metadata["resource_ids"] == ["r1"] for d in docs)


def test_point_ids_are_deterministic_and_identity_is_idempotent():
    docs = [LCDocument("a", {"source_key": "k"}), LCDocument("b", {"source_key": "k"}), LCDocument("c", {})]
    assign_chunk_identity(docs, "doc", 1)
    first = [d.metadata["point_id"] for d in docs]
    assign_chunk_identity(docs, "doc", 1)
    assert [d.metadata["point_id"] for d in docs] == first and len(set(first)) == 3
    assert docs[0].metadata["chunk_record_id"] == "doc:1:k#0"
    assert first[0] == point_id_for("doc:1:k#0")


@pytest.mark.asyncio
async def test_docling_path_records_version_and_chunks(tmp_path, monkeypatch):
    from excel_ingest_fakes import make_ingest_service

    monkeypatch.setattr(ingest_pipeline, "get_settings", lambda: SimpleNamespace(
        excel_parse_mode="docling", md_save_dir="", excel_md_keep_last=5, excel_xls_convert_timeout=120,
        resource_delivery="pull", max_chunk_size=800,
    ))
    service = make_ingest_service(tmp_path / "xl_res", tmp_path / "chunk")
    service._parse_and_chunk = lambda *a, **k: {
        "chunks": [LCDocument(f"본문 {i}", {"section_title": f"절 {i}"}) for i in range(3)],
        "doc_type": "general", "requested_doc_type": "auto", "doc_type_source": "auto_detected",
        "detection_details": None, "is_law": False, "is_manual": False, "total_pages": 2, "chunk_count": 3,
    }
    pdf = tmp_path / "manual.pdf"
    pdf.write_bytes(b"%PDF-1.7 fixture")
    result = await IngestPipeline().run(service, {
        "file_path": str(pdf), "filename": "manual.pdf", "collection_name": "documents",
        "parser_type": "docling", "document_type": "auto", "job_id": "job-d",
    })
    db = get_database_manager()
    version = db.execute_query("SELECT * FROM tb_document_versions WHERE document_id = ?", (result["document_id"],))[0]
    assert (version["version_no"], version["status"], version["processing_engine"]) == (1, "active", "docling")
    rows = db.execute_query("SELECT point_id::text, source_key FROM tb_chunks WHERE document_id = ? ORDER BY 2",
                            (result["document_id"],))
    points = service.vector_repo.points["documents"]
    assert {r[0] for r in rows} == {str(p.id) for p in points} and [r[1] for r in rows] == ["c00000", "c00001", "c00002"]
    assert all(p.payload["chunk_id"] == str(p.id) for p in points)  # payload chunk_id = 포인트 ID(평가 호환)
    assert db.execute_query("SELECT doc_key FROM tb_documents WHERE document_id = ?",
                            (result["document_id"],))[0][0] == "manual"

"""샘플 엑셀 적재 통합 테스트 — Phase 1(분기·md) + Phase 2(버전·청크·사진·흐름도) 완료 기준 (2026.10.16).

관련 ID: F-2-01·F-2-03~05·F-3-01·F-3-02·F-3-04 / R1-1, R2-1~3, R3-1·R3-2 · 설계: reports/phase-2-plan.md P2-1~P2-13
외부 서버(임베딩·Qdrant·docling)만 가짜(tests/excel_ingest_fakes.py), DB는 PostgreSQL 테스트 DB, 사진 저장소는 tmp.
샘플 경로: 환경변수 NEOCON_SAMPLE_XLSX, 없으면 저장소 루트 NEOCON_SAMPLE_XLSX.xlsx. 없으면 건너뛴다(사내 문서).
"""
import asyncio
import json
import os
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.parsers import processor
from app.parsers.loaders import docling_loader
from app.repositories.database import get_database_manager
from app.services import ingest_pipeline
from app.services.ingest_pipeline import IngestPipeline

SAMPLE = Path(
    os.environ.get("NEOCON_SAMPLE_XLSX")
    or Path(__file__).resolve().parents[2] / "NEOCON_SAMPLE_XLSX.xlsx"
)
GUIDE_NOTE_TEXT = "도면 스캔하여 첨부 및 제출을 허용"
MAX_CHUNK_SIZE = 800

pytestmark = pytest.mark.skipif(not SAMPLE.is_file(), reason="NEOCON_SAMPLE_XLSX 샘플 파일 없음")


def _service(root: Path, collection: str):
    from excel_ingest_fakes import make_ingest_service

    service = make_ingest_service(root / "xl_res", root / "chunk", collection=collection)

    def _parse_and_chunk(*args, **kwargs):
        raise AssertionError("docling path must not run in backend mode")

    service._parse_and_chunk = _parse_and_chunk
    return service


def _request(job_id: str, collection: str, product_model: str | None = None):
    return {
        "file_path": str(SAMPLE),
        "filename": SAMPLE.name,
        "collection_name": collection,
        "parser_type": "docling",       # backend 모드에서는 무시(D-16)
        "document_type": "general",     # backend 모드에서는 무시(D-16)
        "job_id": job_id,
        "product_model": product_model,
    }


@pytest.fixture(scope="module")
def md_root(tmp_path_factory):
    return tmp_path_factory.mktemp("parsed_md")


@pytest.fixture
def backend_mode(monkeypatch, md_root):
    calls = []

    def forbidden(*args, **kwargs):
        calls.append(1)
        raise AssertionError("docling must not be called")

    monkeypatch.setitem(processor.PARSER_REGISTRY, "docling", forbidden)
    monkeypatch.setattr(docling_loader.DoclingApiLoader, "load", forbidden)
    monkeypatch.setattr(ingest_pipeline, "get_settings", lambda: SimpleNamespace(
        excel_parse_mode="backend", md_save_dir=str(md_root), excel_md_keep_last=5,
        excel_xls_convert_timeout=120, resource_delivery="pull", max_chunk_size=MAX_CHUNK_SIZE,
        excel_image_link_all=True,
    ))
    return calls


def _summary_value(summary_md: str, label: str) -> str:
    match = re.search(rf"^\| {re.escape(label)} \| (.+?) \|$", summary_md, re.MULTILINE)
    assert match, label
    return match.group(1)


@pytest.mark.asyncio
async def test_sample_backend_mode_md_records_images_and_delete(backend_mode, md_root, tmp_path):
    service = _service(tmp_path, "documents")
    result = await IngestPipeline().run(service, _request("job-sample", "documents", "NEOCON C2"))
    document_id = result["document_id"]
    db = get_database_manager()

    # ── Phase 1: 분기·확인용 md ──
    assert backend_mode == [], "docling 호출 0건"
    assert result["processing_engine"] == "excel_ingest"
    out = Path(result["excel_ingest"]["md_dir"])
    assert out == md_root / "excel" / "NEOCON_SAMPLE_XLSX" / "job-sample"
    assert len(list((out / "sheets").glob("*.md"))) == 18
    summary_md = (out / "00_summary.md").read_text(encoding="utf-8")
    assert _summary_value(summary_md, "이미지 배치 / 고유 이미지") == "190 / 152"
    s = result["excel_ingest"]
    assert len(s["sheet_revisions"]) == 10  # 관리대장 매칭 시트(R2-3)
    assert (s["sheet_count"], s["image_placement_count"], s["unique_image_count"], s["out_of_print_area_count"]) == (
        18, 190, 152, 69,
    )

    # ── Phase 2: 버전·청크(P2-6·7·9) ──
    counts = service.record_repo.count_by_document(document_id)
    points = service.vector_repo.points["documents"]
    assert counts["versions"] == 1 and counts["chunks"] == len(points) > 0
    assert max(len(p.payload["text"]) for p in points) <= MAX_CHUNK_SIZE
    chunk_rows = db.execute_query("SELECT point_id::text, source_key, part_no FROM tb_chunks WHERE document_id = ?",
                                  (document_id,))
    assert {r[0] for r in chunk_rows} == {str(p.id) for p in points}           # Qdrant 포인트 = 청크 행
    assert all(p.payload["version_no"] == 1 and p.payload["point_type"] == "text" for p in points)
    ir = json.loads((out / "ir.json").read_text(encoding="utf-8"))
    text_chunk_keys = {c["chunk_id"].split(":", 1)[1] for c in ir["chunks"] if c["content_type"] != "image"}
    assert {r[1].split("~")[0] for r in chunk_rows} == text_chunk_keys         # 원천 청크 누락 0
    assert any(r[2] > 0 for r in chunk_rows), "긴 표 청크가 분할돼야 함"
    version = db.execute_query("SELECT * FROM tb_document_versions WHERE document_id = ?", (document_id,))[0]
    assert (version["status"], version["processing_engine"], version["md_dir"]) == ("active", "excel_ingest", str(out))
    assert version["file_sha256"] and json.loads(version["summary_json"])["sheet_count"] == 18
    doc = db.execute_query("SELECT doc_key, product_model, version_no FROM tb_documents WHERE document_id = ?",
                           (document_id,))[0]
    assert (doc["doc_key"], doc["product_model"], doc["version_no"]) == ("NEOCON_SAMPLE_XLSX", "NEOCON C2", 1)
    assert any(p.payload["text"].startswith("[NEOCON C2 > ") for p in points)  # 제품 모델 머리말(P2-11)

    # ── Phase 2: 사진 배치·연결(P2-4·8), 흐름도(P2-10) ──
    assert counts["resources"] == 190 and counts["chunk_resources"] > 0 and counts["flow_graphs"] == 1
    step6 = next(p.payload for p in points if p.payload["source_key"] == "09:step:6")
    assert step6["step_no"] == 6 and step6["resource_ids"]
    linked = db.execute_query(
        "SELECT r.step_no, r.role_cd, r.resource_path FROM tb_chunk_resources cr"
        " JOIN tb_chunks c ON c.chunk_id = cr.chunk_id JOIN tb_spreadsheet_resources r ON r.resource_id = cr.resource_id"
        " WHERE c.point_id::text = ?", (str(next(p.id for p in points if p.payload is step6)),))
    assert linked and all(r["step_no"] == 6 for r in linked)
    stored = list((tmp_path / "xl_res" / "documents" / document_id / "resources").glob("*/original/*"))
    assert len(stored) == 190
    assert all(rid.startswith(f"{document_id}-v1-i") for rid in step6["resource_ids"])
    needs_review = db.execute_query(
        "SELECT count(*) FROM tb_spreadsheet_resources WHERE document_id = ? AND review_status = 'needs_review'",
        (document_id,))[0][0]
    assert needs_review == result["excel_ingest"]["needs_review_count"]

    # ── 2026.10.22 추가 - 사진 전부 자동 연결(EXCEL_IMAGE_LINK_ALL): 장식·양식 머리글 22장 외 168장 모두 청크에 연결 ──
    links = result["excel_ingest"]["image_links"]
    assert (links["placements"], links["excluded"], links["linked"], links["unlinked"]) == (190, 22, 168, 0)
    not_linked = db.execute_query(
        "SELECT count(*) FROM tb_spreadsheet_resources r WHERE r.document_id = ?"
        " AND r.role_cd NOT IN ('decoration', 'form_header')"
        " AND NOT EXISTS (SELECT 1 FROM tb_chunk_resources cr WHERE cr.resource_id = r.resource_id)", (document_id,))
    assert not_linked[0][0] == 0
    linked_points = {rid for p in points for rid in p.payload.get("resource_ids") or []}
    assert len(linked_points) == 168                                            # Qdrant payload도 같은 연결
    wrong_step = db.execute_query(
        "SELECT count(*) FROM tb_chunk_resources cr JOIN tb_chunks c ON c.chunk_id = cr.chunk_id"
        " JOIN tb_spreadsheet_resources r ON r.resource_id = cr.resource_id"
        " WHERE c.document_id = ? AND c.content_type = 'step' AND r.step_no IS DISTINCT FROM c.step_no", (document_id,))
    assert wrong_step[0][0] == 0                                                # Step 청크에 다른 Step 사진 없음

    # ── 2026.10.19 추가 - Phase 4-A 답변 사진(완료 기준): Step 6 청크가 근거면 Step 6 사진이 후보 1순위, 인용 검증·자동 첨부 ──
    from app.graphs.images import collect_image_candidates, validate_answer_images

    query = "FAN 모듈 REACT FAN 조립 체크포인트"
    context = [{"chunk_id": "c1", "document_id": document_id, "text": step6["text"], "score": 0.9, "metadata": step6}]
    candidates = collect_image_candidates(context, query=query)
    assert candidates and candidates[0]["step_no"] == 6
    assert candidates[0]["role"] in ("step_photo", "same_image_as_step_photo")
    assert set(c["resource_id"] for c in candidates) <= set(step6["resource_ids"])
    cleaned, shown = validate_answer_images(f"REACT FAN을 조립합니다[1][IMG:{candidates[0]['ref']}][IMG:zz9999].",
                                            candidates, context_chunks=context)
    assert "[IMG:zz9999]" not in cleaned and [i["resource_id"] for i in shown] == [candidates[0]["resource_id"]]
    _, auto = validate_answer_images("REACT FAN을 조립합니다[1].", candidates, context_chunks=context)
    assert len(auto) == 1 and auto[0]["step_no"] == 6 and auto[0]["cited"] is False

    # ── 문서 삭제: 청크·연결·흐름도 행 삭제, 버전 retired, 사진·포인트 정리 ──
    service.delete_document(document_id)
    after = service.record_repo.count_by_document(document_id)
    assert (after["chunks"], after["chunk_resources"], after["flow_graphs"], after["resources"]) == (0, 0, 0, 0)
    assert db.execute_query("SELECT status FROM tb_document_versions WHERE document_id = ?",
                            (document_id,))[0][0] == "retired"
    assert not service.vector_repo.points["documents"]
    assert not (tmp_path / "xl_res" / "documents" / document_id).exists()


@pytest.mark.asyncio
async def test_three_concurrent_uploads_of_same_file_do_not_collide(backend_mode, md_root, tmp_path):
    job_ids = ["job-c1", "job-c2", "job-c3"]
    services = [_service(tmp_path / job_id, f"c-{job_id}") for job_id in job_ids]
    results = await asyncio.gather(*(
        IngestPipeline().run(service, _request(job_id, f"c-{job_id}"))
        for service, job_id in zip(services, job_ids)
    ))
    assert backend_mode == []
    base = md_root / "excel" / "NEOCON_SAMPLE_XLSX"
    for job_id, result in zip(job_ids, results):
        out = base / job_id
        assert Path(result["excel_ingest"]["md_dir"]) == out
        assert len(list((out / "sheets").glob("*.md"))) == 18
    assert not [p for p in base.parent.iterdir() if p.name.startswith(".staging")], "임시 폴더 잔존"
    assert (base / "LATEST").read_text() in job_ids
    # 같은 파일 3건: 문서·사진 ID 충돌 0(문서마다 배치 190행), 포인트 ID도 문서별로 다름
    db = get_database_manager()
    for result in results:
        assert db.execute_query("SELECT count(*) FROM tb_spreadsheet_resources WHERE document_id = ?",
                                (result["document_id"],))[0][0] == 190
    point_ids = [str(p.id) for service in services for pts in service.vector_repo.points.values() for p in pts]
    assert len(point_ids) == len(set(point_ids))

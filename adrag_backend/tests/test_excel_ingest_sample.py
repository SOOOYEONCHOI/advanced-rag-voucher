"""Phase 1·2 완료 기준 - 샘플 엑셀 통합 테스트.

샘플 경로: 환경변수 NEOCON_SAMPLE_XLSX, 없으면 저장소 루트 NEOCON_SAMPLE_XLSX.xlsx.
파일이 없으면 건너뛴다(대용량·사내 문서라 저장소에 넣지 않음).
2026.10.01 Phase 2: 적재 경로 끝까지(가짜 임베딩·Qdrant, 실제 PostgreSQL·resource 저장소) 진행한다.
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

pytestmark = pytest.mark.skipif(not SAMPLE.is_file(), reason="NEOCON_SAMPLE_XLSX 샘플 파일 없음")


def _Service(root: Path, collection: str = "documents"):
    """적재 경로 전체를 타는 서비스(외부 서버만 가짜). 같은 root면 이미지 저장소를 공유한다."""
    from excel_ingest_fakes import make_ingest_service

    service = make_ingest_service(root / "xl_res", root / "chunk", collection=collection)
    service.parse_and_chunk_calls = 0

    def _parse_and_chunk(*args, **kwargs):
        service.parse_and_chunk_calls += 1
        raise AssertionError("docling path must not run in backend mode")

    service._parse_and_chunk = _parse_and_chunk
    return service


def _request(job_id, collection: str = "documents"):
    return {
        "file_path": str(SAMPLE),
        "filename": SAMPLE.name,
        "collection_name": collection,
        "parser_type": "docling",
        "document_type": "auto",
        "job_id": job_id,
    }


@pytest.fixture(scope="module")
def md_root(tmp_path_factory):
    return tmp_path_factory.mktemp("parsed_md")


@pytest.fixture
def backend_mode(monkeypatch, md_root):
    docling_calls = []

    def forbidden(*args, **kwargs):
        docling_calls.append(1)
        raise AssertionError("docling must not be called")

    monkeypatch.setitem(processor.PARSER_REGISTRY, "docling", forbidden)
    monkeypatch.setattr(docling_loader.DoclingApiLoader, "load", forbidden)
    monkeypatch.setattr(
        ingest_pipeline,
        "get_settings",
        lambda: SimpleNamespace(
            excel_parse_mode="backend",
            md_save_dir=str(md_root),
            excel_md_keep_last=5,
            excel_xls_convert_timeout=120,
            resource_delivery="pull",
            max_chunk_size=800,
        ),
    )
    return docling_calls


def _summary_value(summary_md: str, label: str) -> str:
    match = re.search(rf"^\| {re.escape(label)} \| (.+?) \|$", summary_md, re.MULTILINE)
    assert match, label
    return match.group(1)


def _out_of_print_area_by_sheet(summary_md: str) -> dict:
    rows = {}
    for line in summary_md.splitlines():
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) == 11 and cells[0].isdigit():
            sheet = re.sub(r"^\[(.+)\]\(.+\)$", r"\1", cells[1])
            rows[sheet] = int(cells[9])
    return rows


@pytest.mark.asyncio
async def test_sample_upload_backend_mode_produces_expected_md(backend_mode, md_root, tmp_path):
    service = _Service(tmp_path)
    result = await IngestPipeline().run(service, _request("job-sample"))

    assert backend_mode == [], "docling 호출 0건"
    assert service.parse_and_chunk_calls == 0
    out = Path(result["excel_ingest"]["md_dir"])
    assert out == md_root / "excel" / "NEOCON_SAMPLE_XLSX" / "job-sample"

    # 생성 파일
    assert (out / "00_summary.md").is_file()
    assert (out / "chunks.md").is_file()
    assert (out / "ir.json").is_file()
    assert (out / "images").is_dir() and any((out / "images").iterdir())
    assert len(list((out / "sheets").glob("*.md"))) == 18

    # 00_summary.md 수치
    summary_md = (out / "00_summary.md").read_text(encoding="utf-8")
    assert _summary_value(summary_md, "시트 수") == "18"
    assert _summary_value(summary_md, "이미지 배치 / 고유 이미지") == "190 / 152"
    out_of_pa = _out_of_print_area_by_sheet(summary_md)
    assert sum(out_of_pa.values()) == 69
    assert out_of_pa["수입검사성적서(가공품)"] == 5
    assert out_of_pa["Recheck Sheet"] == 64

    # 안내문 청크
    chunks_md = (out / "chunks.md").read_text(encoding="utf-8")
    assert GUIDE_NOTE_TEXT in chunks_md
    ir = json.loads((out / "ir.json").read_text(encoding="utf-8"))
    assert any(
        c["content_type"] == "guide_note"
        and c["sheet"] == "수입검사성적서(가공품)"
        and GUIDE_NOTE_TEXT in c["text"]
        for c in ir["chunks"]
    )

    # job 결과 요약도 같은 수치
    s = result["excel_ingest"]
    assert (s["sheet_count"], s["image_placement_count"], s["unique_image_count"], s["out_of_print_area_count"]) == (
        18, 190, 152, 69,
    )

    # ── Phase 2 완료 기준: 적재 ──
    assert result["indexed"] is True
    document_id = result["document_id"]
    db = service.db
    count = lambda sql, *p: db.execute_query(sql, p)[0][0]  # noqa: E731
    assert count("SELECT count(*) FROM tb_image_placements WHERE document_id=?", document_id) == 190
    assert count("SELECT count(*) FROM tb_image_assets") == 152
    assert s["new_asset_count"] == 152
    assert count("SELECT count(*) FROM tb_flow_graphs WHERE document_id=?", document_id) == 1
    points = service.vector_repo.points["documents"]
    assert count("SELECT count(*) FROM tb_chunks WHERE document_id=?", document_id) == len(points)
    # 청크 길이는 MAX_CHUNK_SIZE(800자) 이하, 원본 296개 청크는 모두 적재(분할 조각 포함)
    assert max(len(p.payload["text"]) for p in points) <= 800
    assert {p.payload["source_chunk_id"] for p in points} >= {
        "NEOCON_SAMPLE_XLSX:09:step:6", "NEOCON_SAMPLE_XLSX:04:guide_note:12", "NEOCON_SAMPLE_XLSX:10:summary:0",
    }
    assert len({p.payload["source_chunk_id"] for p in points}) == 295  # Step 0 중복 ID 1건은 같은 원본 ID
    # Step 청크는 Step 사진(전체 sha256)을 참조하고, 그 이미지는 placement로 찾을 수 있다.
    step6 = next(p.payload for p in points if p.payload["chunk_key"] == "NEOCON_SAMPLE_XLSX:09:step:6")
    assert step6["step_no"] == 6 and step6["section_type"] == "sop" and step6["image_ids"]
    assert count(
        "SELECT count(*) FROM tb_image_placements WHERE document_id=? AND image_id=? AND step_no=6",
        document_id, step6["image_ids"][0],
    ) >= 1
    # 이미지 파일은 해시 기준 공유 위치에 한 번만 저장된다(emf 1장은 PNG 변환을 시도한다).
    stored_names = {p.stem for p in (tmp_path / "xl_res" / "assets").glob("*/*")}
    assert len(stored_names) == 152
    assert count("SELECT count(*) FROM tb_image_assets WHERE conversion_status <> 'not_required'") == 1

    # 같은 파일 재적재: asset 증가 0, placement는 새 문서 기준 190
    # 같은 컬렉션 재업로드는 Phase 3부터 duplicate(skipped) — 다른 컬렉션에 적재해 asset 공유를 확인
    again = await IngestPipeline().run(_Service(tmp_path, "documents-2"), _request("job-sample-2", "documents-2"))
    assert again["excel_ingest"]["new_asset_count"] == 0
    assert count("SELECT count(*) FROM tb_image_assets") == 152
    assert count("SELECT count(*) FROM tb_image_placements WHERE document_id=?", again["document_id"]) == 190


@pytest.mark.asyncio
async def test_three_concurrent_uploads_of_same_file_do_not_collide(backend_mode, md_root, tmp_path):
    job_ids = ["job-c1", "job-c2", "job-c3"]
    results = await asyncio.gather(
        *(IngestPipeline().run(_Service(tmp_path, f"c-{job_id}"), _request(job_id, f"c-{job_id}")) for job_id in job_ids)
    )

    assert backend_mode == []
    base = md_root / "excel" / "NEOCON_SAMPLE_XLSX"
    for job_id, result in zip(job_ids, results):
        out = base / job_id
        assert Path(result["excel_ingest"]["md_dir"]) == out
        assert len(list((out / "sheets").glob("*.md"))) == 18
        assert len(list((out / "images").iterdir())) >= 152
        for name in ("00_summary.md", "chunks.md", "ir.json"):
            assert (out / name).is_file(), f"{job_id}/{name} 누락"
    # 임시 폴더 잔존 없음, LATEST는 세 job 중 하나
    assert not [p for p in base.iterdir() if p.name.startswith(".")]
    assert (base / "LATEST").read_text() in job_ids
    # 2026.10.01 추가 - 같은 이미지 저장소를 공유해도 asset은 152건, 문서별 placement는 190건
    db = get_database_manager()
    assert db.execute_query("SELECT count(*) FROM tb_image_assets")[0][0] == 152
    assert sum(r["excel_ingest"]["new_asset_count"] for r in results) == 152
    for result in results:
        assert db.execute_query(
            "SELECT count(*) FROM tb_image_placements WHERE document_id=?", (result["document_id"],)
        )[0][0] == 190
    assets_root = tmp_path / "xl_res" / "assets"
    assert not [p for p in assets_root.rglob(".*") if p.is_file()], "임시 파일 잔존"

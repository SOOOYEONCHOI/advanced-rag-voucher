"""단계 7 수식 정책과 병합 헤더 문맥의 backend 계약 테스트."""

# 2026.08.27(sooyeon.choi) 추가 - REQ-QUALITY-002/003 backend 회귀 테스트
import pytest

from app.parsers.chunkers.spreadsheet import SpreadsheetChunker
from app.parsers.config import ChunkingConfig
from app.parsers.metadata_extractor import build_unified_payload
from app.parsers.models import LCDocument


def _sheet_document(blocks, **metadata):
    return LCDocument(
        page_content="사용하지 않는 시트 전체 텍스트",
        metadata={
            "document_id": "doc-1",
            "schema_name": "StructuredSpreadsheet",
            "schema_version": "1.0",
            "sheet_id": "sheet-1",
            "sheet_index": 1,
            "sheet_name": "실적",
            "formula_recalculated": False,
            "structured_ir": {"blocks": blocks},
            **metadata,
        },
    )


def _formula_record(row, item, amount, cache_status="available"):
    return {
        "record_id": f"sheet-1:row-{row}",
        "source_range": f"A{row}:B{row}",
        "row_start": row,
        "row_end": row,
        "values": [item, amount],
        "physical_values": [item, amount],
        "inherited_cells": [],
        "formulas": [{
            "coordinate": f"B{row}",
            "formula": f"=C{row}*D{row}",
            "cached_value": amount,
            "cache_status": cache_status,
        }],
        "resource_ids": [],
    }


def _formula_block(records, **extra):
    return {
        "block_id": "sheet-1:block-1",
        "block_index": 1,
        "block_type": "record_table",
        "source_range": "A1:B3",
        "header_range": "A1:B1",
        "headers": ["항목", "금액"],
        "header_paths": [["구분", "항목"], ["2026년", "금액"]],
        "records": records,
        "resource_ids": [],
        "formula_cell_count": len(records),
        "formula_ratio": 1.0,
        "formula_dominant": True,
        **extra,
    }


def _chunks(config, blocks, **document_metadata):
    document = _sheet_document(blocks, **document_metadata)
    return SpreadsheetChunker(config).split_documents([document])


# ── REQ-QUALITY-002 수식 정책 ──────────────────────────────────────────────

def test_default_embedding_uses_display_values_only():
    config = ChunkingConfig(
        spreadsheet_formula_embedding="off", spreadsheet_summary_chunks=False
    )
    chunk = _chunks(config, [_formula_block([_formula_record(2, "모터", "200")])])[0]

    assert "수식:" not in chunk.page_content
    assert "항목: 모터 | 금액: 200" in chunk.page_content


def test_auto_policy_appends_formula_only_for_formula_dominant_block():
    config = ChunkingConfig(spreadsheet_summary_chunks=False)
    assert config.spreadsheet_formula_embedding == "auto"

    dominant = _chunks(config, [_formula_block([_formula_record(2, "모터", "200")])])[0]
    assert "수식: B2=C2*D2" in dominant.page_content

    value_block = _formula_block(
        [_formula_record(2, "모터", "200")], formula_dominant=False, formula_ratio=0.1
    )
    plain = _chunks(config, [value_block])[0]
    assert "수식:" not in plain.page_content


def test_always_policy_appends_formula_for_every_block():
    config = ChunkingConfig(
        spreadsheet_formula_embedding="always", spreadsheet_summary_chunks=False
    )
    block = _formula_block(
        [_formula_record(2, "모터", "200")], formula_dominant=False, formula_ratio=0.1
    )
    chunk = _chunks(config, [block])[0]

    assert "수식: B2=C2*D2" in chunk.page_content


def test_formula_manifest_is_stored_in_chunk_metadata_with_cap():
    config = ChunkingConfig(
        spreadsheet_summary_chunks=False,
        spreadsheet_max_formula_manifest=2,
        spreadsheet_max_records_per_chunk=10,
    )
    records = [
        _formula_record(2, "모터", "200"),
        _formula_record(3, "펌프", "300", cache_status="stale"),
        _formula_record(4, "밸브", "400", cache_status="missing"),
    ]
    chunk = _chunks(config, [_formula_block(records)])[0]
    metadata = chunk.metadata

    assert metadata["formula_count"] == 3
    assert len(metadata["formula_manifest"]) == 2
    assert metadata["formula_manifest_truncated"] is True
    assert metadata["formula_manifest"][0] == {
        "record_id": "sheet-1:row-2",
        "coordinate": "B2",
        "formula": "=C2*D2",
        "cached_value": "200",
        "cache_status": "available",
    }
    # 캐시 위험도가 가장 높은 상태를 chunk 요약으로 남긴다.
    assert metadata["formula_cache_status"] == "missing"
    assert metadata["formula_recalculated"] is False
    assert metadata["formula_dominant"] is True


def test_formula_recalculated_falls_back_to_workbook_metadata():
    config = ChunkingConfig(spreadsheet_summary_chunks=False)
    document = LCDocument(
        page_content="",
        metadata={
            "sheet_id": "sheet-1",
            "sheet_index": 1,
            "sheet_name": "실적",
            "schema_version": "1.0",
            # loader는 workbook 문서 metadata를 workbook_metadata로 감싸 전달한다.
            "workbook_metadata": {"formula_recalculated": False, "formula_cache_stale": True},
            "structured_ir": {"blocks": [_formula_block([_formula_record(2, "모터", "200")])]},
        },
    )
    metadata = SpreadsheetChunker(config).split_documents([document])[0].metadata

    assert metadata["formula_recalculated"] is False


def test_value_only_chunk_reports_no_formula_manifest():
    config = ChunkingConfig(spreadsheet_summary_chunks=False)
    block = {
        "block_id": "sheet-1:block-2",
        "block_index": 2,
        "block_type": "record_table",
        "source_range": "A1:B2",
        "headers": ["항목", "수량"],
        "records": [{
            "record_id": "sheet-1:row-2",
            "source_range": "A2:B2",
            "row_start": 2,
            "row_end": 2,
            "values": ["모터", "2"],
            "resource_ids": [],
        }],
        "resource_ids": [],
    }
    metadata = _chunks(config, [block])[0].metadata

    assert metadata["formula_count"] == 0
    assert metadata["formula_manifest"] == []
    assert metadata["formula_manifest_truncated"] is False
    assert metadata["formula_cache_status"] == "not_applicable"
    assert metadata["formula_dominant"] is False


# ── REQ-QUALITY-003 병합 헤더 문맥 ─────────────────────────────────────────

def test_header_paths_and_cross_block_merge_reach_chunk_metadata():
    config = ChunkingConfig(spreadsheet_summary_chunks=False)
    block = _formula_block([_formula_record(2, "모터", "200")], cross_block_merge=True)
    metadata = _chunks(config, [block])[0].metadata

    assert metadata["header_paths"] == [["구분", "항목"], ["2026년", "금액"]]
    assert "cross_block_merge" in metadata["warning_codes"]


def test_cross_block_merge_warning_is_not_duplicated():
    config = ChunkingConfig(spreadsheet_summary_chunks=False)
    block = _formula_block(
        [_formula_record(2, "모터", "200")],
        cross_block_merge=True,
        warning_codes=["cross_block_merge"],
    )
    metadata = _chunks(config, [block])[0].metadata

    assert metadata["warning_codes"].count("cross_block_merge") == 1


# ── payload 계약 ───────────────────────────────────────────────────────────

def test_quality_fields_are_written_to_qdrant_payload():
    config = ChunkingConfig(spreadsheet_summary_chunks=False)
    chunk = _chunks(config, [_formula_block([_formula_record(2, "모터", "200")])])[0]

    payload = build_unified_payload(
        document_id="doc-1",
        chunk_id="chunk-1",
        chunk_index=0,
        chunk_text=chunk.page_content,
        chunk_meta=chunk.metadata,
        source_path="/data/sample.xlsx",
        original_filename="sample.xlsx",
        source_collection="parts",
        document_type="spreadsheet",
    )

    assert payload["header_paths"] == [["구분", "항목"], ["2026년", "금액"]]
    assert payload["formula_count"] == 1
    assert payload["formula_manifest"][0]["formula"] == "=C2*D2"
    assert payload["formula_manifest_truncated"] is False
    assert payload["formula_cache_status"] == "available"
    assert payload["formula_dominant"] is True
    assert payload["formula_recalculated"] is False
    # 전체 cell IR은 payload에 포함하지 않는다.
    assert "structured_ir" not in payload
    assert "cells" not in payload


# ── 설정 검증 ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("policy", ["", "on", "formula", None])
def test_invalid_formula_policy_is_rejected(policy):
    with pytest.raises(ValueError, match="spreadsheet_formula_embedding"):
        ChunkingConfig(spreadsheet_formula_embedding=policy)


def test_negative_formula_manifest_cap_is_rejected():
    with pytest.raises(ValueError, match="spreadsheet_max_formula_manifest"):
        ChunkingConfig(spreadsheet_max_formula_manifest=-1)

"""SpreadsheetChunker IR 경계 및 metadata 회귀 테스트."""

# 2026.08.27(sooyeon.choi) 추가 - 단계 4 Excel 전용 청킹 검증
import pytest

from app.parsers.chunkers.spreadsheet import SpreadsheetChunker
from app.parsers.config import ChunkingConfig
from app.parsers.models import LCDocument


def _sheet_document(blocks):
    return LCDocument(
        page_content="사용하지 않는 시트 전체 텍스트",
        metadata={
            "document_id": "doc-1",
            "schema_name": "StructuredSpreadsheet",
            "schema_version": "1.0",
            "sheet_id": "sheet-3",
            "sheet_index": 3,
            "sheet_name": "부품",
            "structured_ir": {"blocks": blocks},
        },
    )


def _record(row, name, quantity="1", **extra):
    return {
        "record_id": f"sheet-3:row-{row}",
        "source_range": f"A{row}:B{row}",
        "row_start": row,
        "row_end": row,
        "values": [name, quantity],
        "resource_ids": [],
        **extra,
    }


def _block(block_type="record_table", records=None):
    return {
        "block_id": "sheet-3:block-1",
        "block_index": 1,
        "block_type": block_type,
        "source_range": "A1:B4",
        "header_range": "A1:B1",
        "headers": ["품명", "수량"],
        "records": records or [_record(2, "모터"), _record(3, "볼트"), _record(4, "너트")],
        "resource_ids": ["resource-1"],
    }


def test_record_table_preserves_record_boundary_and_repeats_headers():
    config = ChunkingConfig(
        spreadsheet_max_records_per_chunk=2,
        spreadsheet_summary_chunks=False,
    )
    chunks = SpreadsheetChunker(config).split_documents([_sheet_document([_block()])])

    assert len(chunks) == 2
    assert [chunk.metadata["record_ids"] for chunk in chunks] == [
        ["sheet-3:row-2", "sheet-3:row-3"],
        ["sheet-3:row-4"],
    ]
    assert chunks[0].metadata["chunk_key"] == "sheet-3:block-1:record_group:2-3"
    assert chunks[0].metadata["source_range"] == "A2:B3"
    assert chunks[1].metadata["chunk_key"] == "sheet-3:block-1:record_group:4-4"
    assert all(chunk.metadata["record_count"] == len(chunk.metadata["record_ids"]) for chunk in chunks)
    assert all("헤더: 품명 | 수량" in chunk.page_content for chunk in chunks)
    assert all("| 품명 | 수량 |" in chunk.metadata["display_markdown"] for chunk in chunks)


def test_oversized_record_is_split_by_header_value_fields():
    block = _block(records=[_record(2, "아주 긴 부품 이름", "아주 많은 수량")])
    config = ChunkingConfig(
        spreadsheet_max_embedding_chars=30,
        spreadsheet_max_embedding_tokens=20,
        spreadsheet_summary_chunks=False,
    )
    chunks = SpreadsheetChunker(config).split_documents([_sheet_document([block])])

    assert len(chunks) == 2
    assert "품명: 아주 긴 부품 이름" in chunks[0].page_content
    assert "수량: 아주 많은 수량" in chunks[1].page_content
    assert all(len(chunk.page_content) <= 30 for chunk in chunks)
    assert [chunk.metadata["split_part"] for chunk in chunks] == [1, 2]
    assert all(chunk.metadata["split_part_count"] == 2 for chunk in chunks)
    assert all(chunk.metadata["record_ids"] == ["sheet-3:row-2"] for chunk in chunks)
    assert all(chunk.metadata["resource_ids"] == ["resource-1"] for chunk in chunks)
    assert [chunk.metadata["chunk_key"] for chunk in chunks] == [
        "sheet-3:block-1:record_group:2-2:part-1",
        "sheet-3:block-1:record_group:2-2:part-2",
    ]


def test_single_oversized_field_repeats_label_across_parts():
    block = _block(records=[_record(2, "가" * 80, "")])
    config = ChunkingConfig(
        spreadsheet_max_embedding_chars=35,
        spreadsheet_max_embedding_tokens=100,
        spreadsheet_summary_chunks=False,
    )

    chunks = SpreadsheetChunker(config).split_documents([_sheet_document([block])])

    assert len(chunks) > 1
    assert all(len(chunk.page_content) <= 35 for chunk in chunks)
    assert all("품명: " in chunk.page_content for chunk in chunks)
    assert "".join(chunk.page_content.split("품명: ", 1)[1] for chunk in chunks) == "가" * 80


def test_merged_inherited_cells_are_collapsed_by_source_for_embedding_only():
    record = {
        "record_id": "sheet-3:row-2",
        "source_range": "A2:C2",
        "row_start": 2,
        "row_end": 2,
        "values": ["동일 설명", "동일 설명", "동일 설명"],
        "physical_values": ["동일 설명", "", ""],
        "resource_ids": [],
        "cells": [
            {"coordinate": "A2", "is_merge_anchor": True, "merged_range": "A2:C2", "inherited_from": None},
            {"coordinate": "B2", "is_merge_anchor": False, "merged_range": "A2:C2", "inherited_from": "A2"},
            {"coordinate": "C2", "is_merge_anchor": False, "merged_range": "A2:C2", "inherited_from": "A2"},
        ],
    }
    block = {**_block(records=[record]), "headers": ["기준 A", "기준 B", "기준 C"]}

    chunks = SpreadsheetChunker(ChunkingConfig(spreadsheet_summary_chunks=False)).split_documents(
        [_sheet_document([block])]
    )

    assert len(chunks) == 1
    assert chunks[0].page_content.count("동일 설명") == 1
    assert "적용 헤더: 기준 A | 기준 B | 기준 C" in chunks[0].page_content
    assert chunks[0].metadata["display_markdown"].count("동일 설명") == 3


def test_equal_values_from_different_merge_sources_are_preserved():
    record = {
        "record_id": "sheet-3:row-2",
        "source_range": "A2:B2",
        "row_start": 2,
        "row_end": 2,
        "values": ["정상", "정상"],
        "resource_ids": [],
        "cells": [
            {"coordinate": "A2", "inherited_from": "A1"},
            {"coordinate": "B2", "inherited_from": "B1"},
        ],
    }
    block = _block(records=[record])

    chunks = SpreadsheetChunker(ChunkingConfig(spreadsheet_summary_chunks=False)).split_documents(
        [_sheet_document([block])]
    )

    assert chunks[0].page_content.count("정상") == 2


@pytest.mark.parametrize(
    "block_type",
    ["key_value", "form", "matrix", "timeseries", "unknown_table", "metadata", "card_grid", "process_flow", "image_gallery", "resource_group"],
)
def test_structured_record_block_types_use_record_group_fallback(block_type):
    block = _block(block_type=block_type, records=[_record(2, "모터")])
    chunks = SpreadsheetChunker(ChunkingConfig(spreadsheet_summary_chunks=False)).split_documents(
        [_sheet_document([block])]
    )

    assert len(chunks) == 1
    assert chunks[0].metadata["block_type"] == block_type
    assert chunks[0].metadata["chunk_type"] == "record_group"


def test_timeseries_prefers_natural_month_boundary():
    records = [
        _record(2, "매출", period="2026-01-31"),
        _record(3, "매출", period="2026-02-01"),
    ]
    block = {**_block("timeseries", records), "period_unit": "month", "metric_names": ["매출"]}
    chunks = SpreadsheetChunker(ChunkingConfig(spreadsheet_summary_chunks=False)).split_documents(
        [_sheet_document([block])]
    )

    assert [chunk.metadata["period_start"] for chunk in chunks] == ["2026-01-31", "2026-02-01"]
    assert [chunk.metadata["period_end"] for chunk in chunks] == ["2026-01-31", "2026-02-01"]


def test_summary_chunk_is_deterministic_and_empty_block_is_skipped():
    document = _sheet_document([_block(records=[_record(2, "모터")]), {
        "block_id": "sheet-3:block-2",
        "block_index": 2,
        "block_type": "empty",
        "source_range": "C1:C1",
        "records": [],
    }])
    chunker = SpreadsheetChunker(ChunkingConfig(spreadsheet_summary_chunks=True))

    first = chunker.split_documents([document])
    second = chunker.split_documents([document])
    summaries = [chunk for chunk in first if chunk.metadata["chunk_type"] == "table_summary"]

    assert len(first) == 2
    assert len(summaries) == 1
    assert summaries[0].metadata["chunk_key"] == "sheet-3:block-1:table_summary:A1:B4"
    assert summaries[0].page_content == second[1].page_content
    assert "레코드 수: 1" in summaries[0].page_content
    assert "리소스 수: 1" in summaries[0].page_content


def test_canonical_spreadsheet_limits_must_be_positive():
    with pytest.raises(ValueError, match="spreadsheet_max_records_per_chunk"):
        ChunkingConfig(spreadsheet_max_records_per_chunk=0)

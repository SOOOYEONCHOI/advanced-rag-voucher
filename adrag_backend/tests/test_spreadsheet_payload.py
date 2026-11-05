"""Spreadsheet Qdrant payload와 인덱스 계약 테스트."""

# 2026.08.27(sooyeon.choi) 추가 - 단계 5 compact payload 검증
from types import SimpleNamespace

from app.parsers.metadata_extractor import build_unified_payload
from app.repositories.vector_repository import VectorRepository


SPREADSHEET_FIELDS = {
    "document_type",
    "text",
    "display_markdown",
    "content_type",
    "sheet_id",
    "sheet_index",
    "sheet_name",
    "block_id",
    "block_index",
    "block_type",
    "chunk_type",
    "source_range",
    "row_start",
    "row_end",
    "header_range",
    "headers",
    "record_ids",
    "record_count",
    "resource_ids",
    "chunk_key",
    "warning_codes",
    "spreadsheet_schema_version",
    "embedding_text_version",
    "display_format_version",
}


def test_spreadsheet_payload_is_compact_and_preserves_required_fields():
    metadata = {
        "content_type": "spreadsheet_record_group",
        "display_markdown": "| 품명 | 수량 |\n| --- | --- |\n| 모터 | 2 |",
        "sheet_id": "sheet-1",
        "sheet_index": 1,
        "sheet_name": "부품",
        "block_id": "sheet-1:block-1",
        "block_index": 1,
        "block_type": "record_table",
        "chunk_type": "record_group",
        "source_range": "A2:B2",
        "row_start": 2,
        "row_end": 2,
        "header_range": "A1:B1",
        "headers": ["품명", "수량"],
        "record_ids": ["sheet-1:row-2"],
        "record_count": 1,
        "resource_ids": ["resource-1"],
        "chunk_key": "sheet-1:block-1:record_group:2-2",
        "warning_codes": [],
        "spreadsheet_schema_version": "1.0",
        "embedding_text_version": "header-value-v1",
        "display_format_version": "markdown-table-v1",
        "structured_ir": {"blocks": [{"cells": ["large"]}]},
        "cells": ["must-not-be-copied"],
    }

    payload = build_unified_payload(
        document_id="doc-1",
        chunk_id="chunk-1",
        chunk_index=0,
        chunk_text="품명: 모터 | 수량: 2",
        chunk_meta=metadata,
        original_filename="parts.xlsx",
        document_type="spreadsheet",
        file_format="xlsx",
    )

    assert SPREADSHEET_FIELDS <= payload.keys()
    assert payload["text"] == "품명: 모터 | 수량: 2"
    assert payload["content_type"] == "spreadsheet_record_group"
    assert payload["display_markdown"].startswith("| 품명 |")
    assert "structured_ir" not in payload
    assert "cells" not in payload


def test_non_spreadsheet_payload_does_not_gain_spreadsheet_fields():
    payload = build_unified_payload(
        document_id="doc-1",
        chunk_id="chunk-1",
        chunk_index=0,
        chunk_text="일반 문서",
        chunk_meta={},
        document_type="general",
    )

    assert "sheet_name" not in payload
    assert payload["content_type"] == "text"


def test_payload_indexes_include_spreadsheet_filter_fields():
    calls = []
    repository = object.__new__(VectorRepository)
    repository.client = SimpleNamespace(
        create_payload_index=lambda **kwargs: calls.append(kwargs)
    )

    assert repository.ensure_payload_indexes("documents") is True
    assert {call["field_name"] for call in calls} >= {
        "document_id",
        "document_type",
        "sheet_index",
        "sheet_name",
        "block_type",
        "chunk_type",
        "content_type",
        "resource_ids",
    }

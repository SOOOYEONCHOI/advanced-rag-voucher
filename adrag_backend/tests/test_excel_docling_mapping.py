"""Excel 전용 Docling API 응답 매핑 테스트."""

from types import SimpleNamespace

# 2026.08.18(sooyeon.choi) excel 후처리 로직 추가
from app.parsers.loaders.docling_loader import DoclingApiLoader
from app.parsers import processor
from app.parsers.config import ChunkingConfig


def test_excel_mapping_uses_embedding_text_and_preserves_asset_metadata():
    loader = DoclingApiLoader.__new__(DoclingApiLoader)
    output = {
        # 2026.08.27(sooyeon.choi) 수정 - StructuredSpreadsheet 1.0 계약 fixture
        "schema_name": "StructuredSpreadsheet",
        "schema_version": "1.0",
        "num_pages": 1,
        "metadata": {
            "document_id": "doc-123",
            "processing_engine": "ir",
            "processing_path": "structured_ir",
        },
        "pages": [{
            "page_no": 1,
            "sheet_name": "핵심 부품 List",
            "sheet_index": 6,
            "markdown": "# Sheet: 핵심 부품 List\n\n[이미지 자산: ⟦IMG:asset-1⟧]",
            "embedding_text": "시트: 핵심 부품 List\n번호: 1\n수량: 1",
            "blocks": [{
                "block_index": 1,
                "block_id": "sheet-6:block-1",
                "block_type": "table",
                "source_range": "A1:B2",
                "headers": ["번호", "수량"],
                "rows": [["1", "1"]],
                "records": [],
                "asset_ids": ["asset-1"],
            }],
            "metadata": {
                "source_range": "A1:B2",
                "truncated": False,
                "warnings": [],
                "asset_ids": ["asset-1"],
            },
        }],
    }

    mapped = loader._map_result(output, "sample.xlsx", "xlsx")

    assert mapped[0]["text"] == "시트: 핵심 부품 List\n번호: 1\n수량: 1"
    assert "asset-1" not in mapped[0]["text"]
    assert mapped[0]["metadata"]["document_id"] == "doc-123"
    assert mapped[0]["metadata"]["sheet_index"] == 6
    assert mapped[0]["metadata"]["asset_ids"] == ["asset-1"]
    assert mapped[0]["metadata"]["blocks"][0]["block_id"] == "sheet-6:block-1"
    assert mapped[0]["metadata"]["source_range"] == "A1:B2"
    assert "⟦IMG:asset-1⟧" in mapped[0]["metadata"]["display_markdown"]
    # 2026.08.27(sooyeon.choi) 수정 - parser IR 처리 metadata 무손실 전달
    assert mapped[0]["metadata"]["processing_engine"] == "ir"
    assert mapped[0]["metadata"]["processing_path"] == "structured_ir"


def test_excel_processor_passes_document_id_to_docling_loader(monkeypatch):
    received = {}
    loader = DoclingApiLoader.__new__(DoclingApiLoader)

    def load(file_path, document_id=None):
        received["file_path"] = file_path
        received["document_id"] = document_id
        return []

    loader.load = load
    monkeypatch.setitem(processor.PARSER_REGISTRY, "docling", lambda: loader)
    monkeypatch.setattr(
        processor,
        "get_settings",
        lambda: SimpleNamespace(md_save_dir=None),
    )

    result = processor.DocumentChunkingProcessor().process(
        "sample.xlsx",
        document_id="doc-123",
    )

    assert received == {"file_path": "sample.xlsx", "document_id": "doc-123"}
    assert result["file_type"] == "xlsx"
    # 2026.08.20(sooyeon.choi) 수정 - Excel 문서 유형을 spreadsheet로 고정
    assert result["doc_type"] == "spreadsheet"


# 2026.08.27(sooyeon.choi) 수정 - 단계 3 Parser IR의 시트 문서 무손실 변환 검증
def test_excel_processor_builds_structured_spreadsheet_sheet_document(monkeypatch):
    loader = DoclingApiLoader.__new__(DoclingApiLoader)
    output = {
        "schema_name": "StructuredSpreadsheet",
        "schema_version": "1.0",
        "num_pages": 1,
        "metadata": {"document_id": "doc-structured"},
        "pages": [{
            "page_no": 1,
            "sheet_name": "부품",
            "sheet_index": 2,
            "markdown": "# Sheet: 부품\n\n| 번호 | 품명 | 수량 |\n| --- | --- | --- |\n| 1 | 모터 | 2 |",
            "embedding_text": "시트: 부품\n번호 | 품명 | 수량\n1 | 모터 | 2",
            "blocks": [{
                "block_index": 1,
                "block_id": "sheet-2:block-1",
                "block_type": "record_table",
                "source_range": "A1:C2",
                "header_row_count": 1,
                "headers": ["번호", "품명", "수량"],
                "rows": [["1", "모터", "2"]],
                "records": [
                    {"record_id": "sheet-2:row-2", "source_range": "A2:C2", "values": ["1", "모터", "2"], "cells": [], "resource_ids": []},
                ],
                "asset_ids": [],
            }],
            "metadata": {"source_range": "A1:C2", "asset_ids": []},
        }],
    }

    loader.load = lambda file_path, document_id=None: loader._map_result(
        output, file_path, "xlsx"
    )
    monkeypatch.setitem(processor.PARSER_REGISTRY, "docling", lambda: loader)
    monkeypatch.setattr(
        processor,
        "get_settings",
        lambda: SimpleNamespace(md_save_dir=None),
    )

    result = processor.DocumentChunkingProcessor(
        ChunkingConfig(spreadsheet_summary_chunks=False)
    ).process(
        "sample.xlsx",
        document_id="doc-structured",
    )

    assert result["doc_type"] == "spreadsheet"
    assert result["chunk_count"] == 1
    chunk = result["chunks"][0]
    assert "품명: 모터" in chunk.page_content
    assert "| 번호 | 품명 | 수량 |" in chunk.metadata["display_markdown"]
    assert chunk.metadata["sheet_name"] == "부품"
    assert chunk.metadata["sheet_index"] == 2
    assert chunk.metadata["source_range"] == "A2:C2"
    assert chunk.metadata["document_id"] == "doc-structured"
    assert chunk.metadata["document_type"] == "spreadsheet"
    assert chunk.metadata["structured_ir"]["schema_version"] == "1.0"
    assert chunk.metadata["structured_ir"]["blocks"][0]["records"][0]["record_id"] == "sheet-2:row-2"
    assert chunk.metadata["chunk_key"] == "sheet-2:block-1:record_group:2-2"
    assert chunk.metadata["record_count"] == 1

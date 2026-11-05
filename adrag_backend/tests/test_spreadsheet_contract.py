"""Excel 정형 파싱 1단계 계약 테스트."""

# 2026.08.27(sooyeon.choi) 추가 - 확장자와 IR major version 회귀 검증
import pytest

from app.parsers.spreadsheet_contract import (
    OOXML_SPREADSHEET_EXTENSIONS,
    SpreadsheetContractError,
    validate_spreadsheet_ir,
)
from app.parsers.processor import DocumentChunkingProcessor


def test_ooxml_spreadsheet_extensions_are_canonical():
    assert OOXML_SPREADSHEET_EXTENSIONS == {"xlsx", "xlsm", "xltx", "xltm"}
    assert "xls" not in OOXML_SPREADSHEET_EXTENSIONS


@pytest.mark.parametrize("version", ["1.0", "1.1", "1.99"])
def test_accepts_supported_spreadsheet_ir_major(version):
    validate_spreadsheet_ir({
        "schema_name": "StructuredSpreadsheet",
        "schema_version": version,
        "pages": [],
    })


@pytest.mark.parametrize(
    "result",
    [
        {"schema_version": "1.0", "pages": []},
        {"schema_name": "StructuredSpreadsheet", "pages": []},
        {"schema_name": "StructuredSpreadsheet", "schema_version": "2.0", "pages": []},
        {"schema_name": "StructuredSpreadsheet", "schema_version": "1.0"},
    ],
)
def test_rejects_invalid_spreadsheet_ir(result):
    with pytest.raises(SpreadsheetContractError):
        validate_spreadsheet_ir(result)


def test_excel_type_precedes_content_detectors():
    # 2026.08.27(sooyeon.choi) 추가 - 법령/매뉴얼 문구가 있어도 spreadsheet 고정
    result = DocumentChunkingProcessor().process(
        "sample.XLSX",
        md_meta=[{
            "text": "제1조 목적\n제2조 정의\n① 설정 버튼을 클릭한다.",
            "metadata": {"page": 1},
        }],
    )

    assert result["doc_type"] == "spreadsheet"
    assert result["is_law"] is False
    assert result["is_manual"] is False


def test_normalizes_legacy_block_types_and_rejects_unknown_type():
    # 2026.08.27(sooyeon.choi) 추가 - 단계 2 정본 block type 계약
    legacy = {
        "schema_name": "StructuredSpreadsheet",
        "schema_version": "1.0",
        "pages": [{"blocks": [{"block_type": "table"}, {"type": "text"}]}],
    }
    validate_spreadsheet_ir(legacy)
    assert [block["block_type"] for block in legacy["pages"][0]["blocks"]] == [
        "record_table", "paragraph"
    ]

    invalid = {
        "schema_name": "StructuredSpreadsheet",
        "schema_version": "1.0",
        "pages": [{"blocks": [{"block_type": "unsupported"}]}],
    }
    with pytest.raises(SpreadsheetContractError, match="block_type"):
        validate_spreadsheet_ir(invalid)

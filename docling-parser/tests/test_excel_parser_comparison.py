"""동일 Excel 파일의 OpenPyXL/Docling 실제 파싱 결과 비교 테스트."""

# 2026.08.13(sooyeon.choi) 수정 - 두 실제 Excel 파서의 결과 파일 생성 및 비교
import asyncio
import json
import os
from pathlib import Path

import pytest

# 2026.08.13(sooyeon.choi) 수정 - Docling 미설치 환경에서는 통합 비교 테스트 제외
pytest.importorskip("docling", reason="Real parser comparison requires Docling")

from app.services.parser import DocumentParser


def _write_result(output_dir: Path, parser_name: str, result: dict) -> None:
    pages = result.get("pages", [])
    markdown = "\n\n".join(
        page.get("markdown", "") for page in pages if page.get("markdown")
    )
    (output_dir / f"{parser_name}_result.md").write_text(
        markdown,
        encoding="utf-8",
    )


def _result_summary(result: dict) -> dict:
    markdown = "\n".join(
        page.get("markdown", "") for page in result.get("pages", [])
    )
    return {
        "parser": result.get("metadata", {}).get("parser"),
        "num_pages": result.get("num_pages", 0),
        "markdown_characters": len(markdown),
    }


def test_compare_real_excel_parsers():
    """EXCEL_COMPARISON_FILE을 두 실제 파서로 처리하고 결과 파일을 저장한다."""
    # 2026.08.13(sooyeon.choi) 수정 - 명시적으로 지정한 실제 XLSX만 비교
    source_value = os.getenv("EXCEL_COMPARISON_FILE")
    if not source_value:
        pytest.skip("Set EXCEL_COMPARISON_FILE to run the real parser comparison")

    source = Path(source_value).resolve()
    assert source.is_file(), f"Comparison file not found: {source}"
    assert source.suffix.lower() in {".xlsx", ".xlsm", ".xltx", ".xltm"}

    output_root = Path(
        os.getenv("EXCEL_COMPARISON_OUTPUT_DIR", "tests/results")
    ).resolve()
    output_dir = output_root / source.stem
    output_dir.mkdir(parents=True, exist_ok=True)
    for obsolete_name in (
        "openpyxl_result.json",
        "docling_result.json",
        "comparison_summary.json",
    ):
        (output_dir / obsolete_name).unlink(missing_ok=True)

    # 2026.08.13(sooyeon.choi) 수정 - 환경 기본값과 무관하게 양쪽 파서를 직접 선택
    openpyxl_result = asyncio.run(
        DocumentParser(excel_parser_type="openpyxl").parse(
            str(source),
            output_format="md",
        )
    )
    docling_result = asyncio.run(
        DocumentParser(excel_parser_type="docling").parse(
            str(source),
            output_format="md",
        )
    )

    assert openpyxl_result["metadata"]["parser"] == "openpyxl"
    assert docling_result["metadata"]["parser"] == "docling"

    _write_result(output_dir, "openpyxl", openpyxl_result)
    _write_result(output_dir, "docling", docling_result)

    summary = {
        "source_file": str(source),
        "openpyxl": _result_summary(openpyxl_result),
        "docling": _result_summary(docling_result),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Comparison results written to: {output_dir}")

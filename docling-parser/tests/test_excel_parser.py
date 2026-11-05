"""OpenPyXL Excel 파서 회귀 테스트."""

# 2026.08.12(sooyeon.choi) 추가 - Excel 파싱 정책 및 출력 계약 검증
from datetime import date
import base64
import json
from pathlib import Path
import sys
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

import openpyxl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.spreadsheets.parser import OpenpyxlExcelParser


# 2026.08.13(sooyeon.choi) 수정 - 환경변수 기반 Excel 파서 설정 검증
def test_excel_parser_config_defaults_and_validates(monkeypatch):
    from app.core.config import get_excel_parser

    monkeypatch.delenv("EXCEL_PARSER", raising=False)
    assert get_excel_parser() == "openpyxl"

    monkeypatch.setenv("EXCEL_PARSER", " DOCLING ")
    assert get_excel_parser() == "docling"

    monkeypatch.setenv("EXCEL_PARSER", "unknown")
    with pytest.raises(ValueError, match="Invalid EXCEL_PARSER"):
        get_excel_parser()


def _save_workbook(tmp_path, workbook, name="sample.xlsx"):
    path = tmp_path / name
    workbook.save(path)
    workbook.close()
    return path


def test_markdown_preserves_sheet_order_and_excludes_hidden_and_empty(tmp_path):
    workbook = openpyxl.Workbook()
    first = workbook.active
    first.title = "First"
    first.append(["ID", "Amount"])
    first.append(["A-1", 10])
    hidden = workbook.create_sheet("Hidden")
    hidden["A1"] = "secret"
    hidden.sheet_state = "hidden"
    workbook.create_sheet("Empty")
    last = workbook.create_sheet("Last")
    last["A1"] = "description"

    result = OpenpyxlExcelParser().parse(str(_save_workbook(tmp_path, workbook)))

    assert result["format"] == "md"
    assert [page["sheet_name"] for page in result["pages"]] == ["First", "Last"]
    assert result["pages"][0]["sheet_index"] == 1
    assert result["pages"][1]["sheet_index"] == 4
    assert result["pages"][0]["metadata"]["source_range"] == "A1:B2"
    assert {item["reason"] for item in result["metadata"]["excluded_sheets"]} == {"hidden", "empty"}


def test_logs_and_returns_ir_processing_engine(tmp_path, caplog):
    # 2026.08.27(sooyeon.choi) 수정 - IR 단일 처리 경로 관측 가능성 검증
    workbook = openpyxl.Workbook()
    workbook.active.append(["ID", "Value"])
    workbook.active.append([1, "A"])

    with caplog.at_level("INFO", logger="app.spreadsheets.parser"):
        result = OpenpyxlExcelParser().parse(str(_save_workbook(tmp_path, workbook)))

    assert result["metadata"]["processing_engine"] == "ir"
    assert result["metadata"]["processing_path"] == "structured_ir"
    assert "processing_engine=ir" in caplog.text
    assert "processing_path=structured_ir" in caplog.text


# 2026.08.20(sooyeon.choi) 수정 - Markdown API가 정형 블록 구조를 보존하는지 검증
def test_markdown_response_includes_structured_blocks(tmp_path):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Parts"
    sheet.append(["ID", "Name", "Quantity"])
    sheet.append([1, "Motor", 2])

    result = OpenpyxlExcelParser().parse(str(_save_workbook(tmp_path, workbook)))
    block = result["pages"][0]["blocks"][0]

    # 2026.08.27(sooyeon.choi) 수정 - StructuredSpreadsheet 정본 1.0 계약
    assert result["schema_version"] == "1.0"
    assert block["block_id"] == "sheet-1:block-1"
    assert block["block_type"] == "record_table"
    assert block["source_range"] == "A1:C2"
    assert block["header_row_count"] == 1
    assert block["headers"] == ["ID", "Name", "Quantity"]
    assert block["records"][0]["values"] == ["1", "Motor", "2"]
    assert block["records"][0]["source_range"] == "A2:C2"


def test_structured_spreadsheet_v1_golden_ir(tmp_path):
    # 2026.08.27(sooyeon.choi) 추가 - 단계 2 golden IR 핵심 계약
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Parts"
    sheet.append(["ID", "Name", "Quantity"])
    sheet.append([1, "Motor", 2])
    result = OpenpyxlExcelParser().parse(
        str(_save_workbook(tmp_path, workbook)),
        output_format="json",
        document_id="doc-golden",
    )
    expected = json.loads(
        (Path(__file__).parent / "fixtures" / "structured_spreadsheet_v1_golden.json")
        .read_text(encoding="utf-8")
    )
    sheet_ir = result["content"]["sheets"][0]
    block = sheet_ir["blocks"][0]
    record = block["records"][0]

    assert result["schema_name"] == expected["schema_name"]
    assert result["schema_version"] == expected["schema_version"]
    assert {key: sheet_ir[key] for key in expected["sheet"]} == expected["sheet"]
    assert {key: block[key] for key in expected["block"]} == expected["block"]
    assert {key: record[key] for key in expected["record"]} == expected["record"]
    assert result["metadata"]["document_id"] == "doc-golden"


def test_normalizes_values_merged_cells_and_missing_formula_cache(tmp_path):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Values"
    sheet.merge_cells("A1:B1")
    sheet["A1"] = "2026년"
    sheet.append(["Date", "Rate", "Formula"])
    sheet.append([date(2026, 8, 12), 0.125, "=1+1"])
    sheet["B3"].number_format = "0.0%"

    result = OpenpyxlExcelParser().parse(str(_save_workbook(tmp_path, workbook)))
    page = result["pages"][0]

    assert "2026년" in page["markdown"]
    assert "2026-08-12" in page["markdown"]
    assert "12.5%" in page["markdown"]
    formula_cell = page["blocks"][0]["records"][0]["cells"][2]
    assert formula_cell["formula"] == "=1+1"
    assert formula_cell["formula_cache_status"] == "missing"
    assert any(warning["code"] == "FORMULA_CACHE_MISSING" for warning in page["metadata"]["warnings"])


# 2026.08.18(sooyeon.choi) excel 후처리 로직 추가
def test_merged_value_is_not_repeated_and_virtual_headers_are_not_created(tmp_path):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.merge_cells("A1:C1")
    sheet["A1"] = "병합 제목"
    sheet.append(["값1", "값2", "값3"])

    result = OpenpyxlExcelParser().parse(str(_save_workbook(tmp_path, workbook)))
    markdown = result["pages"][0]["markdown"]

    assert markdown.count("병합 제목") == 1
    assert "Column 1" not in markdown


def test_vertical_merge_inherits_effective_value_and_tracks_anchor(tmp_path):
    # 2026.08.27(sooyeon.choi) 추가 - 단계 2 병합 셀 의미 상속 계약
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["분류", "검사항목", "기준"])
    sheet.append(["펌프", "누수", "없음"])
    sheet.append([None, "진동", "5mm/s 이하"])
    sheet.merge_cells("A2:A3")

    result = OpenpyxlExcelParser().parse(str(_save_workbook(tmp_path, workbook)))
    block = result["pages"][0]["blocks"][0]
    inherited = block["records"][1]["cells"][0]

    assert inherited["display_value"] == ""
    assert inherited["effective_value"] == "펌프"
    assert inherited["inherited_from"] == "A2"
    assert inherited["inheritance_reason"] == "vertical_merge"
    assert "분류: 펌프" in result["pages"][0]["embedding_text"]
    assert result["pages"][0]["markdown"].count("펌프") == 1


def test_deduplicates_styles_and_preserves_cell_contract(tmp_path):
    # 2026.08.27(sooyeon.choi) 추가 - 단계 2 style_ref 및 셀 필수 필드 검증
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["ID", "Value"])
    sheet.append([1, 2])
    from copy import copy
    bold_font = copy(sheet["A1"].font)
    bold_font.bold = True
    sheet["A1"].font = bold_font
    sheet["B1"].font = copy(bold_font)

    result = OpenpyxlExcelParser().parse(str(_save_workbook(tmp_path, workbook)))
    cells = result["pages"][0]["blocks"][0]["cells"]

    assert cells[0][0]["style_ref"] == cells[0][1]["style_ref"]
    assert cells[0][0]["style_ref"] in result["styles"]
    assert {
        "coordinate", "row", "column", "raw_value", "display_value",
        "effective_value", "formula", "formula_cached_value",
        "formula_cache_status", "data_type", "number_format", "hyperlink",
        "comment", "merged_range", "is_merge_anchor", "inherited_from",
        "inheritance_reason", "style_ref",
    }.issubset(cells[0][0])


# 2026.08.18(sooyeon.choi) excel 후처리 로직 추가
def test_extracts_original_image_and_links_anchor_to_block(tmp_path):
    from openpyxl.drawing.image import Image

    image_path = tmp_path / "part.png"
    image_path.write_bytes(base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    ))
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "핵심 부품 List"
    sheet.append(["No", "품명", "품번", "사진", "수량"])
    sheet.append([1, None, None, None, 1])
    sheet.add_image(Image(str(image_path)), "D2")
    workbook_path = _save_workbook(tmp_path, workbook, "with-image.xlsx")

    # 2026.08.27(sooyeon.choi) 수정 - 단계 8 정본(resource/⟦RESOURCE:⟧) 기준으로 정리
    result = OpenpyxlExcelParser().parse(
        str(workbook_path),
        document_id="doc-test",
        resource_root=str(tmp_path / "resources"),
    )

    assert result["metadata"]["document_id"] == "doc-test"
    assert result["metadata"]["image_count"] == 1
    resource = result["resources"][0]
    assert resource["resource_type"] == "image"
    assert resource["from_cell"] == "D2"
    assert resource["linked_record_ids"] == ["sheet-1:row-2"]
    assert resource["linked_block_id"] == "sheet-1:block-1"
    assert resource["content_hash"].startswith("sha256:")
    assert (tmp_path / "resources" / resource["relative_path"]).is_file()
    assert f"⟦RESOURCE:{resource['resource_id']}⟧" in result["pages"][0]["markdown"]
    assert resource["resource_id"] not in result["pages"][0]["embedding_text"]

    json_result = OpenpyxlExcelParser().parse(
        str(workbook_path),
        output_format="json",
        document_id="doc-test-json",
        resource_root=str(tmp_path / "resources"),
    )
    # 헤더 행은 record에서 제외되므로 첫 record가 row-2다.
    records = json_result["content"]["sheets"][0]["blocks"][0]["records"]
    assert records[0]["record_id"] == "sheet-1:row-2"
    assert records[0]["resource_ids"]


# 2026.08.18(sooyeon.choi) excel 후처리 로직 추가
def test_extracts_shape_text_from_drawing_xml(tmp_path):
    from openpyxl.drawing.image import Image

    image_path = tmp_path / "pixel.png"
    image_path.write_bytes(base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    ))
    workbook = openpyxl.Workbook()
    workbook.active["A1"] = "공정"
    workbook.active.add_image(Image(str(image_path)), "B2")
    workbook_path = _save_workbook(tmp_path, workbook, "with-shape.xlsx")

    with ZipFile(workbook_path) as source:
        entries = {name: source.read(name) for name in source.namelist()}
    drawing_path = "xl/drawings/drawing1.xml"
    drawing = ET.fromstring(entries[drawing_path])
    anchor = list(drawing)[0]
    xdr = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
    a = "http://schemas.openxmlformats.org/drawingml/2006/main"
    shape = ET.SubElement(anchor, f"{{{xdr}}}sp")
    non_visual = ET.SubElement(shape, f"{{{xdr}}}nvSpPr")
    ET.SubElement(non_visual, f"{{{xdr}}}cNvPr", {"id": "99", "name": "Process Step"})
    text_body = ET.SubElement(shape, f"{{{xdr}}}txBody")
    paragraph = ET.SubElement(text_body, f"{{{a}}}p")
    run = ET.SubElement(paragraph, f"{{{a}}}r")
    ET.SubElement(run, f"{{{a}}}t").text = "제조 작업 시작"
    entries[drawing_path] = ET.tostring(drawing, encoding="utf-8", xml_declaration=True)
    with ZipFile(workbook_path, "w", ZIP_DEFLATED) as target:
        for name, data in entries.items():
            target.writestr(name, data)

    # 2026.08.27(sooyeon.choi) 수정 - 단계 8 정본(resource) 기준으로 정리
    result = OpenpyxlExcelParser().parse(
        str(workbook_path),
        document_id="doc-shape",
        resource_root=str(tmp_path / "resources"),
    )

    assert result["metadata"]["shape_count"] == 1
    assert "제조 작업 시작" in result["pages"][0]["markdown"]
    shape = next(item for item in result["resources"] if item["resource_type"] == "shape")
    assert shape["details"]["name"] == "Process Step"
    assert shape["details"]["text"] == "제조 작업 시작"


# 2026.08.18(sooyeon.choi) excel 후처리 로직 추가
def test_discards_staged_resources_when_workbook_processing_fails(tmp_path, monkeypatch):
    from openpyxl.drawing.image import Image

    image_path = tmp_path / "pixel.png"
    image_path.write_bytes(base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    ))
    workbook = openpyxl.Workbook()
    workbook.active["A1"] = "data"
    workbook.active.add_image(Image(str(image_path)), "B2")
    workbook_path = _save_workbook(tmp_path, workbook, "failure.xlsx")

    parser = OpenpyxlExcelParser()
    monkeypatch.setattr(
        parser,
        "_parse_workbook",
        lambda *_: (_ for _ in ()).throw(RuntimeError("forced failure")),
    )
    # 2026.08.27(sooyeon.choi) 수정 - 단계 8 정본(resource_root) 기준으로 정리
    resource_root = tmp_path / "resources"

    with pytest.raises(RuntimeError, match="forced failure"):
        parser.parse(
            str(workbook_path),
            document_id="doc-failure",
            resource_root=str(resource_root),
        )

    assert not (resource_root / ".tmp" / "doc-failure").exists()
    assert not (resource_root / "doc-failure").exists()


def test_json_contract_and_vertical_block_split(tmp_path):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Blocks"
    sheet.append(["ID", "Value"])
    sheet.append(["A", 1])
    sheet.append([])
    sheet.append(["B", 2])

    result = OpenpyxlExcelParser().parse(
        str(_save_workbook(tmp_path, workbook)), output_format="json"
    )

    assert result["content"]["schema_name"] == "StructuredSpreadsheet"
    assert len(result["content"]["sheets"][0]["blocks"]) == 2
    assert result["metadata"]["parser"] == "openpyxl"


def test_rejects_non_ooxml_file(tmp_path):
    path = tmp_path / "invalid.xlsx"
    path.write_bytes(b"not-a-zip")

    with pytest.raises(ValueError, match="OOXML"):
        OpenpyxlExcelParser().parse(str(path))


def test_document_parser_routes_excel_without_docling(tmp_path):
    # 2026.08.12(sooyeon.choi) 추가 - Excel 라우팅이 Docling converter를 요구하지 않는지 검증
    import asyncio
    pytest.importorskip("docling", reason="DocumentParser requires the existing Docling dependency")
    from app.services.parser import DocumentParser

    workbook = openpyxl.Workbook()
    workbook.active["A1"] = "routed"
    path = _save_workbook(tmp_path, workbook)

    parser = DocumentParser.__new__(DocumentParser)
    parser._excel_semaphore = None
    parser.excel_parser = OpenpyxlExcelParser()
    # 2026.08.13(sooyeon.choi) 수정 - 테스트에서 선택할 Excel 파서를 직접 지정
    parser.excel_parser_type = "openpyxl"

    result = asyncio.run(parser.parse(str(path)))

    assert result["metadata"]["parser"] == "openpyxl"
    assert "routed" in result["pages"][0]["markdown"]


# 2026.08.13(sooyeon.choi) 수정 - 동일 파일을 양쪽 파서 경로로 선택할 수 있는지 검증
def test_document_parser_selects_openpyxl_or_docling(tmp_path, caplog):
    import asyncio
    pytest.importorskip("docling", reason="DocumentParser requires the existing Docling dependency")
    from app.services.parser import DocumentParser

    workbook = openpyxl.Workbook()
    workbook.active["A1"] = "compare"
    path = _save_workbook(tmp_path, workbook)

    openpyxl_parser = DocumentParser.__new__(DocumentParser)
    openpyxl_parser._excel_semaphore = None
    openpyxl_parser.excel_parser_type = "openpyxl"
    openpyxl_parser.excel_parser = OpenpyxlExcelParser()
    openpyxl_result = asyncio.run(openpyxl_parser.parse(str(path)))

    class FakeDocument:
        pages = {1: object()}

        def export_to_markdown(self, page_no=None):
            return f"docling compare page={page_no}"

    class FakeConversion:
        document = FakeDocument()

    docling_parser = DocumentParser.__new__(DocumentParser)
    docling_parser._excel_semaphore = None
    docling_parser.excel_parser_type = "docling"
    docling_parser.excel_parser = OpenpyxlExcelParser()
    docling_parser._convert_sync = lambda _: FakeConversion()
    docling_result = asyncio.run(docling_parser.parse(str(path)))

    assert openpyxl_result["metadata"]["parser"] == "openpyxl"
    assert docling_result["metadata"]["parser"] == "docling"
    assert docling_result["metadata"]["source_type"] == "spreadsheet"
    assert "docling compare" in docling_result["pages"][0]["markdown"]
    assert "parser=openpyxl" in caplog.text
    assert "parser=docling" in caplog.text


# 2026.08.13(sooyeon.choi) 수정 - Docling JSON 결과에도 파서 식별 metadata 보장
def test_docling_excel_json_contract(tmp_path):
    import asyncio
    pytest.importorskip("docling", reason="DocumentParser requires the existing Docling dependency")
    from app.services.parser import DocumentParser

    path = tmp_path / "sample.xlsx"
    path.write_bytes(b"mocked converter input")

    class FakeDocument:
        pages = {1: object(), 2: object()}

        def export_to_dict(self):
            return {"schema_name": "DoclingDocument"}

    class FakeConversion:
        document = FakeDocument()

    parser = DocumentParser.__new__(DocumentParser)
    parser._excel_semaphore = None
    parser.excel_parser_type = "docling"
    parser.excel_parser = OpenpyxlExcelParser()
    parser._convert_sync = lambda _: FakeConversion()

    result = asyncio.run(parser.parse(str(path), output_format="json"))

    assert result["format"] == "json"
    assert result["num_pages"] == 2
    assert result["metadata"]["parser"] == "docling"
    assert result["metadata"]["source_type"] == "spreadsheet"

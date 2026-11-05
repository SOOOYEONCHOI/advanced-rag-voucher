"""단계 7 수식·병합·서식 품질 계약 테스트."""

# 2026.08.27(sooyeon.choi) 추가 - REQ-QUALITY-001/002/003 회귀 테스트
from datetime import date, datetime, time
from pathlib import Path
import sys

import openpyxl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.spreadsheets.number_format import format_value
from app.spreadsheets.parser import OpenpyxlExcelParser


def _save_workbook(tmp_path, workbook, name="quality.xlsx"):
    path = tmp_path / name
    workbook.save(path)
    workbook.close()
    return path


def _parse(tmp_path, workbook, name="quality.xlsx"):
    return OpenpyxlExcelParser().parse(str(_save_workbook(tmp_path, workbook, name)), output_format="json")


def _cells(page):
    return {
        cell["coordinate"]: cell
        for block in page["blocks"]
        for row in block["cells"]
        for cell in row
    }


# ── REQ-QUALITY-001 표시값 formatter ───────────────────────────────────────

@pytest.mark.parametrize(
    "value,number_format,expected",
    [
        (1234.5, "#,##0", "1,235"),
        (1234.5, "#,##0.00", "1,234.50"),
        (0.1234, "0.0%", "12.3%"),
        (0.07, "0.00%", "7.00%"),
        (1234567, '#,##0,,"M"', "1M"),
        (1234.5, '"₩"#,##0', "₩1,235"),
        (1234.5, "[$₩-412]#,##0.00", "₩1,234.50"),
        (-1234.5, "#,##0;(#,##0)", "(1,235)"),
        (-1234.5, "#,##0", "-1,235"),
        (0, '#,##0;-#,##0;"-"', "-"),
        (100, '0.0"kg"', "100.0kg"),
        (1234.5, "_-#,##0.00_-", "1,234.50"),
        (datetime(2026, 8, 27, 14, 5, 9), "yyyy-mm-dd", "2026-08-27"),
        (datetime(2026, 8, 27, 14, 5, 9), "yyyy-mm-dd hh:mm", "2026-08-27 14:05"),
        (datetime(2026, 1, 3), "mm/dd/yy", "01/03/26"),
        (datetime(2026, 1, 3), "m/d/yyyy", "1/3/2026"),
        (datetime(2026, 8, 27, 14, 5, 9), "h:mm AM/PM", "2:05 PM"),
        (datetime(2026, 8, 27, 14, 5, 9), "hh:mm:ss", "14:05:09"),
        (datetime(2026, 8, 27, 14, 5, 9), "mm:ss", "05:09"),
        (datetime(2026, 8, 27), "mmm d, yyyy", "Aug 27, 2026"),
        (datetime(2026, 8, 27), "dddd", "Thursday"),
        (datetime(2026, 8, 27), 'yyyy"년" m"월" d"일"', "2026년 8월 27일"),
        (time(14, 5, 9), "h:mm", "14:05"),
        (date(2026, 8, 27), "yyyy-mm-dd", "2026-08-27"),
        ("부품", '@"(확인)"', "부품(확인)"),
        (True, "#,##0", "TRUE"),
        (None, "#,##0", ""),
    ],
)
def test_number_format_matches_excel_display(value, number_format, expected):
    text, supported = format_value(value, number_format)
    assert (text, supported) == (expected, True)


@pytest.mark.parametrize("number_format", ["0.00E+00", "# ?/?", "[>100]#,##0;#,##0"])
def test_unsupported_number_format_is_reported(number_format):
    text, supported = format_value(1234.5, number_format)
    assert supported is False
    assert text == "1234.5"


def test_display_formatter_applies_to_cells_and_keeps_raw_value(tmp_path):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["항목", "금액", "비율", "일자"])
    sheet.append(["모터", 1234567.891, 0.1234, datetime(2026, 8, 27, 14, 5)])
    sheet["B2"].number_format = '"₩"#,##0'
    sheet["C2"].number_format = "0.0%"
    sheet["D2"].number_format = "yyyy-mm-dd hh:mm"

    page = _parse(tmp_path, workbook)["pages"][0]
    cells = _cells(page)

    assert cells["B2"]["display_value"] == "₩1,234,568"
    assert cells["B2"]["raw_value"] == 1234567.891
    assert cells["C2"]["display_value"] == "12.3%"
    assert cells["C2"]["raw_value"] == 0.1234
    assert cells["D2"]["display_value"] == "2026-08-27 14:05"
    assert cells["D2"]["raw_value"] == "2026-08-27T14:05:00"


def test_unsupported_cell_format_warns_and_preserves_raw_value(tmp_path):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["항목", "값"])
    sheet.append(["측정", 1234.5])
    sheet["B2"].number_format = "0.00E+00"

    page = _parse(tmp_path, workbook)["pages"][0]
    cells = _cells(page)
    warnings = page["metadata"]["warnings"]

    assert cells["B2"]["raw_value"] == 1234.5
    assert cells["B2"]["number_format"] == "0.00E+00"
    assert cells["B2"]["display_value"] == "1234.5"
    unsupported = [w for w in warnings if w["code"] == "DISPLAY_FORMAT_UNSUPPORTED"]
    assert unsupported and unsupported[0]["cell"] == "B2"


# ── REQ-QUALITY-002 수식 정책 ──────────────────────────────────────────────

def test_formula_cache_stale_is_tracked_as_workbook_warning(tmp_path):
    workbook = openpyxl.Workbook()
    workbook.calculation.fullCalcOnLoad = True
    sheet = workbook.active
    sheet.append(["항목", "수량", "합계"])
    sheet.append(["모터", 2, "=B2*3"])

    result = _parse(tmp_path, workbook)
    document = result["content"]["document"]
    cells = _cells(result["pages"][0])

    assert document["formula_cache_stale"] is True
    assert document["formula_recalculated"] is False
    assert any(warning["code"] == "FORMULA_CACHE_STALE" for warning in document["warnings"])
    assert cells["C2"]["formula"] == "=B2*3"
    assert cells["C2"]["formula_cache_status"] == "missing"


def test_formula_dominant_block_exposes_record_manifest(tmp_path):
    workbook = openpyxl.Workbook()
    workbook.calculation.fullCalcOnLoad = False
    sheet = workbook.active
    sheet.append(["항목", "단가", "수량", "금액"])
    sheet.append(["모터", "=100*2", "=1+1", "=B2*C2"])
    sheet.append(["펌프", "=200*2", "=2+1", "=B3*C3"])

    page = _parse(tmp_path, workbook)["pages"][0]
    block = page["blocks"][0]

    assert block["formula_cell_count"] == 6
    assert block["formula_ratio"] >= 0.5
    assert block["formula_dominant"] is True
    manifest = block["records"][0]["formulas"]
    assert [entry["coordinate"] for entry in manifest] == ["B2", "C2", "D2"]
    assert manifest[0]["formula"] == "=100*2"
    assert manifest[0]["cache_status"] in {"missing", "available", "stale"}


def test_value_table_is_not_formula_dominant(tmp_path):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["항목", "수량"])
    sheet.append(["모터", 2])
    sheet.append(["펌프", 3])

    page = _parse(tmp_path, workbook)["pages"][0]
    block = page["blocks"][0]

    assert block["formula_cell_count"] == 0
    assert block["formula_dominant"] is False
    assert block["records"][0]["formulas"] == []


# ── REQ-QUALITY-003 병합 헤더와 레코드 문맥 ────────────────────────────────

def test_multi_row_header_paths_inherit_merged_parent(tmp_path):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet["A1"] = "구분"
    sheet["B1"] = "2026년 상반기"
    sheet["A2"] = "설비"
    sheet["B2"] = "1분기"
    sheet["C2"] = "2분기"
    sheet.merge_cells("B1:C1")
    sheet.merge_cells("A1:A2")
    sheet.append(["펌프", 10, 20])

    page = _parse(tmp_path, workbook)["pages"][0]
    block = page["blocks"][0]

    assert block["header_row_count"] == 2
    # A1:A2 세로 병합 헤더는 같은 값이 반복되지 않고 한 단계로 유지된다.
    assert block["header_paths"] == [["구분"], ["2026년 상반기", "1분기"], ["2026년 상반기", "2분기"]]
    assert block["headers"] == ["구분", "2026년 상반기 / 1분기", "2026년 상반기 / 2분기"]
    assert block["header_columns"][1]["header_path"] == ["2026년 상반기", "1분기"]
    assert block["header_columns"][2]["physical_header"] == ""


def test_vertical_merge_separates_physical_and_effective_values(tmp_path):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["분류", "검사항목", "기준"])
    sheet.append(["펌프", "누수", "없음"])
    sheet.append([None, "진동", "5mm/s 이하"])
    sheet.merge_cells("A2:A3")

    page = _parse(tmp_path, workbook)["pages"][0]
    block = page["blocks"][0]
    inherited_record = block["records"][1]

    assert inherited_record["values"][0] == "펌프"
    assert inherited_record["physical_values"][0] == ""
    assert inherited_record["inherited_cells"] == [{
        "column": 1,
        "coordinate": "A3",
        "inherited_from": "A2",
        "inheritance_reason": "vertical_merge",
        "effective_value": "펌프",
    }]


def test_merge_crossing_block_boundary_warns_and_flags_blocks(tmp_path):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["분류", "항목"])
    sheet.append(["펌프", "누수"])
    sheet.append([None, "진동"])
    # 병합 범위가 데이터 block(A1:B3) 밖의 행까지 이어진다.
    sheet.merge_cells("A2:A6")

    page = _parse(tmp_path, workbook)["pages"][0]
    metadata = page["metadata"]

    crossing = [w for w in metadata["warnings"] if w["code"] == "MERGE_CROSSES_BLOCK"]
    assert crossing and crossing[0]["cell"] == "A2:A6"
    assert any(block["cross_block_merge"] for block in page["blocks"])
    # 보수적 처리: block 분할과 상속값은 유지되어 데이터가 사라지지 않는다.
    values = [record["values"] for block in page["blocks"] for record in block["records"]]
    assert any("진동" in row for row in values)

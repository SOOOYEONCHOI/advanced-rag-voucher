"""단계 8 이미지·도형·차트 원본 보존 계약 테스트."""

# 2026.08.27(sooyeon.choi) 추가 - REQ-MEDIA-001/002/003/004 회귀 테스트
import base64
import hashlib
from pathlib import Path
import sys
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

import openpyxl
from openpyxl.chart import BarChart, Reference
from openpyxl.drawing.image import Image
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.spreadsheets.parser import OpenpyxlExcelParser


XDR = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _png(tmp_path, name="part.png"):
    path = tmp_path / name
    path.write_bytes(PNG_1PX)
    return path


def _parse(tmp_path, workbook, document_id, name="media.xlsx", output_format="md"):
    path = tmp_path / name
    workbook.save(path)
    workbook.close()
    return OpenpyxlExcelParser().parse(
        str(path),
        output_format=output_format,
        document_id=document_id,
        resource_root=str(tmp_path / "resources"),
    )


def _add_shape(workbook_path, name="Process Step", text="제조 작업 시작", shape_id="99", connector=False):
    """openpyxl이 만들지 못하는 도형/연결선을 drawing XML에 직접 주입한다."""
    with ZipFile(workbook_path) as source:
        entries = {entry: source.read(entry) for entry in source.namelist()}
    drawing_part = "xl/drawings/drawing1.xml"
    drawing = ET.fromstring(entries[drawing_part])
    anchor = list(drawing)[0]
    tag = "cxnSp" if connector else "sp"
    shape = ET.SubElement(anchor, f"{{{XDR}}}{tag}")
    non_visual = ET.SubElement(shape, f"{{{XDR}}}nv{'CxnSp' if connector else 'Sp'}Pr")
    ET.SubElement(non_visual, f"{{{XDR}}}cNvPr", {"id": shape_id, "name": name})
    if connector:
        properties = ET.SubElement(non_visual, f"{{{XDR}}}cNvCxnSpPr")
        ET.SubElement(properties, f"{{{A}}}stCxn", {"id": "10", "idx": "0"})
        ET.SubElement(properties, f"{{{A}}}endCxn", {"id": "11", "idx": "2"})
    else:
        shape_properties = ET.SubElement(shape, f"{{{XDR}}}spPr")
        ET.SubElement(shape_properties, f"{{{A}}}prstGeom", {"prst": "roundRect"})
        text_body = ET.SubElement(shape, f"{{{XDR}}}txBody")
        paragraph = ET.SubElement(text_body, f"{{{A}}}p")
        run = ET.SubElement(paragraph, f"{{{A}}}r")
        ET.SubElement(run, f"{{{A}}}t").text = text
    entries[drawing_part] = ET.tostring(drawing, encoding="utf-8", xml_declaration=True)
    with ZipFile(workbook_path, "w", ZIP_DEFLATED) as target:
        for entry, payload in entries.items():
            target.writestr(entry, payload)


# ── REQ-MEDIA-001 이미지 원본 추출 ─────────────────────────────────────────

def test_image_bytes_hash_matches_workbook_original(tmp_path):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "부품"
    sheet.append(["품명", "사진"])
    sheet.append(["모터", None])
    sheet.add_image(Image(str(_png(tmp_path))), "B2")

    result = _parse(tmp_path, workbook, "doc-image")
    resource = result["resources"][0]
    stored = (tmp_path / "resources" / resource["relative_path"]).read_bytes()

    assert resource["resource_type"] == "image"
    assert resource["mime_type"] == "image/png"
    assert resource["content_hash"] == "sha256:" + hashlib.sha256(PNG_1PX).hexdigest()
    assert stored == PNG_1PX
    assert resource["file_size"] == len(PNG_1PX)
    assert resource["details"]["pixel_width"] == 1
    assert resource["details"]["pixel_height"] == 1
    assert resource["details"]["source_part"] == "xl/media/image1.png"


def test_image_anchor_is_traceable_back_to_sheet_and_cells(tmp_path):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "핵심 부품"
    sheet.append(["품명", "품번", "사진"])
    sheet.append(["팬", "nc-fan-01", None])
    sheet.add_image(Image(str(_png(tmp_path))), "C2")

    resource = _parse(tmp_path, workbook, "doc-anchor")["resources"][0]

    assert resource["sheet_id"] == "sheet-1"
    assert resource["sheet_name"] == "핵심 부품"
    assert resource["from_cell"] == "C2"
    assert resource["anchor"]["anchor_type"] == "oneCellAnchor"
    assert resource["anchor"]["from_row"] == 2
    assert resource["anchor"]["from_column"] == 3
    assert resource["linked_block_id"] == "sheet-1:block-1"
    assert resource["linked_record_ids"] == ["sheet-1:row-2"]
    assert resource["surrounding_range"] == "A2:C2"
    assert "nc-fan-01" in resource["surrounding_text"]


def test_two_cell_anchor_is_normalized_to_cell_range(tmp_path):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["월", "매출"])
    sheet.append(["1월", 100])
    sheet.append(["2월", 150])
    chart = BarChart()
    data = Reference(sheet, min_col=2, min_row=1, max_row=3)
    chart.add_data(data, titles_from_data=True)
    sheet.add_chart(chart, "D2")

    resource = _parse(tmp_path, workbook, "doc-two-cell")["resources"][0]

    assert resource["anchor"]["anchor_type"] == "oneCellAnchor"
    assert resource["from_cell"] == "D2"
    # ext 기반 크기가 셀 좌표로 정규화되어 to_cell이 from_cell보다 뒤에 온다.
    assert resource["anchor"]["to_row"] >= resource["anchor"]["from_row"]
    assert resource["anchor"]["to_column"] > resource["anchor"]["from_column"]


# ── REQ-MEDIA-002 도형 보존 ────────────────────────────────────────────────

def test_shape_text_type_and_xml_fragment_are_preserved(tmp_path):
    workbook = openpyxl.Workbook()
    workbook.active["A1"] = "공정"
    workbook.active.add_image(Image(str(_png(tmp_path))), "B2")
    path = tmp_path / "shape.xlsx"
    workbook.save(path)
    workbook.close()
    _add_shape(path)

    result = OpenpyxlExcelParser().parse(
        str(path), document_id="doc-shape", resource_root=str(tmp_path / "resources")
    )
    shape = next(item for item in result["resources"] if item["resource_type"] == "shape")
    fragment = (tmp_path / "resources" / shape["relative_path"]).read_text(encoding="utf-8")

    assert result["metadata"]["shape_count"] == 1
    assert shape["mime_type"] == "application/xml"
    assert shape["details"]["name"] == "Process Step"
    assert shape["details"]["shape_type"] == "roundRect"
    assert shape["details"]["shape_kind"] == "shape"
    assert shape["details"]["shape_id"] == "99"
    assert shape["details"]["text"] == "제조 작업 시작"
    assert shape["from_cell"] == "B2"
    assert "제조 작업 시작" in fragment


def test_connector_records_start_and_end_shape_ids(tmp_path):
    workbook = openpyxl.Workbook()
    workbook.active["A1"] = "공정"
    workbook.active.add_image(Image(str(_png(tmp_path))), "B2")
    path = tmp_path / "connector.xlsx"
    workbook.save(path)
    workbook.close()
    _add_shape(path, name="Connector 1", shape_id="20", connector=True)

    result = OpenpyxlExcelParser().parse(
        str(path), document_id="doc-connector", resource_root=str(tmp_path / "resources")
    )
    connector = next(item for item in result["resources"] if item["resource_type"] == "shape")

    assert connector["details"]["shape_kind"] == "connector"
    assert connector["details"]["start_shape_id"] == "10"
    assert connector["details"]["end_shape_id"] == "11"


# ── REQ-MEDIA-003 차트 보존 ────────────────────────────────────────────────

def test_chart_keeps_type_title_series_and_source_range(tmp_path):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "실적"
    sheet.append(["월", "매출"])
    sheet.append(["1월", 100])
    sheet.append(["2월", 150])
    chart = BarChart()
    chart.title = "월별 매출"
    data = Reference(sheet, min_col=2, min_row=1, max_row=3)
    categories = Reference(sheet, min_col=1, min_row=2, max_row=3)
    chart.add_data(data, titles_from_data=True)
    chart.set_categories(categories)
    sheet.add_chart(chart, "D2")

    result = _parse(tmp_path, workbook, "doc-chart")
    resource = result["resources"][0]
    details = resource["details"]
    stored = (tmp_path / "resources" / resource["relative_path"]).read_text(encoding="utf-8")

    assert result["metadata"]["chart_count"] == 1
    assert resource["resource_type"] == "chart"
    assert details["chart_type"] == "barChart"
    assert details["title"] == "월별 매출"
    assert details["series"][0]["value_range"] == "'실적'!$B$2:$B$3"
    assert details["series"][0]["category_range"] == "'실적'!$A$2:$A$3"
    assert "'실적'!$B$2:$B$3" in details["source_ranges"]
    assert "barChart" in stored


# ── REQ-MEDIA-004 resource marker ─────────────────────────────────────────

def test_marker_is_display_only_and_ids_stay_out_of_embedding_text(tmp_path):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["품명", "사진"])
    sheet.append(["모터", None])
    sheet.add_image(Image(str(_png(tmp_path))), "B2")

    result = _parse(tmp_path, workbook, "doc-marker")
    page = result["pages"][0]
    resource_id = result["resources"][0]["resource_id"]

    assert f"⟦RESOURCE:{resource_id}⟧" in page["markdown"]
    assert resource_id not in page["embedding_text"]
    assert "RESOURCE:" not in page["embedding_text"]
    # marker로 UI 표시와 resource 조회를 잇도록 block에도 ID가 남는다.
    assert resource_id in page["blocks"][0]["resource_ids"]


# ── 집계와 실패 정리 ───────────────────────────────────────────────────────

def test_workbook_metadata_counts_each_resource_type(tmp_path):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["월", "매출"])
    sheet.append(["1월", 100])
    sheet.add_image(Image(str(_png(tmp_path))), "D2")
    chart = BarChart()
    chart.add_data(Reference(sheet, min_col=2, min_row=1, max_row=2), titles_from_data=True)
    sheet.add_chart(chart, "F2")
    path = tmp_path / "counts.xlsx"
    workbook.save(path)
    workbook.close()
    _add_shape(path, name="Note", text="주의")

    metadata = OpenpyxlExcelParser().parse(
        str(path), document_id="doc-counts", resource_root=str(tmp_path / "resources")
    )["metadata"]

    assert metadata["image_count"] == 1
    assert metadata["chart_count"] == 1
    assert metadata["shape_count"] == 1
    assert metadata["resource_count"] == 3


def test_workbook_without_drawings_has_no_resources(tmp_path):
    workbook = openpyxl.Workbook()
    workbook.active.append(["품명", "수량"])
    workbook.active.append(["모터", 2])

    result = _parse(tmp_path, workbook, "doc-plain")

    assert result["resources"] == []
    assert result["metadata"]["resource_count"] == 0
    assert not (tmp_path / "resources" / ".tmp" / "doc-plain").exists()


def test_staging_is_promoted_to_document_directory_on_success(tmp_path):
    workbook = openpyxl.Workbook()
    workbook.active["A1"] = "공정"
    workbook.active.add_image(Image(str(_png(tmp_path))), "B2")

    result = _parse(tmp_path, workbook, "doc-commit")
    resource = result["resources"][0]

    assert not (tmp_path / "resources" / ".tmp" / "doc-commit").exists()
    assert (tmp_path / "resources" / "doc-commit" / f"{resource['resource_id']}.png").is_file()


def test_failed_parse_leaves_no_local_resource_files(tmp_path, monkeypatch):
    workbook = openpyxl.Workbook()
    workbook.active["A1"] = "공정"
    workbook.active.add_image(Image(str(_png(tmp_path))), "B2")
    path = tmp_path / "failure.xlsx"
    workbook.save(path)
    workbook.close()

    parser = OpenpyxlExcelParser()
    monkeypatch.setattr(
        parser,
        "_build_result",
        lambda *_: (_ for _ in ()).throw(RuntimeError("forced failure")),
    )

    with pytest.raises(RuntimeError, match="forced failure"):
        parser.parse(
            str(path), document_id="doc-fail", resource_root=str(tmp_path / "resources")
        )

    assert not (tmp_path / "resources" / ".tmp" / "doc-fail").exists()
    assert not (tmp_path / "resources" / "doc-fail").exists()

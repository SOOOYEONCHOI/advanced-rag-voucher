"""OOXML drawing part에서 이미지·도형·차트 원본과 anchor를 추출한다."""

# 2026.08.27(sooyeon.choi) 추가 - REQ-MEDIA-001/002/003 원본 보존
from __future__ import annotations

import hashlib
import logging
import shutil
from pathlib import Path, PurePosixPath
from typing import Any
from zipfile import ZipFile

from defusedxml.ElementTree import fromstring
from openpyxl.utils import get_column_letter


logger = logging.getLogger(__name__)

XDR_NS = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
C_NS = "http://schemas.openxmlformats.org/drawingml/2006/chart"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"

# absolute anchor 정규화용 기본 셀 크기 (EMU)
EMU_PER_COLUMN = 609_600
EMU_PER_ROW = 190_500

MAX_RESOURCES_PER_WORKBOOK = 500
MAX_RESOURCE_BYTES = 50 * 1024 * 1024
MAX_SHAPE_TEXT_LENGTH = 2_000

_IMAGE_MIME_BY_SUFFIX = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".bmp": "image/bmp",
    ".emf": "image/emf",
    ".wmf": "image/wmf",
}
_EXTENSION_BY_MIME = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
    "image/tiff": "tiff",
    "application/xml": "xml",
}


class ExcelMediaExtractor:
    """workbook zip에서 resource 원본을 꺼내 parser 로컬 staging에 보관한다."""

    def __init__(self, resource_root: str | Path, document_id: str) -> None:
        self.resource_root = Path(resource_root).resolve()
        self.document_id = document_id
        self.staging_root = self.resource_root / ".tmp" / document_id
        self.document_root = self.resource_root / document_id
        self._sequence = 0
        self._resources: list[dict[str, Any]] = []

    # ── 공개 API ───────────────────────────────────────────────────────────

    def extract(self, file_path: str, sheet_order: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """resource 목록과 warning 목록을 반환한다.

        sheet_order는 parser가 부여한 sheet-{index} 순서와 같은 시트 이름 목록이다.
        """
        resources: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        self.staging_root.mkdir(parents=True, exist_ok=True)
        try:
            with ZipFile(file_path) as archive:
                names = set(archive.namelist())
                for sheet_index, sheet_name in enumerate(sheet_order, start=1):
                    drawing_part = self._sheet_drawing_part(archive, names, sheet_name)
                    if not drawing_part or drawing_part not in names:
                        continue
                    resources.extend(self._extract_drawing(
                        archive, names, drawing_part, sheet_index, sheet_name, warnings
                    ))
                    if len(resources) >= MAX_RESOURCES_PER_WORKBOOK:
                        warnings.append({
                            "code": "RESOURCE_LIMIT_EXCEEDED",
                            "sheet": sheet_name,
                            "message": "Workbook resource limit reached; remaining resources were skipped.",
                        })
                        break
        except Exception:
            self.discard()
            raise
        return resources[:MAX_RESOURCES_PER_WORKBOOK], warnings

    def commit(self) -> None:
        """staging 파일을 document 디렉터리로 확정하고 resource 경로를 갱신한다."""
        if not self.staging_root.exists():
            return
        self.document_root.mkdir(parents=True, exist_ok=True)
        for path in self.staging_root.iterdir():
            shutil.move(str(path), str(self.document_root / path.name))
        shutil.rmtree(self.staging_root, ignore_errors=True)
        # 2026.08.27(sooyeon.choi) 수정 - commit 후 local_path가 staging을 가리키지 않도록 갱신
        for resource in self._resources:
            resource["local_path"] = str(self.document_root / Path(resource["local_path"]).name)

    def discard(self) -> None:
        """실패 시 parser 로컬에 staging/확정 파일을 남기지 않는다."""
        shutil.rmtree(self.staging_root, ignore_errors=True)
        shutil.rmtree(self.document_root, ignore_errors=True)

    # ── zip/관계 탐색 ──────────────────────────────────────────────────────

    def _sheet_drawing_part(self, archive: ZipFile, names: set[str], sheet_name: str) -> str | None:
        worksheet_part = self._worksheet_part(archive, names, sheet_name)
        if not worksheet_part:
            return None
        relationships = self._relationships(archive, names, worksheet_part)
        for target, rel_type in relationships.values():
            if rel_type.endswith("/drawing"):
                return self._resolve_part(worksheet_part, target)
        return None

    def _worksheet_part(self, archive: ZipFile, names: set[str], sheet_name: str) -> str | None:
        if "xl/workbook.xml" not in names:
            return None
        workbook = fromstring(archive.read("xl/workbook.xml"))
        relationships = self._relationships(archive, names, "xl/workbook.xml")
        for sheet in workbook.iter(f"{{{MAIN_NS}}}sheet"):
            if sheet.get("name") != sheet_name:
                continue
            rel_id = sheet.get(f"{{{R_NS}}}id")
            entry = relationships.get(rel_id)
            if entry:
                return self._resolve_part("xl/workbook.xml", entry[0])
        return None

    @staticmethod
    def _relationships(archive: ZipFile, names: set[str], part: str) -> dict[str, tuple[str, str]]:
        path = PurePosixPath(part)
        rels_part = str(path.parent / "_rels" / f"{path.name}.rels")
        if rels_part not in names:
            return {}
        root = fromstring(archive.read(rels_part))
        return {
            element.get("Id"): (element.get("Target", ""), element.get("Type", ""))
            for element in root.iter(f"{{{PKG_REL_NS}}}Relationship")
        }

    @staticmethod
    def _resolve_part(source_part: str, target: str) -> str:
        if target.startswith("/"):
            return target.lstrip("/")
        base = PurePosixPath(source_part).parent
        resolved = PurePosixPath(base, target)
        parts: list[str] = []
        for segment in resolved.parts:
            if segment == "..":
                if parts:
                    parts.pop()
            elif segment != ".":
                parts.append(segment)
        return "/".join(parts)

    # ── drawing 해석 ──────────────────────────────────────────────────────

    def _extract_drawing(
        self,
        archive: ZipFile,
        names: set[str],
        drawing_part: str,
        sheet_index: int,
        sheet_name: str,
        warnings: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        drawing = fromstring(archive.read(drawing_part))
        relationships = self._relationships(archive, names, drawing_part)
        resources: list[dict[str, Any]] = []
        for z_order, anchor in enumerate(list(drawing), start=1):
            anchor_info = self._anchor_cells(anchor)
            for element, group_name in self._iter_shape_elements(anchor):
                tag = element.tag.split("}")[-1]
                try:
                    if tag == "pic":
                        resource = self._build_image(
                            archive, names, drawing_part, relationships, element,
                            anchor_info, sheet_index, sheet_name, z_order, group_name,
                        )
                    elif tag in {"sp", "cxnSp"}:
                        resource = self._build_shape(
                            element, anchor_info, sheet_index, sheet_name, z_order, group_name, tag,
                        )
                    elif tag == "graphicFrame":
                        resource = self._build_chart(
                            archive, names, drawing_part, relationships, element,
                            anchor_info, sheet_index, sheet_name, z_order, group_name,
                        )
                    else:
                        resource = None
                except (KeyError, ValueError, OSError) as exc:
                    warnings.append({
                        "code": "RESOURCE_EXTRACTION_FAILED",
                        "sheet": sheet_name,
                        "message": f"Failed to extract {tag} resource: {exc}",
                    })
                    continue
                if resource:
                    resources.append(resource)
        return resources

    @staticmethod
    def _iter_shape_elements(anchor, group_name: str | None = None):
        """anchor 하위의 도형 요소를 group을 펼쳐 순회한다."""
        for element in anchor:
            tag = element.tag.split("}")[-1]
            if tag == "grpSp":
                name = ExcelMediaExtractor._shape_name(element) or group_name
                yield from ExcelMediaExtractor._iter_shape_elements(element, name)
            elif tag in {"pic", "sp", "cxnSp", "graphicFrame"}:
                yield element, group_name

    @staticmethod
    def _shape_name(element) -> str | None:
        for properties in element.iter(f"{{{XDR_NS}}}cNvPr"):
            return properties.get("name")
        return None

    def _anchor_cells(self, anchor) -> dict[str, Any]:
        tag = anchor.tag.split("}")[-1]
        from_element = anchor.find(f"{{{XDR_NS}}}from")
        to_element = anchor.find(f"{{{XDR_NS}}}to")
        if from_element is not None:
            from_row, from_col = self._anchor_position(from_element)
        elif tag == "absoluteAnchor":
            from_row, from_col = self._absolute_position(anchor)
        else:
            from_row, from_col = 0, 0
        if to_element is not None:
            to_row, to_col = self._anchor_position(to_element)
        else:
            to_row, to_col = self._extent_position(anchor, from_row, from_col)
        return {
            "anchor_type": tag,
            "from_row": from_row + 1,
            "from_column": from_col + 1,
            "to_row": max(to_row + 1, from_row + 1),
            "to_column": max(to_col + 1, from_col + 1),
            "from_cell": f"{get_column_letter(from_col + 1)}{from_row + 1}",
            "to_cell": f"{get_column_letter(max(to_col, from_col) + 1)}{max(to_row, from_row) + 1}",
        }

    @staticmethod
    def _anchor_position(element) -> tuple[int, int]:
        row = element.find(f"{{{XDR_NS}}}row")
        column = element.find(f"{{{XDR_NS}}}col")
        return (
            int(row.text or 0) if row is not None else 0,
            int(column.text or 0) if column is not None else 0,
        )

    @staticmethod
    def _absolute_position(anchor) -> tuple[int, int]:
        position = anchor.find(f"{{{XDR_NS}}}pos")
        if position is None:
            return 0, 0
        x = int(position.get("x", "0"))
        y = int(position.get("y", "0"))
        return y // EMU_PER_ROW, x // EMU_PER_COLUMN

    @staticmethod
    def _extent_position(anchor, from_row: int, from_col: int) -> tuple[int, int]:
        extent = anchor.find(f"{{{XDR_NS}}}ext")
        if extent is None:
            return from_row, from_col
        width = int(extent.get("cx", "0"))
        height = int(extent.get("cy", "0"))
        return (
            from_row + max(height // EMU_PER_ROW, 0),
            from_col + max(width // EMU_PER_COLUMN, 0),
        )

    # ── resource 종류별 생성 ───────────────────────────────────────────────

    def _build_image(
        self, archive, names, drawing_part, relationships, element,
        anchor_info, sheet_index, sheet_name, z_order, group_name,
    ) -> dict[str, Any] | None:
        blip = next(element.iter(f"{{{A_NS}}}blip"), None)
        if blip is None:
            return None
        rel_id = blip.get(f"{{{R_NS}}}embed")
        entry = relationships.get(rel_id)
        if not entry:
            raise KeyError(f"missing image relationship: {rel_id}")
        media_part = self._resolve_part(drawing_part, entry[0])
        if media_part not in names:
            raise KeyError(f"missing media part: {media_part}")
        payload = archive.read(media_part)
        if len(payload) > MAX_RESOURCE_BYTES:
            raise ValueError("image exceeds the resource size limit")
        suffix = PurePosixPath(media_part).suffix.lower()
        mime_type = _IMAGE_MIME_BY_SUFFIX.get(suffix, "application/octet-stream")
        width, height = _image_dimensions(payload)
        resource = self._new_resource(
            resource_type="image",
            payload=payload,
            mime_type=mime_type,
            extension=suffix.lstrip(".") or "bin",
            anchor_info=anchor_info,
            sheet_index=sheet_index,
            sheet_name=sheet_name,
            z_order=z_order,
            group_name=group_name,
        )
        resource["details"] = {
            "name": self._shape_name(element),
            "source_part": media_part,
            "pixel_width": width,
            "pixel_height": height,
        }
        return resource

    def _build_shape(
        self, element, anchor_info, sheet_index, sheet_name, z_order, group_name, tag,
    ) -> dict[str, Any]:
        from xml.etree.ElementTree import tostring

        text = " ".join(
            node.text.strip()
            for node in element.iter(f"{{{A_NS}}}t")
            if node.text and node.text.strip()
        )[:MAX_SHAPE_TEXT_LENGTH]
        geometry = next(element.iter(f"{{{A_NS}}}prstGeom"), None)
        start_connection = next(element.iter(f"{{{A_NS}}}stCxn"), None)
        end_connection = next(element.iter(f"{{{A_NS}}}endCxn"), None)
        payload = tostring(element, encoding="utf-8")
        resource = self._new_resource(
            resource_type="shape",
            payload=payload,
            mime_type="application/xml",
            extension="xml",
            anchor_info=anchor_info,
            sheet_index=sheet_index,
            sheet_name=sheet_name,
            z_order=z_order,
            group_name=group_name,
        )
        resource["details"] = {
            "name": self._shape_name(element),
            "shape_kind": "connector" if tag == "cxnSp" else "shape",
            "shape_type": geometry.get("prst") if geometry is not None else None,
            "text": text,
            "start_shape_id": start_connection.get("id") if start_connection is not None else None,
            "end_shape_id": end_connection.get("id") if end_connection is not None else None,
            "shape_id": self._shape_id(element),
        }
        resource["surrounding_text"] = text
        return resource

    def _build_chart(
        self, archive, names, drawing_part, relationships, element,
        anchor_info, sheet_index, sheet_name, z_order, group_name,
    ) -> dict[str, Any] | None:
        chart_reference = next(element.iter(f"{{{C_NS}}}chart"), None)
        if chart_reference is None:
            return None
        rel_id = chart_reference.get(f"{{{R_NS}}}id")
        entry = relationships.get(rel_id)
        if not entry:
            raise KeyError(f"missing chart relationship: {rel_id}")
        chart_part = self._resolve_part(drawing_part, entry[0])
        if chart_part not in names:
            raise KeyError(f"missing chart part: {chart_part}")
        payload = archive.read(chart_part)
        chart = fromstring(payload)
        resource = self._new_resource(
            resource_type="chart",
            payload=payload,
            mime_type="application/xml",
            extension="xml",
            anchor_info=anchor_info,
            sheet_index=sheet_index,
            sheet_name=sheet_name,
            z_order=z_order,
            group_name=group_name,
        )
        resource["details"] = {
            "name": self._shape_name(element),
            "source_part": chart_part,
            "chart_type": _chart_type(chart),
            "title": _chart_title(chart),
            "series": _chart_series(chart),
            "source_ranges": _chart_source_ranges(chart),
        }
        return resource

    def _new_resource(
        self, *, resource_type, payload, mime_type, extension,
        anchor_info, sheet_index, sheet_name, z_order, group_name,
    ) -> dict[str, Any]:
        self._sequence += 1
        resource_id = f"{self.document_id}-r{self._sequence}"
        digest = hashlib.sha256(payload).hexdigest()
        filename = f"{resource_id}.{_EXTENSION_BY_MIME.get(mime_type, extension)}"
        path = self.staging_root / filename
        path.write_bytes(payload)
        resource = {
            "resource_id": resource_id,
            "document_id": self.document_id,
            "resource_type": resource_type,
            "mime_type": mime_type,
            "content_hash": f"sha256:{digest}",
            "file_size": len(payload),
            "local_path": str(path),
            "relative_path": f"{self.document_id}/{filename}",
            "sheet_id": f"sheet-{sheet_index}",
            "sheet_index": sheet_index,
            "sheet_name": sheet_name,
            "from_cell": anchor_info["from_cell"],
            "to_cell": anchor_info["to_cell"],
            "anchor": anchor_info,
            "z_order": z_order,
            "group_name": group_name,
            "linked_block_id": None,
            "linked_record_ids": [],
            "surrounding_range": None,
            "surrounding_text": "",
            "status": "extracted",
        }
        self._resources.append(resource)
        return resource

    @staticmethod
    def _shape_id(element) -> str | None:
        for properties in element.iter(f"{{{XDR_NS}}}cNvPr"):
            return properties.get("id")
        return None


# ── chart 세부 해석 ────────────────────────────────────────────────────────

def _chart_type(chart) -> str | None:
    plot_area = next(chart.iter(f"{{{C_NS}}}plotArea"), None)
    if plot_area is None:
        return None
    for child in plot_area:
        tag = child.tag.split("}")[-1]
        if tag.endswith("Chart"):
            return tag
    return None


def _chart_title(chart) -> str | None:
    title = next(chart.iter(f"{{{C_NS}}}title"), None)
    if title is None:
        return None
    text = " ".join(
        node.text.strip()
        for node in title.iter(f"{{{A_NS}}}t")
        if node.text and node.text.strip()
    )
    return text or None


def _chart_series(chart) -> list[dict[str, Any]]:
    series = []
    for index, element in enumerate(chart.iter(f"{{{C_NS}}}ser"), start=1):
        name_reference = element.find(f"{{{C_NS}}}tx")
        category = element.find(f"{{{C_NS}}}cat")
        values = element.find(f"{{{C_NS}}}val")
        series.append({
            "index": index,
            "name_range": _first_formula(name_reference),
            "category_range": _first_formula(category),
            "value_range": _first_formula(values),
        })
    return series


def _chart_source_ranges(chart) -> list[str]:
    ranges = []
    for node in chart.iter(f"{{{C_NS}}}f"):
        if node.text and node.text not in ranges:
            ranges.append(node.text)
    return ranges


def _first_formula(element) -> str | None:
    if element is None:
        return None
    node = next(element.iter(f"{{{C_NS}}}f"), None)
    return node.text if node is not None else None


# ── 이미지 크기 (외부 의존성 없이 헤더만 해석) ──────────────────────────────

def _image_dimensions(payload: bytes) -> tuple[int | None, int | None]:
    try:
        if payload.startswith(b"\x89PNG\r\n\x1a\n") and len(payload) >= 24:
            return int.from_bytes(payload[16:20], "big"), int.from_bytes(payload[20:24], "big")
        if payload.startswith(b"GIF") and len(payload) >= 10:
            return (
                int.from_bytes(payload[6:8], "little"),
                int.from_bytes(payload[8:10], "little"),
            )
        if payload.startswith(b"BM") and len(payload) >= 26:
            return (
                int.from_bytes(payload[18:22], "little"),
                int.from_bytes(payload[22:26], "little"),
            )
        if payload.startswith(b"\xff\xd8"):
            return _jpeg_dimensions(payload)
    except (IndexError, ValueError):
        return None, None
    return None, None


def _jpeg_dimensions(payload: bytes) -> tuple[int | None, int | None]:
    index = 2
    length = len(payload)
    while index + 9 < length:
        if payload[index] != 0xFF:
            index += 1
            continue
        marker = payload[index + 1]
        segment_length = int.from_bytes(payload[index + 2:index + 4], "big")
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height = int.from_bytes(payload[index + 5:index + 7], "big")
            width = int.from_bytes(payload[index + 7:index + 9], "big")
            return width, height
        index += 2 + segment_length
    return None, None

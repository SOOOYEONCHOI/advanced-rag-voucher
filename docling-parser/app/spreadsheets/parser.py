"""OpenPyXL 기반 OOXML Excel 파서."""

# 2026.08.12(sooyeon.choi) 추가 - Excel 전용 파서 및 자원 제한
from __future__ import annotations

from datetime import date, datetime, time
import logging
import os
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4
from zipfile import BadZipFile, ZipFile

import openpyxl
from openpyxl.cell.cell import TYPE_FORMULA
from openpyxl.utils import get_column_letter, range_boundaries

from app.spreadsheets.media import ExcelMediaExtractor
from app.spreadsheets.number_format import format_value as format_display_number
from app.spreadsheets.ir import (
    ExcelBlock,
    ExcelCell,
    ExcelRecord,
    ExcelSheet,
    ExcelStyle,
    ExcelWorkbook,
)


MAX_SHEETS = 100
MAX_ROWS_PER_SHEET = 100_000
MAX_COLUMNS_PER_SHEET = 500
MAX_CELLS_PER_SHEET = 2_000_000
MAX_CELL_TEXT_LENGTH = 10_000
MAX_MARKDOWN_TABLE_ROWS = 100
MAX_MARKDOWN_TABLE_CHARS = 30_000
MAX_WARNINGS = 100
INCLUDE_HIDDEN_SHEETS = False
EMPTY_COLUMNS_FOR_BLOCK_SPLIT = 2
# 2026.08.27(sooyeon.choi) 추가 - 수식 중심 표 판정 기준
FORMULA_DOMINANT_RATIO = 0.5
# 2026.08.27(sooyeon.choi) 추가 - resource marker 정본과 기본 staging 경로
RESOURCE_MARKER_FORMAT = "⟦RESOURCE:{resource_id}⟧"
DEFAULT_PARSER_RESOURCE_ROOT = "/app/data/resources"

MAX_ARCHIVE_ENTRIES = 10_000
MAX_UPLOAD_SIZE = 100 * 1024 * 1024
MAX_UNCOMPRESSED_SIZE = 1024 * 1024 * 1024
MAX_ARCHIVE_ENTRY_SIZE = 200 * 1024 * 1024
MAX_COMPRESSION_RATIO = 100

# 2026.08.27(sooyeon.choi) 추가 - StructuredSpreadsheet IR
SPREADSHEET_SCHEMA_NAME = "StructuredSpreadsheet"
SPREADSHEET_SCHEMA_VERSION = "1.0"

logger = logging.getLogger(__name__)


class OpenpyxlExcelParser:
    SUPPORTED_EXTENSIONS = {".xlsx", ".xlsm", ".xltx", ".xltm"}

    def parse(
        self,
        file_path: str,
        output_format: str = "md",
        document_id: str | None = None,
        # 2026.08.27(sooyeon.choi) 추가 - resource 원본 staging 경로
        resource_root: str | None = None,
    ) -> dict[str, Any]:
        extension = Path(file_path).suffix.lower()
        if extension not in self.SUPPORTED_EXTENSIONS:
            raise ValueError(f"Unsupported Excel format: {extension}")
        if output_format not in {"md", "json"}:
            raise ValueError(f"Unsupported output format: {output_format}")

        # 2026.08.27(sooyeon.choi) 수정 - Excel은 IR 단일 처리 경로 사용
        logger.info(
            "[EXCEL][processing] start processing_engine=ir "
            "processing_path=structured_ir file=%s",
            Path(file_path).name,
        )
        self._validate_archive(file_path)
        self._styles: dict[str, ExcelStyle] = {}
        self._style_keys: dict[tuple[Any, ...], str] = {}
        self._formula_cache_stale = False
        self._resources_by_id: dict[str, Any] = {}
        # 2026.08.27(sooyeon.choi) 추가 - resource 추출기 준비
        resolved_document_id = document_id or f"parse-{uuid4()}"
        extractor = ExcelMediaExtractor(
            resource_root or os.environ.get("PARSER_RESOURCE_ROOT", DEFAULT_PARSER_RESOURCE_ROOT),
            resolved_document_id,
        )
        resources: list[dict[str, Any]] = []
        value_workbook = None
        formula_workbook = None
        try:
            value_workbook = openpyxl.load_workbook(
                filename=file_path,
                read_only=False,
                data_only=True,
                keep_links=False,
            )
            formula_workbook = openpyxl.load_workbook(
                filename=file_path,
                read_only=False,
                data_only=False,
                keep_links=False,
            )
            # 2026.08.27(sooyeon.choi) 추가 - 수식 캐시 신선도 판정
            self._formula_cache_stale = self._detect_stale_formula_cache(formula_workbook)
            parsed_sheets, excluded_sheets = self._parse_workbook(
                value_workbook, formula_workbook
            )
            # 2026.08.27(sooyeon.choi) 추가 - 이미지·도형·차트 원본 추출과 anchor 연결
            resources, resource_warnings = extractor.extract(
                file_path, [sheet.title for sheet in value_workbook.worksheets]
            )
            self._link_resources(parsed_sheets, resources, resource_warnings)
        except Exception:
            extractor.discard()
            raise
        finally:
            if value_workbook is not None:
                value_workbook.close()
            if formula_workbook is not None:
                formula_workbook.close()

        workbook_ir = self._build_workbook_ir(
            parsed_sheets,
            excluded_sheets,
            file_path,
            resolved_document_id,
            resources,
        )
        try:
            result = self._build_result(workbook_ir, output_format)
        except Exception:
            extractor.discard()
            raise
        extractor.commit()
        logger.info(
            "[EXCEL][processing] complete processing_engine=ir "
            "processing_path=structured_ir sheets=%s resources=%s file=%s",
            len(parsed_sheets),
            len(resources),
            Path(file_path).name,
        )
        return result

    def _validate_archive(self, file_path: str) -> None:
        if Path(file_path).stat().st_size > MAX_UPLOAD_SIZE:
            raise ValueError("Excel file exceeds the upload size limit")
        try:
            with ZipFile(file_path) as archive:
                entries = archive.infolist()
                if len(entries) > MAX_ARCHIVE_ENTRIES:
                    raise ValueError("Excel archive contains too many entries")

                total_size = 0
                for entry in entries:
                    path = PurePosixPath(entry.filename)
                    if path.is_absolute() or ".." in path.parts:
                        raise ValueError("Excel archive contains an unsafe entry path")
                    if entry.flag_bits & 0x1:
                        raise ValueError("Encrypted Excel archives are not supported")
                    if entry.file_size > MAX_ARCHIVE_ENTRY_SIZE:
                        raise ValueError("Excel archive entry exceeds the size limit")
                    total_size += entry.file_size
                    if total_size > MAX_UNCOMPRESSED_SIZE:
                        raise ValueError("Excel archive exceeds the uncompressed size limit")
                    ratio = entry.file_size / max(entry.compress_size, 1)
                    if ratio > MAX_COMPRESSION_RATIO:
                        raise ValueError("Excel archive compression ratio exceeds the limit")

                names = {entry.filename.replace("\\", "/") for entry in entries}
                if "[Content_Types].xml" not in names or "xl/workbook.xml" not in names:
                    raise ValueError("File is not a valid OOXML Excel container")
        except BadZipFile as exc:
            raise ValueError("File is not a valid OOXML Excel container") from exc

    def _parse_workbook(self, value_workbook, formula_workbook):
        parsed_sheets: list[ExcelSheet] = []
        excluded_sheets: list[dict[str, Any]] = []
        worksheets = value_workbook.worksheets

        if len(worksheets) > MAX_SHEETS:
            excluded_sheets.append({
                "reason": "sheet_limit",
                "count": len(worksheets) - MAX_SHEETS,
            })

        for sheet_index, value_sheet in enumerate(worksheets[:MAX_SHEETS], start=1):
            formula_sheet = formula_workbook[value_sheet.title]
            if value_sheet.sheet_state != "visible" and not INCLUDE_HIDDEN_SHEETS:
                excluded_sheets.append({
                    "sheet_index": sheet_index,
                    "sheet_name": value_sheet.title,
                    "sheet_state": value_sheet.sheet_state,
                    "reason": "hidden",
                })
                continue

            parsed_sheet = self._parse_sheet(value_sheet, formula_sheet, sheet_index)
            if parsed_sheet.source_range is None:
                excluded_sheets.append({
                    "sheet_index": sheet_index,
                    "sheet_name": value_sheet.title,
                    "sheet_state": value_sheet.sheet_state,
                    "reason": "empty",
                })
                continue
            parsed_sheets.append(parsed_sheet)
        return parsed_sheets, excluded_sheets

    # 2026.08.27(sooyeon.choi) 추가 - resource를 block/record와 주변 문맥에 연결
    def _link_resources(self, parsed_sheets, resources, resource_warnings) -> None:
        # display marker 옆에 도형 텍스트를 함께 표시하기 위한 조회용 map
        self._resources_by_id = {resource["resource_id"]: resource for resource in resources}
        sheets_by_id = {sheet.sheet_id: sheet for sheet in parsed_sheets}
        sheets_by_name = {sheet.sheet_name: sheet for sheet in parsed_sheets}

        for warning in resource_warnings:
            sheet = sheets_by_name.get(warning.get("sheet"))
            target = sheet.warnings if sheet else (parsed_sheets[0].warnings if parsed_sheets else None)
            if target is None or len(target) >= MAX_WARNINGS:
                continue
            target.append(warning)
            if sheet:
                sheet.warning_count += 1

        for resource in resources:
            sheet = sheets_by_id.get(resource["sheet_id"])
            if sheet is None:
                continue
            sheet.resource_ids.append(resource["resource_id"])
            anchor = resource["anchor"]
            block = self._resource_block(sheet, anchor)
            if block is None:
                continue
            block.resource_ids.append(resource["resource_id"])
            resource["linked_block_id"] = block.block_id
            linked_records = [
                record for record in block.records
                if record.row_start <= anchor["to_row"] and anchor["from_row"] <= record.row_end
            ]
            for record in linked_records:
                record.resource_ids.append(resource["resource_id"])
            resource["linked_record_ids"] = [record.record_id for record in linked_records]
            resource["surrounding_range"] = (
                linked_records[0].source_range if linked_records else block.source_range
            )
            resource["surrounding_text"] = self._surrounding_text(block, linked_records)

    @staticmethod
    def _resource_block(sheet, anchor):
        """anchor와 겹치는 block을 찾고, 없으면 같은 열 범위의 가장 가까운 block을 쓴다."""
        candidates = []
        for block in sheet.blocks:
            min_col, min_row, max_col, max_row = range_boundaries(block.source_range)
            if (
                min_row <= anchor["to_row"] and anchor["from_row"] <= max_row
                and min_col <= anchor["to_column"] and anchor["from_column"] <= max_col
            ):
                return block
            candidates.append((abs(min_row - anchor["from_row"]), block))
        return min(candidates, key=lambda item: item[0])[1] if candidates else None

    @staticmethod
    def _surrounding_text(block, linked_records) -> str:
        """resource 주변 문맥으로 헤더와 연결 record 값을 사용한다."""
        parts = [value for value in block.headers if value]
        for record in linked_records:
            parts.extend(value for value in record.values if value)
        text = " ".join(parts)
        return text[:MAX_CELL_TEXT_LENGTH]

    def _parse_sheet(self, value_sheet, formula_sheet, sheet_index: int) -> ExcelSheet:
        warnings: list[dict[str, Any]] = []
        warning_count = [0]
        bounds, truncated = self._find_used_range(value_sheet, formula_sheet, warnings, warning_count)
        sheet_id = f"sheet-{sheet_index}"
        parsed = ExcelSheet(
            sheet_id=sheet_id,
            sheet_index=sheet_index,
            sheet_name=value_sheet.title,
            sheet_state=value_sheet.sheet_state,
            source_range=None,
            inspected_range=None,
            title=None,
            description=None,
            blocks=[],
            resource_ids=[],
            warnings=warnings,
            warning_count=0,
            truncated=truncated,
        )
        if bounds is None:
            return parsed

        min_row, max_row, min_col, max_col = bounds
        parsed.source_range = self._range_string(min_row, max_row, min_col, max_col)
        parsed.inspected_range = parsed.source_range
        merged_map = self._build_merged_cell_map(formula_sheet)
        cells: list[list[ExcelCell]] = []
        for row in range(min_row, max_row + 1):
            cell_row: list[ExcelCell] = []
            for column in range(min_col, max_col + 1):
                merge_info = merged_map.get((row, column))
                anchor_row, anchor_column, merged_range = (
                    merge_info if merge_info else (row, column, None)
                )
                value_cell = value_sheet.cell(row, column)
                formula_cell = formula_sheet.cell(row, column)
                anchor_value_cell = value_sheet.cell(anchor_row, anchor_column)
                anchor_formula_cell = formula_sheet.cell(anchor_row, anchor_column)
                cell_row.append(self._build_cell(
                    value_cell=value_cell,
                    formula_cell=formula_cell,
                    anchor_value_cell=anchor_value_cell,
                    anchor_formula_cell=anchor_formula_cell,
                    parsed_sheet=parsed,
                    warning_count=warning_count,
                    merged_range=merged_range,
                    is_merge_anchor=(row == anchor_row and column == anchor_column),
                    value_sheet=value_sheet,
                ))
            cells.append(cell_row)

        parsed.blocks = self._split_blocks(cells, sheet_id)
        # 2026.08.27(sooyeon.choi) 추가 - block 경계를 넘는 병합 범위 추적
        self._flag_cross_block_merges(cells, parsed, warning_count)
        parsed.warning_count = warning_count[0]
        return parsed

    def _flag_cross_block_merges(self, cells, parsed_sheet, warning_count) -> None:
        """병합 범위가 여러 block에 걸치면 warning을 남기고 block에 표시한다.

        block 분할은 그대로 두고(보수적 처리) 상속값도 유지하므로 데이터 손실은 없으며,
        소비 측이 헤더 상속을 신뢰할 수 없는 구간을 식별할 수 있다.
        """
        merged_ranges = {
            cell.merged_range
            for row in cells
            for cell in row
            if cell.merged_range
        }
        for range_text in sorted(merged_ranges):
            merge_min_col, merge_min_row, merge_max_col, merge_max_row = range_boundaries(range_text)
            touching = [
                block for block in parsed_sheet.blocks
                if self._ranges_intersect(block.source_range, range_text)
            ]
            if not touching:
                continue
            crosses = len(touching) > 1
            if not crosses:
                block_min_col, block_min_row, block_max_col, block_max_row = range_boundaries(
                    touching[0].source_range
                )
                crosses = not (
                    block_min_row <= merge_min_row and merge_max_row <= block_max_row
                    and block_min_col <= merge_min_col and merge_max_col <= block_max_col
                )
            if not crosses:
                continue
            for block in touching:
                block.cross_block_merge = True
            self._warn(
                parsed_sheet.warnings,
                warning_count,
                "MERGE_CROSSES_BLOCK",
                parsed_sheet.sheet_name,
                range_text,
                "Merged range spans block boundaries; inherited header context is not guaranteed.",
            )

    @staticmethod
    def _ranges_intersect(left: str, right: str) -> bool:
        left_min_col, left_min_row, left_max_col, left_max_row = range_boundaries(left)
        right_min_col, right_min_row, right_max_col, right_max_row = range_boundaries(right)
        return (
            left_min_row <= right_max_row and right_min_row <= left_max_row
            and left_min_col <= right_max_col and right_min_col <= left_max_col
        )

    def _find_used_range(self, value_sheet, formula_sheet, warnings, warning_count):
        scan_rows = min(max(value_sheet.max_row, formula_sheet.max_row), MAX_ROWS_PER_SHEET)
        scan_columns = min(
            max(value_sheet.max_column, formula_sheet.max_column),
            MAX_COLUMNS_PER_SHEET,
        )
        if scan_rows * scan_columns > MAX_CELLS_PER_SHEET:
            scan_rows = max(1, MAX_CELLS_PER_SHEET // max(scan_columns, 1))

        truncated = (
            value_sheet.max_row > scan_rows
            or formula_sheet.max_row > scan_rows
            or value_sheet.max_column > scan_columns
            or formula_sheet.max_column > scan_columns
        )
        if truncated:
            self._warn(
                warnings,
                warning_count,
                "SHEET_TRUNCATED",
                value_sheet.title,
                None,
                "Sheet inspection was limited by row, column, or cell limits.",
            )

        min_row = min_col = None
        max_row = max_col = 0
        for row in range(1, scan_rows + 1):
            for column in range(1, scan_columns + 1):
                value = value_sheet.cell(row, column).value
                formula = formula_sheet.cell(row, column).value
                if self._has_meaningful_value(value) or self._has_meaningful_value(formula):
                    min_row = row if min_row is None else min(min_row, row)
                    min_col = column if min_col is None else min(min_col, column)
                    max_row = max(max_row, row)
                    max_col = max(max_col, column)
        if min_row is None or min_col is None:
            return None, truncated
        return (min_row, max_row, min_col, max_col), truncated

    @staticmethod
    def _has_meaningful_value(value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        return True

    @staticmethod
    def _build_merged_cell_map(sheet) -> dict[tuple[int, int], tuple[int, int, str]]:
        merged_map = {}
        for merged_range in sheet.merged_cells.ranges:
            range_text = str(merged_range)
            min_col, min_row, max_col, max_row = range_boundaries(range_text)
            for row in range(min_row, max_row + 1):
                for column in range(min_col, max_col + 1):
                    merged_map[(row, column)] = (min_row, min_col, range_text)
        return merged_map

    def _build_cell(
        self,
        *,
        value_cell,
        formula_cell,
        anchor_value_cell,
        anchor_formula_cell,
        parsed_sheet,
        warning_count,
        merged_range,
        is_merge_anchor,
        value_sheet,
    ) -> ExcelCell:
        cached_value = anchor_value_cell.value
        formula_value = anchor_formula_cell.value
        is_formula = anchor_formula_cell.data_type == TYPE_FORMULA or (
            isinstance(formula_value, str) and formula_value.startswith("=")
        )
        cache_status = "not_applicable"
        if is_formula and cached_value is None:
            cache_status = "missing"
            self._warn(
                parsed_sheet.warnings,
                warning_count,
                "FORMULA_CACHE_MISSING",
                parsed_sheet.sheet_name,
                anchor_formula_cell.coordinate,
                "Formula has no cached result.",
            )
        elif is_formula:
            # 2026.08.27(sooyeon.choi) 수정 - 재계산 대기 workbook의 캐시는 stale로 표시
            cache_status = "stale" if self._formula_cache_stale else "available"

        raw_value = formula_value if is_formula else anchor_formula_cell.value
        display_source = cached_value if is_formula else anchor_value_cell.value
        display_text = self._format_display_value(
            display_source,
            anchor_value_cell.number_format,
            parsed_sheet,
            warning_count,
            anchor_formula_cell.coordinate,
        )
        effective_text = display_text
        inherited_from = None
        inheritance_reason = None
        if merged_range and not is_merge_anchor:
            inherited_from = anchor_formula_cell.coordinate
            min_col, min_row, max_col, max_row = range_boundaries(merged_range)
            inheritance_reason = "vertical_merge" if min_col == max_col else "horizontal_merge"

        physical_display = display_text if (not merged_range or is_merge_anchor) else ""
        hyperlink = anchor_formula_cell.hyperlink or anchor_value_cell.hyperlink
        hyperlink_target = None
        if hyperlink is not None:
            hyperlink_target = str(hyperlink.target or hyperlink.location or "") or None
        comment = anchor_formula_cell.comment or anchor_value_cell.comment
        row_dimension = value_sheet.row_dimensions[value_cell.row]
        column_letter = get_column_letter(value_cell.column)
        column_dimension = value_sheet.column_dimensions[column_letter]
        return ExcelCell(
            coordinate=value_cell.coordinate,
            row=value_cell.row,
            column=value_cell.column,
            raw_value=self._json_value(raw_value),
            display_value=physical_display,
            effective_value=effective_text,
            formula=str(formula_value) if is_formula else None,
            formula_cached_value=self._json_value(cached_value) if is_formula else None,
            formula_cache_status=cache_status,
            data_type=self._value_type(display_source),
            number_format=anchor_formula_cell.number_format or "General",
            hyperlink=hyperlink_target,
            comment=comment.text if comment else None,
            merged_range=merged_range,
            is_merge_anchor=bool(merged_range and is_merge_anchor),
            inherited_from=inherited_from,
            inheritance_reason=inheritance_reason,
            style_ref=self._style_ref(anchor_formula_cell),
            row_height=row_dimension.height,
            column_width=column_dimension.width,
            hidden_row=bool(row_dimension.hidden),
            hidden_column=bool(column_dimension.hidden),
        )

    # 2026.08.27(sooyeon.choi) 수정 - 단계 7 number_format 기반 표시값 생성
    def _format_display_value(self, value, number_format, parsed_sheet, warning_count, coordinate):
        text, supported = format_display_number(value, number_format)
        if not supported:
            self._warn(
                parsed_sheet.warnings,
                warning_count,
                "DISPLAY_FORMAT_UNSUPPORTED",
                parsed_sheet.sheet_name,
                coordinate,
                f"Unsupported number_format retained as raw display: {number_format!r}",
            )

        text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
        if len(text) > MAX_CELL_TEXT_LENGTH:
            text = text[:MAX_CELL_TEXT_LENGTH] + "[truncated]"
            self._warn(
                parsed_sheet.warnings,
                warning_count,
                "CELL_TEXT_TRUNCATED",
                parsed_sheet.sheet_name,
                coordinate,
                "Cell text exceeded the output length limit.",
            )
        return text

    @staticmethod
    def _json_value(value):
        if isinstance(value, (datetime, date, time)):
            return value.isoformat()
        return value

    def _style_ref(self, cell) -> str:
        font_color = self._color_value(cell.font.color)
        fill_color = self._color_value(cell.fill.fgColor)
        border = tuple(getattr(cell.border, side).style for side in ("left", "right", "top", "bottom"))
        key = (
            cell.number_format, bool(cell.font.bold), bool(cell.font.italic), font_color,
            fill_color, border, cell.alignment.horizontal, cell.alignment.vertical,
            bool(cell.alignment.wrap_text),
        )
        if key in self._style_keys:
            return self._style_keys[key]
        style_ref = f"style-{len(self._styles) + 1}"
        self._style_keys[key] = style_ref
        self._styles[style_ref] = ExcelStyle(
            style_ref=style_ref,
            number_format=cell.number_format or "General",
            bold=bool(cell.font.bold),
            italic=bool(cell.font.italic),
            font_color=font_color,
            fill_color=fill_color,
            border=dict(zip(("left", "right", "top", "bottom"), border)),
            horizontal_alignment=cell.alignment.horizontal,
            vertical_alignment=cell.alignment.vertical,
            wrap_text=bool(cell.alignment.wrap_text),
        )
        return style_ref

    @staticmethod
    def _color_value(color) -> str | None:
        if color is None:
            return None
        value = getattr(color, "rgb", None) or getattr(color, "indexed", None) or getattr(color, "theme", None)
        return str(value) if value is not None else None

    # 2026.08.27(sooyeon.choi) 추가 - 캐시 재계산 대기 workbook 판정
    @staticmethod
    def _detect_stale_formula_cache(formula_workbook) -> bool:
        calculation = getattr(formula_workbook, "calculation", None)
        if calculation is None:
            return False
        return bool(
            getattr(calculation, "fullCalcOnLoad", False)
            or getattr(calculation, "calcCompleted", True) is False
        )

    @staticmethod
    def _value_type(value: Any) -> str:
        if value is None or (isinstance(value, str) and not value.strip()):
            return "empty"
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, (int, float)):
            return "number"
        if isinstance(value, (date, datetime, time)):
            return "date"
        return "string"

    @staticmethod
    def _escape_markdown(text: str) -> str:
        return text.replace("\\", "\\\\").replace("|", "\\|").replace("\n", "<br>")

    def _split_blocks(self, cells: list[list[ExcelCell]], sheet_id: str) -> list[ExcelBlock]:
        blocks: list[ExcelBlock] = []
        block_start = None
        empty_row = [] if not cells else [None] * len(cells[0])
        for index, row in enumerate(cells + [empty_row]):
            has_value = any(cell and cell.effective_value != "" for cell in row)
            if has_value and block_start is None:
                block_start = index
            elif not has_value and block_start is not None:
                blocks.extend(self._split_horizontal_block(cells[block_start:index], sheet_id, len(blocks)))
                block_start = None
        return blocks

    def _split_horizontal_block(self, rows, sheet_id, existing_count):
        occupied_columns = [
            any(row[column].effective_value != "" for row in rows) for column in range(len(rows[0]))
        ]
        ranges = []
        range_start = None
        empty_run = 0
        for column, occupied in enumerate(occupied_columns + [False] * EMPTY_COLUMNS_FOR_BLOCK_SPLIT):
            if occupied:
                if range_start is None:
                    range_start = column
                empty_run = 0
            elif range_start is not None:
                empty_run += 1
                if empty_run >= EMPTY_COLUMNS_FOR_BLOCK_SPLIT:
                    ranges.append((range_start, column - empty_run))
                    range_start = None
                    empty_run = 0

        blocks: list[ExcelBlock] = []
        for left, right in ranges:
            block_cells = [row[left:right + 1] for row in rows]
            display_rows = [[cell.effective_value for cell in row] for row in block_cells]
            physical_rows = [[cell.display_value for cell in row] for row in block_cells]
            value_types = [[cell.data_type for cell in row] for row in block_cells]
            header_rows = self._detect_header_rows(display_rows, value_types)
            block_index = existing_count + len(blocks) + 1
            min_row = block_cells[0][0].row
            max_row = block_cells[-1][-1].row
            min_col = block_cells[0][0].column
            max_col = block_cells[0][-1].column
            source_range = self._range_string(min_row, max_row, min_col, max_col)
            is_table = len(block_cells) > 1 and len(block_cells[0]) > 1
            block_type = "record_table" if is_table and header_rows else (
                "unknown_table" if is_table else "paragraph"
            )
            header_source = physical_rows if header_rows == 1 else display_rows
            # 2026.08.27(sooyeon.choi) 수정 - 열별 다단 header path 생성
            # 단일 헤더 행은 물리값을 써서 가로 병합 제목이 모든 열에 복제되지 않게 한다.
            header_paths = self._build_header_paths(header_source[:header_rows]) if header_rows else []
            headers = [" / ".join(path) for path in header_paths]
            records = self._build_records(
                block_cells, header_rows, sheet_id, min_col, max_col
            )
            # 2026.08.27(sooyeon.choi) 추가 - 수식 중심 표 판정 통계
            formula_count, formula_ratio = self._formula_statistics(block_cells[header_rows:])
            blocks.append(ExcelBlock(
                block_id=f"{sheet_id}:block-{block_index}",
                block_index=block_index,
                block_type=block_type,
                source_block_type="table" if is_table else "text",
                source_range=source_range,
                header_row_count=header_rows,
                header_range=self._range_string(min_row, min_row + header_rows - 1, min_col, max_col) if header_rows else None,
                headers=headers,
                header_columns=[
                    {
                        "column": min_col + index,
                        "header": header,
                        # 2026.08.27(sooyeon.choi) 추가 - 병합 상속을 반영한 열별 header path
                        "header_path": header_paths[index] if index < len(header_paths) else [],
                        "physical_header": (
                            physical_rows[0][index] if header_rows and index < len(physical_rows[0]) else ""
                        ),
                    }
                    for index, header in enumerate(headers)
                ],
                header_paths=header_paths,
                formula_cell_count=formula_count,
                formula_ratio=formula_ratio,
                formula_dominant=formula_ratio >= FORMULA_DOMINANT_RATIO and formula_count > 0,
                records=records,
                cells=block_cells,
                resource_ids=[],
                classification_confidence=0.9 if header_rows else 0.6,
                classification_reasons=["header_rows_detected"] if header_rows else ["rectangular_values_without_header"],
            ))
        return blocks

    def _build_records(self, cells, header_rows, sheet_id, min_col, max_col):
        records = []
        for row_cells in cells[header_rows:]:
            row_number = row_cells[0].row
            values = [cell.effective_value for cell in row_cells]
            if not any(values):
                continue
            records.append(ExcelRecord(
                record_id=f"{sheet_id}:row-{row_number}",
                source_range=self._range_string(row_number, row_number, min_col, max_col),
                row_start=row_number,
                row_end=row_number,
                values=values,
                cells=row_cells,
                # 2026.08.27(sooyeon.choi) 추가 - 병합 상속, 수식 manifest
                physical_values=[cell.display_value for cell in row_cells],
                inherited_cells=[
                    {
                        "column": cell.column,
                        "coordinate": cell.coordinate,
                        "inherited_from": cell.inherited_from,
                        "inheritance_reason": cell.inheritance_reason,
                        "effective_value": cell.effective_value,
                    }
                    for cell in row_cells
                    if cell.inherited_from
                ],
                formulas=[
                    {
                        "coordinate": cell.coordinate,
                        "formula": cell.formula,
                        "cached_value": cell.formula_cached_value,
                        "cache_status": cell.formula_cache_status,
                    }
                    for cell in row_cells
                    if cell.formula
                ],
            ))
        return records

    @staticmethod
    def _detect_header_rows(rows, value_types) -> int:
        if len(rows) < 2 or len(rows[0]) < 2:
            return 0
        # 2026.08.12(sooyeon.choi) 추가 - 최대 3행의 문자열 중심 다단 헤더 판정
        header_rows = 0
        for index in range(min(3, len(rows) - 1)):
            non_empty_count = sum(value != "" for value in rows[index])
            string_count = sum(kind == "string" for kind in value_types[index])
            if non_empty_count / len(rows[index]) < 0.5:
                break
            if string_count / max(non_empty_count, 1) < 0.7:
                break
            lower_types = {
                kind
                for row in value_types[index + 1:index + 4]
                for kind in row
                if kind != "empty"
            }
            if lower_types.intersection({"number", "date", "boolean"}):
                header_rows = index + 1
        # 2026.08.27(sooyeon.choi) 추가 - 문자열 전용 업무표의 명시적 첫 행 헤더 보존
        if header_rows == 0:
            first_values = [value for value in rows[0] if value]
            first_types = [kind for value, kind in zip(rows[0], value_types[0]) if value]
            if first_values and len(first_values) == len(rows[0]) and all(kind == "string" for kind in first_types):
                header_rows = 1
        return header_rows

    def _build_workbook_ir(self, sheets, excluded_sheets, file_path, document_id, resources=None):
        warnings = [warning for sheet in sheets for warning in sheet.warnings]
        # 2026.08.27(sooyeon.choi) 추가 - 오래된 수식 캐시 위험을 workbook warning으로 추적
        if self._formula_cache_stale:
            warnings = [{
                "code": "FORMULA_CACHE_STALE",
                "sheet": None,
                "message": "Workbook requires full recalculation; cached formula values may be stale.",
            }, *warnings]
        extension = Path(file_path).suffix.lower().lstrip(".")
        document = {
            "document_id": document_id,
            "original_filename": Path(file_path).name,
            "file_format": extension,
            "source_type": "spreadsheet",
            "parser": "openpyxl",
            "parser_version": "1.0",
            "formula_policy": "display_and_formula",
            "formula_recalculated": False,
            # 2026.08.27(sooyeon.choi) 추가 - 캐시 신선도 상태
            "formula_cache_stale": self._formula_cache_stale,
            "sheet_count": len(sheets),
            "excluded_sheets": excluded_sheets,
            "warning_count": sum(sheet.warning_count for sheet in sheets) + (1 if self._formula_cache_stale else 0),
            "warnings": warnings,
            "processing_engine": "ir",
            "processing_path": "structured_ir",
            # 2026.08.27(sooyeon.choi) 추가 - resource 집계
            "resource_count": len(resources or []),
            "image_count": sum(1 for item in resources or [] if item["resource_type"] == "image"),
            "shape_count": sum(1 for item in resources or [] if item["resource_type"] == "shape"),
            "chart_count": sum(1 for item in resources or [] if item["resource_type"] == "chart"),
        }
        return ExcelWorkbook(
            schema_name=SPREADSHEET_SCHEMA_NAME,
            schema_version=SPREADSHEET_SCHEMA_VERSION,
            document=document,
            styles=self._styles,
            sheets=sheets,
            resources=list(resources or []),
            excluded_sheets=excluded_sheets,
            warnings=warnings,
            warning_count=document["warning_count"],
        )

    def _build_result(self, workbook: ExcelWorkbook, output_format: str):
        workbook_dict = workbook.to_dict()
        pages = []
        for page_no, sheet in enumerate(workbook.sheets, start=1):
            markdown = self._render_sheet_markdown(sheet)
            embedding_text = self._render_sheet_embedding(sheet)
            sheet_dict = next(item for item in workbook_dict["sheets"] if item["sheet_id"] == sheet.sheet_id)
            pages.append({
                "page_no": page_no,
                "sheet_id": sheet.sheet_id,
                "sheet_name": sheet.sheet_name,
                "sheet_index": sheet.sheet_index,
                "markdown": markdown,
                "embedding_text": embedding_text,
                "blocks": sheet_dict["blocks"],
                "metadata": {
                    "sheet_state": sheet.sheet_state,
                    "source_range": sheet.source_range,
                    "inspected_range": sheet.inspected_range,
                    "truncated": sheet.truncated,
                    "warnings": sheet.warnings,
                    "warning_count": sheet.warning_count,
                },
            })
        result = {
            "schema_name": workbook.schema_name,
            "schema_version": workbook.schema_version,
            "format": output_format,
            "pages": pages,
            "num_pages": len(pages),
            "metadata": workbook.document,
            "styles": workbook_dict["styles"],
            "resources": workbook.resources,
            "excluded_sheets": workbook.excluded_sheets,
            "warnings": workbook.warnings,
            "warning_count": workbook.warning_count,
        }
        if output_format == "json":
            result["content"] = workbook_dict
        return result

    def _render_sheet_markdown(self, sheet: ExcelSheet) -> str:
        sections = [f"# Sheet: {sheet.sheet_name}"]
        for block in sheet.blocks:
            if block.block_type == "paragraph":
                values = [cell.display_value for row in block.cells for cell in row if cell.display_value]
                if values:
                    sections.extend([f"## Section {block.block_index}", " ".join(map(self._escape_markdown, values))])
                    # 2026.08.27(sooyeon.choi) 추가 - resource marker는 display에만 넣는다.
                    if block.resource_ids:
                        sections.append(self._resource_markers(block.resource_ids))
                continue
            # 2026.08.27(sooyeon.choi) 수정 - 원본에 없는 가상 Column 헤더를 생성하지 않음
            headers = block.headers or ["" for _ in block.cells[0]]
            display_rows = []
            for row in block.cells[block.header_row_count:]:
                display_rows.append([self._escape_markdown(cell.display_value) for cell in row])
            sections.append(f"## Table {block.block_index}")
            sections.append("\n".join([
                "| " + " | ".join(map(self._escape_markdown, headers)) + " |",
                "| " + " | ".join("---" for _ in headers) + " |",
                *("| " + " | ".join(row) + " |" for row in display_rows),
            ]))
            # 2026.08.27(sooyeon.choi) 추가 - resource marker는 display에만 넣는다.
            if block.resource_ids:
                sections.append(self._resource_markers(block.resource_ids))
        return "\n\n".join(sections)

    def _resource_markers(self, resource_ids) -> str:
        """marker와 도형 텍스트를 display Markdown에만 남긴다."""
        parts = []
        for resource_id in resource_ids:
            marker = RESOURCE_MARKER_FORMAT.format(resource_id=resource_id)
            details = (getattr(self, "_resources_by_id", {}).get(resource_id) or {}).get("details") or {}
            text = details.get("text") or details.get("title")
            parts.append(f"{marker} {self._escape_markdown(text)}" if text else marker)
        return " ".join(parts)

    def _render_sheet_embedding(self, sheet: ExcelSheet) -> str:
        sections = [f"시트: {sheet.sheet_name}"]
        for block in sheet.blocks:
            if block.headers:
                for record in block.records:
                    pairs = [f"{header}: {value}" for header, value in zip(block.headers, record.values) if value]
                    if pairs:
                        sections.append(" | ".join(pairs))
            else:
                for record in block.records:
                    text = " ".join(value for value in record.values if value)
                    if text:
                        sections.append(text)
        return "\n".join(sections)

    # 2026.08.27(sooyeon.choi) 수정 - 열별 header path 목록으로 확장
    @staticmethod
    def _build_header_paths(header_rows) -> list[list[str]]:
        if not header_rows:
            return []
        paths: list[list[str]] = []
        for column in range(len(header_rows[0])):
            segments: list[str] = []
            for row in header_rows:
                value = row[column]
                if value and (not segments or segments[-1] != value):
                    segments.append(value)
            paths.append(segments)
        return paths

    # 2026.08.27(sooyeon.choi) 추가 - 수식 셀 비율 계산 (데이터 행 기준)
    @staticmethod
    def _formula_statistics(data_rows) -> tuple[int, float]:
        formula_count = 0
        filled_count = 0
        for row in data_rows:
            for cell in row:
                if cell.formula:
                    formula_count += 1
                if cell.effective_value != "":
                    filled_count += 1
        ratio = formula_count / filled_count if filled_count else 0.0
        return formula_count, round(ratio, 4)


    @staticmethod
    def _range_string(min_row, max_row, min_col, max_col):
        return f"{get_column_letter(min_col)}{min_row}:{get_column_letter(max_col)}{max_row}"

    @staticmethod
    def _warn(warnings, warning_count, code, sheet, cell, message):
        warning_count[0] += 1
        if len(warnings) < MAX_WARNINGS:
            warning = {"code": code, "sheet": sheet, "message": message}
            if cell is not None:
                warning["cell"] = cell
            warnings.append(warning)

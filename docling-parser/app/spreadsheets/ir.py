"""StructuredSpreadsheet 1.0 typed IR models."""

# 2026.08.27(sooyeon.choi) 추가
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


CANONICAL_BLOCK_TYPES = frozenset({
    "title", "metadata", "paragraph", "record_table", "key_value", "form",
    "matrix", "timeseries", "card_grid", "process_flow", "image_gallery",
    "instruction", "note", "resource_group", "empty", "unknown_table",
})


@dataclass
class ExcelStyle:
    style_ref: str
    number_format: str
    bold: bool
    italic: bool
    font_color: str | None
    fill_color: str | None
    border: dict[str, str | None]
    horizontal_alignment: str | None
    vertical_alignment: str | None
    wrap_text: bool


@dataclass
class ExcelCell:
    coordinate: str
    row: int
    column: int
    raw_value: Any
    display_value: str
    effective_value: str
    formula: str | None
    formula_cached_value: Any
    formula_cache_status: str
    data_type: str
    number_format: str
    hyperlink: str | None
    comment: str | None
    merged_range: str | None
    is_merge_anchor: bool
    inherited_from: str | None
    inheritance_reason: str | None
    style_ref: str
    row_height: float | None
    column_width: float | None
    hidden_row: bool
    hidden_column: bool


@dataclass
class ExcelRecord:
    record_id: str
    source_range: str
    row_start: int
    row_end: int
    values: list[str]
    cells: list[ExcelCell]
    resource_ids: list[str] = field(default_factory=list)
    # 2026.08.27(sooyeon.choi) 추가 - 병합 상속/수식 manifest 분리
    physical_values: list[str] = field(default_factory=list)
    inherited_cells: list[dict[str, Any]] = field(default_factory=list)
    formulas: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ExcelBlock:
    block_id: str
    block_index: int
    block_type: str
    source_block_type: str | None
    source_range: str
    header_row_count: int
    header_range: str | None
    headers: list[str]
    header_columns: list[dict[str, Any]]
    records: list[ExcelRecord]
    cells: list[list[ExcelCell]]
    resource_ids: list[str]
    classification_confidence: float
    classification_reasons: list[str]
    # 2026.08.27(sooyeon.choi) 추가 - 다단 header path와 수식 정책 신호
    header_paths: list[list[str]] = field(default_factory=list)
    formula_cell_count: int = 0
    formula_ratio: float = 0.0
    formula_dominant: bool = False
    cross_block_merge: bool = False

    def __post_init__(self) -> None:
        if self.block_type not in CANONICAL_BLOCK_TYPES:
            raise ValueError(f"Unsupported block_type: {self.block_type}")


@dataclass
class ExcelSheet:
    sheet_id: str
    sheet_index: int
    sheet_name: str
    sheet_state: str
    source_range: str | None
    inspected_range: str | None
    title: str | None
    description: str | None
    blocks: list[ExcelBlock]
    resource_ids: list[str]
    truncated: bool
    warnings: list[dict[str, Any]]
    warning_count: int


@dataclass
class ExcelWorkbook:
    schema_name: str
    schema_version: str
    document: dict[str, Any]
    styles: dict[str, ExcelStyle]
    sheets: list[ExcelSheet]
    resources: list[dict[str, Any]]
    excluded_sheets: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    warning_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

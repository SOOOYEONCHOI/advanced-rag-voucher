"""StructuredSpreadsheet IR 기반 Excel 전용 청커."""

# 2026.08.27(sooyeon.choi) 추가 - 단계 4 SpreadsheetChunker
from __future__ import annotations

import re
from typing import Any, Iterable

from ..config import ChunkingConfig
from ..models import LCDocument


_ROW_GROUP_TYPES = {
    "record_table", "key_value", "form", "matrix", "timeseries", "unknown_table",
    "metadata", "card_grid", "process_flow", "image_gallery", "resource_group",
}
_BLOCK_TYPES = {"title", "paragraph", "instruction", "note"}
_CELL_RANGE_RE = re.compile(r"^([A-Z]+)(\d+):([A-Z]+)(\d+)$")
# 2026.08.27(sooyeon.choi) 추가 - 단계 8 resource marker 정본 (display 전용)
_RESOURCE_MARKER_FORMAT = "⟦RESOURCE:{resource_id}⟧"
_TOKEN_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)


class SpreadsheetChunker:
    """시트와 블록 경계를 넘지 않고 IR record 단위로 청킹한다."""

    def __init__(self, config: ChunkingConfig):
        self.config = config

    def split_documents(self, documents: list[LCDocument]) -> list[LCDocument]:
        chunks: list[LCDocument] = []
        for document in documents:
            blocks = document.metadata.get("structured_ir", {}).get("blocks", [])
            for block in blocks:
                block_type = block.get("block_type", "unknown_table")
                if block_type == "empty":
                    continue
                if block_type in _ROW_GROUP_TYPES:
                    chunks.extend(self._split_records(document, block))
                elif block_type in _BLOCK_TYPES:
                    chunks.extend(self._split_block(document, block))
                else:
                    # 계약 검증 이전의 알 수 없는 입력도 block 경계를 유지하여 보수적으로 처리한다.
                    chunks.extend(self._split_records(document, block))
                if self.config.spreadsheet_summary_chunks:
                    chunks.append(self._summary_chunk(document, block))
        return chunks

    def _split_records(self, document: LCDocument, block: dict[str, Any]) -> list[LCDocument]:
        records = list(block.get("records") or [])
        if not records:
            return self._split_block(document, block)

        groups: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        for record in records:
            if not record.get("record_id"):
                raise ValueError("Spreadsheet record is missing record_id")
            if (
                block.get("block_type") == "timeseries"
                and current
                and self._period_bucket(block, current[-1]) != self._period_bucket(block, record)
            ):
                groups.append(current)
                current = []
            proposed = [*current, record]
            proposed_text = self._embedding_text(document, block, proposed)
            exceeds = (
                len(proposed) > self.config.spreadsheet_max_records_per_chunk
                or len(proposed_text) > self.config.spreadsheet_max_embedding_chars
                or self._token_count(proposed_text) > self.config.spreadsheet_max_embedding_tokens
            )
            if current and exceeds:
                groups.append(current)
                current = [record]
            else:
                current = proposed
        if current:
            groups.append(current)
        chunks: list[LCDocument] = []
        for group in groups:
            text = self._embedding_text(document, block, group)
            if len(group) == 1 and self._exceeds_embedding_limit(text):
                chunks.extend(self._split_oversized_record(document, block, group[0]))
            else:
                chunks.append(self._record_chunk(document, block, group))
        return chunks

    def _split_oversized_record(
        self,
        document: LCDocument,
        block: dict[str, Any],
        record: dict[str, Any],
    ) -> list[LCDocument]:
        """단일 oversized record를 header/value 필드 경계로 나눈다."""
        context_lines: list[str] = []
        if self.config.spreadsheet_include_sheet_context and document.metadata.get("sheet_name"):
            context_lines.append(f"시트: {document.metadata['sheet_name']}")
        if block.get("title"):
            context_lines.append(f"표: {block['title']}")

        fields = self._record_embedding_fields(block, record)
        if self._include_formulas(block):
            fields.extend(
                ("수식", f"{entry.get('coordinate')}={str(entry.get('formula')).lstrip('=')}")
                for entry in record.get("formulas") or []
                if entry.get("formula")
            )

        parts: list[tuple[list[str], int, int]] = []
        current: list[str] = []
        part_start = 0
        part_end = 0
        for field_index, (label, value) in enumerate(fields):
            fragments = self._split_field_to_fit(context_lines, label, value)
            for fragment in fragments:
                candidate = "\n".join([*context_lines, *current, fragment])
                if current and self._exceeds_embedding_limit(candidate):
                    parts.append((current, part_start, part_end))
                    current = []
                    part_start = field_index
                current.append(fragment)
                part_end = field_index
        if current:
            parts.append((current, part_start, part_end))

        if not parts:
            # 값이 없는 비정상 record도 기존 내용을 유실하지 않는다.
            parts = [([self._embedding_text(document, block, [record])], 0, 0)]

        chunks: list[LCDocument] = []
        part_count = len(parts)
        for part_index, (part_fields, field_start, field_end) in enumerate(parts, start=1):
            chunk = self._record_chunk(document, block, [record])
            chunk.page_content = "\n".join([*context_lines, *part_fields])
            warnings = list(chunk.metadata.get("warning_codes") or [])
            if "oversized_record" not in warnings:
                warnings.append("oversized_record")
            chunk.metadata.update({
                "chunk_key": f"{chunk.metadata['chunk_key']}:part-{part_index}",
                "display_markdown": chunk.page_content,
                "warning_codes": warnings,
                "oversized_split": True,
                "split_part": part_index,
                "split_part_count": part_count,
                "field_start": field_start,
                "field_end": field_end,
            })
            chunks.append(chunk)
        return chunks

    def _split_field_to_fit(
        self,
        context_lines: list[str],
        label: str,
        value: str,
    ) -> list[str]:
        """필드 하나가 한도를 넘는 경우에도 label을 반복하며 안전하게 분할한다."""
        rendered = f"{label}: {value}"
        if not self._exceeds_embedding_limit("\n".join([*context_lines, rendered])):
            return [rendered]

        fragments: list[str] = []
        remaining = value
        while remaining:
            low, high, fitted = 1, len(remaining), 0
            while low <= high:
                middle = (low + high) // 2
                candidate = f"{label}: {remaining[:middle]}"
                if self._exceeds_embedding_limit("\n".join([*context_lines, candidate])):
                    high = middle - 1
                else:
                    fitted = middle
                    low = middle + 1
            if fitted == 0:
                # 설정 한도보다 공통 문맥 자체가 큰 경우 무한 루프를 피한다.
                fitted = 1
            fragments.append(f"{label}: {remaining[:fitted]}")
            remaining = remaining[fitted:]
        return fragments

    def _exceeds_embedding_limit(self, text: str) -> bool:
        return (
            len(text) > self.config.spreadsheet_max_embedding_chars
            or self._token_count(text) > self.config.spreadsheet_max_embedding_tokens
        )

    def _record_embedding_fields(
        self,
        block: dict[str, Any],
        record: dict[str, Any],
    ) -> list[tuple[str, str]]:
        """embedding field를 생성하고 병합 상속 중복을 원본 셀 기준으로 collapse한다."""
        headers = list(block.get("headers") or [])
        values = list(record.get("values") or [])
        cells = list(record.get("cells") or [])

        if not cells or len(cells) != len(values):
            fields = [
                (str(header), str(value))
                for header, value in zip(headers, values)
                if header not in (None, "") and value not in (None, "")
            ] if headers else [
                ("값", str(value)) for value in values if value not in (None, "")
            ]
        else:
            entries: list[tuple[str, str] | dict[str, Any]] = []
            merge_groups: dict[tuple[str, str], dict[str, Any]] = {}
            for index, (cell, value) in enumerate(zip(cells, values)):
                if value in (None, ""):
                    continue
                header = headers[index] if index < len(headers) else "값"
                header = str(header) if header not in (None, "") else "값"
                inherited_from = cell.get("inherited_from")
                is_merge_anchor = bool(cell.get("is_merge_anchor") and cell.get("merged_range"))
                source = inherited_from or (cell.get("coordinate") if is_merge_anchor else None)
                if not source:
                    entries.append((header, str(value)))
                    continue

                group_key = (str(source), str(value))
                group = merge_groups.get(group_key)
                if group is None:
                    group = {"headers": [], "value": str(value)}
                    merge_groups[group_key] = group
                    entries.append(group)
                if header not in group["headers"]:
                    group["headers"].append(header)

            fields = []
            for entry in entries:
                if isinstance(entry, tuple):
                    fields.append(entry)
                    continue
                grouped_headers = entry["headers"]
                if len(grouped_headers) == 1:
                    fields.append((grouped_headers[0], entry["value"]))
                else:
                    fields.append((
                        "적용 헤더: " + " | ".join(grouped_headers) + "\n값",
                        entry["value"],
                    ))

        return fields

    def _split_block(self, document: LCDocument, block: dict[str, Any]) -> list[LCDocument]:
        records = list(block.get("records") or [])
        text = self._embedding_text(document, block, records)
        if not text.strip():
            return []
        metadata = self._base_metadata(document, block)
        source_range = block.get("source_range") or "unknown"
        metadata.update(self._formula_metadata(block, records))
        metadata.update({
            "chunk_type": "block",
            "content_type": "spreadsheet_block",
            "chunk_key": f"{metadata['block_id']}:block:{source_range}",
            "source_range": source_range,
            "record_ids": [record.get("record_id") for record in records if record.get("record_id")],
            "record_count": len(records),
            "display_markdown": self._display_markdown(block, records),
        })
        return [LCDocument(page_content=text, metadata=metadata)]

    def _record_chunk(
        self,
        document: LCDocument,
        block: dict[str, Any],
        records: list[dict[str, Any]],
    ) -> LCDocument:
        metadata = self._base_metadata(document, block)
        row_start = self._row(records[0], "row_start")
        row_end = self._row(records[-1], "row_end")
        source_range = self._covering_range(records, block.get("source_range"))
        record_ids = [record.get("record_id") for record in records if record.get("record_id")]
        warnings = list(metadata.get("warning_codes") or [])
        text = self._embedding_text(document, block, records)
        if (
            len(records) == 1
            and (
                len(text) > self.config.spreadsheet_max_embedding_chars
                or self._token_count(text) > self.config.spreadsheet_max_embedding_tokens
            )
        ):
            warnings.append("oversized_record")
        metadata.update(self._formula_metadata(block, records))
        metadata.update({
            "chunk_type": "record_group",
            "content_type": "spreadsheet_record_group",
            "chunk_key": f"{metadata['block_id']}:record_group:{row_start}-{row_end}",
            "source_range": source_range,
            "row_start": row_start,
            "row_end": row_end,
            "record_ids": record_ids,
            "record_count": len(records),
            "resource_ids": self._resource_ids(block, records),
            "display_markdown": self._display_markdown(block, records),
            "warning_codes": warnings,
        })
        if block.get("block_type") == "matrix":
            metadata.update(self._matrix_metadata(records))
        if block.get("block_type") == "timeseries":
            metadata.update(self._timeseries_metadata(block, records))
        return LCDocument(page_content=text, metadata=metadata)

    def _summary_chunk(self, document: LCDocument, block: dict[str, Any]) -> LCDocument:
        metadata = self._base_metadata(document, block)
        records = list(block.get("records") or [])
        resources = self._resource_ids(block, records)
        source_range = block.get("source_range") or "unknown"
        headers = block.get("headers") or []
        lines = [
            f"시트: {metadata.get('sheet_name') or ''}",
            f"표: {block.get('title') or source_range}",
            f"블록 유형: {block.get('block_type') or 'unknown_table'}",
            f"헤더: {', '.join(str(value) for value in headers)}",
            f"레코드 수: {len(records)}",
            f"리소스 수: {len(resources)}",
        ]
        metadata.update({
            "chunk_type": "table_summary",
            "content_type": "spreadsheet_table_summary",
            "chunk_key": f"{metadata['block_id']}:table_summary:{source_range}",
            "source_range": source_range,
            "record_ids": [],
            "record_count": 0,
            "resource_ids": resources,
            "display_markdown": "\n".join(lines),
        })
        text = "\n".join(lines)
        return LCDocument(page_content=text, metadata=metadata)

    def _base_metadata(self, document: LCDocument, block: dict[str, Any]) -> dict[str, Any]:
        metadata = dict(document.metadata)
        # 2026.08.27(sooyeon.choi) 추가 - 단계 7 병합 헤더 문맥과 수식 정책 신호 전달
        warning_codes = list(block.get("warning_codes") or block.get("warnings") or [])
        if block.get("cross_block_merge") and "cross_block_merge" not in warning_codes:
            warning_codes.append("cross_block_merge")
        metadata.update({
            "sheet_id": document.metadata.get("sheet_id") or f"sheet-{document.metadata.get('sheet_index')}",
            "block_id": block.get("block_id"),
            "block_index": block.get("block_index"),
            "block_type": block.get("block_type"),
            "header_range": block.get("header_range"),
            "headers": list(block.get("headers") or []),
            "header_paths": [list(path) for path in (block.get("header_paths") or [])],
            "resource_ids": list(block.get("resource_ids") or block.get("asset_ids") or []),
            "warning_codes": warning_codes,
            "formula_dominant": bool(block.get("formula_dominant")),
            "formula_ratio": block.get("formula_ratio") or 0.0,
            # workbook 문서 metadata는 loader가 workbook_metadata로 감싸 전달한다.
            "formula_recalculated": bool(
                document.metadata.get(
                    "formula_recalculated",
                    (document.metadata.get("workbook_metadata") or {}).get("formula_recalculated", False),
                )
            ),
            "spreadsheet_schema_version": document.metadata.get("schema_version") or "1.0",
            "embedding_text_version": "header-value-v1",
            "display_format_version": "markdown-table-v1",
        })
        return metadata

    # 2026.08.27(sooyeon.choi) 추가 - 단계 7 payload 상세 수식 manifest
    def _formula_metadata(
        self, block: dict[str, Any], records: list[dict[str, Any]]
    ) -> dict[str, Any]:
        manifest: list[dict[str, Any]] = []
        statuses: set[str] = set()
        total = 0
        for record in records:
            for entry in record.get("formulas") or []:
                total += 1
                statuses.add(entry.get("cache_status") or "not_applicable")
                if len(manifest) < self.config.spreadsheet_max_formula_manifest:
                    manifest.append({
                        "record_id": record.get("record_id"),
                        "coordinate": entry.get("coordinate"),
                        "formula": entry.get("formula"),
                        "cached_value": entry.get("cached_value"),
                        "cache_status": entry.get("cache_status"),
                    })
        for status in ("missing", "stale", "available"):
            if status in statuses:
                summary = status
                break
        else:
            summary = "not_applicable"
        return {
            "formula_count": total,
            "formula_manifest": manifest,
            "formula_manifest_truncated": total > len(manifest),
            "formula_cache_status": summary,
        }

    # 2026.08.27(sooyeon.choi) 추가 - 단계 7 수식 병기 여부 판정
    def _include_formulas(self, block: dict[str, Any]) -> bool:
        policy = self.config.spreadsheet_formula_embedding
        if policy == "always":
            return True
        if policy == "auto":
            return bool(block.get("formula_dominant"))
        return False

    def _embedding_text(
        self,
        document: LCDocument,
        block: dict[str, Any],
        records: Iterable[dict[str, Any]],
    ) -> str:
        lines: list[str] = []
        if self.config.spreadsheet_include_sheet_context and document.metadata.get("sheet_name"):
            lines.append(f"시트: {document.metadata['sheet_name']}")
        if block.get("title"):
            lines.append(f"표: {block['title']}")
        headers = list(block.get("headers") or [])
        if self.config.spreadsheet_repeat_headers and headers:
            lines.append("헤더: " + " | ".join(str(value) for value in headers))
        # 2026.08.27(sooyeon.choi) 추가 - 단계 7 수식 중심 표는 표시값 뒤에 수식을 병기
        include_formulas = self._include_formulas(block)
        for record in records:
            fields = [
                f"{label}: {value}"
                for label, value in self._record_embedding_fields(block, record)
            ]
            if fields:
                lines.append(" | ".join(fields))
            if include_formulas:
                formulas = [
                    f"{entry.get('coordinate')}={str(entry.get('formula')).lstrip('=')}"
                    for entry in record.get("formulas") or []
                    if entry.get("formula")
                ]
                if formulas:
                    lines.append("수식: " + " | ".join(formulas))
        return "\n".join(lines)

    # 2026.08.27(sooyeon.choi) 추가 - 단계 8 display Markdown에만 resource marker를 남긴다.
    def _resource_markers(self, block: dict[str, Any], records: list[dict[str, Any]]) -> str:
        resource_ids = self._resource_ids(block, records)
        if not resource_ids:
            return ""
        return " ".join(
            _RESOURCE_MARKER_FORMAT.format(resource_id=resource_id) for resource_id in resource_ids
        )

    def _display_markdown(self, block: dict[str, Any], records: list[dict[str, Any]]) -> str:
        markers = self._resource_markers(block, records)
        headers = list(block.get("headers") or [])
        if not headers:
            lines = [
                " | ".join(str(value) for value in record.get("values") or [] if value not in (None, ""))
                for record in records
            ]
            if markers:
                lines.append(markers)
            return "\n".join(lines)
        lines = [
            "| " + " | ".join(self._escape(value) for value in headers) + " |",
            "| " + " | ".join("---" for _ in headers) + " |",
        ]
        for record in records:
            values = list(record.get("values") or [])
            values.extend([""] * (len(headers) - len(values)))
            lines.append("| " + " | ".join(self._escape(value) for value in values[:len(headers)]) + " |")
        if markers:
            lines.append(markers)
        return "\n".join(lines)

    @staticmethod
    def _row(record: dict[str, Any], field: str) -> int:
        value = record.get(field)
        if isinstance(value, int):
            return value
        match = _CELL_RANGE_RE.match(str(record.get("source_range") or ""))
        if match:
            return int(match.group(2 if field == "row_start" else 4))
        raise ValueError(f"Spreadsheet record is missing {field}: {record.get('record_id')}")

    @staticmethod
    def _covering_range(records: list[dict[str, Any]], fallback: Any) -> str:
        first = _CELL_RANGE_RE.match(str(records[0].get("source_range") or ""))
        last = _CELL_RANGE_RE.match(str(records[-1].get("source_range") or ""))
        if first and last:
            return f"{first.group(1)}{first.group(2)}:{last.group(3)}{last.group(4)}"
        return str(fallback or "unknown")

    @staticmethod
    def _resource_ids(block: dict[str, Any], records: Iterable[dict[str, Any]]) -> list[str]:
        ids = list(block.get("resource_ids") or block.get("asset_ids") or [])
        for record in records:
            ids.extend(record.get("resource_ids") or record.get("asset_ids") or [])
        return list(dict.fromkeys(ids))

    @staticmethod
    def _matrix_metadata(records: list[dict[str, Any]]) -> dict[str, Any]:
        ranges = [_CELL_RANGE_RE.match(str(record.get("source_range") or "")) for record in records]
        ranges = [match for match in ranges if match]
        if not ranges:
            return {}
        return {
            "tile_row_start": int(ranges[0].group(2)),
            "tile_row_end": int(ranges[-1].group(4)),
            "tile_column_start": ranges[0].group(1),
            "tile_column_end": ranges[-1].group(3),
        }

    @staticmethod
    def _timeseries_metadata(block: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
        periods = [record.get("period") for record in records if record.get("period") is not None]
        return {
            "period_start": periods[0] if periods else block.get("period_start"),
            "period_end": periods[-1] if periods else block.get("period_end"),
            "period_unit": block.get("period_unit"),
            "metric_names": list(block.get("metric_names") or []),
        }

    @staticmethod
    def _period_bucket(block: dict[str, Any], record: dict[str, Any]) -> str | None:
        period = record.get("period")
        if period is None:
            return None
        value = str(period)
        unit = block.get("period_unit")
        if unit == "year":
            return value[:4]
        if unit == "quarter":
            quarter_match = re.search(r"(\d{4}).*?Q([1-4])", value, re.IGNORECASE)
            if quarter_match:
                return f"{quarter_match.group(1)}-Q{quarter_match.group(2)}"
            month_match = re.match(r"(\d{4})-(\d{1,2})", value)
            if month_match:
                quarter = (int(month_match.group(2)) - 1) // 3 + 1
                return f"{month_match.group(1)}-Q{quarter}"
        if unit == "month":
            month_match = re.match(r"(\d{4})-(\d{1,2})", value)
            if month_match:
                return f"{month_match.group(1)}-{int(month_match.group(2)):02d}"
        return None

    @staticmethod
    def _token_count(text: str) -> int:
        return len(_TOKEN_RE.findall(text))

    @staticmethod
    def _escape(value: Any) -> str:
        return str(value if value is not None else "").replace("|", "\\|").replace("\n", "<br>")


def split_spreadsheet_documents(
    documents: list[LCDocument], config: ChunkingConfig
) -> list[LCDocument]:
    return SpreadsheetChunker(config).split_documents(documents)

"""StructuredSpreadsheet IR to backend LCDocument conversion."""

# 2026.08.27(sooyeon.choi) 추가 - IR 전용 converter
from __future__ import annotations

from typing import Any

from ..models import LCDocument, MdMeta


def spreadsheet_to_documents(md_meta: MdMeta, source_path: str = "") -> list[LCDocument]:
    """시트별 IR envelope을 Markdown 재파싱 없이 LCDocument로 변환한다."""
    documents: list[LCDocument] = []
    for sheet_item in md_meta:
        metadata = dict(sheet_item.get("metadata", {}))
        blocks = metadata.get("blocks", [])
        embedding_text = _build_embedding_text(
            metadata.get("sheet_name"),
            blocks,
            sheet_item.get("text", ""),
        )
        metadata.update({
            "source": source_path or metadata.get("file_path", ""),
            "document_type": "spreadsheet",
            "content_type": "spreadsheet_sheet",
            "display_markdown": metadata.get("display_markdown", ""),
            "structured_ir": {
                "schema_name": metadata.get("schema_name"),
                "schema_version": metadata.get("schema_version"),
                "blocks": blocks,
                "styles": metadata.get("styles", {}),
                "resources": metadata.get("resources", []),
                "warnings": metadata.get("workbook_warnings", []),
            },
        })
        documents.append(LCDocument(page_content=embedding_text, metadata=metadata))
    return documents


def _build_embedding_text(
    sheet_name: str | None,
    blocks: list[dict[str, Any]],
    fallback: str,
) -> str:
    lines = [f"시트: {sheet_name}"] if sheet_name else []
    for block in blocks:
        headers = block.get("headers", [])
        records = block.get("records", [])
        if headers and records:
            for record in records:
                values = record.get("values", [])
                if values == headers:
                    continue
                pairs = [
                    f"{header}: {value}"
                    for header, value in zip(headers, values)
                    if header and value not in (None, "")
                ]
                if pairs:
                    lines.append(" | ".join(pairs))
        else:
            for record in records:
                values = [str(value) for value in record.get("values", []) if value not in (None, "")]
                if values:
                    lines.append(" ".join(values))
    return "\n".join(lines) if len(lines) > bool(sheet_name) else fallback

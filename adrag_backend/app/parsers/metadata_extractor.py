"""
청크 메타데이터 공통 추출기 (v2).

JSON Schema 기반 공통 스키마에 맞춰
파서가 생성한 메타데이터에서 공통 필드를 추출/파생한다.
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from .metadata_schema import (
    ChunkMeta,
    DocumentMeta,
    SemanticMeta,
    UnifiedChunkPayload,
)


# ── 콘텐츠 유형 탐지 패턴 ──────────────────────────────────────────────────

_TABLE_PATTERN = re.compile(r"\|.+\|")
_IMAGE_PATTERN = re.compile(r"<!--\s*image\s*-->", re.IGNORECASE)

# 2026.08.27(sooyeon.choi) 추가 - Qdrant에 저장할 compact spreadsheet metadata 정본
_SPREADSHEET_PAYLOAD_FIELDS = (
    "display_markdown",
    "sheet_id",
    "sheet_index",
    "sheet_name",
    "block_id",
    "block_index",
    "block_type",
    "chunk_type",
    "source_range",
    "row_start",
    "row_end",
    "header_range",
    "headers",
    "record_ids",
    "record_count",
    "resource_ids",
    "chunk_key",
    "warning_codes",
    "spreadsheet_schema_version",
    "embedding_text_version",
    "display_format_version",
    # 2026.08.27(sooyeon.choi) 추가 - 병합 헤더 문맥과 수식 manifest
    "header_paths",
    "formula_count",
    "formula_manifest",
    "formula_manifest_truncated",
    "formula_cache_status",
    "formula_dominant",
    "formula_recalculated",
    # 2026.10.16 추가 - Phase 1 excel_ingest 청크 메타(docling 경로에서는 None)
    "processing_engine",
    "section_type",
    "step_no",
    "revision",
)


def detect_content_type(text: str) -> str:
    """텍스트의 콘텐츠 유형을 판별한다. (text | table | image)"""
    if _IMAGE_PATTERN.search(text):
        return "image"
    if _TABLE_PATTERN.search(text):
        return "table"
    return "text"


def normalize_header_path(raw: Any) -> List[str]:
    """다양한 형태의 header_path를 List[str]로 정규화한다."""
    if isinstance(raw, list):
        return [str(p).strip() for p in raw if p]
    if isinstance(raw, str) and raw:
        return [p.strip() for p in raw.split(">") if p.strip()]
    return []


def extract_doc_title(text: str, doc_type: str) -> str:
    """첫 페이지 텍스트에서 문서 제목을 추출한다."""
    lines = text.strip().splitlines()
    if not lines:
        return ""

    if doc_type == "law":
        first = lines[0].strip().lstrip("# ").strip()
        if first and len(first) < 100:
            return first

    if doc_type == "manual":
        first = lines[0].strip()
        if re.match(r"^\d+\.\s+", first):
            return first

    for line in lines[:10]:
        if line.startswith("# "):
            return line.lstrip("# ").strip()

    return lines[0].strip()[:80]


def detect_file_format(file_path: str) -> str:
    """파일 경로에서 확장자를 추출한다."""
    return Path(file_path).suffix.lstrip(".").lower() or "unknown"


def build_unified_payload(
    document_id: str,
    chunk_id: str,
    chunk_index: int,
    chunk_text: str,
    chunk_meta: Dict[str, Any],
    *,
    source_path: str = "",
    original_filename: Optional[str] = None,
    source_collection: str = "",
    document_type: str = "general",
    title: str = "",
    file_format: str = "pdf",
    created_at: Optional[str] = None,
    updated_at: Optional[str] = None,
    version: Optional[str] = None,
    security_level: str = "public",
    requested_document_type: str = "auto",
    document_type_source: Optional[str] = None,
) -> Dict[str, Any]:
    """청크 하나에 대한 통합 Qdrant payload를 생성한다."""

    header_path = normalize_header_path(chunk_meta.get("header_path"))

    doc = DocumentMeta(
        document_id=document_id,
        source_path=source_path,
        original_filename=original_filename,
        source_collection=source_collection,
        document_type=document_type,
        requested_document_type=requested_document_type,
        document_type_source=document_type_source,
        title=title,
        security_level=security_level,
        file_format=file_format,
        created_at=created_at,
        updated_at=updated_at,
        version=version,
    )

    chunk = ChunkMeta(
        chunk_id=chunk_id,
        chunk_index=chunk_index,
        header_path=header_path,
        # 2026.08.27(sooyeon.choi) 수정 - chunker가 확정한 유형을 정규식 추론보다 우선
        content_type=chunk_meta.get("content_type") or detect_content_type(chunk_text),
        page_number=chunk_meta.get("page_start") or chunk_meta.get("page"),
        section_title=chunk_meta.get("section_title"),
        char_start_offset=chunk_meta.get("char_start_offset"),
        char_end_offset=chunk_meta.get("char_end_offset"),
    )

    semantic = SemanticMeta()

    payload = UnifiedChunkPayload(
        document=doc,
        chunk=chunk,
        semantic=semantic,
    )

    result = payload.to_qdrant_payload()
    result["text"] = chunk_text
    if document_type == "spreadsheet":
        # 전체 structured_ir/cells/workbook manifest는 point마다 복제하지 않는다.
        for field_name in _SPREADSHEET_PAYLOAD_FIELDS:
            result[field_name] = chunk_meta.get(field_name)
    return result

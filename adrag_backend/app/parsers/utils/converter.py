"""
마크다운 → LCDocument 변환
레퍼런스: reference_code/Chatbot_Backend_v1/app/services/pdf_chunking/document/converter.py
"""

from typing import List, Dict, Any, Optional

from ..models import LCDocument
from .text_cleaner import rm_unnecessary_char, format_table_with_line_breaks, remove_table_header_rule, strip_bold_law_markers
from .header_promoter import promote_headers, PROMOTED_PATTERNS

_CHAPTER_PATTERN = PROMOTED_PATTERNS["chapter"]
_SECTION_PATTERN = PROMOTED_PATTERNS["section"]
_ARTICLE_PATTERN = PROMOTED_PATTERNS["article"]


def _parse_header_matches(lines: List[str]):
    chapter = section = article = None
    for line in lines:
        if m := _CHAPTER_PATTERN.match(line):
            chapter = f"제{m.group(1)}장"
            section = article = None
        if m := _SECTION_PATTERN.match(line):
            section = f"제{m.group(1)}절"
            article = None
        if m := _ARTICLE_PATTERN.match(line):
            article = f"제{m.group(1)}조"
    return chapter, section, article


def _build_path_from_parts(chapter, section, article) -> Optional[str]:
    if article:
        if chapter and section:
            return f"{chapter} > {section} > {article}"
        if chapter:
            return f"{chapter} > {article}"
        if section:
            return f"{section} > {article}"
        return article
    if section:
        return f"{chapter} > {section}" if chapter else section
    return chapter


def extract_header_path_from_text(text: str, current_header_path: Optional[str] = None) -> Optional[str]:
    lines = text.splitlines()
    path = _build_path_from_parts(*_parse_header_matches(lines))
    return path if path is not None else current_header_path


def markdown_to_langchain(
    markdown_meta: List[Dict[str, Any]],
    *,
    flatten_tables: bool = False,
    source_path: Optional[str] = None,
    extract_header_path: bool = True,
) -> List[LCDocument]:
    """
    페이지별 마크다운 메타데이터를 LCDocument 리스트로 변환.

    Args:
        markdown_meta: 로더가 반환한 List[{"text": str, "metadata": dict}]
        flatten_tables: 표 헤더 구분선 제거 여부
        source_path: 원본 파일 경로 (메타데이터용)
        extract_header_path: 법령 헤더 경로 추출 여부
    """
    page_texts: List[str] = []
    page_metadatas: List[dict] = []

    for item in markdown_meta:
        text_raw = item.get("text", "")
        page_texts.append(format_table_with_line_breaks(text_raw))
        page_metadatas.append(item.get("metadata", {}) or {})

    joined_text = "\n\n".join(page_texts)
    cleaned_text = rm_unnecessary_char(joined_text)
    # Docling이 DOCX를 **제1조(목적)** 볼드 형식으로 출력하는 경우 제거 후 promote_headers 적용
    unbolded_text = strip_bold_law_markers(cleaned_text)
    promoted_text = promote_headers(unbolded_text)

    promoted_lines = promoted_text.splitlines()

    # 페이지별 줄 수 계산
    page_line_counts: List[tuple] = []
    current_line_idx = 0
    for page_text in page_texts:
        cleaned_page = rm_unnecessary_char(page_text)
        count = len(cleaned_page.splitlines())
        page_line_counts.append((current_line_idx, current_line_idx + count))
        current_line_idx += count + 1  # +1: "\n\n" 구분자

    docs: List[LCDocument] = []
    current_header_path = None

    for i, ((start_idx, end_idx), md) in enumerate(zip(page_line_counts, page_metadatas)):
        page_start = min(start_idx, len(promoted_lines))
        page_end = min(end_idx, len(promoted_lines))

        if i == len(page_line_counts) - 1:
            page_end = len(promoted_lines)

        page_promoted_text = "\n".join(promoted_lines[page_start:page_end])

        if flatten_tables:
            page_promoted_text = remove_table_header_rule(page_promoted_text)

        header_path = None
        if extract_header_path:
            header_path = extract_header_path_from_text(page_promoted_text, current_header_path)
            if header_path:
                current_header_path = header_path

        meta = {
            "source": md.get("file_path") or source_path,
            "total_pages": md.get("page_count"),
            "page": md.get("page"),
            "page_label": md.get("page"),
            "header_path": header_path,
            # 원본 메타에 있는 추가 필드 보존 (파일 형식별 확장)
            "file_type": md.get("file_type"),
        }
        docs.append(LCDocument(page_content=page_promoted_text, metadata=meta))

    return docs
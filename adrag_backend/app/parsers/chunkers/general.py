"""
일반 문서 청킹 (RecursiveCharacterTextSplitter)
레퍼런스: reference_code/Chatbot_Backend_v1/app/services/pdf_chunking/document/chunker.py
"""

import re
from bisect import bisect_right
from typing import List, Tuple

from langchain_text_splitters import RecursiveCharacterTextSplitter

from ..models import LCDocument
from ..config import DEFAULT_CONFIG

from app.utils.log.log import LoggingLogger

# 로거 초기화
# 2026.07.16(sooyeon.choi) 수정 - 모듈별 named logger 적용 (B16)
logger = LoggingLogger().getLogger(__name__)

# ── 타입 별칭 ───────────────────────────────────────────────────────────────
SectionIndex = List[Tuple[int, str]]

# ── 헤더 인식 패턴 (모듈 수준 상수) ─────────────────────────────────────────
# 마크다운 헤더 패턴 (# ~ ###)
_MD_HEADER_RE = re.compile(r"^(#{1,3})\s+(.+)", re.MULTILINE)
# 번호 제목 패턴: 라인 전체를 직접 매칭 (Ⅰ., 1., 가., (1) 등 + 본문 최대 75자)
_NUMBERED_TITLE_LINE_RE = re.compile(
    r"^(?:[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+\."
    r"|\d{1,2}\.\s"
    r"|[가나다라마바사아자차카타파하]\.\s"
    r"|\(\d+\)\s)"
    r".{0,75}$",
    re.MULTILINE,
)
# 볼드 텍스트 제목 패턴 (**제목**)
_BOLD_TITLE_RE = re.compile(r"^\*\*(.+?)\*\*\s*$", re.MULTILINE)
# 밑줄 헤더 패턴 (제목\n=== 또는 제목\n---)
_UNDERLINE_HEADER_RE = re.compile(r"^(.+)\n([=\-]{3,})\s*$", re.MULTILINE)


def build_section_index(full_text: str) -> SectionIndex:
    """전체 텍스트에서 섹션 헤더 위치 인덱스를 구성한다.

    마크다운 헤더, 번호 제목, 볼드 제목, 밑줄 헤더 패턴을 스캔하여
    (char_offset, section_title) 쌍의 정렬된 리스트를 반환한다.
    동일 위치에 여러 패턴이 매칭되면 마크다운 헤더를 우선 채택한다.

    Returns:
        문자 오프셋 기준 오름차순 정렬된 (offset, title) 리스트.
        헤더가 없으면 빈 리스트.
    """
    if not full_text:
        return []

    # offset → title 매핑 (중복 위치 처리용)
    entries: dict[int, str] = {}

    # 1) 마크다운 헤더 (최우선)
    for m in _MD_HEADER_RE.finditer(full_text):
        entries[m.start()] = m.group(2).strip()

    # 2) 밑줄 헤더 (제목\n=== 또는 제목\n---)
    for m in _UNDERLINE_HEADER_RE.finditer(full_text):
        offset = m.start()
        if offset not in entries:
            entries[offset] = m.group(1).strip()

    # 3) 볼드 제목 (**제목**)
    for m in _BOLD_TITLE_RE.finditer(full_text):
        offset = m.start()
        if offset not in entries:
            title = m.group(1).strip()
            if len(title) <= 80:
                entries[offset] = title

    # 4) 번호 제목: 라인 전체 매칭 정규식으로 직접 탐색 (줄 순회 + 2차 검증 불필요)
    for m in _NUMBERED_TITLE_LINE_RE.finditer(full_text):
        offset = m.start()
        if offset not in entries:
            title = m.group().strip()
            if len(title) <= 80:
                entries[offset] = title

    return sorted(entries.items(), key=lambda x: x[0])


# ── 내부 헬퍼 ───────────────────────────────────────────────────────────────

def _find_chunk_position(full_text: str, chunk_text: str, search_start: int) -> int:
    """청크 텍스트의 전체 텍스트 내 시작 위치를 3단계 폴백으로 탐색한다.

    Returns:
        찾은 위치(0-based). 모든 폴백에서 실패하면 -1.
    """
    pos = full_text.find(chunk_text, search_start)
    if pos != -1:
        return pos
    pos = full_text.find(chunk_text[:min(100, len(chunk_text))], search_start)
    if pos != -1:
        return pos
    if len(chunk_text) > 50:
        return full_text.find(chunk_text[:50])
    return full_text.find(chunk_text)


def _resolve_page_info(
    chunk_start: int,
    chunk_end: int,
    chunk_pos: int,
    page_boundaries: list,
) -> tuple:
    """청크 위치에 해당하는 (start_page_info, end_page_info)를 반환한다.

    4단계 폴백:
        1) chunk_start가 속한 페이지
        2) chunk 중간 지점이 속한 페이지
        3) chunk_pos가 속한 페이지
        4) 첫 번째 페이지

    Returns:
        (start_page_info, end_page_info) — 둘 다 None일 수 없음 (page_boundaries 비어있지 않으면).
    """
    start_page_info = None
    end_page_info = None

    for page_info in page_boundaries:
        if page_info["start"] <= chunk_start < page_info["end"]:
            start_page_info = page_info
            break
    for page_info in page_boundaries:
        if page_info["start"] <= chunk_end <= page_info["end"]:
            end_page_info = page_info
            break

    if not start_page_info:
        chunk_mid = chunk_pos + (chunk_end - chunk_start) // 2 if chunk_pos != -1 else 0
        for page_info in page_boundaries:
            if page_info["start"] <= chunk_mid < page_info["end"]:
                start_page_info = page_info
                break

    if not start_page_info and chunk_pos != -1:
        for page_info in page_boundaries:
            if page_info["start"] <= chunk_pos < page_info["end"]:
                start_page_info = page_info
                break

    if not start_page_info and page_boundaries:
        start_page_info = page_boundaries[0]
    if not end_page_info:
        end_page_info = start_page_info

    return start_page_info, end_page_info


def split_general_markdown(
    docs: List[LCDocument],
    chunk_size: int = DEFAULT_CONFIG.general_chunk_size,
    chunk_overlap: int = DEFAULT_CONFIG.general_chunk_overlap,
    include_header_path: bool = DEFAULT_CONFIG.include_header_path_in_content,
    header_path_format: str = DEFAULT_CONFIG.header_path_format,
) -> List[LCDocument]:
    """
    일반 문서를 RecursiveCharacterTextSplitter로 청킹.
    페이지 경계를 넘어서는 문맥 보존을 위해 전체 텍스트를 합쳐서 처리.
    """
    if not docs:
        return []

    full_text_parts: List[str] = []
    page_boundaries = []
    current_pos = 0

    for doc in docs:
        page_content = doc.page_content
        page_num = (doc.metadata or {}).get("page")
        header_path = (doc.metadata or {}).get("header_path")

        if full_text_parts:
            full_text_parts.append("\n\n")
            current_pos += 2

        start_pos = current_pos
        full_text_parts.append(page_content)
        end_pos = current_pos + len(page_content)

        page_boundaries.append({
            "start": start_pos,
            "end": end_pos,
            "page": page_num,
            "metadata": doc.metadata.copy() if doc.metadata else {},
            "header_path": header_path,
        })
        current_pos = end_pos

    full_text = "".join(full_text_parts)

    # ── SectionIndex 구성 + offsets 캐싱 (루프 외부에서 한 번만) ──
    section_index = build_section_index(full_text)
    sec_offsets = [entry[0] for entry in section_index]

    rc = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    text_chunks = rc.split_text(full_text)

    out: List[LCDocument] = []
    search_start = 0

    for chunk_text in text_chunks:
        chunk_pos = _find_chunk_position(full_text, chunk_text, search_start)
        chunk_start = chunk_pos if chunk_pos != -1 else 0
        chunk_end = chunk_pos + len(chunk_text)

        start_page_info, end_page_info = _resolve_page_info(
            chunk_start, chunk_end, chunk_pos, page_boundaries
        )

        if start_page_info:
            metadata = start_page_info["metadata"].copy()
            page_start = start_page_info["page"]
            page_end = end_page_info["page"] if end_page_info else page_start
            metadata["page"] = page_start
            metadata["page_start"] = page_start
            metadata["page_end"] = page_end
            metadata["pages_display"] = (
                str(page_start) if page_start == page_end else f"{page_start}–{page_end}"
            )
            if start_page_info["header_path"]:
                metadata["header_path"] = start_page_info["header_path"]
        else:
            metadata = docs[0].metadata.copy() if docs else {}
            default_page = metadata.get("page", 1)
            metadata["page"] = default_page
            metadata["page_start"] = default_page
            metadata["page_end"] = default_page
            metadata["pages_display"] = str(default_page)

        # section_title: 캐싱된 sec_offsets로 bisect (리스트 재생성 없음)
        idx = bisect_right(sec_offsets, chunk_start)
        if idx > 0:
            metadata["section_title"] = section_index[idx - 1][1]

        if chunk_pos != -1:
            metadata["char_start_offset"] = chunk_start
            metadata["char_end_offset"] = chunk_end

        out.append(LCDocument(page_content=chunk_text, metadata=metadata))

        if chunk_pos != -1:
            search_start = chunk_pos + len(chunk_text) - chunk_overlap

    return out

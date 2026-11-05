"""
매뉴얼 문서 청킹 (메뉴 경로/화면 단위)

2026.06.04(sooyeon.choi) 전면 개편 - 메뉴 경로 기반 화면 단위 청킹으로 전환
  기존: "N. 제목" 번호 섹션 경계 분리 + [섹션: {title}] 라벨 prefix 주입
  변경:
    - "A > B > C" 형태의 메뉴 경로 줄을 섹션 경계로 인식
    - header_path = 메뉴 경로를 '>' 기준으로 파싱한 List[str]
    - 청크 본문 첫 줄 = "A > B > C" (라벨 없이 경로 문자열만 삽입)
    - chunk_size 초과 시 동일 header_path 유지한 채 하위 분할
  메뉴 경로가 없는 문서 (표지/목차 등) 폴백:
    - RecursiveCharacterTextSplitter로 단순 분할, header_path=[]
"""

import re
from typing import List, Optional, Tuple

from langchain_text_splitters import RecursiveCharacterTextSplitter

from ..models import LCDocument
from ..config import DEFAULT_CONFIG

from app.utils.log.log import LoggingLogger

# 2026.07.16(sooyeon.choi) 수정 - 모듈별 named logger 적용 (B16)
logger = LoggingLogger().getLogger(__name__)


# ── 2026.06.04(sooyeon.choi) 추가 - 메뉴 경로 기반 패턴 ────────────────────

# 메뉴 경로 줄 패턴: 줄 전체가 "A > B > C" 형태인 경우만 인식
# - 선택적 앞 번호(01.) 허용
# - '>' 구분자 1개 이상 필수 (줄 중간 문장 배제를 위해 줄 전체를 ^ ~ $ 로 앵커링)
# - &gt; HTML 엔티티도 허용 (Docling 변환 아티팩트 대응)
_MENU_PATH_LINE_PATTERN = re.compile(
    r"^(?:\d{1,2}\.\s+)?"
    r"[가-힣A-Za-z0-9][가-힣A-Za-z0-9 \t\(\)\[\]·,\.]*"
    r"(?:[ \t]*(?:>|&gt;)[ \t]*[가-힣A-Za-z0-9][가-힣A-Za-z0-9 \t\(\)\[\]·,\.]*){1,}$",
    re.MULTILINE,
)

# Docling 변환 아티팩트: "N. ①" → "①" 정규화
_DOCLING_LIST_NUMBERING_PATTERN = re.compile(r"(?m)^\d{1,2}\.\s+([①②③④⑤⑥⑦⑧⑨⑩])")


def _clean_docling_list_numbering(text: str) -> str:
    """Docling 변환 아티팩트 제거: 'N. ①' → '①'"""
    return _DOCLING_LIST_NUMBERING_PATTERN.sub(r"\1", text)


def _parse_menu_path(menu_line: str) -> List[str]:
    """메뉴 경로 줄을 List[str]로 파싱.

    '01. 공사 및 작업허가 > 위험성평가 > 위험성평가 등록'
      → ['공사 및 작업허가', '위험성평가', '위험성평가 등록']
    """
    # 선행 번호(01.) 제거
    clean = re.sub(r"^\d{1,2}\.\s+", "", menu_line.strip())
    # HTML 엔티티 처리
    clean = clean.replace("&gt;", ">")
    return [p.strip() for p in clean.split(">") if p.strip()]


def _make_screen_content(header_path: List[str], body: str) -> str:
    """청크 본문 구성: 경로 문자열(라벨 없음) + 빈 줄 + 본문.

    예:
      공사 및 작업허가 > 위험성평가 > 위험성평가 등록

      1. 위험성평가 상세정보를 등록한다.
      2. 저장 버튼을 클릭한다.
    """
    path_str = " > ".join(header_path)
    body_stripped = body.strip()
    if body_stripped:
        return f"{path_str}\n\n{body_stripped}"
    return path_str


def _split_into_menu_sections(full_text: str) -> List[Tuple[Optional[str], str]]:
    """전체 텍스트를 메뉴 경로 줄 경계로 분리.

    Returns:
        List of (menu_path_line | None, body_content)
        - menu_path_line=None 이면 메뉴 경로 이전 사전 텍스트 (표지/목차 등)
    """
    matches = list(_MENU_PATH_LINE_PATTERN.finditer(full_text))

    if not matches:
        return [(None, full_text)]

    sections: List[Tuple[Optional[str], str]] = []

    # 첫 번째 메뉴 경로 이전 텍스트 (표지, 머리말 등)
    pre_text = full_text[: matches[0].start()].strip()
    if pre_text:
        sections.append((None, pre_text))

    for i, match in enumerate(matches):
        menu_line = match.group(0).strip()
        body_start = match.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(full_text)
        body = full_text[body_start:body_end].strip()
        sections.append((menu_line, body))

    return sections


def _resolve_page_range(
    chunk_text: str,
    full_text: str,
    page_boundaries: List[dict],
) -> Tuple[Optional[int], Optional[int], Optional[int], dict]:
    """청크 텍스트의 페이지 범위(start, end)와 메타데이터를 반환.

    Returns:
        (page_start, page_end, char_pos, base_metadata)
    """
    if not page_boundaries:
        return None, None, -1, {}

    search_key = chunk_text[:50] if len(chunk_text) >= 50 else chunk_text
    chunk_pos = full_text.find(search_key) if search_key else -1

    if chunk_pos == -1:
        default = page_boundaries[0]
        return default["page"], default["page"], -1, default["metadata"].copy()

    chunk_end_pos = chunk_pos + len(chunk_text)
    page_start = page_end = None
    base_meta = page_boundaries[0]["metadata"].copy()

    for pb in page_boundaries:
        if pb["start"] <= chunk_pos < pb["end"]:
            page_start = pb["page"]
            base_meta = pb["metadata"].copy()
        if pb["start"] <= chunk_end_pos <= pb["end"]:
            page_end = pb["page"]

    if page_start is None:
        page_start = page_boundaries[0]["page"]
    if page_end is None:
        page_end = page_start

    return page_start, page_end, chunk_pos, base_meta


def split_manual_markdown(
    docs: List[LCDocument],
    chunk_size: int = DEFAULT_CONFIG.manual_chunk_size,
    chunk_overlap: int = DEFAULT_CONFIG.manual_chunk_overlap,
    section_prefix_format: str = DEFAULT_CONFIG.manual_section_prefix_format,
) -> List[LCDocument]:
    """매뉴얼 문서를 메뉴 경로(header_path) 기반 화면 단위로 청킹.

    흐름:
      1. 전체 텍스트에서 'A > B > C' 형태의 메뉴 경로 줄을 경계로 섹션 분리
      2. 각 섹션의 header_path = 메뉴 경로를 '>' 기준 List[str]로 파싱
      3. 청크 본문 첫 줄 = "A > B > C" (라벨 없이 경로 문자열만 삽입)
      4. body가 chunk_size 초과 시 동일 header_path 유지한 채 RecursiveCharacterTextSplitter로 분할
      5. 메뉴 경로가 없는 문서는 RecursiveCharacterTextSplitter 단순 분할 (폴백)

    Args:
        section_prefix_format: 하위 호환용 파라미터 (이 함수에서는 미사용)
    """
    if not docs:
        return []

    # ── 전체 텍스트 합산 (페이지 경계 보존) ──────────────────────────────────
    full_text_parts: List[str] = []
    page_boundaries: List[dict] = []
    current_pos = 0

    for doc in docs:
        page_content = doc.page_content
        page_num = (doc.metadata or {}).get("page")

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
        })
        current_pos = end_pos

    full_text = "".join(full_text_parts)
    full_text = _clean_docling_list_numbering(full_text).replace("&gt;", ">")

    # ── 섹션 분리 ────────────────────────────────────────────────────────────
    sections = _split_into_menu_sections(full_text)
    has_menu_paths = any(menu_line is not None for menu_line, _ in sections)

    # logger.info(
    #     f"매뉴얼 청킹 시작 - 총 {len(docs)}페이지 | "
    #     f"섹션 {len(sections)}개 | 메뉴경로 {'있음' if has_menu_paths else '없음(폴백)'}"
    # )

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", " ", ""],
    )

    # ── 메뉴 경로 없는 문서 폴백 ─────────────────────────────────────────────
    if not has_menu_paths:
        return _fallback_split(full_text, page_boundaries, splitter, docs)

    # ── 메뉴 경로 기반 청킹 ──────────────────────────────────────────────────
    out: List[LCDocument] = []

    for menu_line, body in sections:
        if menu_line is None:
            # 메뉴 경로 이전 사전 텍스트 (표지/목차): header_path 없이 단순 추가
            if not body.strip():
                continue
            sub_chunks = splitter.split_text(body) if len(body) > chunk_size else [body]
            for sub in sub_chunks:
                if not sub.strip():
                    continue
                page_start, page_end, chunk_pos, base_meta = _resolve_page_range(
                    sub, full_text, page_boundaries
                )
                meta = base_meta
                meta["page"] = page_start
                meta["page_start"] = page_start
                meta["page_end"] = page_end
                meta["pages_display"] = (
                    str(page_start) if page_start == page_end else f"{page_start}–{page_end}"
                )
                meta["header_path"] = []
                meta["section_title"] = None
                if chunk_pos != -1:
                    meta["char_start_offset"] = chunk_pos
                    meta["char_end_offset"] = chunk_pos + len(sub)
                out.append(LCDocument(page_content=sub.strip(), metadata=meta))
            continue

        header_path = _parse_menu_path(menu_line)

        # body가 없으면 경로 문자열만으로 청크 생성
        if not body.strip():
            content = " > ".join(header_path)
            page_start, page_end, chunk_pos, base_meta = _resolve_page_range(
                menu_line, full_text, page_boundaries
            )
            meta = base_meta
            meta["page"] = page_start
            meta["page_start"] = page_start
            meta["page_end"] = page_end
            meta["pages_display"] = str(page_start) if page_start == page_end else f"{page_start}–{page_end}"
            meta["header_path"] = header_path
            meta["section_title"] = header_path[-1] if header_path else None
            out.append(LCDocument(page_content=content, metadata=meta))
            continue

        # body 분할 결정
        sub_chunks = splitter.split_text(body) if len(body) > chunk_size else [body]

        for sub in sub_chunks:
            if not sub.strip():
                continue

            content = _make_screen_content(header_path, sub)
            page_start, page_end, chunk_pos, base_meta = _resolve_page_range(
                sub, full_text, page_boundaries
            )
            meta = base_meta
            meta["page"] = page_start
            meta["page_start"] = page_start
            meta["page_end"] = page_end
            meta["pages_display"] = (
                str(page_start) if page_start == page_end else f"{page_start}–{page_end}"
            )
            meta["header_path"] = header_path
            meta["section_title"] = header_path[-1] if header_path else None
            if chunk_pos != -1:
                meta["char_start_offset"] = chunk_pos
                meta["char_end_offset"] = chunk_pos + len(sub)
            out.append(LCDocument(page_content=content, metadata=meta))

    # logger.info(f"매뉴얼 청킹 완료 - 총 {len(out)}개 청크")
    return out


def _fallback_split(
    full_text: str,
    page_boundaries: List[dict],
    splitter: RecursiveCharacterTextSplitter,
    docs: List[LCDocument],
) -> List[LCDocument]:
    """메뉴 경로가 없는 매뉴얼 문서 폴백: RecursiveCharacterTextSplitter 단순 분할."""
    # logger.info("매뉴얼 폴백 청킹 - 메뉴 경로 없음, RecursiveCharacterTextSplitter 사용")
    out: List[LCDocument] = []
    text_chunks = splitter.split_text(full_text)

    for chunk_text in text_chunks:
        if not chunk_text.strip():
            continue
        page_start, page_end, chunk_pos, base_meta = _resolve_page_range(
            chunk_text, full_text, page_boundaries
        )
        meta = base_meta
        meta["page"] = page_start
        meta["page_start"] = page_start
        meta["page_end"] = page_end
        meta["pages_display"] = (
            str(page_start) if page_start == page_end else f"{page_start}–{page_end}"
        )
        meta["header_path"] = []
        meta["section_title"] = None
        if chunk_pos != -1:
            meta["char_start_offset"] = chunk_pos
            meta["char_end_offset"] = chunk_pos + len(chunk_text)
        out.append(LCDocument(page_content=chunk_text.strip(), metadata=meta))

    return out
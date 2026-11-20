"""
법령 문서 청킹 (조문/별표/별지 단위)
레퍼런스: reference_code/Chatbot_Backend_v1/app/services/pdf_chunking/law/chunker.py
"""

import re
from typing import List, Dict, Any, Optional

from langchain_text_splitters import RecursiveCharacterTextSplitter

from ..models import LCDocument
from ..config import DEFAULT_CONFIG

from app.utils.log.log import LoggingLogger

# 로거 초기화
# 2026.07.16(sooyeon.choi) 수정 - 모듈별 named logger 적용
logger = LoggingLogger().getLogger(__name__)

# ── 공통 패턴 ───────────────────────────────────────────────────────────────
_ARTICLE_PATTERN = re.compile(r'^###\s+제\s*(\d+)\s*조(?:의\s*\d+)?')
_CHAPTER_PATTERN = re.compile(r'^#\s+제\s*(\d+)\s*장')
_SECTION_PATTERN = re.compile(r'^##\s+제\s*(\d+)\s*절')
_ANNEX_HEADING_PATTERN = re.compile(r'^\s*#{1,6}\s*부칙(?:\s*\d+)?\s*$')
_ANNEX_PLAIN_PATTERN = re.compile(r'^\s*부칙(?:\s*\d+)?\s*$')
_ANNEX_PATTERN = re.compile(r'^##\s*[\-■※]\s*.*?\[\s*별표\s*(\d+)\s*\].*')
_ANNEX_FORM_PATTERN = re.compile(r'^##\s*[\-■※]\s*.*?\[\s*별지\s*제?\s*(\d+)\s*호서식\s*\].*')
_ANNEX_HEADER_PATTERN = re.compile(r'^##\s*[\-■※]\s*.*?\[\s*별표\s*\d+\s*\].*', re.M)
_ANNEX_FORM_HEADER_PATTERN = re.compile(r'^##\s*[\-■※]\s*.*?\[\s*별지\s*제?\s*\d+\s*호서식\s*\].*', re.M)


def _prepare_promoted_lines(docs: List[LCDocument]) -> List[tuple]:
    """문서 리스트를 (line, page_num) 튜플 리스트로 변환"""
    promoted_lines = []
    for doc in docs:
        page_num = doc.metadata.get("page") if doc.metadata else None
        for line in doc.page_content.splitlines():
            promoted_lines.append((line, page_num))
    return promoted_lines


def _is_boilerplate_line(text: str) -> bool:
    t = text.strip()
    if not t:
        return True
    if re.search(r'법제처', t) and re.search(r'국가법령정보센터', t):
        return True
    if re.fullmatch(r'법제처\s*\d+\s*국가법령정보센터', t):
        return True
    if re.fullmatch(r'\d+', t):
        return True
    if re.fullmatch(r'[가-힣A-Za-z0-9\s\-\(\)]+(?:법|법률)(?:\s+시행령|\s+시행규칙|\s+기준에\s+관한\s+규칙)?$', t):
        return True
    if re.fullmatch(r'[가-힣A-Za-z0-9\s\-\(\)]+기준에\s+관한\s+규칙$', t):
        return True
    return False


def _is_toc_article(article_text: str) -> bool:
    lines = article_text.splitlines()
    if not lines:
        return True

    item_pattern = re.compile(r'^([①-⑳])\s+')
    subitem_pattern = re.compile(r'^(\d+)\.\s+')
    subsubitem_pattern = re.compile(r'^(?:가|나|다|라|마|바|사|아|자|차|카|타|파|하)\.\s+')

    first_line = lines[0].strip()
    m = _ARTICLE_PATTERN.match(first_line)
    if not m:
        return False

    inline_after_header = first_line[m.end():].strip()
    title_stripped = re.sub(r'^\([^)]*\)\s*', '', inline_after_header)
    if title_stripped:
        return False

    for line in lines[1:]:
        stripped = line.strip()
        if not stripped or _is_boilerplate_line(stripped):
            continue
        if _CHAPTER_PATTERN.match(stripped) or _SECTION_PATTERN.match(stripped):
            return True
        if _ARTICLE_PATTERN.match(stripped):
            return True
        if (item_pattern.match(stripped) or subitem_pattern.match(stripped) or
                subsubitem_pattern.match(stripped) or
                (len(stripped) > 0 and not stripped.startswith('###'))):
            return False
    return True


def _build_header_path(
    current_chapter, current_section, article_num,
    current_annex, current_annex_name=None
) -> str:
    if current_annex_name:
        return f"{current_annex_name} > 제{article_num}조" if article_num else current_annex_name
    if current_annex and article_num:
        return f"부칙 > 제{article_num}조"
    if current_chapter and current_section and article_num:
        return f"{current_chapter} > {current_section} > 제{article_num}조"
    if current_chapter and article_num:
        return f"{current_chapter} > 제{article_num}조"
    if current_section and article_num:
        return f"{current_section} > 제{article_num}조"
    if article_num:
        return f"제{article_num}조"
    if current_chapter and current_section:
        return f"{current_chapter} > {current_section}"
    if current_chapter:
        return current_chapter
    if current_section:
        return current_section
    return "부칙" if current_annex else ""


def _is_annex_line(stripped_line: str) -> bool:
    return (
        _ANNEX_HEADER_PATTERN.match(stripped_line) is not None
        or _ANNEX_PATTERN.match(stripped_line) is not None
        or _ANNEX_FORM_HEADER_PATTERN.match(stripped_line) is not None
        or _ANNEX_FORM_PATTERN.match(stripped_line) is not None
    )


def _is_annex_text(article_text: str) -> bool:
    return (
        _ANNEX_HEADER_PATTERN.search(article_text) is not None
        or _ANNEX_PATTERN.search(article_text) is not None
        or _ANNEX_FORM_HEADER_PATTERN.search(article_text) is not None
        or _ANNEX_FORM_PATTERN.search(article_text) is not None
    )


def _split_into_sentences(text: str) -> List[str]:
    sentences: List[str] = []
    sentence_end = re.compile(r'.*?[\.\?\!。！？…]+|.+$', re.S)
    for para in text.splitlines():
        para = para.strip()
        if para:
            for m in sentence_end.finditer(para):
                s = m.group(0).strip()
                if s:
                    sentences.append(s)
    return sentences


def _merge_enum_only_with_next(sentences: List[str]) -> List[str]:
    merged: List[str] = []
    enum_only = re.compile(r'^\d+(?:의\d+)?\.?$')
    i = 0
    while i < len(sentences):
        if enum_only.match(sentences[i]) and i + 1 < len(sentences):
            merged.append(sentences[i] + ' ' + sentences[i + 1])
            i += 2
        else:
            merged.append(sentences[i])
            i += 1
    return merged


def _assemble_chunks_from_sentences(sentences: List[str], limit: int) -> List[str]:
    chunks: List[str] = []
    cur: List[str] = []
    cur_len = 0
    enum_only = re.compile(r'^\d+(?:의\d+)?\.?$')
    for s in sentences:
        sl = len(s)
        if cur_len and cur_len + sl + 1 > limit:
            if cur and enum_only.match(cur[-1]):
                last_enum = cur.pop()
                if cur:
                    chunks.append(" ".join(cur))
                cur = [last_enum, s]
                cur_len = len(last_enum) + 1 + sl
            else:
                if enum_only.match(s):
                    if cur:
                        chunks.append(" ".join(cur))
                    cur = [s]
                    cur_len = sl
                else:
                    chunks.append(" ".join(cur))
                    cur = [s]
                    cur_len = sl
        else:
            cur.append(s)
            cur_len += sl + (1 if cur_len else 0)
    if cur:
        chunks.append(" ".join(cur))
    return chunks


def _normalize_overlong_chunks(chunks: List[str], limit: int) -> List[str]:
    normalized: List[str] = []
    for c in chunks:
        if len(c) <= limit:
            normalized.append(c)
        else:
            start = 0
            while start < len(c):
                end = min(start + limit, len(c))
                cut = c.rfind(' ', start, end)
                if cut == -1 or cut <= start + int(limit * 0.5):
                    cut = end
                normalized.append(c[start:cut])
                start = cut
    return normalized


def sentence_chunks(text: str, limit: int) -> List[str]:
    sentences = _split_into_sentences(text)
    sentences = _merge_enum_only_with_next(sentences)
    chunks = _assemble_chunks_from_sentences(sentences, limit)
    normalized = _normalize_overlong_chunks(chunks, limit)
    return normalized if normalized else [text]


def _detect_item_pattern(lines: List[str]):
    item_pattern = re.compile(r'^([①-⑳])\s+')
    subitem_pattern = re.compile(r'^(\d+)\.\s+')
    subsubitem_pattern = re.compile(r'^(?:가|나|다|라|마|바|사|아|자|차|카|타|파|하)\.\s+')
    if any(item_pattern.match(line) for line in lines):
        return item_pattern
    if any(subitem_pattern.match(line) for line in lines):
        return subitem_pattern
    if any(subsubitem_pattern.match(line) for line in lines):
        return subsubitem_pattern
    return None


def _split_items_by_pattern(lines, pattern) -> List[str]:
    items: List[str] = []
    current_item: List[str] = []
    for line in lines:
        if pattern.match(line):
            if current_item:
                items.append("\n".join(current_item))
            current_item = [line]
        else:
            current_item.append(line)
    if current_item:
        items.append("\n".join(current_item))
    return items


def split_article_by_items(
    article_text: str,
    chunk_size: int = DEFAULT_CONFIG.law_chunk_size,
    chunk_overlap: int = DEFAULT_CONFIG.law_chunk_overlap,
) -> List[str]:
    lines = article_text.splitlines()
    pattern = _detect_item_pattern(lines)
    if not pattern:
        return sentence_chunks(article_text, chunk_size)

    items = _split_items_by_pattern(lines, pattern)
    if not items:
        return sentence_chunks(article_text, chunk_size)

    chunks: List[str] = []
    current_chunk: List[str] = []
    current_chunk_size = 0
    prev_chunk_end: Optional[str] = None

    for item in items:
        if prev_chunk_end and chunk_overlap > 0:
            overlap_text = prev_chunk_end[-chunk_overlap:] if len(prev_chunk_end) > chunk_overlap else prev_chunk_end
            item = overlap_text + "\n" + item

        item_size = len(item)
        if item_size > chunk_size:
            if current_chunk:
                chunks.append("\n".join(current_chunk))
                prev_chunk_end = "\n".join(current_chunk)
                current_chunk = []
                current_chunk_size = 0
            sub_chunks = sentence_chunks(item, chunk_size)
            chunks.extend(sub_chunks)
            prev_chunk_end = sub_chunks[-1] if sub_chunks else None
        else:
            if current_chunk_size + item_size + 1 > chunk_size:
                if current_chunk:
                    chunks.append("\n".join(current_chunk))
                    prev_chunk_end = "\n".join(current_chunk)
                current_chunk = [item]
                current_chunk_size = item_size
            else:
                current_chunk.append(item)
                current_chunk_size += item_size + 1
    if current_chunk:
        chunks.append("\n".join(current_chunk))
    return chunks if chunks else sentence_chunks(article_text, chunk_size)


def _clean_article_text_with_header(article_text: str) -> Optional[str]:
    lines = article_text.splitlines()
    header_line_formatted = None
    content_lines = []
    is_annex_header = False

    for line in lines:
        stripped = line.strip()
        is_article_header = _ARTICLE_PATTERN.match(stripped)
        is_annex_header_match = _ANNEX_HEADER_PATTERN.match(stripped)
        is_annex_form_match = _ANNEX_FORM_HEADER_PATTERN.match(stripped)

        if is_article_header or is_annex_header_match or is_annex_form_match:
            header_line_formatted = line
            if is_annex_header_match or is_annex_form_match:
                is_annex_header = True
            if is_article_header:
                header_end_pos = _ARTICLE_PATTERN.match(stripped).end()
                remaining = stripped[header_end_pos:].strip()
                m_title = re.match(r'^\([^)]*\)\s*', remaining)
                title_part = m_title.group(0).strip() if m_title else ''
                prefix_ws = line[:len(line) - len(line.lstrip())]
                header_core = stripped[:header_end_pos] + (f" {title_part}" if title_part else '')
                header_line_formatted = prefix_ws + header_core
                remaining_after_title = remaining[len(m_title.group(0)):] if m_title else remaining
                remaining_wo_title = remaining_after_title.strip()
                if remaining_wo_title:
                    content_lines.append(remaining_wo_title)
            continue

        if header_line_formatted:
            if stripped and not _is_boilerplate_line(stripped):
                content_lines.append(stripped)

    if not content_lines:
        return None

    content_text = '\n'.join(content_lines).strip() if is_annex_header else ' '.join(content_lines).strip()
    if len(content_text) < 10:
        return None

    if header_line_formatted:
        return header_line_formatted.rstrip() + ("\n" + "\n".join(content_lines) if content_lines else '')
    return None


def _clean_article_text_without_header(article_text: str) -> Optional[str]:
    filtered_lines = [
        line for line in article_text.splitlines()
        if line.strip() and not _is_boilerplate_line(line.strip())
    ]
    cleaned_text = "\n".join(filtered_lines).strip()
    return cleaned_text if len(cleaned_text) > 50 else None


def _save_article_chunks(
    cleaned_text: str,
    current_header_path: Optional[str],
    article_page: Optional[int],
    base_meta: Dict[str, Any],
    chunk_size: int,
    final_docs: List[LCDocument],
    is_annex: bool = False,
    chunk_overlap: int = DEFAULT_CONFIG.law_chunk_overlap,
) -> Optional[str]:
    """정제된 조문 텍스트를 청크로 분할하여 final_docs에 추가"""
    header_line = None
    if is_annex:
        lines = cleaned_text.split('\n')
        if lines:
            first_line = lines[0].strip()
            if _is_annex_line(first_line):
                header_line = lines[0]
                cleaned_text = '\n'.join(lines[1:]).strip()

    def _make_meta():
        meta = {**base_meta, "header_path": current_header_path}
        meta["page"] = article_page
        meta["page_start"] = article_page
        meta["page_end"] = article_page
        meta["pages_display"] = str(article_page) if article_page else "1"
        # header_path에서 section_title 파생 (마지막 요소)
        if current_header_path:
            parts = [p.strip() for p in current_header_path.split(">")]
            meta["section_title"] = parts[-1] if parts else None
        return meta

    def _make_content(text: str) -> str:
        content = text.strip()
        if current_header_path:
            content = f"{current_header_path}\n\n{content}"
        return content

    if is_annex:
        if len(cleaned_text) > chunk_size:
            rcts = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=0)
            sub_articles = rcts.split_text(cleaned_text)
        else:
            sub_articles = [cleaned_text]

        if header_line and sub_articles:
            sub_articles[0] = header_line + '\n' + sub_articles[0]

        for sub_article in sub_articles:
            if sub_article.strip():
                final_docs.append(LCDocument(page_content=_make_content(sub_article), metadata=_make_meta()))

        return sub_articles[-1] if sub_articles else None
    else:
        if len(cleaned_text) > chunk_size:
            sub_articles = split_article_by_items(cleaned_text, chunk_size=chunk_size, chunk_overlap=0)
            for sub_article in sub_articles:
                if sub_article.strip():
                    final_docs.append(LCDocument(page_content=_make_content(sub_article), metadata=_make_meta()))
            return sub_articles[-1] if sub_articles else None
        else:
            if cleaned_text.strip():
                final_docs.append(LCDocument(page_content=_make_content(cleaned_text), metadata=_make_meta()))
            return cleaned_text


def _save_current_article(
    current_article, current_article_pages, current_article_start_page,
    current_header_path, base_meta, chunk_size, final_docs,
    chunk_overlap=DEFAULT_CONFIG.law_chunk_overlap,
    prev_article_end=None,
) -> Optional[str]:
    if current_article is None:
        return None

    is_annex_article = bool(current_article) and _is_annex_line(current_article[0].strip())

    if is_annex_article:
        filtered_article = current_article
        filtered_pages = current_article_pages
    else:
        filtered_article = []
        filtered_pages = []
        for j, article_line in enumerate(current_article):
            stripped = article_line.strip()
            if j == 0:
                filtered_article.append(article_line)
                if j < len(current_article_pages):
                    filtered_pages.append(current_article_pages[j])
                continue
            if (_ARTICLE_PATTERN.match(stripped) or _ANNEX_HEADER_PATTERN.match(stripped) or
                    _ANNEX_FORM_HEADER_PATTERN.match(stripped) or _CHAPTER_PATTERN.match(stripped) or
                    _SECTION_PATTERN.match(stripped)):
                break
            filtered_article.append(article_line)
            if j < len(current_article_pages):
                filtered_pages.append(current_article_pages[j])

    article_text = "\n".join(filtered_article).strip()
    is_annex = _is_annex_text(article_text)

    if not is_annex and _is_toc_article(article_text):
        return None

    has_header = _ARTICLE_PATTERN.search(article_text) is not None or is_annex

    if has_header:
        cleaned_article_text = article_text if is_annex else _clean_article_text_with_header(article_text)
    else:
        cleaned_article_text = _clean_article_text_without_header(article_text)

    if cleaned_article_text is None:
        return None

    article_page = (
        current_article_start_page
        if current_article_start_page is not None
        else next((p for p in filtered_pages if p is not None), None)
    )

    return _save_article_chunks(
        cleaned_article_text, current_header_path, article_page,
        base_meta, chunk_size, final_docs, is_annex=is_annex,
        chunk_overlap=chunk_overlap,
    )


def split_law_markdown(
    docs: List[LCDocument],
    chunk_size: int = DEFAULT_CONFIG.law_chunk_size,
    chunk_overlap: int = DEFAULT_CONFIG.law_chunk_overlap,
) -> List[LCDocument]:
    """
    법령 문서를 조문/별표/별지 단위로 청킹.

    1) 전체 텍스트 결합 → 2) 조문 단위 분할
    3) 조문이 너무 길면 항(① ② ③) 단위로 분할
    4) 목차 부분(조문 헤더만 있고 내용 없는 부분) 제거
    """
    if not docs:
        return []

    promoted_lines = _prepare_promoted_lines(docs)
    final_docs: List[LCDocument] = []
    base_meta = docs[0].metadata if docs else {}

    current_article = None
    current_article_pages = []
    current_header_path = None
    current_chapter = None
    current_section = None
    current_article_start_page = None
    current_annex = False
    current_annex_name = None
    prev_article_end: Optional[str] = None

    patterns = {
        'article': _ARTICLE_PATTERN,
        'chapter': _CHAPTER_PATTERN,
        'section': _SECTION_PATTERN,
        'annex_heading': _ANNEX_HEADING_PATTERN,
        'annex_plain': _ANNEX_PLAIN_PATTERN,
        'annex': _ANNEX_PATTERN,
        'annex_form': _ANNEX_FORM_PATTERN,
    }

    i = 0
    while i < len(promoted_lines):
        line, page_num = promoted_lines[i]
        stripped_line = line.strip()

        # 별표/별지 수집 중 처리
        if current_article is not None and current_annex and current_annex_name:
            is_next_annex = patterns['annex'].match(stripped_line)
            is_next_annex_form = patterns['annex_form'].match(stripped_line)

            if is_next_annex or is_next_annex_form:
                prev_article_end = _save_current_article(
                    current_article, current_article_pages, current_article_start_page,
                    current_header_path, base_meta, chunk_size, final_docs,
                    chunk_overlap=chunk_overlap, prev_article_end=prev_article_end,
                )
                current_annex = False
                current_annex_name = None
                current_article, current_article_pages, current_article_start_page = None, [], None
                continue
            else:
                current_article.append(line)
                current_article_pages.append(page_num)
                i += 1
                continue

        header_processed = False

        if annex_match := patterns['annex'].match(stripped_line):
            prev_article_end = _save_current_article(
                current_article, current_article_pages, current_article_start_page,
                current_header_path, base_meta, chunk_size, final_docs,
                chunk_overlap=chunk_overlap, prev_article_end=prev_article_end,
            )
            annex_num = annex_match.group(1)
            current_annex_name = f"별표 {annex_num}"
            current_annex = True
            current_header_path = _build_header_path(current_chapter, current_section, None, False, current_annex_name)
            current_article = [line]
            current_article_pages = [page_num]
            current_article_start_page = page_num
            header_processed = True

        elif annex_form_match := patterns['annex_form'].match(stripped_line):
            prev_article_end = _save_current_article(
                current_article, current_article_pages, current_article_start_page,
                current_header_path, base_meta, chunk_size, final_docs,
                chunk_overlap=chunk_overlap, prev_article_end=prev_article_end,
            )
            form_num = annex_form_match.group(1)
            current_annex_name = f"별지 제{form_num}호서식"
            current_annex = True
            current_header_path = _build_header_path(current_chapter, current_section, None, False, current_annex_name)
            current_article = [line]
            current_article_pages = [page_num]
            current_article_start_page = page_num
            header_processed = True

        elif patterns['annex_heading'].match(line) or patterns['annex_plain'].match(line):
            prev_article_end = _save_current_article(
                current_article, current_article_pages, current_article_start_page,
                current_header_path, base_meta, chunk_size, final_docs,
                chunk_overlap=chunk_overlap, prev_article_end=prev_article_end,
            )
            current_annex = True
            current_annex_name = None
            current_chapter = None
            current_section = None
            current_header_path = "부칙"
            current_article, current_article_pages, current_article_start_page = None, [], None
            header_processed = True

        elif chapter_match := patterns['chapter'].match(line):
            prev_article_end = _save_current_article(
                current_article, current_article_pages, current_article_start_page,
                current_header_path, base_meta, chunk_size, final_docs,
                chunk_overlap=chunk_overlap, prev_article_end=prev_article_end,
            )
            current_annex = False
            current_annex_name = None
            current_chapter = f"제{chapter_match.group(1)}장"
            current_section = None
            current_header_path = current_chapter
            current_article, current_article_pages, current_article_start_page = None, [], None
            header_processed = True

        elif section_match := patterns['section'].match(line):
            prev_article_end = _save_current_article(
                current_article, current_article_pages, current_article_start_page,
                current_header_path, base_meta, chunk_size, final_docs,
                chunk_overlap=chunk_overlap, prev_article_end=prev_article_end,
            )
            current_annex = False
            current_annex_name = None
            current_section = f"제{section_match.group(1)}절"
            current_header_path = _build_header_path(current_chapter, current_section, None, False)
            current_article, current_article_pages, current_article_start_page = None, [], None
            header_processed = True

        elif article_match := patterns['article'].match(stripped_line):
            prev_article_end = _save_current_article(
                current_article, current_article_pages, current_article_start_page,
                current_header_path, base_meta, chunk_size, final_docs,
                chunk_overlap=chunk_overlap, prev_article_end=prev_article_end,
            )
            article_num = article_match.group(1)
            current_header_path = _build_header_path(
                current_chapter, current_section, article_num, current_annex, current_annex_name
            )
            current_article = [line.strip()]
            current_article_pages = [page_num]
            current_article_start_page = page_num
            header_processed = True

        if not header_processed and current_article is not None:
            current_article.append(line)
            current_article_pages.append(page_num)

        i += 1

    # 마지막 조문 저장
    _save_current_article(
        current_article, current_article_pages, current_article_start_page,
        current_header_path, base_meta, chunk_size, final_docs,
        chunk_overlap=chunk_overlap, prev_article_end=prev_article_end,
    )

    # char_start_offset / char_end_offset: 전체 텍스트에서 각 청크 위치 탐색
    full_text = "\n".join(line for line, _ in promoted_lines)
    search_pos = 0
    for lc_doc in final_docs:
        content = lc_doc.page_content
        header_path = lc_doc.metadata.get("header_path") or ""
        # _make_content()가 붙인 header prefix 제거 후 원문 검색
        if header_path and content.startswith(header_path + "\n\n"):
            core_text = content[len(header_path) + 2:].strip()
        else:
            core_text = content.strip()
        snippet = core_text[:80]
        if snippet:
            pos = full_text.find(snippet, max(0, search_pos - 500))
            if pos == -1:
                pos = full_text.find(snippet)
            if pos != -1:
                lc_doc.metadata["char_start_offset"] = pos
                lc_doc.metadata["char_end_offset"] = pos + len(core_text)
                search_pos = pos

    return final_docs
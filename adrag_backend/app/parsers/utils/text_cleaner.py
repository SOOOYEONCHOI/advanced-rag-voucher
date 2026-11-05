"""
텍스트 정제 유틸리티
레퍼런스: reference_code/Chatbot_Backend_v1/app/services/pdf_chunking/utils/text_cleaner.py
"""

import html
import re


def rm_unnecessary_char(text: str) -> str:
    """불필요 공백/개행 정리 + 특수문자 정규화 (헤더 패턴 보존)"""
    t = text

    # 2026.05.22(sooyeon.choi) 추가 - HTML 엔티티 디코딩
    # Docling이 마크다운 변환 시 &lt; &gt; &amp; 등을 그대로 남기는 경우 처리.
    # 디코딩 후 기존 법령 개정 패턴(<개정...>) 보존 로직이 정상 동작한다.
    t = html.unescape(t)

    # 법령 개정 정보 보존 (임시 플레이스홀더로 교체)
    revision_placeholders = {}
    revision_pattern = re.compile(r'<([개정신설삭제전부개정][^>]+)>')
    placeholder_idx = 0

    def replace_revision(match):
        nonlocal placeholder_idx
        placeholder = f'__REVISION_PLACEHOLDER_{placeholder_idx}__'
        revision_placeholders[placeholder] = match.group(0)
        placeholder_idx += 1
        return placeholder

    t = revision_pattern.sub(replace_revision, t)

    # HTML 태그 제거 (<br> 제외)
    t = re.sub(r'<(?!br\s*/?>)[^>]+>', '', t, flags=re.IGNORECASE)

    # 법령 개정 정보 복원 (각도 괄호 제거: <개정 2022. 8. 18.> → 개정 2022. 8. 18.)
    for placeholder, original in revision_placeholders.items():
        t = t.replace(placeholder, original[1:-1])

    # NBSP, Zero-width 문자 제거
    t = t.replace("\u00a0", " ")
    t = t.replace("\u200b", "")

    # 라인별 처리 (헤더 패턴 보존)
    lines = t.splitlines()
    cleaned_lines = []
    for line in lines:
        if re.match(r"^\s*제?\s*\d+\s*(편|장|절|관|조)", line):
            cleaned_lines.append(line.strip())
        else:
            cleaned_line = re.sub(r"[ \t]+", " ", line)
            cleaned_lines.append(cleaned_line.strip())

    t = "\n".join(cleaned_lines)
    t = re.sub(r"\n{3,}", "\n\n", t)
    t = re.sub(r"(?m)^\s*[-•·]\s+(?=제?\s*\d+\s*(?:편|장|절|관)|제\s*\d+\s*조)", "", t)
    return t.strip()


def remove_table_header_rule(markdown: str) -> str:
    """Markdown 표의 헤더 구분선(| --- |) 라인 제거"""
    header_rule = re.compile(r"(?m)^\s*\|(?:\s*:?-+:?\s*\|)+\s*$")
    return header_rule.sub('', markdown)


_TABLE_SEPARATOR_ROW_RE = re.compile(r"^\|(?:\s*:?-{3,}:?\s*\|)+\s*$")
_TABLE_SEPARATOR_CELL_RE = re.compile(r"^\s*(:?)-{3,}(:?)\s*$")


def normalize_markdown_table_separators(markdown: str) -> str:
    """Markdown table separator row의 긴 dash 구간을 최소 표현으로 축약한다."""
    if not markdown:
        return ""

    normalized_lines = []
    in_fenced_code_block = False

    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fenced_code_block = not in_fenced_code_block
            normalized_lines.append(line)
            continue

        if in_fenced_code_block or not _TABLE_SEPARATOR_ROW_RE.match(stripped):
            normalized_lines.append(line)
            continue

        cells = stripped.split("|")[1:-1]
        compact_cells = []
        valid_separator_row = True

        for cell in cells:
            match = _TABLE_SEPARATOR_CELL_RE.match(cell)
            if not match:
                valid_separator_row = False
                break

            left_align, right_align = match.groups()
            compact_cells.append(f"{left_align}---{right_align}")

        if valid_separator_row:
            normalized_lines.append("|" + "|".join(compact_cells) + "|")
        else:
            normalized_lines.append(line)

    return "\n".join(normalized_lines)


def preserve_line_breaks_in_text(text: str) -> str:
    """텍스트 내의 <br> 태그를 개행으로 변환"""
    if not text:
        return ""

    t = text.replace('<br>', '\n').replace('<br/>', '\n').replace('<br />', '\n')
    t = t.replace('<BR>', '\n').replace('<BR/>', '\n').replace('<BR />', '\n')

    # 법령 개정 정보 보존
    revision_placeholders = {}
    revision_pattern = re.compile(r'<([개정신설삭제전부개정][^>]+)>')
    placeholder_idx = 0

    def replace_revision(match):
        nonlocal placeholder_idx
        placeholder = f'__REVISION_PLACEHOLDER_SUB_{placeholder_idx}__'
        revision_placeholders[placeholder] = match.group(0)
        placeholder_idx += 1
        return placeholder

    t = revision_pattern.sub(replace_revision, t)
    t = re.sub(r'<[^>]+>', '', t)

    for placeholder, original in revision_placeholders.items():
        t = t.replace(placeholder, original[1:-1])

    return t


# 볼드 처리된 법령 구조 마커 정규식 (** 제N조(제목) ** 형태)
_BOLD_LAW_MARKER = re.compile(
    r'\*\*(제\s*\d+\s*(?:편|장|절|관|조(?:의\s*\d+)?)(?:\s*[^*\n]{0,60})?)\*\*'
)


def strip_bold_law_markers(text: str) -> str:
    """
    볼드(**) 처리된 법령 구조 마커를 일반 텍스트로 변환.
    Docling이 DOCX Word 스타일을 **제1조(목적)** 형태의 볼드로 출력할 때,
    promote_headers()가 올바르게 작동하도록 ** 제거.

    예: **제1장 총칙** → 제1장 총칙
        **제1조(목적)** → 제1조(목적)
    """
    return _BOLD_LAW_MARKER.sub(r'\1', text)


def format_table_with_line_breaks(text: str) -> str:
    """표 내부 텍스트 처리 (표 라인은 <br> 유지, 일반 텍스트는 개행 변환)"""
    if not text:
        return ""

    lines = text.splitlines()
    result_lines = []

    for line in lines:
        stripped = line.strip()
        is_table_line = bool(re.match(r'^\s*\|', stripped))

        if is_table_line:
            processed_line = re.sub(r'<(?!br\s*/?>)[^>]+>', '', line, flags=re.IGNORECASE)
            processed_line = re.sub(r' {2,}', ' ', processed_line)
            result_lines.append(processed_line)
        else:
            result_lines.append(preserve_line_breaks_in_text(line))

    result = "\n".join(result_lines)
    result = re.sub(r'\n{2}', '\n', result)
    result = re.sub(r'\n{3,}', '\n\n', result)
    return result

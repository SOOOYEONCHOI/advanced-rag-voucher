# 2026.11.18(sooyeon.choi) 추가 - 답변 본문 정리본 (설계 F-13, REQ-B-08)
"""LLM 심사 입력용으로 답변에서 인용 표시·사진 표식·마크다운 기호를 뺀다(원문은 별도 보존)."""

import re

_IMG_TAG = re.compile(r"\[IMG:\s*[A-Za-z0-9_-]{1,64}\s*\]")
_CITATION_TAG = re.compile(r"\[\s*\d+(?:\s*[,，]\s*\d+)*\s*\]")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE)
_QUOTE = re.compile(r"^\s{0,3}>\s?", re.MULTILINE)
_BULLET = re.compile(r"^(\s*)[-*+•]\s+", re.MULTILINE)
_EMPHASIS = re.compile(r"(\*\*|__|\*|`+)")
_HR = re.compile(r"^\s*([-*_]\s*){3,}$", re.MULTILINE)
_TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$", re.MULTILINE)


def clean_answer_text(text: str) -> str:
    """원문 답변 → 본문 정리본. 번호 목록(1.)과 줄 구분은 유지한다."""
    if not text:
        return ""
    value = _IMG_TAG.sub("", text)
    value = _CITATION_TAG.sub("", value)
    value = _TABLE_RULE.sub("", value)
    value = _HR.sub("", value)
    value = _HEADING.sub("", value)
    value = _QUOTE.sub("", value)
    value = _BULLET.sub(r"\1", value)
    value = _EMPHASIS.sub("", value)
    value = value.replace("|", " ")
    value = re.sub(r"[ \t]+([,.!?;:])", r"\1", value)
    value = re.sub(r"[ \t]{2,}", " ", value)
    lines = [line.strip() for line in value.splitlines()]
    value = "\n".join(lines)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()

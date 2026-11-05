"""
법령 문서 판정 모듈
레퍼런스: reference_code/Chatbot_Backend_v1/app/services/pdf_chunking/law/detector.py
"""

import re
from typing import Dict, Optional
from ..utils.header_promoter import LAW_PATTERNS, TOC_PATTERNS

_TOC_ARTICLE_PATTERN = TOC_PATTERNS["article"]
_TOC_CHAPTER_PATTERN = TOC_PATTERNS["chapter"]
_TOC_SECTION_PATTERN = TOC_PATTERNS["section"]

# 2026.07.13(sooyeon.choi) 수정 - 목차 없이 본문부터 시작하는 공식 법령 문서 판정 추가
_OFFICIAL_LAW_HEADER_PATTERN = re.compile(
    r"\[시행\s+\d{4}\.\s*\d{1,2}\.\s*\d{1,2}\.\s*\]"
    r"[\s\S]{0,200}?"
    r"\[(?:헌법|법률|대통령령|총리령|[가-힣]*부령|[가-힣]*규칙)\s+제?\s*\d+\s*호",
    re.IGNORECASE,
)
_ARTICLE_HEADING_PATTERN = re.compile(
    r"^\s*(?:#{1,6}\s*)?제\s*\d+\s*조(?:의\s*\d+)?\s*\([^)]+\)",
    re.MULTILINE,
)


def count_law_signals(text: str) -> Dict[str, int]:
    """법령 신호 패턴 개수 집계"""
    return {k: len(p.findall(text)) for k, p in LAW_PATTERNS.items()}


def has_toc_structure(first_page_text: str) -> bool:
    """첫 페이지에 법령 목차 구조가 있는지 확인"""
    toc_articles = len(_TOC_ARTICLE_PATTERN.findall(first_page_text))
    toc_chapters = len(_TOC_CHAPTER_PATTERN.findall(first_page_text))
    toc_sections = len(_TOC_SECTION_PATTERN.findall(first_page_text))
    return (toc_articles >= 7) and (toc_chapters + toc_sections + toc_articles >= 5)


def has_official_law_body(first_page_text: str) -> bool:
    """첫 페이지에 공식 시행·공포 헤더와 조문 본문이 함께 있는지 확인"""
    has_official_header = bool(_OFFICIAL_LAW_HEADER_PATTERN.search(first_page_text))
    article_headings = len(_ARTICLE_HEADING_PATTERN.findall(first_page_text))
    return has_official_header and article_headings >= 2


def is_law_like(
    text: str,
    score_threshold: int = 6,
    article_threshold: int = 2,
    first_page_text: Optional[str] = None,
) -> bool:
    """
    법령 문서 여부 판정.

    판정식:
      1. 상위 구조(편/장/절/관/조/별표) 각 2점, 하위(항/호/목) 각 1점
      2. 총점 >= score_threshold OR '조' >= article_threshold
      3. 첫 페이지에 목차 구조(제N조(제목))가 있거나 공식 시행·공포 헤더와 조문 본문 존재
      → 2, 3 모두 만족 시 법령으로 판정
    """
    c = count_law_signals(text)
    score = (
        2 * (c["편"] + c["장"] + c["절"] + c["관"] + c["조"] + c["별표"] + c["별지"])
        + (c["항"] + c["호"] + c["목"])
    )
    has_score = score >= score_threshold or c["조"] >= article_threshold

    has_toc = True
    has_official_body = False
    if first_page_text is not None:
        has_toc = has_toc_structure(first_page_text)
        # 2026.07.13(sooyeon.choi) 수정 - 기존 목차 판정은 유지하고 공식 법령 본문을 OR 조건으로 허용
        has_official_body = has_official_law_body(first_page_text)

    return has_score and (has_toc or has_official_body)

"""
법령 문서 헤더 승격 + 패턴 정의
레퍼런스: reference_code/Chatbot_Backend_v1/app/services/pdf_chunking/law/patterns.py
레퍼런스: reference_code/Chatbot_Backend_v1/app/services/pdf_chunking/law/header_promoter.py
"""

import re


# ── 법령 구조 패턴 ──────────────────────────────────────────────────────────
LAW_PATTERNS = {
    "편": re.compile(r"^\s*제?\s*\d+\s*편", re.M),
    "장": re.compile(r"^\s*제?\s*\d+\s*장", re.M),
    "절": re.compile(r"^\s*제?\s*\d+\s*절", re.M),
    "관": re.compile(r"^\s*제?\s*\d+\s*관", re.M),
    "조": re.compile(r"(?m)(?:^|[\s\.\:\;])제\s*\d+\s*조(?:\s|$|[\(\)])", re.M),
    "항": re.compile(r"(?m)(^\s*[①-⑳]\s)|(?:제\s*\d+\s*조.*?[①-⑳]\s)"),
    "호": re.compile(r"(?m)^\s*\d+\.\s"),
    "목": re.compile(r"(?m)^\s*(?:가|나|다|라|마|바|사|아|자|차|카|타|파|하)\.\s"),
    "별표": re.compile(r"(?m)[\-■※].*?\[\s*별표\s*\d+\s*\]"),
    "별지": re.compile(r"(?m)[\-■※].*?\[\s*별지\s*제?\s*\d+\s*호서식\s*\]"),
}

# ── 승격 후 패턴 (promote_headers 거친 뒤 텍스트 매칭) ──────────────────────
PROMOTED_PATTERNS = {
    "chapter": re.compile(r'^#\s+제\s*(\d+)\s*장'),
    "section": re.compile(r'^##\s+제\s*(\d+)\s*절'),
    "article": re.compile(r'^###\s+제\s*(\d+)\s*조(?:의\s*\d+)?'),
    "annex_heading": re.compile(r'^\s*#{1,6}\s*부칙(?:\s*\d+)?\s*$'),
    "annex_plain": re.compile(r'^\s*부칙(?:\s*\d+)?\s*$'),
    "annex": re.compile(r'^##\s*[\-■※]\s*.*?\[\s*별표\s*(\d+)\s*\].*'),
    "annex_form": re.compile(r'^##\s*[\-■※]\s*.*?\[\s*별지\s*제?\s*(\d+)\s*호서식\s*\].*'),
    "annex_header": re.compile(r'^##\s*[\-■※]\s*.*?\[\s*별표\s*\d+\s*\].*', re.M),
    "annex_form_header": re.compile(r'^##\s*[\-■※]\s*.*?\[\s*별지\s*제?\s*\d+\s*호서식\s*\].*', re.M),
}

# ── 목차 구조 패턴 ──────────────────────────────────────────────────────────
TOC_PATTERNS = {
    "article": re.compile(r'제\s*\d+\s*조\s*\([^)]+\)', re.M),
    "chapter": re.compile(r'제\s*\d+\s*장', re.M),
    "section": re.compile(r'제\s*\d+\s*절', re.M),
}

# ── 헤더 승격 규칙 ──────────────────────────────────────────────────────────
HEADER_RULES = [
    (re.compile(r"(?m)^\s*제?\s*\d+\s*편.*$"), 1),
    (re.compile(r"(?m)^\s*제?\s*\d+\s*장.*$"), 1),
    (re.compile(r"(?m)^\s*제?\s*\d+\s*절.*$"), 2),
    (re.compile(r"(?m)^\s*제?\s*\d+\s*관.*$"), 2),
    (re.compile(r"(?m)^\s*제\s*\d+\s*조(?:의\s*\d+)?(?!\s*제\s*\d+\s*항)\s*(?:\(|$).*$"), 3),
    (re.compile(r"(?m)^\s*부칙(?:\s*\d+)?\s*$"), 1),
    (re.compile(r"(?m)^\s*[\-■※].*?\[\s*별표\s*\d+\s*\].*$"), 2),
    (re.compile(r"(?m)^\s*[\-■※].*?\[\s*별지\s*제?\s*\d+\s*호서식\s*\].*$"), 2),
]


def promote_headers(markdown_text: str) -> str:
    """각 라인을 HEADER_RULES에 따라 #~### 승격. 이미 #로 시작하면 유지."""
    out_lines = []
    for line in markdown_text.splitlines():
        raw = line.rstrip("\r")
        stripped = raw.strip()

        if stripped.startswith("#"):
            out_lines.append(raw)
            continue

        applied = False
        for pat, level in HEADER_RULES:
            if pat.match(stripped):
                out_lines.append(("#" * level) + " " + stripped)
                applied = True
                break

        if not applied:
            out_lines.append(raw)

    return "\n".join(out_lines)

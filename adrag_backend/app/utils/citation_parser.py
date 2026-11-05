"""답변 본문의 인라인 Citation 번호 파싱 유틸리티."""

import re


# 2026.07.10(sooyeon.choi) 수정 - 인용 앞 공백은 허용하고 줄 시작 번호 목록만 제외
_CITATION_TOKEN_RE = re.compile(r"\[(\d+)\]")
_LIST_PREFIX_RE = re.compile(r"^[ \t]*(?:[-*+][ \t]*)?$")
_LIST_ITEM_SUFFIX_RE = re.compile(r"[ \t]+\S")


def extract_citation_ids(text: str) -> list[int]:
    """인라인 ``[N]`` 인용 번호를 등장 순서대로 반환한다.

    줄 시작(선택적 Markdown bullet 포함)의 ``[N] 항목`` 형식은 번호
    목록으로 간주해 제외한다. 번호의 컨텍스트 범위 검증은 호출 측이 맡는다.
    """
    citation_ids: list[int] = []
    source = text or ""

    for match in _CITATION_TOKEN_RE.finditer(source):
        line_start = source.rfind("\n", 0, match.start()) + 1
        line_prefix = source[line_start:match.start()]
        suffix = source[match.end():]
        is_numbered_list = (
            _LIST_PREFIX_RE.fullmatch(line_prefix) is not None
            and _LIST_ITEM_SUFFIX_RE.match(suffix) is not None
        )
        if is_numbered_list:
            continue

        citation_ids.append(int(match.group(1)))

    return citation_ids

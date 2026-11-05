"""Answer Correctness v1 — 전체 답변 코사인 유사도 기반.

정규화된 gold/system 답변을 각각 임베딩하여 코사인 유사도를 반환한다.
표현 차이 및 답변 길이에 민감한 단순 기준선(baseline) 지표.
"""

import re
from typing import Optional


REFUSAL_PATTERNS = [
    "찾을 수 없", "근거가 없", "정보가 부족", "문서에 없",
    "확인되지 않", "알 수 없", "제공된 문서", "답변하기 어렵",
]


def check_format(answer: str) -> bool:
    """한국어 존댓말 종결 및 think 블록 미노출 여부."""
    if not answer or "<think>" in answer or "</think>" in answer:
        return False
    return bool(
        re.search(
            r"(습니다|세요|이에요|예요|합니다|됩니다)\s*\.?\s*$",
            answer.strip(),
        )
    )


def check_refusal(expected_behavior: str, answer: str) -> Optional[bool]:
    """not_enough_info 케이스의 거절 문구 포함 여부."""
    if expected_behavior != "not_enough_info":
        return None
    return any(pattern in answer for pattern in REFUSAL_PATTERNS)
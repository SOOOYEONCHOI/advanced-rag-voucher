"""not_enough_info 거절 적합성 판정.

2026.11.17(sooyeon.choi) 수정 - Answer Correctness v1(전체 답변 코사인) 삭제, 거절 판정만 남김
"""

from typing import Optional


REFUSAL_PATTERNS = [
    "찾을 수 없", "근거가 없", "정보가 부족", "문서에 없",
    "확인되지 않", "알 수 없", "제공된 문서", "답변하기 어렵",
]


# 2026.11.17(sooyeon.choi) 삭제 - check_format()(존댓말 종결 정규식 판정, 답변 품질과 무관한 형식 지표)


def check_refusal(expected_behavior: str, answer: str) -> Optional[bool]:
    """not_enough_info 케이스의 거절 문구 포함 여부."""
    if expected_behavior != "not_enough_info":
        return None
    return any(pattern in answer for pattern in REFUSAL_PATTERNS)
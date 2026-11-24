"""답변 유사도 계산 보조 함수.

- cosine_similarity: 임베딩 벡터 코사인 유사도 (순수 함수)
- normalize_answer_v2: 인용 태그·공백 정규화

2026.11.17(sooyeon.choi) 수정 - 규칙 일치(rule_check)·인용 태그 수 집계 삭제
"""

import math
import re
from typing import Sequence


class InvalidEmbeddingVector(ValueError):
    """Answer Correctness를 계산할 수 없는 임베딩 벡터."""


_CITATION_TAG_PATTERN = re.compile(r"\[\s*\d+(?:\s*[,，]\s*\d+)*\s*\]")

def cosine_similarity(vec_a: Sequence[float], vec_b: Sequence[float]) -> float:
    """두 유효 벡터의 코사인 유사도.

    빈 벡터·차원 불일치·0 벡터는 의미 있는 0점이 아니라 계산 불가이므로
    호출부가 ``null/error``로 처리할 수 있게 예외를 발생시킨다.
    """
    if not vec_a or not vec_b:
        raise InvalidEmbeddingVector("empty_vector")
    if len(vec_a) != len(vec_b):
        raise InvalidEmbeddingVector("dimension_mismatch")
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0 or norm_b == 0:
        raise InvalidEmbeddingVector("zero_norm")
    return dot / (norm_a * norm_b)


def clamp_similarity(value: float) -> float:
    """Answer Correctness 표시 범위를 0~1로 제한한다."""
    return max(0.0, min(1.0, value))


def normalize_answer_v2(value: str) -> str:
    """숫자 인용 태그와 공백 노이즈만 제거하는 대칭 정규화."""
    if not isinstance(value, str):
        return ""
    text = _CITATION_TAG_PATTERN.sub(" ", value.strip())
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


# 2026.11.17(sooyeon.choi) 삭제 - count_citation_tags(), extract_critical_tokens(), rule_check()
#   (rule_check는 법령 조항 패턴 기반이라 SOP 도메인과 맞지 않고, 정답 토큰이 없으면 1.0으로 통과 처리돼 평균을 부풀림)

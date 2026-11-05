"""답변 유사도 및 규칙 기반 체크.

- cosine_similarity: 임베딩 벡터 코사인 유사도 (순수 함수)
- extract_critical_tokens / rule_check: 골드답변의 수치·법규조항이
  시스템 답변에 포함되는지 확인 (산업안전 도메인에서 수치 오류는 치명적)

"""

import math
import re
from typing import Any, Dict, List, Sequence


class InvalidEmbeddingVector(ValueError):
    """Answer Correctness를 계산할 수 없는 임베딩 벡터."""


_CITATION_TAG_PATTERN = re.compile(r"\[\s*\d+(?:\s*[,，]\s*\d+)*\s*\]")

# 수치+단위 (예: 90cm, 1.5m, 21%, 18세, 2시간, 5일)
_NUMBER_UNIT_PATTERN = re.compile(
    r"\d+(?:\.\d+)?\s*(?:cm|mm|m|km|kg|g|t|%|퍼센트|도|℃|세|명|인|시간|분|초|일|개월|년|회|lux|럭스|dB|데시벨|ppm|MPa|kPa|V|A|kW)"
)
# 법규 조항 (예: 제32조, 제5조의2, 산업안전보건법 제38조)
_LAW_ARTICLE_PATTERN = re.compile(r"제\s?\d+\s?조(?:의\s?\d+)?")


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


def count_citation_tags(value: str) -> int:
    """정규화에서 제거되는 숫자 citation 태그 수를 반환한다."""
    if not isinstance(value, str):
        return 0
    return len(_CITATION_TAG_PATTERN.findall(value))


def extract_critical_tokens(text: str) -> List[str]:
    """수치+단위, 법규 조항 토큰을 추출한다 (공백 정규화, 중복 제거)."""
    tokens = []
    for pattern in (_NUMBER_UNIT_PATTERN, _LAW_ARTICLE_PATTERN):
        for match in pattern.findall(text):
            normalized = re.sub(r"\s+", "", match)
            if normalized not in tokens:
                tokens.append(normalized)
    return tokens


def rule_check(gold_answer: str, system_answer: str) -> Dict[str, Any]:
    """골드답변의 핵심 토큰(수치·법규조항)이 시스템 답변에 포함되는지 확인.

    반환: {expected: [...], found: [...], missing: [...], match_ratio}
    match_ratio는 expected가 없으면 1.0 (체크 대상 없음 = 통과).
    """
    expected = extract_critical_tokens(gold_answer)
    if not expected:
        return {"expected": [], "found": [], "missing": [], "match_ratio": 1.0}

    normalized_answer = re.sub(r"\s+", "", system_answer)
    found = [token for token in expected if token in normalized_answer]
    missing = [token for token in expected if token not in found]
    return {
        "expected": expected,
        "found": found,
        "missing": missing,
        "match_ratio": len(found) / len(expected),
    }

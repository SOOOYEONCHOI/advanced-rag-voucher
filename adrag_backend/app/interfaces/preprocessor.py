"""
질의 전처리기 인터페이스.

2026.07.16(sooyeon.choi) 추가 - 3단계 리팩토링: 인터페이스 도입
기준 구현: app/graphs/preprocessing/query_preprocessor.py QueryPreprocessor
(규칙 기반: 정규화 → 약어 확장 → 패턴 매칭 → 키워드 추출)
"""

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class QueryPreprocessorProtocol(Protocol):
    """규칙 기반 질의 전처리 계약."""

    def preprocess(self, query: str) -> Any:
        """PreprocessResult(normalized_query/expanded_terms/matched_patterns/extracted_keywords)를 반환한다."""
        ...

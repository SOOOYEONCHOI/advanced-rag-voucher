"""
리랭커 인터페이스.

2026.07.16(sooyeon.choi) 추가 - 3단계 리팩토링: 인터페이스 도입
기준 구현: app/clients/reranker_client.py RerankerClient (vLLM /v1/score)
Cross-Encoder 로컬 추론, 외부 rerank API(Cohere 등), no-op 구현 등을
이 계약으로 작성해 컨테이너에서 교체할 수 있다.
"""

from typing import List, Optional, Protocol, Tuple, runtime_checkable


@runtime_checkable
class Reranker(Protocol):
    """query-document 관련성 재순위화 계약."""

    async def rerank(
        self,
        query: str,
        documents: List[str],
        top_k: Optional[int] = None,
    ) -> List[Tuple[int, float]]:
        """관련성 점수를 계산해 [(원본_인덱스, 점수)]를 점수 내림차순으로 반환한다."""
        ...

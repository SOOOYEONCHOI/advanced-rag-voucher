"""
임베딩 프로바이더 인터페이스.

2026.07.16(sooyeon.choi) 추가 - 3단계 리팩토링: 인터페이스 도입
기준 구현: app/clients/embedding_client.py EmbeddingClient (vLLM)
임베딩 모델/서버 교체 시 이 계약을 만족하는 클라이언트를 작성해
컨테이너(app/core/container.py)에서 교체하면 된다.
"""

from typing import List, Protocol, runtime_checkable


@runtime_checkable
class EmbeddingProvider(Protocol):
    """질의/문서 임베딩 계약."""

    async def embed_query(self, query: str) -> List[float]:
        """검색 질의 1건 임베딩 (모델별 instruct prefix 처리 포함)."""
        ...

    async def embed_queries(self, queries: List[str]) -> List[List[float]]:
        """복수 질의 배치 임베딩."""
        ...

    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """문서(passage) 배치 임베딩 (인덱싱용)."""
        ...

    async def health_check(self) -> bool:
        ...

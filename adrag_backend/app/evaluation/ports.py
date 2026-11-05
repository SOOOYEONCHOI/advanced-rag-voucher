"""평가 시스템 추상 인터페이스 (Ports).

metrics/dataset/runner 모듈은 이 인터페이스에만 의존한다.
기존 adrag 코드(app.graphs/app.clients 등)에 대한 직접 의존은 adapters/ 에서만 허용 —
차후 별도 서비스로 분리 시 adapters만 HTTP 클라이언트 구현으로 교체하면 된다.
(reference app/evaluation/ports.py 이식)
"""

from typing import Any, Dict, List, Optional, Protocol, Tuple

# (chunk_id, score, payload) — retrieval_engine.py의 SearchResult와 동일 구조
SearchHit = Tuple[str, float, Dict[str, Any]]


class RetrieverPort(Protocol):
    """채널별 독립 검색 + 운영과 동일한 방식의 병합 검색."""

    async def search_channel(
        self,
        channel: str,               # "dense" | "kiwi_bm25" | "bm42"
        query: str,
        top_k: int,
        collection_name: str,
    ) -> List[SearchHit]:
        ...

    async def search_rrf(
        self,
        query: str,
        top_k: int,
        collection_name: str,
        profile: Optional[str] = None,
    ) -> List[SearchHit]:
        """운영 설정(retrieval_engine: qdrant_hybrid|legacy)과 동일한 병합 방식으로 검색한다."""
        ...


class RerankerPort(Protocol):
    async def rerank(
        self,
        query: str,
        hits: List[SearchHit],
        top_k: int,
    ) -> List[SearchHit]:
        """검색 결과를 재순위화하여 반환한다."""
        ...


class LLMPort(Protocol):
    async def chat(
        self,
        messages: List[Dict[str, str]],
        *,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        backend: str = "vllm",       # "vllm" | "openai"
    ) -> str:
        """메시지를 보내고 응답 텍스트를 반환한다."""
        ...


class EmbedderPort(Protocol):
    async def embed(self, texts: List[str]) -> List[List[float]]:
        ...


class ChunkStorePort(Protocol):
    """지식베이스 청크 조회 (테스트셋 샘플링용)."""

    async def scroll_chunks(
        self,
        collection_name: str,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        """컬렉션의 모든 청크 payload를 반환한다 (chunk_id 포함)."""
        ...

class RagPipelinePort(Protocol):
    """RAG 전체 파이프라인 실행 (end-to-end 평가용)."""

    async def run(
        self,
        query: str,
        collection_name: str,
        retrieval_top_n: int = 10,
        rerank_top_k: int = 5,
    ) -> Dict[str, Any]:
        """반환: {answer, retrieved_chunks, reranked_chunks, final_context,
        context_chunks, citations, relevance_threshold, timing, usage, outcome_code}"""
        ...

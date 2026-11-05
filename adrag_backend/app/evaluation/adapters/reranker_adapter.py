"""리랭커 어댑터 — 기존 RerankerClient를 평가용 인터페이스(RerankerPort)로 래핑.

(reference app/evaluation/adapters/reranker_adapter.py 이식 — import 경로만 변경)
"""

from typing import List

from app.clients.reranker_client import RerankerClient
from app.core.config import get_settings
from app.evaluation.ports import SearchHit

_reranker_client: RerankerClient | None = None


def _get_client() -> RerankerClient:
    global _reranker_client
    if _reranker_client is None:
        _reranker_client = RerankerClient(get_settings())
    return _reranker_client


class EvalReranker:
    """RerankerPort 구현."""

    async def rerank(
        self,
        query: str,
        hits: List[SearchHit],
        top_k: int,
    ) -> List[SearchHit]:
        """검색 결과를 vLLM score API로 재순위화한다.

        RerankerClient.rerank()는 (원본_인덱스, 점수) 2-튜플만 반환하므로
        (chunk_id, score, payload)로 복원할 때 hits의 원본 인덱스로 매핑한다.
        """
        if not hits:
            return []
        documents = [payload.get("text", "") for _, _, payload in hits]
        reranked = await _get_client().rerank(query, documents, top_k=top_k)
        return [
            (hits[idx][0], score, hits[idx][2])
            for idx, score in reranked
        ]

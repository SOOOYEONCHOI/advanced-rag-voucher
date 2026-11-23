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
        # [AI+ 시험] NDCG@5 - 2) 임베딩 모델 및 Reranker 모델을 불러오는 코드 (Reranker 모델)
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
        # 2026.11.19(sooyeon.choi) 수정 - 운영 rerank 노드와 같은 입력으로 재랭킹
        #   기존: 본문만 보내고 같은 본문 중복 제거를 하지 않아, 검색·재정렬 평가의 NDCG@5가
        #   운영(전체 RAG 평가·일괄 질의)과 다르게 나왔다. 운영과 같이 본문 중복 제거 + [문서명]·[섹션] 접두를 쓴다.
        from app.graphs.nodes.rerank import _build_rerank_text
        from app.graphs.utils import dedup_chunks_by_text

        # [AI+ 시험] NDCG@5 - 4) 하이브리드 검색 결과를 Reranker 모델에 입력하여 질의와 문서 청크 간 관련도를 평가하고 검색 결과를 재정렬하는 코드
        chunks = dedup_chunks_by_text([
            {"chunk_id": chunk_id, "document_id": payload.get("document_id", ""),
             "text": payload.get("text", ""), "score": score, "metadata": payload}
            for chunk_id, score, payload in hits
        ])
        documents = [_build_rerank_text(chunk) for chunk in chunks]
        reranked = await _get_client().rerank(query, documents, top_k=top_k)
        return [
            (chunks[idx]["chunk_id"], score, chunks[idx]["metadata"])
            for idx, score in reranked
        ]

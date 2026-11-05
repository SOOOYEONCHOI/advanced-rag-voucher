"""청크 스토어 어댑터 — Qdrant scroll 기반 청크 조회 (ChunkStorePort 구현).

테스트셋 샘플링을 위해 컬렉션 전체 청크의 payload를 수집한다.
(reference app/evaluation/adapters/chunk_store_adapter.py 이식)
"""

import asyncio
from typing import Any, Dict, List

from app.graphs.nodes.retrieve import get_vector_repo


class EvalChunkStore:
    """ChunkStorePort 구현."""

    def __init__(self) -> None:
        self._client = get_vector_repo().client

    async def scroll_chunks(
        self,
        collection_name: str,
        limit: int = 5000,
    ) -> List[Dict[str, Any]]:
        """컬렉션의 청크 payload 목록을 반환한다 (chunk_id 포함, 벡터 제외)."""

        def _scroll_all() -> List[Dict[str, Any]]:
            chunks: List[Dict[str, Any]] = []
            offset = None
            while len(chunks) < limit:
                batch, offset = self._client.scroll(
                    collection_name=collection_name,
                    limit=min(500, limit - len(chunks)),
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
                for point in batch:
                    payload = dict(point.payload or {})
                    payload.setdefault("chunk_id", str(point.id))
                    chunks.append(payload)
                if offset is None:
                    break
            return chunks

        return await asyncio.to_thread(_scroll_all)

"""임베더 어댑터 — 답변 의미 유사도 계산용 (EmbedderPort 구현).

(reference app/evaluation/adapters/embedder_adapter.py 이식)
"""

from typing import List

from app.graphs.nodes.retrieve import get_embedding_client


class EvalEmbedder:
    """EmbedderPort 구현."""

    async def embed(self, texts: List[str]) -> List[List[float]]:
        return await get_embedding_client().embed_texts(texts)

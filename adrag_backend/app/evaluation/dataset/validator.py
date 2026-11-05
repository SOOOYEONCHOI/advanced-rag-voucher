"""Self-validation — 생성된 질문으로 실제 검색을 수행해 원본 청크의 순위를 확인한다.

미검출이어도 자동 반려하지 않는다 (검색기 약점 발견 가치가 있으므로
UI에서 경고 배지로 표시하고 담당자가 판단).
(reference app/evaluation/dataset/validator.py 이식 — import 경로만 변경)
"""

from typing import List, Optional

from app.evaluation.adapters.retrieval_adapter import EvalRetriever


async def self_validate(
    retriever: EvalRetriever,
    question: str,
    gold_chunk_ids: List[str],
    collection_name: str,
    top_k: int = 10,
) -> Optional[int]:
    """RRF 검색에서 gold 청크가 처음 등장하는 순위(1-based)를 반환한다. 미검출 시 None."""
    gold_set = set(gold_chunk_ids)
    hits = await retriever.search_rrf(question, top_k, collection_name)
    for rank, (chunk_id, _, _) in enumerate(hits, start=1):
        if chunk_id in gold_set:
            return rank
    return None

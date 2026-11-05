"""
리랭킹(rerank) 단계 평가기.

cross-encoder score 재정렬 후 순위 품질과 threshold 통과 여부를 확인한다.
check_relevance 엣지가 rerank score와 threshold로 분기하므로,
정답 chunk의 순위뿐 아니라 score가 threshold 이상인지도 함께 검증한다.
"""

from typing import Dict

from offline_evaluation.dataset.schema import GoldenRecord
from offline_evaluation.evaluators.base import (
    EvalResult,
    first_rank,
    hit_at_k,
    mrr,
    ndcg_at_k,
)

_SKIP_BEHAVIORS = {"guardrail", "permission_denied"}


def evaluate(
    record: GoldenRecord,
    result: EvalResult,
    k: int = 5,
) -> Dict:
    """rerank 단계 지표를 계산해 반환한다.

    Returns:
        skipped                 : True면 이 케이스는 rerank 평가 대상이 아님
        mrr                     : Mean Reciprocal Rank (0.0~1.0)
        ndcg_at_k               : nDCG@K (0.0~1.0)
        hit_at_k                : 정답 chunk가 rerank top-K 안에 있는지 (bool)
        evidence_rank           : 첫 번째 정답 chunk의 1-based 순위 (없으면 None)
        evidence_above_threshold: 정답 chunk 중 threshold 이상 score인 것이 하나라도 있는지
        top1_is_relevant        : rerank 1위가 정답 chunk인지 (bool)
        k                       : 평가 기준 K 값
        threshold               : 적용된 relevance_threshold
    """
    if record["expected_behavior"] in _SKIP_BEHAVIORS:
        return {"skipped": True, "reason": record["expected_behavior"]}

    relevant = {e["chunk_id"] for e in record["expected_evidence"]}
    reranked = result["reranked_chunks"]
    ranked_ids = [c["chunk_id"] for c in reranked]
    score_map: Dict[str, float] = {c["chunk_id"]: c["score"] for c in reranked}
    threshold = result["relevance_threshold_used"]

    if not relevant:
        return {
            "skipped": False,
            "mrr": None,
            "ndcg_at_k": None,
            "hit_at_k": None,
            "evidence_rank": None,
            "evidence_above_threshold": None,
            "top1_is_relevant": None,
            "k": k,
            "threshold": threshold,
            "note": "expected_evidence 없음 (unanswerable)",
        }

    above_threshold = any(
        score_map.get(cid, 0.0) >= threshold for cid in relevant
    )

    return {
        "skipped": False,
        "mrr": mrr(relevant, ranked_ids),
        "ndcg_at_k": ndcg_at_k(relevant, ranked_ids, k),
        "hit_at_k": hit_at_k(relevant, ranked_ids, k),
        "evidence_rank": first_rank(relevant, ranked_ids),
        "evidence_above_threshold": above_threshold,
        "top1_is_relevant": bool(ranked_ids) and ranked_ids[0] in relevant,
        "k": k,
        "threshold": threshold,
    }

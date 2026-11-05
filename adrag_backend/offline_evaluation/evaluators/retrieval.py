"""
검색(retrieve) 단계 평가기.

dense + sparse + RRF 조합이 정답 chunk를 충분히 회수하는지 확인한다.
rerank 이전 retrieved_chunks를 기준으로 평가한다.
"""

from typing import Dict

from offline_evaluation.dataset.schema import GoldenRecord
from offline_evaluation.evaluators.base import (
    EvalResult,
    first_rank,
    hit_at_k,
    mrr,
    ndcg_at_k,
    recall_at_k,
)

# guardrail/permission_denied는 retrieve 자체가 실행되지 않으므로 평가 제외
_SKIP_BEHAVIORS = {"guardrail", "permission_denied"}


def evaluate(
    record: GoldenRecord,
    result: EvalResult,
    k: int = 10,
) -> Dict:
    """retrieve 단계 지표를 계산해 반환한다.

    Returns:
        skipped        : True면 이 케이스는 retrieve 평가 대상이 아님
        recall_at_k    : 정답 chunk가 top-K 안에 몇 개 포함됐는지 (0.0~1.0)
        hit_at_k       : 정답 chunk가 top-K 안에 하나라도 있는지 (bool)
        evidence_count : top-K 안에 포함된 정답 chunk 수 (절대값)
        total_retrieved: 실제 검색된 전체 chunk 수
        evidence_rank  : top-K 내 첫 번째 정답 chunk의 1-based 순위
        mrr            : top-K 내 첫 번째 정답 chunk의 역순위
        ndcg_at_k      : 복수 정답 chunk를 반영한 nDCG@K
        top1_is_relevant: 검색 1위가 정답 chunk인지 여부
        k              : 평가 기준 K 값
    """
    if record["expected_behavior"] in _SKIP_BEHAVIORS:
        return {"skipped": True, "reason": record["expected_behavior"]}

    relevant = {e["chunk_id"] for e in record["expected_evidence"]}
    retrieved_ids = [c["chunk_id"] for c in result["retrieved_chunks"]]

    # unanswerable은 relevant가 비어 있으므로 recall/hit은 N/A
    if not relevant:
        return {
            "skipped": False,
            "recall_at_k": None,
            "hit_at_k": None,
            "evidence_count": 0,
            "total_retrieved": len(retrieved_ids),
            "evidence_rank": None,
            "mrr": None,
            "ndcg_at_k": None,
            "top1_is_relevant": None,
            "k": k,
            "note": "expected_evidence 없음 (unanswerable)",
        }

    top_k_ids = retrieved_ids[:k]
    return {
        "skipped": False,
        "recall_at_k": recall_at_k(relevant, retrieved_ids, k),
        "hit_at_k": hit_at_k(relevant, retrieved_ids, k),
        "evidence_count": len(relevant & set(top_k_ids)),
        "total_retrieved": len(retrieved_ids),
        "evidence_rank": first_rank(relevant, top_k_ids),
        "mrr": mrr(relevant, top_k_ids),
        "ndcg_at_k": ndcg_at_k(relevant, top_k_ids, k),
        "top1_is_relevant": bool(top_k_ids) and top_k_ids[0] in relevant,
        "k": k,
    }

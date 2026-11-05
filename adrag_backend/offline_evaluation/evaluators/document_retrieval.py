"""문서 단위 검색 보조 지표.

청크 단위 지표가 공식 KPI이며, 이 지표는 관련 문서는 찾았지만 정확한
근거 청크를 놓친 경우를 구분하기 위한 진단용이다.
"""

from typing import Dict

from offline_evaluation.dataset.schema import GoldenRecord
from offline_evaluation.evaluators.base import EvalResult, first_rank, hit_at_k, recall_at_k


_SKIP_BEHAVIORS = {"guardrail", "permission_denied"}


def evaluate(record: GoldenRecord, result: EvalResult, k: int = 10) -> Dict:
    if record["expected_behavior"] in _SKIP_BEHAVIORS:
        return {"skipped": True, "reason": record["expected_behavior"]}

    relevant = {e["document_id"] for e in record["expected_evidence"]}
    ranked = [c["document_id"] for c in result["retrieved_chunks"]]
    # 같은 문서의 여러 청크가 검색된 경우 문서 순위는 최초 등장만 유지한다.
    ranked = list(dict.fromkeys(ranked))

    if not relevant:
        return {
            "skipped": False,
            "recall_at_k": None,
            "hit_at_k": None,
            "mrr": None,
            "first_rank": None,
            "k": k,
            "note": "expected_evidence 없음 (unanswerable)",
        }

    rank = first_rank(relevant, ranked)
    return {
        "skipped": False,
        "recall_at_k": recall_at_k(relevant, ranked, k),
        "hit_at_k": hit_at_k(relevant, ranked, k),
        "mrr": 1.0 / rank if rank else 0.0,
        "first_rank": rank,
        "k": k,
    }

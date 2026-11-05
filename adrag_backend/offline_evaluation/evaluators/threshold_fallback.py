"""
Threshold / Fallback 흐름 평가기.

check_relevance → fallback_handler → check_fallback_retry 흐름을 평가한다.
expected_behavior를 기준으로 파이프라인이 올바르게 분기했는지 확인한다.

판정 기준:
  answer          : 답변이 생성됐어야 함 → 없으면 false_fallback
  not_enough_info : 거절 답변이어야 함   → 억지 답변 생성 시 false_answer
  guardrail       : 가드레일 차단이어야 함 → should_retrieve=False 확인
  permission_denied: 권한 오류로 차단되어야 함 → error 필드 확인
"""

from typing import Dict

from offline_evaluation.dataset.schema import GoldenRecord
from offline_evaluation.evaluators.base import EvalResult


def evaluate(record: GoldenRecord, result: EvalResult) -> Dict:
    """threshold/fallback 흐름 지표를 계산해 반환한다.

    Returns:
        correct        : 파이프라인이 expected_behavior대로 동작했는지
        false_fallback : answer 케이스인데 답변이 없는 경우 (True = 오류)
        false_answer   : not_enough_info 케이스인데 답변이 생성된 경우 (True = 오류)
        retry_count    : 실제 retry 횟수
        retry_recovered: retry 후 정답 evidence를 회수했는지 (retry 케이스만)
    """
    behavior = record["expected_behavior"]
    has_answer = bool(result.get("generated_answer"))
    retry_count = result.get("retry_count", 0)

    metrics: Dict = {
        "correct": False,
        "false_fallback": False,
        "false_answer": False,
        "retry_count": retry_count,
        "retry_recovered": None,  # retry가 없으면 N/A
    }

    if behavior == "answer":
        metrics["false_fallback"] = not has_answer
        metrics["correct"] = has_answer

    elif behavior == "not_enough_info":
        metrics["false_answer"] = has_answer
        metrics["correct"] = not has_answer

    elif behavior == "guardrail":
        # should_retrieve=False이고 답변이 없어야 정상
        blocked = result.get("should_retrieve") is False and not has_answer
        metrics["correct"] = blocked

    elif behavior == "permission_denied":
        # error 필드에 권한 오류가 기록되고 답변이 없어야 정상
        has_permission_error = bool(result.get("error")) and not has_answer
        metrics["correct"] = has_permission_error

    # retry 후 evidence 회수 여부 (retry가 발생한 케이스만 의미 있음)
    if retry_count > 0:
        relevant = {e["chunk_id"] for e in record["expected_evidence"]}
        if relevant:
            reranked_ids = {c["chunk_id"] for c in result.get("reranked_chunks", [])}
            metrics["retry_recovered"] = bool(relevant & reranked_ids)

    return metrics

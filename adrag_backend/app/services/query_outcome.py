"""RAG query outcome helpers."""

from typing import Any, Mapping


VALID_QUERY_OUTCOMES = frozenset({
    "success",
    "no_context",
    "guardrail_blocked",
    "validation_error",
    "retrieval_error",
    "llm_error",
    "system_error",
    "cancelled",
    "unknown",
})


# 2026.06.19(sooyeon.choi) 추가 - 파이프라인 최종 상태의 통계 결과 코드 확정
def resolve_query_outcome(result: Mapping[str, Any]) -> str:
    explicit = result.get("outcome_code")
    if explicit in VALID_QUERY_OUTCOMES:
        return explicit
    if result.get("should_retrieve") is False:
        return "guardrail_blocked"
    if result.get("generated_answer") and result.get("final_context"):
        return "success"
    if result.get("should_retrieve") and not result.get("final_context"):
        return "no_context"
    return "unknown"

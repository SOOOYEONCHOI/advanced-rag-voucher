"""Query outcome classification tests."""

import pytest

from app.services.query_outcome import resolve_query_outcome


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        ({"outcome_code": "validation_error"}, "validation_error"),
        ({"outcome_code": "retrieval_error"}, "retrieval_error"),
        ({"outcome_code": "llm_error"}, "llm_error"),
        ({"should_retrieve": False, "generated_answer": "차단"}, "guardrail_blocked"),
        (
            {
                "should_retrieve": True,
                "generated_answer": "정상 답변",
                "final_context": "문서 컨텍스트",
            },
            "success",
        ),
        (
            {
                "should_retrieve": True,
                "generated_answer": "관련 문서 없음",
                "final_context": None,
            },
            "no_context",
        ),
        ({"outcome_code": "invalid-code"}, "unknown"),
    ],
)
def test_resolve_query_outcome(result, expected):
    # 2026.06.19(sooyeon.choi) 추가 - 일반 질의 종료 유형별 결과 코드 검증
    assert resolve_query_outcome(result) == expected

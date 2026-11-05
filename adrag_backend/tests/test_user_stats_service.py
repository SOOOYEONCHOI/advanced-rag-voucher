"""User statistics service response tests."""

import sys
import types

# 2026.06.19(sooyeon.choi) 추가 - 통계 서비스 단위 테스트의 설정 의존성 격리
config_module = types.ModuleType("app.core.config")
config_module.get_settings = lambda: types.SimpleNamespace(
    instance_dir="",
    model_pricing_usd={},
    stats_stale_days=90,
    stats_dead_days=60,
)
sys.modules["app.core.config"] = config_module

from app.models.stats_models import (
    FlaggedQueryListResponse,
    KeywordListResponse,
    TopDocumentListResponse,
    UserSummaryResponse,
)
from app.services.stats_service import StatsService


class _FakeStatsRepository:
    def count_queries(self, *_args):
        return 4

    def count_active_days(self, *_args):
        return 2

    def feedback_counts(self, *_args):
        return {"likes": 3, "dislikes": 1, "responded": 4}

    def success_counts(self, *_args):
        return {
            "success_count": 3,
            "failure_count": 1,
            "completed_count": 4,
        }

    def top_keywords(self, *_args):
        return [
            {"keyword": "안전", "count": 4},
            {"keyword": "매뉴얼", "count": 2},
        ]

    def top_cited_documents(self, *_args):
        return [{
            "document_id": "doc-1",
            "document_name": "안전.pdf",
            "collection_id": 1,
            "collection_name": "안전 문서",
            "citation_count": 3,
            "last_cited_at": "2026-06-19T10:00:00+09:00",
        }]

    def flagged_queries(self, *_args):
        return [{
            "log_id": 1,
            "user_id": "user01",
            "query_text": "없는 매뉴얼",
            "outcome_code": "no_context",
            "feedback": "dislike",
            "created_at": "2026-06-19T10:00:00+09:00",
            "model_id": "local",
        }]


def _service() -> StatsService:
    service = object.__new__(StatsService)
    service.repo = _FakeStatsRepository()
    return service


def test_user_summary_matches_response_contract():
    # 2026.06.19(sooyeon.choi) 추가 - 사용자 요약 응답 모델 검증
    response = _service().get_user_summary("7", "user01")
    validated = UserSummaryResponse.model_validate(response)

    assert validated.query_count.value == 4
    assert validated.satisfaction.value_pct == 75.0
    assert validated.success_rate.value_pct == 75.0
    assert validated.success_rate.failure_count == 1


def test_user_list_sections_match_response_contract():
    service = _service()

    # 2026.06.19(sooyeon.choi) 추가 - 사용자 목록 구역별 응답 계약 검증
    keywords = KeywordListResponse(
        items=service.get_top_keywords("7", 5, "user01")
    )
    documents = TopDocumentListResponse(
        items=service.get_top_documents("7", 5, "user01")
    )
    flagged = FlaggedQueryListResponse(
        items=service.get_flagged_queries("7", 10, "user01")
    )

    assert keywords.items[0].ratio_pct == 100.0
    assert keywords.items[1].ratio_pct == 50.0
    assert documents.items[0].rank == 1
    assert flagged.items[0].issue_types == [
        "no_context",
        "negative_feedback",
    ]
    assert flagged.items[0].issue_label == "검색 실패"

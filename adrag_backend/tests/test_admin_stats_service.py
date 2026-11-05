"""Admin statistics service response tests."""

import sys
import types

# 2026.06.19(sooyeon.choi) 추가 - 관리자 통계 서비스 테스트 설정 격리
config_module = types.ModuleType("app.core.config")
config_module.get_settings = lambda: types.SimpleNamespace(
    instance_dir="",
    model_pricing_usd={},
    stats_stale_days=90,
    stats_dead_days=60,
)
sys.modules["app.core.config"] = config_module

from app.models.stats_models import (
    AdminFlaggedQueryListResponse,
    AdminSummaryResponse,
    DepartmentUsageResponse,
    DepartmentWeeklyTrendResponse,
    DocumentHealthResponse,
    KeywordListResponse,
    TopDocumentListResponse,
    TopUserListResponse,
    UsageTrendResponse,
)
from app.services.stats_service import StatsService


class _FakeAdminStatsRepository:
    def count_queries(self, *_args):
        return 10

    def feedback_counts(self, *_args):
        return {"likes": 8, "dislikes": 2, "responded": 10}

    def sum_cost(self, *_args):
        return {"total": 2.5, "daily_avg": 0.0}

    def count_problem_queries(self, *_args):
        return 3

    def daily_usage_trend(self, *_args):
        return []

    def top_keywords(self, *_args):
        return [{"keyword": "안전", "count": 5}]

    def top_cited_documents(self, *_args):
        return [{
            "document_id": "doc-1",
            "document_name": "안전.pdf",
            "collection_id": 1,
            "collection_name": "안전 문서",
            "citation_count": 4,
            "last_cited_at": "2026-06-19T10:00:00+09:00",
        }]

    def count_admin_flagged_queries(self, *_args):
        return 21

    def admin_flagged_queries(self, *_args):
        return [{
            "log_id": 11,
            "user_id": "user01",
            "user_name": "김안전",
            "department": "안전보건팀",
            "query_text": "없는 문서",
            "outcome_code": "no_context",
            "feedback": None,
            "model_id": "local",
            "created_at": "2026-06-19T10:00:00+09:00",
        }]

    def department_usage(self, *_args):
        return [{
            "department": "안전보건팀",
            "query_count": 3,
            "satisfaction_pct": 100.0,
            "feedback_count": 2,
        }, {
            "department": "미지정",
            "query_count": 1,
            "satisfaction_pct": None,
            "feedback_count": 0,
        }]

    def department_weekly_trend(self, _weeks):
        return {
            "weeks": [{
                "key": "2026-W25",
                "label": "6월 3주",
                "start_date": "2026-06-15",
                "end_date": "2026-06-21",
            }],
            "series": [{
                "department": "안전보건팀",
                "values": [3],
            }],
        }

    def top_users_by_activity(self, *_args):
        return [{
            "user_id": "user01",
            "user_name": "김안전",
            "department": "안전보건팀",
            "query_count": 3,
            "satisfaction_pct": 100.0,
            "feedback_count": 2,
        }]

    def document_health_summary(self, *_args):
        return {
            "review_overdue_count": 1,
            "uncited_count": 2,
            "total_document_count": 5,
        }

    def count_document_health_items(self, *_args):
        return 2

    def document_health_items(self, *_args):
        return [{
            "document_id": "doc-1",
            "document_name": "안전.pdf",
            "collection_id": 1,
            "collection_name": "안전 문서",
            "health_status": "review_overdue_and_uncited",
            "last_cited_at": None,
            "citation_reference_at": "2026-01-01T09:00:00+09:00",
            "content_updated_at": "2026-01-01T09:00:00+09:00",
            "review_due_at": "2026-05-01T00:00:00+09:00",
        }]


def _service() -> StatsService:
    service = object.__new__(StatsService)
    service.repo = _FakeAdminStatsRepository()
    service._settings = config_module.get_settings()
    return service


def test_admin_summary_and_basic_sections_match_contract():
    service = _service()

    # 2026.06.19(sooyeon.choi) 추가 - 관리자 기본 구역 응답 계약 검증
    summary = AdminSummaryResponse.model_validate(
        service.get_admin_summary("7")
    )
    trend = UsageTrendResponse.model_validate(
        service.get_admin_usage_trend("7")
    )
    keywords = KeywordListResponse(
        items=service.get_top_keywords("7", 5)
    )
    documents = TopDocumentListResponse(
        items=service.get_top_documents("7", 5)
    )

    assert summary.query_count.value == 10
    assert summary.satisfaction.value_pct == 80.0
    assert summary.cost.total_usd == 2.5
    assert summary.flagged_queries.value == 3
    assert len(trend.items) == 7
    assert keywords.items[0].rank == 1
    assert documents.items[0].citation_count == 4


def test_admin_flagged_queries_include_user_and_pagination():
    # 2026.06.19(sooyeon.choi) 추가 - 관리자 주의 질의 사용자 정보·페이지 검증
    response = AdminFlaggedQueryListResponse.model_validate(
        _service().get_admin_flagged_queries("7", page=2, page_size=10)
    )

    assert response.items[0].user_name == "김안전"
    assert response.items[0].department == "안전보건팀"
    assert response.items[0].issue_label == "검색 실패"
    assert response.pagination.page == 2
    assert response.pagination.total_count == 21
    assert response.pagination.total_pages == 3


def test_admin_organization_sections_match_contract():
    service = _service()

    # 2026.06.19(sooyeon.choi) 추가 - 관리자 조직 통계 응답 계약 검증
    departments = DepartmentUsageResponse.model_validate(
        service.get_department_usage("7")
    )
    weekly = DepartmentWeeklyTrendResponse.model_validate(
        service.get_department_weekly_trend(1)
    )
    users = TopUserListResponse(
        items=service.get_top_users("7", 10)
    )

    assert departments.total_query_count == 4
    assert departments.items[0].query_ratio_pct == 75.0
    assert departments.items[1].satisfaction_pct is None
    assert weekly.weeks[0].start_date == "2026-06-15"
    assert weekly.series[0].values == [3]
    assert users.items[0].rank == 1
    assert users.items[0].feedback_count == 2


def test_admin_document_health_matches_contract():
    # 2026.06.19(sooyeon.choi) 추가 - 관리자 문서 상태 요약·목록·페이지 계약 검증
    response = DocumentHealthResponse.model_validate(
        _service().get_document_health(page=1, page_size=20)
    )

    assert response.summary.review_overdue_count == 1
    assert response.summary.uncited_count == 2
    assert response.summary.total_document_count == 5
    assert response.thresholds.uncited_days == 60
    assert response.items[0].health_status == "review_overdue_and_uncited"
    assert response.items[0].days_since_last_citation > 60
    assert response.pagination.total_count == 2

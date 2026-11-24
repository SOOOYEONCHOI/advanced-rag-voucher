"""Statistics dashboard HTTP API response tests."""

import sys
import types

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

# Keep route tests independent from environment-file and database settings.
config_module = types.ModuleType("app.core.config")
config_module.get_settings = lambda: types.SimpleNamespace(
    instance_dir="",
    model_pricing_usd={},
    stats_stale_days=90,
    stats_dead_days=60,
)
sys.modules["app.core.config"] = config_module

document_repository_module = types.ModuleType(
    "app.repositories.document_repository"
)
document_repository_module.DocumentRepository = object
sys.modules[
    "app.repositories.document_repository"
] = document_repository_module

stats_repository_module = types.ModuleType("app.repositories.stats_repository")
stats_repository_module.StatsRepository = type(
    "StatsRepository",
    (),
    {"__init__": lambda self, *_args, **_kwargs: None},
)
sys.modules["app.repositories.stats_repository"] = stats_repository_module

from app.routes import admin_stats, user_stats
from app.utils.security import get_current_admin, get_current_user


PERIOD = {
    "value": "7",
    "start_at": "2026-06-16T00:00:00+09:00",
    "end_at": "2026-06-22T23:59:59+09:00",
    "timezone": "Asia/Seoul",
}


class _FakeStatsService:
    def __init__(self):
        self.calls = []

    def get_user_summary(self, period, user_id):
        self.calls.append(("get_user_summary", period, user_id))
        return {
            "period": PERIOD,
            "query_count": {
                "value": 4,
                "previous_value": 2,
                "change_count": 2,
                "change_pct": 100.0,
            },
            "active_days": {
                "value": 3,
                "period_days": 7,
                "previous_value": 2,
                "change_count": 1,
            },
            "satisfaction": {
                "value_pct": 75.0,
                "previous_value_pct": 50.0,
                "change_point": 25.0,
                "feedback_count": 4,
                "like_count": 3,
                "dislike_count": 1,
            },
            "success_rate": {
                "value_pct": 75.0,
                "previous_value_pct": 50.0,
                "change_point": 25.0,
                "success_count": 3,
                "failure_count": 1,
            },
        }

    def get_admin_summary(self, period):
        self.calls.append(("get_admin_summary", period))
        return {
            "period": PERIOD,
            "query_count": {
                "value": 10,
                "previous_value": 8,
                "change_count": 2,
                "change_pct": 25.0,
            },
            "satisfaction": {
                "value_pct": 80.0,
                "previous_value_pct": 75.0,
                "change_point": 5.0,
                "feedback_count": 10,
                "like_count": 8,
                "dislike_count": 2,
            },
            "cost": {
                "total_usd": 2.5,
                "daily_average_usd": 0.36,
                "previous_total_usd": 2.0,
                "change_usd": 0.5,
                "change_pct": 25.0,
            },
            "flagged_queries": {
                "value": 3,
                "previous_value": 1,
                "change_count": 2,
                "change_pct": 200.0,
            },
        }

    def get_user_usage_trend(self, period, user_id):
        self.calls.append(("get_user_usage_trend", period, user_id))
        return self._usage_trend()

    def get_admin_usage_trend(self, period):
        self.calls.append(("get_admin_usage_trend", period))
        return self._usage_trend()

    @staticmethod
    def _usage_trend():
        return {
            "period": PERIOD,
            "items": [{
                "date": "2026-06-22",
                "query_count": 4,
                "cost_usd": 0.2,
            }],
            "total_query_count": 4,
            "total_cost_usd": 0.2,
        }

    def get_top_keywords(self, period, limit, user_id=None):
        self.calls.append(("get_top_keywords", period, limit, user_id))
        return [{
            "rank": 1,
            "keyword": "안전",
            "count": 4,
            "ratio_pct": 100.0,
        }]

    def get_top_documents(self, period, limit, user_id=None):
        self.calls.append(("get_top_documents", period, limit, user_id))
        return [{
            "rank": 1,
            "document_id": "doc-1",
            "document_name": "안전.pdf",
            "collection_id": 1,
            "collection_name": "안전 문서",
            "citation_count": 3,
            "last_cited_at": "2026-06-22T10:00:00+09:00",
        }]

    def get_flagged_queries(self, period, limit, user_id):
        self.calls.append(("get_flagged_queries", period, limit, user_id))
        return [{
            "log_id": 1,
            "query_text": "없는 문서",
            "issue_types": ["no_context"],
            "issue_label": "검색 실패",
            "outcome_code": "no_context",
            "feedback": None,
            "model_id": "local",
            "created_at": "2026-06-22T10:00:00+09:00",
        }]

    def get_admin_flagged_queries(self, period, page, page_size):
        self.calls.append(
            ("get_admin_flagged_queries", period, page, page_size)
        )
        return {
            "items": [{
                "log_id": 1,
                "query_text": "없는 문서",
                "issue_types": ["no_context"],
                "issue_label": "검색 실패",
                "outcome_code": "no_context",
                "feedback": None,
                "model_id": "local",
                "created_at": "2026-06-22T10:00:00+09:00",
                "user_id": "user01",
                "user_name": "홍길동",
                "department": "안전보건팀",
            }],
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total_count": 1,
                "total_pages": 1,
            },
        }

    def get_department_usage(self, period):
        self.calls.append(("get_department_usage", period))
        return {
            "items": [{
                "department": "안전보건팀",
                "query_count": 4,
                "query_ratio_pct": 100.0,
                "satisfaction_pct": 75.0,
                "feedback_count": 4,
            }],
            "total_query_count": 4,
        }

    def get_department_weekly_trend(self, weeks):
        self.calls.append(("get_department_weekly_trend", weeks))
        return {
            "weeks": [{
                "key": "2026-W26",
                "label": "6월 4주",
                "start_date": "2026-06-22",
                "end_date": "2026-06-28",
            }],
            "series": [{
                "department": "안전보건팀",
                "values": [4],
            }],
        }

    def get_top_users(self, period, limit):
        self.calls.append(("get_top_users", period, limit))
        return [{
            "rank": 1,
            "user_id": "user01",
            "user_name": "홍길동",
            "department": "안전보건팀",
            "query_count": 4,
            "satisfaction_pct": 75.0,
            "feedback_count": 4,
        }]

    def get_document_health(self, page, page_size):
        self.calls.append(("get_document_health", page, page_size))
        return {
            "summary": {
                "review_overdue_count": 1,
                "uncited_count": 2,
                "total_document_count": 5,
            },
            "thresholds": {"uncited_days": 60},
            "items": [{
                "document_id": "doc-1",
                "document_name": "안전.pdf",
                "collection_id": 1,
                "collection_name": "안전 문서",
                "health_status": "review_overdue_and_uncited",
                "last_cited_at": None,
                "days_since_last_citation": 90,
                "content_updated_at": "2026-01-01T09:00:00+09:00",
                "review_due_at": "2026-05-01T00:00:00+09:00",
            }],
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total_count": 1,
                "total_pages": 1,
            },
        }


@pytest.fixture
def stats_api(monkeypatch):
    fake_stats = _FakeStatsService()
    monkeypatch.setattr(user_stats, "_stats", fake_stats)
    monkeypatch.setattr(admin_stats, "_stats", fake_stats)

    app = FastAPI()
    app.include_router(user_stats.router, prefix="/api")
    app.include_router(admin_stats.router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": "user01",
        "user_name": "홍길동",
        "token_type": "user_access",
    }
    app.dependency_overrides[get_current_admin] = lambda: {
        "admin_id": "admin",
        "is_superadmin": False,
    }

    with TestClient(app) as client:
        yield client, fake_stats


@pytest.mark.parametrize(
    ("path", "top_level_keys"),
    [
        (
            "/api/stats/me/summary?period=7",
            {"period", "query_count", "active_days", "satisfaction", "success_rate"},
        ),
        (
            "/api/stats/me/usage-trend?period=7",
            {"period", "items", "total_query_count", "total_cost_usd"},
        ),
        ("/api/stats/me/top-keywords?period=7&limit=5", {"items"}),
        ("/api/stats/me/top-documents?period=7&limit=5", {"items"}),
        ("/api/stats/me/flagged-queries?period=7&limit=10", {"items"}),
    ],
)
def test_user_dashboard_sections_return_expected_contract(
    stats_api, path, top_level_keys
):
    client, _ = stats_api

    response = client.get(path)

    assert response.status_code == 200
    assert set(response.json()) == top_level_keys


def test_user_dashboard_uses_authenticated_user_id(stats_api):
    client, fake_stats = stats_api

    client.get("/api/stats/me/summary")
    client.get("/api/stats/me/top-keywords")

    assert ("get_user_summary", "7", "user01") in fake_stats.calls
    assert ("get_top_keywords", "7", 5, "user01") in fake_stats.calls


@pytest.mark.parametrize(
    ("path", "top_level_keys"),
    [
        (
            "/api/admin/stats/summary?period=7",
            {"period", "query_count", "satisfaction", "cost", "flagged_queries"},
        ),
        (
            "/api/admin/stats/usage-trend?period=7",
            {"period", "items", "total_query_count", "total_cost_usd"},
        ),
        ("/api/admin/stats/top-keywords?period=7&limit=5", {"items"}),
        ("/api/admin/stats/top-documents?period=7&limit=5", {"items"}),
        (
            "/api/admin/stats/flagged-queries?period=7&page=1&page_size=20",
            {"items", "pagination"},
        ),
        ("/api/admin/stats/departments?period=7", {"items", "total_query_count"}),
        (
            "/api/admin/stats/departments/weekly-trend?weeks=4",
            {"weeks", "series"},
        ),
        ("/api/admin/stats/top-users?period=7&limit=10", {"items"}),
        (
            "/api/admin/stats/document-health?page=1&page_size=20",
            {"summary", "thresholds", "items", "pagination"},
        ),
    ],
)
def test_admin_dashboard_sections_return_expected_contract(
    stats_api, path, top_level_keys
):
    client, _ = stats_api

    response = client.get(path)

    assert response.status_code == 200
    assert set(response.json()) == top_level_keys


@pytest.mark.parametrize(
    "path",
    [
        "/api/stats/me/summary?period=invalid",
        "/api/stats/me/top-keywords?limit=21",
        "/api/admin/stats/flagged-queries?page=0",
        "/api/admin/stats/departments/weekly-trend?weeks=13",
    ],
)
def test_dashboard_query_validation_returns_422(stats_api, path):
    client, _ = stats_api

    assert client.get(path).status_code == 422


def test_user_and_admin_dashboard_reject_wrong_token_type(monkeypatch):
    app = FastAPI()
    app.include_router(user_stats.router, prefix="/api")
    app.include_router(admin_stats.router, prefix="/api")

    def fake_decode(token):
        if token == "user-token":
            return {"sub": "user01", "type": "user_access"}
        return {"sub": "admin", "type": "admin_access"}

    monkeypatch.setattr("app.utils.security.decode_access_token", fake_decode)

    with TestClient(app) as client:
        user_to_admin = client.get(
            "/api/admin/stats/summary",
            headers={"Authorization": "Bearer user-token"},
        )
        admin_to_user = client.get(
            "/api/stats/me/summary",
            headers={"Authorization": "Bearer admin-token"},
        )

    assert user_to_admin.status_code == 401
    assert admin_to_user.status_code == 401

"""Query log repository tests."""

import json
import logging
import sys
import types
from datetime import datetime, timedelta, timezone

import pytest

# 2026.06.19(sooyeon.choi) 추가 - Repository 단위 테스트의 설정·로깅 의존성 격리
config_module = types.ModuleType("app.core.config")
config_module.get_settings = lambda: types.SimpleNamespace(instance_dir="")
sys.modules["app.core.config"] = config_module

log_module = types.ModuleType("app.utils.log.log")


class _TestLoggingLogger:
    # 2026.07.16(sooyeon.choi) 수정 - named logger 지원 API 변경 반영 (B16)
    def getLogger(self, name=None):
        return logging.getLogger("test.query_log")


log_module.LoggingLogger = _TestLoggingLogger
sys.modules["app.utils.log.log"] = log_module

from app.repositories import database
from app.repositories import stats_repository as stats_repository_module
from app.models.data_models import DocumentMetadata, DocumentStatus
from app.repositories.document_repository import DocumentRepository
from app.repositories.query_log_repository import QueryLogRepository
from app.repositories.stats_repository import StatsRepository


@pytest.fixture(autouse=True)
def reset_database_singletons():
    # 2026.06.19(sooyeon.choi) 추가 - 테스트별 DatabaseManager 싱글톤 격리
    database._db_manager = None
    database.DatabaseManager._instance = None
    yield
    manager = database.DatabaseManager._instance
    if manager is not None:
        manager.close_all_connections()
    database._db_manager = None
    database.DatabaseManager._instance = None


def test_log_query_stores_outcome_answer_and_snapshots(tmp_path):
    db_path = str(tmp_path / "query-log.db")
    repo = QueryLogRepository()
    repo.db.execute_update(
        """
        INSERT INTO tb_users (user_id, user_pwd, user_name, department_name)
        VALUES (?, ?, ?, ?)
        """,
        ("user01", "hash", "사용자", "안전보건팀"),
    )
    collection_id = repo.db.execute_query(
        "SELECT collection_id FROM tb_collections WHERE qdrant_name='test_collection'"
    )
    if collection_id:
        resolved_collection_id = collection_id[0]["collection_id"]
    else:
        with repo.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO tb_collections
                    (display_name, qdrant_name, description, created_by)
                VALUES (?, ?, '', ?)
                RETURNING collection_id
                """,
                ("테스트 컬렉션", "test_collection", "user01"),
            )
            resolved_collection_id = cursor.fetchone()["collection_id"]

    # 2026.06.19(sooyeon.choi) 추가 - 정상 결과와 자동 스냅샷 저장 검증
    log_id = repo.log_query(
        query_text="안전 기준을 알려줘",
        user_id="user01",
        collection_id=resolved_collection_id,
        answer_text="안전 기준 답변",
        context_text=["첫 번째 컨텍스트", "두 번째 컨텍스트"],
        context_meta=[
            {"citation_no": 1, "chunk_id": "chunk-1"},
            {"citation_no": 2, "chunk_id": "chunk-2"},
        ],
        response_time_s=1.256,
        response_time_ms=1250.126,
        answer_generated=True,
        outcome_code="success",
        extracted_keywords=["안전", "기준"],
    )

    row = repo.db.execute_query(
        """
        SELECT answer_text, context_text, context_meta,
               response_time_s, response_time_ms,
               outcome_code, department_snapshot,
               collection_name_snapshot, extracted_keywords
        FROM tb_query_logs
        WHERE log_id = ?
        """,
        (log_id,),
    )[0]
    columns = [
        column["column_name"]
        for column in repo.db.execute_query(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'tb_query_logs' ORDER BY ordinal_position"
        )
    ]
    answer_index = columns.index("answer_text")
    assert columns[answer_index:answer_index + 5] == [
        "answer_text",
        "context_text",
        "context_meta",
        "response_time_s",
        "response_time_ms",
    ]
    assert row["answer_text"] == "안전 기준 답변"
    assert json.loads(row["context_text"]) == ["첫 번째 컨텍스트", "두 번째 컨텍스트"]
    assert json.loads(row["context_meta"]) == [
        {"citation_no": 1, "chunk_id": "chunk-1"},
        {"citation_no": 2, "chunk_id": "chunk-2"},
    ]
    assert row["response_time_s"] == 1.26
    assert row["response_time_ms"] == 1250.13
    assert row["outcome_code"] == "success"
    assert row["department_snapshot"] == "안전보건팀"
    assert row["collection_name_snapshot"] == "테스트 컬렉션"
    assert row["extracted_keywords"] == '["안전", "기준"]'
    history = repo.get_history(user_id="user01")[0]
    assert history["outcome_code"] == "success"
    assert history["context_text"] == ["첫 번째 컨텍스트", "두 번째 컨텍스트"]
    assert history["context_meta"][0]["citation_no"] == 1
    assert history["response_time_s"] == 1.26
    assert history["response_time_ms"] == 1250.13
    assert history["department_snapshot"] == "안전보건팀"
    assert history["collection_name_snapshot"] == "테스트 컬렉션"


def test_store_citations_deduplicates_same_document(tmp_path):
    db_path = str(tmp_path / "citations.db")
    repo = QueryLogRepository()
    repo.db.execute_update(
        """
        INSERT INTO tb_users (user_id, user_pwd, user_name)
        VALUES (?, ?, ?)
        """,
        ("user01", "hash", "사용자"),
    )
    log_id = repo.log_query(
        query_text="문서 질의",
        user_id="user01",
        answer_generated=True,
        outcome_code="success",
    )
    citations = [
        {
            "document_id": "doc-1",
            "document_name": "문서.pdf",
            "collection_name_snapshot": "일반",
        },
        {
            "document_id": "doc-1",
            "document_name": "문서.pdf",
            "collection_name_snapshot": "일반",
        },
    ]

    # 2026.06.19(sooyeon.choi) 추가 - 배치 내부와 반복 호출의 문서 중복 방지 검증
    repo.store_citations(log_id, citations)
    repo.store_citations(log_id, citations)

    rows = repo.db.execute_query(
        """
        SELECT document_id, collection_name_snapshot
        FROM tb_query_citations
        WHERE log_id = ?
        """,
        (log_id,),
    )
    assert len(rows) == 1
    assert rows[0]["document_id"] == "doc-1"
    assert rows[0]["collection_name_snapshot"] == "일반"


def test_daily_stats_preserve_kst_calendar_date(tmp_path):
    db_path = str(tmp_path / "kst-stats.db")
    repo = QueryLogRepository()
    repo.db.execute_update(
        """
        INSERT INTO tb_users (user_id, user_pwd, user_name)
        VALUES (?, ?, ?)
        """,
        ("user01", "hash", "사용자"),
    )
    log_id = repo.log_query(
        query_text="자정 직후 질의",
        user_id="user01",
        answer_generated=True,
        outcome_code="success",
        cost_usd=0.1,
    )
    repo.db.execute_update(
        "UPDATE tb_query_logs SET created_at=? WHERE log_id=?",
        ("2026-06-19T00:30:00+09:00", log_id),
    )
    stats = StatsRepository()

    # 2026.06.19(sooyeon.choi) 추가 - KST 자정 직후 로그가 전날로 이동하지 않는지 검증
    trend = stats.daily_usage_trend(
        "2026-06-19T00:00:00+09:00",
        "2026-06-20T00:00:00+09:00",
        "user01",
    )

    assert trend == [
        {
            "date": "2026-06-19",
            "query_count": 1,
            "cost_usd": 0.1,
        }
    ]
    assert stats.count_active_days(
        "2026-06-19T00:00:00+09:00",
        "2026-06-20T00:00:00+09:00",
        "user01",
    ) == 1


def test_user_statistics_are_isolated_and_use_outcome_codes(tmp_path):
    db_path = str(tmp_path / "user-stats.db")
    repo = QueryLogRepository()
    for user_id in ("user01", "user02"):
        repo.db.execute_update(
            """
            INSERT INTO tb_users (user_id, user_pwd, user_name)
            VALUES (?, ?, ?)
            """,
            (user_id, "hash", user_id),
        )

    user01_success = repo.log_query(
        query_text="안전 안전 기준",
        user_id="user01",
        answer_generated=True,
        outcome_code="success",
        extracted_keywords=["안전", "안전", "기준"],
    )
    user01_failure = repo.log_query(
        query_text="없는 매뉴얼",
        user_id="user01",
        outcome_code="no_context",
    )
    user01_guardrail = repo.log_query(
        query_text="인사",
        user_id="user01",
        answer_generated=True,
        outcome_code="guardrail_blocked",
    )
    repo.log_query(
        query_text="다른 사용자 질의",
        user_id="user02",
        answer_generated=True,
        outcome_code="success",
        extracted_keywords=["다른사용자"],
    )
    for log_id in (user01_success, user01_failure, user01_guardrail):
        repo.db.execute_update(
            "UPDATE tb_query_logs SET created_at=? WHERE log_id=?",
            ("2026-06-19T10:00:00+09:00", log_id),
        )
    repo.db.execute_update(
        "UPDATE tb_query_logs SET feedback=0 WHERE log_id=?",
        (user01_success,),
    )

    stats = StatsRepository()
    start = "2026-06-19T00:00:00+09:00"
    end = "2026-06-20T00:00:00+09:00"

    # 2026.06.19(sooyeon.choi) 추가 - 사용자 격리·성공률 분모·주의 질의 기준 검증
    assert stats.count_queries(start, end, "user01") == 3
    assert stats.success_counts(start, end, "user01") == {
        "success_count": 1,
        "failure_count": 1,
        "completed_count": 2,
    }
    assert stats.count_problem_queries(start, end, "user01") == 2
    assert stats.top_keywords(start, end, 5, "user01") == [
        {"keyword": "기준", "count": 1},
        {"keyword": "안전", "count": 1},
    ]
    flagged = stats.flagged_queries(start, end, 10, "user01")
    assert {row["log_id"] for row in flagged} == {
        user01_success,
        user01_failure,
    }
    assert all(row["user_id"] == "user01" for row in flagged)


def test_admin_flagged_queries_are_paginated_with_user_snapshot(tmp_path):
    db_path = str(tmp_path / "admin-flagged.db")
    repo = QueryLogRepository()
    for index in range(3):
        user_id = f"user{index}"
        repo.db.execute_update(
            """
            INSERT INTO tb_users
                (user_id, user_pwd, user_name, department_name)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, "hash", f"사용자{index}", f"부서{index}"),
        )
        log_id = repo.log_query(
            query_text=f"실패 질의 {index}",
            user_id=user_id,
            outcome_code="no_context",
        )
        repo.db.execute_update(
            "UPDATE tb_query_logs SET created_at=? WHERE log_id=?",
            (f"2026-06-19T10:00:0{index}+09:00", log_id),
        )

    stats = StatsRepository()
    start = "2026-06-19T00:00:00+09:00"
    end = "2026-06-20T00:00:00+09:00"

    # 2026.06.19(sooyeon.choi) 추가 - 관리자 목록 전체 건수·페이지·부서 스냅샷 검증
    assert stats.count_admin_flagged_queries(start, end) == 3
    page = stats.admin_flagged_queries(
        start,
        end,
        limit=2,
        offset=0,
    )

    assert len(page) == 2
    assert page[0]["user_id"] == "user2"
    assert page[0]["user_name"] == "사용자2"
    assert page[0]["department"] == "부서2"


def test_department_statistics_keep_query_time_snapshot(tmp_path):
    db_path = str(tmp_path / "department-stats.db")
    repo = QueryLogRepository()
    repo.db.execute_update(
        """
        INSERT INTO tb_users (user_id, user_pwd, user_name, department_name)
        VALUES (?, ?, ?, ?)
        """,
        ("user01", "hash", "사용자", "기존부서"),
    )
    log_id = repo.log_query(
        query_text="부서 통계 질의",
        user_id="user01",
        outcome_code="success",
    )
    repo.db.execute_update(
        """
        UPDATE tb_query_logs
        SET created_at=?, feedback=1
        WHERE log_id=?
        """,
        ("2026-06-18T10:00:00+09:00", log_id),
    )
    repo.db.execute_update(
        "UPDATE tb_users SET department_name=? WHERE user_id=?",
        ("변경부서", "user01"),
    )

    stats = StatsRepository()
    items = stats.department_usage(
        "2026-06-18T00:00:00+09:00",
        "2026-06-19T00:00:00+09:00",
    )

    # 2026.06.19(sooyeon.choi) 추가 - 현재 사용자 부서가 아닌 질의 시점 스냅샷 검증
    assert items == [{
        "department": "기존부서",
        "query_count": 1,
        "satisfaction_pct": 100.0,
        "feedback_count": 1,
    }]


def test_department_weekly_trend_uses_monday_boundaries(tmp_path, monkeypatch):
    db_path = str(tmp_path / "department-weekly.db")
    repo = QueryLogRepository()
    repo.db.execute_update(
        """
        INSERT INTO tb_users (user_id, user_pwd, user_name, department_name)
        VALUES (?, ?, ?, ?)
        """,
        ("user01", "hash", "사용자", "안전보건팀"),
    )
    for created_at in (
        "2026-06-08T09:00:00+09:00",
        "2026-06-15T09:00:00+09:00",
        "2026-06-19T09:00:00+09:00",
    ):
        log_id = repo.log_query(
            query_text="주간 질의",
            user_id="user01",
            outcome_code="success",
        )
        repo.db.execute_update(
            "UPDATE tb_query_logs SET created_at=? WHERE log_id=?",
            (created_at, log_id),
        )

    kst = timezone(timedelta(hours=9))
    monkeypatch.setattr(
        stats_repository_module,
        "_kst_now",
        lambda: datetime(2026, 6, 19, 12, 0, tzinfo=kst),
    )
    trend = StatsRepository().department_weekly_trend(weeks=2)

    # 2026.06.19(sooyeon.choi) 추가 - 월요일 경계·빈 구간 보정·주차 메타데이터 검증
    assert trend["weeks"][0]["start_date"] == "2026-06-08"
    assert trend["weeks"][0]["end_date"] == "2026-06-14"
    assert trend["weeks"][1]["start_date"] == "2026-06-15"
    assert trend["weeks"][1]["end_date"] == "2026-06-21"
    assert trend["series"] == [{
        "department": "안전보건팀",
        "values": [1, 2],
    }]


def test_top_users_apply_tie_break_order(tmp_path):
    db_path = str(tmp_path / "top-users.db")
    repo = QueryLogRepository()
    for user_id in ("user01", "user02", "user03"):
        repo.db.execute_update(
            """
            INSERT INTO tb_users (user_id, user_pwd, user_name, department_name)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, "hash", user_id, "공통부서"),
        )
        for index in range(2):
            log_id = repo.log_query(
                query_text="순위 질의",
                user_id=user_id,
                outcome_code="success",
            )
            repo.db.execute_update(
                """
                UPDATE tb_query_logs
                SET created_at=?, feedback=?
                WHERE log_id=?
                """,
                (
                    f"2026-06-19T10:00:0{index}+09:00",
                    1 if user_id != "user03" or index == 0 else 0,
                    log_id,
                ),
            )

    users = StatsRepository().top_users_by_activity(
        "2026-06-19T00:00:00+09:00",
        "2026-06-20T00:00:00+09:00",
        10,
    )

    # 2026.06.19(sooyeon.choi) 추가 - 질의수·만족도·사용자 ID 순 동률 정렬 검증
    assert [user["user_id"] for user in users] == [
        "user01",
        "user02",
        "user03",
    ]
    assert users[2]["satisfaction_pct"] == 50.0


def test_document_health_excludes_deleted_and_non_ready_documents(tmp_path):
    db_path = str(tmp_path / "document-health.db")
    repo = QueryLogRepository()
    repo.db.execute_update(
        """
        INSERT INTO tb_users (user_id, user_pwd, user_name)
        VALUES ('user01', 'hash', '사용자')
        """
    )
    repo.db.execute_update(
        """
        INSERT INTO tb_collections
            (collection_id, qdrant_name, display_name, created_by)
        VALUES (1, 'safety', '안전 문서', 'user01')
        """
    )
    documents = [
        (
            "both", "both.pdf", "ready", None,
            "2026-01-01T09:00:00+09:00",
            "2026-05-01T00:00:00+09:00",
        ),
        (
            "uncited", "uncited.pdf", "ready", None,
            "2026-01-02T09:00:00+09:00", None,
        ),
        (
            "review", "review.pdf", "ready", None,
            "2026-06-10T09:00:00+09:00",
            "2026-05-01T00:00:00+09:00",
        ),
        (
            "healthy", "healthy.pdf", "ready", None,
            "2026-06-10T09:00:00+09:00", None,
        ),
        (
            "deleted", "deleted.pdf", "deleted",
            "2026-06-01T09:00:00+09:00",
            "2026-01-01T09:00:00+09:00", None,
        ),
        (
            "pending", "pending.pdf", "pending", None,
            "2026-01-01T09:00:00+09:00", None,
        ),
    ]
    for document_id, name, status, deleted_at, created_at, review_due_at in documents:
        repo.db.execute_update(
            """
            INSERT INTO tb_documents (
                document_id, collection_id, original_filename, source_path,
                status, deleted_at, created_at, updated_at,
                content_updated_at, review_due_at
            ) VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                document_id,
                name,
                f"/tmp/{name}",
                status,
                deleted_at,
                created_at,
                created_at,
                created_at,
                review_due_at,
            ),
        )

    log_id = repo.log_query(
        query_text="건강 문서 인용",
        user_id="user01",
        outcome_code="success",
    )
    repo.db.execute_update(
        """
        INSERT INTO tb_query_citations
            (log_id, document_id, original_filename, collection_id, cited_at)
        VALUES (?, 'healthy', 'healthy.pdf', 1, ?)
        """,
        (log_id, "2026-06-18T09:00:00+09:00"),
    )

    stats = StatsRepository()
    now = "2026-06-19T12:00:00+09:00"
    cutoff = "2026-04-20T12:00:00+09:00"

    # 2026.06.19(sooyeon.choi) 추가 - 문서 상태 분류·제외·요약 일치 검증
    assert stats.document_health_summary(now, cutoff) == {
        "review_overdue_count": 2,
        "uncited_count": 2,
        "total_document_count": 4,
    }
    assert stats.count_document_health_items(now, cutoff) == 3
    items = stats.document_health_items(now, cutoff, limit=20, offset=0)
    assert {
        item["document_id"]: item["health_status"]
        for item in items
    } == {
        "both": "review_overdue_and_uncited",
        "review": "review_overdue",
        "uncited": "uncited",
    }


def test_document_repository_sets_content_date_and_updates_review_date(tmp_path):
    db_path = str(tmp_path / "document-review.db")
    repo = DocumentRepository()
    repo.db.execute_update(
        """
        INSERT INTO tb_users (user_id, user_pwd, user_name)
        VALUES ('user01', 'hash', '사용자')
        """
    )
    repo.db.execute_update(
        """
        INSERT INTO tb_collections
            (collection_id, qdrant_name, display_name, created_by)
        VALUES (1, 'safety', '안전 문서', 'user01')
        """
    )

    assert repo.store(DocumentMetadata(
        document_id="doc-1",
        collection_id=1,
        source_path="/tmp/doc-1.pdf",
        original_filename="doc-1.pdf",
        status=DocumentStatus.READY,
    ))
    assert repo.update_review_due_at(
        "doc-1",
        "2026-12-31T00:00:00+09:00",
    )

    row = repo.db.execute_query(
        """
        SELECT content_updated_at, review_due_at
        FROM tb_documents
        WHERE document_id = 'doc-1'
        """
    )[0]

    # 2026.06.19(sooyeon.choi) 추가 - 업로드 콘텐츠 시각 자동 설정·검토일 수정 검증
    assert row["content_updated_at"] is not None
    assert row["review_due_at"] == "2026-12-31T00:00:00+09:00"

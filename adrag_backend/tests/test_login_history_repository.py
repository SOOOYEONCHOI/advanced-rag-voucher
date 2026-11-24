"""Login history repository and schema migration tests."""

import pytest

from app.repositories import database
from app.repositories.login_history_repository import LoginHistoryRepository


@pytest.fixture(autouse=True)
def reset_database_singletons():
    database._db_manager = None
    database.DatabaseManager._instance = None
    yield
    manager = database.DatabaseManager._instance
    if manager is not None:
        manager.close_all_connections()
    database._db_manager = None
    database.DatabaseManager._instance = None


# 2026.06.30(sooyeon.choi) 추가 - 신규 DB에 부서명 스냅샷 저장 검증
def test_record_stores_department_snapshot(tmp_path):
    db_path = str(tmp_path / "login-history.db")
    repo = LoginHistoryRepository()

    repo.record(
        attempted_user_id="adrag",
        user_id=None,
        user_role="user",
        department_snapshot="R&D팀",
        success=False,
        failure_reason="invalid_password",
    )

    rows = repo.db.execute_query(
        "SELECT department_snapshot FROM tb_login_history"
    )
    assert rows[0]["department_snapshot"] == "R&D팀"

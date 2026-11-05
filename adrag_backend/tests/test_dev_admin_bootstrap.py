"""dev 컨테이너 관리자 자동 생성(app/services/admin_bootstrap.py ensure_dev_admin) 테스트 (2026.10.20 D-19).

conftest가 테스트마다 넣는 'admin' 행(사용 불가 비밀번호)은 활성 관리자가 없는 경우를 만들 때 지운다.
"""

from types import SimpleNamespace

import pytest

from app.repositories import database
from app.services import admin_bootstrap
from app.utils.security import verify_password

PASSWORD = "dev-only-pass-1234"


@pytest.fixture
def db():
    database.close_database_manager()
    manager = database.get_database_manager()
    yield manager
    database.close_database_manager()


@pytest.fixture
def no_admin(db):
    db.execute_update("DELETE FROM tb_users WHERE role = 'admin'")
    return db


def _users(db):
    rows = db.execute_query("SELECT user_id, user_pwd, role, is_active FROM tb_users ORDER BY user_id")
    return [dict(row) for row in rows]


def test_creates_admin_when_none_exists(no_admin):
    result, message = admin_bootstrap.ensure_dev_admin(no_admin, "admin", "관리자", PASSWORD)

    assert result == "created"
    assert PASSWORD not in message
    rows = _users(no_admin)
    assert [(r["user_id"], r["role"], r["is_active"]) for r in rows] == [("admin", "admin", True)]
    assert verify_password(PASSWORD, rows[0]["user_pwd"])


def test_skips_when_active_admin_exists(db):
    before = _users(db)

    result, _ = admin_bootstrap.ensure_dev_admin(db, "admin2", "관리자", PASSWORD)

    assert result == "skipped_admin_exists"
    assert _users(db) == before  # 기존 관리자 비밀번호도 덮어쓰지 않는다


@pytest.mark.parametrize("password, expected", [(None, "skipped_no_password"), ("", "skipped_no_password"), ("short", "skipped_short_password")])
def test_skips_without_valid_password(no_admin, password, expected):
    result, message = admin_bootstrap.ensure_dev_admin(no_admin, "admin", "관리자", password)

    assert result == expected
    assert "ADMIN_PASSWORD" in message
    assert _users(no_admin) == []


def test_does_not_promote_existing_normal_user(no_admin):
    no_admin.execute_update(
        "INSERT INTO tb_users (user_id, user_pwd, user_name, role) VALUES ('admin', 'hash', '사용자', 'user')"
    )

    result, _ = admin_bootstrap.ensure_dev_admin(no_admin, "admin", "관리자", PASSWORD)

    assert result == "skipped_user_exists"
    assert [(r["user_id"], r["role"], r["user_pwd"]) for r in _users(no_admin)] == [("admin", "user", "hash")]


def test_refuses_production_database():
    def fail(*_args, **_kwargs):
        raise AssertionError("운영 DB에는 쿼리하지 않아야 한다")

    prod = SimpleNamespace(url=SimpleNamespace(database="rag_chatbot_prod"), execute_query=fail, execute_update=fail)

    result, _ = admin_bootstrap.ensure_dev_admin(prod, "admin", "관리자", PASSWORD)

    assert result == "skipped_prod"

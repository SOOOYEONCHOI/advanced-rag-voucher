"""Department repository synchronization tests."""

import pytest

from app.repositories import database
from app.repositories.department_repository import DepartmentRepository


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


# 2026.06.30(sooyeon.choi) 추가 - 부서명 변경 시 사용자·컬렉션 동기화 검증
def test_department_name_update_syncs_users_and_collections(tmp_path):
    repo = DepartmentRepository()
    department = repo.create("R&D팀")
    department_id = department["department_id"]

    repo.db.execute_update(
        """
        INSERT INTO tb_users (
            user_id, user_pwd, user_name, department_id, department_name
        ) VALUES (?, ?, ?, ?, ?)
        """,
        ("AIE", "hash", "AIE", department_id, "R&D팀"),
    )
    repo.db.execute_update(
        """
        INSERT INTO tb_collections (
            display_name, qdrant_name, created_by,
            department_id, department_name
        ) VALUES (?, ?, ?, ?, ?)
        """,
        ("기타", "AIE_기타", "AIE", department_id, "R&D팀"),
    )

    updated = repo.update(
        department_id=department_id,
        department_name="AI혁신팀",
    )

    user = repo.db.execute_query(
        "SELECT department_name FROM tb_users WHERE user_id = 'AIE'"
    )[0]
    collection = repo.db.execute_query(
        "SELECT department_name FROM tb_collections WHERE qdrant_name = 'AIE_기타'"
    )[0]

    assert updated["department_name"] == "AI혁신팀"
    assert user["department_name"] == "AI혁신팀"
    assert collection["department_name"] == "AI혁신팀"

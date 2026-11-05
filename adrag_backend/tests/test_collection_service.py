"""Collection service tests."""

import logging
import asyncio
import sys
import types
from types import SimpleNamespace

import pytest

config_module = types.ModuleType("app.core.config")
config_module.get_settings = lambda: SimpleNamespace(sqlite_db_path="", instance_dir="")
sys.modules["app.core.config"] = config_module

log_module = types.ModuleType("app.utils.log.log")


class _TestLoggingLogger:
    # 2026.07.16(sooyeon.choi) 수정 - named logger 지원 API 변경 반영 (B16)
    def getLogger(self, name=None):
        return logging.getLogger("test.collection_service")


log_module.LoggingLogger = _TestLoggingLogger
sys.modules["app.utils.log.log"] = log_module

vector_module = types.ModuleType("app.repositories.vector_repository")
vector_module.VectorRepository = object
sys.modules["app.repositories.vector_repository"] = vector_module

from app.repositories import database
from app.repositories.collection_repository import CollectionRepository
from app.services.collection_service import CollectionService


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


class FakeVectorRepository:
    def __init__(self, exists: bool):
        self.exists = exists
        self.created = []
        self.deleted = []

    def collection_exists(self, collection_name: str) -> bool:
        return self.exists

    def create_collection(self, collection_name: str, vector_size: int) -> bool:
        self.created.append((collection_name, vector_size))
        return True

    def delete_collection(self, collection_name: str) -> bool:
        self.deleted.append(collection_name)
        self.exists = False
        return True


def _service(db_path, vector_repo):
    service = CollectionService.__new__(CollectionService)
    service.settings = SimpleNamespace(
        max_collections=5,
        embedding_dim=3,
        sqlite_db_path="", instance_dir=str(db_path),
    )
    service.collection_repo = CollectionRepository(str(db_path))
    service.vector_repo = vector_repo
    return service


def _insert_user(repo, user_id="user01"):
    repo.db.execute_update(
        """
        INSERT INTO tb_users (user_id, user_pwd, user_name, department_name)
        VALUES (?, ?, ?, ?)
        """,
        (user_id, "hash", "User", "Dept"),
    )


def test_create_collection_reuses_name_when_rdb_row_is_missing_from_qdrant(tmp_path):
    repo = CollectionRepository(str(tmp_path / "collections.db"))
    _insert_user(repo)
    stale = repo.create("Topic", created_by="user01", qdrant_name="user01_Topic")
    repo.db.execute_update(
        """
        INSERT INTO tb_documents
            (document_id, collection_id, source_path, security_level, status)
        VALUES (?, ?, ?, ?, ?)
        """,
        ("doc01", stale.collection_id, "/tmp/doc.pdf", "public", "ready"),
    )

    vector_repo = FakeVectorRepository(exists=False)
    service = _service(tmp_path / "collections.db", vector_repo)

    created = service.create_collection("Topic", created_by="user01")

    assert created.display_name == "Topic"
    assert created.qdrant_name == "user01_Topic"
    assert vector_repo.created == [("user01_Topic", 3)]
    assert repo.db.execute_query(
        "SELECT COUNT(*) AS count FROM tb_documents WHERE document_id = ?",
        ("doc01",),
    )[0]["count"] == 0
    assert repo.db.execute_query(
        "SELECT COUNT(*) AS count FROM tb_collections WHERE qdrant_name = ?",
        ("user01_Topic",),
    )[0]["count"] == 1


def test_create_collection_keeps_duplicate_when_qdrant_collection_exists(tmp_path):
    repo = CollectionRepository(str(tmp_path / "collections.db"))
    _insert_user(repo)
    repo.create("Topic", created_by="user01", qdrant_name="user01_Topic")

    service = _service(tmp_path / "collections.db", FakeVectorRepository(exists=True))

    with pytest.raises(ValueError, match="이미 등록된 컬렉션 이름입니다"):
        service.create_collection("Topic", created_by="user01")


# 2026.06.30(sooyeon.choi) 추가 - 부서 허용 주제, 개인 차단, 타 부서 격리 검증
def test_get_accessible_by_user_applies_department_and_blocked_topics(tmp_path):
    repo = CollectionRepository(str(tmp_path / "collections.db"))
    repo.db.execute_update(
        "INSERT INTO tb_departments (department_id, department_name, allowed_topics) VALUES (?, ?, ?)",
        ("D001", "R&D", '["기타", "산업안전보건법"]'),
    )
    repo.db.execute_update(
        "INSERT INTO tb_departments (department_id, department_name, allowed_topics) VALUES (?, ?, ?)",
        ("D002", "지원", '["기타"]'),
    )
    for user in (
        ("AIE", "AIE", "D001", "[]"),
        ("adrag", "adrag", "D001", '["산업안전보건법"]'),
        ("other", "other", "D002", "[]"),
    ):
        repo.db.execute_update(
            """
            INSERT INTO tb_users
                (user_id, user_pwd, user_name, department_id, department_name, blocked_topics)
            VALUES (?, 'hash', ?, ?, ?, ?)
            """,
            (
                user[0],
                user[1],
                user[2],
                "R&D" if user[2] == "D001" else "지원",
                user[3],
            ),
        )

    repo.create("기타", created_by="AIE", qdrant_name="AIE_기타", topic_name="기타", department_id="D001", department_name="R&D")
    repo.create(
        "산업안전보건법",
        created_by="AIE",
        qdrant_name="AIE_산업안전보건법",
        topic_name="산업안전보건법",
        department_id="D001",
        department_name="R&D",
    )
    repo.create("기타", created_by="other", qdrant_name="other_기타", topic_name="기타", department_id="D002", department_name="지원")

    aie_names = [c.qdrant_name for c in repo.get_accessible_by_user("AIE")]
    adrag_names = [c.qdrant_name for c in repo.get_accessible_by_user("adrag")]

    assert aie_names == ["AIE_기타", "AIE_산업안전보건법"]
    assert adrag_names == ["AIE_기타"]


# 2026.06.30(sooyeon.choi) 추가 - 컬렉션 생성자와 관리자만 관리 가능함을 검증
def test_require_collection_manager_rejects_other_user():
    from fastapi import HTTPException
    from app.routes.collections import _require_collection_manager

    collection = SimpleNamespace(created_by="AIE")
    repo = SimpleNamespace(get_by_id=lambda _: collection)

    assert _require_collection_manager(
        1, {"user_id": "AIE", "is_admin": False}, repo
    ) is collection
    assert _require_collection_manager(
        1, {"user_id": "admin", "is_admin": True}, repo
    ) is collection

    with pytest.raises(HTTPException) as exc_info:
        _require_collection_manager(
            1, {"user_id": "adrag", "is_admin": False}, repo
        )

    assert exc_info.value.status_code == 403


def test_delete_collection_cleans_topic_only_after_departments_last_collection(tmp_path):
    db_path = tmp_path / "collections.db"
    repo = CollectionRepository(str(db_path))
    for department_id in ("D001", "D002"):
        department_name = f"Department {department_id}"
        repo.db.execute_update(
            """
            INSERT INTO tb_departments
                (department_id, department_name, allowed_topics)
            VALUES (?, ?, '["shared-topic"]')
            """,
            (department_id, department_name),
        )
        repo.db.execute_update(
            """
            INSERT INTO tb_users
                (user_id, user_pwd, user_name, department_id,
                 department_name, blocked_topics)
            VALUES (?, 'hash', ?, ?, ?, '["shared-topic"]')
            """,
            (
                f"user-{department_id}",
                f"User {department_id}",
                department_id,
                department_name,
            ),
        )

    first = repo.create(
        "First",
        created_by="user-D001",
        qdrant_name="user-D001_First",
        topic_name="shared-topic",
        department_id="D001",
        department_name="Department D001",
    )
    second = repo.create(
        "Second",
        created_by="user-D001",
        qdrant_name="user-D001_Second",
        topic_name="shared-topic",
        department_id="D001",
        department_name="Department D001",
    )
    other_department = repo.create(
        "Other",
        created_by="user-D002",
        qdrant_name="user-D002_Other",
        topic_name="shared-topic",
        department_id="D002",
        department_name="Department D002",
    )
    service = _service(db_path, FakeVectorRepository(exists=True))

    service.delete_collection(first.collection_id)

    d001 = repo.db.execute_query(
        "SELECT allowed_topics FROM tb_departments WHERE department_id = 'D001'"
    )[0]
    assert d001["allowed_topics"] == '["shared-topic"]'

    service.delete_collection(second.collection_id)

    d001 = repo.db.execute_query(
        "SELECT allowed_topics FROM tb_departments WHERE department_id = 'D001'"
    )[0]
    d001_user = repo.db.execute_query(
        "SELECT blocked_topics FROM tb_users WHERE user_id = 'user-D001'"
    )[0]
    d002 = repo.db.execute_query(
        "SELECT allowed_topics FROM tb_departments WHERE department_id = 'D002'"
    )[0]
    d002_user = repo.db.execute_query(
        "SELECT blocked_topics FROM tb_users WHERE user_id = 'user-D002'"
    )[0]
    assert d001["allowed_topics"] == "[]"
    assert d001_user["blocked_topics"] == "[]"
    assert d002["allowed_topics"] == '["shared-topic"]'
    assert d002_user["blocked_topics"] == '["shared-topic"]'
    assert repo.get_by_id(other_department.collection_id) is not None


# 2026.06.30(sooyeon.choi) 추가 - 컬렉션 목록의 공유 조회와 capability 응답 검증
def test_list_collections_returns_accessible_read_only_collection(tmp_path, monkeypatch):
    from fastapi import HTTPException
    from app.routes import collections as collections_route

    db_path = str(tmp_path / "collections.db")
    repo = CollectionRepository(db_path)
    repo.db.execute_update(
        "INSERT INTO tb_departments (department_id, department_name, allowed_topics) VALUES (?, ?, ?)",
        ("D001", "R&D", '["기타"]'),
    )
    for user_id in ("AIE", "adrag"):
        repo.db.execute_update(
            """
            INSERT INTO tb_users (user_id, user_pwd, user_name, department_id, department_name)
            VALUES (?, 'hash', ?, 'D001', 'R&D')
            """,
            (user_id, user_id),
        )
    repo.create(
        "기타",
        created_by="AIE",
        qdrant_name="AIE_기타",
        topic_name="기타",
        department_id="D001",
        department_name="R&D",
    )

    class FakeListVectorRepository:
        def __init__(self, **_):
            pass

        def list_collections(self):
            return ["AIE_기타"]

    monkeypatch.setattr(
        collections_route,
        "get_settings",
        lambda: SimpleNamespace(
            sqlite_db_path="", instance_dir=db_path,
            qdrant_host="localhost",
            qdrant_port=6333,
        ),
    )
    monkeypatch.setattr(
        collections_route,
        "VectorRepository",
        FakeListVectorRepository,
    )

    response = asyncio.run(
        collections_route.list_collections(
            include_all=False,
            principal={"user_id": "adrag", "is_admin": False},
        )
    )

    assert response.total == 1
    assert response.collections[0].created_by == "AIE"
    assert response.collections[0].owned_by_me is False
    assert response.collections[0].can_update is False
    assert response.collections[0].can_delete is False

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            collections_route.list_collections(
                include_all=True,
                principal={"user_id": "adrag", "is_admin": False},
            )
        )

    assert exc_info.value.status_code == 403

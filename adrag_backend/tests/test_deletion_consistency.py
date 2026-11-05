"""Deletion consistency regression tests.

These tests describe the required contract between the RDB and Qdrant.  The
initial tests intentionally fail until the deletion verification work is
implemented.
"""

import asyncio
import json
from types import SimpleNamespace

import pytest
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from app.repositories import database
from app.repositories.collection_repository import CollectionRepository
from app.repositories.vector_repository import VectorRepository
from app.services.collection_service import CollectionService
from app.services.ingest_service import IngestService


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


class FakeDocumentRepository:
    def __init__(self, document):
        self.document = document
        self.soft_deleted = False
        self.events = []

    def get_by_id(self, document_id):
        return self.document if self.document.document_id == document_id else None

    def soft_delete(self, document_id):
        self.soft_deleted = True
        return True

    def record_event(self, event):
        self.events.append(event)
        return True


class FakeDocumentVectorRepository:
    def __init__(self, counts, delete_result=True):
        self.counts = list(counts)
        self.delete_result = delete_result
        self.count_calls = []
        self.delete_calls = []

    def count_by_document_id(self, document_id, collection_name):
        self.count_calls.append((document_id, collection_name))
        return self.counts.pop(0)

    def delete_by_document_id(self, document_id, collection_name):
        self.delete_calls.append((document_id, collection_name))
        return self.delete_result


class NoopFileManager:
    def __init__(self):
        self.deleted = []

    def delete(self, path):
        self.deleted.append(path)


class NoopChunkWriter:
    def __init__(self):
        self.deleted = []

    def delete(self, filename, document_id, collection_name=""):
        self.deleted.append((filename, document_id, collection_name))


def make_ingest_service(vector_repo):
    document = SimpleNamespace(
        document_id="doc-01",
        collection_id=1,
        original_filename="manual.pdf",
        title="Manual",
        source_path="instance/data/manual.pdf",
    )
    service = IngestService.__new__(IngestService)
    service.doc_repo = FakeDocumentRepository(document)
    service.collection_repo = SimpleNamespace(
        get_by_id=lambda collection_id: SimpleNamespace(qdrant_name="user_manual")
    )
    service.vector_repo = vector_repo
    service._file_manager = NoopFileManager()
    service._chunk_writer = NoopChunkWriter()
    return service


def test_document_delete_verifies_zero_remaining_points_before_soft_delete():
    vector_repo = FakeDocumentVectorRepository(counts=[3, 0])
    service = make_ingest_service(vector_repo)

    result = service.delete_document("doc-01", actor_id="user")

    assert vector_repo.count_calls == [
        ("doc-01", "user_manual"),
        ("doc-01", "user_manual"),
    ]
    assert vector_repo.delete_calls == [("doc-01", "user_manual")]
    assert service.doc_repo.soft_deleted is True
    assert result["remaining_vector_count"] == 0
    assert result["deleted_vector_count"] == 3


def test_document_delete_keeps_rdb_active_when_vectors_remain():
    vector_repo = FakeDocumentVectorRepository(counts=[3, 1])
    service = make_ingest_service(vector_repo)

    with pytest.raises(RuntimeError, match="벡터|포인트|잔여"):
        service.delete_document("doc-01", actor_id="user")

    assert service.doc_repo.soft_deleted is False
    assert service.doc_repo.events == []
    assert service._file_manager.deleted == []
    assert service._chunk_writer.deleted == []


def test_document_delete_keeps_rdb_active_when_qdrant_delete_fails():
    vector_repo = FakeDocumentVectorRepository(counts=[3], delete_result=False)
    service = make_ingest_service(vector_repo)

    with pytest.raises(RuntimeError):
        service.delete_document("doc-01", actor_id="user")

    assert service.doc_repo.soft_deleted is False
    assert service.doc_repo.events == []
    assert service._file_manager.deleted == []
    assert service._chunk_writer.deleted == []


def test_document_delete_is_idempotent_when_already_deleted():
    deleted_document = SimpleNamespace(
        document_id="doc-01",
        collection_id=1,
        original_filename="manual.pdf",
        title="Manual",
        source_path="instance/data/manual.pdf",
        status="deleted",
        deleted_at="2026-07-27T10:00:00+09:00",
    )

    class DeletedDocumentRepository(FakeDocumentRepository):
        def get_by_id(self, document_id, include_deleted=False):
            if document_id != self.document.document_id:
                return None
            return self.document if include_deleted else None

    vector_repo = FakeDocumentVectorRepository(counts=[0])
    service = make_ingest_service(vector_repo)
    service.doc_repo = DeletedDocumentRepository(deleted_document)

    result = service.delete_document("doc-01", actor_id="user")

    assert result["status"] == "already_deleted"
    assert result["remaining_vector_count"] == 0
    assert service.doc_repo.events == []
    assert service._file_manager.deleted == []
    assert service._chunk_writer.deleted == []


def test_document_delete_reconciles_active_rdb_row_when_points_are_missing():
    vector_repo = FakeDocumentVectorRepository(counts=[0])
    service = make_ingest_service(vector_repo)

    result = service.delete_document("doc-01", actor_id="user")

    assert result["reconciled"] is True
    assert result["remaining_vector_count"] == 0
    assert service.doc_repo.soft_deleted is True


def test_vector_repository_counts_and_deletes_only_target_document():
    repository = VectorRepository.__new__(VectorRepository)
    repository.collection_name = "documents"
    repository.client = QdrantClient(":memory:")
    repository.client.create_collection(
        collection_name="documents",
        vectors_config=VectorParams(size=2, distance=Distance.COSINE),
    )
    repository.client.upsert(
        collection_name="documents",
        wait=True,
        points=[
            PointStruct(
                id=1,
                vector=[1.0, 0.0],
                payload={"document_id": "doc-01"},
            ),
            PointStruct(
                id=2,
                vector=[0.0, 1.0],
                payload={"document_id": "doc-01"},
            ),
            PointStruct(
                id=3,
                vector=[0.5, 0.5],
                payload={"document_id": "doc-02"},
            ),
        ],
    )

    assert repository.count_by_document_id("doc-01", "documents") == 2
    assert repository.delete_by_document_id("doc-01", "documents") is True
    assert repository.count_by_document_id("doc-01", "documents") == 0
    assert repository.count_by_document_id("doc-02", "documents") == 1


class FakeCollectionVectorRepository:
    def __init__(self, exists=True):
        self.exists = exists
        self.deleted = []
        self.exists_calls = []

    def delete_collection(self, collection_name):
        self.deleted.append(collection_name)
        return True

    def collection_exists(self, collection_name):
        self.exists_calls.append(collection_name)
        return self.exists


class SuccessfulCollectionVectorRepository(FakeCollectionVectorRepository):
    def delete_collection(self, collection_name):
        self.deleted.append(collection_name)
        self.exists = False
        return True


def make_collection_service(db_path, vector_repo):
    service = CollectionService.__new__(CollectionService)
    service.settings = SimpleNamespace(
        max_collections=5,
        embedding_dim=3,
        sqlite_db_path="", instance_dir=str(db_path),
    )
    service.collection_repo = CollectionRepository(str(db_path))
    service.vector_repo = vector_repo
    return service


def insert_user(repo, user_id="user01"):
    repo.db.execute_update(
        """
        INSERT INTO tb_users (user_id, user_pwd, user_name, department_name)
        VALUES (?, 'hash', 'User', 'Dept')
        """,
        (user_id,),
    )


def test_collection_delete_verifies_qdrant_absence_before_rdb_delete(tmp_path):
    db_path = tmp_path / "collections.db"
    repo = CollectionRepository(str(db_path))
    insert_user(repo)
    collection = repo.create(
        "Manual",
        created_by="user01",
        qdrant_name="user01_Manual",
    )
    repo.db.execute_update(
        """
        INSERT INTO tb_documents
            (document_id, collection_id, source_path, security_level, status)
        VALUES ('doc-01', ?, '/tmp/manual.pdf', 'public', 'ready')
        """,
        (collection.collection_id,),
    )
    vector_repo = FakeCollectionVectorRepository(exists=True)
    service = make_collection_service(db_path, vector_repo)

    with pytest.raises(RuntimeError, match="Qdrant|컬렉션|삭제"):
        service.delete_collection(collection.collection_id)

    assert repo.get_by_id(collection.collection_id) is not None
    assert repo.db.execute_query(
        "SELECT COUNT(*) AS count FROM tb_documents WHERE document_id = 'doc-01'"
    )[0]["count"] == 1


def test_collection_delete_with_eval_dataset_returns_409_before_qdrant_change(
    tmp_path, monkeypatch
):
    from fastapi import HTTPException
    from app.routes import collections as collections_route

    db_path = tmp_path / "collections.db"
    repo = CollectionRepository(str(db_path))
    insert_user(repo)
    collection = repo.create(
        "Manual",
        created_by="user01",
        qdrant_name="user01_Manual",
    )
    repo.db.execute_update(
        """
        INSERT INTO tb_eval_datasets (name, collection_id, status, created_by)
        VALUES ('Manual evaluation', ?, 'finalized', 'user01')
        """,
        (collection.collection_id,),
    )

    vector_repo = FakeCollectionVectorRepository(exists=True)
    service = make_collection_service(db_path, vector_repo)
    monkeypatch.setattr(
        collections_route,
        "get_settings",
        lambda: SimpleNamespace(sqlite_db_path="", instance_dir=str(db_path)),
    )
    monkeypatch.setattr(collections_route, "CollectionService", lambda: service)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            collections_route.delete_collection(
                collection.collection_id,
                principal={"user_id": "user01", "is_admin": False},
            )
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["error_code"] == "COLLECTION_HAS_EVALUATION_DATA"
    assert exc_info.value.detail["evaluation_dataset_count"] == 1
    assert vector_repo.deleted == []
    assert repo.get_by_id(collection.collection_id) is not None
    assert repo.db.execute_query(
        "SELECT COUNT(*) AS count FROM tb_eval_datasets WHERE collection_id = ?",
        (collection.collection_id,),
    )[0]["count"] == 1
    assert repo.db.execute_query(
        "SELECT is_active FROM tb_collections WHERE collection_id = ?",
        (collection.collection_id,),
    )[0]["is_active"] == 1


@pytest.mark.parametrize("job_status", ["queued", "running"])
def test_collection_delete_with_active_ingest_job_returns_409_before_changes(
    tmp_path, monkeypatch, job_status
):
    from fastapi import HTTPException
    from app.routes import collections as collections_route

    db_path = tmp_path / "collections.db"
    repo = CollectionRepository(str(db_path))
    insert_user(repo)
    collection = repo.create(
        "Manual",
        created_by="user01",
        qdrant_name="user01_Manual",
    )
    repo.db.execute_update(
        """
        INSERT INTO tb_ingest_jobs
            (job_id, status, current_step, request_json, created_by)
        VALUES (?, ?, 'queued', ?, 'user01')
        """,
        (
            f"job-{job_status}",
            job_status,
            json.dumps({"collection_name": "user01_Manual"}),
        ),
    )

    vector_repo = FakeCollectionVectorRepository(exists=True)
    service = make_collection_service(db_path, vector_repo)
    monkeypatch.setattr(
        collections_route,
        "get_settings",
        lambda: SimpleNamespace(sqlite_db_path="", instance_dir=str(db_path)),
    )
    monkeypatch.setattr(collections_route, "CollectionService", lambda: service)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            collections_route.delete_collection(
                collection.collection_id,
                principal={"user_id": "user01", "is_admin": False},
            )
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["error_code"] == "COLLECTION_HAS_RUNNING_JOB"
    assert exc_info.value.detail["active_ingest_job_count"] == 1
    assert vector_repo.deleted == []
    assert repo.get_by_id(collection.collection_id) is not None
    assert repo.db.execute_query(
        "SELECT is_active FROM tb_collections WHERE collection_id = ?",
        (collection.collection_id,),
    )[0]["is_active"] == 1


def test_collection_delete_with_generating_dataset_returns_409_before_changes(
    tmp_path, monkeypatch
):
    from fastapi import HTTPException
    from app.routes import collections as collections_route

    db_path = tmp_path / "collections.db"
    repo = CollectionRepository(str(db_path))
    insert_user(repo)
    collection = repo.create(
        "Manual",
        created_by="user01",
        qdrant_name="user01_Manual",
    )
    repo.db.execute_update(
        """
        INSERT INTO tb_eval_datasets (name, collection_id, status, created_by)
        VALUES ('Generating evaluation', ?, 'generating', 'user01')
        """,
        (collection.collection_id,),
    )

    vector_repo = FakeCollectionVectorRepository(exists=True)
    service = make_collection_service(db_path, vector_repo)
    monkeypatch.setattr(
        collections_route,
        "get_settings",
        lambda: SimpleNamespace(sqlite_db_path="", instance_dir=str(db_path)),
    )
    monkeypatch.setattr(collections_route, "CollectionService", lambda: service)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            collections_route.delete_collection(
                collection.collection_id,
                principal={"user_id": "user01", "is_admin": False},
            )
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["error_code"] == "COLLECTION_HAS_RUNNING_JOB"
    assert exc_info.value.detail["generating_dataset_count"] == 1
    assert vector_repo.deleted == []
    assert repo.db.execute_query(
        "SELECT is_active FROM tb_collections WHERE collection_id = ?",
        (collection.collection_id,),
    )[0]["is_active"] == 1


@pytest.mark.parametrize("run_status", ["pending", "running"])
def test_collection_delete_with_active_eval_run_returns_409_before_changes(
    tmp_path, monkeypatch, run_status
):
    from fastapi import HTTPException
    from app.routes import collections as collections_route

    db_path = tmp_path / "collections.db"
    repo = CollectionRepository(str(db_path))
    insert_user(repo)
    collection = repo.create(
        "Manual",
        created_by="user01",
        qdrant_name="user01_Manual",
    )
    repo.db.execute_update(
        """
        INSERT INTO tb_eval_datasets (name, collection_id, status, created_by)
        VALUES ('Manual evaluation', ?, 'finalized', 'user01')
        """,
        (collection.collection_id,),
    )
    dataset_id = repo.db.execute_query(
        "SELECT dataset_id FROM tb_eval_datasets WHERE collection_id = ?",
        (collection.collection_id,),
    )[0]["dataset_id"]
    repo.db.execute_update(
        """
        INSERT INTO tb_eval_goldsets
            (dataset_id, version, item_count, items_snapshot_json, created_by)
        VALUES (?, 1, 0, '[]', 'user01')
        """,
        (dataset_id,),
    )
    goldset_id = repo.db.execute_query(
        "SELECT goldset_id FROM tb_eval_goldsets WHERE dataset_id = ?",
        (dataset_id,),
    )[0]["goldset_id"]
    repo.db.execute_update(
        """
        INSERT INTO tb_eval_runs
            (goldset_id, run_type, status, created_by)
        VALUES (?, 'retrieval', ?, 'user01')
        """,
        (goldset_id, run_status),
    )

    vector_repo = FakeCollectionVectorRepository(exists=True)
    service = make_collection_service(db_path, vector_repo)
    monkeypatch.setattr(
        collections_route,
        "get_settings",
        lambda: SimpleNamespace(sqlite_db_path="", instance_dir=str(db_path)),
    )
    monkeypatch.setattr(collections_route, "CollectionService", lambda: service)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            collections_route.delete_collection(
                collection.collection_id,
                principal={"user_id": "user01", "is_admin": False},
            )
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["error_code"] == "COLLECTION_HAS_RUNNING_JOB"
    assert exc_info.value.detail["running_eval_run_count"] == 1
    assert vector_repo.deleted == []
    assert repo.db.execute_query(
        "SELECT is_active FROM tb_collections WHERE collection_id = ?",
        (collection.collection_id,),
    )[0]["is_active"] == 1


def test_collection_delete_rolls_back_rdb_changes_on_metadata_delete_failure(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "collections.db"
    repo = CollectionRepository(str(db_path))
    insert_user(repo)
    collection = repo.create(
        "Manual",
        created_by="user01",
        qdrant_name="user01_Manual",
    )
    repo.db.execute_update(
        """
        INSERT INTO tb_documents
            (document_id, collection_id, source_path, security_level, status)
        VALUES ('doc-01', ?, '/tmp/manual.pdf', 'public', 'ready')
        """,
        (collection.collection_id,),
    )
    service = make_collection_service(
        db_path, FakeCollectionVectorRepository(exists=False)
    )

    def fail_collection_delete(collection_id, conn=None):
        raise RuntimeError("forced metadata delete failure")

    monkeypatch.setattr(service.collection_repo, "delete", fail_collection_delete)

    with pytest.raises(RuntimeError, match="forced metadata delete failure"):
        service.delete_collection(collection.collection_id)

    assert repo.get_by_id(collection.collection_id) is not None
    assert repo.db.execute_query(
        "SELECT COUNT(*) AS count FROM tb_documents WHERE document_id = 'doc-01'"
    )[0]["count"] == 1


def test_collection_delete_reconciles_when_qdrant_collection_is_already_absent(
    tmp_path,
):
    db_path = tmp_path / "collections.db"
    repo = CollectionRepository(str(db_path))
    insert_user(repo)
    collection = repo.create(
        "Manual",
        created_by="user01",
        qdrant_name="user01_Manual",
    )
    vector_repo = FakeCollectionVectorRepository(exists=False)
    service = make_collection_service(db_path, vector_repo)

    result = service.delete_collection(collection.collection_id)

    assert result["reconciled"] is True
    assert repo.get_by_id(collection.collection_id) is None


def test_collection_delete_route_returns_verified_result(tmp_path, monkeypatch):
    from app.routes import collections as collections_route

    db_path = tmp_path / "collections.db"
    repo = CollectionRepository(str(db_path))
    insert_user(repo)
    collection = repo.create(
        "Manual",
        created_by="user01",
        qdrant_name="user01_Manual",
    )
    repo.db.execute_update(
        """
        INSERT INTO tb_documents
            (document_id, collection_id, uploaded_by, source_path,
             security_level, status)
        VALUES ('doc-01', ?, 'user01', '/tmp/manual.pdf', 'public', 'ready')
        """,
        (collection.collection_id,),
    )
    vector_repo = SuccessfulCollectionVectorRepository(exists=True)
    service = make_collection_service(db_path, vector_repo)
    monkeypatch.setattr(
        collections_route,
        "get_settings",
        lambda: SimpleNamespace(sqlite_db_path="", instance_dir=str(db_path)),
    )
    monkeypatch.setattr(collections_route, "CollectionService", lambda: service)

    response = asyncio.run(
        collections_route.delete_collection(
            collection.collection_id,
            principal={"user_id": "user01", "is_admin": False},
        )
    )

    assert response["status"] == "deleted"
    assert response["deleted_document_count"] == 1
    assert response["qdrant_collection_deleted"] is True
    assert response["remaining_qdrant_collection"] is False
    assert response["reconciled"] is False
    assert repo.get_by_id(collection.collection_id) is None

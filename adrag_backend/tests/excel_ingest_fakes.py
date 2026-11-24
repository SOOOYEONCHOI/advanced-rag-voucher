"""엑셀 적재 테스트용 IngestService 조립 도우미 (2026.10.01 Phase 2).

외부 서버(임베딩·Qdrant)만 가짜로 바꾸고 DB(PostgreSQL 테스트 DB)·resource 저장소·청크 변환은 실제 경로를 쓴다.
"""
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

from app.models.data_models import CollectionConfig
from app.repositories.database import get_database_manager
from app.repositories.document_repository import DocumentRepository
from app.repositories.ingest_record_repository import IngestRecordRepository
from app.repositories.spreadsheet_resource_repository import SpreadsheetResourceRepository
from app.services.ingest_service import ChunkResultWriter, IngestService
from app.services.spreadsheet_resource_service import SpreadsheetResourceService


def _real_class(relative_path: str, name: str, imported):
    """sys.modules가 stub으로 바뀌어 있으면(object 등) 원본 파일에서 클래스를 다시 읽는다."""
    if isinstance(imported, type) and imported is not object and hasattr(imported, "__init__"):
        module = getattr(imported, "__module__", "")
        if module and module.startswith("app."):
            return imported
    import importlib.util

    path = Path(__file__).resolve().parents[1] / relative_path
    spec = importlib.util.spec_from_file_location(f"_real_{Path(relative_path).stem}", path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return getattr(loaded, name)


class FakeEmbeddingClient:
    async def embed_texts(self, texts):
        return [[float(len(text) % 7) + 1.0, 0.5, 0.25] for text in texts]


class FakeKiwiEncoder:
    version = "test-1"

    def encode_document(self, text):
        from qdrant_client.models import SparseVector

        return SparseVector(indices=[1, 2], values=[1.0, 0.5])

    def normalize_document(self, text):
        return text


class FakeVectorRepository:
    def __init__(self):
        self.points: dict[str, list] = {}

    def ensure_collection(self, collection_name, vector_size):
        self.points.setdefault(collection_name, [])

    def upsert_points(self, collection_name, points, batch_size=None):
        by_id = {p.id: p for p in self.points.setdefault(collection_name, [])}
        by_id.update({p.id: p for p in points})
        self.points[collection_name] = list(by_id.values())

    def delete_by_document_id(self, document_id, collection_name):
        self.points[collection_name] = [
            p for p in self.points.get(collection_name, []) if p.payload.get("document_id") != document_id
        ]
        return True

    def delete_by_document_version(self, document_id, version, collection_name):
        self.points[collection_name] = [
            p for p in self.points.get(collection_name, [])
            if not (p.payload.get("document_id") == document_id and p.payload.get("version") == version)
        ]
        return True

    def count_by_document_id(self, document_id, collection_name):
        return sum(1 for p in self.points.get(collection_name, []) if p.payload.get("document_id") == document_id)


def ensure_collection(name: str = "documents") -> int:
    db = get_database_manager()
    rows = db.execute_query("SELECT collection_id FROM tb_collections WHERE qdrant_name=?", (name,))
    if rows:
        return rows[0][0]
    return db.execute_query(
        "INSERT INTO tb_collections (display_name, qdrant_name) VALUES (?, ?) RETURNING collection_id",
        (name, name),
    )[0][0]


def make_ingest_service(resource_root: Path, chunk_dir: Path, *, collection: str = "documents",
                        vector_repo: FakeVectorRepository | None = None) -> IngestService:
    """적재 경로 전체를 타는 IngestService (외부 서버만 가짜)."""
    collection_id = ensure_collection(collection)
    db = get_database_manager()
    service = IngestService.__new__(IngestService)
    service.settings = SimpleNamespace(
        kiwi_bm25_vector_name="kiwi_bm25",
        enable_semantic_enrichment=False,
    )
    service.db = db
    # 2026.10.16 수정 - test_stats_api 등이 수집 시 sys.modules의 document_repository를 stub(object)으로
    #   바꿔 끼우므로, stub이면 원본 파일에서 직접 읽는다(전체 실행 순서 의존 방지).
    service.doc_repo = _real_class(
        "app/repositories/document_repository.py", "DocumentRepository", DocumentRepository
    )()
    service.record_repo = IngestRecordRepository(db=db)
    config = CollectionConfig(
        collection_id=collection_id, display_name=collection, qdrant_name=collection, is_active=True
    )
    service.collection_repo = SimpleNamespace(
        get_by_qdrant_name=lambda name: config if name == collection else None,
        get_by_display_name=lambda name: None,
        get_by_id=lambda cid: config if cid == collection_id else None,
    )
    service.embedding_client = FakeEmbeddingClient()
    service.kiwi_bm25_encoder = FakeKiwiEncoder()
    service.sparse_encoder = SimpleNamespace(is_enabled=False)
    service.vector_repo = vector_repo or FakeVectorRepository()
    service._chunk_writer = ChunkResultWriter(chunk_dir)

    async def save(src, filename, document_id, version=1):
        suffix = f"_v{version}" if version > 1 else ""
        return f"stored_{document_id}{suffix}", f"instance/data/{document_id}{suffix}", os.path.getsize(src)

    service._file_manager = SimpleNamespace(save=save, delete=lambda path: None)
    service.resource_service = SpreadsheetResourceService(
        root=resource_root,
        repository=SpreadsheetResourceRepository(db=db),
        max_upload_bytes=10 * 1024 * 1024,
    )
    return service

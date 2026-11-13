# 2026.06.16(sooyeon.choi) 추가 - tb_documents / tb_document_events Repository (신규)
#   tb_ingest_documents + tb_document_history 대체
"""
Document repository for tb_documents and tb_document_events (v4 schema).
"""

import json
import logging
from typing import Any, Dict, List, Optional

from app.models.data_models import DocumentEvent, DocumentMetadata, DocumentStatus
from app.repositories.database import get_database_manager
from app.utils.datetime import now_kst_iso

logger = logging.getLogger(__name__)

_DOC_SELECT = (
    "SELECT document_id, collection_id, uploaded_by, original_filename, stored_filename, "
    "source_path, file_size, doc_type, requested_doc_type, doc_type_source, title, file_format, security_level, parser_type, "
    "total_pages, chunk_count, version_no, status, error_message, "
    "content_updated_at, created_at, updated_at, deleted_at, "
    # 2026.10.19 추가 - 모델명
    "product_model "
    "FROM tb_documents"
)


def _row_to_metadata(row) -> DocumentMetadata:
    return DocumentMetadata(
        document_id=row["document_id"],
        collection_id=row["collection_id"],
        source_path=row["source_path"],
        uploaded_by=row["uploaded_by"],
        original_filename=row["original_filename"],
        stored_filename=row["stored_filename"],
        file_size=row["file_size"],
        doc_type=row["doc_type"],
        requested_doc_type=row["requested_doc_type"] or "auto",
        doc_type_source=row["doc_type_source"],
        title=row["title"],
        file_format=row["file_format"],
        security_level=row["security_level"] or "public",
        parser_type=row["parser_type"],
        total_pages=row["total_pages"],
        chunk_count=row["chunk_count"],
        version_no=row["version_no"] or 1,
        status=row["status"] or DocumentStatus.PENDING,
        error_message=row["error_message"],
        content_updated_at=row["content_updated_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        deleted_at=row["deleted_at"],
    )


class DocumentRepository:
    """tb_documents + tb_document_events CRUD Repository."""

    def __init__(self):
        self.db = get_database_manager()
        logger.debug("DocumentRepository initialized")

    # ── tb_documents 생성 ────────────────────────────────────────────────────

    def store(self, metadata: DocumentMetadata) -> bool:
        """문서 메타데이터를 tb_documents에 INSERT한다."""
        now = now_kst_iso()
        try:
            self.db.execute_update(
                """
                INSERT INTO tb_documents (
                    document_id, collection_id, uploaded_by,
                    original_filename, stored_filename, source_path, file_size,
                    doc_type, requested_doc_type, doc_type_source, title, file_format, security_level,
                    parser_type, total_pages, chunk_count, version_no,
                    status, error_message, content_updated_at,
                    created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    metadata.document_id,
                    metadata.collection_id,
                    metadata.uploaded_by,
                    metadata.original_filename,
                    metadata.stored_filename,
                    metadata.source_path,
                    metadata.file_size,
                    metadata.doc_type,
                    metadata.requested_doc_type or "auto",
                    metadata.doc_type_source,
                    metadata.title,
                    metadata.file_format,
                    metadata.security_level or "public",
                    metadata.parser_type,
                    metadata.total_pages,
                    metadata.chunk_count,
                    metadata.version_no or 1,
                    metadata.status or DocumentStatus.PENDING,
                    metadata.error_message,
                    metadata.content_updated_at or now,
                    metadata.created_at or now,
                    metadata.updated_at or now,
                ),
            )
            logger.info("Document stored: %s", metadata.document_id)
            return True
        except Exception as e:
            logger.error("Document store failed: %s", e)
            return False

    # ── 조회 ─────────────────────────────────────────────────────────────────

    def get_by_id(self, document_id: str, include_deleted: bool = False) -> Optional[DocumentMetadata]:
        where = "WHERE document_id = ?" + ("" if include_deleted else " AND deleted_at IS NULL")
        rows = self.db.execute_query(f"{_DOC_SELECT} {where}", (document_id,))
        return _row_to_metadata(rows[0]) if rows else None

    def update_review_due_at(self, document_id: str, review_due_at: str) -> bool:
        """관리자가 지정한 문서 검토기한을 갱신한다."""
        return bool(self.db.execute_update(
            "UPDATE tb_documents SET review_due_at=?, updated_at=? WHERE document_id=? AND deleted_at IS NULL",
            (review_due_at, now_kst_iso(), document_id),
        ))

    def list_by_collection(
        self,
        collection_id: int,
        include_deleted: bool = False,
        security_level: str = None,
        doc_type: str = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """컬렉션별 문서 목록 (필터 + 페이지네이션)."""
        conditions = ["collection_id = ?"]
        params: list = [collection_id]
        if not include_deleted:
            conditions.append("deleted_at IS NULL")
        if security_level:
            conditions.append("security_level = ?")
            params.append(security_level)
        if doc_type:
            conditions.append("doc_type = ?")
            params.append(doc_type)
        where = "WHERE " + " AND ".join(conditions)
        rows = self.db.execute_query(
            f"{_DOC_SELECT} {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            tuple(params) + (limit, offset),
        )
        return [
            {
                "document_id": r["document_id"],
                "collection_id": r["collection_id"],
                "original_filename": r["original_filename"],
                "doc_type": r["doc_type"],
                "security_level": r["security_level"],
                "status": r["status"],
                "total_pages": r["total_pages"],
                "chunk_count": r["chunk_count"],
                "parser_type": r["parser_type"],
                "uploaded_by": r["uploaded_by"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
                # 2026.10.19 추가 - 모델명·현재 버전
                "product_model": r["product_model"],
                "version_no": r["version_no"],
            }
            for r in rows
        ]

    # ── 모델명 수정 ───────────────────────────────────────

    def update_product_model(
        self, document_id: str, product_model: str, actor_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """모델명만 바꾼다. 버전·청크·Qdrant는 건드리지 않는다(재파싱·재임베딩 없음).

        값이 바뀐 경우에만 updated_at(최근 변경일)을 갱신하고 tb_document_events에 'update' 이력을 남긴다.
        문서가 없거나 삭제됐으면 None.
        """
        with self.db.get_connection():
            rows = self.db.execute_query(
                "SELECT document_id, collection_id, product_model FROM tb_documents "
                "WHERE document_id = ? AND deleted_at IS NULL FOR UPDATE",
                (document_id,),
            )
            if not rows:
                return None
            before = rows[0]["product_model"]
            if before != product_model:
                self.db.execute_update(
                    "UPDATE tb_documents SET product_model = ?, updated_at = now() WHERE document_id = ?",
                    (product_model, document_id),
                )
                self.db.execute_update(
                    """INSERT INTO tb_document_events
                           (document_id, collection_id, event_type, event_message, actor_id, snapshot_json)
                       VALUES (?, ?, 'update', ?, (SELECT user_id FROM tb_users WHERE user_id = ?), ?)""",
                    (
                        document_id, rows[0]["collection_id"], "모델명 수정", actor_id,
                        json.dumps({"field": "product_model", "before": before, "after": product_model},
                                   ensure_ascii=False),
                    ),
                )
            result = self.db.execute_query(
                "SELECT document_id, product_model, version_no, updated_at FROM tb_documents WHERE document_id = ?",
                (document_id,),
            )
        return dict(result[0])

    # ── 삭제 ─────────────────────────────────────────────────────────────────

    def soft_delete(self, document_id: str) -> bool:
        """논리 삭제: deleted_at 설정 + status='deleted'."""
        now = now_kst_iso()
        affected = self.db.execute_update(
            "UPDATE tb_documents SET deleted_at=?, status='deleted', updated_at=? WHERE document_id=?",
            (now, now, document_id),
        )
        return affected > 0

    # ── tb_document_events ────────────────────────────────────────────────────

    def record_event(self, event: DocumentEvent) -> bool:
        """문서 처리 이벤트 이력을 tb_document_events에 INSERT한다."""
        now = now_kst_iso()
        try:
            self.db.execute_update(
                """
                INSERT INTO tb_document_events
                    (document_id, collection_id, event_type, event_message,
                     actor_id, event_at, snapshot_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.document_id,
                    event.collection_id,
                    event.event_type,
                    event.event_message,
                    event.actor_id,
                    event.event_at or now,
                    event.snapshot_json,
                ),
            )
            return True
        except Exception as e:
            logger.error("Document event record failed: %s", e)
            return False


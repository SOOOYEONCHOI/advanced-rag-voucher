"""문서 버전·청크·사진 배치·흐름도 기록 (2026.10.16 Phase 2, Alembic 0003).

설계: docs/design/reports/phase-2-plan.md P2-4·P2-6~P2-10·P2-13
- 적재 1회 = 버전 1행(현재는 v1·active) + 청크 N행(Qdrant 포인트와 1:1) + 청크↔사진 연결 + 흐름도.
- 모든 쓰기는 호출자가 연 트랜잭션(``DatabaseManager.get_connection``) 안에서 문서 행 저장과 함께 실행된다.
  (이전 계보의 같은 이름 파일은 doc_key 자동 개정 판단을 포함해 D-01과 맞지 않아 새로 썼다.)
"""
from __future__ import annotations

import json
from typing import Any, Iterable, Optional

from app.repositories.database import DatabaseManager, get_database_manager


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


_CHUNK_COLUMNS = (
    "chunk_id", "document_id", "version_no", "collection_id", "point_id", "source_key", "part_no",
    "point_type", "content_type", "section_type", "sheet_name", "source_range", "step_no", "chunk_text", "meta_json",
)
_RESOURCE_COLUMNS = (
    "resource_id", "document_id", "parse_job_id", "resource_type", "resource_path", "content_hash", "mime_type",
    "file_size", "sheet_name", "from_cell", "to_cell", "surrounding_range", "surrounding_text", "status",
    "version_no", "role_cd", "section_type", "step_no", "step_title", "anchor_type", "in_print_area",
    "overlay_json", "link_method", "link_confidence", "review_status",
)


class IngestRecordRepository:
    def __init__(self, db: Optional[DatabaseManager] = None) -> None:
        self.db = db or get_database_manager()

    # ── 문서 보조 정보 ───────────────────────────────────────────────────────

    def update_document_info(self, document_id: str, *, doc_key: Optional[str], product_model: Optional[str]) -> None:
        self.db.execute_update(
            "UPDATE tb_documents SET doc_key = ?, product_model = ?, active_activated_at = now() WHERE document_id = ?",
            (doc_key, product_model or None, document_id),
        )

    # ── 버전 (P2-6) ─────────────────────────────────────────────────────────

    def create_active_version(self, document_id: str, version_no: int, **fields: Any) -> None:
        """버전 행을 active로 만든다. 개정본 전환(이전 active → retired)은 Phase 3."""
        self.db.execute_update(
            """INSERT INTO tb_document_versions (
                   document_id, version_no, status, activated_at, processing_engine, file_sha256,
                   original_filename, stored_filename, source_path, file_size, file_format, parser_type,
                   total_pages, chunk_count, revision_label, md_dir, summary_json, warnings_json,
                   job_id, uploaded_by)
               VALUES (?, ?, 'active', now(), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                       -- 작업·사용자 행이 없으면(직접 호출·테스트) FK 대신 NULL
                       (SELECT job_id FROM tb_ingest_jobs WHERE job_id = ?),
                       (SELECT user_id FROM tb_users WHERE user_id = ?))""",
            (
                document_id, version_no, fields.get("processing_engine"), fields.get("file_sha256"),
                fields.get("original_filename"), fields.get("stored_filename"), fields["source_path"],
                fields.get("file_size"), fields.get("file_format"), fields.get("parser_type"),
                fields.get("total_pages"), fields.get("chunk_count"), fields.get("revision_label"),
                fields.get("md_dir"), _dump(fields.get("summary_json") or {}),
                _dump(fields.get("warnings_json") or []), fields.get("job_id"), fields.get("uploaded_by"),
            ),
        )

    def retire_document_versions(self, document_id: str) -> int:
        """문서 삭제(soft delete) 시 버전을 retired로 둔다(감사용 행은 남김)."""
        # 2026.10.19 수정 - 문서 삭제는 모든 포인트를 지우므로 정리 완료 시각도 함께 기록
        return self.db.execute_update(
            "UPDATE tb_document_versions SET status = 'retired', retired_at = coalesce(retired_at, now()), "
            "vectors_purged_at = coalesce(vectors_purged_at, now()) "
            "WHERE document_id = ? AND (status <> 'retired' OR vectors_purged_at IS NULL)",
            (document_id,),
        )

    # ── 최신본 변경 ─────────────
    #   building(접수) → ready(새 포인트 저장·검증 완료) → active(한 트랜잭션으로 전환, 이전 active는 retired)
    #   실패하면 failed. 처리 중 버전은 문서마다 1개(uq_doc_versions_in_progress).

    def lock_document(self, document_id: str) -> None:
        """같은 문서의 버전 접수·전환을 직렬화한다(트랜잭션 끝까지 유지, D-01 pg_advisory_xact_lock)."""
        self.db.execute_query("SELECT pg_advisory_xact_lock(hashtext(?))", (f"doc-version:{document_id}",))

    def in_progress_version(self, document_id: str) -> Optional[dict[str, Any]]:
        rows = self.db.execute_query(
            "SELECT version_no, status, job_id FROM tb_document_versions "
            "WHERE document_id = ? AND status IN ('building', 'ready')",
            (document_id,),
        )
        return dict(rows[0]) if rows else None

    def next_version_no(self, document_id: str) -> int:
        return int(self.db.execute_query(
            "SELECT coalesce(max(version_no), 0) + 1 FROM tb_document_versions WHERE document_id = ?",
            (document_id,),
        )[0][0])

    def active_version_sha(self, document_id: str) -> Optional[str]:
        rows = self.db.execute_query(
            "SELECT file_sha256 FROM tb_document_versions WHERE document_id = ? AND status = 'active'",
            (document_id,),
        )
        return rows[0][0] if rows else None

    def create_building_version(self, document_id: str, version_no: int, **fields: Any) -> None:
        """최신본 변경 접수: 새 버전 행을 building으로 만든다(파일 경로·처리 결과는 전환 때 채움)."""
        self.db.execute_update(
            """INSERT INTO tb_document_versions (
                   document_id, version_no, status, original_filename, file_sha256, file_size, source_path,
                   job_id, uploaded_by)
               VALUES (?, ?, 'building', ?, ?, ?, '',
                       (SELECT job_id FROM tb_ingest_jobs WHERE job_id = ?),
                       (SELECT user_id FROM tb_users WHERE user_id = ?))""",
            (
                document_id, version_no, fields.get("original_filename"), fields.get("file_sha256"),
                fields.get("file_size"), fields.get("job_id"), fields.get("uploaded_by"),
            ),
        )

    def set_version_status(
        self, document_id: str, version_no: int, status: str, *, vectors_purged: Optional[bool] = None,
        from_statuses: tuple[str, ...] = ("building", "ready", "failed"),
    ) -> int:
        """처리 중 버전의 상태를 바꾼다(active·retired 행은 건드리지 않음)."""
        purged_sql = ""
        if vectors_purged is True:
            purged_sql = ", vectors_purged_at = coalesce(vectors_purged_at, now())"
        elif vectors_purged is False:
            purged_sql = ", vectors_purged_at = NULL"
        placeholders = ", ".join("?" for _ in from_statuses)
        return self.db.execute_update(
            f"UPDATE tb_document_versions SET status = ?{purged_sql} "
            f"WHERE document_id = ? AND version_no = ? AND status IN ({placeholders})",
            (status, document_id, version_no, *from_statuses),
        )

    def set_version_source(self, document_id: str, version_no: int, source_path: str, stored_filename: Optional[str]) -> None:
        """실패한 버전도 저장한 원본 경로를 남긴다(이력 표시·문서 삭제 시 파일 정리)."""
        self.db.execute_update(
            "UPDATE tb_document_versions SET source_path = ?, stored_filename = coalesce(?, stored_filename) "
            "WHERE document_id = ? AND version_no = ? AND source_path = ''",
            (source_path, stored_filename, document_id, version_no),
        )

    def activate_version(self, document_id: str, version_no: int, **fields: Any) -> None:
        """새 버전을 active로 전환하고 이전 active를 retired로 둔다. 호출자 트랜잭션 안에서 실행.

        문서가 삭제됐거나 새 버전이 처리 중 상태가 아니면 RuntimeError(트랜잭션 롤백 → 기존 최신본 유지).
        """
        self.lock_document(document_id)
        doc = self.db.execute_query(
            "SELECT version_no FROM tb_documents WHERE document_id = ? AND deleted_at IS NULL FOR UPDATE",
            (document_id,),
        )
        if not doc:
            raise RuntimeError("최신본을 바꿀 문서가 없거나 삭제되었습니다.")
        state = self.db.execute_query(
            "SELECT status FROM tb_document_versions WHERE document_id = ? AND version_no = ? FOR UPDATE",
            (document_id, version_no),
        )
        if not state or state[0][0] not in ("building", "ready"):
            raise RuntimeError(f"v{version_no}은 전환할 수 있는 상태가 아닙니다.")
        self.db.execute_update(
            "UPDATE tb_document_versions SET status = 'retired', retired_at = now() "
            "WHERE document_id = ? AND status = 'active'",
            (document_id,),
        )
        self.db.execute_update(
            """UPDATE tb_document_versions SET
                   status = 'active', activated_at = now(), processing_engine = ?, file_sha256 = coalesce(?, file_sha256),
                   original_filename = ?, stored_filename = ?, source_path = ?, file_size = ?, file_format = ?,
                   parser_type = ?, total_pages = ?, chunk_count = ?, md_dir = ?, summary_json = ?,
                   vectors_purged_at = NULL
               WHERE document_id = ? AND version_no = ?""",
            (
                fields.get("processing_engine"), fields.get("file_sha256"), fields.get("original_filename"),
                fields.get("stored_filename"), fields["source_path"], fields.get("file_size"),
                fields.get("file_format"), fields.get("parser_type"), fields.get("total_pages"),
                fields.get("chunk_count"), fields.get("md_dir"), _dump(fields.get("summary_json") or {}),
                document_id, version_no,
            ),
        )
        # 문서 행: 표시 정보·활성 버전만 갱신. 모델명(product_model)·doc_key·업로더·대화 주제는 유지
        self.db.execute_update(
            """UPDATE tb_documents SET
                   version_no = ?, original_filename = ?, stored_filename = ?, source_path = ?, file_size = ?,
                   doc_type = ?, requested_doc_type = ?, doc_type_source = ?, title = ?, file_format = ?,
                   parser_type = ?, total_pages = ?, chunk_count = ?, status = 'ready', error_message = NULL,
                   active_activated_at = now(), content_updated_at = now(), updated_at = now()
               WHERE document_id = ?""",
            (
                version_no, fields.get("original_filename"), fields.get("stored_filename"), fields["source_path"],
                fields.get("file_size"), fields.get("doc_type"), fields.get("requested_doc_type") or "auto",
                fields.get("doc_type_source"), fields.get("title"), fields.get("file_format"),
                fields.get("parser_type"), fields.get("total_pages"), fields.get("chunk_count"), document_id,
            ),
        )

    def mark_inactive_versions_purged(self, document_id: str) -> int:
        """활성 버전을 뺀 나머지 포인트를 지운 뒤 호출 — 검색 제외 조건에서 빠진다."""
        return self.db.execute_update(
            """UPDATE tb_document_versions v SET vectors_purged_at = now()
               FROM tb_documents d
               WHERE d.document_id = v.document_id AND v.document_id = ? AND v.version_no <> d.version_no
                 AND v.status IN ('retired', 'failed') AND v.vectors_purged_at IS NULL""",
            (document_id,),
        )

    def documents_needing_purge(self) -> list[tuple[str, int, str]]:
        """(document_id, 활성 version_no, qdrant 컬렉션) — 이전 버전 포인트 정리를 다시 시도할 문서."""
        rows = self.db.execute_query(
            """SELECT DISTINCT d.document_id, d.version_no, c.qdrant_name
               FROM tb_document_versions v
               JOIN tb_documents d ON d.document_id = v.document_id AND d.deleted_at IS NULL
               JOIN tb_collections c ON c.collection_id = d.collection_id
               WHERE v.version_no <> d.version_no AND v.status IN ('retired', 'failed')
                 AND v.vectors_purged_at IS NULL"""
        )
        return [(r[0], int(r[1]), r[2]) for r in rows]

    def list_versions(self, document_id: str) -> list[dict[str, Any]]:
        rows = self.db.execute_query(
            """SELECT v.version_no, v.status, v.original_filename, v.file_size, v.file_format, v.parser_type,
                      v.processing_engine, v.total_pages, v.chunk_count, v.uploaded_by, v.job_id,
                      v.created_at, v.activated_at, v.retired_at, j.status AS job_status, j.error_message
               FROM tb_document_versions v
               LEFT JOIN tb_ingest_jobs j ON j.job_id = v.job_id
               WHERE v.document_id = ?
               ORDER BY v.version_no DESC""",
            (document_id,),
        )
        return [dict(r) for r in rows]

    # ── 청크 (P2-7) ─────────────────────────────────────────────────────────

    def insert_chunks(self, rows: Iterable[dict[str, Any]]) -> int:
        params = [
            tuple(_dump(row.get(c) or {}) if c == "meta_json" else row.get(c) for c in _CHUNK_COLUMNS)
            for row in rows
        ]
        if not params:
            return 0
        return self.db.execute_many(
            f"INSERT INTO tb_chunks ({', '.join(_CHUNK_COLUMNS)}) VALUES ({', '.join('?' for _ in _CHUNK_COLUMNS)})",
            params,
        )

    def delete_document_chunks(self, document_id: str) -> int:
        """문서 삭제 시 청크·연결·흐름도 행을 지운다(Qdrant 포인트는 호출자가 지움)."""
        deleted = self.db.execute_update("DELETE FROM tb_chunks WHERE document_id = ?", (document_id,))
        self.db.execute_update("DELETE FROM tb_flow_graphs WHERE document_id = ?", (document_id,))
        return deleted

    # ── 청크↔사진 (P2-8) ───────────────────────────────────────────────────

    def insert_chunk_resources(self, links: Iterable[tuple[str, str, int]]) -> int:
        """(chunk_id, resource_id, sort_order). 확정 리소스가 없는 연결은 건너뛴다(FK)."""
        params = list(links)
        if not params:
            return 0
        return self.db.execute_many(
            """INSERT INTO tb_chunk_resources (chunk_id, resource_id, sort_order)
               SELECT ?, ?, ? WHERE EXISTS (SELECT 1 FROM tb_spreadsheet_resources r WHERE r.resource_id = ?)
               ON CONFLICT DO NOTHING""",
            [(chunk_id, resource_id, order, resource_id) for chunk_id, resource_id, order in params],
        )

    # ── 사진 배치 (P2-4, excel_ingest 경로) ───────────────────────────────────

    def insert_resources(self, rows: Iterable[dict[str, Any]]) -> int:
        params = [
            tuple(_dump(row.get(c) or {}) if c == "overlay_json" else row.get(c) for c in _RESOURCE_COLUMNS)
            for row in rows
        ]
        if not params:
            return 0
        return self.db.execute_many(
            f"INSERT INTO tb_spreadsheet_resources ({', '.join(_RESOURCE_COLUMNS)}) "
            f"VALUES ({', '.join('?' for _ in _RESOURCE_COLUMNS)})",
            params,
        )

    # ── 흐름도 (P2-10) ─────────────────────────────────────────────────────

    def insert_flow_graphs(self, document_id: str, version_no: int, graphs: Iterable[dict[str, Any]]) -> int:
        params = [
            (
                document_id, version_no, graph["sheet_name"], _dump(graph.get("nodes") or []),
                _dump(graph.get("edges") or []), _dump(graph.get("unresolved") or []),
                graph.get("source_hash"), graph.get("vlm_status"), graph.get("review_status") or "needs_review",
            )
            for graph in graphs
        ]
        if not params:
            return 0
        return self.db.execute_many(
            """INSERT INTO tb_flow_graphs (document_id, version_no, sheet_name, nodes_json, edges_json,
                                           unresolved_json, source_hash, vlm_status, review_status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            params,
        )

    # ── 조회 (검증·테스트·문서 상세) ─────────────────────────────────────────

    def count_by_document(self, document_id: str) -> dict[str, int]:
        row = self.db.execute_query(
            """SELECT
                 (SELECT count(*) FROM tb_document_versions WHERE document_id = ?) AS versions,
                 (SELECT count(*) FROM tb_chunks WHERE document_id = ?) AS chunks,
                 (SELECT count(*) FROM tb_chunk_resources cr JOIN tb_chunks c ON c.chunk_id = cr.chunk_id
                   WHERE c.document_id = ?) AS chunk_resources,
                 (SELECT count(*) FROM tb_flow_graphs WHERE document_id = ?) AS flow_graphs,
                 (SELECT count(*) FROM tb_spreadsheet_resources WHERE document_id = ? AND status <> 'deleted')
                   AS resources""",
            (document_id,) * 5,
        )[0]
        return {key: int(row[key]) for key in row.keys()}

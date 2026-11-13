"""문서 버전·청크·사진 배치·흐름도 기록 (2026.10.16 Phase 2, Alembic 0003).

설계: docs/design/reports/phase-2-plan.md
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


# 2026.11.06(sooyeon.choi) 수정 - 복원 전환 조건 불일치(코드는 API·작업 오류 코드와 같음)
class RestoreStateError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class IngestRecordRepository:
    def __init__(self, db: Optional[DatabaseManager] = None) -> None:
        self.db = db or get_database_manager()

    # ── 문서 보조 정보 ───────────────────────────────────────────────────────

    def update_document_info(self, document_id: str, *, doc_key: Optional[str], product_model: Optional[str]) -> None:
        self.db.execute_update(
            "UPDATE tb_documents SET doc_key = ?, product_model = ?, active_activated_at = now() WHERE document_id = ?",
            (doc_key, product_model or None, document_id),
        )

    # ── 버전 ─────────────────────────────────────────────────────────

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
            "vectors_purged_at = coalesce(vectors_purged_at, now()), "
            "vector_storage_state = 'missing' "  # 2026.11.06(sooyeon.choi) 수정 - 보관 상태도 함께 기록
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
            # 2026.11.06(sooyeon.choi) 수정 - 포인트를 지웠으면 보관 상태도 missing
            purged_sql = ", vectors_purged_at = coalesce(vectors_purged_at, now()), vector_storage_state = 'missing'"
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

    def activate_version(self, document_id: str, version_no: int, **fields: Any) -> Optional[int]:
        """새 버전을 active로 전환하고 이전 active를 retired로 둔다. 호출자 트랜잭션 안에서 실행.

        문서가 삭제됐거나 새 버전이 처리 중 상태가 아니면 RuntimeError(트랜잭션 롤백 → 기존 최신본 유지).
        """
        self.lock_document(document_id)
        doc = self.db.execute_query(
            "SELECT version_no FROM tb_documents WHERE document_id = ? AND deleted_at IS NULL FOR UPDATE",
            (document_id,),
        )
        if not doc:
            raise RuntimeError("새 버전을 등록할 문서가 없거나 삭제되었습니다.")
        previous_version_no = doc[0][0]  # 2026.11.06(sooyeon.choi) 수정 - 적용 이력(from_version_no)용
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
        # 2026.11.06(sooyeon.choi) 수정 - 이 버전 작업의 점유 표식 해제(자기 소유만)
        self.db.execute_update(
            "UPDATE tb_documents SET pending_job_id = NULL WHERE document_id = ? AND pending_job_id = "
            "(SELECT job_id FROM tb_document_versions WHERE document_id = ? AND version_no = ?)",
            (document_id, document_id, version_no),
        )
        return previous_version_no

    def mark_inactive_versions_purged(self, document_id: str) -> int:
        """활성 버전을 뺀 나머지 포인트를 지운 뒤 호출 — 검색 제외 조건에서 빠진다."""
        return self.db.execute_update(
            """UPDATE tb_document_versions v SET vectors_purged_at = now(), vector_storage_state = 'missing'
               FROM tb_documents d
               WHERE d.document_id = v.document_id AND v.document_id = ? AND v.version_no <> d.version_no
                 AND v.status IN ('retired', 'failed') AND v.vectors_purged_at IS NULL""",
            (document_id,),
        )

    # 2026.11.06(sooyeon.choi) 수정 - 특정 비활성 버전 하나의 포인트를 지운 뒤 호출(보존 OFF의 즉시 정리)
    def mark_version_purged(self, document_id: str, version_no: int) -> int:
        return self.db.execute_update(
            """UPDATE tb_document_versions v SET vectors_purged_at = coalesce(v.vectors_purged_at, now()),
                   vector_storage_state = 'missing'
               FROM tb_documents d
               WHERE d.document_id = v.document_id AND v.document_id = ? AND v.version_no = ?
                 AND v.version_no <> d.version_no""",
            (document_id, version_no),
        )

    def documents_needing_purge(self) -> list[tuple[str, int, str]]:
        """(document_id, 활성 version_no, qdrant 컬렉션) — 이전 버전 포인트 정리를 다시 시도할 문서."""
        rows = self.db.execute_query(
            """SELECT DISTINCT d.document_id, d.version_no, c.qdrant_name
               FROM tb_document_versions v
               JOIN tb_documents d ON d.document_id = v.document_id AND d.deleted_at IS NULL
               JOIN tb_collections c ON c.collection_id = d.collection_id
               WHERE v.version_no <> d.version_no AND v.status IN ('retired', 'failed')
                 AND v.vectors_purged_at IS NULL
                 AND (v.status = 'failed' OR v.vector_storage_state <> 'available')"""
            # 2026.11.06(sooyeon.choi) 수정 - 봉인된(available) 정상 버전은 주기 정리에서 제외(보존 데이터 보호)
        )
        return [(r[0], int(r[1]), r[2]) for r in rows]

    def list_versions(self, document_id: str) -> list[dict[str, Any]]:
        # 2026.11.06(sooyeon.choi) 수정 - 복원 가능 여부 판정용 컬럼·등록자 이름 추가
        rows = self.db.execute_query(
            """SELECT v.version_no, v.status, v.original_filename, v.file_size, v.file_format, v.parser_type,
                      v.processing_engine, v.total_pages, v.chunk_count, v.uploaded_by, v.job_id,
                      v.created_at, v.activated_at, v.retired_at, j.status AS job_status, j.error_message,
                      v.source_path, v.vectors_purged_at, v.vector_storage_state, v.embedding_profile_id,
                      v.document_snapshot_json IS NOT NULL AS has_snapshot, v.restore_verified_at,
                      nullif(u.user_name, '') AS uploaded_by_name
               FROM tb_document_versions v
               LEFT JOIN tb_ingest_jobs j ON j.job_id = v.job_id
               LEFT JOIN tb_users u ON u.user_id = v.uploaded_by
               WHERE v.document_id = ?
               ORDER BY v.version_no DESC""",
            (document_id,),
        )
        return [dict(r) for r in rows]

    # ── 이전 버전 복원·적용 이력·점유 표식 (2026.11.06(sooyeon.choi) 수정 - UI-12 R1-5, 설계 v1.1 5·6절) ──

    def pending_job_id(self, document_id: str) -> Optional[str]:
        rows = self.db.execute_query("SELECT pending_job_id FROM tb_documents WHERE document_id = ?", (document_id,))
        return rows[0][0] if rows else None

    def acquire_pending(self, document_id: str, job_id: str) -> bool:
        """문서 변경 작업 점유(최신본 변경·복원 공통). 비어 있거나 이미 자기 것일 때만 성공. 호출자가 lock_document 아래에서 호출."""
        return bool(self.db.execute_update(
            "UPDATE tb_documents SET pending_job_id = ? WHERE document_id = ? AND deleted_at IS NULL "
            "AND (pending_job_id IS NULL OR pending_job_id = ?)",
            (job_id, document_id, job_id),
        ))

    def release_pending(self, document_id: str, job_id: str) -> int:
        """자기 소유 점유만 해제한다."""
        return self.db.execute_update(
            "UPDATE tb_documents SET pending_job_id = NULL WHERE document_id = ? AND pending_job_id = ?",
            (document_id, job_id),
        )

    def reconcile_pending(self) -> int:
        """기동 시 정합성 복구: 끝났거나 없는 작업을 가리키는 점유를 해제한다(6.4)."""
        return self.db.execute_update(
            """UPDATE tb_documents d SET pending_job_id = NULL
               WHERE d.pending_job_id IS NOT NULL
                 AND NOT EXISTS (SELECT 1 FROM tb_ingest_jobs j
                                 WHERE j.job_id = d.pending_job_id AND j.status IN ('queued', 'running'))"""
        )

    def record_activation(
        self, document_id: str, *, to_version_no: int, operation_type: str, from_version_no: Optional[int] = None,
        actor_id: Optional[str] = None, job_id: Optional[str] = None, initial: bool = False,
    ) -> dict[str, Any]:
        """적용 이력 1행. initial이면 순번 1(신규 문서), 아니면 tb_documents.activation_revision을 1 올린다.
        호출자의 전환 트랜잭션 안에서 실행한다."""
        if initial:
            revision = 1
        else:
            revision = int(self.db.execute_query(
                "UPDATE tb_documents SET activation_revision = activation_revision + 1 WHERE document_id = ? "
                "RETURNING activation_revision",
                (document_id,),
            )[0][0])
        row = self.db.execute_query(
            """INSERT INTO tb_document_version_activations
                   (document_id, from_version_no, to_version_no, activation_revision, operation_type, actor_id, job_id)
               VALUES (?, ?, ?, ?, ?,
                       (SELECT user_id FROM tb_users WHERE user_id = ?),
                       (SELECT job_id FROM tb_ingest_jobs WHERE job_id = ?))
               RETURNING activation_id, activated_at""",
            (document_id, from_version_no, to_version_no, revision, operation_type, actor_id, job_id),
        )[0]
        return {"activation_id": int(row[0]), "activated_at": row[1], "activation_revision": revision}

    def seal_version(
        self, document_id: str, version_no: int, *, embedding_profile_id: Optional[int],
        manifest: dict[str, Any], snapshot: dict[str, Any],
    ) -> None:
        """적재 성공 버전의 프로필·벡터 명세·문서 snapshot 기록(봉인). 이후 복원 판정·검증의 기준."""
        self.db.execute_update(
            """UPDATE tb_document_versions SET embedding_profile_id = ?, vector_manifest_json = ?,
                   document_snapshot_json = ?, vector_storage_state = 'available', restore_verified_at = now()
               WHERE document_id = ? AND version_no = ?""",
            (embedding_profile_id, _dump(manifest), _dump(snapshot), document_id, version_no),
        )

    def get_version(self, document_id: str, version_no: int) -> Optional[dict[str, Any]]:
        rows = self.db.execute_query(
            "SELECT * FROM tb_document_versions WHERE document_id = ? AND version_no = ?", (document_id, version_no)
        )
        return dict(rows[0]) if rows else None

    def version_point_ids(self, document_id: str, version_no: int) -> list[str]:
        return [str(r[0]) for r in self.db.execute_query(
            "SELECT point_id FROM tb_chunks WHERE document_id = ? AND version_no = ? ORDER BY point_id",
            (document_id, version_no),
        )]

    def version_resources(self, document_id: str, version_no: int) -> list[str]:
        return [r[0] for r in self.db.execute_query(
            "SELECT resource_id FROM tb_spreadsheet_resources WHERE document_id = ? AND version_no = ? "
            "AND status <> 'deleted'",
            (document_id, version_no),
        )]

    def restore_version(
        self, document_id: str, version_no: int, *, job_id: str, actor_id: Optional[str],
        expected_version_no: int, expected_revision: int,
    ) -> dict[str, Any]:
        """이전 버전 복원 전환(6.2). 호출자 트랜잭션 안에서 실행. 조건이 어긋나면 RestoreStateError(롤백 → 기존 유지).

        이전 active → retired, 대상 → active, 문서 행 표시·내용 정보 전환(모델명·doc_key·업로더·대화 주제·보안 등급 유지),
        적용 순번 +1·적용 이력·점유 해제. 새 임베딩·포인트는 만들지 않는다.
        """
        self.lock_document(document_id)
        doc = self.db.execute_query(
            "SELECT version_no, activation_revision, pending_job_id, deleted_at FROM tb_documents "
            "WHERE document_id = ? FOR UPDATE",
            (document_id,),
        )
        if not doc or doc[0]["deleted_at"] is not None:
            raise RestoreStateError("NOT_FOUND", "문서가 없거나 삭제되었습니다.")
        doc = dict(doc[0])
        if doc["pending_job_id"] != job_id:
            raise RestoreStateError("JOB_IN_PROGRESS", "다른 작업이 이 문서를 처리 중입니다.")
        if int(doc["version_no"] or 1) != expected_version_no or int(doc["activation_revision"]) != expected_revision:
            raise RestoreStateError("STATE_CHANGED", "현재 적용 버전이 변경되었습니다.")
        target = self.db.execute_query(
            "SELECT * FROM tb_document_versions WHERE document_id = ? AND version_no = ? FOR UPDATE",
            (document_id, version_no),
        )
        if not target:
            raise RestoreStateError("VERSION_NOT_FOUND", "선택한 버전을 찾을 수 없습니다.")
        target = dict(target[0])
        if target["status"] != "retired" or target["activated_at"] is None:
            raise RestoreStateError("VERSION_NOT_RESTORABLE", "정상 적용 이력이 없는 버전입니다.")
        snapshot = target.get("document_snapshot_json")
        if isinstance(snapshot, str):
            snapshot = json.loads(snapshot)
        if not snapshot:
            raise RestoreStateError("METADATA_MISSING", "이 버전의 정보가 부족해 적용할 수 없습니다.")
        from_version_no = int(doc["version_no"] or 1)
        self.db.execute_update(
            "UPDATE tb_document_versions SET status = 'retired', retired_at = now() "
            "WHERE document_id = ? AND status = 'active'",
            (document_id,),
        )
        self.db.execute_update(
            "UPDATE tb_document_versions SET status = 'active', activated_at = now(), retired_at = NULL "
            "WHERE document_id = ? AND version_no = ?",
            (document_id, version_no),
        )
        self.db.execute_update(
            """UPDATE tb_documents SET
                   version_no = ?, original_filename = ?, stored_filename = ?, source_path = ?, file_size = ?,
                   file_format = ?, parser_type = ?, total_pages = ?, chunk_count = ?,
                   doc_type = ?, requested_doc_type = ?, doc_type_source = ?, title = ?,
                   status = 'ready', error_message = NULL, pending_job_id = NULL,
                   active_activated_at = now(), content_updated_at = now(), updated_at = now()
               WHERE document_id = ?""",
            (
                version_no, target["original_filename"], target["stored_filename"], target["source_path"],
                target["file_size"], target["file_format"], target["parser_type"], target["total_pages"],
                target["chunk_count"], snapshot.get("doc_type"), snapshot.get("requested_doc_type") or "auto",
                snapshot.get("doc_type_source"), snapshot.get("title"), document_id,
            ),
        )
        activation = self.record_activation(
            document_id, from_version_no=from_version_no, to_version_no=version_no, operation_type="restore",
            actor_id=actor_id, job_id=job_id,
        )
        return {
            "document_id": document_id,
            "from_version_no": from_version_no,
            "current_version_no": version_no,
            "original_filename": target["original_filename"],
            "total_pages": target["total_pages"],
            "chunk_count": target["chunk_count"],
            **activation,
        }

    def list_activations(
        self, document_id: str, *, limit: int, before_activation_id: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        params: list[Any] = [document_id]
        cursor_sql = ""
        if before_activation_id is not None:
            cursor_sql = " AND a.activation_id < ?"
            params.append(before_activation_id)
        params.append(limit)
        rows = self.db.execute_query(
            f"""SELECT a.activation_id, a.operation_type, a.from_version_no, a.to_version_no, a.activation_revision,
                       a.actor_id, nullif(u.user_name, '') AS actor_name, a.activated_at
                FROM tb_document_version_activations a
                LEFT JOIN tb_users u ON u.user_id = a.actor_id
                WHERE a.document_id = ?{cursor_sql}
                ORDER BY a.activation_id DESC LIMIT ?""",
            tuple(params),
        )
        return [dict(r) for r in rows]

    # ── 청크 ─────────────────────────────────────────────────────────

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

    # ── 청크↔사진 ───────────────────────────────────────────────────

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

    # ── 사진 배치 (excel_ingest 경로) ───────────────────────────────────

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

    # ── 흐름도 ─────────────────────────────────────────────────────

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

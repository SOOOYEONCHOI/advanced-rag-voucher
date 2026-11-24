# 2026.11.18(sooyeon.choi) 추가 - 시험 대응 일괄 질의 저장소 (tb_eval_batch_jobs·tb_eval_batch_items)
"""일괄 질의 작업·질의별 결과 저장소.

설계: docs/design/reports/eval-batch-query-design-v1.0.md 3장 (R8-7, N-4)
- JSON 열은 문자열로 넣고(``?::jsonb``) 읽을 때는 JSON 문자열로 돌아온다(DatabaseManager 규칙).
- 작업 상태 전이: pending → running → completed / failed / cancelled.
"""

import json
from typing import Any, Dict, List, Optional, Sequence

from app.repositories.database import get_database_manager

_JOB_JSON_FIELDS = ("config_json", "doc_versions_json", "summary_json")
_ITEM_JSON_FIELDS = ("citations_json", "retrieved_top_json", "reranked_top_json", "timing_json")
_CLAIM_LOCK_KEY = 20261118  # 일괄 질의 작업 꺼내기용 advisory lock 키


def _dumps(value: Any) -> Optional[str]:
    return None if value is None else json.dumps(value, ensure_ascii=False)


def _loads(row: Dict[str, Any], fields: Sequence[str]) -> Dict[str, Any]:
    for field in fields:
        value = row.get(field)
        if isinstance(value, str):
            try:
                row[field] = json.loads(value)
            except json.JSONDecodeError:
                pass
    return row


class EvalBatchRepository:
    def __init__(self):
        self._db = get_database_manager()

    # ── 작업 ──────────────────────────────────────────────────────────────

    def create_job(
        self,
        *,
        name: str,
        collection_name: str,
        items: List[Dict[str, str]],
        warmup_count: int,
        config: Dict[str, Any],
        doc_versions: Dict[str, int],
        created_by: Optional[str],
    ) -> int:
        """작업과 질의 행을 한 트랜잭션으로 만든다. items: [{query_key, query_text}] (파일 행 순서)."""
        with self._db.get_connection() as conn:
            job_id = conn.execute(
                """INSERT INTO tb_eval_batch_jobs
                       (name, collection_name, total_count, warmup_count,
                        config_json, doc_versions_json, created_by)
                   VALUES (?, ?, ?, ?, ?::jsonb, ?::jsonb, ?)
                   RETURNING job_id""",
                (name, collection_name, len(items), warmup_count,
                 _dumps(config), _dumps(doc_versions), created_by),
            ).fetchone()[0]
            conn.executemany(
                """INSERT INTO tb_eval_batch_items (job_id, seq, query_key, query_text)
                   VALUES (?, ?, ?, ?)""",
                [
                    (job_id, seq, item["query_key"], item["query_text"])
                    for seq, item in enumerate(items, start=1)
                ],
            )
        return int(job_id)

    def get_job(self, job_id: int) -> Optional[Dict[str, Any]]:
        rows = self._db.execute_query("SELECT * FROM tb_eval_batch_jobs WHERE job_id = ?", (job_id,))
        return _loads(dict(rows[0]), _JOB_JSON_FIELDS) if rows else None

    def list_jobs(self, limit: int = 20) -> List[Dict[str, Any]]:
        rows = self._db.execute_query(
            """SELECT job_id, name, collection_name, status, total_count, done_count, error_count,
                      gold_status, created_by, created_at, started_at, finished_at
               FROM tb_eval_batch_jobs ORDER BY job_id DESC LIMIT ?""",
            (limit,),
        )
        return [dict(row) for row in rows]

    def queue_position(self, job_id: int) -> int:
        """이 작업 앞에 대기·실행 중인 작업 수(0이면 바로 실행)."""
        rows = self._db.execute_query(
            """SELECT COUNT(*) AS cnt FROM tb_eval_batch_jobs
               WHERE status IN ('pending', 'running') AND job_id < ?""",
            (job_id,),
        )
        return int(rows[0]["cnt"]) if rows else 0

    def claim_next_pending(self) -> Optional[int]:
        """대기 작업 1개를 running으로 바꾸고 job_id를 반환한다(동시에 도는 작업은 1개, F-03)."""
        with self._db.get_connection() as conn:
            # 워커 프로세스가 여럿이어도 꺼내기를 직렬화해 running 작업이 2개가 되지 않게 한다(트랜잭션 종료 시 해제)
            conn.execute("SELECT pg_advisory_xact_lock(?)", (_CLAIM_LOCK_KEY,))
            running = conn.execute(
                "SELECT 1 FROM tb_eval_batch_jobs WHERE status = 'running' LIMIT 1"
            ).fetchone()
            if running:
                return None
            row = conn.execute(
                """SELECT job_id FROM tb_eval_batch_jobs
                   WHERE status = 'pending'
                   ORDER BY created_at, job_id
                   LIMIT 1 FOR UPDATE SKIP LOCKED"""
            ).fetchone()
            if not row:
                return None
            conn.execute(
                """UPDATE tb_eval_batch_jobs
                   SET status = 'running', started_at = now(), error_message = NULL
                   WHERE job_id = ?""",
                (row[0],),
            )
            return int(row[0])

    def finish_job(
        self,
        job_id: int,
        status: str,
        *,
        summary: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
    ) -> None:
        self._db.execute_update(
            """UPDATE tb_eval_batch_jobs
               SET status = ?, summary_json = COALESCE(?::jsonb, summary_json),
                   error_message = ?, finished_at = now()
               WHERE job_id = ?""",
            (status, _dumps(summary), error_message, job_id),
        )

    def update_summary(self, job_id: int, summary: Dict[str, Any]) -> None:
        self._db.execute_update(
            "UPDATE tb_eval_batch_jobs SET summary_json = ?::jsonb WHERE job_id = ?",
            (_dumps(summary), job_id),
        )

    def mark_interrupted_jobs_failed(self) -> int:
        """앱 재기동 시 running으로 남은 작업을 failed로 정리한다(완료 질의 결과는 보존, 5.1-1)."""
        return self._db.execute_update(
            """UPDATE tb_eval_batch_jobs
               SET status = 'failed',
                   error_message = '서버 재시작으로 중단됨(완료 ' || done_count || '건 보존)',
                   finished_at = now()
               WHERE status = 'running'"""
        )

    def delete_job(self, job_id: int) -> int:
        return self._db.execute_update("DELETE FROM tb_eval_batch_jobs WHERE job_id = ?", (job_id,))

    # ── 질의별 결과 ───────────────────────────────────────────────────────

    def list_pending_items(self, job_id: int) -> List[Dict[str, Any]]:
        rows = self._db.execute_query(
            """SELECT item_id, seq, query_key, query_text FROM tb_eval_batch_items
               WHERE job_id = ? AND status = 'pending' ORDER BY seq""",
            (job_id,),
        )
        return [dict(row) for row in rows]

    def list_items(self, job_id: int) -> List[Dict[str, Any]]:
        rows = self._db.execute_query(
            "SELECT * FROM tb_eval_batch_items WHERE job_id = ? ORDER BY seq", (job_id,)
        )
        return [_loads(dict(row), _ITEM_JSON_FIELDS) for row in rows]

    def mark_item_started(self, item_id: int) -> None:
        self._db.execute_update(
            "UPDATE tb_eval_batch_items SET started_at = now() WHERE item_id = ?", (item_id,)
        )

    def save_item_result(self, job_id: int, item_id: int, fields: Dict[str, Any]) -> None:
        """질의 1건 결과 저장 + 작업 진행 건수 증가(한 트랜잭션)."""
        is_error = fields.get("status") == "error"
        with self._db.get_connection() as conn:
            conn.execute(
                """UPDATE tb_eval_batch_items
                   SET status = ?, outcome_code = ?, answer_text = ?, answer_plain = ?,
                       citations_json = ?::jsonb, retrieved_top_json = ?::jsonb,
                       reranked_top_json = ?::jsonb, response_ms = ?, timing_json = ?::jsonb,
                       log_id = ?, error_message = ?, finished_at = now()
                   WHERE item_id = ?""",
                (
                    fields.get("status"),
                    fields.get("outcome_code"),
                    fields.get("answer_text"),
                    fields.get("answer_plain"),
                    _dumps(fields.get("citations_json")),
                    _dumps(fields.get("retrieved_top_json")),
                    _dumps(fields.get("reranked_top_json")),
                    fields.get("response_ms"),
                    _dumps(fields.get("timing_json")),
                    fields.get("log_id"),
                    fields.get("error_message"),
                    item_id,
                ),
            )
            conn.execute(
                """UPDATE tb_eval_batch_jobs
                   SET done_count = done_count + 1, error_count = error_count + ?
                   WHERE job_id = ?""",
                (1 if is_error else 0, job_id),
            )

    def average_response_ms(self, job_id: int) -> Optional[float]:
        rows = self._db.execute_query(
            """SELECT AVG(response_ms) AS avg_ms FROM tb_eval_batch_items
               WHERE job_id = ? AND status = 'ok'""",
            (job_id,),
        )
        value = rows[0]["avg_ms"] if rows else None
        return float(value) if value is not None else None

    # ── 문서 버전 스냅샷(F-18) ─────────────────────────────────────────────

    def collection_doc_versions(self, collection_name: str) -> Dict[str, int]:
        """컬렉션의 활성 문서별 현재 버전 번호 {document_id: version_no}."""
        rows = self._db.execute_query(
            """SELECT d.document_id, d.version_no
               FROM tb_documents d
               JOIN tb_collections c ON c.collection_id = d.collection_id
               WHERE c.qdrant_name = ? AND d.deleted_at IS NULL
               ORDER BY d.document_id""",
            (collection_name,),
        )
        return {str(row["document_id"]): int(row["version_no"] or 0) for row in rows}

    # ── 정답 근거 대조 (설계 6.7·7장) ───────────────────────────────────────
    # 2026.11.18(sooyeon.choi) 추가

    def list_query_keys(self, job_id: int) -> List[str]:
        rows = self._db.execute_query(
            "SELECT query_key FROM tb_eval_batch_items WHERE job_id = ? ORDER BY seq", (job_id,)
        )
        return [row["query_key"] for row in rows]

    def collection_documents(self, collection_name: str) -> List[Dict[str, Any]]:
        """컬렉션의 삭제되지 않은 문서(활성 버전 번호 포함)."""
        rows = self._db.execute_query(
            """SELECT d.document_id, d.original_filename, d.title, d.version_no
               FROM tb_documents d
               JOIN tb_collections c ON c.collection_id = d.collection_id
               WHERE c.qdrant_name = ? AND d.deleted_at IS NULL
               ORDER BY d.document_id""",
            (collection_name,),
        )
        return [dict(row) for row in rows]

    # 2026.11.19(sooyeon.choi) 수정 - 정답 청크ID = Qdrant 포인트 ID(tb_chunks.point_id).
    #   검색 결과(retrieved/reranked_top_json)의 chunk_id가 포인트 ID라서 tb_chunks.chunk_id로는 대조되지 않았다.
    def active_chunks(self, documents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """문서별 활성 버전 청크(검색 대상과 같은 chunk_id = 포인트 ID)."""
        if not documents:
            return []
        conditions = " OR ".join("(ch.document_id = ? AND ch.version_no = ?)" for _ in documents)
        params: List[Any] = []
        for doc in documents:
            params.extend([doc["document_id"], int(doc["version_no"] or 0)])
        rows = self._db.execute_query(
            f"""SELECT ch.point_id::text AS chunk_id, ch.document_id, ch.version_no, ch.sheet_name, ch.step_no,
                       ch.source_range, ch.chunk_text
                FROM tb_chunks ch
                WHERE ch.point_type = 'text' AND ({conditions})
                ORDER BY ch.document_id, ch.chunk_id""",
            tuple(params),
        )
        return [dict(row) for row in rows]

    def existing_chunk_ids(self, collection_name: str, chunk_ids: Sequence[str]) -> set:
        if not chunk_ids:
            return set()
        placeholders = ", ".join("?" for _ in chunk_ids)
        rows = self._db.execute_query(
            f"""SELECT ch.point_id::text AS chunk_id FROM tb_chunks ch
                JOIN tb_collections c ON c.collection_id = ch.collection_id
                WHERE c.qdrant_name = ? AND ch.point_id::text IN ({placeholders})""",
            (collection_name, *chunk_ids),
        )
        return {row["chunk_id"] for row in rows}

    def chunks_by_ids(self, chunk_ids: Sequence[str]) -> Dict[str, Dict[str, Any]]:
        if not chunk_ids:
            return {}
        placeholders = ", ".join("?" for _ in chunk_ids)
        rows = self._db.execute_query(
            f"""SELECT ch.point_id::text AS chunk_id, ch.document_id, ch.version_no, ch.sheet_name,
                       ch.step_no, ch.chunk_text, d.original_filename
                FROM tb_chunks ch LEFT JOIN tb_documents d ON d.document_id = ch.document_id
                WHERE ch.point_id::text IN ({placeholders})""",
            tuple(chunk_ids),
        )
        return {row["chunk_id"]: dict(row) for row in rows}

    def chunk_versions(self, chunk_ids: Sequence[str]) -> Dict[str, tuple]:
        """2026.11.19(sooyeon.choi) 추가 - 포인트 ID → (document_id, version_no). 정답 버전 불일치 확인용."""
        return {cid: (row["document_id"], int(row["version_no"])) for cid, row in self.chunks_by_ids(chunk_ids).items()}

    def replace_gold(self, job_id: int, rows: List[Dict[str, Any]], gold_status: str = "matched") -> None:
        """정답 근거를 통째로 바꾸고 gold_status='matched'(다시 올리면 덮어씀).

        2026.11.19(sooyeon.choi) 수정 - 정답 파일에 청크ID가 모두 있으면 바로 'confirmed'.
        """
        with self._db.get_connection() as conn:
            conn.execute("DELETE FROM tb_eval_batch_gold WHERE job_id = ?", (job_id,))
            conn.executemany(
                """INSERT INTO tb_eval_batch_gold
                       (job_id, query_key, evidence_seq, source_doc, source_loc, evidence_text,
                        matched_json, confirmed_ids, match_status)
                   VALUES (?, ?, ?, ?, ?, ?, ?::jsonb, ?::jsonb, ?)""",
                [
                    (job_id, r["query_key"], r["evidence_seq"], r.get("source_doc"), r.get("source_loc"),
                     r["evidence_text"], _dumps(r.get("matched_json")), _dumps(r.get("confirmed_ids")),
                     r["match_status"])
                    for r in rows
                ],
            )
            conn.execute(
                "UPDATE tb_eval_batch_jobs SET gold_status = ? WHERE job_id = ?", (gold_status, job_id)
            )

    def list_gold(self, job_id: int) -> List[Dict[str, Any]]:
        rows = self._db.execute_query(
            """SELECT * FROM tb_eval_batch_gold WHERE job_id = ?
               ORDER BY query_key, evidence_seq""",
            (job_id,),
        )
        return [_loads(dict(row), ("matched_json", "confirmed_ids")) for row in rows]

    def confirm_gold(self, job_id: int, updates: List[Dict[str, Any]]) -> None:
        """검토 결과 반영: [{gold_id, confirmed_ids, match_status}] → gold_status='confirmed'."""
        with self._db.get_connection() as conn:
            conn.executemany(
                """UPDATE tb_eval_batch_gold SET confirmed_ids = ?::jsonb, match_status = ?
                   WHERE gold_id = ? AND job_id = ?""",
                [(_dumps(u["confirmed_ids"]), u["match_status"], u["gold_id"], job_id) for u in updates],
            )
            conn.execute(
                "UPDATE tb_eval_batch_jobs SET gold_status = 'confirmed' WHERE job_id = ?", (job_id,)
            )

"""평가 시스템 CRUD.

테이블 정의(tb_eval_*)는 Alembic 리비전(migrations/versions/0001_baseline.py)에 있다
(2026.10.16 Phase 1.5 - SQLite schema.sql·_sync_schema 대체). 이 모듈은 별도 스키마 부트스트랩을 하지 않고
기존 DatabaseManager 커넥션/헬퍼(execute_query/execute_update/execute_many)를 재사용한다.
"""

import json
from typing import Any, Dict, List, Optional

from app.repositories.database import get_database_manager
from app.utils.log.log import LoggingLogger

logger = LoggingLogger().getLogger(__name__)


def _row_to_dict(row) -> Optional[Dict[str, Any]]:
    return dict(row) if row is not None else None


class EvalRepository:
    """평가 관련 테이블 CRUD."""

    def __init__(self):
        self._db = get_database_manager()

    # ── 데이터셋 ────────────────────────────────────────────────────────

    def create_dataset(
        self,
        name: str,
        collection_id: int,
        gen_config: Dict[str, Any],
        created_by: Optional[str] = None,
    ) -> int:
        with self._db.get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO tb_eval_datasets (name, collection_id, gen_config_json, created_by)
                   VALUES (?, ?, ?, ?) RETURNING dataset_id""",
                (name, collection_id, json.dumps(gen_config, ensure_ascii=False), created_by),
            )
            return cur.fetchone()[0]  # 2026.10.16 Phase 1.5 - lastrowid → RETURNING

    def list_datasets(self) -> List[Dict[str, Any]]:
        rows = self._db.execute_query(
            """SELECT d.*, c.display_name AS collection_name,
                      (SELECT COUNT(*) FROM tb_eval_qa_items q WHERE q.dataset_id = d.dataset_id) AS item_count,
                      (SELECT COUNT(*) FROM tb_eval_qa_items q
                        WHERE q.dataset_id = d.dataset_id AND q.review_status IN ('approved','edited')) AS approved_count
               FROM tb_eval_datasets d
               LEFT JOIN tb_collections c ON c.collection_id = d.collection_id
               ORDER BY d.dataset_id DESC"""
        )
        return [dict(r) for r in rows]

    # ── 데이터셋 생성용 설정 (관리자 OpenAI 키) ───────────────────────────

    def get_dataset_generation_openai_key_enc(self, admin_id: str) -> Optional[str]:
        """관리자의 저장된 OpenAI 키(암호문)를 반환. 없으면 None."""
        if not admin_id:
            return None
        rows = self._db.execute_query(
            "SELECT openai_api_key_enc FROM tb_eval_settings WHERE admin_id = ?",
            (admin_id,),
        )
        return rows[0]["openai_api_key_enc"] if rows else None

    def save_dataset_generation_openai_key(self, admin_id: str, key_enc: Optional[str]) -> None:
        """관리자의 OpenAI 키(암호문)를 upsert (key_enc=None이면 키를 비운다)."""
        with self._db.get_connection() as conn:
            conn.execute(
                """INSERT INTO tb_eval_settings (admin_id, openai_api_key_enc, updated_at)
                   VALUES (?, ?, now())
                   ON CONFLICT(admin_id) DO UPDATE SET
                       openai_api_key_enc = excluded.openai_api_key_enc,
                       updated_at = excluded.updated_at""",
                (admin_id, key_enc),
            )

    def delete_dataset_generation_openai_key(self, admin_id: str) -> None:
        with self._db.get_connection() as conn:
            conn.execute("DELETE FROM tb_eval_settings WHERE admin_id = ?", (admin_id,))

    def get_dataset(self, dataset_id: int) -> Optional[Dict[str, Any]]:
        rows = self._db.execute_query(
            """SELECT d.*, c.display_name AS collection_name, c.qdrant_name
               FROM tb_eval_datasets d
               LEFT JOIN tb_collections c ON c.collection_id = d.collection_id
               WHERE d.dataset_id = ?""",
            (dataset_id,),
        )
        return _row_to_dict(rows[0]) if rows else None

    def active_chunk_versions(self, collection_id: int) -> Dict[str, int]:
        """2026.11.19(sooyeon.choi) 추가 - 컬렉션 활성 문서 버전의 청크 {포인트 ID: version_no}.

        Qdrant에는 DB에서 지워진 문서의 포인트가 남을 수 있으므로(고아 포인트) 생성 대상은 이 목록으로 거른다.
        """
        rows = self._db.execute_query(
            """SELECT ch.point_id::text AS point_id, ch.version_no
               FROM tb_chunks ch
               JOIN tb_documents d ON d.document_id = ch.document_id AND d.version_no = ch.version_no
               WHERE d.collection_id = ? AND d.deleted_at IS NULL AND ch.point_type = 'text'""",
            (collection_id,),
        )
        return {row["point_id"]: int(row["version_no"]) for row in rows}

    def document_versions(self, document_ids: List[str]) -> Dict[str, Optional[int]]:
        """2026.11.19(sooyeon.choi) 추가 - 문서별 현재 버전(삭제 문서는 None). 시험 데이터셋 버전 확인용."""
        if not document_ids:
            return {}
        placeholders = ", ".join("?" for _ in document_ids)
        rows = self._db.execute_query(
            f"""SELECT document_id, version_no, deleted_at FROM tb_documents
                WHERE document_id IN ({placeholders})""",
            tuple(document_ids),
        )
        found = {
            row["document_id"]: (None if row["deleted_at"] is not None else int(row["version_no"] or 0))
            for row in rows
        }
        return {doc_id: found.get(doc_id) for doc_id in document_ids}

    def update_dataset_status(
        self,
        dataset_id: int,
        status: str,
        error_message: Optional[str] = None,
    ) -> None:
        self._db.execute_update(
            """UPDATE tb_eval_datasets
               SET status = ?, error_message = ?,
                   updated_at = now()
               WHERE dataset_id = ?""",
            (status, error_message, dataset_id),
        )

    # 2026.11.23(sooyeon.choi) 추가 - 확정 이후에도 질의ID 접두어만 변경(gen_config_json의 다른 값은 유지)
    def update_dataset_query_id_prefix(self, dataset_id: int, prefix: str) -> Dict[str, Any]:
        with self._db.get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT gen_config_json FROM tb_eval_datasets WHERE dataset_id = ? FOR UPDATE",
                (dataset_id,),
            )
            row = cur.fetchone()
            raw = row[0] if row else None
            config: Any = raw
            if isinstance(raw, str):
                try:
                    config = json.loads(raw) if raw else {}
                except json.JSONDecodeError:
                    config = {}
            config = dict(config) if isinstance(config, dict) else {}
            if prefix:
                config["query_id_prefix"] = prefix
            else:
                config.pop("query_id_prefix", None)
            cur.execute(
                "UPDATE tb_eval_datasets SET gen_config_json = ?, updated_at = now() WHERE dataset_id = ?",
                (json.dumps(config, ensure_ascii=False), dataset_id),
            )
        return config

    def update_dataset_progress(self, dataset_id: int, done: int, total: int) -> None:
        self._db.execute_update(
            """UPDATE tb_eval_datasets SET progress_done = ?, progress_total = ?,
                   updated_at = now()
               WHERE dataset_id = ?""",
            (done, total, dataset_id),
        )

    def delete_dataset(self, dataset_id: int) -> None:
        """데이터셋 삭제. 확정된 골드셋이 있으면 그 골드셋을 참조하는 run과 골드셋도 함께 삭제한다
        (tb_eval_goldsets/tb_eval_runs는 이력 보존을 위해 FK가 RESTRICT라 단순 CASCADE로는 안 지워짐).
        QA 항목(tb_eval_qa_items)은 데이터셋에 CASCADE로 걸려있어 자동 삭제된다.
        """
        with self._db.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT goldset_id FROM tb_eval_goldsets WHERE dataset_id = ?", (dataset_id,))
            goldset_ids = [row[0] for row in cur.fetchall()]
            for goldset_id in goldset_ids:
                cur.execute("DELETE FROM tb_eval_runs WHERE goldset_id = ?", (goldset_id,))
            if goldset_ids:
                cur.execute(
                    # 보간되는 건 '?' 개수뿐, 실값은 tuple(goldset_ids)로 파라미터 바인딩됨
                    f"DELETE FROM tb_eval_goldsets WHERE goldset_id IN ({','.join('?' * len(goldset_ids))})",
                    tuple(goldset_ids),
                )
            cur.execute("DELETE FROM tb_eval_datasets WHERE dataset_id = ?", (dataset_id,))

    # ── QA 항목 ─────────────────────────────────────────────────────────

    def insert_qa_item(
        self,
        dataset_id: int,
        question: str,
        gold_answer: str,
        gold_chunk_ids: List[str],
        gold_document_ids: List[str],
        gold_chunk_texts: List[str],
        question_type: str,
        self_valid_rank: Optional[int] = None,
        source_meta: Optional[Dict[str, Any]] = None,
        expected_behavior: str = "answer",
        tags: Optional[List[str]] = None,
    ) -> int:
        with self._db.get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO tb_eval_qa_items
                   (dataset_id, question, gold_answer, gold_chunk_ids, gold_document_ids,
                    gold_chunk_texts, question_type, self_valid_rank, source_meta_json,
                    expected_behavior, tags)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING qa_id""",
                (
                    dataset_id, question, gold_answer,
                    json.dumps(gold_chunk_ids, ensure_ascii=False),
                    json.dumps(gold_document_ids, ensure_ascii=False),
                    json.dumps(gold_chunk_texts, ensure_ascii=False),
                    question_type, self_valid_rank,
                    json.dumps(source_meta or {}, ensure_ascii=False),
                    expected_behavior,
                    json.dumps(tags or [], ensure_ascii=False),
                ),
            )
            return cur.fetchone()[0]  # 2026.10.16 Phase 1.5 - lastrowid → RETURNING

    def list_qa_items(
        self,
        dataset_id: int,
        review_status: Optional[str] = None,
        question_type: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Dict[str, Any]:
        where = ["dataset_id = ?"]
        params: List[Any] = [dataset_id]
        if review_status:
            where.append("review_status = ?")
            params.append(review_status)
        if question_type:
            where.append("question_type = ?")
            params.append(question_type)
        where_sql = " AND ".join(where)

        total = self._db.execute_query(
            f"SELECT COUNT(*) AS cnt FROM tb_eval_qa_items WHERE {where_sql}", tuple(params)
        )[0]["cnt"]
        rows = self._db.execute_query(
            f"""SELECT * FROM tb_eval_qa_items WHERE {where_sql}
                ORDER BY qa_id LIMIT ? OFFSET ?""",
            tuple(params + [page_size, (page - 1) * page_size]),
        )
        return {"total": total, "items": [dict(r) for r in rows]}

    def list_approved_qa_items(self, dataset_id: int) -> List[Dict[str, Any]]:
        """Excel 내보내기용 승인·수정 QA 전체를 생성 순서로 조회한다."""
        rows = self._db.execute_query(
            """SELECT qa_id, question, gold_answer, question_type, difficulty,
                      expected_behavior, tags, review_status, reviewed_by, reviewed_at,
                      gold_document_ids, gold_chunk_ids, gold_chunk_texts,
                      self_valid_rank, source_meta_json, created_at
               FROM tb_eval_qa_items
               WHERE dataset_id = ?
                 AND review_status IN ('approved', 'edited')
               ORDER BY qa_id""",
            (dataset_id,),
        )
        return [dict(row) for row in rows]

    def get_qa_item(self, qa_id: int) -> Optional[Dict[str, Any]]:
        rows = self._db.execute_query(
            "SELECT * FROM tb_eval_qa_items WHERE qa_id = ?", (qa_id,)
        )
        return _row_to_dict(rows[0]) if rows else None

    def replace_generated_qa(
        self,
        qa_id: int,
        *,
        question: str,
        gold_answer: str,
        self_valid_rank: Optional[int],
        tags: List[str],
        source_meta: Dict[str, Any],
    ) -> None:
        """2026.11.19(sooyeon.choi) 추가 - 같은 근거로 다시 생성한 질문·답변으로 교체하고 검수 대기로 되돌린다."""
        self._db.execute_update(
            """UPDATE tb_eval_qa_items
               SET question = ?, gold_answer = ?, self_valid_rank = ?, tags = ?::jsonb,
                   source_meta_json = ?::jsonb, review_status = 'pending',
                   reviewed_by = NULL, reviewed_at = NULL
               WHERE qa_id = ?""",
            (
                question, gold_answer, self_valid_rank,
                json.dumps(tags or [], ensure_ascii=False),
                json.dumps(source_meta or {}, ensure_ascii=False),
                qa_id,
            ),
        )

    def update_qa_item(
        self,
        qa_id: int,
        *,
        question: Optional[str] = None,
        gold_answer: Optional[str] = None,
        gold_chunk_ids: Optional[List[str]] = None,
        gold_document_ids: Optional[List[str]] = None,
        expected_behavior: Optional[str] = None,
        tags: Optional[List[str]] = None,
        review_status: Optional[str] = None,
        reviewed_by: Optional[str] = None,
    ) -> None:
        sets: List[str] = []
        params: List[Any] = []
        if question is not None:
            sets.append("question = ?")
            params.append(question)
        if gold_answer is not None:
            sets.append("gold_answer = ?")
            params.append(gold_answer)
        if gold_chunk_ids is not None:
            sets.append("gold_chunk_ids = ?")
            params.append(json.dumps(gold_chunk_ids, ensure_ascii=False))
        if gold_document_ids is not None:
            sets.append("gold_document_ids = ?")
            params.append(json.dumps(gold_document_ids, ensure_ascii=False))
        if expected_behavior is not None:
            sets.append("expected_behavior = ?")
            params.append(expected_behavior)
        if tags is not None:
            sets.append("tags = ?")
            params.append(json.dumps(tags, ensure_ascii=False))
        if review_status is not None:
            sets.append("review_status = ?")
            params.append(review_status)
            sets.append("reviewed_at = now()")
        if reviewed_by is not None:
            sets.append("reviewed_by = ?")
            params.append(reviewed_by)
        if not sets:
            return
        params.append(qa_id)
        self._db.execute_update(
            f"UPDATE tb_eval_qa_items SET {', '.join(sets)} WHERE qa_id = ?", tuple(params)
        )
        # 2026.07.23(sychoi) 추가 - 검수(승인/반려/수정)도 데이터셋의 '최종 수정일'에 반영한다.
        # 이전에는 생성 상태/진행률 변경 시에만 updated_at이 갱신되어, 검수를 아무리 해도
        # 목록의 최종 수정일이 그대로여서 실제 작업 시점을 알 수 없었다.
        self._db.execute_update(
            """UPDATE tb_eval_datasets
               SET updated_at = now()
               WHERE dataset_id = (SELECT dataset_id FROM tb_eval_qa_items WHERE qa_id = ?)""",
            (qa_id,),
        )

    # ── 골드셋 ──────────────────────────────────────────────────────────

    def create_goldset(
        self,
        dataset_id: int,
        note: str = "",
        created_by: Optional[str] = None,
    ) -> Optional[int]:
        """승인(approved/edited) 항목 스냅샷으로 골드셋 버전을 생성한다."""
        rows = self._db.execute_query(
            """SELECT * FROM tb_eval_qa_items
               WHERE dataset_id = ? AND review_status IN ('approved', 'edited')
               ORDER BY qa_id""",
            (dataset_id,),
        )
        items = [dict(r) for r in rows]
        if not items:
            return None

        version_row = self._db.execute_query(
            "SELECT COALESCE(MAX(version), 0) + 1 AS v FROM tb_eval_goldsets WHERE dataset_id = ?",
            (dataset_id,),
        )
        version = version_row[0]["v"]

        with self._db.get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO tb_eval_goldsets
                   (dataset_id, version, item_count, items_snapshot_json, note, created_by)
                   VALUES (?, ?, ?, ?, ?, ?) RETURNING goldset_id""",
                (dataset_id, version, len(items),
                 json.dumps(items, ensure_ascii=False), note, created_by),
            )
            goldset_id = cur.fetchone()[0]
        self.update_dataset_status(dataset_id, "finalized")
        return goldset_id

    def import_goldset(
        self,
        dataset_id: int,
        items: List[Dict[str, Any]],
        note: str = "",
        created_by: Optional[str] = None,
    ) -> int:
        """수동 JSON 골드셋 직접 등록."""
        version_row = self._db.execute_query(
            "SELECT COALESCE(MAX(version), 0) + 1 AS v FROM tb_eval_goldsets WHERE dataset_id = ?",
            (dataset_id,),
        )
        version = version_row[0]["v"]
        with self._db.get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO tb_eval_goldsets
                   (dataset_id, version, item_count, items_snapshot_json, note, created_by)
                   VALUES (?, ?, ?, ?, ?, ?) RETURNING goldset_id""",
                (dataset_id, version, len(items),
                 json.dumps(items, ensure_ascii=False), note, created_by),
            )
            return cur.fetchone()[0]  # 2026.10.16 Phase 1.5 - lastrowid → RETURNING

    def list_goldsets(self, dataset_id: Optional[int] = None) -> List[Dict[str, Any]]:
        # 2026.11.20(sooyeon.choi) 수정 - dataset_kind(합본 표시)
        sql = """SELECT g.goldset_id, g.dataset_id, g.version, g.item_count, g.note,
                        g.created_by, g.created_at, d.name AS dataset_name, d.collection_id,
                        d.gen_config_json->>'dataset_kind' AS dataset_kind,
                        c.display_name AS collection_name, c.qdrant_name
                 FROM tb_eval_goldsets g
                 LEFT JOIN tb_eval_datasets d ON d.dataset_id = g.dataset_id
                 LEFT JOIN tb_collections c ON c.collection_id = d.collection_id"""
        params: tuple = ()
        if dataset_id is not None:
            sql += " WHERE g.dataset_id = ?"
            params = (dataset_id,)
        sql += " ORDER BY g.goldset_id DESC"
        return [dict(r) for r in self._db.execute_query(sql, params)]

    def latest_goldset(self, dataset_id: int) -> Optional[Dict[str, Any]]:
        """2026.11.20(sooyeon.choi) 수정 - 데이터셋의 최신 확정본(합본 원본으로 사용)."""
        rows = self._db.execute_query(
            """SELECT goldset_id FROM tb_eval_goldsets WHERE dataset_id = ?
               ORDER BY version DESC LIMIT 1""",
            (dataset_id,),
        )
        return self.get_goldset(rows[0]["goldset_id"]) if rows else None

    def create_merged_dataset(
        self,
        name: str,
        collection_id: int,
        gen_config: Dict[str, Any],
        items: List[Dict[str, Any]],
        note: str = "",
        created_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """2026.11.20(sooyeon.choi) 수정 - 합본 데이터셋·문항 복사 후 골드셋 v1까지 만든다.

        collection_id는 NOT NULL 열을 채우는 값(첫 원본 컬렉션)이며, 검색은 문항별 source_meta_json.qdrant_name을 쓴다.
        골드셋 생성이 실패하면 만든 데이터셋을 지운다.
        """
        with self._db.get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO tb_eval_datasets
                   (name, collection_id, status, gen_config_json, progress_done, progress_total, created_by)
                   VALUES (?, ?, 'review', ?, ?, ?, ?) RETURNING dataset_id""",
                (name, collection_id, json.dumps(gen_config, ensure_ascii=False), len(items), len(items), created_by),
            )
            dataset_id = cur.fetchone()[0]
            cur.executemany(
                """INSERT INTO tb_eval_qa_items
                   (dataset_id, question, gold_answer, gold_chunk_ids, gold_document_ids, gold_chunk_texts,
                    question_type, difficulty, self_valid_rank, expected_behavior, tags, review_status,
                    reviewed_by, reviewed_at, source_meta_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, now(), ?)""",
                [
                    (
                        dataset_id, item["question"], item["gold_answer"],
                        json.dumps(item["gold_chunk_ids"], ensure_ascii=False),
                        json.dumps(item["gold_document_ids"], ensure_ascii=False),
                        json.dumps(item["gold_chunk_texts"], ensure_ascii=False),
                        item["question_type"], item["difficulty"], item["self_valid_rank"],
                        item["expected_behavior"], json.dumps(item["tags"], ensure_ascii=False),
                        item["review_status"], item.get("reviewed_by") or created_by,
                        json.dumps(item["source_meta"], ensure_ascii=False),
                    )
                    for item in items
                ],
            )
        try:
            goldset_id = self.create_goldset(dataset_id, note=note, created_by=created_by)
        except Exception:
            self.delete_dataset(dataset_id)
            raise
        return {"dataset_id": dataset_id, "goldset_id": goldset_id, "item_count": len(items)}

    def get_goldset(self, goldset_id: int) -> Optional[Dict[str, Any]]:
        rows = self._db.execute_query(
            """SELECT g.*, d.name AS dataset_name, d.collection_id,
                      c.display_name AS collection_name, c.qdrant_name
               FROM tb_eval_goldsets g
               LEFT JOIN tb_eval_datasets d ON d.dataset_id = g.dataset_id
               LEFT JOIN tb_collections c ON c.collection_id = d.collection_id
               WHERE g.goldset_id = ?""",
            (goldset_id,),
        )
        return _row_to_dict(rows[0]) if rows else None

    # ── 평가 실행 ────────────────────────────────────────────────────────

    def create_run(
        self,
        goldset_id: int,
        run_type: str,
        config: Dict[str, Any],
        total: int,
        created_by: Optional[str] = None,
    ) -> int:
        with self._db.get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO tb_eval_runs
                   (goldset_id, run_type, config_json, progress_total, created_by)
                   VALUES (?, ?, ?, ?, ?) RETURNING run_id""",
                (goldset_id, run_type, json.dumps(config, ensure_ascii=False), total, created_by),
            )
            return cur.fetchone()[0]  # 2026.10.16 Phase 1.5 - lastrowid → RETURNING

    def list_runs(self, goldset_id: Optional[int] = None, limit: int = 50) -> List[Dict[str, Any]]:
        # 2026.11.20(sooyeon.choi) 수정 - dataset_kind(합본 표시)
        sql = """SELECT r.*, g.version AS goldset_version, g.dataset_id,
                        d.name AS dataset_name, c.display_name AS collection_name,
                        d.gen_config_json->>'dataset_kind' AS dataset_kind
                 FROM tb_eval_runs r
                 LEFT JOIN tb_eval_goldsets g ON g.goldset_id = r.goldset_id
                 LEFT JOIN tb_eval_datasets d ON d.dataset_id = g.dataset_id
                 LEFT JOIN tb_collections c ON c.collection_id = d.collection_id"""
        params: List[Any] = []
        if goldset_id is not None:
            sql += " WHERE r.goldset_id = ?"
            params.append(goldset_id)
        sql += " ORDER BY r.run_id DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in self._db.execute_query(sql, tuple(params))]

    def get_run(self, run_id: int) -> Optional[Dict[str, Any]]:
        rows = self._db.execute_query(
            """SELECT r.*, g.version AS goldset_version, g.dataset_id,
                      d.name AS dataset_name, c.display_name AS collection_name, c.qdrant_name,
                      d.gen_config_json->>'dataset_kind' AS dataset_kind
               FROM tb_eval_runs r
               LEFT JOIN tb_eval_goldsets g ON g.goldset_id = r.goldset_id
               LEFT JOIN tb_eval_datasets d ON d.dataset_id = g.dataset_id
               LEFT JOIN tb_collections c ON c.collection_id = d.collection_id
               WHERE r.run_id = ?""",
            (run_id,),
        )
        return _row_to_dict(rows[0]) if rows else None

    def delete_run(self, run_id: int) -> None:
        """run 삭제. tb_eval_item_results/tb_eval_run_metrics는 CASCADE로 자동 삭제된다."""
        self._db.execute_update("DELETE FROM tb_eval_runs WHERE run_id = ?", (run_id,))

    def update_run_status(
        self,
        run_id: int,
        status: str,
        error_message: Optional[str] = None,
    ) -> None:
        extra = ""
        if status == "running":
            extra = ", started_at = now()"
        elif status in ("completed", "failed", "cancelled"):
            extra = ", finished_at = now()"
        self._db.execute_update(
            f"UPDATE tb_eval_runs SET status = ?, error_message = ?{extra} WHERE run_id = ?",
            (status, error_message, run_id),
        )

    def increment_run_progress(self, run_id: int) -> None:
        self._db.execute_update(
            "UPDATE tb_eval_runs SET progress_done = progress_done + 1 WHERE run_id = ?",
            (run_id,),
        )

    def mark_orphan_runs_failed(self) -> int:
        """서버 재시작 시 running 상태로 남은 run을 failed로 마킹한다."""
        return self._db.execute_update(
            """UPDATE tb_eval_runs SET status = 'failed',
                   error_message = '서버 재시작으로 중단됨',
                   finished_at = now()
               WHERE status IN ('pending', 'running')"""
        )

    # ── 항목별 결과 ──────────────────────────────────────────────────────

    def insert_item_result(self, run_id: int, qa_id: int, **fields) -> int:
        json_fields = {
            "retrieval_json", "judge_json",
            "answer_correctness_v1_json",
            "answer_correctness_v2_json",
            "answer_correctness_f2_json",
            "answer_correctness_judge_json",
            "answer_correctness_json",
            "rule_check_json",
            "metric_status_json",
            "citation_json", "citation_detail_json", "timing_json", "token_usage_json",
            "threshold_fallback_json", "guardrail_json",
        }
        cols = ["run_id", "qa_id"]
        vals: List[Any] = [run_id, qa_id]
        for key, value in fields.items():
            cols.append(key)
            if key in json_fields and value is not None and not isinstance(value, str):
                vals.append(json.dumps(value, ensure_ascii=False))
            else:
                vals.append(value)
        placeholders = ", ".join("?" for _ in cols)
        with self._db.get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                f"INSERT INTO tb_eval_item_results ({', '.join(cols)}) VALUES ({placeholders}) RETURNING result_id",
                tuple(vals),
            )
            return cur.fetchone()[0]  # 2026.10.16 Phase 1.5 - lastrowid → RETURNING

    def list_item_results(
        self,
        run_id: int,
        status: Optional[str] = None,
        question_type: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
        law: Optional[str] = None,
    ) -> Dict[str, Any]:
        # question_type은 tb_eval_item_results 컬럼이 아니라 골드셋 스냅샷에서만
        # 확인 가능하므로, 스냅샷을 먼저 조인한 뒤 파이썬 레벨에서 페이징한다.
        where = ["run_id = ?"]
        params: List[Any] = [run_id]
        if status:
            where.append("status = ?")
            params.append(status)
        where_sql = " AND ".join(where)

        rows = self._db.execute_query(
            f"SELECT * FROM tb_eval_item_results WHERE {where_sql} ORDER BY result_id",
            tuple(params),
        )
        items = [dict(r) for r in rows]

        # 상세 화면용 — 골드셋 스냅샷에서 질문/정답/근거 청크 원문을 조인
        qa_map = self._get_qa_snapshot_map(run_id)
        for item in items:
            snapshot = qa_map.get(item["qa_id"])
            if snapshot:
                item["question"] = snapshot.get("question")
                item["gold_answer"] = snapshot.get("gold_answer")
                item["gold_chunk_ids"] = snapshot.get("gold_chunk_ids")
                item["gold_document_ids"] = snapshot.get("gold_document_ids")
                item["gold_chunk_texts"] = snapshot.get("gold_chunk_texts")
                item["question_type"] = snapshot.get("question_type")
                item["source_meta_json"] = snapshot.get("source_meta_json")
                item["dataset_sequence"] = snapshot.get("dataset_sequence")

        if question_type:
            items = [i for i in items if i.get("question_type") == question_type]
        # 2026.11.20(sooyeon.choi) 수정 - 합본 실행 법령 필터(source_meta_json.law_label)
        if law:
            def _law_of(item: Dict[str, Any]) -> Any:
                meta = item.get("source_meta_json")
                try:
                    meta = json.loads(meta) if isinstance(meta, str) and meta else (meta or {})
                except json.JSONDecodeError:
                    meta = {}
                return meta.get("law_label") if isinstance(meta, dict) else None
            items = [i for i in items if _law_of(i) == law]

        total = len(items)
        start = (page - 1) * page_size
        items = items[start:start + page_size]

        return {"total": total, "items": items}

    def list_item_results_for_export(self, run_id: int) -> List[Dict[str, Any]]:
        """Excel 내보내기용 항목별 결과 전체를 데이터셋 번호순으로 반환한다."""
        rows = self._db.execute_query(
            "SELECT * FROM tb_eval_item_results WHERE run_id = ? ORDER BY result_id",
            (run_id,),
        )
        items = [dict(row) for row in rows]
        qa_map = self._get_qa_snapshot_map(run_id)
        for item in items:
            snapshot = qa_map.get(item["qa_id"])
            if snapshot:
                item["question"] = snapshot.get("question")
                item["question_type"] = snapshot.get("question_type")
                item["dataset_sequence"] = snapshot.get("dataset_sequence")
                # 2026.11.20(sooyeon.choi) 수정 - 결과 Excel 정답 답변·질의ID·법령 열
                item["gold_answer"] = snapshot.get("gold_answer")
                item["source_meta_json"] = snapshot.get("source_meta_json")
        return sorted(
            items,
            key=lambda item: (item.get("dataset_sequence") is None,
                              item.get("dataset_sequence") or item.get("result_id") or 0),
        )

    def qa_snapshot_items(self, run_id: int) -> List[Dict[str, Any]]:
        """2026.11.20(sooyeon.choi) 수정 - run 골드셋 스냅샷 문항 전체(질의ID 계산용)."""
        return list(self._get_qa_snapshot_map(run_id).values())

    def _get_qa_snapshot_map(self, run_id: int) -> Dict[int, Dict[str, Any]]:
        """run이 참조하는 골드셋 스냅샷을 qa_id → QA dict로 변환한다."""
        run = self.get_run(run_id)
        if not run:
            return {}
        goldset = self.get_goldset(run["goldset_id"])
        if not goldset:
            return {}
        items = json.loads(goldset["items_snapshot_json"])
        return {
            item.get("qa_id"): {**item, "dataset_sequence": index}
            for index, item in enumerate(items, start=1)
        }

    # ── 지표 집계 ────────────────────────────────────────────────────────

    def save_run_metrics(self, run_id: int, metrics: Dict[str, Dict[str, Any]]) -> None:
        """집계 저장. 구형 float와 신규 aggregate dict 입력을 모두 허용한다."""
        params_list = [
            (
                run_id, key,
                value.get("value") if isinstance(value, dict) else value,
                value.get("std") if isinstance(value, dict) else None,
                value.get("evaluated_count", 1) if isinstance(value, dict) else 1,
                value.get("excluded_count", 0) if isinstance(value, dict) else 0,
                value.get("error_count", 0) if isinstance(value, dict) else 0,
                value.get("total_count", 1) if isinstance(value, dict) else 1,
                value.get("metric_version", "legacy") if isinstance(value, dict) else "legacy",
                segment,
            )
            for segment, kv in metrics.items()
            for key, value in kv.items()
        ]
        if params_list:
            self._db.execute_many(
                # 2026.10.16 Phase 1.5 - INSERT OR REPLACE → ON CONFLICT (PK: run_id, metric_key, segment)
                """INSERT INTO tb_eval_run_metrics
                   (run_id, metric_key, metric_value, metric_std, evaluated_count,
                    excluded_count, error_count, total_count, metric_version, segment)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT (run_id, metric_key, segment) DO UPDATE SET
                       metric_value = excluded.metric_value, metric_std = excluded.metric_std,
                       evaluated_count = excluded.evaluated_count, excluded_count = excluded.excluded_count,
                       error_count = excluded.error_count, total_count = excluded.total_count,
                       metric_version = excluded.metric_version""",
                params_list,
            )

    def get_run_metrics(self, run_id: int) -> List[Dict[str, Any]]:
        return [
            dict(r) for r in self._db.execute_query(
                """SELECT metric_key, metric_value, metric_std, evaluated_count,
                          excluded_count, error_count, total_count, metric_version, segment
                   FROM tb_eval_run_metrics WHERE run_id = ?""",
                (run_id,),
            )
        ]

    def get_metrics_trend(
        self,
        metric_keys: List[str],
        collection_id: Optional[int] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """완료된 run들의 지표 시계열 (오래된 것부터)."""
        placeholders = ", ".join("?" for _ in metric_keys)
        sql = f"""SELECT r.run_id, r.created_at, r.run_type, m.metric_key, m.metric_value,
                         g.version AS goldset_version, d.name AS dataset_name
                  FROM tb_eval_runs r
                  JOIN tb_eval_run_metrics m ON m.run_id = r.run_id AND m.segment = 'all'
                  LEFT JOIN tb_eval_goldsets g ON g.goldset_id = r.goldset_id
                  LEFT JOIN tb_eval_datasets d ON d.dataset_id = g.dataset_id
                  WHERE r.status = 'completed' AND m.metric_key IN ({placeholders})"""
        params: List[Any] = list(metric_keys)
        if collection_id is not None:
            sql += " AND d.collection_id = ?"
            params.append(collection_id)
        sql += """ AND r.run_id IN (
                      SELECT run_id FROM tb_eval_runs WHERE status = 'completed'
                      ORDER BY run_id DESC LIMIT ?)
                  ORDER BY r.run_id"""
        params.append(limit)
        return [dict(r) for r in self._db.execute_query(sql, tuple(params))]

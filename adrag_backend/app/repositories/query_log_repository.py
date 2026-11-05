# 2026.06.16(sooyeon.choi) 추가 - 쿼리 로그 Repository 신규 (tb_query_logs + tb_query_citations)
#   기존 metadata_repository의 log_query / get_query_history 대체
#   log_query() 반환값: bool → Optional[int] (log_id 반환, 피드백 API 연동)
"""
Query log repository for tb_query_logs and tb_query_citations.
"""

import json
import logging
from typing import Any, Dict, List, Optional

from app.core.config import get_settings
from app.repositories.database import get_database_manager
from app.utils.datetime import now_kst_iso

logger = logging.getLogger(__name__)


class QueryLogRepository:
    """tb_query_logs + tb_query_citations Write/Read Repository."""

    def __init__(self, db_path: str = None):
        self.db = get_database_manager(db_path or get_settings().sqlite_db_path)
        logger.debug("QueryLogRepository initialized")

    # ── tb_query_logs ──────────────────────────────────────────────────────

    def log_query(
        self,
        query_text: str,
        user_id: str,
        session_id: Optional[str] = None,
        collection_id: Optional[int] = None,
        answer_text: Optional[str] = None,
        context_text: Optional[List[str]] = None,
        context_meta: Optional[List[Dict[str, Any]]] = None,
        response_time_s: Optional[float] = None,
        response_time_ms: Optional[float] = None,
        chunks_retrieved: Optional[int] = None,
        answer_generated: bool = False,
        outcome_code: str = "unknown",
        error_message: Optional[str] = None,
        model_id: Optional[str] = None,
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None,
        cost_usd: Optional[float] = None,
        extracted_keywords: Optional[List[str]] = None,
        department_snapshot: Optional[str] = None,
        collection_name_snapshot: Optional[str] = None,
    ) -> Optional[int]:
        """질의 로그를 INSERT하고 log_id를 반환한다 (피드백 API 연동용)."""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                # 2026.06.30(sooyeon.choi) 수정 - 동기화된 사용자 부서명을 질의 시점 스냅샷으로 사용
                user_row = cursor.execute(
                    """
                    SELECT u.department_name AS department
                    FROM   tb_users u
                    WHERE  u.user_id = ?
                    """,
                    (user_id,),
                ).fetchone()
                if user_row is None:
                    logger.error(
                        "Query log skipped: unknown user_id=%r, session_id=%r, collection_id=%r",
                        user_id,
                        session_id,
                        collection_id,
                    )
                    return None

                if session_id is not None:
                    session_row = cursor.execute(
                        "SELECT 1 FROM tb_query_sessions WHERE session_id = ?",
                        (session_id,),
                    ).fetchone()
                    if session_row is None:
                        logger.warning(
                            "Query log session FK cleared: user_id=%r, session_id=%r, collection_id=%r",
                            user_id,
                            session_id,
                            collection_id,
                        )
                        session_id = None

                # 2026.06.19(sooyeon.choi) 추가 - 질의 시점 부서·컬렉션 표시명 스냅샷 보완
                if department_snapshot is None:
                    department_snapshot = user_row["department"]
                if collection_name_snapshot is None and collection_id is not None:
                    collection_row = cursor.execute(
                        "SELECT display_name FROM tb_collections WHERE collection_id = ?",
                        (collection_id,),
                    ).fetchone()
                    collection_name_snapshot = (
                        collection_row["display_name"] if collection_row else None
                    )

                cursor.execute(
                    """
                    INSERT INTO tb_query_logs (
                        session_id, user_id, collection_id,
                        query_text, answer_text,
                        context_text, context_meta,
                        response_time_s, response_time_ms,
                        chunks_retrieved, answer_generated,
                        outcome_code, error_message,
                        model_id, prompt_tokens, completion_tokens, cost_usd,
                        extracted_keywords, department_snapshot,
                        collection_name_snapshot, created_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    RETURNING log_id
                    """,
                    (
                        session_id,
                        user_id,
                        collection_id,
                        query_text,
                        answer_text,
                        json.dumps(context_text or [], ensure_ascii=False),
                        json.dumps(context_meta or [], ensure_ascii=False),
                        round(response_time_s, 2) if response_time_s is not None else None,
                        round(response_time_ms, 2) if response_time_ms is not None else None,
                        chunks_retrieved,
                        bool(answer_generated),
                        outcome_code,
                        error_message,
                        model_id,
                        prompt_tokens,
                        completion_tokens,
                        cost_usd,
                        json.dumps(extracted_keywords, ensure_ascii=False) if extracted_keywords else None,
                        department_snapshot,
                        collection_name_snapshot,
                        now_kst_iso(),
                    ),
                )
                return cursor.fetchone()[0]  # 2026.10.16 Phase 1.5 - lastrowid → RETURNING
        except Exception as e:
            logger.error(
                "Query log failed: %s | user_id=%r, session_id=%r, collection_id=%r",
                e,
                user_id,
                session_id,
                collection_id,
            )
            return None

    def set_feedback(
        self,
        log_id: int,
        user_id: str,
        feedback: Optional[int],
        reasons: Optional[List[str]] = None,
        comment: Optional[str] = None,
    ) -> bool:
        """피드백 저장 (1=좋아요, 0=별로에요, None=취소).
        user_id 조건으로 본인 로그만 수정 가능하다.
        사유·의견은 매 호출마다 덮어쓴다(평가만 바꾸면 이전 사유·의견은 비워진다).
        """
        # 2026.11.05(woojin.jung) 수정 - 피드백 사유(feedback_reasons)·의견(feedback_comment) 저장 추가
        feedback_at = now_kst_iso() if feedback is not None else None
        affected = self.db.execute_update(
            """
            UPDATE tb_query_logs
            SET feedback=?, feedback_at=?, feedback_reasons=?, feedback_comment=?
            WHERE log_id=? AND user_id=?
            """,
            (
                feedback,
                feedback_at,
                json.dumps(reasons, ensure_ascii=False) if reasons else None,
                comment or None,
                log_id,
                user_id,
            ),
        )
        return affected > 0

    def get_history(
        self,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        collection_id: Optional[int] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """질의 이력 조회 (관리자: user_id 없이 전체, 사용자: user_id 필터)."""
        conditions = ["1=1"]
        params: list = []
        if user_id:
            conditions.append("user_id = ?")
            params.append(user_id)
        if session_id:
            conditions.append("session_id = ?")
            params.append(session_id)
        if collection_id is not None:
            conditions.append("collection_id = ?")
            params.append(collection_id)
        where = "WHERE " + " AND ".join(conditions)
        rows = self.db.execute_query(
            f"""
            SELECT log_id, session_id, user_id, collection_id,
                   query_text, answer_text, answer_generated, chunks_retrieved,
                   context_text, context_meta, response_time_s, response_time_ms,
                   outcome_code, error_message,
                   model_id, cost_usd, department_snapshot,
                   collection_name_snapshot, feedback, feedback_at, created_at
            FROM tb_query_logs
            {where}
            ORDER BY created_at DESC LIMIT ?
            """,
            tuple(params) + (limit,),
        )
        return [
            {
                "log_id": r["log_id"],
                "session_id": r["session_id"],
                "user_id": r["user_id"],
                "collection_id": r["collection_id"],
                "query_text": r["query_text"],
                # 2026.06.24(woojin.jung) 추가 - 채팅 히스토리와 쿼리 로그의 응답 매칭
                "answer_text": r["answer_text"],
                "context_text": json.loads(r["context_text"]) if r["context_text"] is not None else None,
                "context_meta": json.loads(r["context_meta"]) if r["context_meta"] is not None else None,
                "answer_generated": bool(r["answer_generated"]),
                "chunks_retrieved": r["chunks_retrieved"],
                "response_time_ms": r["response_time_ms"],
                "response_time_s": r["response_time_s"],
                "outcome_code": r["outcome_code"],
                "error_message": r["error_message"],
                "model_id": r["model_id"],
                "cost_usd": r["cost_usd"],
                "department_snapshot": r["department_snapshot"],
                "collection_name_snapshot": r["collection_name_snapshot"],
                "feedback": r["feedback"],
                "feedback_at": r["feedback_at"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    # ── tb_query_citations ─────────────────────────────────────────────────

    def store_citations(
        self, log_id: int, citations: List[Dict[str, Any]]
    ) -> None:
        """인용 문서 목록을 tb_query_citations에 일괄 INSERT한다.

        citations 항목은 document_id, original_filename, collection_id 키를 포함해야 한다.
        """
        # 2026.06.19(sooyeon.choi) 추가 - 동일 질의의 동일 문서 인용 중복 제거
        unique_citations: Dict[str, Dict[str, Any]] = {}
        for citation in citations:
            document_id = citation.get("document_id")
            if document_id and document_id not in unique_citations:
                unique_citations[document_id] = citation

        rows = [
            (
                log_id,
                document_id,
                citation.get("original_filename", ""),
                citation.get("collection_id"),
                citation.get("collection_name_snapshot"),
                now_kst_iso(),
            )
            for document_id, citation in unique_citations.items()
        ]
        if not rows:
            return
        try:
            self.db.execute_many(
                """
                INSERT INTO tb_query_citations
                    (log_id, document_id, original_filename, collection_id,
                     collection_name_snapshot, cited_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (log_id, document_id) DO NOTHING
                """,
                rows,
            )
        except Exception as e:
            logger.error("Citation store failed log_id=%s: %s", log_id, e)

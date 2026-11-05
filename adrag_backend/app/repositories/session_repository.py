# 2026.06.16(sooyeon.choi) 추가 - 대화 세션 Repository 신규 (tb_query_sessions)
#   기존 metadata_repository의 QueryContext 관련 메서드 대체
#   변경: collection_name(TEXT) → collection_id(Optional[int])
"""
Session repository for tb_query_sessions.
"""

import json
import logging
from datetime import timedelta
from typing import Optional

from app.core.config import get_settings
from app.models.data_models import QueryContext
from app.repositories.database import get_database_manager
from app.utils.datetime import now_kst, now_kst_iso

logger = logging.getLogger(__name__)

_SESSION_TTL_DAYS = 14


class SessionRepository:
    """tb_query_sessions CRUD Repository."""

    def __init__(self, db_path: str = None):
        self.db = get_database_manager(db_path or get_settings().sqlite_db_path)
        logger.debug("SessionRepository initialized")

    def _row_to_context(self, row) -> QueryContext:
        from datetime import datetime
        def _parse_dt(s):
            return datetime.fromisoformat(s) if s else None

        return QueryContext(
            session_id=row["session_id"],
            user_id=row["user_id"],
            collection_id=row["collection_id"],
            conversation_history=json.loads(row["conversation_history"] or "[]"),
            created_at=_parse_dt(row["created_at"]) or now_kst(),
            updated_at=_parse_dt(row["updated_at"]) or now_kst(),
            expires_at=_parse_dt(row["expires_at"]),
        )

    # ── 저장 ─────────────────────────────────────────────────────────────────

    def upsert(self, context: QueryContext) -> bool:
        """세션을 INSERT 또는 UPDATE한다."""
        now = now_kst()
        expires_at = context.expires_at or (now + timedelta(days=_SESSION_TTL_DAYS))
        try:
            self.db.execute_update(
                """
                INSERT INTO tb_query_sessions
                    (session_id, user_id, collection_id, conversation_history,
                     created_at, updated_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    conversation_history = excluded.conversation_history,
                    updated_at           = excluded.updated_at,
                    expires_at           = excluded.expires_at
                """,
                (
                    context.session_id,
                    context.user_id,
                    context.collection_id,
                    json.dumps(context.conversation_history, ensure_ascii=False),
                    context.created_at.isoformat(),
                    now.isoformat(),
                    expires_at.isoformat(),
                ),
            )
            return True
        except Exception as e:
            logger.error("Session upsert failed: %s", e)
            return False

    # ── 조회 ─────────────────────────────────────────────────────────────────

    def get_by_id(self, session_id: str) -> Optional[QueryContext]:
        """session_id로 유효한(만료되지 않은) 세션 조회."""
        now = now_kst_iso()
        rows = self.db.execute_query(
            """
            SELECT * FROM tb_query_sessions
            WHERE session_id = ?
              AND (expires_at IS NULL OR expires_at >= ?)
            """,
            (session_id, now),
        )
        return self._row_to_context(rows[0]) if rows else None

    def get_by_user_collection(
        self, user_id: str, collection_id: int
    ) -> Optional[QueryContext]:
        """(user_id, collection_id) 조합으로 유효한 최신 세션 조회."""
        now = now_kst_iso()
        rows = self.db.execute_query(
            """
            SELECT * FROM tb_query_sessions
            WHERE user_id = ? AND collection_id = ?
              AND (expires_at IS NULL OR expires_at >= ?)
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (user_id, collection_id, now),
        )
        return self._row_to_context(rows[0]) if rows else None

    # ── 초기화 / 삭제 ─────────────────────────────────────────────────────────

    def reset(self, user_id: str, collection_id: int) -> bool:
        """대화 이력을 초기화하고 만료 기간을 갱신한다 ('새 채팅 시작')."""
        now = now_kst()
        expires_at = (now + timedelta(days=_SESSION_TTL_DAYS)).isoformat()
        affected = self.db.execute_update(
            """
            UPDATE tb_query_sessions
            SET conversation_history = '[]',
                updated_at = ?,
                expires_at = ?
            WHERE user_id = ? AND collection_id = ?
            """,
            (now.isoformat(), expires_at, user_id, collection_id),
        )
        return affected > 0

    def delete_expired(self) -> int:
        """만료된 세션을 일괄 삭제하고 삭제 건수를 반환한다."""
        now = now_kst_iso()
        count = self.db.execute_update(
            "DELETE FROM tb_query_sessions WHERE expires_at IS NOT NULL AND expires_at < ?",
            (now,),
        )
        if count:
            logger.info("만료 세션 %d건 삭제", count)
        return count
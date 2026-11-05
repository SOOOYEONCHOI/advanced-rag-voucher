"""Repository for login audit history."""

import logging
from typing import Optional

from app.repositories.database import get_database_manager

logger = logging.getLogger(__name__)


class LoginHistoryRepository:
    """Stores login success/failure audit rows.

    Audit writes are best-effort: failures are logged but do not block auth.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db = get_database_manager(db_path)

    def record(
        self,
        *,
        attempted_user_id: str,
        user_id: Optional[str] = None,
        user_role: Optional[str] = None,
        # 2026.06.30(sooyeon.choi) 추가 - 로그인 당시 부서명 스냅샷임을 명시
        department_snapshot: Optional[str] = None,
        success: bool,
        failure_reason: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        auth_session_id: Optional[str] = None,
    ) -> None:
        try:
            self.db.execute_update(
                """
                INSERT INTO tb_login_history (
                    attempted_user_id,
                    user_id,
                    user_role,
                    department_snapshot,
                    success,
                    failure_reason,
                    ip_address,
                    user_agent,
                    auth_session_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attempted_user_id,
                    user_id,
                    user_role,
                    department_snapshot,
                    bool(success),
                    failure_reason,
                    ip_address,
                    user_agent,
                    auth_session_id,
                ),
            )
        except Exception:
            logger.exception("Failed to record login history for %s", attempted_user_id)

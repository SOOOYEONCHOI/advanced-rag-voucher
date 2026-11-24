# 2026.09.17(woojin.jung) 추가 - 사용자 UI 연동 설정 조회 및 수정 Repository 추가
"""사용자 UI 연동 설정 데이터 접근 계층."""

from typing import Optional

from app.repositories.database import DatabaseManager, get_database_manager


class UiSettingsRepository:
    """tb_users의 UI 연동 설정을 조회하고 수정한다."""

    def __init__(
        self,
        db: Optional[DatabaseManager] = None,
    ) -> None:
        self.db = db or get_database_manager()

    def get_ui_type(self, user_id: str) -> tuple[bool, Optional[str]]:
        rows = self.db.execute_query(
            """
            SELECT ui_type
            FROM tb_users
            WHERE user_id = ? AND role IN ('user', 'manager')
            """,
            (user_id,),
        )
        return (True, rows[0]["ui_type"]) if rows else (False, None)

    def select_ui_type(self, user_id: str, ui_type: str, updated_at: str) -> bool:
        updated = self.db.execute_update(
            """
            UPDATE tb_users
            SET ui_type = ?, updated_at = ?
            WHERE user_id = ? AND role IN ('user', 'manager') AND ui_type IS NULL
            """,
            (ui_type, updated_at, user_id),
        )
        return updated > 0

    def user_exists(self, user_id: str) -> bool:
        rows = self.db.execute_query(
            "SELECT 1 FROM tb_users WHERE user_id = ? AND role IN ('user', 'manager')",
            (user_id,),
        )
        return bool(rows)

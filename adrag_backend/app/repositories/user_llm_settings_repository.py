# 2026.06.16(sooyeon.choi) 수정 - collection_name(TEXT) → collection_id(INTEGER FK)
"""
사용자별/컬렉션별 LLM 설정 Repository.

tb_user_llm_settings: 사용자가 마지막으로 선택한 모델 + 암호화된 API 키 관리.
"""

import logging
from dataclasses import dataclass
from typing import Optional

from app.core.config import get_settings
from app.repositories.database import get_database_manager
from app.utils.datetime import now_kst_iso

logger = logging.getLogger(__name__)


@dataclass
class UserLlmSetting:
    user_id: str
    collection_id: int          # 2026.06.16(sooyeon.choi) 수정: collection_name → collection_id
    model_id: str
    api_key_enc: Optional[str]
    setting_id: Optional[int] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class UserLlmSettingsRepository:
    """tb_user_llm_settings CRUD Repository."""

    def __init__(self, db_path: str = None):
        self.db = get_database_manager(db_path or get_settings().sqlite_db_path)
        logger.debug("UserLlmSettingsRepository initialized")

    def _row_to_setting(self, row) -> UserLlmSetting:
        return UserLlmSetting(
            setting_id=row["setting_id"],
            user_id=row["user_id"],
            collection_id=row["collection_id"],
            model_id=row["model_id"],
            api_key_enc=row["api_key_enc"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def get(self, user_id: str, collection_id: int) -> Optional[UserLlmSetting]:
        """사용자+컬렉션 기준으로 저장된 LLM 설정을 조회한다."""
        rows = self.db.execute_query(
            "SELECT * FROM tb_user_llm_settings WHERE user_id=? AND collection_id=?",
            (user_id, collection_id),
        )
        return self._row_to_setting(rows[0]) if rows else None

    def save(
        self,
        user_id: str,
        collection_id: int,
        model_id: str,
        api_key_enc: Optional[str] = None,
    ) -> UserLlmSetting:
        """설정을 저장한다 (없으면 INSERT, 있으면 UPDATE)."""
        now = now_kst_iso()
        existing = self.get(user_id, collection_id)
        if existing:
            self.db.execute_update(
                """
                UPDATE tb_user_llm_settings
                SET model_id=?, api_key_enc=?, updated_at=?
                WHERE user_id=? AND collection_id=?
                """,
                (model_id, api_key_enc, now, user_id, collection_id),
            )
        else:
            self.db.execute_update(
                """
                INSERT INTO tb_user_llm_settings
                    (user_id, collection_id, model_id, api_key_enc, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, collection_id, model_id, api_key_enc, now, now),
            )
        return self.get(user_id, collection_id)

    def delete(self, user_id: str, collection_id: int) -> bool:
        affected = self.db.execute_update(
            "DELETE FROM tb_user_llm_settings WHERE user_id=? AND collection_id=?",
            (user_id, collection_id),
        )
        return affected > 0

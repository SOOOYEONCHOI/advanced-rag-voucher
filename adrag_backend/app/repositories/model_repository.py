"""
LLM 모델 관리 Repository.

tb_llm_models 테이블에 대한 CRUD 작업을 수행한다.
"""

import logging
from dataclasses import dataclass
from typing import List, Optional

from app.repositories.database import get_database_manager
from app.utils.datetime import now_kst_iso

logger = logging.getLogger(__name__)


@dataclass
class LlmModel:
    model_id: str
    model_name: str
    provider: str
    requires_api_key: bool
    is_enabled: bool
    sort_order: int
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ModelRepository:
    """Repository for tb_llm_models CRUD operations."""

    def __init__(self):
        self.db = get_database_manager()

    def _row_to_model(self, row) -> LlmModel:
        return LlmModel(
            model_id=row["model_id"],
            model_name=row["model_name"],
            provider=row["provider"],
            requires_api_key=bool(row["requires_api_key"]),
            is_enabled=bool(row["is_enabled"]),
            sort_order=row["sort_order"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # ── 조회 ──────────────────────────────────────────────────────────────────

    def get_all(self) -> List[LlmModel]:
        """전체 모델 목록 (관리자용, 비활성 포함)."""
        rows = self.db.execute_query(
            "SELECT * FROM tb_llm_models ORDER BY sort_order ASC, model_id ASC"
        )
        return [self._row_to_model(r) for r in rows]

    def get_enabled(self) -> List[LlmModel]:
        """활성화된 모델 목록 (프론트엔드용)."""
        rows = self.db.execute_query(
            "SELECT * FROM tb_llm_models WHERE is_enabled = TRUE ORDER BY sort_order ASC, model_id ASC"
        )
        return [self._row_to_model(r) for r in rows]

    def get_by_id(self, model_id: str) -> Optional[LlmModel]:
        rows = self.db.execute_query(
            "SELECT * FROM tb_llm_models WHERE model_id = ?", (model_id,)
        )
        return self._row_to_model(rows[0]) if rows else None

    # ── 생성 ──────────────────────────────────────────────────────────────────

    def create(
        self,
        model_id: str,
        model_name: str,
        provider: str,
        requires_api_key: bool = False,
        is_enabled: bool = True,
        sort_order: int = 0,
    ) -> LlmModel:
        now = now_kst_iso()
        self.db.execute_update(
            """
            INSERT INTO tb_llm_models
                (model_id, model_name, provider, requires_api_key, is_enabled, sort_order, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (model_id, model_name, provider, bool(requires_api_key), bool(is_enabled), sort_order, now, now),
        )
        return self.get_by_id(model_id)

    # ── 수정 ──────────────────────────────────────────────────────────────────

    def update(
        self,
        model_id: str,
        model_name: Optional[str] = None,
        provider: Optional[str] = None,
        requires_api_key: Optional[bool] = None,
        is_enabled: Optional[bool] = None,
        sort_order: Optional[int] = None,
    ) -> Optional[LlmModel]:
        current = self.get_by_id(model_id)
        if not current:
            return None

        now = now_kst_iso()
        self.db.execute_update(
            """
            UPDATE tb_llm_models SET
                model_name       = ?,
                provider         = ?,
                requires_api_key = ?,
                is_enabled       = ?,
                sort_order       = ?,
                updated_at       = ?
            WHERE model_id = ?
            """,
            (
                model_name if model_name is not None else current.model_name,
                provider if provider is not None else current.provider,
                bool(requires_api_key) if requires_api_key is not None else bool(current.requires_api_key),
                bool(is_enabled) if is_enabled is not None else bool(current.is_enabled),
                sort_order if sort_order is not None else current.sort_order,
                now,
                model_id,
            ),
        )
        return self.get_by_id(model_id)

    # ── 삭제 ──────────────────────────────────────────────────────────────────

    def delete(self, model_id: str) -> bool:
        affected = self.db.execute_update(
            "DELETE FROM tb_llm_models WHERE model_id = ?", (model_id,)
        )
        return affected > 0

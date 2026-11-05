# 2026.06.16(sooyeon.choi) 추가 - 권한 Repository 신규 (tb_user_collection_permissions + tb_user_security_policies)
#   기존 metadata_repository의 store_user_permission / get_user_permissions 대체
"""
Permissions repository for tb_user_collection_permissions and tb_user_security_policies.
"""

import json
import logging
from typing import List, Optional

from app.core.config import get_settings
from app.models.data_models import (
    SecurityLevel,
    UserCollectionPermission,
    UserPermission,
    UserSecurityPolicy,
)
from app.repositories.database import get_database_manager
from app.repositories.collection_repository import CollectionRepository
from app.utils.datetime import now_kst_iso

logger = logging.getLogger(__name__)


class PermissionsRepository:
    """tb_user_collection_permissions + tb_user_security_policies CRUD Repository."""

    def __init__(self, db_path: str = None):
        resolved_db_path = db_path or get_settings().sqlite_db_path
        self.db = get_database_manager(resolved_db_path)
        # 2026.06.30(sooyeon.choi) 추가 - 화면과 RAG가 동일한 실질 접근 컬렉션 조회를 사용
        self.collection_repo = CollectionRepository(resolved_db_path)
        logger.debug("PermissionsRepository initialized")

    # ── 컬렉션 접근 권한 (tb_user_collection_permissions) ─────────────────────

    def grant(
        self,
        user_id: str,
        collection_id: int,
    ) -> bool:
        """컬렉션 접근 권한 부여."""
        now = now_kst_iso()
        try:
            self.db.execute_update(
                """
                INSERT INTO tb_user_collection_permissions
                    (user_id, collection_id, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id, collection_id) DO NOTHING
                """,
                (user_id, collection_id, now),
            )
            return True
        except Exception as e:
            logger.error("Permission grant failed: %s", e)
            return False

    def revoke_all(self, user_id: str) -> int:
        """사용자의 모든 컬렉션 권한 회수."""
        return self.db.execute_update(
            "DELETE FROM tb_user_collection_permissions WHERE user_id=?", (user_id,)
        )

    def get_user_collection_permissions(self, user_id: str) -> List[UserCollectionPermission]:
        """사용자의 컬렉션별 권한 목록."""
        rows = self.db.execute_query(
            """
            SELECT p.permission_id, p.user_id, p.collection_id,
                   p.created_at
            FROM tb_user_collection_permissions p
            WHERE p.user_id = ?
            ORDER BY p.created_at
            """,
            (user_id,),
        )
        return [
            UserCollectionPermission(
                permission_id=r["permission_id"],
                user_id=r["user_id"],
                collection_id=r["collection_id"],
                created_at=r["created_at"],
            )
            for r in rows
        ]

    # ── 보안 정책 (tb_user_security_policies) ────────────────────────────────

    def upsert_policy(self, policy: UserSecurityPolicy) -> bool:
        """보안 정책 생성 또는 갱신."""
        now = now_kst_iso()
        try:
            self.db.execute_update(
                """
                INSERT INTO tb_user_security_policies
                    (user_id, max_security_level, allowed_doc_types, metadata_filters, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    max_security_level = excluded.max_security_level,
                    allowed_doc_types  = excluded.allowed_doc_types,
                    metadata_filters   = excluded.metadata_filters,
                    updated_at         = excluded.updated_at
                """,
                (
                    policy.user_id,
                    policy.max_security_level or SecurityLevel.PUBLIC,
                    json.dumps(policy.allowed_doc_types or [], ensure_ascii=False),
                    json.dumps(policy.metadata_filters or {}, ensure_ascii=False),
                    now,
                ),
            )
            return True
        except Exception as e:
            logger.error("Security policy upsert failed: %s", e)
            return False

    def get_policy(self, user_id: str) -> Optional[UserSecurityPolicy]:
        """사용자 보안 정책 조회."""
        rows = self.db.execute_query(
            "SELECT * FROM tb_user_security_policies WHERE user_id=?", (user_id,)
        )
        if not rows:
            return None
        r = rows[0]
        return UserSecurityPolicy(
            user_id=r["user_id"],
            max_security_level=r["max_security_level"],
            allowed_doc_types=json.loads(r["allowed_doc_types"] or "[]"),
            metadata_filters=json.loads(r["metadata_filters"] or "{}"),
            updated_at=r["updated_at"],
        )

    def create_default_policy(self, user_id: str) -> bool:
        """신규 user 생성 시 기본 보안 정책 행을 생성한다."""
        return self.upsert_policy(UserSecurityPolicy(user_id=user_id))

    # ── RAG 파이프라인용 통합 조회 ─────────────────────────────────────────────

    def get_user_permission(self, user_id: str) -> Optional[UserPermission]:
        """RAG 파이프라인 필터 빌드용 통합 UserPermission 조립.

        2026.06.29(sooyeon.choi) 수정 - tb_user_collection_permissions 기반 조회를
        effective_topics(부서 주제 − 개인 차단) 기반 컬렉션 조회로 교체.
        tb_user_security_policies 조회는 그대로 유지.
        """
        # 2026.06.30(sooyeon.choi) 추가 - 같은 부서의 실질 접근 컬렉션으로 권한 계산 통일
        accessible = [
            collection.qdrant_name
            for collection in self.collection_repo.get_accessible_by_user(user_id)
        ]

        policy = self.get_policy(user_id)
        if policy is None:
            policy = UserSecurityPolicy(user_id=user_id)

        return UserPermission(
            user_id=user_id,
            accessible_collections=accessible,
            max_security_level=policy.max_security_level,
            allowed_document_types=policy.allowed_doc_types,
            metadata_filters=policy.metadata_filters,
        )


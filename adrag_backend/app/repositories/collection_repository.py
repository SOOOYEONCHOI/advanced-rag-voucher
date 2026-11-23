"""
2026.06.16(sooyeon.choi) 수정
#   - collection_name → display_name, collection_desc → description
#   - is_active 필드 추가
#   - get_by_display_name() 추가 (기존 get_by_name() 대체)
#   - get_by_qdrant_name() 유지 (Qdrant 접근 시 사용)
Collection repository for managing tb_collections in SQLite.
"""

import logging
from typing import List, Optional

from app.models.data_models import CollectionConfig
from app.repositories.database import get_database_manager
from app.utils.datetime import now_kst_iso

logger = logging.getLogger(__name__)

_SELECT = (
    "SELECT collection_id, display_name, qdrant_name, description, "
    # 2026.06.30(sooyeon.choi) 추가 - topic_name, 부서 ID·부서명 컬럼 포함
    "topic_name, department_id, department_name, "
    "created_by, is_active, created_at, updated_at "
    "FROM tb_collections"
)


def _row_to_config(row) -> CollectionConfig:
    keys = row.keys() if hasattr(row, "keys") else []
    return CollectionConfig(
        collection_id=row["collection_id"],
        display_name=row["display_name"],
        description=row["description"] or "",
        qdrant_name=row["qdrant_name"] or "",
        created_by=row["created_by"],
        is_active=bool(row["is_active"]),
        created_at=row["created_at"] or "",
        updated_at=row["updated_at"] or "",
        # 2026.06.29(sooyeon.choi) 추가
        topic_name=row["topic_name"] if "topic_name" in keys else None,
        department_id=row["department_id"] if "department_id" in keys else None,
        department_name=row["department_name"] if "department_name" in keys else "",
    )


class CollectionRepository:
    """tb_collections CRUD Repository."""

    def __init__(self):
        self.db = get_database_manager()
        logger.debug("CollectionRepository initialized")

    # ── 생성 ─────────────────────────────────────────────────────────────────

    def create(
        self,
        display_name: str,
        description: str = "",
        created_by: str = None,
        qdrant_name: str = "",
        # 2026.06.29(sooyeon.choi) 추가 - 대화 주제 + 생성자 부서 스냅샷
        topic_name: str = None,
        department_id: str = None,
        # 2026.06.30(sooyeon.choi) 추가 - 생성자 부서명 동기화 값
        department_name: str = "",
    ) -> CollectionConfig:
        """컬렉션 INSERT 후 CollectionConfig 반환."""
        now = now_kst_iso()
        resolved_qdrant = qdrant_name or (
            f"{created_by}_{display_name}" if created_by else display_name
        )
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO tb_collections
                    (display_name, qdrant_name, description, created_by,
                     topic_name, department_id, department_name,
                     is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, TRUE, ?, ?)
                RETURNING collection_id
                """,
                (display_name, resolved_qdrant, description, created_by,
                 topic_name, department_id, department_name,
                 now, now),
            )
            new_id = cursor.fetchone()[0]  # 2026.10.16 Phase 1.5 - lastrowid → RETURNING

        return CollectionConfig(
            collection_id=new_id,
            display_name=display_name,
            description=description,
            qdrant_name=resolved_qdrant,
            created_by=created_by,
            is_active=True,
            created_at=now,
            updated_at=now,
            topic_name=topic_name,
            department_id=department_id,
            department_name=department_name,
        )

    # ── 조회 ─────────────────────────────────────────────────────────────────

    def get_all(self, include_inactive: bool = False) -> List[CollectionConfig]:
        """전체 컬렉션 목록 (기본: 활성만)."""
        where = "" if include_inactive else "WHERE is_active = TRUE"
        rows = self.db.execute_query(f"{_SELECT} {where} ORDER BY created_at")
        return [_row_to_config(r) for r in rows]

    def get_by_id(self, collection_id: int) -> Optional[CollectionConfig]:
        rows = self.db.execute_query(
            f"{_SELECT} WHERE collection_id = ?", (collection_id,)
        )
        return _row_to_config(rows[0]) if rows else None

    def get_by_display_name(self, display_name: str, created_by: str = None) -> Optional[CollectionConfig]:
        """display_name (+ 선택적 created_by) 로 조회."""
        if created_by is not None:
            rows = self.db.execute_query(
                f"{_SELECT} WHERE display_name = ? AND created_by = ?",
                (display_name, created_by),
            )
        else:
            rows = self.db.execute_query(
                f"{_SELECT} WHERE display_name = ?", (display_name,)
            )
        return _row_to_config(rows[0]) if rows else None

    def get_by_qdrant_name(self, qdrant_name: str) -> Optional[CollectionConfig]:
        """qdrant_name으로 조회 (Qdrant 접근 시 사용)."""
        rows = self.db.execute_query(
            f"{_SELECT} WHERE qdrant_name = ?", (qdrant_name,)
        )
        return _row_to_config(rows[0]) if rows else None

    def get_by_owner(self, created_by: str) -> List[CollectionConfig]:
        rows = self.db.execute_query(
            f"{_SELECT} WHERE created_by = ? AND is_active = TRUE ORDER BY created_at",
            (created_by,),
        )
        return [_row_to_config(r) for r in rows]

    # 2026.11.20(woojin.jung) 추가 - 부서 운영관리자 관리 대상(수정 권한은 부서 기준)
    def get_by_department(self, department_id: str) -> List[CollectionConfig]:
        rows = self.db.execute_query(
            f"{_SELECT} WHERE department_id = ? AND is_active = TRUE ORDER BY created_at",
            (department_id,),
        )
        return [_row_to_config(r) for r in rows]

    # 2026.06.30(sooyeon.choi) 추가 - 부서 허용 주제와 개인 차단 기준의 실질 접근 컬렉션 조회
    def get_accessible_by_user(self, user_id: str) -> List[CollectionConfig]:
        rows = self.db.execute_query(
            """
            SELECT c.collection_id, c.display_name, c.qdrant_name, c.description,
                   c.topic_name, c.department_id, c.department_name,
                   c.created_by, c.is_active,
                   c.created_at, c.updated_at
            FROM tb_collections c
            JOIN tb_users u
              ON u.user_id = ?
            JOIN tb_departments d
              ON d.department_id = u.department_id
            WHERE c.is_active = TRUE
              AND d.is_active = TRUE
              AND c.department_id = u.department_id
              -- 2026.10.16 Phase 1.5 - json_each → jsonb_array_elements_text
              AND EXISTS (
                  SELECT 1
                  FROM jsonb_array_elements_text(COALESCE(d.allowed_topics, '[]'::jsonb)) AS t(value)
                  WHERE t.value = c.topic_name
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM jsonb_array_elements_text(COALESCE(u.blocked_topics, '[]'::jsonb)) AS t(value)
                  WHERE t.value = c.topic_name
              )
            ORDER BY c.created_at
            """,
            (user_id,),
        )
        return [_row_to_config(r) for r in rows]

    def count(self) -> int:
        rows = self.db.execute_query("SELECT COUNT(*) FROM tb_collections WHERE is_active = TRUE")
        return rows[0][0]

    def count_by_owner(self, created_by: str) -> int:
        rows = self.db.execute_query(
            "SELECT COUNT(*) FROM tb_collections WHERE created_by = ? AND is_active = TRUE",
            (created_by,),
        )
        return rows[0][0]

    # ── 수정 ─────────────────────────────────────────────────────────────────

    def update(
        self,
        collection_id: int,
        display_name: str = None,
        description: str = None,
    ) -> Optional[CollectionConfig]:
        existing = self.get_by_id(collection_id)
        if existing is None:
            return None
        new_name = display_name if display_name is not None else existing.display_name
        new_desc = description if description is not None else existing.description
        now = now_kst_iso()
        self.db.execute_update(
            "UPDATE tb_collections SET display_name=?, description=?, updated_at=? WHERE collection_id=?",
            (new_name, new_desc, now, collection_id),
        )
        return CollectionConfig(
            collection_id=collection_id,
            display_name=new_name,
            description=new_desc,
            qdrant_name=existing.qdrant_name,
            created_by=existing.created_by,
            is_active=existing.is_active,
            created_at=existing.created_at,
            updated_at=now,
            topic_name=existing.topic_name,
            department_id=existing.department_id,
            department_name=existing.department_name,
        )

    # ── 삭제 ─────────────────────────────────────────────────────────────────

    def delete(self, collection_id: int, conn=None) -> bool:
        """Hard Delete. 문서(tb_documents)가 있으면 RESTRICT FK로 실패한다."""
        if conn is not None:
            affected = conn.execute(
                "DELETE FROM tb_collections WHERE collection_id = ?",
                (collection_id,),
            ).rowcount
        else:
            affected = self.db.execute_update(
                "DELETE FROM tb_collections WHERE collection_id = ?",
                (collection_id,),
            )
        return affected > 0

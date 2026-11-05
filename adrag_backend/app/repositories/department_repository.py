# 2026.06.29(sooyeon.choi) 추가 - 사용자 권한 관리: tb_departments CRUD Repository
"""
부서 Repository — tb_departments CRUD.
"""

import json
import logging
from typing import Any, Dict, List, Optional

from app.core.config import get_settings
from app.repositories.database import get_database_manager
from app.utils.datetime import now_kst_iso

logger = logging.getLogger(__name__)


def _row_to_dict(row) -> Dict[str, Any]:
    return {
        "department_id": row["department_id"],
        "department_name": row["department_name"],
        "allowed_topics": json.loads(row["allowed_topics"] or "[]"),
        "is_active": bool(row["is_active"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


class DepartmentRepository:
    """tb_departments CRUD Repository."""

    def __init__(self, db_path: Optional[str] = None):
        self.db = get_database_manager(db_path or get_settings().sqlite_db_path)

    # ── 채번 ────────────────────────────────────────────────────────────────

    def _next_dept_id(self, conn) -> str:
        """트랜잭션 내에서 호출해야 한다. 경쟁조건 방지."""
        row = conn.execute(
            "SELECT MAX(CAST(SUBSTR(department_id, 2) AS INTEGER)) AS n "
            "FROM tb_departments"
        ).fetchone()
        n = (row["n"] or 0) + 1
        return f"D{n:03d}"

    # ── 생성 ────────────────────────────────────────────────────────────────

    def create(self, department_name: str) -> Dict[str, Any]:
        """부서를 생성하고 생성된 레코드를 반환한다."""
        now = now_kst_iso()
        with self.db.get_connection() as conn:
            dept_id = self._next_dept_id(conn)
            conn.execute(
                """
                INSERT INTO tb_departments
                    (department_id, department_name, allowed_topics, is_active, created_at, updated_at)
                VALUES (?, ?, '[]', TRUE, ?, ?)
                """,
                (dept_id, department_name, now, now),
            )
        return self.get_by_id(dept_id)

    # ── 조회 ────────────────────────────────────────────────────────────────

    def get_all(self, search: Optional[str] = None) -> List[Dict[str, Any]]:
        """전체 부서 목록. search가 주어지면 department_name LIKE 필터 적용."""
        if search:
            rows = self.db.execute_query(
                "SELECT d.*, "
                "  (SELECT COUNT(*) FROM tb_users u WHERE u.department_id = d.department_id) AS user_count "
                "FROM tb_departments d "
                "WHERE d.department_name ILIKE ? "
                "ORDER BY d.department_id",
                (f"%{search}%",),
            )
        else:
            rows = self.db.execute_query(
                "SELECT d.*, "
                "  (SELECT COUNT(*) FROM tb_users u WHERE u.department_id = d.department_id) AS user_count "
                "FROM tb_departments d "
                "ORDER BY d.department_id",
            )
        result = []
        for r in rows:
            d = _row_to_dict(r)
            d["user_count"] = r["user_count"]
            result.append(d)
        return result

    def get_by_id(self, department_id: str) -> Optional[Dict[str, Any]]:
        rows = self.db.execute_query(
            "SELECT d.*, "
            "  (SELECT COUNT(*) FROM tb_users u WHERE u.department_id = d.department_id) AS user_count "
            "FROM tb_departments d "
            "WHERE d.department_id = ?",
            (department_id,),
        )
        if not rows:
            return None
        d = _row_to_dict(rows[0])
        d["user_count"] = rows[0]["user_count"]
        return d

    def get_by_name(self, department_name: str) -> Optional[Dict[str, Any]]:
        rows = self.db.execute_query(
            "SELECT * FROM tb_departments WHERE department_name = ?", (department_name,)
        )
        return _row_to_dict(rows[0]) if rows else None

    # ── 수정 ────────────────────────────────────────────────────────────────

    def update(
        self,
        department_id: str,
        department_name: Optional[str] = None,
        allowed_topics: Optional[List[str]] = None,
        is_active: Optional[bool] = None,
    ) -> Optional[Dict[str, Any]]:
        """부서 수정. None 필드는 기존 값 유지."""
        existing = self.get_by_id(department_id)
        if existing is None:
            return None

        new_name = (
            department_name
            if department_name is not None
            else existing["department_name"]
        )
        new_topics = allowed_topics if allowed_topics is not None else existing["allowed_topics"]
        new_active = is_active if is_active is not None else existing["is_active"]
        now = now_kst_iso()

        # 2026.06.30(sooyeon.choi) 추가 - 부서명 변경을 사용자·컬렉션에 한 트랜잭션으로 동기화
        with self.db.get_connection() as conn:
            conn.execute(
                "UPDATE tb_departments "
                "SET department_name = ?, allowed_topics = ?, is_active = ?, updated_at = ? "
                "WHERE department_id = ?",
                (
                    new_name,
                    json.dumps(new_topics, ensure_ascii=False),
                    bool(new_active),
                    now,
                    department_id,
                ),
            )
            if new_name != existing["department_name"]:
                conn.execute(
                    "UPDATE tb_users SET department_name = ?, updated_at = ? "
                    "WHERE department_id = ?",
                    (new_name, now, department_id),
                )
                conn.execute(
                    "UPDATE tb_collections SET department_name = ?, updated_at = ? "
                    "WHERE department_id = ?",
                    (new_name, now, department_id),
                )
        return self.get_by_id(department_id)

    # ── 연쇄 처리 (규칙 1) — 부서 주제 축소 시 소속 사용자 blocked_topics 정리 ──

    def remove_topic_and_clean_users(
        self,
        department_id: str,
        topic_name: str,
        conn=None,
    ) -> None:
        """2026.06.29(sooyeon.choi) 추가
        부서 allowed_topics에서 주제 제거 + 소속 사용자 blocked_topics에서 동일 주제 자동 삭제.
        """
        if conn is None:
            with self.db.get_connection() as transaction:
                self.remove_topic_and_clean_users(
                    department_id,
                    topic_name,
                    conn=transaction,
                )
            return

        department = conn.execute(
            "SELECT allowed_topics FROM tb_departments WHERE department_id = ?",
            (department_id,),
        ).fetchone()
        if department is None:
            return

        allowed_topics = json.loads(department["allowed_topics"] or "[]")
        new_topics = [topic for topic in allowed_topics if topic != topic_name]
        now = now_kst_iso()

        conn.execute(
            "UPDATE tb_departments SET allowed_topics = ?, updated_at = ? "
            "WHERE department_id = ?",
            (json.dumps(new_topics, ensure_ascii=False), now, department_id),
        )
        users = conn.execute(
            "SELECT user_id, blocked_topics FROM tb_users WHERE department_id = ?",
            (department_id,),
        ).fetchall()
        for user in users:
            blocked = json.loads(user["blocked_topics"] or "[]")
            if topic_name in blocked:
                blocked.remove(topic_name)
                conn.execute(
                    "UPDATE tb_users SET blocked_topics = ?, updated_at = ? "
                    "WHERE user_id = ?",
                    (json.dumps(blocked, ensure_ascii=False), now, user["user_id"]),
                )

    # ── 대화 주제 목록 ────────────────────────────────────────────────────────

    def get_all_topics(self) -> List[str]:
        """시스템 전체 대화 주제 목록 (tb_collections.topic_name DISTINCT)."""
        rows = self.db.execute_query(
            "SELECT DISTINCT topic_name FROM tb_collections "
            "WHERE topic_name IS NOT NULL AND topic_name != '' "
            "ORDER BY topic_name"
        )
        return [r["topic_name"] for r in rows]

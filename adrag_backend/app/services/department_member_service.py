# 2026.11.20(woojin.jung) 추가 - 부서 운영관리자 역할: 관리자(/admin/users)와 운영관리자(/manager/members) 공용
"""
부서 사용자 조회·개인 주제 권한 서비스.

- 대상 계정은 일반 로그인 계정(role IN ('manager', 'user')). 관리자 계정은 다루지 않는다.
- 개인 권한 = 부서 허용 주제 중 개인 차단(blocked_topics). 차단 목록은 부서 허용 주제 안에서만 저장한다.
"""

import json
from typing import List, Optional

from app.repositories.database import get_database_manager
from app.utils.datetime import now_kst_iso

MEMBER_ROLE_SQL = "u.role IN ('manager', 'user')"
STATUS_FILTERS = {"active", "inactive", "blocked"}


def _json_list(value) -> List[str]:
    if not value:
        return []
    return json.loads(value) if isinstance(value, str) else list(value)


def get_member(user_id: str) -> Optional[dict]:
    """사용자 단건(부서 허용 주제 포함). 관리자 계정이거나 없으면 None."""
    rows = get_database_manager().execute_query(
        f"""
        SELECT u.user_id, u.user_name, u.role, u.is_active, u.blocked_topics,
               u.created_at, u.updated_at, u.department_id, u.department_name,
               d.department_name AS dept_name, d.allowed_topics
        FROM   tb_users u
        LEFT JOIN tb_departments d ON d.department_id = u.department_id
        WHERE  u.user_id = ? AND {MEMBER_ROLE_SQL}
        """,
        (user_id,),
    )
    if not rows:
        return None
    row = dict(rows[0])
    row["blocked_topics"] = _json_list(row["blocked_topics"])
    row["allowed_topics"] = _json_list(row["allowed_topics"])
    return row


def get_department_manager(department_id: str) -> Optional[dict]:
    """부서 운영관리자(부서당 1명). 없으면 None."""
    rows = get_database_manager().execute_query(
        "SELECT user_id, user_name, is_active FROM tb_users WHERE department_id = ? AND role = 'manager'",
        (department_id,),
    )
    return dict(rows[0]) if rows else None


def list_members(
    *,
    department_id: Optional[str] = None,
    search: Optional[str] = None,
    role: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    size: int = 20,
) -> dict:
    """사용자 목록. 운영관리자 → 활성 → 최근 생성 순."""
    conditions = [MEMBER_ROLE_SQL]
    params: list = []
    if search:
        conditions.append("(u.user_id ILIKE ? OR u.user_name ILIKE ?)")
        params += [f"%{search}%", f"%{search}%"]
    if department_id:
        conditions.append("u.department_id = ?")
        params.append(department_id)
    if role in ("manager", "user"):
        conditions.append("u.role = ?")
        params.append(role)
    if status == "active":
        conditions.append("u.is_active = TRUE")
    elif status == "inactive":
        conditions.append("u.is_active = FALSE")
    elif status == "blocked":
        conditions.append("jsonb_array_length(COALESCE(u.blocked_topics, '[]'::jsonb)) > 0")

    where = "WHERE " + " AND ".join(conditions)
    db = get_database_manager()
    total_rows = db.execute_query(f"SELECT COUNT(*) AS cnt FROM tb_users u {where}", tuple(params))
    total = total_rows[0]["cnt"] if total_rows else 0

    rows = db.execute_query(
        f"""
        SELECT u.user_id, u.user_name, u.role, u.is_active, u.blocked_topics,
               u.department_id, d.department_name AS dept_name, d.allowed_topics
        FROM   tb_users u
        LEFT JOIN tb_departments d ON d.department_id = u.department_id
        {where}
        ORDER BY (u.role = 'manager') DESC, u.is_active DESC, u.created_at DESC
        LIMIT ? OFFSET ?
        """,
        tuple(params) + (size, (page - 1) * size),
    )
    items = []
    for r in rows:
        allowed = _json_list(r["allowed_topics"])
        blocked = _json_list(r["blocked_topics"])
        items.append({
            "id": r["user_id"],
            "name": r["user_name"],
            "role": r["role"],
            "department": {"id": r["department_id"], "name": r["dept_name"]} if r["department_id"] else None,
            "effective_topics": [t for t in allowed if t not in blocked],
            "blocked_count": len(blocked),
            "is_active": bool(r["is_active"]),
        })
    return {"items": items, "total": total}


def member_permissions(member: dict) -> dict:
    return {"department_topics": member["allowed_topics"], "blocked_topics": member["blocked_topics"]}


def save_member_permissions(member: dict, blocked_topics: List[str]) -> dict:
    """개인 차단 주제 저장. 부서 허용 주제 밖의 항목이 있으면 ValueError(목록)."""
    dept_topics = member["allowed_topics"]
    invalid = [t for t in blocked_topics if t not in dept_topics]
    if invalid:
        raise ValueError(invalid)
    get_database_manager().execute_update(
        "UPDATE tb_users SET blocked_topics = ?, updated_at = ? WHERE user_id = ?",
        (json.dumps(blocked_topics, ensure_ascii=False), now_kst_iso(), member["user_id"]),
    )
    blocked_set = set(blocked_topics)
    return {
        "department_topics": dept_topics,
        "blocked_topics": blocked_topics,
        "effective_topics": [t for t in dept_topics if t not in blocked_set],
    }

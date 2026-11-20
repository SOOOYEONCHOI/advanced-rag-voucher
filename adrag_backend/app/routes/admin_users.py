# 2026.06.29(sooyeon.choi) 추가 - 사용자 권한 관리: 사용자 관리 API
"""
관리자 사용자 관리 API.

GET  /admin/users                            — 사용자 목록 (부서·주제 중심)
POST /admin/users                            — 사용자 추가 (POST /auth/register 대체)
GET  /admin/users/{user_id}                  — 사용자 단건 조회
PUT  /admin/users/{user_id}                  — 사용자 정보 수정
GET  /admin/users/{user_id}/permissions      — 개인 권한 조회
PUT  /admin/users/{user_id}/permissions      — 개인 권한 저장 (blocked_topics(개인 차단 주제) 관리)
"""

import json
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.repositories.database import get_database_manager
from app.repositories.department_repository import DepartmentRepository
from app.repositories.permissions_repository import PermissionsRepository
from app.services.ui_settings_service import UiType
from app.utils.datetime import now_kst_iso
from app.utils.password_policy import password_policy_error
from app.utils.security import get_current_admin, hash_password

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/users", tags=["Admin Users"])


# ── Pydantic 모델 ─────────────────────────────────────────────────────────────

class UserCreateRequest(BaseModel):
    login_id: str = Field(..., min_length=3, max_length=50)
    name: str = Field(..., min_length=1, max_length=100)
    department_id: str
    # 2026.11.13(woojin.jung) 수정 - 길이 규칙은 password_policy_error에서 검사
    password: str = Field(..., min_length=1)
    ui_type: Optional[UiType] = None


class UserUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    department_id: Optional[str] = None
    is_active: Optional[bool] = None


class PermissionsUpdateRequest(BaseModel):
    blocked_topics: List[str] = Field(default_factory=list)


# ── 헬퍼 ─────────────────────────────────────────────────────────────────────

def _get_db():
    return get_database_manager()


def _get_dept_repo() -> DepartmentRepository:
    return DepartmentRepository()


def _get_user_row(user_id: str, db):
    rows = db.execute_query(
        """
        SELECT u.user_id, u.user_name, u.is_active, u.blocked_topics,
               u.created_at, u.updated_at,
               u.department_id, u.department_name,
               d.department_name AS dept_name
        FROM   tb_users u
        LEFT JOIN tb_departments d ON d.department_id = u.department_id
        WHERE  u.user_id = ? AND u.role = 'user'
        """,
        (user_id,),
    )
    return rows[0] if rows else None


# ── 엔드포인트 ────────────────────────────────────────────────────────────────

@router.get("")
async def list_users(
    search: Optional[str] = Query(None),
    department_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    _: dict = Depends(get_current_admin),
):
    """사용자 목록 조회 (부서·주제 중심 응답)."""
    db = _get_db()

    conditions = ["u.role = 'user'"]
    params = []
    if search:
        conditions.append("(u.user_id ILIKE ? OR u.user_name ILIKE ?)")
        params += [f"%{search}%", f"%{search}%"]
    if department_id:
        conditions.append("u.department_id = ?")
        params.append(department_id)

    where = "WHERE " + " AND ".join(conditions)
    offset = (page - 1) * size

    total_rows = db.execute_query(
        f"SELECT COUNT(*) AS cnt FROM tb_users u {where}", tuple(params)
    )
    total = total_rows[0]["cnt"] if total_rows else 0

    rows = db.execute_query(
        f"""
        SELECT u.user_id, u.user_name, u.is_active, u.blocked_topics,
               u.department_id, u.department_name,
               d.department_name AS dept_name,
               d.allowed_topics
        FROM   tb_users u
        LEFT JOIN tb_departments d ON d.department_id = u.department_id
        {where}
        ORDER BY u.created_at DESC
        LIMIT ? OFFSET ?
        """,
        tuple(params) + (size, offset),
    )

    items = []
    for r in rows:
        allowed = json.loads(r["allowed_topics"] or "[]") if r["allowed_topics"] else []
        blocked = json.loads(r["blocked_topics"] or "[]")
        effective = [t for t in allowed if t not in blocked]
        items.append({
            "id": r["user_id"],
            "name": r["user_name"],
            "department": (
                {"id": r["department_id"], "name": r["dept_name"]}
                if r["department_id"] else None
            ),
            "effective_topics": effective,
            "blocked_count": len(blocked),
            "is_active": bool(r["is_active"]),
        })

    return {"items": items, "total": total}


@router.post("", status_code=201)
async def create_user(
    body: UserCreateRequest,
    _: dict = Depends(get_current_admin),
):
    """사용자 추가. POST /auth/register를 대체한다.

    department_id가 is_active=true인 부서인지 검증한다.
    """
    db = _get_db()

    # login_id 중복 확인
    existing = db.execute_query(
        "SELECT 1 FROM tb_users WHERE user_id = ?", (body.login_id,)
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail={"error": "DUPLICATE_LOGIN_ID", "message": "이미 사용 중인 아이디입니다."},
        )

    # 2026.11.13(woojin.jung) 추가 - 비밀번호 규칙 공통 적용
    policy_error = password_policy_error(body.password, user_id=body.login_id)
    if policy_error:
        raise HTTPException(status_code=400, detail={"error": "INVALID_PASSWORD", "message": policy_error})

    # 부서 활성 여부 검증
    dept_repo = _get_dept_repo()
    dept = dept_repo.get_by_id(body.department_id)
    if dept is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "DEPT_NOT_FOUND", "message": "존재하지 않는 부서입니다."},
        )
    if not dept["is_active"]:
        raise HTTPException(
            status_code=400,
            detail={"error": "DEPT_INACTIVE", "message": "비활성 부서에는 사용자를 배정할 수 없습니다."},
        )

    now = now_kst_iso()
    db.execute_update(
        """
        INSERT INTO tb_users
            (user_id, user_pwd, user_name, department_id, department_name, blocked_topics,
             role, ui_type, is_active, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, '[]', 'user', ?, TRUE, ?, ?)
        """,
        (body.login_id, hash_password(body.password), body.name,
         body.department_id, dept["department_name"], body.ui_type, now, now),
    )

    # 기본 보안 정책 생성
    PermissionsRepository().create_default_policy(body.login_id)

    logger.info("사용자 생성: %s → 부서 %s", body.login_id, body.department_id)
    return {
        "id": body.login_id,
        "name": body.name,
        "department_id": body.department_id,
        "is_active": True,
    }


@router.get("/{user_id}")
async def get_user(user_id: str, _: dict = Depends(get_current_admin)):
    """사용자 단건 조회."""
    db = _get_db()
    row = _get_user_row(user_id, db)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "USER_NOT_FOUND", "message": "존재하지 않는 사용자입니다."},
        )
    return {
        "id": row["user_id"],
        "name": row["user_name"],
        "department": (
            {"id": row["department_id"], "name": row["dept_name"]}
            if row["department_id"] else None
        ),
        "is_active": bool(row["is_active"]),
        "created_at": row["created_at"],
    }


@router.put("/{user_id}")
async def update_user(
    user_id: str,
    body: UserUpdateRequest,
    _: dict = Depends(get_current_admin),
):
    """사용자 정보 수정.

    department_id 변경 시 새 부서 주제에 없는 blocked_topics 자동 정리.
    """
    db = _get_db()
    row = _get_user_row(user_id, db)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "USER_NOT_FOUND", "message": "존재하지 않는 사용자입니다."},
        )

    dept_repo = _get_dept_repo()
    new_dept_id = body.department_id if body.department_id is not None else row["department_id"]
    new_dept_name = row["department_name"] or ""

    # 부서 변경 시 검증 및 blocked_topics 정리
    blocked = json.loads(row["blocked_topics"] or "[]")
    if body.department_id and body.department_id != row["department_id"]:
        new_dept = dept_repo.get_by_id(body.department_id)
        if new_dept is None:
            raise HTTPException(
                status_code=404,
                detail={"error": "DEPT_NOT_FOUND", "message": "존재하지 않는 부서입니다."},
            )
        if not new_dept["is_active"]:
            raise HTTPException(
                status_code=400,
                detail={"error": "DEPT_INACTIVE", "message": "비활성 부서에는 사용자를 배정할 수 없습니다."},
            )
        # 규칙 2: 새 부서 주제에 없는 blocked_topics 자동 삭제
        new_topics = set(new_dept["allowed_topics"])
        blocked = [t for t in blocked if t in new_topics]
        new_dept_name = new_dept["department_name"]
        logger.info("부서 변경으로 blocked_topics 정리: user=%s dept=%s",
                    user_id, body.department_id)

    new_name = body.name if body.name is not None else row["user_name"]
    new_active = body.is_active if body.is_active is not None else bool(row["is_active"])
    now = now_kst_iso()

    db.execute_update(
        """
        UPDATE tb_users
        SET user_name = ?, department_id = ?, department_name = ?,
            blocked_topics = ?, is_active = ?, updated_at = ?
        WHERE user_id = ?
        """,
        (new_name, new_dept_id, new_dept_name,
         json.dumps(blocked, ensure_ascii=False),
         bool(new_active), now, user_id),
    )
    logger.info("사용자 수정: %s", user_id)
    return {
        "id": user_id,
        "name": new_name,
        "department_id": new_dept_id,
        "is_active": new_active,
    }


@router.get("/{user_id}/permissions")
async def get_user_permissions(user_id: str, _: dict = Depends(get_current_admin)):
    """개인 권한 조회 (부서 주제 목록 + 차단 목록)."""
    db = _get_db()
    row = _get_user_row(user_id, db)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "USER_NOT_FOUND", "message": "존재하지 않는 사용자입니다."},
        )

    dept_topics: List[str] = []
    if row["department_id"]:
        dept = _get_dept_repo().get_by_id(row["department_id"])
        if dept:
            dept_topics = dept["allowed_topics"]

    blocked = json.loads(row["blocked_topics"] or "[]")
    return {
        "department_topics": dept_topics,
        "blocked_topics": blocked,
    }


@router.put("/{user_id}/permissions")
async def update_user_permissions(
    user_id: str,
    body: PermissionsUpdateRequest,
    _: dict = Depends(get_current_admin),
):
    """개인 권한 저장 (blocked_topics 관리).

    검증: blocked_topics ⊆ department.allowed_topics
    """
    db = _get_db()
    row = _get_user_row(user_id, db)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "USER_NOT_FOUND", "message": "존재하지 않는 사용자입니다."},
        )

    dept_topics: List[str] = []
    if row["department_id"]:
        dept = _get_dept_repo().get_by_id(row["department_id"])
        if dept:
            dept_topics = dept["allowed_topics"]

    invalid = [t for t in body.blocked_topics if t not in dept_topics]
    if invalid:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "BLOCKED_TOPICS_EXCEED_DEPT",
                "message": f"부서 주제에 없는 항목입니다: {invalid}",
            },
        )

    now = now_kst_iso()
    db.execute_update(
        "UPDATE tb_users SET blocked_topics = ?, updated_at = ? WHERE user_id = ?",
        (json.dumps(body.blocked_topics, ensure_ascii=False), now, user_id),
    )

    blocked_set = set(body.blocked_topics)
    effective = [t for t in dept_topics if t not in blocked_set]
    logger.info("사용자 권한 저장: user=%s blocked=%s", user_id, body.blocked_topics)
    return {
        "department_topics": dept_topics,
        "blocked_topics": body.blocked_topics,
        "effective_topics": effective,
    }

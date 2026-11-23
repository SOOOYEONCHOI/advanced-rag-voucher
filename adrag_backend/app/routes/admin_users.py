# 2026.06.29(sooyeon.choi) 추가 - 사용자 권한 관리: 사용자 관리 API
# 2026.11.20(woojin.jung) 수정 - 부서 운영관리자 역할(부서당 1명, 운영관리자 먼저 등록)
"""
관리자 사용자 관리 API.

GET  /admin/users                            — 사용자 목록 (부서·역할·상태 필터)
POST /admin/users                            — 사용자 추가 (POST /auth/register 대체)
GET  /admin/users/{user_id}                  — 사용자 단건 조회
PUT  /admin/users/{user_id}                  — 사용자 정보 수정
GET  /admin/users/{user_id}/permissions      — 개인 권한 조회
PUT  /admin/users/{user_id}/permissions      — 개인 권한 저장 (blocked_topics(개인 차단 주제) 관리)

등록 규칙(2026.11.20):
- 운영관리자는 부서당 1명. 일반 사용자는 운영관리자가 있는 부서에만 추가·이동할 수 있다.
- 운영관리자 계정은 이 API로 부서 이동·비활성화할 수 없다 → POST /admin/departments/{id}/manager(운영관리자 변경).
"""

import json
import logging
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError

from app.repositories.database import get_database_manager
from app.repositories.department_repository import DepartmentRepository
from app.repositories.permissions_repository import PermissionsRepository
from app.services import department_member_service as members
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
    # 2026.11.20(woojin.jung) 추가 - 부서 운영관리자 / 일반 사용자
    role: Literal["manager", "user"] = "user"


class UserUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    department_id: Optional[str] = None
    is_active: Optional[bool] = None


class PermissionsUpdateRequest(BaseModel):
    blocked_topics: List[str] = Field(default_factory=list)


# ── 헬퍼 ─────────────────────────────────────────────────────────────────────

def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"error": code, "message": message})


def _require_member(user_id: str) -> dict:
    member = members.get_member(user_id)
    if member is None:
        raise _error(404, "USER_NOT_FOUND", "존재하지 않는 사용자입니다.")
    return member


def _require_active_department(department_id: str) -> dict:
    dept = DepartmentRepository().get_by_id(department_id)
    if dept is None:
        raise _error(404, "DEPT_NOT_FOUND", "존재하지 않는 부서입니다.")
    if not dept["is_active"]:
        raise _error(400, "DEPT_INACTIVE", "비활성 부서에는 사용자를 배정할 수 없습니다.")
    return dept


def _require_department_manager(department_id: str) -> None:
    """일반 사용자 추가·이동 전제: 부서에 운영관리자가 있어야 한다."""
    if members.get_department_manager(department_id) is None:
        raise _error(400, "MANAGER_REQUIRED", "먼저 이 부서의 운영관리자를 등록해주세요.")


# ── 엔드포인트 ────────────────────────────────────────────────────────────────

@router.get("")
async def list_users(
    search: Optional[str] = Query(None),
    department_id: Optional[str] = Query(None),
    role: Optional[Literal["manager", "user"]] = Query(None),
    status: Optional[Literal["active", "inactive", "blocked"]] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    _: dict = Depends(get_current_admin),
):
    """사용자 목록 조회 (운영관리자 → 활성 → 최근 생성 순)."""
    return members.list_members(
        department_id=department_id, search=search, role=role, status=status, page=page, size=size,
    )


@router.post("", status_code=201)
async def create_user(
    body: UserCreateRequest,
    _: dict = Depends(get_current_admin),
):
    """사용자 추가. POST /auth/register를 대체한다.

    - 부서는 활성 부서여야 한다.
    - role=manager: 부서에 운영관리자가 없어야 한다(부서당 1명).
    - role=user: 부서에 운영관리자가 있어야 한다(운영관리자 먼저 등록).
    """
    db = get_database_manager()
    if db.execute_query("SELECT 1 FROM tb_users WHERE user_id = ?", (body.login_id,)):
        raise _error(409, "DUPLICATE_LOGIN_ID", "이미 사용 중인 아이디입니다.")

    # 2026.11.13(woojin.jung) 추가 - 비밀번호 규칙 공통 적용
    policy_error = password_policy_error(body.password, user_id=body.login_id)
    if policy_error:
        raise _error(400, "INVALID_PASSWORD", policy_error)

    dept = _require_active_department(body.department_id)
    if body.role == "manager":
        if members.get_department_manager(body.department_id) is not None:
            raise _error(409, "MANAGER_EXISTS", "이 부서에는 이미 운영관리자가 있습니다. 교체는 [운영관리자 변경]에서 합니다.")
    else:
        _require_department_manager(body.department_id)

    now = now_kst_iso()
    try:
        db.execute_update(
            """
            INSERT INTO tb_users
                (user_id, user_pwd, user_name, department_id, department_name, blocked_topics,
                 role, ui_type, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, '[]', ?, ?, TRUE, ?, ?)
            """,
            (body.login_id, hash_password(body.password), body.name,
             body.department_id, dept["department_name"], body.role, body.ui_type, now, now),
        )
    except IntegrityError as exc:
        # 동시에 같은 부서 운영관리자를 등록한 경우(uq_users_department_manager)
        raise _error(409, "MANAGER_EXISTS", "이 부서에는 이미 운영관리자가 있습니다.") from exc

    # 기본 보안 정책 생성
    PermissionsRepository().create_default_policy(body.login_id)

    logger.info("사용자 생성: %s → 부서 %s (role=%s)", body.login_id, body.department_id, body.role)
    return {
        "id": body.login_id,
        "name": body.name,
        "role": body.role,
        "department_id": body.department_id,
        "is_active": True,
    }


@router.get("/{user_id}")
async def get_user(user_id: str, _: dict = Depends(get_current_admin)):
    """사용자 단건 조회."""
    row = _require_member(user_id)
    return {
        "id": row["user_id"],
        "name": row["user_name"],
        "role": row["role"],
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

    - department_id 변경 시 새 부서 주제에 없는 blocked_topics 자동 정리.
    - 운영관리자는 부서 이동·비활성화 불가(운영관리자 변경으로 후임을 먼저 지정).
    - 일반 사용자는 운영관리자가 있는 부서로만 이동할 수 있다.
    """
    row = _require_member(user_id)
    is_manager = row["role"] == "manager"
    dept_changed = bool(body.department_id) and body.department_id != row["department_id"]

    if is_manager and (dept_changed or body.is_active is False):
        raise _error(
            400, "MANAGER_LOCKED",
            "운영관리자는 부서를 옮기거나 비활성화할 수 없습니다. 먼저 [운영관리자 변경]으로 후임을 지정하세요.",
        )

    new_dept_id = row["department_id"]
    new_dept_name = row["department_name"] or ""
    blocked = row["blocked_topics"]
    if dept_changed:
        new_dept = _require_active_department(body.department_id)
        _require_department_manager(body.department_id)
        # 규칙 2: 새 부서 주제에 없는 blocked_topics 자동 삭제
        new_topics = set(new_dept["allowed_topics"])
        blocked = [t for t in blocked if t in new_topics]
        new_dept_id = body.department_id
        new_dept_name = new_dept["department_name"]
        logger.info("부서 변경으로 blocked_topics 정리: user=%s dept=%s", user_id, body.department_id)

    new_name = body.name if body.name is not None else row["user_name"]
    new_active = body.is_active if body.is_active is not None else bool(row["is_active"])

    get_database_manager().execute_update(
        """
        UPDATE tb_users
        SET user_name = ?, department_id = ?, department_name = ?,
            blocked_topics = ?, is_active = ?, updated_at = ?
        WHERE user_id = ?
        """,
        (new_name, new_dept_id, new_dept_name,
         json.dumps(blocked, ensure_ascii=False),
         bool(new_active), now_kst_iso(), user_id),
    )
    logger.info("사용자 수정: %s", user_id)
    return {
        "id": user_id,
        "name": new_name,
        "role": row["role"],
        "department_id": new_dept_id,
        "is_active": new_active,
    }


@router.get("/{user_id}/permissions")
async def get_user_permissions(user_id: str, _: dict = Depends(get_current_admin)):
    """개인 권한 조회 (부서 주제 목록 + 차단 목록)."""
    return members.member_permissions(_require_member(user_id))


@router.put("/{user_id}/permissions")
async def update_user_permissions(
    user_id: str,
    body: PermissionsUpdateRequest,
    _: dict = Depends(get_current_admin),
):
    """개인 권한 저장 (blocked_topics 관리). 검증: blocked_topics ⊆ department.allowed_topics"""
    member = _require_member(user_id)
    # 2026.11.23(woojin.jung) 추가 - 운영관리자는 부서 주제를 관리하므로 개인 차단 대상이 아니다
    if member["role"] == "manager":
        raise _error(400, "MANAGER_NOT_RESTRICTABLE", "부서 운영관리자는 개인 주제 권한을 설정할 수 없습니다.")
    try:
        result = members.save_member_permissions(member, body.blocked_topics)
    except ValueError as exc:
        raise _error(400, "BLOCKED_TOPICS_EXCEED_DEPT", f"부서 주제에 없는 항목입니다: {exc.args[0]}") from exc
    logger.info("사용자 권한 저장(관리자): user=%s blocked=%s", user_id, body.blocked_topics)
    return result

# 2026.11.20(woojin.jung) 추가 - 부서 운영관리자: 부서 사용자 권한 API
"""
부서 운영관리자 전용 API. 대상은 항상 자기 부서(서버에서 tb_users.department_id 로 판단)이다.

GET /manager/department                         — 자기 부서 요약 (운영관리자·허용 주제·인원)
GET /manager/members                            — 자기 부서 일반 사용자 목록 (본인·운영관리자 제외)
GET /manager/members/{user_id}/permissions      — 개인 권한 조회
PUT /manager/members/{user_id}/permissions      — 개인 권한 저장 (부서 허용 주제 안에서 개인 차단)

사용자 추가·정보 수정·비활성화와 부서 허용 주제 변경은 관리자만 할 수 있다.
"""

import logging
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.repositories.department_repository import DepartmentRepository
from app.services import department_member_service as members
from app.utils.security import get_current_manager, require_department_active

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/manager", tags=["Department Manager"])


class PermissionsUpdateRequest(BaseModel):
    blocked_topics: List[str] = Field(default_factory=list)


def _require_department_member(user_id: str, manager: dict) -> dict:
    """같은 부서의 일반 사용자만 대상. 다른 부서·운영관리자·관리자 계정은 존재를 숨기고 404."""
    member = members.get_member(user_id)
    if member is None or member["role"] != "user" or member["department_id"] != manager["department_id"]:
        raise HTTPException(
            status_code=404,
            detail={"error": "USER_NOT_FOUND", "message": "부서 사용자를 찾을 수 없습니다."},
        )
    return member


@router.get("/department")
async def get_my_department(manager: dict = Depends(get_current_manager)):
    dept = DepartmentRepository().get_by_id(manager["department_id"])
    if dept is None:
        raise HTTPException(status_code=404, detail={"error": "DEPT_NOT_FOUND", "message": "부서를 찾을 수 없습니다."})
    # 2026.11.23(woojin.jung) 수정 - 인원은 화면 목록과 같은 기준(일반 사용자만). 운영관리자 = 본인 1명(활성·개인 차단 없음)을 뺀다
    return {
        "id": dept["department_id"],
        "name": dept["department_name"],
        "topic_names": dept["allowed_topics"],
        "user_count": max(dept["user_count"] - 1, 0),
        "active_user_count": max(dept["active_user_count"] - 1, 0),
        "blocked_user_count": dept["blocked_user_count"],
        "manager": dept["manager"],
        "is_active": dept["is_active"],
    }


@router.get("/members")
async def list_department_members(
    search: Optional[str] = Query(None),
    status: Optional[Literal["active", "inactive", "blocked"]] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    manager: dict = Depends(get_current_manager),
):
    return members.list_members(
        department_id=manager["department_id"], role="user", search=search, status=status, page=page, size=size,
    )


@router.get("/members/{user_id}/permissions")
async def get_member_permissions(user_id: str, manager: dict = Depends(get_current_manager)):
    return members.member_permissions(_require_department_member(user_id, manager))


@router.put("/members/{user_id}/permissions")
async def update_member_permissions(
    user_id: str,
    body: PermissionsUpdateRequest,
    manager: dict = Depends(get_current_manager),
):
    member = _require_department_member(user_id, manager)
    require_department_active(manager)  # 2026.11.23(woojin.jung) 추가 - 비활성 부서는 조회만
    try:
        result = members.save_member_permissions(member, body.blocked_topics)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "BLOCKED_TOPICS_EXCEED_DEPT", "message": f"부서 주제에 없는 항목입니다: {exc.args[0]}"},
        ) from exc
    logger.info("사용자 권한 저장(운영관리자): manager=%s user=%s blocked=%s",
                manager["user_id"], user_id, body.blocked_topics)
    return result

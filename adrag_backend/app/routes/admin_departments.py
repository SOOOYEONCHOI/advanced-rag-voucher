# 2026.06.29(sooyeon.choi) 추가 - 사용자 권한 관리: 부서 관리 API
"""
관리자 부서 관리 API.

GET  /admin/departments           — 부서 목록
POST /admin/departments           — 부서 추가
GET  /admin/departments/{id}      — 부서 단건 조회
PUT  /admin/departments/{id}      — 부서 수정 / 활성화 토글
GET  /admin/topics                — 시스템 전체 대화 주제 목록
GET  /admin/summary               — 상단 전체 요약 (사용자 수·활성 부서 수·미배정 사용자 수)
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.repositories.department_repository import DepartmentRepository
from app.repositories.database import get_database_manager
from app.core.config import get_settings
from app.utils.security import get_current_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["Admin Departments"])


# ── Pydantic 모델 ─────────────────────────────────────────────────────────────

class DepartmentCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class DepartmentUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    topic_names: Optional[List[str]] = None
    is_active: Optional[bool] = None


class DepartmentResponse(BaseModel):
    id: str
    name: str
    topic_names: List[str]
    user_count: int
    is_active: bool


class DepartmentDetailResponse(DepartmentResponse):
    created_at: str


# ── 헬퍼 ─────────────────────────────────────────────────────────────────────

def _to_response(dept: dict) -> dict:
    return {
        "id": dept["department_id"],
        "name": dept["department_name"],
        "topic_names": dept["allowed_topics"],
        "user_count": dept.get("user_count", 0),
        "is_active": dept["is_active"],
    }


def _get_repo() -> DepartmentRepository:
    return DepartmentRepository(get_settings().sqlite_db_path)


# ── 엔드포인트 ────────────────────────────────────────────────────────────────

@router.get("/summary")
async def admin_summary(_: dict = Depends(get_current_admin)):
    """전체 요약 수치 (총 사용자 수, 활성 부서 수, 미배정 사용자 수)."""
    db = get_database_manager(get_settings().sqlite_db_path)
    rows = db.execute_query(
        """
        SELECT
          (SELECT COUNT(*) FROM tb_users WHERE role = 'user') AS total_users,
          (SELECT COUNT(*) FROM tb_departments WHERE is_active = TRUE) AS active_departments,
          (SELECT COUNT(*) FROM tb_users WHERE role = 'user' AND department_id IS NULL) AS unassigned_users
        """
    )
    r = rows[0]
    return {
        "total_users": r["total_users"],
        "active_departments": r["active_departments"],
        "unassigned_users": r["unassigned_users"],
    }


@router.get("/departments", response_model=List[DepartmentResponse])
async def list_departments(
    search: Optional[str] = Query(None),
    _: dict = Depends(get_current_admin),
):
    """부서 목록 조회."""
    repo = _get_repo()
    depts = repo.get_all(search=search)
    return [_to_response(d) for d in depts]


@router.post("/departments", status_code=201, response_model=DepartmentDetailResponse)
async def create_department(
    body: DepartmentCreateRequest,
    _: dict = Depends(get_current_admin),
):
    """부서 추가."""
    repo = _get_repo()
    if repo.get_by_name(body.name):
        raise HTTPException(
            status_code=400,
            detail={"error": "DUPLICATE_DEPT_NAME", "message": "이미 사용 중인 부서명입니다."},
        )
    dept = repo.create(body.name)
    return {**_to_response(dept), "created_at": dept["created_at"]}


@router.get("/departments/{department_id}", response_model=DepartmentDetailResponse)
async def get_department(
    department_id: str,
    _: dict = Depends(get_current_admin),
):
    """부서 단건 조회."""
    repo = _get_repo()
    dept = repo.get_by_id(department_id)
    if dept is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "DEPT_NOT_FOUND", "message": "존재하지 않는 부서입니다."},
        )
    return {**_to_response(dept), "created_at": dept["created_at"]}


@router.put("/departments/{department_id}", response_model=DepartmentResponse)
async def update_department(
    department_id: str,
    body: DepartmentUpdateRequest,
    _: dict = Depends(get_current_admin),
):
    """부서 수정 (이름 / 허용 주제 / 활성화 토글).

    주제 축소 시 소속 사용자의 blocked_topics를 자동 정리한다.
    """
    repo = _get_repo()
    existing = repo.get_by_id(department_id)
    if existing is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "DEPT_NOT_FOUND", "message": "존재하지 않는 부서입니다."},
        )

    # 부서명 중복 검사 (자기 자신 제외)
    if body.name and body.name != existing["department_name"]:
        if repo.get_by_name(body.name):
            raise HTTPException(
                status_code=400,
                detail={"error": "DUPLICATE_DEPT_NAME", "message": "이미 사용 중인 부서명입니다."},
            )

    # 주제 축소 감지 → 제거된 주제에 대해 규칙 1 적용
    if body.topic_names is not None:
        removed_topics = set(existing["allowed_topics"]) - set(body.topic_names)
        for topic in removed_topics:
            repo.remove_topic_and_clean_users(department_id, topic)
            logger.info("부서 주제 제거 및 사용자 blocked_topics 정리: dept=%s topic=%s",
                        department_id, topic)

    dept = repo.update(
        department_id=department_id,
        department_name=body.name,
        allowed_topics=body.topic_names,
        is_active=body.is_active,
    )
    return _to_response(dept)


@router.get("/topics")
async def list_topics(_: dict = Depends(get_current_admin)):
    """시스템 전체 대화 주제 목록 (부서 수정 모달 자동완성용)."""
    repo = _get_repo()
    topics = repo.get_all_topics()
    return {"topics": topics}

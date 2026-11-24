# 2026.06.29(sooyeon.choi) 추가 - 사용자 권한 관리: 부서 관리 API
"""
관리자 부서 관리 API.

GET  /admin/departments           — 부서 목록
POST /admin/departments           — 부서 추가
GET  /admin/departments/{id}      — 부서 단건 조회
PUT  /admin/departments/{id}      — 부서 수정 / 활성화 토글
GET  /admin/topics                — 대화 주제 목록 (?department_id= 로 부서 한정)
GET  /admin/summary               — 전체 요약 (사용자 수·활성 부서 수·운영관리자 등록 부서 수)
POST /admin/departments/{id}/manager — 운영관리자 변경 (2026.11.20, 후임 지정 + 기존 처리 한 트랜잭션)
"""

import logging
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.repositories.department_repository import DepartmentRepository
from app.repositories.database import get_database_manager
from app.core.config import get_settings
from app.utils.datetime import now_kst_iso
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


class DepartmentManager(BaseModel):
    id: str
    name: str


class DepartmentResponse(BaseModel):
    id: str
    name: str
    topic_names: List[str]
    user_count: int
    is_active: bool
    # 2026.11.20(woojin.jung) 추가 - 부서 운영관리자(부서당 1명)·활성 인원·개인 차단 인원
    manager: Optional[DepartmentManager] = None
    active_user_count: int = 0
    blocked_user_count: int = 0


# 2026.11.20(woojin.jung) 추가 - 운영관리자 변경
class ManagerChangeRequest(BaseModel):
    new_manager_id: str = Field(..., min_length=1)
    # 기존 운영관리자 처리: 일반 사용자로 변경(demote) / 계정 비활성화(deactivate)
    previous_action: Literal["demote", "deactivate"] = "demote"


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
        "manager": dept.get("manager"),
        "active_user_count": dept.get("active_user_count", 0),
        "blocked_user_count": dept.get("blocked_user_count", 0),
    }


def _get_repo() -> DepartmentRepository:
    return DepartmentRepository()


# ── 엔드포인트 ────────────────────────────────────────────────────────────────

@router.get("/summary")
async def admin_summary(_: dict = Depends(get_current_admin)):
    """전체 요약 수치 (사용자 수, 활성 부서 수, 운영관리자 등록 부서 수, 미배정 사용자 수)."""
    db = get_database_manager()
    rows = db.execute_query(
        """
        SELECT
          (SELECT COUNT(*) FROM tb_users WHERE role IN ('manager', 'user')) AS total_users,
          (SELECT COUNT(*) FROM tb_users WHERE role IN ('manager', 'user') AND is_active) AS active_users,
          (SELECT COUNT(*) FROM tb_departments WHERE is_active = TRUE) AS active_departments,
          (SELECT COUNT(*) FROM tb_departments d WHERE d.is_active = TRUE AND EXISTS (
              SELECT 1 FROM tb_users m WHERE m.department_id = d.department_id AND m.role = 'manager'
          )) AS managed_departments,
          (SELECT COUNT(*) FROM tb_users WHERE role IN ('manager', 'user') AND department_id IS NULL) AS unassigned_users
        """
    )
    r = rows[0]
    return {
        "total_users": r["total_users"],
        "active_users": r["active_users"],
        "active_departments": r["active_departments"],
        "managed_departments": r["managed_departments"],
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


# 2026.11.20(woojin.jung) 추가 - 운영관리자 변경(부서당 1명이라 후임 지정과 기존 처리를 한 트랜잭션으로)
@router.post("/departments/{department_id}/manager", response_model=DepartmentResponse)
async def change_department_manager(
    department_id: str,
    body: ManagerChangeRequest,
    admin: dict = Depends(get_current_admin),
):
    """후임은 같은 부서의 활성 일반 사용자. 기존 운영관리자는 일반 사용자로 바꾸거나 비활성화한다.

    대화 주제·문서 수정 권한은 부서 기준이라 소유권 이전 작업은 없다.
    """
    repo = _get_repo()
    if repo.get_by_id(department_id) is None:
        raise HTTPException(status_code=404, detail={"error": "DEPT_NOT_FOUND", "message": "존재하지 않는 부서입니다."})

    db = get_database_manager()
    with db.get_connection() as conn:
        # 같은 부서 계정 행을 잠가 동시 변경을 막는다
        rows = conn.execute(
            "SELECT user_id, role, is_active FROM tb_users "
            "WHERE department_id = ? AND role IN ('manager', 'user') FOR UPDATE",
            (department_id,),
        ).fetchall()
        current = next((r for r in rows if r["role"] == "manager"), None)
        successor = next((r for r in rows if r["user_id"] == body.new_manager_id), None)
        if current is None:
            raise HTTPException(
                status_code=400,
                detail={"error": "MANAGER_NOT_FOUND", "message": "운영관리자가 없는 부서입니다. 사용자 추가에서 운영관리자를 등록하세요."},
            )
        if successor is None or successor["role"] != "user" or not successor["is_active"]:
            raise HTTPException(
                status_code=400,
                detail={"error": "INVALID_SUCCESSOR", "message": "후임은 같은 부서의 활성 일반 사용자여야 합니다."},
            )
        now = now_kst_iso()
        conn.execute(
            "UPDATE tb_users SET role = 'user', is_active = ?, updated_at = ? WHERE user_id = ?",
            (body.previous_action != "deactivate", now, current["user_id"]),
        )
        conn.execute(
            # 2026.11.23(woojin.jung) 수정 - 운영관리자는 개인 차단 대상이 아니므로 승격 시 차단 목록을 비운다
            "UPDATE tb_users SET role = 'manager', blocked_topics = '[]', updated_at = ? WHERE user_id = ?",
            (now, body.new_manager_id),
        )
    logger.info(
        "운영관리자 변경: dept=%s %s → %s (기존 처리=%s, actor=%s)",
        department_id, current["user_id"], body.new_manager_id, body.previous_action, admin.get("admin_id"),
    )
    return _to_response(repo.get_by_id(department_id))


@router.get("/topics")
async def list_topics(
    department_id: Optional[str] = Query(None),
    _: dict = Depends(get_current_admin),
):
    """대화 주제 목록 (부서 수정 모달용). department_id 를 주면 그 부서 대화 주제만(2026.11.23 woojin.jung)."""
    repo = _get_repo()
    topics = repo.get_all_topics(department_id)
    return {"topics": topics}

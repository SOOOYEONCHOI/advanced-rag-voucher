# 2026.06.16(sooyeon.choi) 수정
#   tb_user_permissions(JSON) 제거 → PermissionsRepository(tb_user_collection_permissions + tb_user_security_policies)
# 2026.06.29(sooyeon.choi) 수정 - 사용자 권한 관리
#   GET /admin/users, PUT /admin/users/{id}/permissions → admin_users.py로 이전
#   GET /admin/users/logs → GET /admin/logs 로 경로 변경 (user_id path param 충돌 방지)
"""사용자 권한 및 접속 로그 관리 API (레거시 호환용 - 로그 조회만 유지)."""

from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.core.config import get_settings
from app.repositories.metadata_repository import MetadataRepository
from app.utils.datetime import format_kst_datetime
from app.utils.security import get_current_admin

router = APIRouter(prefix="/admin", tags=["Admin Logs"])


@router.get("/logs")
async def get_query_logs(
    user_id: Optional[str] = Query(default=None),
    session_id: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    current_admin: dict = Depends(get_current_admin),
):
    """접속/질의 로그를 조회한다."""
    repo = MetadataRepository(get_settings().sqlite_db_path)
    logs = []
    for log in repo.get_query_history(user_id=user_id, session_id=session_id, limit=limit):
        logs.append({
            **log,
            "created_at": format_kst_datetime(log.get("created_at")),
        })
    return {"logs": logs}

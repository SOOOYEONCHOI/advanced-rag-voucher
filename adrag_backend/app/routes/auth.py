"""일반 사용자 인증 API."""

import logging
import time
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.repositories.collection_repository import CollectionRepository
from app.repositories.database import get_database_manager
from app.models.data_models import UserPermission
from app.repositories.login_history_repository import LoginHistoryRepository
from app.repositories.metadata_repository import MetadataRepository
# 2026.09.03(sooyeon.choi) 추가 - 로그인/로그아웃 감사 로그 공통 헬퍼
from app.utils.audit import client_ip, log_auth_event
from app.utils.security import (
    create_access_token,
    create_user_access_token,
    get_current_admin,
    get_current_principal,
    get_current_user,
    get_user_role,
    hash_password,
    verify_password,
)
from app.utils.password_policy import password_policy_error
from app.utils.datetime import now_kst_iso

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["User Auth"])


class UserRegisterRequest(BaseModel):
    user_id: str = Field(..., min_length=3, max_length=50)
    # 2026.11.13(woojin.jung) 수정 - 길이 규칙은 password_policy_error에서 검사
    password: str = Field(..., min_length=1)
    user_name: Optional[str] = Field(None, max_length=100)


class UserLoginRequest(BaseModel):

    user_id: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1)


class UserAuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    user_name: str
    role: str = "user"
    is_admin: bool = False
    is_superadmin: bool = False
    admin_id: Optional[str] = None
    admin_name: Optional[str] = None
    ui_type: Optional[str] = None
    # 2026.11.20(woojin.jung) 추가 - 부서 운영관리자 화면 분기용
    department_id: Optional[str] = None
    department_name: Optional[str] = None
    # 2026.11.23(woojin.jung) 추가 - 비활성 부서 안내(운영관리자 읽기 전용, 일반 사용자 대화 주제 없음)
    department_active: bool = True


def _get_user(user_id: str) -> Optional[dict]:
    settings = get_settings()
    db = get_database_manager()
    rows = db.execute_query(
        """
        SELECT user_id, user_pwd, user_name, is_active, ui_type, role, department_id, department_name
        FROM tb_users
        WHERE user_id = ? AND role IN ('user', 'manager')
        """,
        (user_id,),
    )
    if not rows:
        return None
    row = rows[0]
    return {
        "user_id": row["user_id"],
        "user_pwd": row["user_pwd"],
        "user_name": row["user_name"],
        "is_active": bool(row["is_active"]),
        "ui_type": row["ui_type"],
        # 2026.11.20(woojin.jung) 추가 - 부서 운영관리자 역할·부서
        "role": row["role"],
        "department_id": row["department_id"],
        "department_name": row["department_name"] or "",
    }


# 2026.06.16(sooyeon.choi) 수정 - is_superadmin 컬럼 제거
# 2026.06.30(sooyeon.choi) 수정 - 동기화된 tb_users.department_name 사용
def _get_account(user_id: str) -> Optional[dict]:
    settings = get_settings()
    db = get_database_manager()
    rows = db.execute_query(
        """
        SELECT u.user_id, u.user_pwd, u.user_name, u.role, u.is_active, u.ui_type,
               u.department_name AS department, u.department_id
        FROM   tb_users u
        WHERE  u.user_id = ?
        """,
        (user_id,),
    )
    if not rows:
        return None
    row = rows[0]
    return {
        "user_id": row["user_id"],
        "user_pwd": row["user_pwd"],
        "user_name": row["user_name"],
        "role": row["role"],
        "is_active": bool(row["is_active"]),
        "ui_type": row["ui_type"],
        "department": row["department"],
        "department_id": row["department_id"],
    }


def _record_login_history(
    *,
    attempted_user_id: str,
    account: Optional[dict],
    success: bool,
    failure_reason: Optional[str],
    request: Request,
) -> None:
    # 2026.09.03(sooyeon.choi) 추가 - 모든 로그인 시도에 감사 로그(ID·IP·호출 API) 기록.
    #   DB 이력 저장이 실패해도 로그는 남도록 저장보다 먼저 호출한다.
    log_auth_event(
        logger,
        "login",
        request=request,
        user_id=account["user_id"] if account else attempted_user_id,
        role=account["role"] if account else None,
        result="success" if success else "failure",
        reason=failure_reason,
    )

    settings = get_settings()
    LoginHistoryRepository().record(
        attempted_user_id=attempted_user_id,
        user_id=account["user_id"] if account else None,
        user_role=account["role"] if account else None,
        # 2026.06.30(sooyeon.choi) 추가 - 로그인 당시 부서명을 이력 스냅샷으로 저장
        department_snapshot=account.get("department") if account else None,
        success=success,
        failure_reason=failure_reason,
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )


def _create_default_permission(user_id: str) -> None:
    settings = get_settings()
    meta_repo = MetadataRepository()
    permission = UserPermission(
        user_id=user_id,
        accessible_collections=[],   # 관리자가 명시적으로 권한을 부여해야 접근 가능
        max_security_level="public",
        allowed_document_types=[],
        metadata_filters={},
    )
    meta_repo.store_user_permission(permission)


@router.post("/register", response_model=UserAuthResponse, status_code=201)
async def register_user(body: UserRegisterRequest, _: dict = Depends(get_current_admin)):
    """일반 사용자 계정을 생성하고 즉시 로그인 토큰을 발급한다."""
    settings = get_settings()
    db = get_database_manager()
    existing = _get_user(body.user_id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 존재하는 사용자 ID입니다.",
        )
    # 2026.11.13(woojin.jung) 추가 - 비밀번호 규칙 공통 적용
    policy_error = password_policy_error(body.password, user_id=body.user_id)
    if policy_error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=policy_error)

    user_name = body.user_name or body.user_id
    now = now_kst_iso()
    db.execute_update(
        """
        INSERT INTO tb_users (user_id, user_pwd, user_name, role, is_active, created_at, updated_at)
        VALUES (?, ?, ?, 'user', TRUE, ?, ?)
        """,
        (body.user_id, hash_password(body.password), user_name, now, now),
    )
    _create_default_permission(body.user_id)

    token = create_user_access_token(body.user_id, user_name)
    logger.info("사용자 계정 생성: %s", body.user_id)
    return UserAuthResponse(
        access_token=token,
        user_id=body.user_id,
        user_name=user_name,
    )


@router.post("/login", response_model=UserAuthResponse)
async def login_user(body: UserLoginRequest, request: Request):
    # 2026.06.17(sooyeon.choi) - admin/user 로그인을 /auth/login으로 통합 처리
    """사용자/관리자 통합 로그인."""
    account = _get_account(body.user_id)
    if not account:
        _record_login_history(
            attempted_user_id=body.user_id,
            account=None,
            success=False,
            failure_reason="unknown_user",
            request=request,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="아이디 또는 비밀번호가 올바르지 않습니다.",
        )

    if not verify_password(body.password, account["user_pwd"]):
        _record_login_history(
            attempted_user_id=body.user_id,
            account=account,
            success=False,
            failure_reason="invalid_password",
            request=request,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="아이디 또는 비밀번호가 올바르지 않습니다.",
        )

    # 2026.06.16(sooyeon.choi) 수정 - is_superadmin 제거; admin 토큰은 시드 계정으로만 생성
    if account["role"] == "admin":
        token = create_access_token(
            admin_id=account["user_id"],
            is_superadmin=False,
        )
        _record_login_history(
            attempted_user_id=body.user_id,
            account=account,
            success=True,
            failure_reason=None,
            request=request,
        )
        return UserAuthResponse(
            access_token=token,
            user_id=account["user_id"],
            user_name=account["user_name"],
            role="admin",
            is_admin=True,
            is_superadmin=False,
            admin_id=account["user_id"],
            admin_name=account["user_name"],
        )

    if not account["is_active"]:
        _record_login_history(
            attempted_user_id=body.user_id,
            account=account,
            success=False,
            failure_reason="inactive_user",
            request=request,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="비활성화된 사용자입니다. 관리자에게 문의하세요.",  # 2026.11.23(woojin.jung) 수정 - 문의처 안내 추가
        )

    # 2026.04.10(sooyeon.choi) 추가 - 권한 행이 없는 기존 사용자 보정 (회원가입 전 생성된 계정 대응)
    settings = get_settings()
    meta_repo = MetadataRepository()
    if not meta_repo.get_user_permissions(account["user_id"]):
        _create_default_permission(account["user_id"])
        logger.info("로그인 시 기본 권한 자동 생성: %s", account["user_id"])

    token = create_user_access_token(account["user_id"], account["user_name"])
    _record_login_history(
        attempted_user_id=body.user_id,
        account=account,
        success=True,
        failure_reason=None,
        request=request,
    )
    return UserAuthResponse(
        access_token=token,
        user_id=account["user_id"],
        user_name=account["user_name"],
        role=account["role"],
        ui_type=account["ui_type"],
        department_id=account["department_id"],
        department_name=account["department"] or "",
        department_active=bool((get_user_role(account["user_id"]) or {}).get("department_active")),
    )


@router.post("/logout", status_code=200)
async def logout_user(
    request: Request,
    current_user: dict = Depends(get_current_principal),
):
    """일반 사용자 로그아웃 — 클라이언트 토큰 파기 안내."""
    # 2026.09.03(sooyeon.choi) 수정 - 로그아웃 로그에 IP·호출 API·역할 추가
    log_auth_event(
        logger,
        "logout",
        request=request,
        user_id=current_user.get("user_id"),
        role=current_user.get("role"),
    )
    return {"message": "로그아웃 되었습니다."}


# 2026.11.13(woojin.jung) 추가 - 일반 사용자 본인 비밀번호 변경(관리자 계정은 scripts/create_admin.py 사용)
class PasswordChangeRequest(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=1)


# 현재 비밀번호 확인 실패 제한(탈취된 토큰으로 현재 비밀번호를 대입하는 것 방지).
# 프로세스 메모리에 보관한다(uvicorn workers=1 기준, 재시작하면 초기화).
_PW_FAIL_LIMIT = 5
_PW_FAIL_WINDOW_SEC = 600
_pw_failures: dict[str, list[float]] = {}


def _password_error(code: str, field: str, message: str, status_code: int = status.HTTP_400_BAD_REQUEST):
    return HTTPException(status_code=status_code, detail={"error": code, "field": field, "message": message})


@router.post("/password")
async def change_password(
    body: PasswordChangeRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """현재 비밀번호를 확인한 뒤 새 비밀번호로 변경한다. 변경 전에 발급된 토큰은 모두 무효가 된다."""
    user_id = current_user["user_id"]
    now = time.monotonic()
    failures = [t for t in _pw_failures.get(user_id, []) if now - t < _PW_FAIL_WINDOW_SEC]
    if len(failures) >= _PW_FAIL_LIMIT:
        log_auth_event(logger, "password_change", request=request, user_id=user_id, role="user",
                       result="failure", reason="too_many_attempts")
        raise _password_error("TOO_MANY_ATTEMPTS", "current_password",
                              "비밀번호 확인에 여러 번 실패했습니다. 10분 후 다시 시도해 주세요.",
                              status.HTTP_429_TOO_MANY_REQUESTS)

    account = _get_user(user_id)
    if not account or not account["is_active"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="비활성화된 사용자입니다. 관리자에게 문의하세요.")

    if not verify_password(body.current_password, account["user_pwd"]):
        _pw_failures[user_id] = failures + [now]
        log_auth_event(logger, "password_change", request=request, user_id=user_id, role="user",
                       result="failure", reason="invalid_password")
        raise _password_error("INVALID_CURRENT_PASSWORD", "current_password", "현재 비밀번호가 올바르지 않습니다.")
    _pw_failures.pop(user_id, None)

    policy_error = password_policy_error(body.new_password, user_id=user_id, current_password=body.current_password)
    if policy_error:
        raise _password_error("INVALID_NEW_PASSWORD", "new_password", policy_error)

    changed_at = now_kst_iso()
    get_database_manager().execute_update(
        "UPDATE tb_users SET user_pwd = ?, pwd_changed_at = ?, updated_at = ? WHERE user_id = ?",
        (hash_password(body.new_password), changed_at, changed_at, user_id),
    )
    log_auth_event(logger, "password_change", request=request, user_id=user_id, role="user")
    return {"message": "비밀번호가 변경되었습니다."}


@router.get("/me")
async def get_me(current_user: dict = Depends(get_current_principal)):
    """현재 로그인한 사용자 정보를 반환한다."""
    if current_user["token_type"] == "admin_access":
        return {
            "user_id": current_user["user_id"],
            "user_name": "admin",
            "token_type": current_user["token_type"],
            "role": "admin",
            "is_admin": True,
            "is_superadmin": current_user.get("is_superadmin", False),
        }

    user = _get_user(current_user["user_id"])
    if not user:
        raise HTTPException(status_code=404, detail="사용자 정보를 찾을 수 없습니다.")

    settings = get_settings()
    permissions = MetadataRepository().get_user_permissions(
        current_user["user_id"]
    )
    return {
        "user_id": user["user_id"],
        "user_name": user["user_name"],
        "token_type": current_user["token_type"],
        "role": user["role"],
        "is_admin": False,
        "is_superadmin": False,
        "ui_type": user["ui_type"],
        "department_id": user["department_id"],
        "department_name": user["department_name"],
        "department_active": current_user.get("department_active", False),  # 2026.11.23(woojin.jung) 추가
        "accessible_collections": permissions.accessible_collections if permissions else [],
    }


class UpdateMyCollectionsRequest(BaseModel):
    accessible_collections: List[str] = Field(default_factory=list)


@router.put("/me/collections", status_code=200)
async def update_my_collections(
    body: UpdateMyCollectionsRequest,
    current_user: dict = Depends(get_current_principal),
):
    """현재 사용자의 접근 가능 컬렉션 목록을 업데이트한다."""
    if current_user.get("is_admin"):
        raise HTTPException(
            status_code=400,
            detail="관리자는 '사용자 권한 관리' 페이지에서 권한을 수정하세요.",
        )

    settings = get_settings()

    # 요청 컬렉션(qdrant_name)이 시스템에 실제로 존재하는지 검증
    # 2026.06.16(sooyeon.choi) 수정 - collection_name → display_name
    all_system = {
        c.qdrant_name
        for c in CollectionRepository().get_all()
    }
    invalid = [c for c in body.accessible_collections if c not in all_system]
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"존재하지 않는 컬렉션이 포함되어 있습니다: {invalid}",
        )

    meta_repo = MetadataRepository()
    permissions = meta_repo.get_user_permissions(current_user["user_id"])

    if permissions:
        permissions.accessible_collections = body.accessible_collections
    else:
        permissions = UserPermission(
            user_id=current_user["user_id"],
            accessible_collections=body.accessible_collections,
            max_security_level="public",
            allowed_document_types=[],
            metadata_filters={},
        )

    meta_repo.store_user_permission(permissions)
    logger.info("사용자 컬렉션 자가 설정: %s → %s", current_user["user_id"], body.accessible_collections)
    return {"accessible_collections": body.accessible_collections}

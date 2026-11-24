"""
관리자 인증 보안 유틸리티.

비밀번호 해시/검증(bcrypt)과 JWT 토큰 생성/검증을 제공한다.
"""

from datetime import datetime, timezone, timedelta
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import get_settings
from app.repositories.database import get_database_manager

# bcrypt 컨텍스트
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Bearer 토큰 파서
_bearer = HTTPBearer(auto_error=False)

# 2026.07.16(sooyeon.choi) 추가 - 보안등급 계층 단일 정의
#   기존: build_metadata_filter.py와 routes/ingest.py에 동일 dict가 중복 정의되어
#   등급 추가/변경 시 한쪽 누락 위험 → 공통 모듈로 통합
# 보안등급 계층: 상위 등급은 하위 등급도 조회 가능
SECURITY_HIERARCHY: dict[str, list[str]] = {
    "public":       ["public"],
    "internal":     ["public", "internal"],
    "confidential": ["public", "internal", "confidential"],
    "restricted":   ["public", "internal", "confidential", "restricted"],
}


# 2026.11.09(sooyeon.choi) 추가 - 문서 열람 범위 계산 공통 함수
#   주의: 검색 필터(graphs/nodes/build_metadata_filter.py)는 accessible_collections가 비면 "전체 허용"으로
#   규칙이 달라 이 함수를 쓰지 않는다(빈 목록 = 열람 불가인 아래 규칙과 다름).
def document_scope(permissions) -> tuple[set[str], set[str]]:
    """사용자 권한(UserPermission) → (접근 가능한 대화 주제 qdrant_name 집합, 열람 가능한 보안 등급 집합).

    권한 행이 없으면 둘 다 빈 집합(아무 문서도 열람 불가). 관리자 여부는 호출하는 쪽에서 먼저 판단한다.
    """
    if not permissions:
        return set(), set()
    accessible = set(permissions.accessible_collections or [])
    allowed = set(SECURITY_HIERARCHY.get(permissions.max_security_level or "public", ["public"]))
    return accessible, allowed


def in_document_scope(
    scope: tuple[set[str], set[str]],
    collection_name: Optional[str],
    security_level: Optional[str],
) -> bool:
    """문서(대화 주제·보안 등급)가 열람 범위 안이면 True. 보안 등급 기본값 처리는 호출하는 쪽 규칙을 따른다."""
    accessible, allowed = scope
    return collection_name in accessible and security_level in allowed


# ── 비밀번호 ─────────────────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    """비밀번호를 bcrypt 해시로 변환한다."""
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """입력 비밀번호와 bcrypt 해시를 비교한다."""
    return _pwd_context.verify(plain, hashed)


# ── JWT ──────────────────────────────────────────────────────────────────────

def _create_token_payload(
    subject: str,
    token_type: str,
    extra: Optional[dict] = None,
) -> dict:
    """공통 JWT payload를 생성한다."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "type": token_type,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expiration_minutes),
    }
    if extra:
        payload.update(extra)
    return payload


def create_access_token(admin_id: str, is_superadmin: bool = False) -> str:
    """관리자용 JWT access 토큰을 생성한다."""
    settings = get_settings()
    payload = _create_token_payload(
        subject=admin_id,
        token_type="admin_access",
        extra={"is_superadmin": is_superadmin},
    )
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_user_access_token(user_id: str, user_name: str = "") -> str:
    """일반 사용자용 JWT access 토큰을 생성한다."""
    settings = get_settings()
    payload = _create_token_payload(
        subject=user_id,
        token_type="user_access",
        extra={"user_name": user_name},
    )
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    """JWT 토큰을 검증하고 payload를 반환한다. 실패 시 예외를 발생시킨다."""
    settings = get_settings()
    return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])


# 2026.11.13(woojin.jung) 추가 - 비밀번호 변경 전에 발급된 일반 사용자 토큰 무효화
def _is_revoked_user_token(payload: dict) -> bool:
    """일반 사용자 토큰이 마지막 비밀번호 변경(tb_users.pwd_changed_at)보다 먼저 발급됐으면 True."""
    if payload.get("type") != "user_access":
        return False
    # iat와 같은 초 단위 epoch로 비교한다(timestamptz는 DB 계층에서 문자열로 바뀌므로 SQL에서 변환).
    rows = get_database_manager().execute_query(
        "SELECT floor(extract(epoch FROM pwd_changed_at))::bigint AS changed_epoch FROM tb_users WHERE user_id = ?",
        (payload.get("sub"),),
    )
    changed_epoch = rows[0]["changed_epoch"] if rows else None
    # 변경과 같은 초에 다시 로그인한 토큰은 유효하게 둔다.
    return changed_epoch is not None and payload.get("iat", 0) < changed_epoch


# ── FastAPI Depends ───────────────────────────────────────────────────────────

# 2026.11.09(sooyeon.choi) 추가 - Depends 3종 공통 토큰 확인
def _decode_bearer_payload(credentials: Optional[HTTPAuthorizationCredentials]) -> dict:
    """Bearer 토큰을 복호화한다. 토큰이 없거나 복호화에 실패하면 401(WWW-Authenticate: Bearer)."""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="인증 토큰이 필요합니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_access_token(credentials.credentials)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않거나 만료된 토큰입니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if _is_revoked_user_token(payload):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="비밀번호가 변경되었습니다. 다시 로그인해 주세요.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload


# admin 토큰만 허용하는 Depends 함수
async def get_current_admin(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    """JWT Bearer 토큰에서 관리자 정보를 추출하는 FastAPI Depends 함수.

    인증 실패 시 401을 반환한다.
    """
    payload = _decode_bearer_payload(credentials)

    if payload.get("type") != "admin_access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="관리자 토큰이 아닙니다.",
        )

    return {
        "admin_id": payload.get("sub"),
        "is_superadmin": payload.get("is_superadmin", False),
    }


# admin + user 토큰 모두 허용하는 Depends 함수 (is_admin/is_superadmin 플래그 포함)
async def get_current_principal(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    """JWT Bearer 토큰에서 현재 주체(admin/user)를 추출한다."""
    payload = _decode_bearer_payload(credentials)

    token_type = payload.get("type")
    if token_type not in {"admin_access", "user_access"}:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="지원하지 않는 토큰입니다.",
        )

    is_admin = token_type == "admin_access"
    # 2026.11.20(woojin.jung) 추가 - 역할·부서는 토큰이 아니라 매 요청 DB에서 읽는다(운영관리자 교체 즉시 반영)
    account = None if is_admin else get_user_role(payload.get("sub"))
    return {
        "user_id": payload.get("sub"),
        "user_name": payload.get("user_name", ""),
        "token_type": token_type,
        "is_admin": is_admin,
        "is_superadmin": payload.get("is_superadmin", False),
        "role": ROLE_ADMIN if is_admin else (account["role"] if account else ROLE_USER),
        "department_id": account["department_id"] if account else None,
        # 2026.11.23(woojin.jung) 추가 - 비활성 부서의 운영관리자는 읽기 전용
        "department_active": bool(account and account["department_active"]),
    }


# ── 역할 (2026.11.20(woojin.jung) 추가 - 부서 운영관리자) ─────────────────────────
#   관리자: 계정·부서 관리 / 부서 운영관리자: 자기 부서 문서·대화 주제·FAQ·사용자 주제 권한 / 일반 사용자: 챗봇
#   문서·대화 주제 수정 권한은 업로더·생성자가 아니라 "부서" 기준이다(can_manage_department 한 곳에서 판단).

ROLE_ADMIN = "admin"
ROLE_MANAGER = "manager"
ROLE_USER = "user"
# 관리자가 아닌 일반 로그인 계정(user_access 토큰)의 역할
MEMBER_ROLES = (ROLE_MANAGER, ROLE_USER)


def get_user_role(user_id: Optional[str]) -> Optional[dict]:
    """tb_users 의 역할·부서·활성 여부(+ 소속 부서 활성 여부). 계정이 없으면 None."""
    if not user_id:
        return None
    rows = get_database_manager().execute_query(
        "SELECT u.role, u.department_id, u.is_active, d.is_active AS department_active "
        "FROM tb_users u LEFT JOIN tb_departments d ON d.department_id = u.department_id "
        "WHERE u.user_id = ?",
        (user_id,),
    )
    if not rows:
        return None
    return {
        "role": rows[0]["role"],
        "department_id": rows[0]["department_id"],
        "is_active": bool(rows[0]["is_active"]),
        "department_active": bool(rows[0]["department_active"]),
    }


def is_manager(principal: dict) -> bool:
    return principal.get("role") == ROLE_MANAGER and bool(principal.get("department_id"))


# 2026.11.23(woojin.jung) 추가 - 비활성 부서: 운영관리자는 조회만(쓰기는 can_manage_department 에서 일괄 차단)
DEPARTMENT_INACTIVE_MESSAGE = "소속 부서가 비활성화되어 조회만 할 수 있습니다. 관리자에게 문의하세요."


def in_department_scope(principal: dict, department_id: Optional[str]) -> bool:
    """조회 범위: 관리자 전체, 부서 운영관리자는 자기 부서 것(부서 활성 여부와 무관)."""
    if principal.get("is_admin"):
        return True
    return is_manager(principal) and department_id is not None and principal["department_id"] == department_id


def can_manage_department(principal: dict, department_id: Optional[str]) -> bool:
    """문서·대화 주제·FAQ 수정 권한: 관리자 전체, 부서 운영관리자는 활성 상태인 자기 부서 것만."""
    if principal.get("is_admin"):
        return True
    return in_department_scope(principal, department_id) and principal.get("department_active", False)


def require_department_manager(principal: dict, department_id: Optional[str]) -> None:
    if not can_manage_department(principal, department_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=DEPARTMENT_INACTIVE_MESSAGE
            if in_department_scope(principal, department_id)
            else "소속 부서의 운영관리자만 수정할 수 있습니다.",
        )


def require_department_scope(principal: dict, department_id: Optional[str]) -> None:
    """조회용: 비활성 부서의 운영관리자도 통과."""
    if not in_department_scope(principal, department_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="소속 부서의 운영관리자만 볼 수 있습니다.",
        )


def require_department_active(principal: dict) -> None:
    """운영관리자 쓰기 작업 공통: 소속 부서가 비활성이면 403. 관리자는 통과."""
    if not principal.get("is_admin") and not principal.get("department_active", False):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=DEPARTMENT_INACTIVE_MESSAGE)


def require_content_manager(principal: dict) -> None:
    """문서 업로드·대화 주제 생성 등 관리 기능 진입: 관리자 또는 (활성 부서의) 부서 운영관리자."""
    if not (principal.get("is_admin") or is_manager(principal)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="부서 운영관리자만 사용할 수 있습니다.",
        )
    require_department_active(principal)


async def get_current_manager(principal: dict = Depends(get_current_principal)) -> dict:
    """부서 운영관리자 토큰만 허용(역할은 DB 기준). 비활성 계정은 403."""
    if not is_manager(principal):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="부서 운영관리자만 사용할 수 있습니다.")
    account = get_user_role(principal["user_id"])
    if not account or not account["is_active"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="비활성화된 사용자입니다. 관리자에게 문의하세요.")
    return principal


# 2026.06.19(sooyeon.choi) 추가 - 일반 사용자 토큰만 허용하는 Depends 함수
async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    """JWT Bearer 토큰에서 일반 사용자 정보를 추출한다."""
    payload = _decode_bearer_payload(credentials)

    if payload.get("type") != "user_access" or not payload.get("sub"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="일반 사용자 토큰이 아닙니다.",
        )

    return {
        "user_id": payload["sub"],
        "user_name": payload.get("user_name", ""),
        "token_type": "user_access",
    }


def decode_optional_token(token: str) -> Optional[dict]:
    """옵션 토큰을 복호화하고 실패 시 None을 반환한다."""
    try:
        payload = decode_access_token(token)
    except Exception:
        return None
    # 2026.11.13(woojin.jung) 추가 - 비밀번호 변경 전 토큰은 비로그인으로 취급
    return None if _is_revoked_user_token(payload) else payload

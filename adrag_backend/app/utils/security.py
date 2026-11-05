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

# bcrypt 컨텍스트
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Bearer 토큰 파서
_bearer = HTTPBearer(auto_error=False)

# 2026.07.16(sooyeon.choi) 추가 - 보안등급 계층 단일 정의 (B10)
#   기존: build_metadata_filter.py와 routes/ingest.py에 동일 dict가 중복 정의되어
#   등급 추가/변경 시 한쪽 누락 위험 → 공통 모듈로 통합
# 보안등급 계층: 상위 등급은 하위 등급도 조회 가능
SECURITY_HIERARCHY: dict[str, list[str]] = {
    "public":       ["public"],
    "internal":     ["public", "internal"],
    "confidential": ["public", "internal", "confidential"],
    "restricted":   ["public", "internal", "confidential", "restricted"],
}


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


# ── FastAPI Depends ───────────────────────────────────────────────────────────

# admin 토큰만 허용하는 Depends 함수
async def get_current_admin(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    """JWT Bearer 토큰에서 관리자 정보를 추출하는 FastAPI Depends 함수.

    인증 실패 시 401을 반환한다.
    """
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

    token_type = payload.get("type")
    if token_type not in {"admin_access", "user_access"}:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="지원하지 않는 토큰입니다.",
        )

    return {
        "user_id": payload.get("sub"),
        "user_name": payload.get("user_name", ""),
        "token_type": token_type,
        "is_admin": token_type == "admin_access",
        "is_superadmin": payload.get("is_superadmin", False),
    }


# 2026.06.19(sooyeon.choi) 추가 - 일반 사용자 토큰만 허용하는 Depends 함수
async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    """JWT Bearer 토큰에서 일반 사용자 정보를 추출한다."""
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
        return decode_access_token(token)
    except Exception:
        return None

"""
API 키 대칭 암호화 유틸리티.

JWT_SECRET_KEY에서 파생한 키로 Fernet 대칭 암호화를 수행한다.
평문 API 키를 DB에 직접 저장하지 않기 위해 사용한다.
"""

import base64
import hashlib

from cryptography.fernet import Fernet

from app.core.config import get_settings


def _get_fernet() -> Fernet:
    """JWT_SECRET_KEY에서 Fernet 키를 파생하여 반환한다."""
    secret = get_settings().jwt_secret_key.encode()
    # SHA-256(32 bytes) → Base64URL → Fernet 키 형식
    key = base64.urlsafe_b64encode(hashlib.sha256(secret).digest())
    return Fernet(key)


def encrypt_api_key(plain: str) -> str:
    """평문 API 키를 암호화하여 문자열로 반환한다."""
    return _get_fernet().encrypt(plain.encode()).decode()


def decrypt_api_key(encrypted: str) -> str:
    """암호화된 API 키를 복호화하여 평문으로 반환한다."""
    return _get_fernet().decrypt(encrypted.encode()).decode()
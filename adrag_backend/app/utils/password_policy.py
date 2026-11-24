"""일반 사용자 비밀번호 규칙.

2026.11.13(woojin.jung) 추가 - 비밀번호 변경·사용자 생성 공통 규칙
프론트 체크리스트(adrag_frontend/src/constants/passwordPolicy.js)와 같은 규칙을 유지한다.
관리자 계정은 별도 규칙(app/services/admin_bootstrap.py MIN_PASSWORD_LENGTH)을 따른다.
"""

import re
from typing import Optional

MIN_PASSWORD_LENGTH = 8
# bcrypt는 72바이트까지만 처리한다(초과하면 해시 단계에서 오류).
MAX_PASSWORD_BYTES = 72


def password_policy_error(
    password: str,
    *,
    user_id: Optional[str] = None,
    current_password: Optional[str] = None,
) -> Optional[str]:
    """규칙을 어기면 사용자에게 보여줄 메시지를, 통과하면 None을 반환한다."""
    if len(password) < MIN_PASSWORD_LENGTH or not (re.search(r"[A-Za-z]", password) and re.search(r"\d", password)):
        return f"비밀번호는 영문과 숫자를 포함해 {MIN_PASSWORD_LENGTH}자 이상이어야 합니다."
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        return "비밀번호가 너무 깁니다."
    if user_id and password == user_id:
        return "아이디와 같은 비밀번호는 사용할 수 없습니다."
    if current_password is not None and password == current_password:
        return "현재 비밀번호와 다른 비밀번호를 입력해 주세요."
    return None

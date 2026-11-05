"""인증 이벤트(로그인/로그아웃) 감사 로그 헬퍼."""

# 2026.09.03(sooyeon.choi) 추가 - 로그인/로그아웃 감사 로그를 ID·IP·호출 API 포함해 공통 처리

import logging
from typing import Optional

from fastapi import Request

UNKNOWN = "-"


def client_ip(request: Optional[Request]) -> Optional[str]:
    """프록시를 거친 경우 X-Forwarded-For의 첫 IP를, 아니면 소켓 주소를 반환한다."""
    if request is None:
        return None
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    return request.client.host if request.client else None


def _quoted(value: Optional[str], limit: int = 200) -> str:
    """공백이 포함될 수 있는 값을 key=value 파싱이 깨지지 않도록 인용한다."""
    if not value:
        return UNKNOWN
    text = value.replace('"', "'")
    if len(text) > limit:
        text = text[:limit] + "..."
    return f'"{text}"'


def log_auth_event(
    logger: logging.Logger,
    event: str,
    *,
    request: Optional[Request],
    user_id: Optional[str],
    role: Optional[str] = None,
    result: str = "success",
    reason: Optional[str] = None,
) -> None:
    """
    `[AUTH][<event>]` 형식의 감사 로그를 남긴다.

    Args:
        event: login / logout 등 이벤트 이름
        request: 호출 API·IP·User-Agent 추출용 요청 객체
        user_id: 로그인 시도/성공한 계정 ID
        role: user / admin
        result: success 이면 INFO, 그 외에는 WARNING으로 기록
        reason: 실패 사유

    비밀번호 등 자격 증명은 절대 기록하지 않는다.
    """
    api = f"{request.method} {request.url.path}" if request is not None else None
    user_agent = request.headers.get("user-agent") if request is not None else None

    logger.log(
        logging.INFO if result == "success" else logging.WARNING,
        "[AUTH][%s] result=%s user_id=%s role=%s ip=%s api=%s ua=%s reason=%s",
        event,
        result,
        user_id or UNKNOWN,
        role or UNKNOWN,
        client_ip(request) or UNKNOWN,
        _quoted(api),
        _quoted(user_agent),
        _quoted(reason),
        # 호출한 라우트의 파일:라인이 로그 포맷에 남도록 한다
        stacklevel=2,
    )

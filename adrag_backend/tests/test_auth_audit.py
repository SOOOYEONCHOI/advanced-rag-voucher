import logging

from starlette.requests import Request

from app.utils.audit import log_auth_event


def _request(path: str, forwarded_for: str = "203.0.113.10") -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": [
                (b"x-forwarded-for", forwarded_for.encode()),
                (b"user-agent", b"pytest-agent"),
            ],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
            "scheme": "http",
            "query_string": b"",
        }
    )


def test_login_success_audit_log_contains_request_context(caplog):
    logger = logging.getLogger("test.auth.audit")

    with caplog.at_level(logging.INFO, logger=logger.name):
        log_auth_event(
            logger,
            "login",
            request=_request("/api/auth/login"),
            user_id="user01",
            role="user",
        )

    message = caplog.records[-1].getMessage()
    assert caplog.records[-1].levelno == logging.INFO
    assert "[AUTH][login] result=success" in message
    assert "user_id=user01 role=user ip=203.0.113.10" in message
    assert 'api="POST /api/auth/login"' in message
    assert 'ua="pytest-agent" reason=-' in message


def test_login_failure_audit_log_is_warning_with_reason(caplog):
    logger = logging.getLogger("test.auth.audit")

    with caplog.at_level(logging.WARNING, logger=logger.name):
        log_auth_event(
            logger,
            "login",
            request=_request("/api/auth/login"),
            user_id="user01",
            role="user",
            result="failure",
            reason="invalid_password",
        )

    message = caplog.records[-1].getMessage()
    assert caplog.records[-1].levelno == logging.WARNING
    assert "[AUTH][login] result=failure" in message
    assert 'reason="invalid_password"' in message


def test_logout_audit_log_does_not_contain_credentials(caplog):
    logger = logging.getLogger("test.auth.audit")

    with caplog.at_level(logging.INFO, logger=logger.name):
        log_auth_event(
            logger,
            "logout",
            request=_request("/api/auth/logout"),
            user_id="admin01",
            role="admin",
        )

    message = caplog.records[-1].getMessage()
    assert "[AUTH][logout] result=success" in message
    assert 'api="POST /api/auth/logout"' in message
    assert "password" not in message
    assert "token" not in message

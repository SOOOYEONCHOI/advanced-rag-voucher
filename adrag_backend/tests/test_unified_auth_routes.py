from fastapi import FastAPI
from fastapi.testclient import TestClient

import importlib.util

from app.routes import auth
from app.utils.security import get_current_principal


def _route_paths(router) -> set[tuple[str, str]]:
    return {
        (method, route.path)
        for route in router.routes
        for method in route.methods
    }


# 2026.10.20 수정 - D-19: 인증 없는 최초 관리자 생성 API(POST /api/admin/init) 제거 → 라우터 모듈 자체가 없어야 한다
def test_admin_init_api_is_removed():
    assert importlib.util.find_spec("app.routes.admin_auth") is None


def test_admin_uses_unified_auth_login_me_and_logout(monkeypatch):
    account = {
        "user_id": "admin01",
        "user_pwd": "hashed-password",
        "user_name": "관리자",
        "role": "admin",
        "is_active": True,
        "department": None,
    }
    history = []
    monkeypatch.setattr(auth, "_get_account", lambda user_id: account)
    monkeypatch.setattr(auth, "verify_password", lambda password, hashed: True)
    monkeypatch.setattr(auth, "create_access_token", lambda **kwargs: "admin-token")
    monkeypatch.setattr(auth, "_record_login_history", lambda **kwargs: history.append(kwargs))

    app = FastAPI()
    app.include_router(auth.router, prefix="/api")
    app.dependency_overrides[get_current_principal] = lambda: {
        "user_id": "admin01",
        "token_type": "admin_access",
        "is_admin": True,
        "is_superadmin": False,
    }
    client = TestClient(app)

    login = client.post(
        "/api/auth/login",
        json={"user_id": "admin01", "password": "password"},
    )
    assert login.status_code == 200
    assert login.json() == {
        "access_token": "admin-token",
        "token_type": "bearer",
        "user_id": "admin01",
        "user_name": "관리자",
        "role": "admin",
        "is_admin": True,
        "is_superadmin": False,
        "admin_id": "admin01",
        "admin_name": "관리자",
    }
    assert history[-1]["success"] is True

    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["role"] == "admin"
    assert me.json()["is_admin"] is True

    logout = client.post("/api/auth/logout")
    assert logout.status_code == 200
    assert logout.json() == {"message": "로그아웃 되었습니다."}

"""리팩토링 전후 동작 고정 테스트 (2026.11.09(sooyeon.choi) 추가).

리팩토링 대상 중 기존 테스트가 없던 부분의 현재 동작을 고정한다. 리팩토링 전 코드에서 먼저 통과시킨 뒤 수정했다.
- app/utils/security: get_current_admin·get_current_principal·get_current_user의 401 응답(문구·헤더)과 반환값
- app/routes/query: rag_query·rag_query_stream의 대화 주제 권한(403)·저장 API 키 조회·서비스 호출 인자
- app/services/rag_service: query()·query_stream()의 대화 이력 저장 형식과 저장 조건
외부 서버·DB 없음(저장소는 가짜 객체).
"""
from __future__ import annotations

import asyncio
import importlib
import json
import sys
from types import SimpleNamespace

import pytest

# test_answer_images와 같은 이유: 수집 단계에서 다른 테스트가 app.core.config를 stub으로 바꿔 둘 수 있다.
_config_stub = sys.modules.get("app.core.config")
if _config_stub is not None and not hasattr(_config_stub, "Settings"):
    sys.modules.pop("app.core.config")
    importlib.import_module("app.core.config")
try:
    from fastapi import HTTPException
    from fastapi.security import HTTPAuthorizationCredentials

    from app.utils import security
finally:
    if _config_stub is not None and not hasattr(_config_stub, "Settings"):
        sys.modules["app.core.config"] = _config_stub


# ── 인증 Depends ─────────────────────────────────────────────────────────────

def _cred(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def _error(coro) -> HTTPException:
    with pytest.raises(HTTPException) as info:
        asyncio.run(coro)
    return info.value


@pytest.fixture
def tokens(monkeypatch):
    settings = SimpleNamespace(jwt_secret_key="test-secret", jwt_algorithm="HS256", jwt_expiration_minutes=30)
    monkeypatch.setattr(security, "get_settings", lambda: settings)
    return {
        "admin": security.create_access_token("admin1", is_superadmin=True),
        "user": security.create_user_access_token("user1", "사용자"),
        "other": security.jwt.encode({"sub": "x", "type": "refresh"}, "test-secret", algorithm="HS256"),
        "user_no_sub": security.jwt.encode({"type": "user_access"}, "test-secret", algorithm="HS256"),
    }


@pytest.mark.parametrize("dependency", [
    security.get_current_admin, security.get_current_principal, security.get_current_user,
])
def test_missing_and_invalid_token_are_401_with_bearer_header(dependency, tokens):
    missing = _error(dependency(credentials=None))
    assert (missing.status_code, missing.detail) == (401, "인증 토큰이 필요합니다.")
    assert missing.headers == {"WWW-Authenticate": "Bearer"}
    invalid = _error(dependency(credentials=_cred("not-a-jwt")))
    assert (invalid.status_code, invalid.detail) == (401, "유효하지 않거나 만료된 토큰입니다.")
    assert invalid.headers == {"WWW-Authenticate": "Bearer"}


def test_admin_dependency(tokens):
    assert asyncio.run(security.get_current_admin(credentials=_cred(tokens["admin"]))) == {
        "admin_id": "admin1", "is_superadmin": True,
    }
    for name in ("user", "other"):
        err = _error(security.get_current_admin(credentials=_cred(tokens[name])))
        assert (err.status_code, err.detail, err.headers) == (401, "관리자 토큰이 아닙니다.", None)


def test_principal_dependency(tokens):
    assert asyncio.run(security.get_current_principal(credentials=_cred(tokens["admin"]))) == {
        "user_id": "admin1", "user_name": "", "token_type": "admin_access", "is_admin": True, "is_superadmin": True,
    }
    assert asyncio.run(security.get_current_principal(credentials=_cred(tokens["user"]))) == {
        "user_id": "user1", "user_name": "사용자", "token_type": "user_access", "is_admin": False,
        "is_superadmin": False,
    }
    err = _error(security.get_current_principal(credentials=_cred(tokens["other"])))
    assert (err.status_code, err.detail, err.headers) == (401, "지원하지 않는 토큰입니다.", None)


def test_user_dependency(tokens):
    assert asyncio.run(security.get_current_user(credentials=_cred(tokens["user"]))) == {
        "user_id": "user1", "user_name": "사용자", "token_type": "user_access",
    }
    for name in ("admin", "other", "user_no_sub"):
        err = _error(security.get_current_user(credentials=_cred(tokens[name])))
        assert (err.status_code, err.detail, err.headers) == (401, "일반 사용자 토큰이 아닙니다.", None)


# ── 질의 API(권한·저장 API 키) ────────────────────────────────────────────────

@pytest.fixture
def query_routes(monkeypatch):
    pytest.importorskip("langgraph")
    from app.routes import query

    calls = {}

    class FakeService:
        async def query(self, **kwargs):
            calls["query"] = kwargs
            return SimpleNamespace()

        def query_stream(self, **kwargs):
            calls["stream"] = kwargs

            async def gen():
                yield "data: {}\n\n"

            return gen()

    saved = {"key": SimpleNamespace(api_key_enc="enc"), "decrypt": lambda enc: "sk-saved"}
    monkeypatch.setattr(query, "_rag_service", FakeService())
    monkeypatch.setattr(query, "asdict", lambda response: {"ok": True})
    monkeypatch.setattr(query, "get_settings", lambda: SimpleNamespace())
    monkeypatch.setattr(query, "_get_accessible_collections", lambda user_id: ["allowed"])
    monkeypatch.setattr(query, "CollectionRepository", lambda *_: SimpleNamespace(
        get_by_qdrant_name=lambda name: SimpleNamespace(collection_id=7) if name != "unregistered" else None))
    monkeypatch.setattr(query, "UserLlmSettingsRepository", lambda: SimpleNamespace(
        get=lambda user_id, collection_id: saved["key"]))
    monkeypatch.setattr(query, "decrypt_api_key", lambda enc: saved["decrypt"](enc))
    return query, calls, saved


def _call(query_module, endpoint: str, body, is_admin=False, monkeypatch=None):
    principal = {"user_id": "u1", "token_type": "admin_access" if is_admin else "user_access", "is_admin": is_admin}
    monkeypatch.setattr(query_module, "_extract_principal", lambda request: principal)
    handler = query_module.rag_query if endpoint == "query" else query_module.rag_query_stream
    return asyncio.run(handler(SimpleNamespace(headers={}), body))


@pytest.mark.parametrize("endpoint", ["query", "stream"])
def test_non_admin_cannot_query_unassigned_collection(endpoint, query_routes, monkeypatch):
    query, calls, _ = query_routes
    body = query.QueryRequestBody(query="질문", collection_name="secret")
    with pytest.raises(HTTPException) as info:
        _call(query, endpoint, body, monkeypatch=monkeypatch)
    assert (info.value.status_code, info.value.detail) == (403, "'secret' 컬렉션에 접근 권한이 없습니다.")
    assert calls == {}
    # 관리자는 대화 주제 권한 검사를 하지 않는다
    _call(query, endpoint, body, is_admin=True, monkeypatch=monkeypatch)
    assert calls[endpoint]["collection_name"] == "secret"


@pytest.mark.parametrize("endpoint", ["query", "stream"])
def test_service_arguments_and_saved_api_key(endpoint, query_routes, monkeypatch):
    query, calls, saved = query_routes
    body = query.QueryRequestBody(query="질문", collection_name="allowed", llm_provider="openai", llm_model="m",
                                  top_k=3, collection_filters=["allowed"], enable_metadata_filtering=False)
    result = _call(query, endpoint, body, monkeypatch=monkeypatch)
    assert calls[endpoint] == {
        "query": "질문", "user_id": "u1", "collection_filters": ["allowed"], "collection_name": "allowed",
        "top_k": 3, "llm_provider": "openai", "llm_model": "m", "openai_api_key": "sk-saved",
        "enable_metadata_filtering": False,
    }
    if endpoint == "query":
        assert result == {"ok": True}
    else:
        assert result.media_type == "text/event-stream"
        assert result.headers["cache-control"] == "no-cache"
        assert result.headers["connection"] == "keep-alive"

    # 요청에 키가 있으면 저장 키를 보지 않는다
    calls.clear()
    _call(query, endpoint, body.model_copy(update={"openai_api_key": "sk-body"}), monkeypatch=monkeypatch)
    assert calls[endpoint]["openai_api_key"] == "sk-body"
    # openai가 아니거나 대화 주제가 없거나 미등록이면 None
    for update in ({"llm_provider": "local"}, {"collection_name": None}):
        calls.clear()
        _call(query, endpoint, body.model_copy(update=update), monkeypatch=monkeypatch)
        assert calls[endpoint]["openai_api_key"] is None
    calls.clear()
    _call(query, endpoint, body.model_copy(update={"collection_name": "unregistered"}), is_admin=True,
          monkeypatch=monkeypatch)
    assert calls[endpoint]["openai_api_key"] is None
    # 저장 키가 없거나 복호화 실패면 None(오류 아님)
    saved["key"] = SimpleNamespace(api_key_enc=None)
    calls.clear()
    _call(query, endpoint, body, monkeypatch=monkeypatch)
    assert calls[endpoint]["openai_api_key"] is None
    saved["key"] = SimpleNamespace(api_key_enc="enc")
    saved["decrypt"] = lambda enc: (_ for _ in ()).throw(ValueError("bad"))
    calls.clear()
    _call(query, endpoint, body, monkeypatch=monkeypatch)
    assert calls[endpoint]["openai_api_key"] is None


def test_query_service_error_is_500_with_user_message(query_routes, monkeypatch):
    query, _, _ = query_routes

    class Failing:
        async def query(self, **kwargs):
            raise RuntimeError("boom")

    monkeypatch.setattr(query, "_rag_service", Failing())
    with pytest.raises(HTTPException) as info:
        _call(query, "query", query.QueryRequestBody(query="질문"), monkeypatch=monkeypatch)
    assert info.value.status_code == 500
    assert info.value.detail == query.get_user_message(query.UserMessageType.TEMPORARY_ERROR)


# ── 대화 이력 저장 ───────────────────────────────────────────────────────────

class _HistoryRepository:
    def __init__(self, existing=None, previous=None):
        self.existing = existing
        self.previous = previous
        self.stored = []

    def get_session_by_collection(self, user_id, name):
        return self.existing

    def get_query_context(self, session_id):
        return self.previous

    def store_query_context(self, context):
        self.stored.append(context)


@pytest.fixture
def rag_module(monkeypatch):
    pytest.importorskip("langgraph")
    import app.services.rag_service as rag_service_module

    class FakeRecorder:
        def __init__(self, repository):
            pass

        async def record(self, record, state, **kwargs):
            return 11

    settings = SimpleNamespace(max_query_top_k=20, context_top_k=5,
                               max_citation_results=5, relevance_threshold=0.5)
    monkeypatch.setattr(rag_service_module, "get_settings", lambda: settings)
    monkeypatch.setattr(rag_service_module, "QueryRecorder", FakeRecorder)
    monkeypatch.setattr(rag_service_module, "CollectionRepository",
                        lambda *_: SimpleNamespace(get_by_id=lambda _id: SimpleNamespace(display_name="주제")))
    return rag_service_module


def _service(rag_module, output):
    class FakeGraph:
        async def ainvoke(self, state):
            return {**state, **output}

        async def astream_events(self, state, version):
            yield {"event": "on_chain_end", "name": "LangGraph", "parent_ids": [], "data": {"output": {
                **state, **output}}}

    service = object.__new__(rag_module.RAGService)
    service._current_graph = lambda: FakeGraph()
    return service


_OUTPUT = {
    "generated_answer": "답변",
    "citations": [{"citation_id": 1, "document_id": "d1", "original_filename": "a.xlsx", "chunk_text": "t"}],
    "answer_images": [{"resource_id": "r1"}, {"resource_id": "r2"}],
    "answer_images_total": 5,
}


def test_query_history_appends_turn_and_keeps_last_20(rag_module, monkeypatch):
    previous = SimpleNamespace(user_id="u1", conversation_history=[{"role": "user", "content": str(i)} for i in range(25)])
    repo = _HistoryRepository(existing=SimpleNamespace(session_id="s1", collection_id=3), previous=previous)
    monkeypatch.setattr(rag_module, "MetadataRepository", lambda *_: repo)
    response = asyncio.run(_service(rag_module, _OUTPUT).query(query="질문", user_id="u1", collection_name="c"))
    assert response.log_id == 11
    (context,) = repo.stored
    assert (context.session_id, context.user_id, context.collection_id) == ("s1", "u1", 3)
    assert (context.expires_at - context.updated_at).days == 14
    history = context.conversation_history
    assert len(history) == 20
    assert history[-2] == {"role": "user", "content": "질문"}
    assert history[-1]["role"] == "assistant" and history[-1]["content"] == "답변"
    assert history[-1]["citations"][0]["document_id"] == "d1"
    assert history[-1]["images"] == _OUTPUT["answer_images"]
    assert history[-1]["images_total"] == 5


def test_query_history_ignores_other_users_context_and_saves_unresolved_collection(rag_module, monkeypatch):
    # query()는 대화 주제 이름만 있으면(collection_id를 못 찾아도) 이력을 저장한다 — query_stream과 다른 기존 규칙
    repo = _HistoryRepository(existing=None, previous=SimpleNamespace(user_id="other", conversation_history=[{"x": 1}]))
    monkeypatch.setattr(rag_module, "MetadataRepository", lambda *_: repo)
    monkeypatch.setattr(rag_module, "_resolve_collection_id", lambda *_: None)
    asyncio.run(_service(rag_module, {**_OUTPUT, "answer_images_total": None}).query(
        query="질문", user_id="u1", collection_name="c"))
    (context,) = repo.stored
    assert context.collection_id is None
    assert [h["role"] for h in context.conversation_history] == ["user", "assistant"]
    assert context.conversation_history[-1]["images_total"] == 2  # 전체 장수가 없으면 붙은 사진 수


def test_query_history_not_saved_without_collection_and_failure_is_ignored(rag_module, monkeypatch):
    repo = _HistoryRepository()
    monkeypatch.setattr(rag_module, "MetadataRepository", lambda *_: repo)
    asyncio.run(_service(rag_module, _OUTPUT).query(query="질문", user_id="u1"))
    assert repo.stored == []

    class Broken(_HistoryRepository):
        def store_query_context(self, context):
            raise RuntimeError("db down")

    monkeypatch.setattr(rag_module, "MetadataRepository",
                        lambda *_: Broken(existing=SimpleNamespace(session_id="s1", collection_id=3)))
    response = asyncio.run(_service(rag_module, _OUTPUT).query(query="질문", user_id="u1", collection_name="c"))
    assert response.answer == "답변"


def test_stream_history_skips_unresolved_collection(rag_module, monkeypatch):
    # query_stream은 collection_id가 있을 때만 저장한다(기존 규칙)
    repo = _HistoryRepository(existing=None)
    monkeypatch.setattr(rag_module, "MetadataRepository", lambda *_: repo)
    monkeypatch.setattr(rag_module, "_resolve_collection_id", lambda *_: None)

    async def collect(service):
        return [json.loads(e.removeprefix("data: ").strip())
                async for e in service.query_stream(query="질문", user_id="u1", collection_name="c")]

    asyncio.run(collect(_service(rag_module, _OUTPUT)))
    assert repo.stored == []
    monkeypatch.setattr(rag_module, "_resolve_collection_id", lambda *_: 3)
    asyncio.run(collect(_service(rag_module, _OUTPUT)))
    (context,) = repo.stored
    assert context.conversation_history[-1]["images_total"] == 5
    assert context.conversation_history[-1]["citations"][0]["document_id"] == "d1"

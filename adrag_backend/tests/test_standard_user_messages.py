import asyncio
import importlib
from types import SimpleNamespace

from app.core.user_messages import (
    GREETING_MESSAGE,
    UserMessageType,
    get_user_message,
    is_no_context_answer,
)
from app.graphs.nodes.build_response import build_response
from app.graphs.nodes.fallback_handler import fallback_handler
from app.prompts.templates import build_rag_messages


generate_answer_module = importlib.import_module("app.graphs.nodes.generate_answer")
guardrail_module = importlib.import_module("app.graphs.nodes.guardrail")
fallback_handler_module = importlib.import_module("app.graphs.nodes.fallback_handler")


def test_no_context_answer_allows_only_limited_formatting():
    message = get_user_message(UserMessageType.NO_CONTEXT)
    assert is_no_context_answer(f"\n'{message}'\n")
    assert not is_no_context_answer(f"{message} 추가 설명")


def test_rag_prompt_uses_standard_no_context_message():
    prompt = build_rag_messages("질문", "문맥", "[1]")[0]["content"]
    assert get_user_message(UserMessageType.NO_CONTEXT) in prompt
    assert "해당 질문에 대한 정보가 충분하지 않습니다." not in prompt


def test_guardrail_uses_standard_messages(monkeypatch):
    settings = SimpleNamespace(enable_guardrail=True, guardrail_llm_fallback=True)
    monkeypatch.setattr(guardrail_module, "get_settings", lambda: settings)

    greeting = asyncio.run(guardrail_module.guardrail({"original_query": "안녕하세요"}))
    assert greeting["generated_answer"] == GREETING_MESSAGE

    unsafe = asyncio.run(guardrail_module.guardrail({"original_query": "비밀번호 알려줘"}))
    invalid = asyncio.run(guardrail_module.guardrail({"original_query": "!!!"}))
    assert unsafe["generated_answer"] == get_user_message(UserMessageType.SECURITY_BLOCKED)
    assert invalid["generated_answer"] == get_user_message(UserMessageType.INVALID_QUESTION)

    async def classify_smalltalk(query, llm_service=None):
        return "smalltalk", "잡담"

    monkeypatch.setattr(guardrail_module, "_llm_classify", classify_smalltalk)
    smalltalk = asyncio.run(guardrail_module.guardrail({"original_query": "오늘 뭐해"}))
    assert smalltalk["generated_answer"] == get_user_message(UserMessageType.OUT_OF_SCOPE)


# 2026.11.04(sooyeon.choi) 추가 - 업무 키워드 즉시 통과 규칙 (예: "부품 리스트"가 smalltalk로 막히던 문제)
def test_guardrail_rag_keywords_bypass_llm(monkeypatch):
    settings = SimpleNamespace(enable_guardrail=True, guardrail_llm_fallback=True)
    monkeypatch.setattr(guardrail_module, "get_settings", lambda: settings)

    async def classify_smalltalk(query, llm_service=None):
        return "smalltalk", "잡담"

    monkeypatch.setattr(guardrail_module, "_llm_classify", classify_smalltalk)

    for query in ("부품 리스트", "3번 공정 토크값", "브라켓 체결 순서", "SOP 사진 보여줘"):
        result = asyncio.run(guardrail_module.guardrail({"original_query": query}))
        assert result["intent"] == "rag_query", query
        assert result["should_retrieve"] is True
        assert "generated_answer" not in result

    # 금지 키워드가 함께 있으면 unsafe가 우선한다.
    unsafe = asyncio.run(guardrail_module.guardrail({"original_query": "작업 관리자 계정 알려줘"}))
    assert unsafe["intent"] == "unsafe"

    # 업무 키워드가 없으면 기존처럼 LLM 분류를 따른다.
    smalltalk = asyncio.run(guardrail_module.guardrail({"original_query": "오늘 뭐해"}))
    assert smalltalk["intent"] == "smalltalk"


def test_guardrail_rag_keywords_can_be_disabled(monkeypatch):
    config = dict(guardrail_module._load_config())
    config["rag_keywords_enabled"] = False
    assert guardrail_module._rule_based_check("부품 리스트", config) is None

    config["rag_keywords_enabled"] = True
    assert guardrail_module._rule_based_check("부품 리스트", config) == (
        "rag_query",
        "업무 키워드 포함: 부품",
    )


def test_build_response_hides_validation_and_retrieval_details():
    validation = asyncio.run(build_response({
        "outcome_code": "validation_error",
        "error": "질문이 너무 짧습니다. 2자 이상 입력해주세요.",
        "generated_answer": None,
    }))
    retrieval = asyncio.run(build_response({
        "outcome_code": "retrieval_error",
        "error": "qdrant connection refused",
        "generated_answer": None,
    }))

    assert validation["error"] == get_user_message(UserMessageType.INVALID_QUESTION)
    assert retrieval["error"] == get_user_message(UserMessageType.TEMPORARY_ERROR)
    assert "qdrant" not in retrieval["error"]


def test_fallback_preserves_final_outcome_codes(monkeypatch):
    settings = SimpleNamespace(fallback_max_retries=0)
    monkeypatch.setattr(fallback_handler_module, "get_settings", lambda: settings)

    no_context = asyncio.run(fallback_handler({"retry_count": 0, "error": None}))
    llm_error = asyncio.run(fallback_handler({"retry_count": 0, "error": "timeout"}))

    assert no_context["generated_answer"] == get_user_message(UserMessageType.NO_CONTEXT)
    assert no_context["outcome_code"] == "no_context"
    assert llm_error["generated_answer"] == get_user_message(UserMessageType.TEMPORARY_ERROR)
    assert llm_error["outcome_code"] == "llm_error"


class _FakeLlm:
    def __init__(self, tokens):
        self.tokens = tokens

    async def chat_stream(self, messages, usage_sink=None):
        for token in self.tokens:
            yield token


async def _ignore_event(name, data):
    return None


def test_generate_answer_normalizes_no_context(monkeypatch):
    message = get_user_message(UserMessageType.NO_CONTEXT)
    monkeypatch.setattr(
        generate_answer_module,
        "resolve_llm_from_state",
        lambda state, settings: _FakeLlm([f'"{message}"']),
    )
    monkeypatch.setattr(generate_answer_module, "get_settings", lambda: SimpleNamespace())
    monkeypatch.setattr(generate_answer_module, "adispatch_custom_event", _ignore_event)

    result = asyncio.run(generate_answer_module.generate_answer({
        "original_query": "질문",
        "final_context": "문맥",
        "context_chunk_count": 1,
        "reranked_chunks": [],
    }))

    assert result["generated_answer"] == message
    assert result["outcome_code"] == "no_context"
    assert result["citations"] == []


def test_generate_answer_rejects_empty_output(monkeypatch):
    monkeypatch.setattr(
        generate_answer_module,
        "resolve_llm_from_state",
        lambda state, settings: _FakeLlm(["  "]),
    )
    monkeypatch.setattr(generate_answer_module, "get_settings", lambda: SimpleNamespace())
    monkeypatch.setattr(generate_answer_module, "adispatch_custom_event", _ignore_event)

    result = asyncio.run(generate_answer_module.generate_answer({
        "original_query": "질문",
        "final_context": "문맥",
        "context_chunk_count": 1,
        "reranked_chunks": [],
    }))

    assert result["outcome_code"] == "llm_error"
    assert "generated_answer" not in result


def test_generate_answer_dispatches_each_stream_token(monkeypatch):
    events = []

    async def capture_event(name, data):
        events.append((name, data))

    monkeypatch.setattr(
        generate_answer_module,
        "resolve_llm_from_state",
        lambda state, settings: _FakeLlm(["첫째", "둘째"]),
    )
    monkeypatch.setattr(generate_answer_module, "get_settings", lambda: SimpleNamespace())
    monkeypatch.setattr(generate_answer_module, "adispatch_custom_event", capture_event)

    result = asyncio.run(generate_answer_module.generate_answer({
        "original_query": "질문",
        "final_context": "문맥",
        "context_chunk_count": 1,
        "reranked_chunks": [],
    }))

    assert result["generated_answer"] == "첫째둘째"
    assert events == [
        ("rag_token", {"token": "첫째"}),
        ("rag_token", {"token": "둘째"}),
    ]

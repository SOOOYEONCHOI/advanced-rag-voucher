"""LangGraph 이벤트의 SSE 변환 회귀 테스트."""

import asyncio
import json
from types import SimpleNamespace

import pytest

pytest.importorskip("langgraph")

import app.services.rag_service as rag_service_module
from app.services.rag_service import RAGService


class _FakeGraph:
    async def astream_events(self, state, version):
        assert state["original_query"] == "질문"
        assert version == "v2"
        yield {
            "event": "on_chain_start",
            "name": "retrieve",
            "metadata": {"langgraph_node": "retrieve"},
        }
        yield {
            "event": "on_chain_start",
            "name": "generate_answer",
            "metadata": {"langgraph_node": "generate_answer"},
        }
        yield {
            "event": "on_custom_event",
            "name": "rag_token",
            "data": {"token": "첫째"},
        }
        yield {
            "event": "on_custom_event",
            "name": "rag_token",
            "data": {"token": "둘째"},
        }
        yield {
            "event": "on_chain_end",
            "name": "LangGraph",
            "parent_ids": [],
            "data": {
                "output": {
                    **state,
                    "generated_answer": "첫째둘째",
                    "citations": [{"document_id": "doc-1"}],
                }
            },
        }


class _FakeRecorder:
    def __init__(self, repository):
        self.repository = repository

    async def record(self, record, state, **kwargs):
        assert kwargs["answer"] == "첫째둘째"
        return 7


def test_query_stream_converts_graph_tokens_to_sse(monkeypatch):
    settings = SimpleNamespace(
        instance_dir=":memory:",
        max_query_top_k=20,
        context_top_k=5,
        max_citation_results=5,
        relevance_threshold=0.5,
    )
    monkeypatch.setattr(rag_service_module, "get_settings", lambda: settings)
    monkeypatch.setattr(rag_service_module, "MetadataRepository", lambda *_: object())
    monkeypatch.setattr(rag_service_module, "QueryRecorder", _FakeRecorder)

    service = object.__new__(RAGService)
    service._current_graph = lambda: _FakeGraph()

    async def collect():
        return [
            json.loads(event.removeprefix("data: ").strip())
            async for event in service.query_stream(query="질문", user_id="user-1")
        ]

    events = asyncio.run(collect())

    assert events == [
        {"type": "progress", "stage": "searching"},
        {"type": "progress", "stage": "generating"},
        {"type": "token", "content": "첫째"},
        {"type": "token", "content": "둘째"},
        {"type": "citations", "data": [{"document_id": "doc-1"}]},
        {"type": "meta", "log_id": 7},
        {"type": "done"},
    ]


# 2026.11.11(sooyeon.choi) 추가 - LLM 재시도·최종 실패 시 reset 이벤트(답변 이어 붙임 방지)
def _token(text):
    return {"event": "on_custom_event", "name": "rag_token", "data": {"token": text}}


def _generate_start():
    return {
        "event": "on_chain_start",
        "name": "generate_answer",
        "metadata": {"langgraph_node": "generate_answer"},
    }


class _ScriptedGraph:
    def __init__(self, events, output):
        self.events = events
        self.output = output

    async def astream_events(self, state, version):
        for event in self.events:
            yield event
        yield {
            "event": "on_chain_end",
            "name": "LangGraph",
            "parent_ids": [],
            "data": {"output": {**state, **self.output}},
        }


def _run_stream(monkeypatch, graph):
    settings = SimpleNamespace(
        instance_dir=":memory:",
        max_query_top_k=20,
        context_top_k=5,
        max_citation_results=5,
        relevance_threshold=0.5,
    )
    recorded = {}

    class _Recorder:
        def __init__(self, repository):
            pass

        async def record(self, record, state, **kwargs):
            recorded.update(kwargs)
            return 1

    monkeypatch.setattr(rag_service_module, "get_settings", lambda: settings)
    monkeypatch.setattr(rag_service_module, "MetadataRepository", lambda *_: object())
    monkeypatch.setattr(rag_service_module, "QueryRecorder", _Recorder)
    service = object.__new__(RAGService)
    service._current_graph = lambda: graph

    async def collect():
        return [
            json.loads(event.removeprefix("data: ").strip())
            async for event in service.query_stream(query="질문", user_id="user-1")
        ]

    return asyncio.run(collect()), recorded


def _screen_text(events):
    """화면(useChatView)과 같은 규칙으로 token은 이어 붙이고 reset은 비운다."""
    text = ""
    for event in events:
        if event["type"] == "reset":
            text = ""
        elif event["type"] == "token":
            text += event["content"]
    return text


def test_llm_retry_resets_partial_answer(monkeypatch):
    graph = _ScriptedGraph(
        [_generate_start(), _token("끊긴"), _generate_start(), _token("새 답변")],
        {"generated_answer": "새 답변", "outcome_code": "success"},
    )
    events, recorded = _run_stream(monkeypatch, graph)

    assert {"type": "reset"} in events
    assert _screen_text(events) == "새 답변"
    assert recorded["answer"] == "새 답변"


def test_llm_final_failure_after_tokens_shows_error_message(monkeypatch):
    from app.core.user_messages import UserMessageType, get_user_message

    message = get_user_message(UserMessageType.TEMPORARY_ERROR)
    graph = _ScriptedGraph(
        [_generate_start(), _token("끊긴"), _generate_start(), _token("또 끊긴")],
        {"generated_answer": message, "outcome_code": "llm_error"},
    )
    events, recorded = _run_stream(monkeypatch, graph)

    assert _screen_text(events) == message
    assert recorded["answer"] == message


def test_first_generation_has_no_reset(monkeypatch):
    graph = _ScriptedGraph(
        [_generate_start(), _token("정상")],
        {"generated_answer": "정상", "outcome_code": "success"},
    )
    events, _ = _run_stream(monkeypatch, graph)

    assert {"type": "reset"} not in events
    assert _screen_text(events) == "정상"

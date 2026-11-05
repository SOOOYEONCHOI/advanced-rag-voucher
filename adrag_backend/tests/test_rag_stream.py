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

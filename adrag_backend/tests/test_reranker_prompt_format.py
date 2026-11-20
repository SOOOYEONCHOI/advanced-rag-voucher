# 2026.11.19(sooyeon.choi) 수정 - 리랭커 입력 형식(plain/qwen3)·평가 리랭커 입력을 운영과 일치
"""- plain(기본): 질의·문서를 그대로 보낸다(기존 동작)
- qwen3: Qwen3-Reranker 공식 지시문 형식
- 검색·재정렬 평가 리랭커: 운영 rerank 노드와 같이 본문 중복 제거 + [문서명]·[섹션] 접두
"""

import asyncio
from types import SimpleNamespace

import pytest

from app.clients.reranker_client import RerankerClient, format_rerank_inputs


def _settings(**overrides):
    base = dict(
        reranker_top_k=10, reranker_api_url="http://reranker", reranker_api_key="k",
        reranker_model_name="Qwen3-Reranker-0.6B", reranker_timeout=5.0, reranker_truncate_prompt_tokens=-1,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_plain_format_keeps_texts():
    assert format_rerank_inputs("plain", "지시", "질문", ["문서 A"]) == ("질문", ["문서 A"])


def test_qwen3_format_wraps_query_and_documents():
    query, docs = format_rerank_inputs("qwen3", "Judge law articles", "경영책임자의 의무는?", ["제4조 본문", "제5조 본문"])
    assert query.startswith("<|im_start|>system\nJudge whether the Document meets the requirements")
    assert query.endswith("<|im_start|>user\n<Instruct>: Judge law articles\n<Query>: 경영책임자의 의무는?\n")
    assert docs == [
        "<Document>: 제4조 본문<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n",
        "<Document>: 제5조 본문<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n",
    ]


def test_client_sends_formatted_payload_and_default_is_plain(monkeypatch):
    import app.clients.reranker_client as module

    sent = []

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": [{"index": 0, "score": 0.2}, {"index": 1, "score": 0.9}]}

    class FakeClient:
        async def post(self, url, json, headers, timeout):
            sent.append(json)
            return FakeResponse()

    monkeypatch.setattr(module, "get_shared_async_client", lambda: FakeClient())
    plain = RerankerClient(_settings())                      # 설정이 없으면 plain(기존 동작)
    assert asyncio.run(plain.rerank("질문", ["a", "b"])) == [(1, 0.9), (0, 0.2)]
    assert sent[-1]["text_1"] == "질문" and sent[-1]["text_2"] == ["a", "b"]

    qwen3 = RerankerClient(_settings(reranker_prompt_format="qwen3", reranker_instruction="지시"))
    asyncio.run(qwen3.rerank("질문", ["a", "b"]))
    assert "<Instruct>: 지시\n<Query>: 질문\n" in sent[-1]["text_1"]
    assert sent[-1]["text_2"][0].startswith("<Document>: a")


def test_eval_reranker_uses_production_rerank_input(monkeypatch):
    import app.evaluation.adapters.reranker_adapter as adapter

    received = {}

    class FakeRerankerClient:
        async def rerank(self, query, documents, top_k=None):
            received["documents"] = documents
            return [(1, 0.8), (0, 0.5)]

    monkeypatch.setattr(adapter, "_get_client", lambda: FakeRerankerClient())
    hits = [
        ("old", 0.9, {"text": "같은 본문", "original_filename": "옛 시행령.pdf", "header_path": ["제1장", "제2조"]}),
        ("p1", 0.8, {"text": "같은 본문", "original_filename": "시행령.pdf", "header_path": ["제1장", "제2조"]}),
        ("p2", 0.7, {"text": "다른 본문", "original_filename": "시행령.pdf", "section_title": "제3조"}),
    ]
    result = asyncio.run(adapter.EvalReranker().rerank("질문", hits, top_k=2))
    # 같은 본문은 하나만 남고(점수가 높은 것), 입력에 문서명·섹션 접두가 붙는다
    assert received["documents"] == [
        "[문서명] 옛 시행령.pdf\n[섹션] 제1장 > 제2조\n[본문] 같은 본문",
        "[문서명] 시행령.pdf\n[섹션] 제3조\n[본문] 다른 본문",
    ]
    assert [chunk_id for chunk_id, _, _ in result] == ["p2", "old"]


@pytest.mark.parametrize("mode,expected", [("ok", "ok"), ("timeout", "error"), ("disabled", "skipped"), ("empty", "empty")])
def test_rerank_node_records_stage_outcome(monkeypatch, mode, expected):
    from importlib import import_module
    node = import_module("app.graphs.nodes.rerank")

    class Client:
        async def rerank(self, *_args, **_kwargs):
            if mode == "timeout":
                raise asyncio.TimeoutError()
            return [(0, 0.9)]

    settings = _settings(enable_reranking=mode != "disabled", reranker_degraded_top_k=1,
                         relevance_threshold=0.25)
    monkeypatch.setattr(node, "get_retrieval_config", lambda *_args: SimpleNamespace(rerank_top_k=1))
    deps = SimpleNamespace(settings=settings, container=SimpleNamespace(reranker=Client()))
    chunks = [] if mode == "empty" else [
        {"chunk_id": "c1", "document_id": "d1", "text": "example evidence", "score": 0.8, "metadata": {}}
    ]
    result = asyncio.run(node.rerank.__wrapped__({"original_query": "query", "retrieved_chunks": chunks}, deps))
    assert result["rerank_status"] == expected
    if mode in ("timeout", "disabled"):
        assert result["reranked_chunks"][0]["chunk_id"] == "c1"  # 운영 폴백은 유지

# -*- coding: utf-8 -*-
"""
2026.07.16(sooyeon.choi) 추가 - 3단계 인터페이스 도입 단위 테스트.

- Protocol 계약 준수: 기존 구현체가 인터페이스를 구조적으로 만족하는지 검증
- LLM 프로바이더 레지스트리: 등록/생성/선택(resolve_llm_from_state) 규칙 검증
- 파서/청커 레지스트리: 라우팅 및 신규 전략 등록 확장점 검증
"""

from types import SimpleNamespace

import pytest

from app.interfaces import (
    EmbeddingProvider,
    LLMProvider,
    QueryPreprocessorProtocol,
    Reranker,
    VectorStore,
)


def _fake_llm_settings() -> SimpleNamespace:
    return SimpleNamespace(
        vllm_api_url="http://fake:8000",
        vllm_model_name="fake-model",
        vllm_api_key="EMPTY",
        vllm_timeout=10.0,
        vllm_max_tokens=128,
        vllm_temperature=0.1,
    )


def _fake_embedding_settings() -> SimpleNamespace:
    return SimpleNamespace(
        embedding_api_url="http://fake:8001",
        embedding_model_name="fake-embed",
        embedding_api_key="EMPTY",
        embedding_timeout=10.0,
        embedding_batch_size=8,
        embedding_dim=8,
        embedding_max_model_len=512,
        embedding_instruct_template="Query: {query}",
        embedding_truncate_prompt_tokens=-1,
    )


def _fake_reranker_settings() -> SimpleNamespace:
    return SimpleNamespace(
        reranker_top_k=5,
        reranker_api_url="http://fake:8002",
        reranker_api_key="EMPTY",
        reranker_model_name="fake-reranker",
        reranker_timeout=10.0,
        reranker_truncate_prompt_tokens=-1,
    )


# ── Protocol 계약 준수 ───────────────────────────────────────────────────────

def test_embedding_client_satisfies_embedding_provider():
    from app.clients.embedding_client import EmbeddingClient
    client = EmbeddingClient(_fake_embedding_settings())
    assert isinstance(client, EmbeddingProvider)


def test_reranker_client_satisfies_reranker():
    from app.clients.reranker_client import RerankerClient
    client = RerankerClient(_fake_reranker_settings())
    assert isinstance(client, Reranker)


def test_llm_service_satisfies_llm_provider():
    from app.services.llm_service import LLMService
    service = LLMService(_fake_llm_settings())
    assert isinstance(service, LLMProvider)


def test_query_preprocessor_satisfies_protocol():
    from app.graphs.preprocessing import QueryPreprocessor
    assert isinstance(QueryPreprocessor(), QueryPreprocessorProtocol)


def test_vector_repository_declares_vectorstore_methods():
    # VectorRepository 인스턴스화는 QdrantClient 생성이 필요하므로 메서드 존재만 검증
    # 주의: test_collection_service.py가 sys.modules에 스텁을 심으므로(테스트 오염)
    #   스텁이 감지되면 실제 모듈을 다시 로드해 검증한다.
    import sys
    module_name = "app.repositories.vector_repository"
    mod = sys.modules.get(module_name)
    if mod is not None and not hasattr(getattr(mod, "VectorRepository", None), "search_hybrid"):
        sys.modules.pop(module_name, None)
    from app.repositories.vector_repository import VectorRepository
    # 2026.07.28(sooyeon.choi) 수정 - 평가용 Kiwi BM25 직접 검색 계약 검증
    for method in (
        "search_similar",
        "search_bm25",
        "search_sparse",
        "search_kiwi_bm25",
        "search_hybrid",
    ):
        assert callable(getattr(VectorRepository, method, None)), method


# ── LLM 프로바이더 레지스트리 ────────────────────────────────────────────────

def test_create_llm_provider_unknown_name_raises():
    from app.core.registry import create_llm_provider
    with pytest.raises(ValueError):
        create_llm_provider("no-such-provider", _fake_llm_settings())


def test_openai_factory_builds_openai_service():
    from app.core.registry import create_llm_provider
    provider = create_llm_provider(
        "openai", _fake_llm_settings(), model="gpt-4o-mini", api_key="sk-test"
    )
    assert getattr(provider, "_is_openai") is True


def test_resolve_llm_from_state_selects_openai_when_fully_specified():
    from app.core.registry import resolve_llm_from_state
    state = {
        "llm_provider": "openai",
        "llm_model": "gpt-4o-mini",
        "llm_api_key": "sk-test",
    }
    provider = resolve_llm_from_state(state, _fake_llm_settings())
    assert getattr(provider, "_is_openai") is True


def test_resolve_llm_from_state_falls_back_to_local_without_api_key():
    # api_key 누락 시 local 폴백 — local 팩토리를 더미로 치환해 네트워크/env 의존 제거
    from app.core import registry

    sentinel = object()
    original = registry._llm_providers["local"]
    registry.register_llm_provider("local", lambda s, m, k: sentinel)
    try:
        state = {"llm_provider": "openai", "llm_model": "gpt-4o-mini", "llm_api_key": None}
        resolved = registry.resolve_llm_from_state(state, _fake_llm_settings())
        assert resolved is sentinel
    finally:
        registry.register_llm_provider("local", original)


def test_register_llm_provider_extension_point():
    # 신규 프로바이더(예: gemini)가 등록만으로 편입되는지 검증
    from app.core import registry

    class _DummyProvider:
        async def chat(self, messages, *, temperature=None, max_tokens=None):
            return None

        def chat_stream(self, messages, *, temperature=None, max_tokens=None, usage_sink=None):
            raise NotImplementedError

    registry.register_llm_provider("dummy-gemini", lambda s, m, k: _DummyProvider())
    try:
        provider = registry.create_llm_provider("dummy-gemini", _fake_llm_settings())
        assert isinstance(provider, LLMProvider)
    finally:
        registry._llm_providers.pop("dummy-gemini", None)


# ── 파서/청커 레지스트리 ─────────────────────────────────────────────────────

def test_chunker_registry_covers_all_doc_types():
    from app.parsers.processor import CHUNKER_REGISTRY
    assert set(CHUNKER_REGISTRY) >= {"law", "manual", "general"}


def test_register_chunker_extension_point():
    from app.parsers import processor

    def _dummy_chunker(docs, config):
        return docs

    original = processor.CHUNKER_REGISTRY.get("general")
    processor.register_chunker("general", _dummy_chunker)
    try:
        assert processor.CHUNKER_REGISTRY["general"] is _dummy_chunker
    finally:
        processor.register_chunker("general", original)


def test_parser_routing_pdfplumber_only_for_pdf():
    from app.parsers.config import ChunkingConfig
    from app.parsers.processor import _resolve_parser_name

    cfg_plumber = ChunkingConfig(parser_type="pdfplumber")
    assert _resolve_parser_name("pdf", cfg_plumber) == "pdfplumber"
    assert _resolve_parser_name("docx", cfg_plumber) == "docling"

    cfg_docling = ChunkingConfig(parser_type="docling")
    assert _resolve_parser_name("pdf", cfg_docling) == "docling"


def test_register_parser_extension_point():
    from app.parsers import processor
    from app.parsers.config import ChunkingConfig

    processor.register_parser("dummy-ocr", lambda: object())
    try:
        cfg = ChunkingConfig(parser_type="dummy-ocr")
        assert processor._resolve_parser_name("png", cfg) == "dummy-ocr"
    finally:
        processor.PARSER_REGISTRY.pop("dummy-ocr", None)

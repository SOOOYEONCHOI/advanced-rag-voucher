# 2026.11.11(sooyeon.choi) 추가 - (R4-1, MOD-08) 가중치 프로필(QUERY_TYPE_PROFILE)·원문 질의 비중(DENSE_ORIGINAL_QUERY_SHARE)
import asyncio
import importlib
from types import SimpleNamespace

import pytest
from qdrant_client.models import SparseVector

from app.graphs.retrieval_engine import (
    RRF_WEIGHTS,
    QueryType,
    build_query_bundle,
    dense_query_weights,
    get_rrf_weights,
)
from app.repositories.vector_repository import VectorRepository

# app.graphs.nodes 패키지의 retrieve는 노드 함수이므로 모듈을 직접 가져온다
retrieve_module = importlib.import_module("app.graphs.nodes.retrieve")
_SPARSE = SparseVector(indices=[1], values=[1.0])


# ── 가중치 프로필 ──────────────────────────────────────────────────────────────

def test_default_profile_is_legacy_weights():
    for query_type in QueryType:
        assert get_rrf_weights(query_type) == RRF_WEIGHTS[query_type]
        assert get_rrf_weights(query_type, SimpleNamespace(query_type_profile="legacy")) == RRF_WEIGHTS[query_type]


def test_unknown_profile_falls_back_to_legacy():
    settings = SimpleNamespace(query_type_profile="unknown")
    assert get_rrf_weights(QueryType.CONCEPT_EXPLANATION, settings) == RRF_WEIGHTS[QueryType.CONCEPT_EXPLANATION]


def test_sop_profile_keeps_legal_and_prefers_bm25_elsewhere():
    settings = SimpleNamespace(query_type_profile="sop")
    assert get_rrf_weights(QueryType.LEGAL_REFERENCE, settings) == RRF_WEIGHTS[QueryType.LEGAL_REFERENCE]
    for query_type in (QueryType.CONCEPT_EXPLANATION, QueryType.MENU_MANUAL, QueryType.INCIDENT_NARRATIVE):
        weights = get_rrf_weights(query_type, settings)
        assert weights["dense"] == 1.0
        assert weights["kiwi_bm25"] == 1.5


def test_returned_weights_are_copies():
    weights = get_rrf_weights(QueryType.CONCEPT_EXPLANATION)
    weights["dense"] = 99
    assert RRF_WEIGHTS[QueryType.CONCEPT_EXPLANATION]["dense"] != 99


# ── 원문 질의 비중 ─────────────────────────────────────────────────────────────

def test_dense_weights_uniform_without_share():
    assert dense_query_weights(["q", "r1", "r2"], "q", 1.5) == [0.5, 0.5, 0.5]


def test_dense_weights_original_share():
    assert dense_query_weights(["q", "r1", "r2"], "q", 1.0, 0.5) == pytest.approx([0.5, 0.25, 0.25])


def test_dense_weights_original_not_first():
    assert dense_query_weights(["r1", "q", "r2"], "q", 2.0, 0.5) == pytest.approx([0.5, 1.0, 0.5])


@pytest.mark.parametrize(
    ("queries", "original"),
    [(["q"], "q"), (["r1", "r2"], "q")],
)
def test_dense_weights_uniform_when_single_or_original_missing(queries, original):
    assert dense_query_weights(queries, original, 1.0, 0.5) == pytest.approx([1.0 / len(queries)] * len(queries))


def test_dense_weights_total_is_preserved():
    weights = dense_query_weights(["q", "r1", "r2", "r3"], "q", 1.0, 0.7)
    assert sum(weights) == pytest.approx(1.0)


# ── 설정 검증 ──────────────────────────────────────────────────────────────────

def test_share_setting_validator():
    from app.core.config import Settings

    validate = Settings.validate_dense_original_query_share
    assert validate("") is None
    assert validate(None) is None
    assert validate("0.5") == 0.5
    with pytest.raises(ValueError):
        validate("1.5")


# ── retrieve → search_hybrid 전달 ─────────────────────────────────────────────

class _Encoder:
    def encode_query(self, text):
        return _SPARSE


class _Store:
    def __init__(self):
        self.kwargs = None

    def search_hybrid(self, **kwargs):
        self.kwargs = kwargs
        return []


def _bundle():
    return build_query_bundle({
        "original_query": "XG-500A 체결",
        "rewritten_queries": ["XG-500A 체결", "XG500A 조립 방법", "브라켓 체결 순서"],
        "rewritten_query_embeddings": [[0.1], [0.2], [0.3]],
        "preprocess_result": {},
    })


def _settings(**overrides):
    base = dict(dense_prefetch_k=80, sparse_prefetch_k=80, hybrid_rrf_k=60,
                query_type_profile="legacy", dense_original_query_share=None)
    base.update(overrides)
    return SimpleNamespace(**base)


def _run(settings):
    store = _Store()
    container = SimpleNamespace(vector_store=store, kiwi_bm25_encoder=_Encoder(), embedding=None)
    asyncio.run(retrieve_module._search_qdrant_hybrid(
        query_bundle=_bundle(), collection_name="c", filters=None, top_k=40,
        query_type=QueryType.CONCEPT_EXPLANATION, settings=settings, container=container,
    ))
    return store.kwargs


def test_legacy_settings_call_search_hybrid_as_before():
    kwargs = _run(_settings())
    assert kwargs["dense_weight"] == 1.5
    assert kwargs["sparse_weight"] == 0.7
    assert "dense_weights" not in kwargs


def test_sop_profile_with_share_passes_per_query_weights():
    kwargs = _run(_settings(query_type_profile="sop", dense_original_query_share=0.5))
    assert kwargs["dense_weight"] == 1.0
    assert kwargs["sparse_weight"] == 1.5
    assert kwargs["dense_weights"] == pytest.approx([0.5, 0.25, 0.25])


# ── search_hybrid가 질의별 가중치를 Qdrant RRF에 넣는지 ─────────────────────────

def _repository(captured):
    class FakeClient:
        def query_points(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(points=[])

    repo = object.__new__(VectorRepository)
    repo.client = FakeClient()
    repo.collection_name = "default"
    repo.kiwi_bm25_vector_name = "kiwi_bm25"
    repo._visible = lambda query_filter: query_filter
    return repo


def test_search_hybrid_uses_dense_weights_when_given():
    captured = {}
    _repository(captured).search_hybrid(
        dense_vectors=[[0.1], [0.2], [0.3]], sparse_query=_SPARSE, top_k=10,
        dense_weight=1.0, sparse_weight=1.5, dense_weights=[0.5, 0.25, 0.25],
    )
    assert captured["query"].rrf.weights == [0.5, 0.25, 0.25, 1.5]


@pytest.mark.parametrize("dense_weights", [None, [0.5, 0.5]])
def test_search_hybrid_falls_back_to_uniform(dense_weights):
    captured = {}
    _repository(captured).search_hybrid(
        dense_vectors=[[0.1], [0.2], [0.3]], sparse_query=_SPARSE, top_k=10,
        dense_weight=1.5, sparse_weight=0.7, dense_weights=dense_weights,
    )
    assert captured["query"].rrf.weights == pytest.approx([0.5, 0.5, 0.5, 0.7])

"""평가용 Kiwi BM25 direct sparse 검색 회귀 테스트."""

import asyncio
import time
from types import SimpleNamespace

import pytest

from app.evaluation.adapters import retrieval_adapter
from app.evaluation.adapters.retrieval_adapter import EvalRetriever
from app.repositories.vector_repository import VectorRepository


class _FakeKiwiEncoder:
    def encode_query(self, text):
        return {"encoded": text}


class _FailingEmbeddingClient:
    async def embed_query(self, _query):
        raise AssertionError("Kiwi 단독 평가에서 Dense 임베딩을 호출하면 안 됩니다.")


def test_vector_repository_search_kiwi_bm25_uses_named_sparse_vector():
    # 2026.07.28(sooyeon.choi) 수정 - RRF 없이 kiwi_bm25 named vector 직접 조회 검증
    captured = {}

    class FakeClient:
        def query_points(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                points=[
                    SimpleNamespace(
                        id="chunk-1",
                        score=12.5,
                        payload={"chunk_id": "chunk-1"},
                    )
                ]
            )

    repository = object.__new__(VectorRepository)
    repository.client = FakeClient()
    repository.collection_name = "default"
    repository.kiwi_bm25_vector_name = "kiwi_bm25"

    query = object()
    results = repository.search_kiwi_bm25(
        query=query,
        top_k=7,
        collection_name="eval_collection",
    )

    assert captured == {
        "collection_name": "eval_collection",
        "query": query,
        "using": "kiwi_bm25",
        "query_filter": None,
        "limit": 7,
        "with_payload": True,
        "with_vectors": False,
    }
    assert results == [("chunk-1", 12.5, {"chunk_id": "chunk-1"})]


def test_vector_repository_search_kiwi_bm25_distinguishes_error_from_empty():
    # 2026.07.28(sooyeon.choi) 수정 - 정상 0건과 Qdrant 오류를 구분해 평가 오판 방지
    repository = object.__new__(VectorRepository)
    repository.collection_name = "default"
    repository.kiwi_bm25_vector_name = "kiwi_bm25"

    repository.client = SimpleNamespace(
        query_points=lambda **_kwargs: SimpleNamespace(points=[])
    )
    assert repository.search_kiwi_bm25(query=object(), top_k=5) == []

    def fail(**_kwargs):
        raise ValueError("qdrant unavailable")

    repository.client = SimpleNamespace(query_points=fail)
    with pytest.raises(RuntimeError, match="Qdrant Kiwi BM25 검색 실패"):
        repository.search_kiwi_bm25(query=object(), top_k=5)


@pytest.mark.asyncio
async def test_eval_kiwi_uses_direct_sparse_without_dense_or_hybrid(monkeypatch):
    # 2026.07.28(sooyeon.choi) 수정 - 평가 Kiwi 경로의 운영 hybrid/Dense 호출 차단 검증
    calls = []

    class FakeVectorRepository:
        def search_kiwi_bm25(self, **kwargs):
            calls.append(kwargs)
            return [("gold-chunk", 9.5, {"chunk_id": "gold-chunk"})]

        def search_hybrid(self, **_kwargs):
            raise AssertionError("Kiwi 단독 평가에서 운영 hybrid 검색을 호출하면 안 됩니다.")

    monkeypatch.setattr(
        retrieval_adapter,
        "get_kiwi_bm25_encoder",
        lambda: _FakeKiwiEncoder(),
    )
    retriever = object.__new__(EvalRetriever)
    retriever._vector_repo = FakeVectorRepository()
    retriever._embedding_client = _FailingEmbeddingClient()

    results = await retriever._search_sparse_only(
        "산업안전보건법 기준은?",
        top_k=10,
        collection_name="eval_collection",
    )

    assert results == [("gold-chunk", 9.5, {"chunk_id": "gold-chunk"})]
    assert calls == [
        {
            "query": {"encoded": "산업안전보건법 기준은?"},
            "top_k": 10,
            "collection_name": "eval_collection",
            "filters": None,
        }
    ]


@pytest.mark.asyncio
async def test_eval_kiwi_direct_search_is_serialized(monkeypatch):
    # 2026.07.28(sooyeon.choi) 수정 - 동시 평가에서도 Kiwi query/search 구간 단일 실행 보장
    active = 0
    max_active = 0

    class FakeVectorRepository:
        def search_kiwi_bm25(self, **_kwargs):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            time.sleep(0.02)
            active -= 1
            return []

    monkeypatch.setattr(
        retrieval_adapter,
        "get_kiwi_bm25_encoder",
        lambda: _FakeKiwiEncoder(),
    )
    retriever = object.__new__(EvalRetriever)
    retriever._vector_repo = FakeVectorRepository()
    retriever._embedding_client = _FailingEmbeddingClient()

    await asyncio.gather(
        *[
            retriever._search_sparse_only(
                f"질문 {index}",
                top_k=10,
                collection_name="eval_collection",
            )
            for index in range(3)
        ]
    )

    assert max_active == 1

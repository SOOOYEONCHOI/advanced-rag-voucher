# 2026.06.29(sooyeon.choi) 수정 - Task 5 MatchText 핵심 검색어와 BM25 설정값 전달 검증
import importlib
import sys
import types
from types import SimpleNamespace

config_stub = types.ModuleType("app.core.config")
config_stub.LOG_PATH = "./instance/log"
sys.modules.setdefault("app.core.config", config_stub)

sys.modules.pop("app.core.config", None)


class FakeScores:
    def tolist(self):
        return [1.0]


def test_search_bm25_uses_core_tokens_for_match_text_and_configured_parameters(
    monkeypatch,
):
    captured = {}

    # 2026.06.29(sooyeon.choi) 수정 - Qdrant 미설치 단위 테스트 환경에서도 저장소 검색 조건 검증
    class FakeModel:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)

    class FakeEnum:
        COSINE = "cosine"
        KEYWORD = "keyword"
        WORD = "word"

    qdrant_stub = types.ModuleType("qdrant_client")
    qdrant_stub.QdrantClient = object
    qdrant_http_stub = types.ModuleType("qdrant_client.http")
    qdrant_exceptions_stub = types.ModuleType("qdrant_client.http.exceptions")
    qdrant_exceptions_stub.UnexpectedResponse = RuntimeError
    qdrant_models_stub = types.ModuleType("qdrant_client.models")
    for name in (
        "VectorParams", "PointStruct", "Filter", "FieldCondition",
        "MatchValue", "MatchAny", "MatchText", "TextIndexParams",
        "SparseVectorParams", "SparseIndexParams", "SparseVector",
    ):
        setattr(qdrant_models_stub, name, FakeModel)
    qdrant_models_stub.Distance = FakeEnum
    qdrant_models_stub.PayloadSchemaType = FakeEnum
    qdrant_models_stub.TokenizerType = FakeEnum
    monkeypatch.setitem(sys.modules, "qdrant_client", qdrant_stub)
    monkeypatch.setitem(sys.modules, "qdrant_client.http", qdrant_http_stub)
    monkeypatch.setitem(
        sys.modules, "qdrant_client.http.exceptions", qdrant_exceptions_stub
    )
    monkeypatch.setitem(sys.modules, "qdrant_client.models", qdrant_models_stub)

    repositories_package = importlib.import_module("app.repositories")
    monkeypatch.delitem(
        sys.modules, "app.repositories.vector_repository", raising=False
    )
    monkeypatch.delattr(
        repositories_package, "vector_repository", raising=False
    )
    vector_repository = importlib.import_module(
        "app.repositories.vector_repository"
    )

    class FakeBM25Okapi:
        def __init__(self, corpus, k1, b):
            captured["corpus"] = corpus
            captured["k1"] = k1
            captured["b"] = b

        def get_scores(self, query_tokens):
            captured["query_tokens"] = query_tokens
            return FakeScores()

    rank_bm25_stub = types.ModuleType("rank_bm25")
    rank_bm25_stub.BM25Okapi = FakeBM25Okapi
    monkeypatch.setitem(sys.modules, "rank_bm25", rank_bm25_stub)
    monkeypatch.setattr(
        vector_repository,
        "tokenize_query_for_bm25",
        lambda text: ["안전관리자", "자격", "요건"],
    )
    monkeypatch.setattr(
        vector_repository,
        "tokenize_corpus",
        lambda text: ["안전관리자", "자격", "요건"],
    )

    class FakeClient:
        def scroll(self, **kwargs):
            captured["filter"] = kwargs["scroll_filter"]
            point = SimpleNamespace(
                id="law-1",
                payload={"text": "안전관리자의 자격 요건"},
            )
            return [point], None

    repository = vector_repository.VectorRepository.__new__(
        vector_repository.VectorRepository
    )
    repository.collection_name = "documents"
    repository.client = FakeClient()
    repository.bm25_k1 = 1.2
    repository.bm25_b = 0.5

    results = repository.search_bm25("안전관리자의 자격 요건은")

    match_condition = captured["filter"].must[0]
    assert match_condition.match.text == "안전관리자 자격 요건"
    assert captured["query_tokens"] == ["안전관리자", "자격", "요건"]
    assert captured["k1"] == 1.2
    assert captured["b"] == 0.5
    assert results[0][0] == "law-1"


def test_bm25_parameter_comparison_uses_same_candidates(monkeypatch):
    from offline_evaluation import bm25_parameter_comparison as comparison

    candidates = [
        ("law-1", "안전관리자 선임 기준"),
        ("other-1", "일반 교육 안내"),
        ("other-2", "시스템 메뉴 설명"),
    ]
    monkeypatch.setattr(comparison, "_fetch_candidates", lambda *args, **kwargs: candidates)
    monkeypatch.setattr(comparison, "tokenize_query_for_bm25", lambda text: ["안전관리자"])
    monkeypatch.setattr(comparison, "tokenize_corpus", lambda text: text.split())

    result = comparison.compare(
        [{
            "id": "legal",
            "question": "안전관리자 선임 기준",
            "collection_name": "safety",
            "expected_evidence": [{"chunk_id": "law-1"}],
        }],
        qdrant_url="http://unused",
    )

    assert result["evaluated_records"] == 1
    assert result["before"]["recall_at_k"] == 1.0
    assert result["after"]["recall_at_k"] == 1.0
    assert result["before"]["k1"] == 1.5
    assert result["after"]["k1"] == 1.2

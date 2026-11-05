# 2026.06.29(sooyeon.choi) 수정 - Task 4 검색 프로필, 채널, query 분리, N채널 RRF 검증
import asyncio
import sys
import types
from types import SimpleNamespace

import pytest

config_stub = types.ModuleType("app.core.config")
config_stub.LOG_PATH = "./instance/log"
sys.modules.setdefault("app.core.config", config_stub)

from app.graphs.retrieval_engine import (
    Bm42Channel,
    DenseChannel,
    KiwiBm25Channel,
    QueryBundle,
    QueryType,
    RRF_WEIGHTS,
    RetrievalChannel,
    RetrievalConfig,
    RetrievalOrchestrator,
    _merge_rrf,
    apply_soft_boost,
    build_query_bundle,
    # 2026.07.16(sooyeon.choi) 추가 - B4 fallback 확장 규칙 테스트용
    expand_retrieval_config_for_fallback,
    classify_query_type,
    get_retrieval_config,
    get_retrieval_profile,
)

sys.modules.pop("app.core.config", None)


def _query_bundle() -> QueryBundle:
    return QueryBundle(
        original_query="산안법 제17조의3 안전관리자 기준",
        rewritten_queries=["산안법 제17조의3 안전관리자 기준"],
        rewritten_query_embeddings=[[0.1, 0.2]],
        normalized_query="산업안전보건법 제17조의3 안전관리자 기준",
        expanded_terms=["산업안전보건법"],
        law_references=["제17조의3"],
        extracted_keywords=["안전관리자", "기준"],
        dense_queries=["산안법 제17조의3 안전관리자 기준"],
        kiwi_bm25_query="산업안전보건법 제17조의3 안전관리자 기준",
        bm42_queries=[
            "산안법 제17조의3 안전관리자 기준",
            "산업안전보건법 제17조의3 안전관리자 기준",
        ],
    )


class StubChannel(RetrievalChannel):
    def __init__(self, name, calls):
        self.name = name
        self.calls = calls

    async def search(
        self,
        query_bundle,
        top_k,
        collection_name,
        filters,
        context=None,
    ):
        self.calls.append(self.name)
        return [(self.name, 1.0, {"text": self.name})]


def test_profiles_select_only_configured_channels_and_lazy_load_bm42():
    created = []
    searched = []

    def factory(name):
        def create():
            created.append(name)
            return StubChannel(name, searched)
        return create

    orchestrator = RetrievalOrchestrator({
        "dense": factory("dense"),
        "kiwi_bm25": factory("kiwi_bm25"),
        "bm42": factory("bm42"),
    })

    async def run(profile_name):
        return await orchestrator.search(
            profile=get_retrieval_profile(profile_name),
            query_bundle=_query_bundle(),
            top_k=10,
            collection_name="safety",
            filters=None,
        )

    default_results = asyncio.run(run("dense_kiwi"))
    assert list(default_results) == ["dense", "kiwi_bm25"]
    assert created == ["dense", "kiwi_bm25"]
    assert "bm42" not in searched

    bm42_results = asyncio.run(run("dense_bm42"))
    assert list(bm42_results) == ["dense", "bm42"]

    three_channel_results = asyncio.run(run("dense_kiwi_bm42"))
    assert list(three_channel_results) == ["dense", "kiwi_bm25", "bm42"]


def test_build_query_bundle_separates_dense_and_kiwi_queries():
    original = "산안법 제17조의3에 따른 안전관리자 선임 기준"
    state = {
        "original_query": original,
        "rewritten_queries": [original, "안전관리자 자격 요건"],
        "rewritten_query_embeddings": [[0.1], [0.2]],
        "preprocess_result": {
            "normalized_query": "산업안전보건법 제17조의3에 따른 안전관리자 선임 기준",
            "expanded_terms": ["산업안전보건법"],
            "matched_patterns": {"law_references": ["제17조의3"]},
            "extracted_keywords": ["산업안전보건법", "안전관리자", "선임", "기준"],
        },
    }

    bundle = build_query_bundle(state)

    assert bundle.dense_queries == [original, "안전관리자 자격 요건"]
    assert bundle.kiwi_bm25_query != bundle.dense_queries[0]
    assert "산업안전보건법" in bundle.kiwi_bm25_query
    assert "제17조의3" in bundle.kiwi_bm25_query
    assert "안전관리자" in bundle.kiwi_bm25_query


def test_channels_return_same_result_format_and_use_channel_queries():
    class FakeRepository:
        def __init__(self):
            self.bm25_query = None

        def search_similar(self, **kwargs):
            return [("dense-doc", 0.9, {"text": "dense"})]

        def search_bm25(self, **kwargs):
            self.bm25_query = kwargs["query_text"]
            return [("law-doc", 2.0, {"text": "제17조의3 안전관리자"})]

        def search_sparse(self, **kwargs):
            return [("bm42-doc", 0.8, {"text": "bm42"})]

    class FakeEmbeddingClient:
        async def embed_query(self, query):
            return [0.1, 0.2]

    class FakeSparseEncoder:
        async def encode_single(self, query):
            return SimpleNamespace(indices=[1], values=[0.5])

    repository = FakeRepository()
    bundle = _query_bundle()

    async def run_channels():
        channels = [
            DenseChannel(repository, FakeEmbeddingClient()),
            KiwiBm25Channel(repository),
            Bm42Channel(repository, FakeSparseEncoder()),
        ]
        return await asyncio.gather(*[
            channel.search(bundle, 10, "safety", None)
            for channel in channels
        ])

    dense_results, kiwi_results, bm42_results = asyncio.run(run_channels())

    for results in (dense_results, kiwi_results, bm42_results):
        chunk_id, score, payload = results[0]
        assert isinstance(chunk_id, str)
        assert isinstance(score, float)
        assert isinstance(payload, dict)

    assert repository.bm25_query == bundle.kiwi_bm25_query
    assert kiwi_results[0][0] == "law-doc"


def test_merge_rrf_accepts_two_or_three_channel_dictionaries():
    dense = [
        ("shared", 0.9, {"text": "shared"}),
        ("dense-only", 0.8, {"text": "dense"}),
    ]
    kiwi = [
        ("kiwi-only", 2.0, {"text": "kiwi"}),
        ("shared", 1.5, {"text": "shared"}),
    ]
    bm42 = [("bm42-only", 0.7, {"text": "bm42"})]

    two_channel = _merge_rrf({"dense": dense, "kiwi_bm25": kiwi})
    three_channel = _merge_rrf({
        "dense": dense,
        "kiwi_bm25": kiwi,
        "bm42": bm42,
    })

    assert two_channel[0][0] == "shared"
    assert {item[0] for item in three_channel} == {
        "shared", "dense-only", "kiwi-only", "bm42-only"
    }


def test_dense_kiwi_profile_returns_legal_reference_from_kiwi_bm25():
    from rank_bm25 import BM25Okapi

    from app.utils.kiwi_tokenizer import tokenize_corpus, tokenize_query_for_bm25

    documents = [
        (
            "law-17-3",
            "산업안전보건법 제17조의3에 따른 안전관리자 선임 기준",
        ),
        ("general", "사업장 일반 안전교육 운영 안내"),
        ("manual", "관리 시스템 사용자 메뉴 설명서"),
    ]

    class InMemoryRepository:
        def search_similar(self, **kwargs):
            return [("general", 0.9, {"text": documents[1][1]})]

        def search_bm25(self, **kwargs):
            query_tokens = tokenize_query_for_bm25(kwargs["query_text"])
            corpus = [tokenize_corpus(text) for _, text in documents]
            scores = BM25Okapi(corpus, k1=1.2, b=0.5).get_scores(query_tokens)
            ranked = sorted(
                zip(documents, scores.tolist()),
                key=lambda item: item[1],
                reverse=True,
            )
            return [
                (document_id, float(score), {"text": text})
                for ((document_id, text), score) in ranked
                if score > 0
            ][:kwargs["top_k"]]

    class UnusedEmbeddingClient:
        async def embed_query(self, query):
            raise AssertionError("사전 계산 임베딩을 사용해야 합니다")

    repository = InMemoryRepository()
    orchestrator = RetrievalOrchestrator({
        "dense": lambda: DenseChannel(repository, UnusedEmbeddingClient()),
        "kiwi_bm25": lambda: KiwiBm25Channel(repository),
    })
    profile = get_retrieval_profile("dense_kiwi")

    async def run():
        channel_results = await orchestrator.search(
            profile=profile,
            query_bundle=_query_bundle(),
            top_k=10,
            collection_name="safety",
            filters=None,
        )
        return channel_results, orchestrator.merge(channel_results, profile)

    channel_results, merged = asyncio.run(run())

    assert channel_results["kiwi_bm25"][0][0] == "law-17-3"
    assert "law-17-3" in {chunk_id for chunk_id, _, _ in merged}


# ── Task 6: classify_query_type + Weighted RRF ────────────────────────────────

def test_classify_query_type_legal_reference():
    result = classify_query_type({
        "matched_patterns": {"law_references": ["제17조의3"]},
    })
    assert result == QueryType.LEGAL_REFERENCE


def test_classify_query_type_menu_manual():
    result = classify_query_type({
        "matched_patterns": {"law_references": []},
        "extracted_keywords": ["화면", "버튼", "메뉴"],
    })
    assert result == QueryType.MENU_MANUAL


def test_classify_query_type_incident_narrative():
    result = classify_query_type({
        "extracted_keywords": ["사고", "현장", "작업자", "피해"],
    })
    assert result == QueryType.INCIDENT_NARRATIVE


def test_classify_query_type_concept_explanation_is_default():
    # 힌트 키워드 없을 때 기본값
    assert classify_query_type({}) == QueryType.CONCEPT_EXPLANATION
    assert classify_query_type({"extracted_keywords": ["위험성평가", "기준"]}) == QueryType.CONCEPT_EXPLANATION


def test_classify_query_type_law_reference_takes_priority_over_hint_terms():
    # law_references가 있으면 다른 힌트보다 우선
    result = classify_query_type({
        "matched_patterns": {"law_references": ["제3조"]},
        "extracted_keywords": ["사고", "화면"],
    })
    assert result == QueryType.LEGAL_REFERENCE


def test_rrf_weights_table_covers_all_query_types():
    for qt in QueryType:
        assert qt in RRF_WEIGHTS, f"RRF_WEIGHTS에 {qt} 미등록"
        weights = RRF_WEIGHTS[qt]
        assert "dense" in weights
        assert "kiwi_bm25" in weights


def test_weighted_rrf_legal_reference_boosts_kiwi_over_dense():
    # kiwi가 1위, dense가 2위인 doc_A  vs  dense가 1위인 doc_B
    channel_results = {
        "kiwi_bm25": [("doc_A", 0.9, {}), ("doc_B", 0.5, {})],
        "dense":     [("doc_B", 0.9, {}), ("doc_A", 0.5, {})],
    }
    legal_weights = RRF_WEIGHTS[QueryType.LEGAL_REFERENCE]
    merged = _merge_rrf(channel_results, weights=legal_weights)
    # kiwi_bm25 가중치(1.5)가 높으므로 kiwi에서 1위인 doc_A가 최상위
    assert merged[0][0] == "doc_A"


def test_weighted_rrf_concept_explanation_boosts_dense_over_kiwi():
    channel_results = {
        "kiwi_bm25": [("doc_A", 0.9, {}), ("doc_B", 0.5, {})],
        "dense":     [("doc_B", 0.9, {}), ("doc_A", 0.5, {})],
    }
    concept_weights = RRF_WEIGHTS[QueryType.CONCEPT_EXPLANATION]
    merged = _merge_rrf(channel_results, weights=concept_weights)
    # dense 가중치(1.5)가 높으므로 dense에서 1위인 doc_B가 최상위
    assert merged[0][0] == "doc_B"


def test_orchestrator_merge_weights_override_profile_weights():
    orchestrator = RetrievalOrchestrator({})
    channel_results = {
        "kiwi_bm25": [("doc_A", 0.9, {}), ("doc_B", 0.5, {})],
        "dense":     [("doc_B", 0.9, {}), ("doc_A", 0.5, {})],
    }
    profile = get_retrieval_profile("dense_kiwi")  # weights: dense=1.0, kiwi=1.0

    # weights 미지정 → 프로필 기본(1.0/1.0) → 타이 브레이크로 순서 결정
    default_merged = orchestrator.merge(channel_results, profile)

    # weights 지정 → kiwi 우세 → doc_A 1위
    kiwi_heavy = {"kiwi_bm25": 2.0, "dense": 0.5}
    kiwi_merged = orchestrator.merge(channel_results, profile, weights=kiwi_heavy)
    assert kiwi_merged[0][0] == "doc_A"

    # weights 지정 → dense 우세 → doc_B 1위
    dense_heavy = {"dense": 2.0, "kiwi_bm25": 0.5}
    dense_merged = orchestrator.merge(channel_results, profile, weights=dense_heavy)
    assert dense_merged[0][0] == "doc_B"


# ── Task 7: RetrievalConfig / get_retrieval_config ────────────────────────────

def test_retrieval_config_defaults():
    cfg = RetrievalConfig()
    assert cfg.candidate_top_k == 40
    assert cfg.rerank_top_k == 10
    assert cfg.context_top_k == 6


def test_retrieval_config_from_legacy_top_k():
    cfg = RetrievalConfig.from_legacy_top_k(10)
    assert cfg.candidate_top_k == 40
    assert cfg.rerank_top_k == 10
    assert cfg.context_top_k == 5

    cfg_small = RetrievalConfig.from_legacy_top_k(1)
    assert cfg_small.candidate_top_k == 4
    assert cfg_small.rerank_top_k == 1
    assert cfg_small.context_top_k == 1  # max(1, 0)


def test_get_retrieval_config_uses_legacy_top_k_when_present():
    class MockSettings:
        candidate_top_k = 40
        rerank_top_k = 10
        context_top_k = 6

    state = {"top_k": 5}
    cfg = get_retrieval_config(state, MockSettings())
    assert cfg.candidate_top_k == 20   # 5 * 4
    assert cfg.rerank_top_k == 5
    assert cfg.context_top_k == 2      # max(1, 5//2)


# 2026.07.16(sooyeon.choi) 수정 - 설정 필드명 통합(reranker_top_k, 2026.07.07) 미반영 stale 테스트 수정
def test_get_retrieval_config_uses_settings_when_no_legacy_top_k():
    class MockSettings:
        candidate_top_k = 30
        reranker_top_k = 8
        context_top_k = 4

    state = {}
    cfg = get_retrieval_config(state, MockSettings())
    assert cfg.candidate_top_k == 30
    assert cfg.rerank_top_k == 8
    assert cfg.context_top_k == 4


# 2026.07.16(sooyeon.choi) 수정 - 설정 필드명 통합(reranker_top_k) 미반영 stale 테스트 수정
def test_get_retrieval_config_top_k_zero_falls_back_to_settings():
    # top_k=0 은 falsy → settings 사용
    class MockSettings:
        candidate_top_k = 40
        reranker_top_k = 10
        context_top_k = 6

    state = {"top_k": 0}
    cfg = get_retrieval_config(state, MockSettings())
    assert cfg.candidate_top_k == 40


# 2026.07.16(sooyeon.choi) 추가 - B4: fallback retrieval_override 우선순위/확장 규칙 테스트
def test_get_retrieval_config_prefers_retrieval_override():
    class MockSettings:
        candidate_top_k = 40
        reranker_top_k = 10
        context_top_k = 6

    state = {
        "top_k": 5,  # legacy 값이 있어도 override가 우선
        "retrieval_override": {
            "candidate_top_k": 80,
            "rerank_top_k": 20,
            "context_top_k": 6,
        },
    }
    cfg = get_retrieval_config(state, MockSettings())
    assert cfg.candidate_top_k == 80
    assert cfg.rerank_top_k == 20
    assert cfg.context_top_k == 6


def test_expand_retrieval_config_for_fallback_doubles_with_caps():
    class MockSettings:
        candidate_top_k = 40
        reranker_top_k = 10
        context_top_k = 6
        max_query_top_k = 20

    base = RetrievalConfig(candidate_top_k=40, rerank_top_k=10, context_top_k=6)
    expanded = expand_retrieval_config_for_fallback(base, MockSettings())
    assert expanded["candidate_top_k"] == 80    # 2배
    assert expanded["rerank_top_k"] == 20       # 2배 (max_query_top_k 이내)
    assert expanded["context_top_k"] == 6       # 유지

    # 상한 검증: rerank는 max_query_top_k, candidate는 settings.candidate_top_k*4
    big = RetrievalConfig(candidate_top_k=100, rerank_top_k=15, context_top_k=6)
    capped = expand_retrieval_config_for_fallback(big, MockSettings())
    assert capped["candidate_top_k"] == 160     # min(200, 40*4)
    assert capped["rerank_top_k"] == 20         # min(30, 20)


# ── Task 8: apply_soft_boost ──────────────────────────────────────────────────

# 2026.07.16(sooyeon.choi) 수정 - 가산식(+0.05) → 비율식(×1.05) boost 전환(2026.07.07)
#   미반영 stale 테스트 수정
def test_apply_soft_boost_keyword_match_increases_score():
    results = [
        ("doc_A", 0.50, {"keywords": ["안전관리자"], "tags": []}),
        ("doc_B", 0.48, {"keywords": ["위험성평가"], "tags": ["안전관리자"]}),
        ("doc_C", 0.45, {"keywords": [], "tags": []}),
    ]
    boosted = apply_soft_boost(results, {"keywords": ["안전관리자"]})

    scores = {cid: score for cid, score, _ in boosted}
    assert scores["doc_A"] == pytest.approx(0.50 * 1.05)   # ×1.05 keywords
    assert scores["doc_B"] == pytest.approx(0.48 * 1.03)   # ×1.03 tags
    assert scores["doc_C"] == pytest.approx(0.45)          # boost 없음


# 2026.07.16(sooyeon.choi) 수정 - 비율식 boost 기준으로 추월 케이스 값 조정
def test_apply_soft_boost_reorders_results_when_boost_closes_gap():
    # doc_B가 keyword 일치로 doc_A를 추월하는 케이스
    results = [
        ("doc_A", 0.50, {"keywords": []}),
        ("doc_B", 0.48, {"keywords": ["안전관리자"]}),
    ]
    boosted = apply_soft_boost(results, {"keywords": ["안전관리자"]})
    # doc_B: 0.48 × 1.05 = 0.504 > doc_A: 0.50
    assert boosted[0][0] == "doc_B"


def test_apply_soft_boost_no_keywords_returns_original_order():
    results = [
        ("doc_A", 0.9, {"keywords": ["안전관리자"]}),
        ("doc_B", 0.8, {"keywords": ["위험성평가"]}),
    ]
    boosted = apply_soft_boost(results, {"keywords": []})
    assert boosted[0][0] == "doc_A"
    assert boosted[0][1] == pytest.approx(0.9)


def test_apply_soft_boost_never_produces_zero_results():
    # 일치 항목 없어도 0건이 되어선 안 됨
    results = [("doc_X", 0.6, {"keywords": ["무관한키워드"]})]
    boosted = apply_soft_boost(results, {"keywords": ["안전관리자"]})
    assert len(boosted) == 1


def test_apply_soft_boost_empty_results_returns_empty():
    assert apply_soft_boost([], {"keywords": ["안전관리자"]}) == []


# 2026.07.16(sooyeon.choi) 수정 - 비율식 boost 기준으로 기대값 조정
def test_apply_soft_boost_document_type_match():
    results = [
        ("doc_A", 0.50, {"document_type": "manual", "keywords": []}),
        ("doc_B", 0.52, {"document_type": "law", "keywords": []}),
    ]
    # inferred_type=manual → doc_A ×1.1 → 0.55 > doc_B 0.52
    boosted = apply_soft_boost(results, {"keywords": [], "inferred_type": "manual"})
    assert boosted[0][0] == "doc_A"
    assert boosted[0][1] == pytest.approx(0.50 * 1.1)

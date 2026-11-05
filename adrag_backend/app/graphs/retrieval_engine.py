"""검색 채널 구성, 실행 및 RRF 병합 로직."""

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Mapping, Tuple

from app.graphs.state import PipelineState
from app.utils.kiwi_tokenizer import normalize_query

SearchResult = Tuple[str, float, Dict[str, Any]]


# ── Task 6: 질의 유형 분류 ────────────────────────────────────────────────────

class QueryType(Enum):
    LEGAL_REFERENCE = "legal_reference"          # 조문/법령/약어/별표 질의
    CONCEPT_EXPLANATION = "concept_explanation"  # 개념 설명/요약 질의
    MENU_MANUAL = "menu_manual"                  # 매뉴얼/화면명/메뉴명 질의
    INCIDENT_NARRATIVE = "incident_narrative"    # 사고 사례/서술형 질의


# 질의 유형별 RRF 채널 가중치 — 초기값이며 평가셋 기반 튜닝 대상
RRF_WEIGHTS: Dict[QueryType, Dict[str, float]] = {
    QueryType.LEGAL_REFERENCE:      {"kiwi_bm25": 1.5, "dense": 0.7, "bm42": 1.0},
    QueryType.CONCEPT_EXPLANATION:  {"dense": 1.5, "kiwi_bm25": 0.7, "bm42": 1.0},
    QueryType.MENU_MANUAL:          {"kiwi_bm25": 1.5, "dense": 0.8, "bm42": 1.2},
    QueryType.INCIDENT_NARRATIVE:   {"dense": 1.5, "kiwi_bm25": 0.8, "bm42": 1.0},
}

_MENU_HINT_TERMS = frozenset({"메뉴", "화면", "버튼", "탭", "페이지", "기능", "클릭", "선택"})
_NARRATIVE_HINT_TERMS = frozenset({"사고", "재해", "사례", "발생", "현장", "작업자", "피해", "원인", "경위"})


def classify_query_type(preprocess_result: Dict[str, Any], settings=None) -> QueryType:
    """전처리 결과로 질의 유형을 분류한다."""
    matched_patterns = preprocess_result.get("matched_patterns") or {}
    if matched_patterns.get("law_references"):
        return QueryType.LEGAL_REFERENCE

    expanded_terms = set(preprocess_result.get("expanded_terms") or [])
    extracted_keywords = set(preprocess_result.get("extracted_keywords") or [])
    normalized = preprocess_result.get("normalized_query") or ""
    all_terms = expanded_terms | extracted_keywords | set(normalized.split())

    menu_terms = frozenset(settings.menu_hint_terms) if settings else _MENU_HINT_TERMS
    narrative_terms = frozenset(settings.narrative_hint_terms) if settings else _NARRATIVE_HINT_TERMS
    if all_terms & menu_terms:
        return QueryType.MENU_MANUAL

    if all_terms & narrative_terms:
        return QueryType.INCIDENT_NARRATIVE

    return QueryType.CONCEPT_EXPLANATION


# 2026.06.29(sooyeon.choi) 수정 - boolean flag 대신 실행할 검색 채널 조합을 프로필로 정의
RETRIEVAL_PROFILES: Dict[str, Dict[str, Any]] = {
    "dense_kiwi": {
        "channels": ["dense", "kiwi_bm25"],
        "weights": {"dense": 1.0, "kiwi_bm25": 1.0},
    },
    "dense_bm42": {
        "channels": ["dense", "bm42"],
        "weights": {"dense": 1.0, "bm42": 1.0},
    },
    "dense_kiwi_bm42": {
        "channels": ["dense", "kiwi_bm25", "bm42"],
        "weights": {"dense": 1.0, "kiwi_bm25": 1.2, "bm42": 0.8},
    },
}


def get_retrieval_profile(name: str) -> Dict[str, Any]:
    """설정 이름에 해당하는 검색 프로필을 반환한다."""
    try:
        return RETRIEVAL_PROFILES[name]
    except KeyError as exc:
        supported = ", ".join(RETRIEVAL_PROFILES)
        raise ValueError(
            f"지원하지 않는 retrieval_profile입니다: {name} (지원: {supported})"
        ) from exc


# ── Task 7: 3단계 top_k 설정 ─────────────────────────────────────────────────

@dataclass(frozen=True)
class RetrievalConfig:
    """retrieve → rerank → assemble_context 단계별 독립 top_k 설정."""

    candidate_top_k: int = 40   # 검색 후보 수 (retrieve 단계)
    rerank_top_k: int = 10      # 재랭킹 대상 수 (rerank 단계)
    context_top_k: int = 6      # 최종 LLM 컨텍스트 포함 수 (assemble_context 단계)

    @classmethod
    def from_legacy_top_k(cls, top_k: int) -> "RetrievalConfig":
        """단일 top_k → 3단계 자동 매핑 (하위 호환)."""
        return cls(
            candidate_top_k=top_k * 4,
            rerank_top_k=top_k,
            context_top_k=max(1, top_k // 2),
        )


def get_retrieval_config(state: PipelineState, settings: Any) -> RetrievalConfig:
    """state의 override/legacy top_k 또는 settings 3단계 값에서 RetrievalConfig를 생성한다.

    우선순위 (2026.07.16(sooyeon.choi) 수정 - B4):
      1. retrieval_override — fallback 재시도가 현재 유효 설정 기준으로 계산한 명시 배분
      2. legacy top_k      — 요청에서 명시한 단일 top_k (from_legacy_top_k 자동 매핑)
      3. settings          — 단계별 기본 설정
    기존에는 fallback이 legacy top_k에 값을 써서 재시도부터 candidate=×4, context=×0.5로
    배분 체계가 변질되던 것을 명시 override로 분리했다.
    """
    override = state.get("retrieval_override")
    if override:
        return RetrievalConfig(
            candidate_top_k=override["candidate_top_k"],
            rerank_top_k=override["rerank_top_k"],
            context_top_k=override["context_top_k"],
        )
    legacy_top_k = state.get("top_k")
    if legacy_top_k:
        return RetrievalConfig.from_legacy_top_k(legacy_top_k)
    return RetrievalConfig(
        candidate_top_k=settings.candidate_top_k,
        rerank_top_k=settings.reranker_top_k,
        context_top_k=settings.context_top_k,
    )


# 2026.07.16(sooyeon.choi) 추가 - fallback 재시도용 검색 범위 확장 계산 (B4)
#   fallback_handler(그래프)와 query_stream(스트리밍)이 동일 확장 규칙을 공유한다.
#   candidate/rerank만 2배 확장하고 context는 유지해 배분 의미를 보존한다.
def expand_retrieval_config_for_fallback(
    config: RetrievalConfig, settings: Any
) -> Dict[str, int]:
    """현재 유효 설정을 기준으로 확장된 retrieval_override dict를 반환한다."""
    return {
        "candidate_top_k": min(config.candidate_top_k * 2, settings.candidate_top_k * 4),
        "rerank_top_k": min(config.rerank_top_k * 2, settings.max_query_top_k),
        "context_top_k": config.context_top_k,
    }


@dataclass(frozen=True)
class QueryBundle:
    """한 번의 질의를 검색 채널별 입력으로 가공한 값."""

    original_query: str
    rewritten_queries: List[str]
    rewritten_query_embeddings: List[List[float]] | None
    normalized_query: str
    expanded_terms: List[str]
    law_references: List[str]
    extracted_keywords: List[str]
    dense_queries: List[str]
    kiwi_bm25_query: str
    bm42_queries: List[str]


def _unique_strings(values: List[str]) -> List[str]:
    seen: set[str] = set()
    result: List[str] = []
    for value in values:
        value = value.strip()
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def build_query_bundle(state: PipelineState) -> QueryBundle:
    """PipelineState를 Dense, Kiwi BM25, BM42 전용 query로 분리한다."""
    # 2026.06.29(sooyeon.choi) 수정 - 같은 원본 질의를 채널 특성에 맞는 서로 다른 문자열로 구성
    original_query = state["original_query"]
    preprocess_result = state.get("preprocess_result") or {}
    matched_patterns = preprocess_result.get("matched_patterns") or {}

    rewritten_queries = _unique_strings(
        list(state.get("rewritten_queries") or [original_query])
    )
    if not rewritten_queries:
        rewritten_queries = [original_query]

    embeddings = state.get("rewritten_query_embeddings")
    if not embeddings or len(embeddings) != len(rewritten_queries):
        embeddings = None

    normalized = preprocess_result.get("normalized_query") or normalize_query(
        original_query
    )
    expanded_terms = _unique_strings(list(preprocess_result.get("expanded_terms") or []))
    law_references = _unique_strings(list(matched_patterns.get("law_references") or []))
    extracted_keywords = _unique_strings(
        list(preprocess_result.get("extracted_keywords") or [])
    )

    kiwi_parts = _unique_strings(
        [normalized, *expanded_terms, *law_references, *extracted_keywords]
    )
    bm42_queries = _unique_strings(
        [original_query, normalized, *rewritten_queries, *expanded_terms]
    )

    return QueryBundle(
        original_query=original_query,
        rewritten_queries=rewritten_queries,
        rewritten_query_embeddings=embeddings,
        normalized_query=normalized,
        expanded_terms=expanded_terms,
        law_references=law_references,
        extracted_keywords=extracted_keywords,
        dense_queries=rewritten_queries,
        kiwi_bm25_query=" ".join(kiwi_parts),
        bm42_queries=bm42_queries,
    )


class RetrievalChannel(ABC):
    """모든 검색 채널이 따르는 공통 인터페이스."""

    name: str

    @abstractmethod
    async def search(
        self,
        query_bundle: QueryBundle,
        top_k: int,
        collection_name: str,
        filters: Dict[str, Any] | None,
        context: Dict[str, Any] | None = None,
    ) -> List[SearchResult]:
        """검색 결과를 (chunk_id, score, payload) 형식으로 반환한다."""


def _deduplicate_results(results: List[List[SearchResult]]) -> List[SearchResult]:
    best: Dict[str, SearchResult] = {}
    for result_list in results:
        for chunk_id, score, payload in result_list:
            cid = str(chunk_id)
            if cid not in best or score > best[cid][1]:
                best[cid] = (cid, score, payload)
    return sorted(best.values(), key=lambda item: item[1], reverse=True)


class DenseChannel(RetrievalChannel):
    """임베딩과 Qdrant dense vector를 사용하는 검색 채널."""

    name = "dense"

    def __init__(self, vector_repo: Any, embedding_client: Any) -> None:
        self._vector_repo = vector_repo
        self._embedding_client = embedding_client

    async def search(
        self,
        query_bundle: QueryBundle,
        top_k: int,
        collection_name: str,
        filters: Dict[str, Any] | None,
        context: Dict[str, Any] | None = None,
    ) -> List[SearchResult]:
        async def _single(query: str, embedding: List[float] | None):
            query_vector = embedding
            if query_vector is None:
                query_vector = await self._embedding_client.embed_query(query)
            return await asyncio.to_thread(
                self._vector_repo.search_similar,
                query_vector=query_vector,
                top_k=top_k,
                collection_name=collection_name,
                filters=filters,
            )

        embeddings = query_bundle.rewritten_query_embeddings
        tasks = [
            _single(query, embeddings[index] if embeddings else None)
            for index, query in enumerate(query_bundle.dense_queries)
        ]
        return _deduplicate_results(await asyncio.gather(*tasks))


class KiwiBm25Channel(RetrievalChannel):
    """Kiwi로 정제한 query와 Python BM25Okapi를 사용하는 검색 채널."""

    name = "kiwi_bm25"

    def __init__(self, vector_repo: Any) -> None:
        self._vector_repo = vector_repo

    async def search(
        self,
        query_bundle: QueryBundle,
        top_k: int,
        collection_name: str,
        filters: Dict[str, Any] | None,
        context: Dict[str, Any] | None = None,
    ) -> List[SearchResult]:
        # 2026.06.29(sooyeon.choi) 수정 - Dense 문장 대신 전처리 힌트를 합친 BM25 전용 query 전달
        return await asyncio.to_thread(
            self._vector_repo.search_bm25,
            query_text=query_bundle.kiwi_bm25_query,
            top_k=top_k,
            collection_name=collection_name,
            filters=filters,
        )


class Bm42Channel(RetrievalChannel):
    """기존 BM42/SPLADE sparse vector 검색을 보존하는 선택 채널."""

    name = "bm42"

    def __init__(self, vector_repo: Any, sparse_encoder: Any) -> None:
        self._vector_repo = vector_repo
        self._sparse_encoder = sparse_encoder

    async def search(
        self,
        query_bundle: QueryBundle,
        top_k: int,
        collection_name: str,
        filters: Dict[str, Any] | None,
        context: Dict[str, Any] | None = None,
    ) -> List[SearchResult]:
        async def _single(query: str) -> List[SearchResult]:
            sparse_vector = await self._sparse_encoder.encode_single(query)
            if sparse_vector is None:
                return []
            return await asyncio.to_thread(
                self._vector_repo.search_sparse,
                sparse_indices=sparse_vector.indices,
                sparse_values=sparse_vector.values,
                top_k=top_k,
                collection_name=collection_name,
                filters=filters,
            )

        return _deduplicate_results(
            await asyncio.gather(
                *[_single(query) for query in query_bundle.bm42_queries]
            )
        )


class RetrievalOrchestrator:
    """프로필에 지정된 채널만 병렬 실행한다."""

    def __init__(
        self,
        channel_factories: Mapping[str, Callable[[], RetrievalChannel]],
    ) -> None:
        self._channel_factories = dict(channel_factories)
        self._channels: Dict[str, RetrievalChannel] = {}

    def _get_channel(self, name: str) -> RetrievalChannel:
        if name not in self._channel_factories:
            raise ValueError(f"등록되지 않은 검색 채널입니다: {name}")
        if name not in self._channels:
            self._channels[name] = self._channel_factories[name]()
        return self._channels[name]

    async def search(
        self,
        profile: Dict[str, Any],
        query_bundle: QueryBundle,
        top_k: int,
        collection_name: str,
        filters: Dict[str, Any] | None,
        context: Dict[str, Any] | None = None,
    ) -> Dict[str, List[SearchResult]]:
        # 2026.06.29(sooyeon.choi) 수정 - 기본 프로필에서는 BM42 객체도 생성하지 않는 지연 채널 선택
        channel_names = list(profile["channels"])
        channels = [self._get_channel(name) for name in channel_names]
        results = await asyncio.gather(
            *[
                channel.search(
                    query_bundle=query_bundle,
                    top_k=top_k,
                    collection_name=collection_name,
                    filters=filters,
                    context=context,
                )
                for channel in channels
            ]
        )
        return dict(zip(channel_names, results))

    def merge(
        self,
        channel_results: Dict[str, List[SearchResult]],
        profile: Dict[str, Any],
        weights: Dict[str, float] | None = None,
        k: int = 60,
    ) -> List[SearchResult]:
        """프로필 가중치로 채널 결과를 RRF 병합한다. weights가 주어지면 프로필 가중치를 덮어쓴다."""
        effective_weights = weights if weights is not None else profile.get("weights")
        return _merge_rrf(channel_results, weights=effective_weights, k=k)


def create_retrieval_orchestrator(
    vector_repo: Any,
    embedding_client: Any,
    sparse_encoder_factory: Callable[[], Any],
) -> RetrievalOrchestrator:
    """애플리케이션 기본 검색 채널 팩토리로 오케스트레이터를 생성한다."""
    return RetrievalOrchestrator({
        "dense": lambda: DenseChannel(vector_repo, embedding_client),
        "kiwi_bm25": lambda: KiwiBm25Channel(vector_repo),
        "bm42": lambda: Bm42Channel(vector_repo, sparse_encoder_factory()),
    })


def _merge_rrf(
    channel_results: Dict[str, List[SearchResult]],
    weights: Dict[str, float] | None = None,
    k: int = 60,
) -> List[SearchResult]:
    """채널 수와 무관하게 Reciprocal Rank Fusion으로 결과를 병합한다."""
    # 2026.06.29(sooyeon.choi) 수정 - Dense/BM42 2개 인자 대신 채널명→결과 딕셔너리 입력 사용
    effective_weights = weights or {
        channel_name: 1.0 for channel_name in channel_results
    }
    rrf_scores: Dict[str, float] = {}
    payloads: Dict[str, Dict[str, Any]] = {}

    for channel_name, results in channel_results.items():
        weight = effective_weights.get(channel_name, 1.0)
        for rank, (chunk_id, _, payload) in enumerate(results, start=1):
            cid = str(chunk_id)
            rrf_scores[cid] = (
                rrf_scores.get(cid, 0.0) + weight / (k + rank)
            )
            payloads.setdefault(cid, payload)

    merged = sorted(rrf_scores.items(), key=lambda item: item[1], reverse=True)
    return [(cid, score, payloads[cid]) for cid, score in merged]


# ── Task 8: 메타데이터 soft boost ─────────────────────────────────────────────

def apply_soft_boost(
    results: List[SearchResult],
    query_metadata: Dict[str, Any],
    settings=None,
) -> List[SearchResult]:
    """청크 메타데이터와 질의 메타데이터 일치도에 따라 점수를 가산하고 재정렬한다.

    hard filter가 아니라 점수 가산이므로 0건 결과가 발생하지 않는다.
    boost 수치는 초기값이며 평가셋 기반 튜닝 대상이다.
    """
    query_keywords = set(query_metadata.get("keywords") or [])
    query_type = query_metadata.get("inferred_type")
    boosted: List[SearchResult] = []
    for chunk_id, score, payload in results:
        # 2026.07.07(sooyeon.choi) 수정 - 작은 RRF 점수를 고정 가산값이 덮지 않도록 비율 boost 적용
        multiplier = 1.0
        if query_keywords:
            if set(payload.get("keywords") or []) & query_keywords:
                multiplier += settings.soft_boost_keyword if settings else 0.05
            if set(payload.get("tags") or []) & query_keywords:
                multiplier += settings.soft_boost_tag if settings else 0.03
        if query_type:
            if payload.get("document_type") == query_type:
                multiplier += settings.soft_boost_document_type if settings else 0.1
            if payload.get("intent") == query_type:
                multiplier += settings.soft_boost_intent if settings else 0.05
        boosted.append((chunk_id, score * multiplier, payload))
    return sorted(boosted, key=lambda item: item[1], reverse=True)

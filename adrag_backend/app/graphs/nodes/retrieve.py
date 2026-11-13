"""
hybrid 검색 노드.

2026.06.29(sooyeon.choi) 수정 - 기본(Dense+BM25) 기반 검색 오케스트레이터로 전환.
  - 기본은 Dense + Kiwi BM25, BM42는 선택 채널로 보존
  - 그래프의 retrieve -> rerank 경계는 유지

공통 동작:
  - rewritten_queries 각각에 대해 검색 수행
  - chunk_id 기준 중복 제거 후 score 내림차순 정렬하여 반환
"""

import asyncio
import json
from typing import List

from app.clients.kiwi_bm25_encoder import KiwiBm25Encoder
from app.clients.sparse_encoder import SparseEncoder
from app.core.config import get_settings
# 2026.07.16(sooyeon.choi) 수정 - 모듈 전역 싱글턴 6개를 컨테이너 조립으로 단일화 (3단계)
from app.core.container import get_container
from app.graphs.retrieval_engine import (
    RetrievalOrchestrator,
    RRF_WEIGHTS,
    apply_soft_boost,
    build_query_bundle,
    classify_query_type,
    # 2026.11.11(sooyeon.choi) 추가 - 가중치 프로필·원문 질의 비중
    dense_query_weights,
    get_rrf_weights,
    get_retrieval_config,
    get_retrieval_profile,
)
from app.graphs.state import ChunkResult, PipelineState
from app.graphs.dependencies import GraphDependencies
from app.graphs.utils import chunk_log_payload, rag_diag, timed_node
from app.interfaces import EmbeddingProvider, VectorStore
from app.services.collection_service import CollectionService
from app.utils.log.log import LoggingLogger

# 로거 초기화
# 2026.07.16(sooyeon.choi) 수정 - 모듈별 named logger 적용
logger = LoggingLogger().getLogger(__name__)


# 2026.04.21(sooyeon.choi) 추가 - 클라이언트 싱글톤: 매 요청마다 Qdrant 연결·클라이언트 재생성 방지
# 2026.07.16(sooyeon.choi) 수정 - 조립 지점을 app/core/container.py로 이동 (3단계)
#   아래 getter들은 기존 호출부 호환을 위해 유지하며 컨테이너에 위임한다.
#   구현 교체는 컨테이너에서 수행한다.

def get_embedding_client() -> EmbeddingProvider:
    return get_container().embedding


def get_vector_repo() -> VectorStore:
    return get_container().vector_store


def get_sparse_encoder() -> SparseEncoder:
    return get_container().sparse_encoder


# 2026.07.07(sooyeon.choi) 수정 - Qdrant hybrid query용 Kiwi BM25 query 생성
def get_kiwi_bm25_encoder() -> KiwiBm25Encoder:
    """Qdrant BM25 적재/검색 정책을 공유하는 인코더 싱글톤 반환."""
    return get_container().kiwi_bm25_encoder


def get_collection_service() -> CollectionService:
    return get_container().collection_service


def get_retrieval_orchestrator() -> RetrievalOrchestrator:
    """검색 채널을 지연 생성하는 오케스트레이터 싱글톤 반환"""
    return get_container().retrieval_orchestrator


# 2026.07.07(sooyeon.choi) 수정 - 별도 검색/외부 RRF를 단일 Query API 호출로 전환
async def _search_qdrant_hybrid(
    query_bundle,
    collection_name: str,
    filters,
    top_k: int,
    query_type,
    settings,
    container=None,
):
    """Dense와 Kiwi BM25를 Qdrant 서버에서 weighted RRF로 병합한다."""
    # 2026.07.08(sooyeon.choi) 수정 - 첫 rewrite만 사용하던 누락을 제거하고 전체 Dense query 반영
    dense_queries = query_bundle.dense_queries
    embeddings = query_bundle.rewritten_query_embeddings
    if embeddings:
        dense_vectors = embeddings
    else:
        dense_vectors = await asyncio.gather(
            *[(container.embedding if container else get_embedding_client()).embed_query(query) for query in dense_queries]
        )
    sparse_query = await asyncio.to_thread(
        (container.kiwi_bm25_encoder if container else get_kiwi_bm25_encoder()).encode_query,
        query_bundle.kiwi_bm25_query,
    )
    # 2026.11.11(sooyeon.choi) 수정 - 가중치는 QUERY_TYPE_PROFILE 표에서, Dense는 원문 질의 비중을 반영해 질의별로 나눈다
    weights = get_rrf_weights(query_type, settings)
    dense_weight = weights.get("dense", 1.0)
    share = getattr(settings, "dense_original_query_share", None)
    hybrid_kwargs = {}
    if share is not None:
        hybrid_kwargs["dense_weights"] = dense_query_weights(
            list(dense_queries), query_bundle.original_query, dense_weight, share
        )
    return await asyncio.to_thread(
        (container.vector_store if container else get_vector_repo()).search_hybrid,
        dense_vectors=dense_vectors,
        sparse_query=sparse_query,
        top_k=top_k,
        collection_name=collection_name,
        filters=filters,
        dense_prefetch_k=max(top_k, settings.dense_prefetch_k),
        sparse_prefetch_k=max(top_k, settings.sparse_prefetch_k),
        dense_weight=dense_weight,
        sparse_weight=weights.get("kiwi_bm25", 1.0),
        rrf_k=settings.hybrid_rrf_k,
        **hybrid_kwargs,
    )


# ── 메인 노드 ─────────────────────────────────────────────────────────────────

@timed_node("retrieve")
async def retrieve(state: PipelineState, deps: GraphDependencies | None = None) -> dict:
    """설정된 검색 프로필의 채널을 실행하고 RRF로 병합"""
    settings = deps.settings if deps else get_settings()

    # 2026.04.01(sooyeon.choi) 수정 - 멀티컬렉션 관리 기능 추가: 선택된 컬렉션에서만 검색
    collection_name = state.get("collection_name")

    if not collection_name:
        logger.warning("[RAG][node=retrieve] collection 미지정")
        # 2026.06.19(sooyeon.choi) 추가 - 검색 실패 결과 코드 기록
        return {
            "retrieved_chunks": [],
            "error": "검색할 컬렉션을 선택해주세요",
            "outcome_code": "retrieval_error",
            "error_message_type": "collection_unavailable",  # 2026.11.11(sooyeon.choi) 추가
        }

    # 2026.04.21(sooyeon.choi) 수정 - CollectionService 싱글톤으로 교체
    collection_service = deps.container.collection_service if deps else get_collection_service()
    if not collection_service.validate_collection_name(collection_name):
        logger.error("[RAG][node=retrieve] 등록되지 않은 컬렉션: %s", collection_name)
        return {
            "retrieved_chunks": [],
            "error": "등록되지 않은 컬렉션입니다",
            "outcome_code": "retrieval_error",
            "error_message_type": "collection_unavailable",  # 2026.11.11(sooyeon.choi) 추가
        }

    # 2026.06.29(sooyeon.choi) 추가 - Task 7: state의 legacy top_k 또는 settings 3단계 top_k에서 RetrievalConfig 생성
    preprocess_result = state.get("preprocess_result") or {}
    retrieval_config = get_retrieval_config(state, settings)
    top_k = retrieval_config.candidate_top_k
    applied_filters = state.get("filters")
    rrf_k = settings.hybrid_rrf_k
    query_bundle = build_query_bundle(state)
    profile_name = settings.retrieval_profile

    logger.info(
        "[RAG][query_compare] original_query=%r rewritten_queries=%r",
        query_bundle.original_query,
        query_bundle.rewritten_queries,
    )
    logger.info(
        "[RAG][query_preprocess] original_query=%r normalized_query=%r "
        "expanded_terms=%r law_references=%r extracted_keywords=%r "
        "kiwi_bm25_query=%r dense_queries=%r retry_count=%s",
        query_bundle.original_query,
        query_bundle.normalized_query,
        query_bundle.expanded_terms,
        query_bundle.law_references,
        query_bundle.extracted_keywords,
        query_bundle.kiwi_bm25_query,
        query_bundle.dense_queries,
        state.get("retry_count", 0),
    )

    # 2026.06.29(sooyeon.choi) 추가 - Task 6: 질의 유형 분류 후 채널별 가중치 결정
    query_type = classify_query_type(preprocess_result, settings)
    # 2026.11.11(sooyeon.choi) 수정 - legacy 엔진 경로도 같은 가중치 프로필 사용
    rrf_weights = get_rrf_weights(query_type, settings) or None

    logger.info(
        "[RAG][node=retrieve] collection=%s profile=%s dense_queries=%s candidate_top_k=%s filters=%s query_type=%s",
        collection_name,
        profile_name,
        len(query_bundle.dense_queries),
        top_k,
        bool(applied_filters),
        query_type.value,
    )

    # 2026.06.29(sooyeon.choi) 수정 - 설정에서 선택한 검색 방식들을 동시에 실행하고 결과를 하나로 합치도록 오케스트레이터에 위임
    retrieve_timeout = settings.retrieve_timeout
    try:
        # 2026.07.07(sooyeon.choi) 수정 - 운영 기본은 Qdrant 서버 측 Dense+Kiwi BM25 RRF
        if settings.retrieval_engine == "qdrant_hybrid":
            merged_results = await asyncio.wait_for(
                _search_qdrant_hybrid(
                    query_bundle=query_bundle,
                    collection_name=collection_name,
                    filters=applied_filters,
                    top_k=top_k,
                    query_type=query_type,
                    settings=settings,
                    container=deps.container if deps else None,
                ),
                timeout=retrieve_timeout,
            )
            channel_results = {"qdrant_hybrid": merged_results}
        elif settings.retrieval_engine == "legacy":
            profile = get_retrieval_profile(profile_name)
            orchestrator = deps.container.retrieval_orchestrator if deps else get_retrieval_orchestrator()
            channel_results = await asyncio.wait_for(
                orchestrator.search(
                    profile=profile,
                    query_bundle=query_bundle,
                    top_k=top_k,
                    collection_name=collection_name,
                    filters=applied_filters,
                ),
                timeout=retrieve_timeout,
            )
            # Task 6: 질의 유형 가중치로 RRF 병합
            merged_results = orchestrator.merge(
                channel_results,
                profile=profile,
                weights=rrf_weights,
                k=rrf_k,
            )
        else:
            raise ValueError(
                f"지원하지 않는 retrieval_engine입니다: {settings.retrieval_engine}"
            )
        # Task 8: 메타데이터 soft boost 적용 후 candidate_top_k로 슬라이싱
        query_metadata = {"keywords": preprocess_result.get("extracted_keywords") or []}
        raw_results = apply_soft_boost(merged_results, query_metadata, settings)[:top_k]
        rag_diag(
            logger,
            "[RAG][diag][node=retrieve] collection=%s profile=%s channels=%s counts=%s merged=%s rrf_k=%s query_type=%s",
            collection_name,
            profile_name,
            list(channel_results),
            {name: len(results) for name, results in channel_results.items()},
            len(raw_results),
            rrf_k,
            query_type.value,
        )

    except asyncio.TimeoutError:
        logger.error(f"검색 타임아웃 (제한: {retrieve_timeout}초, 컬렉션: '{collection_name}')")
        return {
            "retrieved_chunks": [],
            "error": f"검색 타임아웃 ({retrieve_timeout}초 초과)",
            "outcome_code": "retrieval_error",
        }
    except Exception as e:
        logger.error(f"검색 실패 (컬렉션: '{collection_name}'): {e}")
        return {
            "retrieved_chunks": [],
            "error": str(e),
            "outcome_code": "retrieval_error",
        }

    # ── ChunkResult 변환 ──────────────────────────────────────────────────────
    chunks: List[ChunkResult] = []
    for cid, score, payload in raw_results:
        payload["source_collection"] = collection_name
        chunks.append(ChunkResult(
            chunk_id=cid,
            document_id=payload.get("document_id", ""),
            text=payload.get("text", ""),
            score=score,
            metadata=payload,
        ))

    scores = [c["score"] for c in chunks]
    logger.info(
        "[RAG][results][pre_rerank] count=%s chunks=%s",
        len(chunks),
        json.dumps(chunk_log_payload(chunks), ensure_ascii=False),
    )
    rag_diag(
        logger,
        "[RAG][diag][node=retrieve] returned=%s max_score=%.4f min_score=%.4f",
        len(chunks),
        max(scores, default=0.0),
        min(scores, default=0.0),
    )
    return {"retrieved_chunks": chunks, "error": None}
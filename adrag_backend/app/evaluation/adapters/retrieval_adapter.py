"""검색 어댑터 — 기존 검색 채널을 평가용 인터페이스(RetrieverPort)로 래핑.

평가 목적상 질의 재작성(LLM) 없이 원 질의만으로 QueryBundle을 구성한다.
LLM 재작성 포함 평가는 end_to_end(rag_pipeline_adapter) 경로에서 수행된다.

운영 기본 검색 방식이 settings.retrieval_engine="qdrant_hybrid"(Qdrant 서버측
weighted RRF)이므로, search_rrf()는 retrieve.py 노드와 동일한 분기 로직을 재사용해
운영과 동일한 병합 결과를 평가한다.
(reference app/evaluation/adapters/retrieval_adapter.py 이식 — import 경로만 변경)
"""

import asyncio
from typing import List, Optional

from app.core.config import get_settings
from app.evaluation.ports import SearchHit
from app.graphs.nodes.retrieve import (
    _search_qdrant_hybrid,
    get_embedding_client,
    get_kiwi_bm25_encoder,
    get_retrieval_orchestrator,
    get_sparse_encoder,
    get_vector_repo,
)
from app.graphs.retrieval_engine import (
    Bm42Channel,
    DenseChannel,
    KiwiBm25Channel,
    QueryBundle,
    apply_soft_boost,
    classify_query_type,
    get_retrieval_profile,
)
from app.utils.kiwi_tokenizer import normalize_query


# 2026.07.28(sooyeon.choi) 수정 - 평가 Kiwi 단독 검색의 query 인코딩/Qdrant 호출 직렬화
#   운영 RAG 검색은 이 lock을 사용하지 않으며 기존 병렬 hybrid 경로에 영향이 없다.
_KIWI_EVAL_LOCK = asyncio.Lock()


def _build_eval_query_bundle(query: str) -> QueryBundle:
    """재작성 없이 원 질의만으로 QueryBundle을 구성한다."""
    normalized = normalize_query(query)
    return QueryBundle(
        original_query=query,
        rewritten_queries=[query],
        rewritten_query_embeddings=None,
        normalized_query=normalized,
        expanded_terms=[],
        law_references=[],
        extracted_keywords=[],
        dense_queries=[query],
        kiwi_bm25_query=normalized,
        bm42_queries=[query, normalized] if normalized != query else [query],
    )

# 검색 채널 어댑터
class EvalRetriever:
    """RetrieverPort 구현 — 채널별 독립 검색 + 운영 방식과 동일한 병합 검색."""

    def __init__(self) -> None:
        # [AI+ 시험] Recall@10 - 2) 임베딩 모델 및 하이브리드 검색에 필요한 구성 요소를 불러오는 코드
        # [AI+ 시험] NDCG@5 - 2) 임베딩 모델 및 Reranker 모델을 불러오는 코드 (임베딩 모델)
        self._vector_repo = get_vector_repo()
        self._embedding_client = get_embedding_client()
        self._channels = {
            "dense": DenseChannel(self._vector_repo, self._embedding_client),
            "kiwi_bm25": KiwiBm25Channel(self._vector_repo),
        }

    def _get_channel(self, name: str):
        if name == "bm42" and "bm42" not in self._channels:
            self._channels["bm42"] = Bm42Channel(self._vector_repo, get_sparse_encoder())
        if name not in self._channels:
            raise ValueError(f"지원하지 않는 검색 채널입니다: {name}")
        return self._channels[name]

    async def search_channel(
        self,
        channel: str,
        query: str,
        top_k: int,
        collection_name: str,
    ) -> List[SearchHit]:
        """채널 단독 검색.

        2026.07.23(sychoi) 수정 - kiwi_bm25는 운영과 동일한 Qdrant 네이티브 sparse 경로로 측정한다.
        기존에는 legacy KiwiBm25Channel(vector_repo.search_bm25)을 호출했는데, 이 경로는
        MatchText 프리필터가 토큰을 AND로 묶어 다중 토큰 질의에서 후보가 0건이 되어
        지표가 항상 0에 수렴했다(운영 기본값 retrieval_engine="qdrant_hybrid"는 이 경로를
        사용하지 않으므로 서비스 품질과 무관한 측정 오류였다).
        """
        if channel == "kiwi_bm25":
            return await self._search_sparse_only(query, top_k, collection_name)

        bundle = _build_eval_query_bundle(query)
        return await self._get_channel(channel).search(
            query_bundle=bundle,
            top_k=top_k,
            collection_name=collection_name,
            filters=None,
        )

    async def _search_sparse_only(
        self,
        query: str,
        top_k: int,
        collection_name: str,
    ) -> List[SearchHit]:
        """Kiwi BM25 named sparse vector를 RRF 없이 직접 검색한다."""
        bundle = _build_eval_query_bundle(query)

        # 2026.07.28(sooyeon.choi) 수정 - Dense+RRF 우회를 제거하고 평가에서만
        #   Qdrant kiwi_bm25 named sparse vector를 직접 조회한다.
        async with _KIWI_EVAL_LOCK:
            sparse_query = await asyncio.to_thread(
                get_kiwi_bm25_encoder().encode_query, bundle.kiwi_bm25_query
            )
            return await asyncio.to_thread(
                self._vector_repo.search_kiwi_bm25,
                query=sparse_query,
                top_k=top_k,
                collection_name=collection_name,
                filters=None,
            )

    async def search_rrf(
        self,
        query: str,
        top_k: int,
        collection_name: str,
        profile: Optional[str] = None,
    ) -> List[SearchHit]:
        """운영 설정(retrieval_engine)과 동일한 병합 방식으로 검색한다.

        - qdrant_hybrid(기본): retrieve.py의 _search_qdrant_hybrid()를 그대로 재사용
        - legacy: RetrievalOrchestrator 채널 병렬 실행 + RRF 병합
        """
        settings = get_settings()
        bundle = _build_eval_query_bundle(query)
        query_type = classify_query_type({})  # 평가는 전처리 없이 기본 분류 사용

        if settings.retrieval_engine == "qdrant_hybrid":
            # [AI+ 시험] Recall@10 - 3) 시험 데이터를 입력하여 임베딩 기반 의미 검색과 BM25 기반 키워드 검색을 수행하는 코드
            # [AI+ 시험] NDCG@5 - 3) 시험 데이터를 입력하여 임베딩 기반 의미 검색과 BM25 기반 키워드 검색을 수행하는 코드
            merged = await _search_qdrant_hybrid(
                query_bundle=bundle,
                collection_name=collection_name,
                filters=None,
                top_k=top_k,
                query_type=query_type,
                settings=settings,
            )
        else:
            profile_def = get_retrieval_profile(profile or settings.retrieval_profile)
            orchestrator = get_retrieval_orchestrator()
            channel_results = await orchestrator.search(
                profile=profile_def,
                query_bundle=bundle,
                top_k=top_k,
                collection_name=collection_name,
                filters=None,
            )
            merged = orchestrator.merge(
                channel_results, profile=profile_def, k=settings.hybrid_rrf_k
            )

        boosted = apply_soft_boost(merged, {"keywords": []})
        # [AI+ 시험] Recall@10 - 4) 검색 결과를 통합하여 질의별 상위 10개 문서 청크를 추출하는 코드
        return boosted[:top_k]

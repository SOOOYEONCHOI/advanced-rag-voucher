"""검색 성능 전용 평가 실행기.

전체 답변 생성 없이 dense baseline, 운영 hybrid 검색, 운영 rerank 결과를
동일 Golden 데이터로 비교한다.
"""

import asyncio
import time
from typing import List, Literal

from app.core.config import get_settings
from app.graphs.nodes.rerank import rerank
from app.graphs.nodes.retrieve import get_retrieval_orchestrator, retrieve
from app.graphs.retrieval_engine import build_query_bundle, get_retrieval_config
from app.graphs.state import ChunkResult, PipelineState

from offline_evaluation.config import EvalConfig
from offline_evaluation.dataset.schema import GoldenRecord
from offline_evaluation.evaluators.base import EvalResult


RetrievalMode = Literal["dense_only", "hybrid_retrieval", "hybrid_rerank"]


class RetrievalEvaluationRunner:
    """운영 검색 컴포넌트를 재사용하는 검색 전용 실행기."""

    def __init__(self, mode: RetrievalMode, config: EvalConfig | None = None):
        self.mode = mode
        self.config = config or EvalConfig()
        self.settings = get_settings()

    async def run_single(self, record: GoldenRecord) -> EvalResult:
        state = self._build_state(record)
        timing = {}
        error = None
        relevance_threshold = self.settings.relevance_threshold

        try:
            if self.mode == "dense_only":
                started = time.perf_counter()
                retrieved = await self._run_dense(state)
                timing["retrieve_s"] = time.perf_counter() - started
            else:
                retrieve_result = await retrieve(state)
                retrieved = retrieve_result.get("retrieved_chunks") or []
                timing.update(retrieve_result.get("timing") or {})
                error = retrieve_result.get("error")

            reranked = []
            if not error and self.mode == "hybrid_rerank":
                state["retrieved_chunks"] = retrieved
                state["timing"] = timing
                rerank_result = await rerank(state)
                reranked = rerank_result.get("reranked_chunks") or []
                timing.update(rerank_result.get("timing") or {})
                relevance_threshold = rerank_result.get(
                    "relevance_threshold", relevance_threshold
                )
        except Exception as exc:
            retrieved = []
            reranked = []
            error = str(exc)

        return EvalResult(
            record_id=record["id"],
            intent=None,
            should_retrieve=True,
            retrieved_chunks=retrieved,
            reranked_chunks=reranked,
            relevance_threshold_used=relevance_threshold,
            final_context=None,
            context_chunk_count=None,
            context_chunks=[],
            generated_answer=None,
            citations=[],
            retry_count=0,
            error=error,
            timing=timing,
        )

    async def run_all(self, records: List[GoldenRecord]) -> List[EvalResult]:
        sem = asyncio.Semaphore(self.config.runner_concurrency)

        async def _bounded(record: GoldenRecord) -> EvalResult:
            async with sem:
                return await self.run_single(record)

        return list(await asyncio.gather(*[_bounded(r) for r in records]))

    async def _run_dense(self, state: PipelineState) -> List[ChunkResult]:
        """기존 RetrievalOrchestrator의 dense 채널만 실행한다."""
        config = get_retrieval_config(state, self.settings)
        bundle = build_query_bundle(state)
        orchestrator = get_retrieval_orchestrator()
        profile = {"channels": ["dense"], "weights": {"dense": 1.0}}
        channel_results = await orchestrator.search(
            profile=profile,
            query_bundle=bundle,
            top_k=config.candidate_top_k,
            collection_name=state["collection_name"],
            filters=state.get("filters"),
        )
        results = channel_results.get("dense", [])[:config.candidate_top_k]
        return [
            ChunkResult(
                chunk_id=str(chunk_id),
                document_id=payload.get("document_id", ""),
                text=payload.get("text", ""),
                score=float(score),
                metadata=payload,
            )
            for chunk_id, score, payload in results
        ]

    def _build_state(self, record: GoldenRecord) -> PipelineState:
        return {
            "user_id": record["user_id"],
            "session_id": None,
            "original_query": record["question"],
            "collection_filters": None,
            "collection_name": record["collection_name"],
            "conversation_history": None,
            "top_k": self.config.top_k,
            "citation_limit": 0,
            "llm_provider": None,
            "llm_model": None,
            "llm_api_key": None,
            "query_embedding": None,
            "rewritten_queries": [],
            "rewritten_query_embeddings": None,
            "filters": {},
            "retrieved_chunks": [],
            "reranked_chunks": [],
            "final_context": None,
            "context_chunks": [],
            "generated_answer": None,
            "thinking": None,
            "citations": [],
            "retry_count": 0,
            "error": None,
            "enable_metadata_filtering": False,
            "preprocess_result": {},
            "context_chunk_count": None,
            "intent": "rag_query",
            "should_retrieve": True,
            "guardrail_reason": None,
            "response_type": "rag",
            "timing": {},
            "usage": None,
            "outcome_code": "",
        }

"""
평가 파이프라인 실행기.

GoldenRecord 1건을 받아 실제 RAG 그래프를 실행하고,
평가에 필요한 중간 상태를 EvalResult로 캡처해 반환한다.

RAGService.query()를 거치지 않고 그래프를 직접 invoke하는 이유:
  RAGService는 PipelineState를 QueryResponse로 변환하는 과정에서
  retrieved_chunks, reranked_chunks 등 검색 단계 세부 정보를 일부 잃기 때문이다.
"""

import asyncio
import logging
import time
from typing import List

from app.core.config import get_settings
from app.graphs.rag_graph import build_rag_graph
from app.graphs.state import PipelineState

from offline_evaluation.config import EvalConfig
from offline_evaluation.dataset.schema import GoldenRecord
from offline_evaluation.evaluators.base import EvalResult

logger = logging.getLogger(__name__)


class EvaluationRunner:
    """RAG 그래프를 직접 실행해 EvalResult를 반환하는 실행기."""

    def __init__(self, config: EvalConfig | None = None):
        self.config = config or EvalConfig()
        self.settings = get_settings()
        self.graph = build_rag_graph()

    # ── 단건 실행 ─────────────────────────────────────────────

    async def run_single(self, record: GoldenRecord) -> EvalResult:
        """GoldenRecord 1건에 대해 파이프라인을 실행하고 EvalResult를 반환한다."""
        initial_state = self._build_initial_state(record)

        try:
            start = time.time()
            final_state: PipelineState = await self.graph.ainvoke(initial_state)
            elapsed_ms = (time.time() - start) * 1000
            logger.info(
                f"[runner] {record['id']} 완료 ({elapsed_ms:.0f}ms) "
                f"| intent={final_state.get('intent')} "
                f"| retry={final_state.get('retry_count', 0)}"
            )
        except Exception as exc:
            # 파이프라인 자체가 예외를 던진 경우 — error 필드로 기록하고 빈 결과 반환
            logger.error(f"[runner] {record['id']} 파이프라인 예외: {exc}", exc_info=True)
            return self._empty_result(record["id"], error=str(exc))

        return self._extract_result(record["id"], final_state)

    # ── 전체 실행 ─────────────────────────────────────────────

    async def run_all(self, records: List[GoldenRecord]) -> List[EvalResult]:
        """Semaphore로 동시성을 제어하며 전체 레코드를 실행한다.

        순서는 records 순서를 그대로 유지한다.
        """
        sem = asyncio.Semaphore(self.config.runner_concurrency)

        async def _bounded(record: GoldenRecord) -> EvalResult:
            async with sem:
                return await self.run_single(record)

        results = await asyncio.gather(*[_bounded(r) for r in records])
        return list(results)

    # ── 내부 헬퍼 ────────────────────────────────────────────

    def _build_initial_state(self, record: GoldenRecord) -> PipelineState:
        """GoldenRecord에서 PipelineState 초기값을 구성한다.

        RAGService.query()의 초기화 방식을 따르되,
        세션 관리와 LLM 공급자 선택은 생략한다 (로컬 vLLM 고정).
        """
        settings = self.settings
        top_k = self.config.top_k

        return {
            "user_id": record["user_id"],
            "session_id": None,                # 평가 시 세션 저장 불필요
            "original_query": record["question"],
            "collection_filters": None,
            "collection_name": record["collection_name"],
            "conversation_history": None,
            "top_k": top_k,
            "citation_limit": min(top_k, settings.max_citation_results),
            # LLM: 로컬 vLLM 고정
            "llm_provider": None,
            "llm_model": None,
            "llm_api_key": None,
            "enable_metadata_filtering": None,  # config 기본값 사용
            # 가드레일
            "intent": None,
            "should_retrieve": None,
            "guardrail_reason": None,
            "response_type": None,
            # 질의 분석
            "query_embedding": None,
            "rewritten_queries": [],
            "rewritten_query_embeddings": None,
            # 필터
            "filters": {},
            # 검색 결과
            "retrieved_chunks": [],
            "reranked_chunks": [],
            # 컨텍스트
            "final_context": None,
            "context_chunk_count": None,
            # 2026.07.10(sooyeon.choi) 수정 - 평가 파이프라인 Citation 매핑 기준 초기화
            "context_chunks": [],
            # 생성
            "generated_answer": None,
            "thinking": None,
            "citations": [],
            # 폴백
            "relevance_threshold": settings.relevance_threshold,
            "retry_count": 0,
            "error": None,
            # 전처리
            "preprocess_result": {},
            # 관측성
            "timing": {},
        }

    def _extract_result(self, record_id: str, state: PipelineState) -> EvalResult:
        """PipelineState에서 평가에 필요한 필드만 추출한다."""
        return EvalResult(
            record_id=record_id,
            intent=state.get("intent"),
            should_retrieve=state.get("should_retrieve"),
            retrieved_chunks=state.get("retrieved_chunks") or [],
            reranked_chunks=state.get("reranked_chunks") or [],
            relevance_threshold_used=(
                state.get("relevance_threshold")
                or self.settings.relevance_threshold
            ),
            final_context=state.get("final_context"),
            context_chunk_count=state.get("context_chunk_count"),
            # 2026.07.10(sooyeon.choi) 수정 - Citation 평가에 실제 컨텍스트 청크 전달
            context_chunks=state.get("context_chunks") or [],
            generated_answer=state.get("generated_answer"),
            citations=state.get("citations") or [],
            retry_count=state.get("retry_count", 0),
            error=state.get("error"),
            timing=state.get("timing") or {},
        )

    @staticmethod
    def _empty_result(record_id: str, error: str) -> EvalResult:
        """파이프라인 예외 발생 시 반환하는 빈 EvalResult."""
        return EvalResult(
            record_id=record_id,
            intent=None,
            should_retrieve=None,
            retrieved_chunks=[],
            reranked_chunks=[],
            relevance_threshold_used=0.0,
            final_context=None,
            context_chunk_count=None,
            # 2026.07.10(sooyeon.choi) 수정 - 예외 결과도 동일한 평가 스키마 유지
            context_chunks=[],
            generated_answer=None,
            citations=[],
            retry_count=0,
            error=error,
            timing={},
        )

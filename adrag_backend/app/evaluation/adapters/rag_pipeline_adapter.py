"""RAG 파이프라인 어댑터 — 그래프 in-process 실행 (RagPipelinePort 구현).

RAGService.query() 대신 그래프를 직접 실행하는 이유:
1. 평가 질의가 운영 쿼리 로그(tb_query_logs)에 기록되어 통계를 오염시키는 것 방지
2. state의 reranked_chunks(chunk_id 포함)·citations·노드별 timing·usage를
   API 응답 스키마 제약 없이 그대로 확보 (citations에는 chunk_id가 없으므로 필수)

PipelineState 초기화는 make_initial_state() 팩토리를 그대로 재사용한다.
(reference app/evaluation/adapters/rag_pipeline_adapter.py 이식 + ①축 평가용
 retry_count/should_retrieve 필드 추가)
"""

from typing import Any, Dict, Optional

from app.core.config import get_settings
from app.core.registry import resolve_llm_from_state
from app.evaluation.adapters.citation_repair import repair_missing_citations
from app.graphs.rag_graph import build_rag_graph
from app.graphs.nodes.format_citations import format_citations
from app.graphs.state import make_initial_state
from app.utils.log.log import LoggingLogger

logger = LoggingLogger().getLogger(__name__)

_graph = None


async def _repair_missing_citations(result: Dict[str, Any], initial_state: Dict[str, Any]) -> None:
    """평가 답변의 내용은 유지하고 누락된 인라인 인용만 1회 보정한다."""
    answer = result.get("generated_answer") or ""
    context_chunks = result.get("context_chunks") or []
    try:
        repaired = await repair_missing_citations(
            answer=answer,
            final_context=result.get("final_context") or "",
            context_count=len(context_chunks),
            llm_provider=resolve_llm_from_state(initial_state, get_settings()),
        )
        if not repaired:
            return
        result["generated_answer"] = repaired
        result.update(await format_citations(result))
        logger.info("[eval] 누락된 답변 인용 [N] 1회 보정 완료")
    except Exception as exc:
        # 인용 보정 실패가 이미 생성된 답변 전체를 평가 오류로 만들지는 않게 한다.
        logger.warning("[eval] 답변 인용 보정 실패: %s", type(exc).__name__)


def _get_graph():
    global _graph
    if _graph is None:
        _graph = build_rag_graph()
    return _graph


class EvalRagPipeline:
    """RagPipelinePort 구현."""

    async def run(
        self,
        query: str,
        collection_name: str,
        retrieval_top_n: int = 10,
        rerank_top_k: int = 5,
        llm_provider: Optional[str] = None,
        llm_model: Optional[str] = None,
        openai_api_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        settings = get_settings()

        initial_state = make_initial_state(
            user_id="eval_runner",
            session_id=None,               # 세션 미사용 (멀티턴 컨텍스트 배제)
            original_query=query,
            collection_filters=None,
            collection_name=collection_name,
            # 평가 실행은 legacy 단일 top_k 자동 배분을 사용하지 않는다.
            top_k=None,
            citation_limit=rerank_top_k,
            llm_provider=llm_provider,
            llm_model=llm_model,
            llm_api_key=openai_api_key,
            enable_metadata_filtering=None,
            relevance_threshold=settings.relevance_threshold,
        )
        initial_state["retrieval_override"] = {
            "candidate_top_k": retrieval_top_n,
            "rerank_top_k": rerank_top_k,
            "context_top_k": rerank_top_k,
        }

        result = await _get_graph().ainvoke(initial_state)

        # 평가 실행에서만 형식 누락을 한 번 보정한다. 운영 스트리밍 응답에는 원문과
        # 보정문이 중복 전송될 수 있으므로 그래프 공통 노드가 아닌 평가 어댑터에 둔다.
        await _repair_missing_citations(result, initial_state)

        return {
            "answer": result.get("generated_answer") or "",
            "error": result.get("error"),
            "outcome_code": result.get("outcome_code", "unknown"),
            "intent": result.get("intent"),
            # ①축(threshold-fallback/guardrail) 평가용
            "should_retrieve": result.get("should_retrieve"),
            "retry_count": result.get("retry_count", 0),
            "relevance_threshold": (
                result["relevance_threshold"]
                if result.get("relevance_threshold") is not None
                else settings.relevance_threshold
            ),
            "retrieved_chunks": result.get("retrieved_chunks", []),
            # ChunkResult dict: {chunk_id, document_id, text, score, metadata}
            "reranked_chunks": result.get("reranked_chunks", []),
            "final_context": result.get("final_context"),
            # 실제 LLM 컨텍스트의 인용 번호 순서와 동일한 청크 목록
            "context_chunks": result.get("context_chunks", []),
            # citation dict: {citation_id, document_id, original_filename, ...}
            "citations": result.get("citations", []),
            "timing": result.get("timing", {}),
            "usage": result.get("usage"),
        }

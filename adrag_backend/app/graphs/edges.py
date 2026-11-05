"""LangGraph RAG 파이프라인 조건부 엣지 함수 모음."""

from app.core.config import get_settings
from app.graphs.state import PipelineState
from app.graphs.dependencies import GraphDependencies
# 2026.07.16(sooyeon.choi) 수정 - 임계값 우선순위 규칙 공유 (B5)
from app.graphs.utils import effective_threshold
from app.utils.log.log import LoggingLogger

# 2026.07.16(sooyeon.choi) 수정 - 모듈별 named logger 적용 (B16)
logger = LoggingLogger().getLogger(__name__)


def check_filter_error(state: PipelineState) -> str:
    """build_metadata_filter 이후 분기: 권한 오류 시 build_response, 정상 시 retrieve."""
    if state.get("error"):
        logger.info("[RAG][edge=check_filter_error] route=build_response reason=필터오류")
        return "build_response"
    logger.info("[RAG][edge=check_filter_error] route=retrieve reason=정상")
    return "retrieve"


def check_validation(state: PipelineState) -> str:
    """validate_input 이후 분기: 오류 시 build_response, 정상 시 guardrail."""
    if state.get("error"):
        logger.info("[RAG][edge=check_validation] route=build_response reason=검증오류")
        return "build_response"
    logger.info("[RAG][edge=check_validation] route=guardrail reason=정상")
    return "guardrail"


def check_guardrail(state: PipelineState) -> str:
    """guardrail 이후 분기: 차단 시 build_response, 정상 질의 시 analyze_and_rewrite."""
    if state.get("should_retrieve") is False:
        logger.info(
            "[RAG][edge=check_guardrail] route=build_response reason=차단 intent=%r",
            state.get("intent"),
        )
        return "build_response"
    logger.info("[RAG][edge=check_guardrail] route=analyze_and_rewrite reason=허용")
    return "analyze_and_rewrite"


# 2026.07.16(sooyeon.choi) 추가 - retrieve 시스템 오류는 재시도 없이 즉시 종료 (B2)
#   기존: 타임아웃/미등록 컬렉션/Qdrant 장애도 rerank→fallback을 거쳐 확장 재검색을
#   1회 더 수행한 뒤 "관련 정보를 찾을 수 없습니다"로 응답 → 시스템 장애가
#   '문서 없음'으로 위장되어 사용자·운영자 모두 오판하던 문제 수정.
#   fallback 재시도는 이제 '검색 성공 + 관련성 미달' 및 'LLM 생성 오류' 경로 전용이다.
def check_retrieval(state: PipelineState) -> str:
    """retrieve 이후 분기: 시스템 오류 시 build_response로 즉시 종료, 정상 시 rerank."""
    if state.get("error"):
        logger.info(
            "[RAG][edge=check_retrieval] route=build_response reason=검색오류 error=%r",
            state.get("error"),
        )
        return "build_response"
    logger.info("[RAG][edge=check_retrieval] route=rerank reason=정상")
    return "rerank"


def check_relevance(state: PipelineState, deps: GraphDependencies | None = None) -> str:
    """rerank 이후 분기: threshold 이상 점수의 청크가 있으면 assemble_context, 없으면 fallback_handler."""
    chunks = state.get("reranked_chunks", [])
    # 2026.07.16(sooyeon.choi) 수정 - threshold_override 우선순위 헬퍼 적용 (B5)
    threshold = effective_threshold(state, deps.settings if deps else get_settings())

    qualified = [c for c in chunks if c.get("score", 0.0) >= threshold]
    if qualified:
        logger.info(
            "[RAG][edge=check_relevance] route=assemble_context qualified=%s total=%s threshold=%.4f",
            len(qualified),
            len(chunks),
            threshold,
        )
        return "assemble_context"

    logger.info(
        "[RAG][edge=check_relevance] route=fallback_handler qualified=0 total=%s threshold=%.4f max_score=%.4f",
        len(chunks),
        threshold,
        max((c.get("score", 0.0) for c in chunks), default=0.0),
    )
    return "fallback_handler"


def check_generation(state: PipelineState) -> str:
    """generate_answer 이후 분기: 오류 시 fallback_handler, 정상 시 format_citations."""
    if state.get("error"):
        logger.info("[RAG][edge=check_generation] route=fallback_handler reason=생성오류")
        return "fallback_handler"
    logger.info("[RAG][edge=check_generation] route=format_citations reason=정상")
    return "format_citations"


def check_fallback_retry(state: PipelineState, deps: GraphDependencies | None = None) -> str:
    """fallback_handler 이후 라우팅."""
    max_retries = (deps.settings if deps else get_settings()).fallback_max_retries
    if state.get("retry_count", 0) <= max_retries and not state.get("generated_answer"):
        # 2026.07.16(sooyeon.choi) 수정 - fallback 확장이 retrieval_override로 전환됨에 따라 로그 갱신 (B4)
        logger.info(
            "[RAG][edge=check_fallback_retry] route=retrieve retry_count=%s max_retries=%s retrieval_override=%s threshold=%s",
            state.get("retry_count", 0),
            max_retries,
            state.get("retrieval_override"),
            state.get("relevance_threshold"),
        )
        return state.get("retry_target") or "retrieve"

    logger.info("[RAG][edge=check_fallback_retry] route=build_response reason=최대 재시도 또는 답변완료")
    return "build_response"

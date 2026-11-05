"""
폴백/재시도 핸들러 노드.

retry_count 기반으로 재시도 또는 안내 메시지를 반환한다.

2026.07.16(sooyeon.choi) 수정 - 오류 경로 재설계 (B2/B4)
  - 검색 시스템 오류는 check_retrieval 엣지가 build_response로 직행시키므로
    이 노드는 '검색 성공 + 관련성 미달'과 'LLM 생성 오류' 경로만 처리한다.
  - top_k 확장 방식 변경: legacy top_k에 값을 쓰면 from_legacy_top_k()가
    candidate=×4, context=×0.5로 재해석해 배분 체계가 변질되던 것을
    retrieval_override(단계별 명시 배분)로 분리 (B4)
  - 최대 재시도 초과 시 원인 유형별로 사용자 메시지 구분 (LLM 오류 vs 관련 문서 없음)

재시도 전략:
  - candidate/rerank top_k를 2배로 확장해 더 넓은 후보군에서 재검색 (context는 유지)
  - relevance_threshold를 완화값(fallback_relevance_threshold)으로 낮춰 경계선 청크도 포함
  - rewritten_queries를 원본 질의 단독으로 초기화 (재작성 쿼리가 오히려 노이즈인 경우 대비)

에러 체이닝:
  - 재시도 진입 시 error 필드를 None으로 초기화 (이전 오류가 다음 체크에 영향 안 줌)
  - 최대 재시도 초과 시 원인 유형을 최종 메시지에 반영
"""

from app.core.config import get_settings
from app.core.user_messages import UserMessageType, get_user_message
from app.graphs.dependencies import GraphDependencies
from app.graphs.retrieval_engine import (
    expand_retrieval_config_for_fallback,
    get_retrieval_config,
)
from app.graphs.state import PipelineState
from app.graphs.utils import rag_diag, timed_node
from app.utils.log.log import LoggingLogger

# 로거 초기화
# 2026.07.16(sooyeon.choi) 수정 - 모듈별 named logger 적용 (B16)
logger = LoggingLogger().getLogger(__name__)

@timed_node("fallback_handler")
async def fallback_handler(state: PipelineState, deps: GraphDependencies | None = None) -> dict:
    """retry_count 기반 재시도 또는 안내 메시지 반환."""
    settings = deps.settings if deps else get_settings()
    max_retries = settings.fallback_max_retries
    current_retry = state.get("retry_count", 0)

    # 진입 원인 파악: LLM 생성 오류 vs 검색 관련성 미달
    # (검색 시스템 오류는 check_retrieval에서 차단되어 여기 도달하지 않음 - B2)
    prior_error = state.get("error")
    if prior_error:
        logger.warning(f"fallback 진입 원인 — LLM 생성 오류: {prior_error}")
    else:
        # 2026.06.19(sooyeon.choi) 추가 - 관련 문서 없음 결과 코드 유지
        outcome_code = "no_context"

    if current_retry < max_retries:
        # 생성 실패 시에는 이미 확보한 컨텍스트를 재사용하고 LLM만 재시도한다.
        if prior_error:
            return {
                "retry_count": current_retry + 1,
                "retry_target": "generate_answer",
                "error": None,
            }
        # 2026.07.16(sooyeon.choi) 수정 - legacy top_k 대신 retrieval_override로 확장 (B4)
        #   현재 유효 설정(candidate/rerank/context)을 기준으로 candidate·rerank만 2배 확장
        current_config = get_retrieval_config(state, settings)
        expanded_override = expand_retrieval_config_for_fallback(current_config, settings)
        fallback_threshold = settings.fallback_relevance_threshold
        rag_diag(
            logger,
            "[RAG][diag][node=fallback_handler] retry=재시도 reason=%s retry_count=%s max_retries=%s "
            "config=%s expanded=%s threshold=%s fallback_threshold=%s",
            "LLM오류" if prior_error else "관련 청크없음",
            current_retry + 1,
            max_retries,
            current_config,
            expanded_override,
            state.get("relevance_threshold"),
            fallback_threshold,
        )
        result = {
            "retry_count": current_retry + 1,
            "retry_target": "retrieve",
            "retrieval_override": expanded_override,
            "relevance_threshold": fallback_threshold,
            # 2026.07.16(sooyeon.choi) 추가 - 이전 degraded 폴백의 임계값 우회 잔류 방지 (B5)
            "threshold_override": None,
            "error": None,  # 이전 오류를 초기화하여 재시도 후 체크에 영향 없도록 함
            # 재작성 쿼리가 오히려 범위를 좁힌 경우를 대비해 원본 질의만 사용
            "rewritten_queries": [state["original_query"]],
        }
        if not prior_error:
            result["outcome_code"] = outcome_code
        return result
    else:
        # 최대 재시도 초과 — 원인 유형에 따라 메시지 구분
        # 2026.07.16(sooyeon.choi) 수정 - LLM 오류가 '관련 문서 없음'으로 위장되던 문제 수정 (B2)
        # 2026.06.05(sooyeon.choi) 수정 - query_stream 안내 문구와 통일
        if prior_error:
            logger.warning(
                f"최대 재시도 횟수({max_retries}) 도달 — LLM 오류로 인한 종료: {prior_error}"
            )
            final_answer = get_user_message(UserMessageType.TEMPORARY_ERROR)
        else:
            final_answer = get_user_message(UserMessageType.NO_CONTEXT)
        result = {
            "generated_answer": final_answer,
            "citations": [],
            "error": None,
            "retry_target": None,
        }
        rag_diag(
            logger,
            "[RAG][diag][node=fallback_handler] retry=종료 reason=%s retry_count=%s max_retries=%s",
            "LLM오류" if prior_error else "관련 청크없음",
            current_retry,
            max_retries,
        )
        if not prior_error:
            result["outcome_code"] = outcome_code
        else:
            result["outcome_code"] = "llm_error"
        return result

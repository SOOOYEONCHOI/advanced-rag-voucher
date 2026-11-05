"""
입력 검증 노드.

user_id와 original_query 필수 필드를 검증하고,
검증 실패 시 error 필드를 설정하여 build_response로 분기시킨다.

1. user_id 가 있는지 확인
2. original_query 가 있는지 확인
3. original_query 길이가 설정 범위 내에 있는지 확인 (2자 이상 ~ 2000자 이하)
4. 검증 통과 시 파이프라인 State 초기화 (기존 값 유지, 없으면 config 기본값 적용)
- error: 검증 실패 시 에러 메시지, 성공 시 None
"""

from app.core.config import get_settings
from app.graphs.dependencies import GraphDependencies
from app.graphs.state import PipelineState
from app.graphs.utils import timed_node
from app.utils.log.log import LoggingLogger

# 2026.05.22(sooyeon.choi) 추가 - 노드 출력 로깅
# 2026.07.16(sooyeon.choi) 수정 - 모듈별 named logger 적용 (B16)
logger = LoggingLogger().getLogger(__name__)


@timed_node("validate_input")
async def validate_input(state: PipelineState, deps: GraphDependencies | None = None) -> dict:
    """user_id, original_query 필수 필드 및 길이 검증."""
    # user_id 검증
    if not state.get("user_id") or not state["user_id"].strip():
        logger.warning("[validate_input 출력] 검증 실패 | reason=user_id 누락")
        # 2026.06.19(sooyeon.choi) 추가 - 입력 검증 실패 결과 코드 기록
        return {
            "error": "user_id는 필수 입력입니다",
            "outcome_code": "validation_error",
        }

    # original_query 존재 여부 검증
    query = (state.get("original_query") or "").strip()
    if not query:
        logger.warning("[validate_input 출력] 검증 실패 | reason=original_query 누락")
        return {
            "error": "질의 내용은 필수 입력입니다",
            "outcome_code": "validation_error",
        }

    # 길이 검증
    settings = deps.settings if deps else get_settings()
    if len(query) < settings.query_min_length:
        logger.warning(f"[validate_input 출력] 검증 실패 | reason=질의 너무 짧음({len(query)}자)")
        return {
            "error": f"질문이 너무 짧습니다. {settings.query_min_length}자 이상 입력해주세요.",
            "outcome_code": "validation_error",
        }
    if len(query) > settings.query_max_length:
        logger.warning(f"[validate_input 출력] 검증 실패 | reason=질의 너무 김({len(query)}자)")
        return {
            "error": f"질문이 너무 깁니다. {settings.query_max_length}자 이내로 입력해주세요.",
            "outcome_code": "validation_error",
        }

    # 파이프라인 State 초기화
    # 요청에서 넘어온 값은 유지, 없으면 config 기본값 적용
    # 파이프라인 내부 누적 필드는 항상 초기화 (이전 실행 잔류 방지)
    # 2026.07.16(sooyeon.choi) 수정 - top_k 기본값 강제 주입 제거 (B4)
    #   기존: 요청에 top_k가 없어도 settings.top_k_results를 채워 넣어
    #   get_retrieval_config()가 항상 legacy(from_legacy_top_k) 경로를 타면서
    #   2026.07.08에 도입한 단계별(candidate/reranker/context) 설정이 무력화되어 있었음.
    #   변경: 요청 명시값만 유지하고 None이면 단계별 설정이 적용되도록 그대로 둔다.
    return {
        "error": None,
        "outcome_code": "unknown",
        "retry_count": 0,
        "top_k": state.get("top_k"),
        # 2026.07.16(sooyeon.choi) 추가 - B4/B5 override 필드 초기화 (이전 실행 잔류 방지)
        "retrieval_override": None,
        "threshold_override": None,
        "citation_limit": state.get("citation_limit") or settings.max_citation_results,
        "relevance_threshold": (
            state["relevance_threshold"]
            if state.get("relevance_threshold") is not None
            else settings.relevance_threshold
        ),
        "timing": {},
        "rewritten_queries": [],
        "retrieved_chunks": [],
        "reranked_chunks": [],
        "citations": [],
        "filters": {},
    }

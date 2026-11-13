"""
최종 응답 구성 노드.

파이프라인의 마지막 단계로, 실제 QueryResponse 변환은 RAGService 래퍼에서 수행한다.
이 노드는 타이밍 정보만 기록하고 빈 딕셔너리를 반환한다.
"""

from app.core.user_messages import UserMessageType, get_user_message
from app.graphs.state import PipelineState
from app.graphs.utils import timed_node
from app.utils.log.log import LoggingLogger

# 로거 초기화
# 2026.07.16(sooyeon.choi) 수정 - 모듈별 named logger 적용
logger = LoggingLogger().getLogger(__name__)


@timed_node("build_response")
async def build_response(state: PipelineState) -> dict:
    """최종 응답 구성 — RAGService에서 QueryResponse로 변환 위임."""
    if (
        state.get("outcome_code") == "validation_error"
        and state.get("error")
        and not state.get("generated_answer")
    ):
        logger.warning(
            "[RAG][node=build_response] 입력 검증 실패 error=%r", state.get("error")
        )
        return {
            "error": get_user_message(UserMessageType.INVALID_QUESTION),
            "citations": [],
        }
    # 2026.07.16(sooyeon.choi) 추가 - 검색 시스템 오류의 사용자 안내 메시지 구성
    #   check_retrieval이 오류를 재시도 없이 이곳으로 직행시키므로,
    #   raw error 문자열 대신 원인 유형이 드러나는 안내 문구로 교체한다.
    #   generated_answer가 아닌 error 필드를 교체하는 이유:
    #   RAGService가 answer = generated_answer or error 로 채우면서도
    #   answer_generated 통계(bool(generated_answer))는 False로 유지되어야 하기 때문.
    if (
        state.get("outcome_code") == "retrieval_error"
        and state.get("error")
        and not state.get("generated_answer")
    ):
        logger.warning(
            "[RAG][node=build_response] 검색 오류 종료 error=%r", state.get("error")
        )
        # 2026.11.11(sooyeon.choi) 수정 - 권한 없음·컬렉션 없음은 원인별 안내(그 밖의 검색 오류는 일시 오류 안내)
        message_type = state.get("error_message_type")
        if message_type not in (UserMessageType.PERMISSION_DENIED.value, UserMessageType.COLLECTION_UNAVAILABLE.value):
            message_type = UserMessageType.TEMPORARY_ERROR
        return {
            "error": get_user_message(message_type),
            "citations": [],
        }
    return {}

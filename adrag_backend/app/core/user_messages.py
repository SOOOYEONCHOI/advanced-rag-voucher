"""사용자에게 노출하는 표준 안내 문구."""

from enum import Enum


class UserMessageType(str, Enum):
    OUT_OF_SCOPE = "out_of_scope"
    NO_CONTEXT = "no_context"
    SECURITY_BLOCKED = "security_blocked"
    INVALID_QUESTION = "invalid_question"
    TEMPORARY_ERROR = "temporary_error"
    # 2026.11.11(sooyeon.choi) 추가 - 검색 준비 단계 오류를 원인별로 안내(전에는 모두 TEMPORARY_ERROR)
    PERMISSION_DENIED = "permission_denied"
    COLLECTION_UNAVAILABLE = "collection_unavailable"


USER_MESSAGES = {
    UserMessageType.OUT_OF_SCOPE: (
        "요청하신 내용은 현재 문서 검색 서비스에서 지원하지 않습니다. \n"
        "등록된 문서 또는 업무 내용과 관련된 질문을 입력해 주세요."
    ),
    UserMessageType.NO_CONTEXT: (
        "등록된 문서에서 질문에 답변할 수 있는 충분한 근거를 찾지 못했습니다. \n"
        "질문을 구체적으로 입력하거나 검색할 문서 컬렉션을 확인해 주세요."
    ),
    UserMessageType.SECURITY_BLOCKED: (
        "요청하신 내용은 보안 정책에 따라 처리할 수 없습니다. \n"
        "민감정보나 제한된 내용을 제외한 후 다시 질문해 주세요."
    ),
    UserMessageType.INVALID_QUESTION: (
        "질문의 의미나 요청 사항을 정확히 파악하기 어렵습니다. \n"
        "찾으려는 정보와 관련 문서, 조건 등을 포함하여 조금 더 구체적으로 입력해 주세요."
    ),
    UserMessageType.TEMPORARY_ERROR: (
        "답변을 생성하는 중 일시적인 오류가 발생했습니다. \n"
        "잠시 후 다시 시도해 주세요. 문제가 계속되면 관리자에게 문의해 주세요."
    ),
    UserMessageType.PERMISSION_DENIED: (
        "선택한 문서 컬렉션을 검색할 권한이 없습니다. \n"
        "권한이 필요하면 관리자에게 문의해 주세요."
    ),
    UserMessageType.COLLECTION_UNAVAILABLE: (
        "검색할 문서 컬렉션을 찾을 수 없습니다. \n"
        "문서 컬렉션을 다시 선택해 주세요. 목록에 없으면 관리자에게 문의해 주세요."
    ),
}

GREETING_MESSAGE = (
    "안녕하세요. 등록된 문서를 기반으로 질문에 답변해 드립니다. \n"
    "궁금한 내용을 입력해 주세요."
)


def get_user_message(message_type: UserMessageType | str) -> str:
    """메시지 유형에 대응하는 사용자 안내 문구를 반환한다."""
    return USER_MESSAGES[UserMessageType(message_type)]


def is_no_context_answer(answer: str) -> bool:
    """제한적인 형식 차이를 허용해 표준 근거 부족 응답인지 판별한다."""
    normalized = answer.strip()
    if len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in {'"', "'"}:
        normalized = normalized[1:-1].strip()
    return normalized == get_user_message(UserMessageType.NO_CONTEXT)

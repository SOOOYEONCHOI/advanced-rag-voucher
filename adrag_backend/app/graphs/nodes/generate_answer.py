"""
LLM 답변 생성 노드.

build_rag_messages()로 메시지를 구성하고, LLMService.chat()으로 답변을 생성한다.
Qwen3의 <think> 태그는 LLMService.strip_thinking()으로 분리한다.
LLM 호출 실패 시 error 필드를 설정하여 fallback_handler로 분기시킨다.
"""

from langchain_core.callbacks.manager import adispatch_custom_event

from app.core.config import get_settings
from app.core.user_messages import (
    UserMessageType,
    get_user_message,
    is_no_context_answer,
)
from app.graphs.dependencies import GraphDependencies
# 2026.07.16(sooyeon.choi) 수정 - 프로바이더 문자열 분기를 레지스트리로 이동 (3단계)
#   신규 LLM(Gemini/Claude 등)은 registry 등록만으로 이 노드 수정 없이 편입된다.
from app.core.registry import resolve_llm_from_state
from app.graphs.nodes.collect_answer_images import context_with_images
from app.graphs.state import PipelineState
from app.graphs.utils import timed_node
from app.prompts.templates import build_rag_messages
from app.utils.log.log import LoggingLogger

# 로거 초기화
# 2026.07.16(sooyeon.choi) 수정 - 모듈별 named logger 적용 (B16)
logger = LoggingLogger().getLogger(__name__)


@timed_node("generate_answer")
async def generate_answer(state: PipelineState, deps: GraphDependencies | None = None) -> dict:
    """컨텍스트 + 질의로 LLM 답변 생성."""
    settings = deps.settings if deps else get_settings()

    # 2026.07.16(sooyeon.choi) 수정 - 프로바이더 선택을 레지스트리에 위임 (3단계)
    #   (OpenAI: 요청별 인스턴스 / 로컬 vLLM: 싱글턴 재사용 정책은 레지스트리 팩토리가 유지)
    llm_service = resolve_llm_from_state(state, settings)

    # available_numbers: assemble_context가 실제로 포함한 청크 수 기준으로 계산.
    # reranked_chunks 전체 수를 쓰면 토큰 초과로 잘린 청크 번호까지 포함되어
    # LLM이 컨텍스트에 없는 번호를 인용하는 환각이 발생한다.
    n = state.get("context_chunk_count") or len(state.get("reranked_chunks", [])) or 1
    available_numbers = ", ".join(f"[{i + 1}]" for i in range(n))

    # build_rag_messages()로 메시지 구성 (RAG_SYSTEM_PROMPT 사용)
    messages = build_rag_messages(
        question=state["original_query"],
        # 2026.10.19 수정 - 사진 답변: 사진 후보가 있으면 컨텍스트 뒤에 "[관련 이미지 후보]" 목록을 붙인다
        context=context_with_images(state.get("final_context", ""), state.get("image_candidates") or []),
        available_numbers=available_numbers,
    )

    try:
        answer_parts = []
        usage = {}
        async for token in llm_service.chat_stream(messages, usage_sink=usage):
            answer_parts.append(token)
            await adispatch_custom_event("rag_token", {"token": token})
        answer = "".join(answer_parts).strip()
        # LLMService.chat()에서 이미 strip_thinking() 처리됨
        # logger.info(f"답변 생성 완료: {len(answer)}자")
        # 2026.05.22(sooyeon.choi) 추가 - 노드 출력 로깅
        # logger.info(f"[generate_answer 출력] 답변 앞 200자: {answer[:200]!r}")

        # [DEBUG] 컨텍스트 및 전체 답변 확인 (검색 품질 디버깅용)
        # context_preview = (state.get("final_context", "") or "")[:500]
        # logger.debug(f"[DEBUG] 컨텍스트 앞 500자:\n{context_preview}")
        # logger.debug(f"[DEBUG] 생성된 전체 답변:\n{answer}")

        # 2026.06.16(sooyeon.choi) 추가 - SCR-006 토큰 사용량 캡처 (비스트리밍 전용)
        usage = usage or None
        if not answer:
            return {
                "error": "LLM이 빈 응답을 반환했습니다.",
                "usage": usage,
                "outcome_code": "llm_error",
            }
        if is_no_context_answer(answer):
            return {
                "generated_answer": get_user_message(UserMessageType.NO_CONTEXT),
                "thinking": None,
                "citations": [],
                "error": None,
                "usage": usage,
                "outcome_code": "no_context",
            }
        # 2026.06.19(sooyeon.choi) 추가 - 정상 답변 생성 결과 코드 기록
        return {
            "generated_answer": answer,
            "thinking": None,
            "error": None,
            "usage": usage,
            "outcome_code": "success",
        }
    except Exception as e:
        logger.error(f"LLM 답변 생성 실패: {e}")
        return {
            "error": f"LLM 답변 생성 실패: {str(e)}",
            "usage": None,
            "outcome_code": "llm_error",
        }

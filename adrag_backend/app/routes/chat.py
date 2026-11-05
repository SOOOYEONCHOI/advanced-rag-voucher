"""
채팅 API 엔드포인트.

vLLM 서버를 통한 LLM 채팅 및 헬스체크 엔드포인트를 제공합니다.
"""

from fastapi import APIRouter, HTTPException

from app.models.llm_models import (
    ChatRequest,
    ChatResponse,
    CompletionRequest,
    CompletionResponse,
    SimpleMessageRequest,
    SimpleMessageResponse,
)
from app.services.llm_service import LLMService

router = APIRouter(prefix="/chat", tags=["Chat"])

# 서비스 인스턴스 (앱 시작 시 1회 생성)
_llm_service = LLMService()


@router.post("/", response_model=SimpleMessageResponse)
async def simple_chat(request: SimpleMessageRequest):
    """
    간단 채팅 API (프론트엔드용).

    { "message": "질문" } → { "response": "답변", "model": "..." }
    """
    try:
        answer = await _llm_service.generate_answer(
            request.message,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
        )
        return SimpleMessageResponse(
            response=answer,
            model=_llm_service.settings.vllm_model_name,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM 서버 호출 실패: {str(e)}")


@router.get("/models")
async def get_model_info():
    """현재 사용 중인 모델 정보 반환."""
    return {
        "model": _llm_service.settings.vllm_model_name,
        "embedding_model": _llm_service.settings.embedding_model_name,
    }


@router.post("/completions", response_model=ChatResponse)
async def chat_completions(request: ChatRequest):
    """
    채팅 완성 API.

    OpenAI 호환 메시지 형식으로 요청하면 vLLM을 통해 응답을 생성합니다.
    """
    try:
        messages = [m.model_dump() for m in request.messages]
        response = await _llm_service.chat(
            messages,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
        )
        return response
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM 서버 호출 실패: {str(e)}")


@router.post("/generate", response_model=CompletionResponse)
async def generate(request: CompletionRequest):
    """
    단순 텍스트 생성 API.

    프롬프트를 받아 답변 텍스트를 반환합니다.
    """
    try:
        answer = await _llm_service.generate_answer(request.prompt)
        return CompletionResponse(
            model=_llm_service.settings.vllm_model_name,
            text=answer,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM 서버 호출 실패: {str(e)}")


@router.get("/health")
async def llm_health():
    """vLLM 서버 상태 확인."""
    status = await _llm_service.health_check()
    return status

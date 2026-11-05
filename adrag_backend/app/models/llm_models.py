"""
LLM 요청/응답 Pydantic 스키마.

OpenAI 호환 API 형식에 맞춘 모델 정의입니다.
"""

from typing import List, Optional
from pydantic import BaseModel, Field


# ── 요청 모델 ────────────────────────────────────────────


class ChatMessage(BaseModel):
    """단일 채팅 메시지."""
    role: str = Field(..., description="system | user | assistant")
    content: str


class ChatRequest(BaseModel):
    """클라이언트 → FastAPI 채팅 요청."""
    messages: List[ChatMessage]
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    stream: bool = False


class CompletionRequest(BaseModel):
    """단순 텍스트 완성 요청."""
    prompt: str
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None


class SimpleMessageRequest(BaseModel):
    """프론트엔드용 간단 메시지 요청."""
    message: str
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None


# ── 응답 모델 ────────────────────────────────────────────


class SimpleMessageResponse(BaseModel):
    """프론트엔드용 간단 메시지 응답."""
    response: str
    model: str


class ChatChoice(BaseModel):
    """응답 선택지."""
    index: int = 0
    message: ChatMessage
    finish_reason: Optional[str] = None


class UsageInfo(BaseModel):
    """토큰 사용량."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatResponse(BaseModel):
    """FastAPI → 클라이언트 채팅 응답."""
    model: str
    choices: List[ChatChoice]
    usage: Optional[UsageInfo] = None


class CompletionResponse(BaseModel):
    """단순 텍스트 완성 응답."""
    model: str
    text: str
    usage: Optional[UsageInfo] = None

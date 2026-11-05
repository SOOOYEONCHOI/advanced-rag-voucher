"""
LLM 프로바이더 인터페이스.

2026.07.16(sooyeon.choi) 추가 - 3단계 리팩토링: 인터페이스 도입
기준 구현: app/services/llm_service.py LLMService (local vLLM / OpenAI)
신규 프로바이더(Gemini, Claude 등)는 이 계약을 만족하는 서비스를 작성해
app/core/registry.py의 LLM 레지스트리에 등록하면 노드 수정 없이 편입된다.
"""

from typing import Any, AsyncGenerator, Dict, List, Optional, Protocol, runtime_checkable


@runtime_checkable
class LLMProvider(Protocol):
    """대화형 LLM 호출 계약 (비스트리밍/스트리밍)."""

    async def chat(
        self,
        messages: List[Dict[str, str]],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Any:
        """OpenAI 호환 메시지를 전달하고 ChatResponse(choices/usage)를 반환한다."""
        ...

    def chat_stream(
        self,
        messages: List[Dict[str, str]],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        usage_sink: Optional[Dict[str, int]] = None,
    ) -> AsyncGenerator[str, None]:
        """토큰 단위 스트리밍. usage_sink에 최종 토큰 사용량을 기록한다."""
        ...

"""
OpenAI API 비동기 클라이언트.

httpx.AsyncClient를 사용하여 OpenAI /v1/chat/completions 엔드포인트를 호출합니다.
vLLM LLMClient와 동일한 인터페이스를 제공하여 교체 가능합니다.
"""

# 2026.05.27(sooyeon.choi) 스트리밍 기능 추가 - AsyncGenerator import 추가
from typing import Any, AsyncGenerator, Dict, List, Optional

# 2026.07.16(sooyeon.choi) 수정 - 요청마다 AsyncClient 생성 → 공유 클라이언트 재사용 (B6)
from app.core.http import get_shared_async_client
from app.utils.log.log import LoggingLogger

logger = LoggingLogger().getLogger(__name__)

OPENAI_BASE_URL = "https://api.openai.com"


class OpenAILLMClient:
    """OpenAI API 비동기 클라이언트."""

    def __init__(
        self,
        api_key: str,
        model: str,
        timeout: float = 120.0,
        max_tokens: int = 2048,
        temperature: float = 0.1,
    ) -> None:
        self.base_url = OPENAI_BASE_URL
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.default_max_tokens = max_tokens
        self.default_temperature = temperature

    def _headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    async def chat(
        self,
        messages: List[Dict[str, str]],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        OpenAI /v1/chat/completions 호출 (non-streaming).

        Returns:
            OpenAI 호환 응답 dict
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self.default_temperature,
            "max_tokens": max_tokens or self.default_max_tokens,
        }

        # 2026.07.16(sooyeon.choi) 수정 - 공유 AsyncClient + 요청 단위 타임아웃 (B6)
        client = get_shared_async_client()
        resp = await client.post(
            f"{self.base_url}/v1/chat/completions",
            json=payload,
            headers=self._headers(),
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        logger.debug(
            f"OpenAI response: model={data.get('model')}, "
            f"tokens={data.get('usage', {}).get('total_tokens', '?')}"
        )
        return data

    # 2026.05.27(sooyeon.choi) 스트리밍 기능 추가 - OpenAI 스트리밍 호출 메서드
    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> AsyncGenerator[str, None]:
        """
        OpenAI /v1/chat/completions 스트리밍 호출.

        Yields:
            SSE data 라인 (text/event-stream 형식, LLMClient.chat_stream과 동일 포맷)
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self.default_temperature,
            "max_tokens": max_tokens or self.default_max_tokens,
            "stream": True,
            # 2026.06.19(sooyeon.choi) 추가 - 스트림 마지막 청크에서 토큰 사용량 수집
            "stream_options": {"include_usage": True},
            **kwargs,
        }

        # 2026.07.16(sooyeon.choi) 수정 - 공유 AsyncClient + 요청 단위 타임아웃 (B6)
        client = get_shared_async_client()
        async with client.stream(
            "POST",
            f"{self.base_url}/v1/chat/completions",
            json=payload,
            headers=self._headers(),
            timeout=self.timeout,
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    yield line

    async def health_check(self) -> bool:
        """OpenAI API 상태 확인."""
        try:
            # 2026.07.16(sooyeon.choi) 수정 - 공유 AsyncClient 재사용 (B6)
            resp = await get_shared_async_client().get(
                f"{self.base_url}/v1/models",
                headers=self._headers(),
                timeout=10.0,
            )
            return resp.status_code == 200
        except Exception as e:
            logger.error(f"OpenAI health check failed: {e}")
            return False

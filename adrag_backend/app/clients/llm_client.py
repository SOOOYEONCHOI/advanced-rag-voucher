"""
vLLM OpenAI-compatible API 비동기 클라이언트.

httpx.AsyncClient를 사용하여 vLLM 서버의 /v1/chat/completions 엔드포인트를 호출합니다.
모델명, URL 등은 모두 Settings에서 주입받으므로 모델 교체 시 환경변수만 변경하면 됩니다.

사용 예시:
    client = LLMClient(settings)
    response = await client.chat([
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "안녕하세요"},
    ])
"""

from typing import Any, AsyncGenerator, Dict, List, Optional

from app.core.config import Settings
# 2026.07.16(sooyeon.choi) 수정 - 요청마다 AsyncClient 생성 → 공유 클라이언트 재사용
from app.core.http import get_shared_async_client
from app.utils.log.log import LoggingLogger

logger = LoggingLogger().getLogger(__name__)


class LLMClient:
    """vLLM OpenAI-compatible 비동기 클라이언트."""

    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.vllm_api_url.rstrip("/")
        self.model = settings.vllm_model_name
        self.api_key = settings.vllm_api_key
        self.timeout = settings.vllm_timeout
        self.default_max_tokens = settings.vllm_max_tokens
        self.default_temperature = settings.vllm_temperature

    # ── 내부 헬퍼 ────────────────────────────────────────

    def _headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    # ── Chat Completions ─────────────────────────────────

    async def chat(
        self,
        messages: List[Dict[str, str]],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        /v1/chat/completions 호출 (non-streaming).

        Returns:
            OpenAI 호환 응답 dict
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self.default_temperature,
            "max_tokens": max_tokens or self.default_max_tokens,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": False},
            "stop": ["</think>", "Thinking Process:"],
            **kwargs,
        }

        # 2026.07.16(sooyeon.choi) 수정 - 공유 AsyncClient + 요청 단위 타임아웃
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
            f"LLM response: model={data.get('model')}, "
            f"tokens={data.get('usage', {}).get('total_tokens', '?')}"
        )
        return data

    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> AsyncGenerator[str, None]:
        """
        /v1/chat/completions 스트리밍 호출.

        Yields:
            SSE data 라인 (text/event-stream 형식)
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self.default_temperature,
            "max_tokens": max_tokens or self.default_max_tokens,
            "stream": True,
            # 2026.06.19(sooyeon.choi) 추가 - 스트림 마지막 청크에서 토큰 사용량 수집
            "stream_options": {"include_usage": True},
            "chat_template_kwargs": {"enable_thinking": False},
            "stop": ["</think>", "Thinking Process:"],
            **kwargs,
        }

        # 2026.07.16(sooyeon.choi) 수정 - 공유 AsyncClient + 요청 단위 타임아웃
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

    # ── 헬스체크 ─────────────────────────────────────────

    async def health_check(self) -> bool:
        """vLLM 서버 상태 확인."""
        try:
            # 2026.07.16(sooyeon.choi) 수정 - 공유 AsyncClient 재사용
            resp = await get_shared_async_client().get(
                f"{self.base_url}/v1/models",
                headers=self._headers(),
                timeout=10.0,
            )
            return resp.status_code == 200
        except Exception as e:
            logger.error(f"vLLM health check failed: {e}")
            return False

    async def list_models(self) -> List[str]:
        """vLLM에 로드된 모델 목록 조회."""
        try:
            # 2026.07.16(sooyeon.choi) 수정 - 공유 AsyncClient 재사용
            resp = await get_shared_async_client().get(
                f"{self.base_url}/v1/models",
                headers=self._headers(),
                timeout=10.0,
            )
            resp.raise_for_status()
            data = resp.json()
            return [m["id"] for m in data.get("data", [])]
        except Exception:
            return []

"""
평가 전용 Ollama LLM judge 클라이언트.

httpx만 사용하므로 신규 의존성 없음.
vLLM LLMClient와 달리 chat_template_kwargs 등 vLLM 전용 필드를 보내지 않는다.
"""

import logging
from typing import Optional

import httpx

from app.services.llm_service import LLMService

logger = logging.getLogger(__name__)


class OllamaJudgeClient:
    """Ollama OpenAI-compatible API 비동기 클라이언트."""

    def __init__(
        self,
        base_url: str = "http://49.247.45.119:11434",
        model: str = "qwen3:14b",
        timeout: float = 60.0,
    ):
        self._url = f"{base_url.rstrip('/')}/v1/chat/completions"
        self._model = model
        self._timeout = timeout

    async def judge(self, prompt: str, max_tokens: int = 16) -> Optional[str]:
        """프롬프트를 Ollama에 전송하고 <think> 블록을 제거한 텍스트를 반환한다.

        연결 실패 또는 HTTP 오류 시 None을 반환한다.
        """
        payload = {
            "model": self._model,
            # /no_think: Qwen3 thinking 모드 비활성화 (속도 우선)
            "messages": [{"role": "user", "content": "/no_think\n\n" + prompt}],
            "max_tokens": max_tokens,
            "temperature": 0.0,
            "stream": False,
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(self._url, json=payload)
                resp.raise_for_status()
                raw = resp.json()["choices"][0]["message"]["content"]
        except httpx.ConnectError:
            logger.error(f"Ollama 연결 실패: {self._url} — Ollama가 실행 중인지 확인하세요.")
            return None
        except Exception as exc:
            logger.error(f"Ollama 호출 오류: {exc}")
            return None

        # 혹시 남아 있는 <think> 블록 제거 (LLMService 재사용)
        text, _ = LLMService.strip_thinking(raw)
        return text.strip()
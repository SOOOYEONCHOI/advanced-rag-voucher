"""LLM 어댑터 — 로컬 vLLM + OpenAI 이중 백엔드 (LLMPort 구현).

- backend="vllm"  : 기존 LLMClient (Qwen3-8B, 무료) — 테스트셋 생성·1차 대량 평가
- backend="openai": OpenAILLMClient — 정밀 judge (API 키는 호출 시 주입)
(reference app/evaluation/adapters/llm_adapter.py 이식 — import 경로만 변경)
"""

from typing import Dict, List, Optional

from app.clients.llm_client import LLMClient
from app.clients.openai_client import OpenAILLMClient
from app.core.config import get_settings

_vllm_client: LLMClient | None = None


def _get_vllm() -> LLMClient:
    global _vllm_client
    if _vllm_client is None:
        _vllm_client = LLMClient(get_settings())
    return _vllm_client


class EvalLLM:
    """LLMPort 구현."""

    def __init__(
        self,
        openai_api_key: Optional[str] = None,
        openai_model: str = "gpt-4.1-mini",
    ) -> None:
        self._openai_api_key = openai_api_key
        self._openai_model = openai_model

    async def chat(
        self,
        messages: List[Dict[str, str]],
        *,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        backend: str = "vllm",
    ) -> str:
        """메시지를 보내고 응답 텍스트(content)를 반환한다."""
        if backend == "openai":
            if not self._openai_api_key:
                raise ValueError("OpenAI 백엔드에는 openai_api_key가 필요합니다")
            client = OpenAILLMClient(
                api_key=self._openai_api_key,
                model=self._openai_model,
            )
            data = await client.chat(
                messages, temperature=temperature, max_tokens=max_tokens
            )
        else:
            data = await _get_vllm().chat(
                messages, temperature=temperature, max_tokens=max_tokens
            )
        return data["choices"][0]["message"]["content"] or ""

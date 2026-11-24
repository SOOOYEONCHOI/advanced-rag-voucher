"""LLM 어댑터 — 로컬 vLLM + OpenAI 이중 백엔드 (LLMPort 구현).

- backend="vllm"  : 기존 LLMClient (기본은 챗봇 LLM, 무료) — 테스트셋 생성·1차 대량 평가
                    2026.11.18(sooyeon.choi) 수정 - vllm_api_url·vllm_model로 다른 vLLM 모델 지정 가능
- backend="openai": OpenAILLMClient — 정밀 judge (API 키는 호출 시 주입)
(reference app/evaluation/adapters/llm_adapter.py 이식 — import 경로만 변경)
"""

from typing import Dict, List, Optional, Tuple

from app.clients.llm_client import LLMClient
from app.clients.openai_client import OpenAILLMClient
from app.core.config import get_settings

_vllm_client: LLMClient | None = None
# 2026.11.18(sooyeon.choi) 추가 - 데이터셋 생성 모델 선택용 (주소, 모델명)별 클라이언트
_vllm_clients_by_target: Dict[Tuple[str, str], LLMClient] = {}


def _get_vllm(api_url: Optional[str] = None, model: Optional[str] = None) -> LLMClient:
    global _vllm_client
    if not api_url and not model:
        if _vllm_client is None:
            _vllm_client = LLMClient(get_settings())
        return _vllm_client
    settings = get_settings()
    key = (api_url or settings.vllm_api_url, model or settings.vllm_model_name)
    if key not in _vllm_clients_by_target:
        _vllm_clients_by_target[key] = LLMClient(
            settings.model_copy(update={"vllm_api_url": key[0], "vllm_model_name": key[1]})
        )
    return _vllm_clients_by_target[key]


class EvalLLM:
    """LLMPort 구현."""

    def __init__(
        self,
        openai_api_key: Optional[str] = None,
        openai_model: str = "gpt-4.1-mini",
        vllm_api_url: Optional[str] = None,
        vllm_model: Optional[str] = None,
    ) -> None:
        self._openai_api_key = openai_api_key
        self._openai_model = openai_model
        # 2026.11.18(sooyeon.choi) 추가 - 비우면 챗봇 기본 LLM(VLLM_API_URL·VLLM_MODEL_NAME)
        self._vllm_api_url = vllm_api_url
        self._vllm_model = vllm_model

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
            data = await _get_vllm(self._vllm_api_url, self._vllm_model).chat(
                messages, temperature=temperature, max_tokens=max_tokens
            )
        return data["choices"][0]["message"]["content"] or ""

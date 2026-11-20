"""
LLM 서비스 레이어.

비즈니스 로직을 담당하며, LLMClient를 통해 vLLM 서버와 통신합니다.
추후 RAG 파이프라인 연동 시 이 레이어에서 검색 결과를 조합하여 LLM에 전달합니다.
"""

import json
import re
# 2026.05.27(sooyeon.choi) 스트리밍 기능 추가 - AsyncGenerator import 추가
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple, Union

from app.clients.llm_client import LLMClient
from app.clients.openai_client import OpenAILLMClient
from app.core.config import Settings, get_settings
from app.models.llm_models import (
    ChatMessage,
    ChatChoice,
    ChatResponse,
    UsageInfo,
)
from app.prompts.templates import DEFAULT_SYSTEM_PROMPT

from app.utils.log.log import LoggingLogger

# 로거 초기화
# 2026.07.16(sooyeon.choi) 수정 - 모듈별 named logger 적용
logger = LoggingLogger().getLogger(__name__)

# 로컬 vLLM 전용 모듈 수준 싱글턴 — 설정이 동일하므로 요청마다 재생성할 필요 없음
_local_llm_service: "LLMService | None" = None


def get_local_llm_service() -> "LLMService":
    """로컬 vLLM LLMService 싱글턴을 반환한다."""
    global _local_llm_service
    if _local_llm_service is None:
        _local_llm_service = LLMService()
    return _local_llm_service


class LLMService:
    """LLM 호출 비즈니스 로직."""

    # 2026.07.16(sooyeon.choi) 수정 - 미사용 _THINK_BLOCK_RE 제거
    #   strip_thinking()은 문자열 split 방식만 사용하며 이 정규식은 참조된 적 없음
    # "Thinking Process:" 또는 "Reasoning:" 로 시작하는 접두 블록 제거
    _THINKING_PREFIX_RE = re.compile(
        r"^(Thinking Process:|Reasoning:).*?(?=\n\S|\Z)", re.DOTALL | re.IGNORECASE
    )
    # 2026.05.27(sooyeon.choi) 스트리밍 기능 추가 - <think> 부분 태그 감지용 접두 튜플
    _THINK_OPEN_PREFIXES = tuple("<think>"[:i] for i in range(1, len("<think>")))

    def __init__(
        self,
        settings: Optional[Settings] = None,
        *,
        openai_api_key: Optional[str] = None,
        openai_model: Optional[str] = None,
    ) -> None:
        self.settings = settings or get_settings()
        if openai_api_key and openai_model:
            self.client: Union[LLMClient, OpenAILLMClient] = OpenAILLMClient(
                api_key=openai_api_key,
                model=openai_model,
                timeout=self.settings.vllm_timeout,
                max_tokens=self.settings.vllm_max_tokens,
                temperature=self.settings.vllm_temperature,
            )
            self._is_openai = True
        else:
            self.client = LLMClient(self.settings)
            self._is_openai = False

    @classmethod
    def strip_thinking(cls, text: str) -> Tuple[str, Optional[str]]:
        """
        thinking 블록을 제거하고 최종 답변만 반환합니다.

        처리 대상:
          - <think>...</think> 블록 (여는 태그 없는 경우 포함)
          - "Thinking Process:" / "Reasoning:" 접두 블록

        Returns:
            (답변 텍스트, thinking 텍스트 or None)
        """
        thinking: Optional[str] = None

        # 1단계: </think> 기준으로 분리
        if "</think>" in text:
            parts = text.split("</think>", 1)
            thinking = parts[0].replace("<think>", "").strip()
            text = parts[1].strip()

        # 2단계: "Thinking Process:" / "Reasoning:" 접두 블록 제거
        match = cls._THINKING_PREFIX_RE.match(text)
        if match:
            thinking = thinking or match.group(0).strip()
            text = text[match.end():].strip()

        return text, thinking

    async def chat(
        self,
        messages: List[Dict[str, str]],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> ChatResponse:
        """
        채팅 메시지를 vLLM에 전달하고 구조화된 응답을 반환합니다.

        시스템 프롬프트가 없으면 기본값을 자동 삽입합니다.
        """
        # 시스템 프롬프트가 없으면 기본값 삽입
        if not messages or messages[0].get("role") != "system":
            messages = [
                {"role": "system", "content": DEFAULT_SYSTEM_PROMPT},
                *messages,
            ]

        raw = await self.client.chat(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        # OpenAI 호환 응답을 내부 모델로 변환
        choices = []
        for c in raw.get("choices", []):
            msg = c.get("message", {})
            content, _ = self.strip_thinking(msg.get("content", ""))
            choices.append(
                ChatChoice(
                    index=c.get("index", 0),
                    message=ChatMessage(
                        role=msg.get("role", "assistant"),
                        content=content,
                    ),
                    finish_reason=c.get("finish_reason"),
                )
            )

        usage_raw = raw.get("usage", {})
        usage = UsageInfo(
            prompt_tokens=usage_raw.get("prompt_tokens", 0),
            completion_tokens=usage_raw.get("completion_tokens", 0),
            total_tokens=usage_raw.get("total_tokens", 0),
        )

        return ChatResponse(
            model=raw.get("model", self.settings.vllm_model_name),
            choices=choices,
            usage=usage,
        )

    async def generate_answer(
        self,
        question: str,
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """단순 질의응답 — 질문을 받아 답변 텍스트만 반환합니다."""
        response = await self.chat(
            [{"role": "user", "content": question}],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if response.choices:
            return response.choices[0].message.content
        return ""

    # 2026.05.27(sooyeon.choi) 스트리밍 기능 추가 - SSE 토큰 스트리밍 메서드
    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        usage_sink: Optional[Dict[str, int]] = None,
    ) -> AsyncGenerator[str, None]:
        """
        스트리밍 채팅 — SSE 라인을 파싱하여 delta content token을 하나씩 yield합니다.
        <think>...</think> 블록은 토큰 단위 상태 기반 필터로 실시간 제거합니다.
        """
        if not messages or messages[0].get("role") != "system":
            messages = [
                {"role": "system", "content": DEFAULT_SYSTEM_PROMPT},
                *messages,
            ]

        async def _parse_tokens() -> AsyncGenerator[str, None]:
            """SSE data 라인 → delta content 토큰 추출."""
            async for line in self.client.chat_stream(
                messages, temperature=temperature, max_tokens=max_tokens
            ):
                if not line.startswith("data: "):
                    continue
                data = line[6:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                    # 2026.06.19(sooyeon.choi) 추가 - 선택지 없는 최종 usage 청크 수집
                    usage = chunk.get("usage")
                    if usage_sink is not None and usage:
                        usage_sink.update({
                            "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                            "completion_tokens": int(
                                usage.get("completion_tokens") or 0
                            ),
                            "total_tokens": int(usage.get("total_tokens") or 0),
                        })
                    delta = chunk.get("choices", [{}])[0].get("delta", {}).get("content")
                    if delta:
                        yield delta
                except Exception:
                    continue

        # thinking 블록 실시간 필터
        in_think = False
        buf = ""
        async for token in _parse_tokens():
            buf += token
            if not in_think:
                if "<think>" in buf:
                    pre = buf[:buf.index("<think>")]
                    if pre:
                        yield pre
                    buf = buf[buf.index("<think>"):]
                    in_think = True
                elif not buf.endswith(self._THINK_OPEN_PREFIXES):
                    yield buf
                    buf = ""
            if in_think and "</think>" in buf:
                buf = buf[buf.index("</think>") + len("</think>"):]
                in_think = False
                if buf and not buf.endswith(self._THINK_OPEN_PREFIXES):
                    yield buf
                    buf = ""
        if buf and not in_think:
            yield buf

    async def health_check(self) -> Dict[str, Any]:
        """vLLM 서버 상태 및 모델 정보를 반환합니다."""
        is_healthy = await self.client.health_check()
        models = []
        if is_healthy and hasattr(self.client, "list_models"):
            models = await self.client.list_models()
        return {
            "vllm_status": "healthy" if is_healthy else "unavailable",
            "vllm_url": self.settings.vllm_api_url,
            "loaded_models": models,
        }

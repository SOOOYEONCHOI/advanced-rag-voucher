"""LLM stream usage collection tests."""

import asyncio
import logging
import sys
import types

# 2026.06.19(sooyeon.choi) 추가 - LLM 서비스 단위 테스트의 설정·로깅 의존성 격리
config_module = types.ModuleType("app.core.config")
config_module.Settings = object
config_module.get_settings = lambda: types.SimpleNamespace(
    vllm_model_name="local",
)
sys.modules["app.core.config"] = config_module

log_module = types.ModuleType("app.utils.log.log")


class _TestLoggingLogger:
    # 2026.07.16(sooyeon.choi) 수정 - named logger 지원 API 변경 반영 (B16)
    def getLogger(self, name=None):
        return logging.getLogger("test.llm_stream")


log_module.LoggingLogger = _TestLoggingLogger
sys.modules["app.utils.log.log"] = log_module

from app.services.llm_service import LLMService


class _FakeStreamingClient:
    async def chat_stream(self, *_args, **_kwargs):
        yield 'data: {"choices":[{"delta":{"content":"답변"}}]}'
        yield (
            'data: {"choices":[],"usage":{"prompt_tokens":12,'
            '"completion_tokens":3,"total_tokens":15}}'
        )
        yield "data: [DONE]"


def test_chat_stream_collects_final_usage_chunk():
    async def run_stream():
        service = object.__new__(LLMService)
        service.client = _FakeStreamingClient()
        usage = {}
        tokens = []

        # 2026.06.19(sooyeon.choi) 추가 - 마지막 usage 청크와 답변 토큰 동시 수집 검증
        async for token in service.chat_stream(
            [{"role": "system", "content": "system"}],
            usage_sink=usage,
        ):
            tokens.append(token)
        return tokens, usage

    tokens, usage = asyncio.run(run_stream())
    assert tokens == ["답변"]
    assert usage == {
        "prompt_tokens": 12,
        "completion_tokens": 3,
        "total_tokens": 15,
    }

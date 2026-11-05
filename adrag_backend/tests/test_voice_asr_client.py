from types import SimpleNamespace

import pytest

from app.clients import voice_asr_client
from app.clients.voice_asr_client import VoiceAsrClient, VoiceAsrError


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class _HttpClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def post(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.response


def _settings(**overrides):
    values = {
        "voice_asr_api_url": "http://asr.internal:8007",
        "voice_asr_api_key": None,
        "vllm_api_key": "shared-vllm-key",
        "voice_asr_model_name": "Qwen/Qwen3-ASR-1.7B",
        "voice_asr_timeout": 30.0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.asyncio
async def test_transcribe_uses_openai_transcription_contract(monkeypatch):
    http_client = _HttpClient(_Response({"text": "보호구 착용 기준"}))
    monkeypatch.setattr(voice_asr_client, "get_shared_async_client", lambda: http_client)

    result = await VoiceAsrClient(_settings()).transcribe(
        b"audio-bytes", "question.webm", "audio/webm", language="ko"
    )

    assert result == "보호구 착용 기준"
    args, kwargs = http_client.calls[0]
    assert args == ("http://asr.internal:8007/v1/audio/transcriptions",)
    assert kwargs["data"] == {"model": "Qwen/Qwen3-ASR-1.7B", "language": "ko"}
    assert kwargs["files"]["file"] == ("question.webm", b"audio-bytes", "audio/webm")
    assert kwargs["headers"] == {"Authorization": "Bearer shared-vllm-key"}


@pytest.mark.asyncio
async def test_transcribe_rejects_empty_model_result(monkeypatch):
    monkeypatch.setattr(voice_asr_client, "get_shared_async_client", lambda: _HttpClient(_Response({"text": " "})))

    with pytest.raises(VoiceAsrError, match="empty transcription"):
        await VoiceAsrClient(_settings()).transcribe(b"audio", "question.wav", "audio/wav")


def test_transcription_url_does_not_duplicate_v1():
    client = VoiceAsrClient(_settings(voice_asr_api_url="http://asr.internal:8007/v1"))
    assert client.transcription_url == "http://asr.internal:8007/v1/audio/transcriptions"

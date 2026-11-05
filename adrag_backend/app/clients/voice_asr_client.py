"""OpenAI transcription API client for the dedicated Qwen3-ASR vLLM server."""

from typing import Optional

import httpx

from app.core.config import Settings
from app.core.http import get_shared_async_client


class VoiceAsrError(RuntimeError):
    """Raised when the ASR server cannot return a usable transcription."""


class VoiceAsrClient:
    def __init__(self, settings: Settings) -> None:
        if not settings.voice_asr_api_url:
            raise ValueError("VOICE_ASR_API_URL is not configured")
        self.base_url = settings.voice_asr_api_url.rstrip("/")
        self.api_key = settings.voice_asr_api_key or settings.vllm_api_key
        self.model = settings.voice_asr_model_name
        self.timeout = settings.voice_asr_timeout

    @property
    def transcription_url(self) -> str:
        suffix = "/audio/transcriptions"
        return f"{self.base_url}{suffix}" if self.base_url.endswith("/v1") else f"{self.base_url}/v1{suffix}"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    async def transcribe(
        self,
        audio: bytes,
        filename: str,
        content_type: str,
        *,
        language: Optional[str] = None,
    ) -> str:
        data = {"model": self.model}
        if language:
            data["language"] = language

        try:
            response = await get_shared_async_client().post(
                self.transcription_url,
                data=data,
                files={"file": (filename, audio, content_type)},
                headers=self._headers(),
                timeout=self.timeout,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise VoiceAsrError("ASR server request failed") from exc

        try:
            payload = response.json()
            text = payload.get("text") if isinstance(payload, dict) else None
        except ValueError as exc:
            raise VoiceAsrError("ASR server returned invalid JSON") from exc
        if not isinstance(text, str) or not text.strip():
            raise VoiceAsrError("ASR server returned an empty transcription")
        return text.strip()

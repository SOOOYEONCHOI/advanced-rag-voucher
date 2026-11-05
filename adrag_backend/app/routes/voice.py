"""Voice proof-of-concept routes. Audio is not persisted."""

from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.clients.voice_asr_client import VoiceAsrClient, VoiceAsrError
from app.core.config import get_settings
from app.utils.security import get_current_principal

router = APIRouter(prefix="/voice", tags=["Voice"])
_SUPPORTED_AUDIO_TYPES = {"audio/mpeg", "audio/mp4", "audio/ogg", "audio/wav", "audio/webm"}
_settings = get_settings()
_asr_client = VoiceAsrClient(_settings) if _settings.voice_asr_api_url else None


@router.post("/transcriptions")
async def create_transcription(
    audio: UploadFile = File(...),
    language: Optional[str] = Form(default=None),
    _principal: dict = Depends(get_current_principal),
):
    """Transcribe a short browser-recorded audio file through Qwen3-ASR."""
    content_type = (audio.content_type or "").split(";", 1)[0].lower()
    if content_type not in _SUPPORTED_AUDIO_TYPES:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Unsupported audio format")
    payload = await audio.read()
    if not payload:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Audio file is empty")
    if len(payload) > _settings.voice_max_upload_bytes:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Audio file is too large")
    if _asr_client is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Voice transcription is unavailable")
    try:
        text = await _asr_client.transcribe(payload, audio.filename or "recording.webm", content_type, language=language)
    except VoiceAsrError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Voice transcription failed") from exc
    return {"text": text, "language": language}

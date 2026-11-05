from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes import voice
from app.utils.security import get_current_principal


class _AsrClient:
    def __init__(self, text="보호구 착용 기준을 알려줘"):
        self.text = text
        self.calls = []

    async def transcribe(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.text


def _client():
    app = FastAPI()
    app.include_router(voice.router, prefix="/api")
    app.dependency_overrides[get_current_principal] = lambda: {"user_id": "user01"}
    return TestClient(app)


def test_transcription_forwards_audio_to_asr(monkeypatch):
    asr = _AsrClient()
    monkeypatch.setattr(voice, "_asr_client", asr)

    response = _client().post(
        "/api/voice/transcriptions",
        files={"audio": ("question.webm", b"voice", "audio/webm")},
        data={"language": "ko"},
    )

    assert response.status_code == 200
    assert response.json() == {"text": "보호구 착용 기준을 알려줘", "language": "ko"}
    assert asr.calls[0][0] == (b"voice", "question.webm", "audio/webm")


def test_transcription_requires_authentication():
    app = FastAPI()
    app.include_router(voice.router, prefix="/api")
    response = TestClient(app).post(
        "/api/voice/transcriptions",
        files={"audio": ("question.webm", b"voice", "audio/webm")},
    )
    assert response.status_code == 401


def test_transcription_rejects_unsupported_media_type():
    response = _client().post(
        "/api/voice/transcriptions",
        files={"audio": ("question.txt", b"not audio", "text/plain")},
    )
    assert response.status_code == 415


def test_transcription_rejects_empty_audio():
    response = _client().post(
        "/api/voice/transcriptions",
        files={"audio": ("question.webm", b"", "audio/webm")},
    )
    assert response.status_code == 400


def test_transcription_disabled_without_asr(monkeypatch):
    monkeypatch.setattr(voice, "_asr_client", None)
    response = _client().post(
        "/api/voice/transcriptions",
        files={"audio": ("question.webm", b"voice", "audio/webm;codecs=opus")},
    )
    assert response.status_code == 503


def test_transcription_reports_asr_failure(monkeypatch):
    class _FailedAsr:
        async def transcribe(self, *args, **kwargs):
            raise voice.VoiceAsrError("unavailable")

    monkeypatch.setattr(voice, "_asr_client", _FailedAsr())
    response = _client().post(
        "/api/voice/transcriptions",
        files={"audio": ("question.webm", b"voice", "audio/webm;codecs=opus")},
    )
    assert response.status_code == 502

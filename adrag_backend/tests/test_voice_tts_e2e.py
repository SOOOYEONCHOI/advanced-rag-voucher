"""Optional test against a running Qwen3-TTS (vLLM-Omni) server.

Settings are read from the repository-root .env (process environment wins).
VOICE_TTS_E2E_TEXT_PATH points to a JSON object {"<id>": "<sentence>"}; each sentence is one test case:
VOICE_TTS_E2E_TEXT_PATH=tests/fixtures/stt/expected.json pytest -m voice tests/test_voice_tts_e2e.py -s --noconftest

Speaking style: VOICE_TTS_INSTRUCTIONS (style/emotion text) and VOICE_TTS_SPEED (0.25-4.0) are sent when set.

Each case:
1. POST /v1/audio/speech and measure latency
2. Check the returned WAV header (sample rate / channels / duration)
3. Optionally save the WAV to VOICE_TTS_E2E_OUTPUT_DIR for listening
4. Round-trip: transcribe the WAV with the ASR server and compare by CER (VOICE_TTS_E2E_MAX_CER, default 0.15).
   Skipped when VOICE_ASR_API_URL is not configured.
"""

import json
import time
from pathlib import Path

import httpx
import pytest

from voice_e2e_utils import cer, describe_wav, env, make_latency_report, openai_audio_endpoint, resolve_path

latency_report = make_latency_report("TTS")


def _sentences() -> list[tuple[str, str]]:
    text_path = env("VOICE_TTS_E2E_TEXT_PATH")
    if not text_path:
        return []
    return list(json.loads(resolve_path(text_path).read_text(encoding="utf-8")).items())


def _api_key(name: str) -> str:
    return env(name) or env("VLLM_API_KEY", "EMPTY")


def _transcribe(audio: bytes, filename: str) -> str:
    response = httpx.post(
        openai_audio_endpoint(env("VOICE_ASR_API_URL"), "/audio/transcriptions"),
        data={"model": env("VOICE_ASR_MODEL_NAME", "Qwen/Qwen3-ASR-1.7B"), "language": "ko"},
        files={"file": (filename, audio, "audio/wav")},
        headers={"Authorization": f"Bearer {_api_key('VOICE_ASR_API_KEY')}"},
        timeout=float(env("VOICE_ASR_TIMEOUT", "90")),
    )
    assert response.status_code == 200, f"ASR round-trip failed: {response.text}"
    return response.json().get("text", "").strip()


@pytest.mark.voice
@pytest.mark.parametrize("case", _sentences() or [None], ids=lambda c: c[0] if c else "unconfigured")
def test_qwen3_tts_synthesizes_configured_sentence(case, latency_report):
    if case is None:
        pytest.skip("VOICE_TTS_E2E_TEXT_PATH is not configured")
    case_id, sentence = case

    endpoint = openai_audio_endpoint(env("VOICE_TTS_API_URL", "http://127.0.0.1:8008"), "/audio/speech")
    payload = {
        "model": env("VOICE_TTS_MODEL_NAME", "Qwen3-TTS-1.7B"),
        "input": sentence,
        "voice": env("VOICE_TTS_VOICE", "sohee"),
        "language": "Korean",
        "response_format": "wav",
    }
    if env("VOICE_TTS_INSTRUCTIONS"):
        payload["instructions"] = env("VOICE_TTS_INSTRUCTIONS")
    if env("VOICE_TTS_SPEED"):
        payload["speed"] = float(env("VOICE_TTS_SPEED"))

    started = time.perf_counter()
    response = httpx.post(
        endpoint,
        json=payload,
        headers={"Authorization": f"Bearer {_api_key('VOICE_TTS_API_KEY')}"},
        timeout=float(env("VOICE_TTS_TIMEOUT", "120")),
    )
    latency = time.perf_counter() - started

    assert response.status_code == 200, response.text
    assert response.headers.get("content-type", "").startswith("audio/"), response.headers.get("content-type")
    audio = response.content
    audio_info, duration = describe_wav(audio)
    assert duration > 0.3, f"synthesized audio is too short: {audio_info}"
    latency_report.append((duration, latency))
    print(f"\n[{case_id}] {sentence}\n  {audio_info}\n  latency={latency:.3f}s RTF={latency / duration:.3f}")

    filename = f"tts_{Path(case_id).stem}.wav"
    output_dir = env("VOICE_TTS_E2E_OUTPUT_DIR")
    if output_dir:
        output_path = resolve_path(output_dir) / filename
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(audio)
        print(f"  saved: {output_path}")

    if not env("VOICE_ASR_API_URL"):
        return
    transcript = _transcribe(audio, filename)
    max_cer = float(env("VOICE_TTS_E2E_MAX_CER", "0.15"))
    score = cer(sentence, transcript)
    print(f"  ASR round-trip: {transcript} (CER={score:.3f})")
    assert score <= max_cer, f"CER {score:.3f} > {max_cer}: input={sentence!r} asr={transcript!r}"

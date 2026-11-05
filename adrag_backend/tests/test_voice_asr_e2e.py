"""Optional test against a running Qwen3-ASR vLLM server.

Settings are read from the repository-root .env (process environment wins).
VOICE_ASR_E2E_AUDIO_PATH may point to a single WAV file or a directory of WAV files:
pytest -m voice tests/test_voice_asr_e2e.py -s --noconftest

Expected transcripts are read from expected.json next to the WAV file ({"<file name>": "<text>"}).
They are compared by CER after removing whitespace/punctuation (VOICE_ASR_E2E_MAX_CER, default 0.1).
VOICE_ASR_E2E_EXPECTED_TEXT is a substring check used only for files without an expected.json entry.
"""

import json
import time
from pathlib import Path

import httpx
import pytest

from voice_e2e_utils import cer, describe_wav, env, make_latency_report, openai_audio_endpoint, resolve_path

latency_report = make_latency_report("ASR")


def _audio_fixtures() -> list[Path]:
    audio_path = env("VOICE_ASR_E2E_AUDIO_PATH")
    if not audio_path:
        return []
    path = resolve_path(audio_path)
    if path.is_dir():
        return sorted(path.glob("*.wav"), key=lambda p: (len(p.stem), p.stem))
    return [path]


def _expected_transcript(path: Path) -> str | None:
    expected_file = path.parent / "expected.json"
    if not expected_file.is_file():
        return None
    return json.loads(expected_file.read_text(encoding="utf-8")).get(path.name)


@pytest.mark.voice
@pytest.mark.parametrize("fixture", _audio_fixtures() or [None], ids=lambda p: p.name if p else "unconfigured")
def test_qwen3_asr_transcribes_configured_fixture(fixture, latency_report):
    if fixture is None:
        pytest.skip("VOICE_ASR_E2E_AUDIO_PATH is not configured")
    if not fixture.is_file():
        pytest.fail(f"VOICE_ASR_E2E_AUDIO_PATH does not exist: {fixture}")

    endpoint = openai_audio_endpoint(env("VOICE_ASR_API_URL", "http://127.0.0.1:8007"), "/audio/transcriptions")
    expected_text = env("VOICE_ASR_E2E_EXPECTED_TEXT")
    api_key = env("VOICE_ASR_API_KEY") or env("VLLM_API_KEY", "EMPTY")
    audio_info, duration = describe_wav(fixture)

    with fixture.open("rb") as audio_file:
        started = time.perf_counter()
        response = httpx.post(
            endpoint,
            data={"model": env("VOICE_ASR_MODEL_NAME", "Qwen/Qwen3-ASR-1.7B"), "language": "ko"},
            files={"file": (fixture.name, audio_file, "audio/wav")},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=float(env("VOICE_ASR_TIMEOUT", "90")),
        )
        latency = time.perf_counter() - started

    assert response.status_code == 200, response.text
    text = response.json().get("text", "").strip()
    latency_report.append((duration, latency))
    print(f"\n[{fixture.name}] {audio_info}\n  -> {text}\n  latency={latency:.3f}s RTF={latency / duration:.3f}")
    assert text

    expected_transcript = _expected_transcript(fixture)
    if expected_transcript:
        max_cer = float(env("VOICE_ASR_E2E_MAX_CER", "0.1"))
        score = cer(expected_transcript, text)
        print(f"  expected: {expected_transcript} (CER={score:.3f})")
        assert score <= max_cer, f"CER {score:.3f} > {max_cer}: expected={expected_transcript!r} actual={text!r}"
    elif expected_text:
        assert expected_text in text

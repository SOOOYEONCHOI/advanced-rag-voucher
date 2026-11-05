"""Shared helpers for the optional voice (STT/TTS) E2E tests."""

import io
import os
import re
import wave
from pathlib import Path

import pytest
from dotenv import dotenv_values

BACKEND_ROOT = Path(__file__).resolve().parents[1]
_ENV = {**dotenv_values(BACKEND_ROOT.parent / ".env"), **os.environ}


def env(name: str, default: str | None = None) -> str | None:
    """Repository-root .env 값을 읽는다(프로세스 환경변수가 우선)."""
    return _ENV.get(name) or default


def resolve_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else BACKEND_ROOT / path


def openai_audio_endpoint(base_url: str, suffix: str) -> str:
    base_url = base_url.rstrip("/")
    return f"{base_url}{suffix}" if base_url.endswith("/v1") else f"{base_url}/v1{suffix}"


def describe_wav(source: Path | bytes) -> tuple[str, float]:
    """ffprobe 대체: WAV 헤더에서 포맷/길이 정보를 읽는다(ffmpeg 미설치 환경 대응)."""
    with wave.open(str(source) if isinstance(source, Path) else io.BytesIO(source), "rb") as wav:
        rate = wav.getframerate()
        duration = wav.getnframes() / rate
        info = f"codec=pcm_s{wav.getsampwidth() * 8}le sample_rate={rate} channels={wav.getnchannels()} duration={duration:.2f}s"
        return info, duration


def normalize(text: str) -> str:
    return re.sub(r"[\W_]+", "", text).lower()


def cer(reference: str, hypothesis: str) -> float:
    """공백/문장부호를 제거한 뒤 문자 단위 편집거리 / 기준 길이."""
    ref, hyp = normalize(reference), normalize(hypothesis)
    previous = list(range(len(hyp) + 1))
    for i, ref_char in enumerate(ref, 1):
        current = [i]
        for j, hyp_char in enumerate(hyp, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ref_char != hyp_char)))
        previous = current
    return previous[-1] / max(len(ref), 1)


def make_latency_report(label: str):
    """(오디오 길이, 응답 시간)을 모아 모듈 종료 시 요약을 출력하는 module fixture를 만든다."""

    @pytest.fixture(scope="module")
    def latency_report():
        records: list[tuple[float, float]] = []
        yield records
        if not records:
            return
        latencies = [latency for _, latency in records]
        total_audio = sum(duration for duration, _ in records)
        print(
            f"\n[{label} latency] files={len(records)} avg={sum(latencies) / len(latencies):.3f}s "
            f"min={min(latencies):.3f}s max={max(latencies):.3f}s RTF={sum(latencies) / total_audio:.3f}"
        )

    return latency_report

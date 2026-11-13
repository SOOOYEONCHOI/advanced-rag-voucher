"""DWG → DXF 변환기 (2026.11.12(sooyeon.choi) 도면 파싱 기능 추가).

LibreDWG(GPLv3)는 라이브러리로 링크하지 않고 별도 프로세스(dwg2dxf)로만 호출한다.
작업별 임시 폴더·제한 시간·메모리 상한(Linux)을 두고, 업로드 파일은 신뢰하지 않는 입력으로 본다.
변환기를 바꿀 때는 ``Converter``를 구현해 ``get_converter``에 더한다.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Protocol

from .common import DrawingError, warning

_MAX_LOG_LINES = 20


@dataclass
class ConvertResult:
    dxf_path: str
    tool: str
    version: Optional[str]
    elapsed_ms: int
    exit_code: int
    warnings: list[dict] = field(default_factory=list)
    log_tail: list[str] = field(default_factory=list)


class Converter(Protocol):
    name: str

    def convert(self, src: str, out_dir: str) -> ConvertResult: ...


def _limit_memory(max_mb: int):
    """Linux 자식 프로세스 주소 공간 상한. Windows(로컬 개발)는 적용하지 않는다."""
    if os.name != "posix":
        return None

    def apply() -> None:  # pragma: no cover - 자식 프로세스에서 실행
        import resource

        limit = max_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))

    return apply


class LibreDwgConverter:
    name = "libredwg"

    def __init__(self, binary: str = "dwg2dxf", timeout_sec: int = 120, max_mem_mb: int = 2048) -> None:
        self.binary = binary
        self.timeout_sec = timeout_sec
        self.max_mem_mb = max_mem_mb

    def version(self) -> Optional[str]:
        try:
            done = subprocess.run([self.binary, "--version"], capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            return None
        out = (done.stdout or done.stderr or "").strip().splitlines()
        return out[0].strip() if out else None

    def convert(self, src: str, out_dir: str) -> ConvertResult:
        if not shutil.which(self.binary) and not Path(self.binary).is_file():
            raise DrawingError("E_CONVERT_FAILED", f"변환기 실행 파일을 찾을 수 없습니다: {self.binary}")
        # 변환기는 작업 폴더(cwd=out)에서 실행하므로 상대 경로를 넘기면 경로가 겹친다 → 절대 경로로 바꿔 넘긴다
        out = Path(out_dir).resolve()
        out.mkdir(parents=True, exist_ok=True)
        # 입력은 작업 폴더로 복사해 원본 경로·파일명(공백·한글)을 명령줄에 넘기지 않는다
        work_src = out / "input.dwg"
        shutil.copyfile(src, work_src)
        dxf_path = out / "converted.dxf"
        dxf_path.unlink(missing_ok=True)
        started = time.perf_counter()
        try:
            done = subprocess.run(
                [self.binary, "-y", "-o", str(dxf_path), str(work_src)],
                cwd=str(out), capture_output=True, text=True, errors="replace",
                timeout=self.timeout_sec, env={"PATH": os.environ.get("PATH", ""), "LANG": "C.UTF-8"},
                preexec_fn=_limit_memory(self.max_mem_mb),
            )
        except subprocess.TimeoutExpired as exc:
            raise DrawingError("E_CONVERT_TIMEOUT", f"{self.timeout_sec}초") from exc
        finally:
            work_src.unlink(missing_ok=True)
        elapsed = int((time.perf_counter() - started) * 1000)
        log = [line for line in (done.stderr or "").splitlines() + (done.stdout or "").splitlines() if line.strip()]
        if done.returncode != 0 or not dxf_path.exists() or dxf_path.stat().st_size == 0:
            raise DrawingError("E_CONVERT_FAILED", f"종료 코드 {done.returncode}: {' / '.join(log[-3:])[:300]}")
        warned = [line for line in log if "warning" in line.lower() or "error" in line.lower()]
        warnings = [warning("W_CONVERTER_WARN", "변환기가 경고를 남겼습니다.", count=len(warned))] if warned else []
        return ConvertResult(
            dxf_path=str(dxf_path), tool=self.name, version=self.version(), elapsed_ms=elapsed,
            exit_code=done.returncode, warnings=warnings, log_tail=log[-_MAX_LOG_LINES:],
        )


def get_converter(settings) -> Converter:
    return LibreDwgConverter(
        binary=getattr(settings, "libredwg_bin", "dwg2dxf"),
        timeout_sec=int(getattr(settings, "dwg_convert_timeout_sec", 120)),
        max_mem_mb=int(getattr(settings, "dwg_convert_max_mem_mb", 2048)),
    )

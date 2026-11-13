"""LibreOffice UNO Worker를 격리 실행하는 Excel 시트 미리보기 서비스."""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from pathlib import Path


logger = logging.getLogger(__name__)

# 2026.10.28(woojin.jung) 추가 - 강조·인쇄영역 방식 변경 시 이전 PDF 캐시를 자동 무효화하는 버전
SHEET_PREVIEW_RENDERER_VERSION = "2026-10-28-v1"
_cache_locks: dict[str, threading.Lock] = {}
_cache_locks_guard = threading.Lock()


class SheetPreviewError(RuntimeError):
    pass


class SheetPreviewValidationError(SheetPreviewError):
    pass


class SheetPreviewSheetNotFoundError(SheetPreviewError):
    pass


class SheetPreviewTimeoutError(SheetPreviewError):
    pass


def _cleanup_stale_jobs(work_root: Path, max_age_seconds: int = 86400) -> None:
    cutoff = time.time() - max_age_seconds
    for candidate in work_root.glob("job-*"):
        try:
            if candidate.is_symlink() or not candidate.is_dir() or candidate.stat().st_mtime >= cutoff:
                continue
            shutil.rmtree(candidate)
        except OSError:
            continue


def _terminate_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "posix":
        os.killpg(process.pid, signal.SIGKILL)
    else:
        process.kill()
    process.wait(timeout=5)


# 2026.10.28(woojin.jung) 추가 - 원본 변경·시트·범위·렌더러 버전을 반영한 충돌 없는 PDF 캐시 키 생성
def _build_cache_key(source_path: Path, sheet_name: str, source_range: str) -> str:
    source_stat = source_path.stat()
    fingerprint = "\0".join(
        (
            SHEET_PREVIEW_RENDERER_VERSION,
            str(source_path.resolve()),
            str(source_stat.st_size),
            str(source_stat.st_mtime_ns),
            sheet_name,
            source_range,
        )
    )
    return hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()


def _get_cache_lock(cache_key: str) -> threading.Lock:
    with _cache_locks_guard:
        return _cache_locks.setdefault(cache_key, threading.Lock())


def _read_cached_pdf(cache_path: Path, ttl_seconds: int) -> bytes | None:
    try:
        cache_stat = cache_path.stat()
        if time.time() - cache_stat.st_mtime > ttl_seconds:
            cache_path.unlink(missing_ok=True)
            return None
        data = cache_path.read_bytes()
        if not data.startswith(b"%PDF"):
            cache_path.unlink(missing_ok=True)
            return None
        os.utime(cache_path, None)
        return data
    except FileNotFoundError:
        return None
    except OSError:
        return None


# 2026.10.28(woojin.jung) 추가 - TTL 만료 및 최대 용량 초과 캐시를 오래된 순서로 자동 정리
def _cleanup_preview_cache(cache_root: Path, ttl_seconds: int, max_bytes: int) -> None:
    now = time.time()
    entries: list[tuple[Path, os.stat_result]] = []
    for candidate in cache_root.glob("*.pdf"):
        try:
            if candidate.is_symlink() or not candidate.is_file():
                continue
            candidate_stat = candidate.stat()
            if now - candidate_stat.st_mtime > ttl_seconds:
                candidate.unlink(missing_ok=True)
                continue
            entries.append((candidate, candidate_stat))
        except OSError:
            continue

    total_bytes = sum(candidate_stat.st_size for _, candidate_stat in entries)
    # 2026.10.28(woojin.jung) 추가 - 설정 용량보다 작은 로컬 마운트에서도 최소 16MB 여유 공간 보존
    disk_usage = shutil.disk_usage(cache_root)
    disk_safe_max_bytes = total_bytes + max(0, disk_usage.free - 16 * 1024 * 1024)
    effective_max_bytes = min(max_bytes, disk_safe_max_bytes)
    for candidate, candidate_stat in sorted(entries, key=lambda item: item[1].st_mtime):
        if total_bytes <= effective_max_bytes:
            break
        try:
            candidate.unlink(missing_ok=True)
            total_bytes -= candidate_stat.st_size
        except OSError:
            continue


def _write_cached_pdf(cache_path: Path, data: bytes) -> None:
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{cache_path.stem}-",
            suffix=".tmp",
            dir=cache_path.parent,
            delete=False,
        ) as cache_file:
            temp_path = Path(cache_file.name)
            cache_file.write(data)
            cache_file.flush()
            os.fsync(cache_file.fileno())
        os.replace(temp_path, cache_path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def _render_sheet_preview(
    source_path: Path,
    sheet_name: str,
    source_range: str,
    *,
    work_root: Path,
    worker_path: Path,
    python_executable: str,
    soffice_executable: str,
    timeout_seconds: int,
) -> bytes:
    if not worker_path.is_file():
        raise SheetPreviewError("시트 미리보기 Worker를 찾을 수 없습니다.")
    if not Path(python_executable).is_file() and not shutil.which(python_executable):
        raise SheetPreviewError("UNO 시스템 Python을 찾을 수 없습니다.")
    if not Path(soffice_executable).is_file() and not shutil.which(soffice_executable):
        raise SheetPreviewError("LibreOffice 실행 파일을 찾을 수 없습니다.")

    # 2026.10.28(woojin.jung) 수정 - 용량이 작은 호스트 공유 마운트에서는 작업 상태만 관리하고
    # LibreOffice 원본 복사·프로필·PDF 출력은 충분한 공간의 컨테이너 로컬 임시 디스크에서 처리
    with tempfile.TemporaryDirectory(prefix="job-", dir=work_root), tempfile.TemporaryDirectory(
        prefix="sheet-preview-runtime-"
    ) as runtime_temp_dir:
        runtime_dir = Path(runtime_temp_dir)
        input_path = runtime_dir / f"input{source_path.suffix.lower()}"
        output_path = runtime_dir / "preview.pdf"
        profile_dir = runtime_dir / "lo-profile"
        shutil.copy2(source_path, input_path)

        command = [
            python_executable,
            str(worker_path),
            "--input", str(input_path),
            "--output", str(output_path),
            "--sheet", sheet_name,
            "--range", source_range,
            "--profile", str(profile_dir),
            "--soffice", soffice_executable,
        ]
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=(os.name == "posix"),
        )
        try:
            _, stderr = process.communicate(timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            _terminate_process(process)
            raise SheetPreviewTimeoutError(f"시트 미리보기 변환 시간이 {timeout_seconds}초를 초과했습니다.") from exc

        if process.returncode == 3:
            detail = stderr.strip() or "시트명 또는 셀 범위가 올바르지 않습니다."
            if "시트를 찾을 수 없습니다" in detail:
                raise SheetPreviewSheetNotFoundError(detail)
            raise SheetPreviewValidationError(detail)
        if process.returncode != 0:
            raise SheetPreviewError(stderr.strip() or "시트 미리보기 변환에 실패했습니다.")
        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise SheetPreviewError("시트 미리보기 PDF가 생성되지 않았습니다.")
        return output_path.read_bytes()


# 2026.10.28(woojin.jung) 추가 - 작업별 임시 디렉터리와 별도 프로세스로 UNO 변환 장애를 FastAPI에서 격리
def create_sheet_preview(
    source_path: Path,
    sheet_name: str,
    source_range: str,
    *,
    work_root: Path,
    python_executable: str,
    soffice_executable: str,
    timeout_seconds: int,
    cache_enabled: bool,
    cache_ttl_hours: int,
    cache_max_bytes: int,
) -> bytes:
    backend_root = Path(__file__).resolve().parents[2]
    # 2026.10.28(woojin.jung) 추가 - 환경변수가 상대경로이면 백엔드 루트를 기준으로 일관되게 해석
    if not work_root.is_absolute():
        work_root = (backend_root / work_root).resolve()
    worker_path = backend_root / "scripts" / "sheet_preview_worker.py"

    work_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    # 2026.10.28(woojin.jung) 추가 - 비정상 종료로 남은 24시간 이전 작업 디렉터리를 다음 요청에서 정리
    _cleanup_stale_jobs(work_root)

    render_arguments = {
        "work_root": work_root,
        "worker_path": worker_path,
        "python_executable": python_executable,
        "soffice_executable": soffice_executable,
        "timeout_seconds": timeout_seconds,
    }
    if not cache_enabled:
        return _render_sheet_preview(source_path, sheet_name, source_range, **render_arguments)

    cache_root = work_root / "cache"
    cache_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    ttl_seconds = cache_ttl_hours * 3600
    cache_key = _build_cache_key(source_path, sheet_name, source_range)
    cache_path = cache_root / f"{cache_key}.pdf"

    # 2026.10.28(woojin.jung) 추가 - 같은 문서·시트·범위의 동시 요청은 한 번만 변환
    with _get_cache_lock(cache_key):
        cached_pdf = _read_cached_pdf(cache_path, ttl_seconds)
        if cached_pdf is not None:
            return cached_pdf

        pdf_bytes = _render_sheet_preview(source_path, sheet_name, source_range, **render_arguments)
        try:
            _write_cached_pdf(cache_path, pdf_bytes)
            _cleanup_preview_cache(cache_root, ttl_seconds, cache_max_bytes)
        except OSError as exc:
            logger.warning("시트 미리보기 캐시 저장 실패 path=%s: %s", cache_path, exc)
        return pdf_bytes

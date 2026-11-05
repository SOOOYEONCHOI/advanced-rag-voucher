"""Parser-local resource store for pull 방식 전달."""

# 2026.08.28(sooyeon.choi) 추가 - push 불가 토폴로지(백엔드가 사설망/루프백)에서
#   백엔드가 직접 가져갈 수 있도록 parse job별 resource를 보관한다.
from __future__ import annotations

import os
import json
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Optional


def resource_root() -> Path:
    return Path(os.environ.get("PARSER_RESOURCE_ROOT", "/app/data/resources")).resolve()


def _job_dir(parse_job_id: str) -> Path:
    return resource_root() / "jobs" / parse_job_id


class ParserResourceStore:
    """parse job 단위로 resource 파일과 metadata를 보관/조회/삭제한다."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, list[dict[str, Any]]] = {}
        self._created_at: dict[str, float] = {}
        self.restore()

    def restore(self) -> int:
        """디스크 manifest를 읽어 재시작 전 pull resource 상태를 복구한다."""
        jobs_root = resource_root() / "jobs"
        restored = 0
        if not jobs_root.exists():
            return restored
        for directory in jobs_root.iterdir():
            manifest = directory / "manifest.json"
            if not directory.is_dir() or not manifest.is_file():
                continue
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
                if data.get("parse_job_id") != directory.name:
                    continue
                entries = data["resources"]
                created_at = float(data["created_at"])
            except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
                continue
            with self._lock:
                self._jobs[directory.name] = entries
                self._created_at[directory.name] = created_at
            restored += 1
        return restored

    def retain(self, result: dict[str, Any], *, parse_job_id: str) -> list[dict[str, Any]]:
        """파싱 결과의 resource 원본을 job 디렉터리로 옮기고 metadata를 등록한다."""
        resources = result.get("resources") or result.get("assets") or []
        if not resources:
            return []

        root = resource_root()
        destination_dir = _job_dir(parse_job_id)
        destination_dir.mkdir(parents=True, exist_ok=True)

        retained: list[dict[str, Any]] = []
        for resource in resources:
            resource_id = resource.get("resource_id") or resource.get("asset_id")
            if not resource_id:
                raise ValueError("Resource metadata requires resource_id")
            source = self._resolve_local_path(resource, root)
            destination = destination_dir / f"{resource_id}{source.suffix}"
            shutil.move(str(source), str(destination))

            entry = {k: v for k, v in resource.items() if k not in ("local_path", "relative_path")}
            entry["resource_id"] = resource_id
            entry["file_name"] = destination.name
            entry["file_size"] = destination.stat().st_size
            entry["status"] = "retained"
            retained.append(entry)

            # 결과 문서에는 parser 로컬 경로를 남기지 않는다.
            resource.pop("local_path", None)
            resource.pop("relative_path", None)
            resource["status"] = "retained"

        created_at = time.time()
        manifest = {
            "parse_job_id": parse_job_id,
            "created_at": created_at,
            "resources": retained,
        }
        temporary_manifest = destination_dir / "manifest.json.tmp"
        temporary_manifest.write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
        )
        temporary_manifest.replace(destination_dir / "manifest.json")

        with self._lock:
            self._jobs[parse_job_id] = retained
            self._created_at[parse_job_id] = created_at
        return retained

    def list(self, parse_job_id: str) -> Optional[list[dict[str, Any]]]:
        with self._lock:
            entries = self._jobs.get(parse_job_id)
            return list(entries) if entries is not None else None

    def path_of(self, parse_job_id: str, resource_id: str) -> Optional[Path]:
        entries = self.list(parse_job_id)
        if entries is None:
            return None
        for entry in entries:
            if entry["resource_id"] == resource_id:
                candidate = (_job_dir(parse_job_id) / entry["file_name"]).resolve()
                # job 디렉터리 밖을 가리키는 이름은 거부한다.
                try:
                    candidate.relative_to(_job_dir(parse_job_id).resolve())
                except ValueError:
                    return None
                return candidate if candidate.is_file() else None
        return None

    def discard(self, parse_job_id: str) -> None:
        with self._lock:
            self._jobs.pop(parse_job_id, None)
            self._created_at.pop(parse_job_id, None)
        shutil.rmtree(_job_dir(parse_job_id), ignore_errors=True)

    def purge_expired(self, ttl_seconds: float) -> list[str]:
        """백엔드가 가져가지 않은 job을 TTL 경과 후 정리한다."""
        now = time.time()
        with self._lock:
            expired = [j for j, created in self._created_at.items() if now - created > ttl_seconds]
        for parse_job_id in expired:
            self.discard(parse_job_id)
        return expired

    @staticmethod
    def _resolve_local_path(resource: dict[str, Any], root: Path) -> Path:
        raw_path = resource.get("local_path") or resource.get("relative_path")
        if not raw_path:
            raise ValueError("Resource local path is missing")
        path = Path(raw_path)
        candidate = path.resolve() if path.is_absolute() else (root / path).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise ValueError("Parser resource path traversal detected") from exc
        if not candidate.is_file():
            raise FileNotFoundError(candidate)
        return candidate


resource_store = ParserResourceStore()

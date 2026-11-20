"""Spreadsheet resource staging, commit, lookup and cleanup."""

# 2026.08.27(sooyeon.choi) 추가 - backend resource 저장 서비스
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import re
import shutil
from uuid import uuid4
from pathlib import Path
from typing import Any

from fastapi import UploadFile

from app.repositories.spreadsheet_resource_repository import SpreadsheetResourceRepository
from app.services.resource_labels import is_displayable, resource_title


_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,160}$")
_HASH_RE = re.compile(r"^(?:sha256:)?([0-9a-fA-F]{64})$")
_MIME_EXTENSIONS = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
    "image/tiff": "tiff",
    "image/bmp": "bmp",
    "image/emf": "emf",
    "image/wmf": "wmf",
    "image/svg+xml": "svg",
    "application/xml": "xml",
    "text/xml": "xml",
    "application/json": "json",
}


# 2026.08.27(sooyeon.choi) 추가 - 분석 계약 정본
ANALYSIS_METHODS = frozenset({"ocr", "vlm", "chart_parser"})
ANALYSIS_STATUS_TO_RESOURCE_STATUS = {
    "pending": "analysis_pending",
    "processing": "analysis_processing",
    "completed": "analysis_completed",
    "failed": "analysis_failed",
}
# 분석 대기 상태로 commit할 resource 유형 (이미지에는 텍스트 정보가 없다)
ANALYSIS_PENDING_RESOURCE_TYPES = frozenset({"image"})
MAX_ANALYSIS_TEXT_LENGTH = 100_000

logger = logging.getLogger(__name__)

# 2026.08.27(sooyeon.choi) 추가 - 실행 중 parse job은 staging TTL cleanup 대상에서 제외한다.
# 값은 등록 시각이며, TTL을 넘긴 항목은 죽은 job으로 보고 제외 대상에서 뺀다.
_ACTIVE_PARSE_JOBS: dict[str, datetime] = {}


class ResourceConflictError(ValueError):
    pass


class SpreadsheetResourceService:
    def __init__(
        self,
        root: str | Path,
        repository: SpreadsheetResourceRepository,
        max_upload_bytes: int,
    ) -> None:
        self.root = Path(root).resolve()
        self.repository = repository
        self.max_upload_bytes = max_upload_bytes
        self.root.mkdir(parents=True, exist_ok=True)

    async def stage_upload(
        self,
        upload: UploadFile,
        *,
        parse_job_id: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        resource_id = metadata["resource_id"]
        document_id = metadata["document_id"]
        self._validate_id("parse_job_id", parse_job_id)
        self._validate_id("resource_id", resource_id)
        self._validate_id("document_id", document_id)
        expected_hash = self._normalize_hash(metadata["content_hash"])
        mime_type = metadata["mime_type"].lower()
        extension = _MIME_EXTENSIONS.get(mime_type)
        if not extension or (upload.content_type and upload.content_type.lower() != mime_type):
            raise ValueError("허용되지 않거나 일치하지 않는 MIME type입니다.")

        # 2026.08.27(sooyeon.choi) 추가 - 같은 parse job에 다른 document ID 혼입을 거부한다.
        for sibling in self.repository.list_by_parse_job(parse_job_id):
            if sibling["document_id"] != document_id:
                raise ResourceConflictError("parse job에 서로 다른 document ID를 섞을 수 없습니다.")

        # 2026.10.16 수정 - Phase 2: staging 테이블과 확정 테이블을 모두 확인
        existing = self.repository.get_staging(resource_id) or self.repository.get(resource_id)
        if existing:
            if existing["document_id"] != document_id or existing["parse_job_id"] != parse_job_id:
                raise ResourceConflictError("resource의 job/document ID가 기존 metadata와 일치하지 않습니다.")
            if self._normalize_hash(existing["content_hash"]) != expected_hash:
                raise ResourceConflictError("동일 resource_id에 다른 content hash를 사용할 수 없습니다.")
            if self.resolve_relative_path(existing["resource_path"]).is_file():
                return existing

        relative_path = Path("staging") / parse_job_id / "originals" / f"{resource_id}.{extension}"
        destination = self.resolve_relative_path(relative_path.as_posix())
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".uploading")
        digest = hashlib.sha256()
        size = 0
        try:
            with open(temporary, "wb") as handle:
                while chunk := await upload.read(1024 * 1024):
                    size += len(chunk)
                    if size > self.max_upload_bytes:
                        raise ValueError("resource가 최대 업로드 크기를 초과했습니다.")
                    digest.update(chunk)
                    handle.write(chunk)
            if digest.hexdigest() != expected_hash:
                raise ValueError("resource content hash가 일치하지 않습니다.")
            temporary.replace(destination)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

        stored = {
            **metadata,
            "parse_job_id": parse_job_id,
            "content_hash": f"sha256:{expected_hash}",
            "resource_path": relative_path.as_posix(),
            "file_size": size,
        }
        self.repository.create_staging(stored)
        # 2026.08.27(sooyeon.choi) 추가 - commit/rollback 전까지 실행 중 job으로 표시한다.
        self.mark_job_active(parse_job_id)
        # 2026.10.16 수정 - Phase 2: 방금 만든 행은 staging 테이블에 있다
        return self.repository.get_staging(resource_id) or stored

    def commit_parse_job(self, parse_job_id: str, document_id: str) -> list[dict[str, Any]]:
        self._validate_id("parse_job_id", parse_job_id)
        self._validate_id("document_id", document_id)
        committed = []
        for item in self.repository.list_by_parse_job(parse_job_id):
            if item["document_id"] != document_id:
                raise ResourceConflictError("parse job과 document ID가 일치하지 않습니다.")
            if item["status"] != "staging":
                committed.append(item)
                continue
            source = self.resolve_relative_path(item["resource_path"])
            extension = source.suffix.lstrip(".")
            digest = self._normalize_hash(item["content_hash"])
            relative = Path("documents") / document_id / "resources" / item["resource_id"] / "original" / f"{digest}.{extension}"
            destination = self.resolve_relative_path(relative.as_posix())
            destination.parent.mkdir(parents=True, exist_ok=True)
            (destination.parent.parent / "renditions").mkdir(exist_ok=True)
            (destination.parent.parent / "analyses").mkdir(exist_ok=True)
            if destination.exists():
                if self._file_hash(destination) != digest:
                    raise ResourceConflictError("commit 대상 original 파일의 hash가 다릅니다.")
                source.unlink(missing_ok=True)
            else:
                shutil.move(str(source), str(destination))
            # 2026.08.27(sooyeon.choi) 수정 - 분석 대기 유형은 analysis_pending으로 commit
            commit_status = (
                "analysis_pending"
                if item["resource_type"] in ANALYSIS_PENDING_RESOURCE_TYPES
                else "committed"
            )
            self.repository.mark_committed(
                item["resource_id"], relative.as_posix(), status=commit_status
            )
            committed.append(self.repository.get(item["resource_id"]))
        shutil.rmtree(self.resolve_relative_path(f"staging/{parse_job_id}"), ignore_errors=True)
        # 2026.08.27(sooyeon.choi) 추가 - commit 완료 job은 cleanup 제외 대상에서 해제한다.
        self.mark_job_finished(parse_job_id)
        logger.info(
            "[RESOURCE][commit] parse_job_id=%s document_id=%s resources=%s",
            parse_job_id,
            document_id,
            len(committed),
        )
        return committed

    def rollback_parse_job(self, parse_job_id: str) -> None:
        self._validate_id("parse_job_id", parse_job_id)
        shutil.rmtree(self.resolve_relative_path(f"staging/{parse_job_id}"), ignore_errors=True)
        self.repository.delete_staging_by_parse_job(parse_job_id)
        # 2026.08.27(sooyeon.choi) 추가 - rollback한 job도 실행 중 목록에서 제거한다.
        self.mark_job_finished(parse_job_id)
        logger.info("[RESOURCE][rollback] parse_job_id=%s", parse_job_id)

    # 2026.08.27(sooyeon.choi) 수정 - 삭제 실패를 재시도 가능한 상태로 기록한다.
    def delete_document_resources(self, document_id: str) -> str:
        """document resource 파일과 metadata를 삭제하고 결과 상태를 반환한다.

        파일 삭제에 실패하면 metadata를 deleted로 바꾸지 않는다. 남은 resource는
        retry_pending_deletions()가 다시 처리하므로 고아 파일이 남지 않는다.
        """
        self._validate_id("document_id", document_id)
        document_root = self.resolve_relative_path(f"documents/{document_id}")
        if document_root.exists():
            try:
                shutil.rmtree(document_root)
            except OSError as exc:
                logger.error(
                    "[RESOURCE][delete] 재시도 대기 document_id=%s error=%s", document_id, exc
                )
                return "pending"
        # 2026.08.27(sooyeon.choi) 수정 - 연결된 분석 결과 metadata도 함께 삭제
        self.repository.delete_analyses_by_document(document_id)
        self.repository.mark_deleted_by_document(document_id)
        logger.info("[RESOURCE][delete] 완료 document_id=%s", document_id)
        return "deleted"

    # 2026.08.27(sooyeon.choi) 추가 - 실패로 남은 삭제 대상과 고아 디렉터리를 정리한다.
    def retry_pending_deletions(self) -> dict[str, int]:
        retried = 0
        removed_orphans = 0
        for document_id in self.repository.list_documents_pending_deletion():
            if self.delete_document_resources(document_id) == "deleted":
                retried += 1
        documents_root = self.resolve_relative_path("documents")
        if documents_root.exists():
            for directory in documents_root.iterdir():
                if not directory.is_dir() or self.repository.list_by_document(directory.name):
                    continue
                try:
                    shutil.rmtree(directory)
                    removed_orphans += 1
                except OSError as exc:
                    logger.error(
                        "[RESOURCE][orphan] 정리 실패 document_id=%s error=%s", directory.name, exc
                    )
        return {"retried_documents": retried, "removed_orphan_dirs": removed_orphans}

    # 2026.08.27(sooyeon.choi) 추가 - 서버 절대 경로를 노출하지 않는 조회 응답 변환
    def list_document_resources(self, document_id: str) -> list[dict[str, Any]]:
        self._validate_id("document_id", document_id)
        fields = (
            "resource_id", "document_id", "resource_type", "content_hash", "mime_type",
            "file_size", "sheet_id", "sheet_name", "from_cell", "to_cell", "linked_block_id",
            "linked_record_ids", "surrounding_range", "surrounding_text", "status", "created_at",
        )
        # 2026.10.19 추가 - 출처 패널 "연결된 이미지"(UI-05·ANS-03): 답변 사진과 같은 제목·역할·표시 가능 여부
        return [
            {
                **{field: item.get(field) for field in fields},
                "download_url": f"/api/spreadsheet-resources/{item['resource_id']}",
                "title": resource_title(item),
                "role": item.get("role_cd"),
                "step_no": item.get("step_no"),
                "step_title": item.get("step_title"),
                "version_no": item.get("version_no"),
                "in_print_area": None if item.get("in_print_area") is None else bool(item.get("in_print_area")),
                "review_status": item.get("review_status"),
                "displayable": is_displayable(item),
            }
            for item in self.repository.list_by_document(document_id)
        ]

    # 2026.08.27(sooyeon.choi) 추가 - 단계 8 REQ-MEDIA-005 분석 결과 등록 계약
    def register_analysis(
        self,
        resource_id: str,
        payload: dict[str, Any],
        result_document: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """resource에 분석 결과를 version별로 연결한다.

        원본 파일과 resource metadata는 덮어쓰지 않고, 결과는 analyses/{version}/에만 쓴다.
        """
        self._validate_id("resource_id", resource_id)
        resource = self.repository.get(resource_id)
        if not resource or resource["status"] == "deleted":
            raise FileNotFoundError(resource_id)

        method = (payload.get("method") or "").lower()
        if method not in ANALYSIS_METHODS:
            raise ValueError(f"지원하지 않는 분석 method입니다: {method!r}")
        status = (payload.get("status") or "pending").lower()
        if status not in ANALYSIS_STATUS_TO_RESOURCE_STATUS:
            raise ValueError(f"지원하지 않는 분석 status입니다: {status!r}")
        confidence = payload.get("confidence")
        if confidence is not None and not 0.0 <= float(confidence) <= 1.0:
            raise ValueError("confidence는 0.0과 1.0 사이여야 합니다.")
        text = payload.get("text")
        if text is not None and len(text) > MAX_ANALYSIS_TEXT_LENGTH:
            raise ValueError("분석 텍스트가 최대 길이를 초과했습니다.")

        version = int(payload.get("analysis_version") or 0) or (
            self.repository.latest_analysis_version(resource_id) + 1
        )
        result_path = None
        if result_document is not None:
            relative = (
                Path("documents") / resource["document_id"] / "resources" / resource_id
                / "analyses" / str(version) / "result.json"
            )
            destination = self.resolve_relative_path(relative.as_posix())
            if destination.exists():
                raise ResourceConflictError("같은 analysis_version 결과가 이미 존재합니다.")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(
                json.dumps(result_document, ensure_ascii=False), encoding="utf-8"
            )
            result_path = relative.as_posix()

        analysis = {
            "analysis_id": payload.get("analysis_id") or f"analysis-{uuid4()}",
            "resource_id": resource_id,
            "document_id": resource["document_id"],
            "analysis_version": version,
            "method": method,
            "model": payload.get("model"),
            "model_version": payload.get("model_version"),
            "prompt_version": payload.get("prompt_version"),
            "pipeline_version": payload.get("pipeline_version"),
            "status": status,
            "result_path": result_path,
            "text": text,
            "confidence": confidence,
        }
        self.repository.create_analysis(analysis)
        self.repository.set_status(resource_id, ANALYSIS_STATUS_TO_RESOURCE_STATUS[status])
        logger.info(
            "[RESOURCE][analysis] resource_id=%s version=%s method=%s status=%s",
            resource_id, version, method, status,
        )
        return self.get_analysis(resource_id, version) or analysis

    def list_analyses(self, resource_id: str) -> list[dict[str, Any]]:
        self._validate_id("resource_id", resource_id)
        return self.repository.list_analyses(resource_id)

    def get_analysis(self, resource_id: str, analysis_version: int) -> dict[str, Any] | None:
        for item in self.list_analyses(resource_id):
            if item["analysis_version"] == analysis_version:
                return item
        return None

    def read_analysis_result(self, resource_id: str, analysis_version: int) -> dict[str, Any] | None:
        analysis = self.get_analysis(resource_id, analysis_version)
        if not analysis or not analysis.get("result_path"):
            return None
        path = self.resolve_relative_path(analysis["result_path"])
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def resolve_resource(self, resource_id: str) -> tuple[dict[str, Any], Path]:
        self._validate_id("resource_id", resource_id)
        metadata = self.repository.get(resource_id)
        if not metadata or metadata["status"] == "deleted":
            raise FileNotFoundError(resource_id)
        # analysis_* 상태에서도 원본 파일 위치는 바뀌지 않는다.
        path = self.resolve_relative_path(metadata["resource_path"])
        if not path.is_file():
            raise FileNotFoundError(resource_id)
        return metadata, path

    def cleanup_expired_staging(self, ttl_hours: int, active_parse_job_ids: set[str] | None = None) -> int:
        # 2026.08.27(sooyeon.choi) 수정 - 인자를 생략하면 실행 중 job을 자동으로 제외한다.
        active = (
            active_parse_job_ids
            if active_parse_job_ids is not None
            else self.active_parse_job_ids(ttl_hours)
        )
        cutoff = datetime.now(timezone.utc) - timedelta(hours=ttl_hours)
        count = 0
        staging_root = self.resolve_relative_path("staging")
        if not staging_root.exists():
            return 0
        for directory in staging_root.iterdir():
            if not directory.is_dir() or directory.name in active:
                continue
            modified = datetime.fromtimestamp(directory.stat().st_mtime, timezone.utc)
            if modified < cutoff:
                self.rollback_parse_job(directory.name)
                count += 1
        return count

    # 2026.08.27(sooyeon.choi) 추가 - 실행 중 parse job 등록/해제 (backend 프로세스 단위)
    @staticmethod
    def mark_job_active(parse_job_id: str) -> None:
        if parse_job_id:
            _ACTIVE_PARSE_JOBS[parse_job_id] = datetime.now(timezone.utc)

    @staticmethod
    def mark_job_finished(parse_job_id: str) -> None:
        _ACTIVE_PARSE_JOBS.pop(parse_job_id, None)

    @staticmethod
    def active_parse_job_ids(max_age_hours: int | None = None) -> set[str]:
        if max_age_hours is None:
            return set(_ACTIVE_PARSE_JOBS)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        return {job_id for job_id, started in _ACTIVE_PARSE_JOBS.items() if started >= cutoff}

    def usage(self) -> dict[str, int]:
        files = [path for path in self.root.rglob("*") if path.is_file()]
        return {"resource_count": len(files), "disk_bytes": sum(path.stat().st_size for path in files)}

    def resolve_relative_path(self, relative_path: str) -> Path:
        candidate = (self.root / relative_path).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("resource path traversal이 감지되었습니다.") from exc
        return candidate

    @staticmethod
    def _validate_id(name: str, value: str) -> None:
        if not _SAFE_ID_RE.fullmatch(value or ""):
            raise ValueError(f"잘못된 {name}입니다.")

    @staticmethod
    def _normalize_hash(value: str) -> str:
        match = _HASH_RE.fullmatch(value or "")
        if not match:
            raise ValueError("content_hash는 SHA-256 형식이어야 합니다.")
        return match.group(1).lower()

    @staticmethod
    def _file_hash(path: Path) -> str:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

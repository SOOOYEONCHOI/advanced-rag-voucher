"""Upload parser-local resources to backend staging storage."""

# 2026.08.27(sooyeon.choi) 추가 - 단계 6 parser → backend resource 전송
from __future__ import annotations

import json
import mimetypes
import os
from pathlib import Path
from typing import Any

import requests
from urllib.parse import urlparse


# 2026.08.28(sooyeon.choi) 추가 - 요청별 콜백 URL 계약
#   파서는 공용이고 백엔드는 여러 개(서버 배포본 / 개발자 PC)일 수 있다.
#   전역 BACKEND_INTERNAL_URL 하나로는 "누가 요청했는지"를 알 수 없어,
#   parse 요청이 callback_url을 실어 보내면 그 백엔드로 회신한다.
#   임의 URL로 내부 API 키가 새 나가지 않도록 allowlist로 제한한다.
def _allowed_callback_urls() -> set[str]:
    raw = os.environ.get("BACKEND_CALLBACK_ALLOWLIST", "")
    allowed = {item.strip().rstrip("/") for item in raw.split(",") if item.strip()}
    default = os.environ.get("BACKEND_INTERNAL_URL", "").strip().rstrip("/")
    if default:
        allowed.add(default)
    return allowed


def resolve_backend_url(requested: str | None) -> str:
    """parse 요청이 전달한 callback URL을 검증해 확정한다. 없으면 환경변수 기본값."""
    default = os.environ.get("BACKEND_INTERNAL_URL", "").strip().rstrip("/")
    if not requested:
        return default

    candidate = requested.strip().rstrip("/")
    parsed = urlparse(candidate)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"Invalid callback URL: {requested}")

    allowed = _allowed_callback_urls()
    if candidate not in allowed:
        raise ValueError(
            f"Callback URL not allowed: {candidate}. "
            "BACKEND_CALLBACK_ALLOWLIST에 등록된 주소만 사용할 수 있습니다."
        )
    return candidate


class BackendResourceUploader:
    def __init__(self, backend_url: str | None = None) -> None:
        # 2026.08.28(sooyeon.choi) 수정 - 요청별 backend_url 주입 (미지정 시 환경변수)
        self.backend_url = (backend_url or os.environ.get("BACKEND_INTERNAL_URL", "")).rstrip("/")
        self.api_key = os.environ.get("BACKEND_INTERNAL_API_KEY", "")
        self.resource_root = Path(os.environ.get("PARSER_RESOURCE_ROOT", "/app/data/resources")).resolve()

    def upload_result_resources(
        self,
        result: dict[str, Any],
        *,
        parse_job_id: str,
        document_id: str | None,
    ) -> None:
        resources = result.get("resources") or result.get("assets") or []
        if not resources:
            return
        if not document_id:
            raise ValueError("Resource upload requires document_id")
        if not self.backend_url or not self.api_key:
            raise RuntimeError("BACKEND_INTERNAL_URL and BACKEND_INTERNAL_API_KEY are required for resource upload")

        for resource in resources:
            path = self._resolve_local_path(resource)
            resource_id = resource.get("resource_id") or resource.get("asset_id")
            content_hash = resource.get("content_hash") or resource.get("original_content_hash")
            mime_type = resource.get("mime_type") or mimetypes.guess_type(path.name)[0]
            if not resource_id or not content_hash or not mime_type:
                raise ValueError("Resource metadata requires resource_id, content_hash and mime_type")
            url = f"{self.backend_url}/internal/ingest-jobs/{parse_job_id}/resources"
            with open(path, "rb") as handle:
                response = requests.post(
                    url,
                    headers={"X-INTERNAL-API-KEY": self.api_key},
                    files={"file": (path.name, handle, mime_type)},
                    data={
                        "resource_id": resource_id,
                        "document_id": document_id,
                        "resource_type": resource.get("resource_type") or "image",
                        "content_hash": content_hash,
                        "mime_type": mime_type,
                        "sheet_id": resource.get("sheet_id") or "",
                        "sheet_name": resource.get("sheet_name") or "",
                        "from_cell": resource.get("from_cell") or "",
                        "to_cell": resource.get("to_cell") or "",
                        "linked_block_id": resource.get("linked_block_id") or "",
                        "linked_record_ids": json.dumps(
                            resource.get("linked_record_ids")
                            or ([resource["linked_record_id"]] if resource.get("linked_record_id") else [])
                        ),
                        "surrounding_range": resource.get("surrounding_range") or "",
                        "surrounding_text": resource.get("surrounding_text") or "",
                    },
                    timeout=(10, 120),
                )
            if response.status_code not in (200, 201):
                raise RuntimeError(
                    f"Backend resource upload failed: http_status={response.status_code}"
                )
            # 2026.08.28(sooyeon.choi) 추가 - backend가 아닌 곳(nginx/SPA 등)에 닿으면
            #   200 + HTML이 돌아와 json()이 "Expecting value"만 남기고 죽는다.
            #   응답 본문이나 callback URL은 로그/예외에 포함하지 않는다.
            try:
                payload = response.json()
            except ValueError as exc:
                raise RuntimeError(
                    "Backend resource upload returned non-JSON: "
                    f"http_status={response.status_code}"
                ) from exc
            if "resource" not in payload:
                raise RuntimeError("Backend resource upload response has no resource field")
            backend_resource = payload["resource"]
            resource["resource_id"] = resource_id
            resource["resource_path"] = backend_resource["resource_path"]
            resource["status"] = backend_resource["status"]
            path.unlink(missing_ok=True)

    def _resolve_local_path(self, resource: dict[str, Any]) -> Path:
        raw_path = resource.get("local_path") or resource.get("relative_path")
        if not raw_path:
            raise ValueError("Resource local path is missing")
        path = Path(raw_path)
        candidate = path.resolve() if path.is_absolute() else (self.resource_root / path).resolve()
        try:
            candidate.relative_to(self.resource_root)
        except ValueError as exc:
            raise ValueError("Parser resource path traversal detected") from exc
        if not candidate.is_file():
            raise FileNotFoundError(candidate)
        return candidate

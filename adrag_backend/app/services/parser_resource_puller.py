"""파서에 보관된 spreadsheet resource를 backend가 회수한다."""

# 2026.08.28(sooyeon.choi) 추가 - pull 방식 resource 전달.
#   백엔드가 사설망/루프백에 있으면 파서가 백엔드로 접속할 수 없다(push 불가).
#   백엔드 → 파서 방향은 이미 열려 있으므로, 그 연결만으로 resource를 가져온다.
from __future__ import annotations

import io
import logging
import os
from typing import Any

import requests

logger = logging.getLogger(__name__)

_RESOURCE_FIELDS = (
    "resource_type",
    "sheet_id",
    "sheet_name",
    "from_cell",
    "to_cell",
    "linked_block_id",
    "surrounding_range",
    "surrounding_text",
)


class _BytesUpload:
    """SpreadsheetResourceService.stage_upload가 기대하는 UploadFile 최소 인터페이스."""

    def __init__(self, data: bytes, content_type: str) -> None:
        self._buffer = io.BytesIO(data)
        self.content_type = content_type

    async def read(self, size: int = -1) -> bytes:
        return self._buffer.read(size)


class ParserResourcePuller:
    def __init__(
        self,
        host: str = "",
        api_key: str = "",
        connect_timeout: int = 10,
        read_timeout: int = 300,
    ) -> None:
        self.host = (host or os.environ.get("DOCLING_PARSER_HOST", "")).rstrip("/")
        self.api_key = api_key or os.environ.get("DOCLING_API_KEY", "")
        self.timeout = (connect_timeout, read_timeout)

    @property
    def _headers(self) -> dict:
        return {"X-API-KEY": self.api_key} if self.api_key else {}

    def list_resources(self, parse_job_id: str) -> list[dict[str, Any]]:
        response = requests.get(
            f"{self.host}/api/job/{parse_job_id}/resources",
            headers=self._headers,
            timeout=self.timeout,
        )
        if response.status_code == 404:
            # 이미지가 없는 문서이거나 push 모드로 처리된 job
            return []
        if response.status_code != 200:
            raise RuntimeError(
                f"파서 resource 목록 조회 실패: {response.status_code} - {response.text[:200]}"
            )
        return response.json().get("resources", [])

    def download(self, parse_job_id: str, resource_id: str) -> bytes:
        response = requests.get(
            f"{self.host}/api/job/{parse_job_id}/resources/{resource_id}",
            headers=self._headers,
            timeout=self.timeout,
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"파서 resource 다운로드 실패: {resource_id} "
                f"{response.status_code} - {response.text[:200]}"
            )
        return response.content

    def discard(self, parse_job_id: str) -> None:
        """수령을 마친 파서 보관본을 정리한다. 실패해도 TTL이 정리하므로 치명적이지 않다."""
        try:
            requests.delete(
                f"{self.host}/api/job/{parse_job_id}/resources",
                headers=self._headers,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            logger.warning(
                "[RESOURCE][pull] 파서 보관본 정리 실패 parse_job_id=%s error=%s", parse_job_id, exc
            )


async def pull_parser_resources(
    resource_service,
    parse_job_id: str,
    document_id: str,
    puller: ParserResourcePuller | None = None,
) -> int:
    """파서 보관본을 내려받아 backend staging에 저장하고, 저장 건수를 반환한다."""
    puller = puller or ParserResourcePuller()
    # 2026.08.28(sooyeon.choi) 추가 - 파서 호스트가 없으면 가져올 곳이 없다.
    #   (로컬 파서 미사용 / push 모드로 이미 저장된 경우)
    if not puller.host:
        logger.debug(
            "[RESOURCE][pull] 파서 호스트 미설정으로 건너뜀 parse_job_id=%s", parse_job_id
        )
        return 0
    entries = puller.list_resources(parse_job_id)
    if not entries:
        return 0

    stored = 0
    for entry in entries:
        mime_type = entry.get("mime_type") or "application/octet-stream"
        payload = puller.download(parse_job_id, entry["resource_id"])
        metadata = {
            "resource_id": entry["resource_id"],
            "document_id": document_id,
            "content_hash": entry["content_hash"],
            "mime_type": mime_type,
            "linked_record_ids": entry.get("linked_record_ids")
            or ([entry["linked_record_id"]] if entry.get("linked_record_id") else []),
        }
        for field in _RESOURCE_FIELDS:
            metadata[field] = entry.get(field)
        metadata["resource_type"] = entry.get("resource_type") or "image"

        await resource_service.stage_upload(
            _BytesUpload(payload, mime_type),
            parse_job_id=parse_job_id,
            metadata=metadata,
        )
        stored += 1

    puller.discard(parse_job_id)
    logger.info(
        "[RESOURCE][pull] parse_job_id=%s document_id=%s resources=%s",
        parse_job_id,
        document_id,
        stored,
    )
    return stored

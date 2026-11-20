"""Spreadsheet resource internal upload and authenticated download APIs."""

# 2026.08.27(sooyeon.choi) 추가 - resource API
from __future__ import annotations

import hmac
import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Body, Depends, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.core.config import get_settings
from app.repositories.database import get_database_manager
from app.repositories.metadata_repository import MetadataRepository
from app.repositories.spreadsheet_resource_repository import SpreadsheetResourceRepository
from app.services.spreadsheet_resource_service import ResourceConflictError, SpreadsheetResourceService
# 2026.11.09(sooyeon.choi) 수정 - 열람 범위는 공통 함수로 판정
from app.utils.security import document_scope, get_current_principal, in_document_scope


router = APIRouter(tags=["spreadsheet-resources"])


def _service() -> SpreadsheetResourceService:
    settings = get_settings()
    root = Path(settings.resource_storage_root)
    if not root.is_absolute():
        root = Path(__file__).resolve().parents[2] / root
    return SpreadsheetResourceService(
        root=root,
        repository=SpreadsheetResourceRepository(),
        max_upload_bytes=settings.resource_max_upload_bytes,
    )


def _verify_internal_key(provided: str) -> None:
    expected = get_settings().resource_internal_api_key
    if not expected:
        raise HTTPException(status_code=503, detail="Resource internal API key is not configured")
    if not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Invalid internal API key")


@router.post("/internal/ingest-jobs/{parse_job_id}/resources", status_code=201)
async def upload_resource(
    parse_job_id: str,
    file: UploadFile = File(...),
    resource_id: str = Form(...),
    document_id: str = Form(...),
    resource_type: str = Form(...),
    content_hash: str = Form(...),
    mime_type: str = Form(...),
    sheet_id: Optional[str] = Form(None),
    sheet_name: Optional[str] = Form(None),
    from_cell: Optional[str] = Form(None),
    to_cell: Optional[str] = Form(None),
    linked_block_id: Optional[str] = Form(None),
    linked_record_ids: str = Form("[]"),
    surrounding_range: Optional[str] = Form(None),
    surrounding_text: Optional[str] = Form(None),
    x_internal_api_key: str = Header(..., alias="X-INTERNAL-API-KEY"),
):
    _verify_internal_key(x_internal_api_key)
    try:
        record_ids = json.loads(linked_record_ids)
        if not isinstance(record_ids, list):
            raise ValueError
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(status_code=400, detail="linked_record_ids must be a JSON array")
    try:
        metadata = await _service().stage_upload(
            file,
            parse_job_id=parse_job_id,
            metadata={
                "resource_id": resource_id,
                "document_id": document_id,
                "resource_type": resource_type,
                "content_hash": content_hash,
                "mime_type": mime_type,
                "sheet_id": sheet_id,
                "sheet_name": sheet_name,
                "from_cell": from_cell,
                "to_cell": to_cell,
                "linked_block_id": linked_block_id,
                "linked_record_ids": record_ids,
                "surrounding_range": surrounding_range,
                "surrounding_text": surrounding_text,
            },
        )
        return {"resource": metadata}
    except ResourceConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# 2026.08.27(sooyeon.choi) 추가 - REQ-MEDIA-005 분석 결과 등록 (내부 서비스 전용)
@router.post("/internal/spreadsheet-resources/{resource_id}/analyses", status_code=201)
async def register_resource_analysis(
    resource_id: str,
    payload: dict = Body(...),
    x_internal_api_key: str = Header(..., alias="X-INTERNAL-API-KEY"),
):
    _verify_internal_key(x_internal_api_key)
    result_document = payload.get("result")
    if result_document is not None and not isinstance(result_document, dict):
        raise HTTPException(status_code=400, detail="result must be a JSON object")
    try:
        analysis = _service().register_analysis(
            resource_id, payload, result_document=result_document
        )
    except ResourceConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Resource not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"analysis": analysis}


# 2026.08.27(sooyeon.choi) 추가 - resource 분석 결과 version별 조회
@router.get("/api/spreadsheet-resources/{resource_id}/analyses")
async def list_resource_analyses(
    resource_id: str,
    principal: dict = Depends(get_current_principal),
):
    service = _service()
    try:
        metadata, _ = service.resolve_resource(resource_id)
    except (FileNotFoundError, ValueError):
        raise HTTPException(status_code=404, detail="Resource not found")
    _authorize_document(metadata["document_id"], principal)
    analyses = service.list_analyses(resource_id)
    return {
        "resource_id": resource_id,
        "resource_status": metadata["status"],
        "total": len(analyses),
        "analyses": analyses,
    }


# 2026.08.27(sooyeon.choi) 추가 - 다운로드와 목록 조회가 동일한 document 권한을 사용한다.
def _authorize_document(document_id: str, principal: dict) -> None:
    settings = get_settings()
    # 2026.10.16 수정 - Phase 2: DB 계층은 경로를 쓰지 않는다(Q-15.7) — 설정 stub과 무관하게 동작
    rows = get_database_manager().execute_query(
        """SELECT d.security_level, c.qdrant_name AS source_collection
           FROM tb_documents d JOIN tb_collections c ON c.collection_id=d.collection_id
           WHERE d.document_id=? AND d.deleted_at IS NULL""",
        (document_id,),
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Document not found")
    document = dict(rows[0])
    if principal.get("is_admin"):
        return
    permissions = MetadataRepository().get_user_permissions(principal["user_id"])
    # 2026.11.09(sooyeon.choi) 수정 - 열람 범위 공통 함수 사용
    if not in_document_scope(document_scope(permissions), document["source_collection"], document["security_level"]):
        raise HTTPException(status_code=403, detail="Resource access denied")


# 2026.08.27(sooyeon.choi) 추가 - document에 연결된 resource 목록 조회 (절대 경로 비노출)
@router.get("/api/documents/{document_id}/spreadsheet-resources")
async def list_document_resources(
    document_id: str,
    version_no: Optional[int] = None,
    principal: dict = Depends(get_current_principal),
):
    _authorize_document(document_id, principal)
    try:
        resources = _service().list_document_resources(document_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid document_id")
    # 2026.11.06(sooyeon.choi) 수정 - 이전 버전 사진이 보존되므로 기본은 현재 적용 버전만(version_no로 특정 버전 조회).
    #   버전 정보가 없는 과거 리소스(version_no NULL)는 그대로 둔다
    if version_no is None:
        rows = get_database_manager().execute_query(
            "SELECT version_no FROM tb_documents WHERE document_id = ?", (document_id,)
        )
        version_no = (dict(rows[0]).get("version_no") if rows else None) or 1
    resources = [r for r in resources if r.get("version_no") in (None, version_no)]
    return {"document_id": document_id, "total": len(resources), "resources": resources}


@router.get("/api/spreadsheet-resources/{resource_id}")
async def download_resource(
    resource_id: str,
    principal: dict = Depends(get_current_principal),
):
    try:
        metadata, path = _service().resolve_resource(resource_id)
    except (FileNotFoundError, ValueError):
        raise HTTPException(status_code=404, detail="Resource not found")

    _authorize_document(metadata["document_id"], principal)
    return FileResponse(
        path=str(path),
        media_type=metadata["mime_type"],
        filename=f"{resource_id}{path.suffix}",
    )

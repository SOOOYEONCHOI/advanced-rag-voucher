"""
문서 수집(Ingest) API 엔드포인트.

파일 업로드 → 파싱 → 청킹 → 임베딩 → Qdrant 적재
"""
# 2026.06.16(sooyeon.choi) 수정
#   open_original_document(): tb_ingest_documents → tb_documents (JOIN tb_collections)
#   delete_document(): tb_ingest_documents → tb_documents
#   list_documents(): upload_timestamp → created_at 매핑

import logging
import asyncio
import os
import shutil
from uuid import uuid4
from pathlib import Path
from typing import List, Optional, Set, Tuple
from urllib.parse import quote

import json
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.repositories.database import get_database_manager
from app.repositories.metadata_repository import MetadataRepository
from app.repositories.document_repository import DocumentRepository
# 2026.10.30(sooyeon.choi) 수정 - 원본 열기 경로 계산용 get_original_file_storage 추가
from app.services.ingest_service import IngestService, get_original_file_storage
from app.services.ingest_jobs import get_ingest_job_manager
from app.repositories.ingest_job_repository import IngestJobRepository
from app.services.manual_display_service import ManualDisplayService
# 2026.10.16 추가 - Phase 1 엑셀 전용 처리기 파일 판별
from app.ingest.file_router import (
    EXCEL_INGEST_EXTENSIONS,
    LEGACY_XLS_EXTENSION,
    ExcelFileRejected,
    is_excel_ingest_extension,
    resolve_parse_route,
)
# 2026.07.16(sooyeon.choi) 수정 - 중복 정의 제거, 공통 모듈의 보안등급 계층 사용 (B10)
from app.utils.security import SECURITY_HIERARCHY as _SECURITY_HIERARCHY
from app.utils.security import get_current_principal
from app.utils.datetime import format_kst_datetime
# 2026.10.19(sooyeon.choi) 추가 - 모델명(product_model) 기본값·검증
from app.ingest.model_name import resolve_upload_model_name, validate_model_name
from app.parsers.document_types import (
    normalize_requested_doc_type,
    validate_document_type_compatibility,
)
# 2026.11.06(sooyeon.choi) 수정 - 이전 버전 복원(UI-12, R1-5, D-22)
from app.services.document_version_restore import (
    BLOCK_MESSAGES as RESTORE_BLOCK_MESSAGES,
    RestoreError,
    document_block_code,
    evaluate_versions,
    job_payload,
    restore_enabled,
    submit_restore,
)
from app.services.embedding_profile import current_profile_id
from app.services.ingest_jobs import RestoreRetryNotAllowed


def _get_user_accessible(principal: dict) -> Optional[Tuple[Set[str], Set[str]]]:
    """비관리자 사용자의 (accessible_collections, allowed_security_levels) 반환.
    관리자이면 None 반환 (전체 허용).
    """
    if principal.get("is_admin"):
        return None
    settings = get_settings()
    permissions = MetadataRepository(settings.sqlite_db_path).get_user_permissions(
        principal["user_id"]
    )
    if not permissions:
        return (set(), set())
    accessible = set(permissions.accessible_collections or [])
    allowed = set(
        _SECURITY_HIERARCHY.get(permissions.max_security_level or "public", ["public"])
    )
    return (accessible, allowed)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ingest", tags=["ingest"])

# 2026.08.27(sooyeon.choi) 수정 - Excel OOXML 지원 확장자와 .xls 거부 정책 통일
from app.parsers.spreadsheet_contract import (
    LEGACY_XLS_UPLOAD_MESSAGE,
    OOXML_SPREADSHEET_EXTENSIONS,
)

SUPPORTED_EXTENSIONS = {
    "pdf", "docx", "doc", "pptx", "ppt",
    *OOXML_SPREADSHEET_EXTENSIONS,
    "png", "jpg", "jpeg", "tiff", "bmp", "webp",
}


# ── Response Schemas ──────────────────────────────────────────────────────────

class IngestJobResponse(BaseModel):
    job_id: str
    status: str
    current_step: str
    result: Optional[dict] = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    # 2026.11.06(sooyeon.choi) 수정 - 작업 유형(upload·replace·restore)과 대상 문서·버전(복원 진행·결과 화면)
    operation_type: Optional[str] = None
    document_id: Optional[str] = None
    from_version_no: Optional[int] = None
    target_version_no: Optional[int] = None


class CollectionsResponse(BaseModel):
    collections: List[str]


class DocumentItem(BaseModel):
    document_id: str
    filename: str
    collection_name: str
    doc_type: Optional[str] = None
    requested_doc_type: Optional[str] = None
    doc_type_source: Optional[str] = None
    total_pages: Optional[int] = None
    chunk_count: Optional[int] = None
    parser_type: Optional[str] = None
    upload_timestamp: Optional[str] = None
    # 2026.06.30(sooyeon.choi) 추가 - 실제 업로더와 개별 삭제 권한 응답
    uploaded_by: Optional[str] = None
    can_delete: bool = False
    # 2026.10.19(sooyeon.choi) 추가 - 모델명·현재 버전·최근 변경일, 모델명 수정 가능 여부(삭제와 같은 규칙)
    product_model: Optional[str] = None
    version_no: Optional[int] = None
    updated_at: Optional[str] = None
    can_edit: bool = False
    # 2026.10.19 추가(sooyeon.choi) - 최신본 변경 처리 중인 버전(없으면 None) — 화면 상태 표시·폴링 복원용
    pending_version_no: Optional[int] = None
    pending_job_id: Optional[str] = None
    # 2026.11.06(sooyeon.choi) 수정 - 적용 순번·진행 중 변경 작업(최신본 변경·복원 공통, queued/running일 때만).
    #   기존 pending_job_id·pending_version_no는 최신본 변경 전용으로 유지(기존 화면 호환)
    activation_revision: Optional[int] = None
    pending_operation: Optional[dict] = None


class VersionJobResponse(BaseModel):
    """2026.10.19 추가 - 최신본 변경 접수 응답(작업 상태는 GET /ingest/jobs/{job_id}로 확인)."""
    job_id: str
    status: str
    current_step: str
    document_id: str
    version_no: int


class DocumentVersionItem(BaseModel):
    version_no: int
    status: str
    is_active: bool
    original_filename: Optional[str] = None
    file_size: Optional[int] = None
    file_format: Optional[str] = None
    parser_type: Optional[str] = None
    processing_engine: Optional[str] = None
    total_pages: Optional[int] = None
    chunk_count: Optional[int] = None
    uploaded_by: Optional[str] = None
    created_at: Optional[str] = None
    activated_at: Optional[str] = None
    retired_at: Optional[str] = None
    job_id: Optional[str] = None
    job_status: Optional[str] = None
    error: Optional[str] = None
    # 2026.11.06(sooyeon.choi) 수정 - 등록자 이름·행별 복원 가능 여부(서버 판정)
    uploaded_by_name: Optional[str] = None
    can_restore: bool = False
    restore_block_code: Optional[str] = None
    restore_block_reason: Optional[str] = None


class DocumentVersionsResponse(BaseModel):
    document_id: str
    product_model: Optional[str] = None
    current_version_no: int
    versions: List[DocumentVersionItem]
    restore_supported: bool = False
    # 2026.11.06(sooyeon.choi) 수정 - 이전 버전 복원 화면(명세 v1.1 4절)
    collection_name: Optional[str] = None
    collection_display_name: Optional[str] = None
    current_original_filename: Optional[str] = None
    activation_revision: int = 1
    total_versions: int = 0
    next_version_no: int = 1
    can_restore: bool = False
    restore_block_code: Optional[str] = None
    restore_block_reason: Optional[str] = None
    pending_operation: Optional[dict] = None


# 2026.11.06(sooyeon.choi) 수정 - 이전 버전 복원 접수 본문·응답, 적용 이력(명세 v1.1 5·7절)
class RestoreVersionRequest(BaseModel):
    expected_current_version_no: int = Field(ge=1)
    expected_activation_revision: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=128)


class RestoreJobResponse(BaseModel):
    job_id: str
    operation_type: str = "restore"
    status: str
    current_step: str
    document_id: str
    from_version_no: Optional[int] = None
    target_version_no: int


class ActivationItem(BaseModel):
    activation_id: int
    operation_type: str
    from_version_no: Optional[int] = None
    to_version_no: int
    activation_revision: int
    activated_by: Optional[str] = None
    activated_by_name: Optional[str] = None
    activated_at: Optional[str] = None


class ActivationsResponse(BaseModel):
    document_id: str
    activations: List[ActivationItem]
    next_before_activation_id: Optional[int] = None


class ModelNameUpdateRequest(BaseModel):
    product_model: str


class ModelNameUpdateResponse(BaseModel):
    document_id: str
    product_model: str
    version_no: Optional[int] = None
    updated_at: Optional[str] = None


class DocumentsResponse(BaseModel):
    documents: List[DocumentItem]
    total: int


# 2026.04.02(sooyeon.choi) - 문서 삭제 기능 추가
class ManualDisplayResolveResponse(BaseModel):
    mapped: bool
    display_filename: str
    display_page: int


class DeleteDocumentResponse(BaseModel):
    status: str
    document_id: str
    deleted_vector_count: int
    remaining_vector_count: int
    reconciled: bool
    message: str


# ── 업로드 공통 (2026.10.19 업로드·최신본 변경 공용으로 분리) ─────────────────────

def _validate_upload_options(filename: Optional[str], parser_type: str, document_type: str, settings_obj):
    """확장자·파서·문서 유형을 검사하고 (확장자, 엑셀 전용 처리 여부, 정규화한 문서 유형)을 돌려준다(400)."""
    ext = (filename or "").rsplit(".", 1)[-1].lower()
    # 2026.10.16 추가 - Phase 1: backend 모드의 엑셀(xlsx·xlsm·xls)은 excel_ingest가 처리하므로
    #   문서 유형·파서 선택을 검사하지 않는다(D-16). 파일 서명은 저장 후 resolve_parse_route로 확인한다.
    excel_ingest_upload = (
        settings_obj.excel_parse_mode == "backend" and is_excel_ingest_extension(filename or "")
    )
    # 2026.08.27(sooyeon.choi) 추가 - 변환 방법을 안내하는 레거시 Excel 오류
    if ext == "xls" and not excel_ingest_upload:
        raise HTTPException(status_code=400, detail=LEGACY_XLS_UPLOAD_MESSAGE)
    if ext not in SUPPORTED_EXTENSIONS and not excel_ingest_upload:
        raise HTTPException(
            status_code=400,
            detail=f"지원하지 않는 파일 형식: .{ext}",
        )
    if parser_type not in ("docling", "pdfplumber"):
        raise HTTPException(
            status_code=400,
            detail="parser_type은 'docling' 또는 'pdfplumber' 이어야 합니다.",
        )
    if parser_type == "pdfplumber" and ext != "pdf" and not excel_ingest_upload:
        raise HTTPException(
            status_code=400,
            detail="pdfplumber는 PDF 파일만 지원합니다.",
        )
    try:
        document_type = normalize_requested_doc_type(document_type)
        if not excel_ingest_upload:
            validate_document_type_compatibility(ext, document_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ext, excel_ingest_upload, document_type


async def _store_upload_tmp(file: UploadFile, job_id: str, ext: str, excel_ingest_upload: bool, settings_obj) -> str:
    """업로드 파일을 작업 대기 폴더에 저장한다. 엑셀 위장·암호 파일은 지우고 400."""
    queue_dir = Path(settings_obj.sqlite_db_path).parent / "ingest_jobs"
    queue_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = str(queue_dir / f"{job_id}.{ext}")
    with open(tmp_path, "wb") as target:
        await asyncio.to_thread(shutil.copyfileobj, file.file, target)

    # 2026.10.16(sooyeon.choi) 추가 - 엑셀 위장·암호 파일은 거부, 임시 파일을 지운다
    if excel_ingest_upload:
        try:
            await asyncio.to_thread(
                resolve_parse_route, tmp_path, settings_obj.excel_parse_mode, file.filename
            )
        except ExcelFileRejected as exc:
            Path(tmp_path).unlink(missing_ok=True)
            raise HTTPException(
                status_code=400, detail=f"엑셀 파일 rejected({exc.reason}): {exc}"
            ) from exc
    return tmp_path


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/upload", response_model=IngestJobResponse, status_code=202)
async def upload_document(
    file: UploadFile = File(...),
    collection_name: str = Form("documents"),
    parser_type: str = Form("docling"),
    document_type: str = Form("auto"),
    chunk_size: Optional[int] = Form(None),
    # 2026.10.16(sooyeon.choi) 추가 - 제품 모델(선택). 엑셀 청크 머리말 [모델 > 시트 > …]과 tb_documents.product_model
    # 2026.10.19(sooyeon.choi) 수정 - 화면 표기 "모델명". 필드 누락 시 파일명 기본값, 명시한 빈 값·공백·100자 초과는 422
    product_model: Optional[str] = Form(None),
    principal: dict = Depends(get_current_principal),
    http_request: Request = None,
):
    """
    문서를 업로드하고 파싱 → 청킹 → 임베딩 → Qdrant 적재까지 실행합니다.

    - **file**: 업로드할 문서 (PDF, DOCX, PPTX 등)
    - **collection_name**: Qdrant 컬렉션 이름 (기본: documents)
    - **parser_type**: 파서 선택 `docling` | `pdfplumber`
    - **chunk_size**: 청크 크기 오버라이드 (선택)
    - **product_model**: 모델명. 생략하면 파일명에서 마지막 확장자를 뺀 값
    """
    # 2026.06.04(sooyeon.choi) 수정 - security_level을 업로드 사용자의 max_security_level에서 자동 결정
    settings_obj = get_settings()
    meta_repo = MetadataRepository(settings_obj.sqlite_db_path)
    user_perm = meta_repo.get_user_permissions(principal["user_id"])
    security_level = user_perm.max_security_level if user_perm else "public"

    # 비관리자: 대상 컬렉션 접근 권한 검증
    user_filter = _get_user_accessible(principal)
    if user_filter is not None:
        accessible, _ = user_filter
        if collection_name not in accessible:
            raise HTTPException(
                status_code=403,
                detail=f"'{collection_name}' 컬렉션에 접근 권한이 없습니다.",
            )

    # 2026.10.19(sooyeon.choi) 추가 - 모델명 검증. FastAPI는 빈 문자열 폼 값을 "필드 없음"으로 바꾸므로
    #   원본 폼에 키가 있었는지로 명시적 빈 값과 누락을 구분한다.
    provided = product_model is not None
    if not provided and http_request is not None:
        provided = "product_model" in (await http_request.form())
    try:
        product_model = resolve_upload_model_name(product_model, file.filename, provided=provided)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # 2026.10.19(sooyeon.choi) 수정 - 파일·옵션 검증과 임시 저장을 최신본 변경 API와 함께 쓰도록 함수로 분리(동작 동일)
    ext, excel_ingest_upload, document_type = _validate_upload_options(
        file.filename, parser_type, document_type, settings_obj
    )

    tmp_path: Optional[str] = None
    try:
        job_id = str(uuid4())
        tmp_path = await _store_upload_tmp(file, job_id, ext, excel_ingest_upload, settings_obj)

        request = dict(
            file_path=tmp_path,
            filename=file.filename,
            collection_name=collection_name,
            parser_type=parser_type,
            document_type=document_type,
            chunk_size=chunk_size,
            uploaded_by=principal["user_id"],
            security_level=security_level,
            product_model=product_model,
        )
        repository = IngestJobRepository(settings_obj.sqlite_db_path)
        await asyncio.to_thread(repository.create, job_id, request, principal["user_id"])
        await get_ingest_job_manager().enqueue(job_id)
        return IngestJobResponse(job_id=job_id, status="queued", current_step="queued")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"문서 수집 실패: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"문서 처리 중 오류가 발생했습니다: {str(e)}",
        )
    finally:
        await file.close()


# 2026.10.16 추가 - Phase 1: 업로드 화면이 엑셀 처리 방식을 알 수 있게 한다(UI-12, D-16)
@router.get("/options")
async def get_ingest_options(principal: dict = Depends(get_current_principal)):
    """업로드 옵션: 엑셀 처리 방식과 엑셀 전용 처리기가 받는 확장자."""
    mode = get_settings().excel_parse_mode
    return {
        "excel_parse_mode": mode,
        "excel_ingest_extensions": (
            sorted(EXCEL_INGEST_EXTENSIONS) + [LEGACY_XLS_EXTENSION] if mode == "backend" else []
        ),
        # 2026.10.19(sooyeon.choi) 추가 - 문서 목록 [최신본 변경] 사용 여부
        "version_replace_enabled": bool(getattr(get_settings(), "document_version_replace_enabled", True)),
    }


@router.get("/jobs/{job_id}", response_model=IngestJobResponse)
async def get_ingest_job(job_id: str, principal: dict = Depends(get_current_principal)):
    job = await asyncio.to_thread(IngestJobRepository().get, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다.")
    if not principal.get("is_admin") and job.get("created_by") != principal["user_id"]:
        raise HTTPException(status_code=403, detail="작업 조회 권한이 없습니다.")
    return IngestJobResponse(
        job_id=job_id,
        status=job["status"],
        current_step=job["current_step"],
        result=job.get("result"),
        error=job.get("error_message"),
        error_code=job.get("error_code"),
        **job_payload(job),  # 2026.11.06(sooyeon.choi) 수정 - 작업 유형·대상 문서·버전
    )


@router.post("/jobs/{job_id}/retry", response_model=IngestJobResponse, status_code=202)
async def retry_ingest_job(job_id: str, principal: dict = Depends(get_current_principal)):
    job = await asyncio.to_thread(IngestJobRepository().get, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다.")
    if not principal.get("is_admin") and job.get("created_by") != principal["user_id"]:
        raise HTTPException(status_code=403, detail="작업 재시도 권한이 없습니다.")
    try:
        await get_ingest_job_manager().retry(job_id)
    except RestoreRetryNotAllowed as exc:
        # 2026.11.06(sooyeon.choi) 수정 - 복원 작업은 최신 이력 확인 후 새 요청으로만 다시 실행
        code = "RESTORE_RETRY_REQUIRES_NEW_REQUEST"
        raise HTTPException(status_code=409, detail={"code": code, "message": RESTORE_BLOCK_MESSAGES[code]}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return IngestJobResponse(job_id=job_id, status="queued", current_step=job["current_step"])


@router.get("/collections", response_model=CollectionsResponse)
async def list_collections(principal: dict = Depends(get_current_principal)):
    """Qdrant 컬렉션 목록을 반환합니다."""
    try:
        service = IngestService()
        all_cols = service.list_collections()
        user_filter = _get_user_accessible(principal)
        if user_filter is not None:
            accessible, _ = user_filter
            all_cols = [c for c in all_cols if c in accessible]
        return CollectionsResponse(collections=all_cols)
    except Exception as e:
        logger.error(f"컬렉션 목록 조회 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/documents", response_model=DocumentsResponse)
async def list_documents(
    collection_name: Optional[str] = None,
    principal: dict = Depends(get_current_principal),
):
    """업로드된 문서 목록을 반환합니다."""
    try:
        service = IngestService()
        raw_docs = service.list_documents(collection_name)

        # 비관리자: accessible_collections + security_level 계층 필터 적용
        user_filter = _get_user_accessible(principal)
        if user_filter is not None:
            accessible, allowed_levels = user_filter
            raw_docs = [
                d for d in raw_docs
                if d.get("source_collection", d.get("collection_name", "")) in accessible
                and d.get("security_level", "public") in allowed_levels
            ]
        # 2026.10.19(sooyeon.choi) 추가 - 최신본 변경 처리 중인 버전(문서별 최대 1개)
        pending = await asyncio.to_thread(_pending_versions, [d.get("document_id") for d in raw_docs])
        # 2026.11.06(sooyeon.choi) 수정 - 적용 순번·진행 중 변경 작업(복원 포함)
        states = await asyncio.to_thread(_document_states, [d.get("document_id") for d in raw_docs])
        docs = []
        for d in raw_docs:
            docs.append(DocumentItem(
                document_id=d.get("document_id", ""),
                filename=(
                    d.get("filename")
                    or d.get("original_filename")
                    or d.get("title")
                    or os.path.basename(d.get("source_path", ""))
                ),
                collection_name=d.get("collection_name") or d.get("source_collection", ""),
                doc_type=d.get("doc_type") or d.get("document_type"),
                requested_doc_type=d.get("requested_doc_type") or "auto",
                doc_type_source=d.get("doc_type_source"),
                total_pages=d.get("total_pages"),
                chunk_count=d.get("chunk_count"),
                parser_type=d.get("parser_type"),
                # 2026.06.16(sooyeon.choi) 수정 - upload_timestamp → created_at (v4 필드명)
                upload_timestamp=format_kst_datetime(
                    d.get("upload_timestamp") or d.get("created_at")
                ),
                # 2026.06.30(sooyeon.choi) 추가 - 관리자는 전체, 사용자는 본인 문서만 개별 삭제 가능
                uploaded_by=d.get("uploaded_by"),
                can_delete=bool(
                    principal.get("is_admin")
                    or d.get("uploaded_by") == principal["user_id"]
                ),
                # 2026.10.19(sooyeon.choi) 추가 - 모델명·현재 버전(version_no)·최근 변경일(updated_at, KST)
                product_model=d.get("product_model"),
                version_no=d.get("version_no"),
                updated_at=format_kst_datetime(d.get("updated_at") or d.get("created_at")),
                can_edit=bool(
                    principal.get("is_admin")
                    or d.get("uploaded_by") == principal["user_id"]
                ),
                pending_version_no=pending.get(d.get("document_id"), (None, None))[0],
                pending_job_id=pending.get(d.get("document_id"), (None, None))[1],
                activation_revision=states.get(d.get("document_id"), {}).get("activation_revision"),
                pending_operation=states.get(d.get("document_id"), {}).get("pending_operation"),
            ))
        return DocumentsResponse(documents=docs, total=len(docs))
    except Exception as e:
        logger.error(f"문서 목록 조회 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# 2026.10.19(sooyeon.choi) 추가 - 모델명 수정. 모델명만 바꾸며 버전 증가·재파싱·재임베딩은 하지 않는다.
#   권한: 관리자 전체, 그 외는 본인 업로드 문서만(삭제와 같은 규칙). 볼 수 없는 문서는 404(존재 숨김).
@router.patch("/documents/{document_id}/model-name", response_model=ModelNameUpdateResponse)
async def update_document_model_name(
    document_id: str,
    body: ModelNameUpdateRequest,
    principal: dict = Depends(get_current_principal),
):
    db = get_database_manager()
    doc_rows = await asyncio.to_thread(
        db.execute_query,
        """
        SELECT d.uploaded_by, d.security_level, c.qdrant_name AS source_collection
        FROM tb_documents d
        LEFT JOIN tb_collections c ON c.collection_id = d.collection_id
        WHERE d.document_id = ? AND d.deleted_at IS NULL
        """,
        (document_id,),
    )
    if not doc_rows:
        raise HTTPException(status_code=404, detail="해당 문서를 찾을 수 없습니다.")
    doc_info = dict(doc_rows[0])
    user_filter = _get_user_accessible(principal)
    if user_filter is not None:
        accessible, allowed_levels = user_filter
        if (
            doc_info.get("source_collection") not in accessible
            or (doc_info.get("security_level") or "public") not in allowed_levels
        ):
            raise HTTPException(status_code=404, detail="해당 문서를 찾을 수 없습니다.")
    if not principal.get("is_admin") and doc_info.get("uploaded_by") != principal["user_id"]:
        raise HTTPException(status_code=403, detail="본인이 업로드한 문서만 모델명을 수정할 수 있습니다.")
    try:
        product_model = validate_model_name(body.product_model)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    updated = await asyncio.to_thread(
        DocumentRepository().update_product_model, document_id, product_model, principal["user_id"]
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="해당 문서를 찾을 수 없습니다.")
    return ModelNameUpdateResponse(
        document_id=updated["document_id"],
        product_model=updated["product_model"],
        version_no=updated.get("version_no"),
        updated_at=format_kst_datetime(updated.get("updated_at")),
    )


# ── 최신본 변경·버전 이력 (2026.10.19) ─────────
#   - 상단 업로드는 항상 새 문서, 개정본은 문서 행의 [최신본 변경]으로만 올린다(자동 판단 없음).
#   - 기존 document_id·모델명 유지. 새 버전 처리·검증이 끝나야 한 트랜잭션으로 최신본 전환(ingest_pipeline).
#   - 처리 중·실패 시 기존 최신본으로 검색·답변(version_visibility). 문서별 처리 중 버전은 1개(409).
#   - 권한: 대상 문서가 없거나 볼 수 없거나 본인 업로드 문서가 아니면 404. 관리자는 모든 문서.


class _VersionConflict(Exception):
    pass


def _pending_versions(document_ids: List[str]) -> dict:
    ids = [doc_id for doc_id in document_ids if doc_id]
    if not ids:
        return {}
    placeholders = ", ".join("?" for _ in ids)
    rows = get_database_manager().execute_query(
        f"SELECT document_id, version_no, job_id FROM tb_document_versions "
        f"WHERE status IN ('building', 'ready') AND document_id IN ({placeholders})",
        tuple(ids),
    )
    return {r["document_id"]: (r["version_no"], r["job_id"]) for r in rows}


# 2026.11.06(sooyeon.choi) 추가 - 문서별 적용 순번과 진행 중 변경 작업(pending_job_id가 가리키는 queued/running 작업)
def _pending_operation(row) -> Optional[dict]:
    if not row["job_id"]:
        return None
    request = row["request_json"]
    request = json.loads(request) if isinstance(request, str) else (request or {})
    restore = row["operation_type"] == "restore"
    return {
        "job_id": row["job_id"],
        "operation_type": "restore" if restore else "replace",
        "status": row["status"],
        "current_step": row["current_step"],
        "target_version_no": request.get("target_version_no") if restore else request.get("version_no"),
    }


def _document_states(document_ids: List[str]) -> dict:
    ids = [doc_id for doc_id in document_ids if doc_id]
    if not ids:
        return {}
    placeholders = ", ".join("?" for _ in ids)
    rows = get_database_manager().execute_query(
        f"""SELECT d.document_id, d.activation_revision, j.job_id, j.status, j.current_step, j.operation_type,
                   j.request_json
            FROM tb_documents d
            LEFT JOIN tb_ingest_jobs j ON j.job_id = d.pending_job_id AND j.status IN ('queued', 'running')
            WHERE d.document_id IN ({placeholders})""",
        tuple(ids),
    )
    return {
        r["document_id"]: {"activation_revision": r["activation_revision"], "pending_operation": _pending_operation(r)}
        for r in rows
    }


def _load_visible_document(document_id: str, principal: dict) -> dict:
    """삭제되지 않았고 사용자가 볼 수 있는 문서 정보. 아니면 404."""
    rows = get_database_manager().execute_query(
        """
        SELECT d.document_id, d.uploaded_by, d.security_level, d.parser_type, d.requested_doc_type,
               d.product_model, d.version_no, d.original_filename,
               c.qdrant_name AS source_collection
        FROM tb_documents d
        LEFT JOIN tb_collections c ON c.collection_id = d.collection_id
        WHERE d.document_id = ? AND d.deleted_at IS NULL
        """,
        (document_id,),
    )
    if not rows:
        raise HTTPException(status_code=404, detail="해당 문서를 찾을 수 없습니다.")
    doc = dict(rows[0])
    user_filter = _get_user_accessible(principal)
    if user_filter is not None:
        accessible, allowed_levels = user_filter
        if (
            doc.get("source_collection") not in accessible
            or (doc.get("security_level") or "public") not in allowed_levels
        ):
            raise HTTPException(status_code=404, detail="해당 문서를 찾을 수 없습니다.")
    return doc


def _register_version_job(document_id: str, job_id: str, request: dict, created_by: str) -> int:
    """같은 문서를 잠그고(advisory lock) 처리 중 버전·같은 파일을 확인한 뒤 작업과 building 버전을 한 번에 만든다."""
    from app.repositories.ingest_record_repository import IngestRecordRepository

    repo = IngestRecordRepository()
    # 해시·크기는 버전 행에만 쓰고 작업 요청(IngestService.ingest 인자)에는 넣지 않는다
    file_sha256 = request.pop("file_sha256", None)
    file_size = request.pop("file_size", None)
    with repo.db.get_connection():
        repo.lock_document(document_id)
        alive = repo.db.execute_query(
            "SELECT 1 FROM tb_documents WHERE document_id = ? AND deleted_at IS NULL", (document_id,)
        )
        if not alive:
            raise _VersionConflict("NOT_FOUND")
        current = repo.in_progress_version(document_id)
        if current:
            raise _VersionConflict(
                f"JOB_IN_PROGRESS: 이 문서는 v{current['version_no']} 최신본 변경을 처리 중입니다. 완료 후 다시 시도하세요."
            )
        # 2026.11.06(sooyeon.choi) 수정 - 복원 등 다른 변경 작업이 문서를 점유 중이면 거부(공통 점유 표식, B-01)
        if repo.pending_job_id(document_id):
            raise _VersionConflict("JOB_IN_PROGRESS: 이 문서는 다른 변경 작업을 처리 중입니다. 완료 후 다시 시도하세요.")
        if file_sha256 and file_sha256 == repo.active_version_sha(document_id):
            raise _VersionConflict("DUPLICATE_FILE: 현재 최신본과 같은 파일입니다.")
        version_no = repo.next_version_no(document_id)
        request["version_no"] = version_no
        IngestJobRepository().create(job_id, request, created_by)
        repo.create_building_version(
            document_id, version_no,
            original_filename=request["filename"], file_sha256=file_sha256,
            file_size=file_size, job_id=job_id, uploaded_by=created_by,
        )
        repo.acquire_pending(document_id, job_id)  # 2026.11.06(sooyeon.choi) 수정 - 전환·실패 시 해제
    return version_no


@router.post("/documents/{document_id}/versions", response_model=VersionJobResponse, status_code=202)
async def replace_document_version(
    document_id: str,
    file: UploadFile = File(...),
    principal: dict = Depends(get_current_principal),
):
    """[최신본 변경] 기존 문서의 다음 버전을 접수한다(처리 완료·검증 후에만 최신본으로 전환)."""
    settings_obj = get_settings()
    try:
        if not getattr(settings_obj, "document_version_replace_enabled", True):
            raise HTTPException(status_code=403, detail="최신본 변경 기능이 꺼져 있습니다.")
        doc = await asyncio.to_thread(_load_visible_document, document_id, principal)
        if not principal.get("is_admin") and doc.get("uploaded_by") != principal["user_id"]:
            raise HTTPException(status_code=404, detail="해당 문서를 찾을 수 없습니다.")

        # 파서·문서 유형은 기존 문서 설정을 따르되, 새 파일 형식에 맞지 않으면 기본값(docling·자동)
        ext_guess = (file.filename or "").rsplit(".", 1)[-1].lower()
        parser_type = doc.get("parser_type") if doc.get("parser_type") == "pdfplumber" and ext_guess == "pdf" else "docling"
        document_type = doc.get("requested_doc_type") or "auto"
        try:
            validate_document_type_compatibility(ext_guess, normalize_requested_doc_type(document_type))
        except ValueError:
            document_type = "auto"
        ext, excel_ingest_upload, document_type = _validate_upload_options(
            file.filename, parser_type, document_type, settings_obj
        )

        job_id = str(uuid4())
        tmp_path = await _store_upload_tmp(file, job_id, ext, excel_ingest_upload, settings_obj)
        from app.services.ingest_pipeline import _sha256_of

        request = dict(
            file_path=tmp_path,
            filename=file.filename,
            collection_name=doc.get("source_collection"),
            parser_type=parser_type,
            document_type=document_type,
            chunk_size=None,
            uploaded_by=principal["user_id"],
            # 문서의 보안 등급·모델명을 그대로 이어 쓴다(모델명은 자동 덮어쓰지 않음)
            security_level=doc.get("security_level") or "public",
            product_model=doc.get("product_model"),
            target_document_id=document_id,
            file_sha256=await asyncio.to_thread(_sha256_of, tmp_path),
            file_size=Path(tmp_path).stat().st_size,
        )
        try:
            version_no = await asyncio.to_thread(
                _register_version_job, document_id, job_id, request, principal["user_id"]
            )
        except _VersionConflict as exc:
            Path(tmp_path).unlink(missing_ok=True)
            if str(exc) == "NOT_FOUND":
                raise HTTPException(status_code=404, detail="해당 문서를 찾을 수 없습니다.") from exc
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except Exception:
            Path(tmp_path).unlink(missing_ok=True)
            raise
        await get_ingest_job_manager().enqueue(job_id)
        logger.info("event=version_replace status=queued document_id=%s version_no=%s job_id=%s",
                    document_id, version_no, job_id)
        return VersionJobResponse(
            job_id=job_id, status="queued", current_step="queued", document_id=document_id, version_no=version_no
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"최신본 변경 접수 실패: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"최신본 변경 접수 중 오류가 발생했습니다: {str(e)}")
    finally:
        await file.close()


@router.get("/documents/{document_id}/versions", response_model=DocumentVersionsResponse)
async def list_document_versions(document_id: str, principal: dict = Depends(get_current_principal)):
    """[버전 이력] 문서의 실제 버전 목록(최신 순). 볼 수 없는 문서는 404."""
    from app.repositories.ingest_record_repository import IngestRecordRepository

    doc = await asyncio.to_thread(_load_visible_document, document_id, principal)
    rows = await asyncio.to_thread(IngestRecordRepository().list_versions, document_id)
    # 2026.11.06(sooyeon.choi) 수정 - 이전 버전 복원: 문서 단위·행 단위 가능 여부(서버 판정, 설계 v1.1 8절)
    settings_obj = get_settings()
    extra = await asyncio.to_thread(_version_history_context, document_id, settings_obj)
    pending_operation = extra["state"].get("pending_operation")
    doc_code = document_block_code(
        settings=settings_obj, principal=principal,
        pending_job=pending_operation or (extra["in_progress"] or None),
    )
    verdicts = evaluate_versions(
        rows, doc_code=doc_code, profile_id=extra["profile_id"], pending_busy=bool(pending_operation),
    )
    items = []
    for row, (can_restore, block_code, block_reason) in zip(rows, verdicts):
        failed = row["status"] == "failed" or row.get("job_status") == "failed"
        items.append(DocumentVersionItem(
            version_no=row["version_no"],
            status=row["status"],
            is_active=row["status"] == "active",
            original_filename=row.get("original_filename"),
            file_size=row.get("file_size"),
            file_format=row.get("file_format"),
            parser_type=row.get("parser_type"),
            processing_engine=row.get("processing_engine"),
            total_pages=row.get("total_pages"),
            chunk_count=row.get("chunk_count"),
            uploaded_by=row.get("uploaded_by"),
            created_at=format_kst_datetime(row.get("created_at")) or None,
            activated_at=format_kst_datetime(row.get("activated_at")) or None,
            retired_at=format_kst_datetime(row.get("retired_at")) or None,
            job_id=row.get("job_id"),
            job_status=row.get("job_status"),
            error=row.get("error_message") if failed else None,
            uploaded_by_name=row.get("uploaded_by_name"),
            can_restore=can_restore,
            restore_block_code=block_code,
            restore_block_reason=block_reason,
        ))
    return DocumentVersionsResponse(
        document_id=document_id,
        product_model=doc.get("product_model"),
        current_version_no=doc.get("version_no") or 1,
        versions=items,
        # 2026.11.06(sooyeon.choi) 수정 - 이전 버전 복원 화면 값
        restore_supported=restore_enabled(settings_obj),
        collection_name=doc.get("source_collection"),
        collection_display_name=extra["collection_display_name"],
        current_original_filename=doc.get("original_filename"),
        activation_revision=extra["state"].get("activation_revision") or 1,
        total_versions=len(rows),
        next_version_no=max((r["version_no"] for r in rows), default=0) + 1,
        can_restore=doc_code is None,
        restore_block_code=doc_code,
        restore_block_reason=RESTORE_BLOCK_MESSAGES.get(doc_code) if doc_code else None,
        pending_operation=pending_operation,
    )


# 2026.11.06(sooyeon.choi) 추가 - 이력 화면 보조 정보(대화 주제 표시명·적용 순번·진행 작업·현재 임베딩 프로필)
def _version_history_context(document_id: str, settings_obj) -> dict:
    from app.repositories.ingest_record_repository import IngestRecordRepository

    db = get_database_manager()
    rows = db.execute_query(
        "SELECT c.display_name FROM tb_documents d LEFT JOIN tb_collections c ON c.collection_id = d.collection_id "
        "WHERE d.document_id = ?",
        (document_id,),
    )
    return {
        "collection_display_name": rows[0][0] if rows else None,
        "state": _document_states([document_id]).get(document_id, {}),
        "in_progress": IngestRecordRepository(db).in_progress_version(document_id),
        "profile_id": current_profile_id(db, settings_obj),
    }


def _restore_http_error(exc: RestoreError) -> HTTPException:
    if exc.code == "NOT_FOUND":
        return HTTPException(status_code=404, detail="해당 문서를 찾을 수 없습니다.")
    return HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.message})


# 2026.11.06(sooyeon.choi) 추가 - [이전 버전 복원] 접수(문서를 볼 수 있는 모든 사용자, 명세 v1.1 5절). 새 접수 202, 같은 키 재전송은
#   진행 중 202·끝난 작업 200(같은 job_id). 실제 전환은 작업 관리자가 검증 후 수행한다.
@router.post(
    "/documents/{document_id}/versions/{version_no}/restore", response_model=RestoreJobResponse, status_code=202,
)
async def restore_document_version(
    document_id: str,
    version_no: int,
    body: RestoreVersionRequest,
    response: Response,
    principal: dict = Depends(get_current_principal),
):
    # 볼 수 없거나 삭제된 문서는 404. 2026.11.06(sooyeon.choi) 수정 - 볼 수 있으면 복원 가능(관리자 전용 아님)
    await asyncio.to_thread(_load_visible_document, document_id, principal)
    try:
        result = await asyncio.to_thread(
            submit_restore, document_id, version_no,
            expected_version_no=body.expected_current_version_no,
            expected_revision=body.expected_activation_revision,
            idempotency_key=body.idempotency_key,
            principal=principal,
        )
    except RestoreError as exc:
        raise _restore_http_error(exc) from exc
    job = result.job
    if result.created:
        try:
            await get_ingest_job_manager().enqueue(job["job_id"])
        except Exception:
            # 접수(DB 저장)는 끝났다 — 실패로 위장하지 않고 재기동 시 queued 작업으로 이어서 처리한다
            logger.exception("event=version_restore status=enqueue_failed job_id=%s", job["job_id"])
    elif job["status"] in ("completed", "failed"):
        response.status_code = 200
    payload = job_payload(job)
    return RestoreJobResponse(
        job_id=job["job_id"], status=job["status"], current_step=job["current_step"],
        document_id=payload["document_id"], from_version_no=payload.get("from_version_no"),
        target_version_no=payload["target_version_no"],
    )


# 2026.11.06(sooyeon.choi) 추가 - [적용 이력 보기](명세 v1.1 7절). 문서를 볼 수 있으면 조회, 최신순·커서 페이지
@router.get("/documents/{document_id}/activations", response_model=ActivationsResponse)
async def list_document_activations(
    document_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    before_activation_id: Optional[int] = Query(default=None, ge=1),
    principal: dict = Depends(get_current_principal),
):
    from app.repositories.ingest_record_repository import IngestRecordRepository

    await asyncio.to_thread(_load_visible_document, document_id, principal)
    rows = await asyncio.to_thread(
        IngestRecordRepository().list_activations, document_id, limit=limit + 1,
        before_activation_id=before_activation_id,
    )
    page = rows[:limit]
    return ActivationsResponse(
        document_id=document_id,
        activations=[
            ActivationItem(
                activation_id=r["activation_id"], operation_type=r["operation_type"],
                from_version_no=r["from_version_no"], to_version_no=r["to_version_no"],
                activation_revision=r["activation_revision"], activated_by=r["actor_id"],
                activated_by_name=r["actor_name"],
                activated_at=format_kst_datetime(r["activated_at"]) or None,
            )
            for r in page
        ],
        next_before_activation_id=page[-1]["activation_id"] if len(rows) > limit else None,
    )


# 2026.05.27(woojin.jung) - 원본 문서 보기 기능 추가
# 2026.06.16(sooyeon.choi) 수정 - tb_ingest_documents → tb_documents JOIN tb_collections
# 2026.07.10(sooyeon.choi) 추가 - 매뉴얼 citation 표시용 원본 PDF 매핑 조회
@router.get("/manual-display/resolve", response_model=ManualDisplayResolveResponse)
async def resolve_manual_display(
    filename: str,
    page: int = 1,
    principal: dict = Depends(get_current_principal),
):
    service = ManualDisplayService()
    return ManualDisplayResolveResponse(**service.resolve(filename, page))


# 2026.07.10(sooyeon.choi) 추가 - 매뉴얼 citation 표시용 원본 PDF 반환
@router.get("/manual-display/file/{display_filename}")
async def open_manual_display_file(
    display_filename: str,
    principal: dict = Depends(get_current_principal),
):
    service = ManualDisplayService()
    try:
        file_path = service.resolve_pdf_path(display_filename)
    except ValueError:
        raise HTTPException(status_code=400, detail="?섎せ??매뉴얼 표시용 PDF 파일명입니다.")

    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="매뉴얼 표시용 PDF 파일을 찾을 수 없습니다.")

    return FileResponse(
        path=str(file_path),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"inline; filename*=UTF-8''{quote(display_filename)}",
        },
    )


@router.get("/documents/{document_id}/file")
async def open_original_document(
    document_id: str,
    principal: dict = Depends(get_current_principal),
):
    """원본 문서 파일을 브라우저에서 열 수 있도록 반환한다."""
    settings = get_settings()
    db = get_database_manager(settings.sqlite_db_path)
    doc_rows = db.execute_query(
        """
        SELECT d.document_id, d.source_path, d.original_filename, d.security_level,
               d.doc_type AS document_type,
               c.qdrant_name AS source_collection
        FROM tb_documents d
        LEFT JOIN tb_collections c ON c.collection_id = d.collection_id
        WHERE d.document_id = ? AND d.deleted_at IS NULL
        """,
        (document_id,),
    )
    if not doc_rows:
        raise HTTPException(status_code=404, detail="해당 문서를 찾을 수 없습니다.")

    doc_info = dict(doc_rows[0])
    user_filter = _get_user_accessible(principal)
    if user_filter is not None:
        accessible, allowed_levels = user_filter
        if (
            doc_info.get("source_collection") not in accessible
            or doc_info.get("security_level", "public") not in allowed_levels
        ):
            raise HTTPException(status_code=403, detail="해당 문서에 접근 권한이 없습니다.")

    # 2026.10.30(sooyeon.choi) 수정 - 백엔드 소스 폴더 기준 → 저장할 때와 같은 저장 폴더 기준으로 경로를 푼다.
    #   운영은 소스(/app)와 데이터(/data)가 따로 마운트되어 소스 기준으로는 파일을 찾지 못했다("원본 문서를 열 수 없습니다").
    source_path = doc_info.get("source_path") or ""
    try:
        file_path = get_original_file_storage(settings).resolve(source_path)
    except ValueError:
        raise HTTPException(status_code=400, detail="잘못된 문서 경로입니다.")
    if not file_path.is_file():
        logger.warning(f"[Ingest] 원본 파일 없음: document_id={document_id}, path={file_path}")
        raise HTTPException(status_code=404, detail="원본 파일을 찾을 수 없습니다.")

    filename = doc_info.get("original_filename") or file_path.name
    media_type = "application/pdf" if file_path.suffix.lower() == ".pdf" else "application/octet-stream"
    return FileResponse(
        path=str(file_path),
        media_type=media_type,
        headers={
            "Content-Disposition": f"inline; filename*=UTF-8''{quote(filename)}",
        },
    )


# 2026.04.02(sooyeon.choi) - 문서 삭제 기능 추가
# 2026.06.16(sooyeon.choi) 수정 - tb_ingest_documents → tb_documents (v4 스키마)
@router.delete("/documents/{document_id}", response_model=DeleteDocumentResponse)
@router.post("/documents/{document_id}/delete", response_model=DeleteDocumentResponse)
async def delete_document(
    document_id: str,
    principal: dict = Depends(get_current_principal),
):
    """문서를 삭제한다 (Qdrant 포인트 + tb_documents Soft Delete)."""
    # 삭제 전 문서 정보 조회 (권한 검증 + 이력 기록용)
    settings = get_settings()
    db = get_database_manager(settings.sqlite_db_path)
    doc_rows = db.execute_query(
        """
        SELECT d.document_id, d.uploaded_by, d.original_filename, d.security_level,
               d.doc_type AS document_type, d.total_pages, d.chunk_count, d.parser_type,
               d.deleted_at,
               c.qdrant_name AS source_collection
        FROM tb_documents d
        LEFT JOIN tb_collections c ON c.collection_id = d.collection_id
        WHERE d.document_id = ?
        """,
        (document_id,),
    )
    if not doc_rows:
        raise HTTPException(status_code=404, detail="해당 문서를 찾을 수 없습니다.")
    doc_info = dict(doc_rows[0])

    # 비관리자: 컬렉션 접근 권한 검증
    user_filter = _get_user_accessible(principal)
    if user_filter is not None:
        accessible, _ = user_filter
        if doc_info["source_collection"] not in accessible:
            raise HTTPException(
                status_code=403,
                detail=f"'{doc_info['source_collection']}' 컬렉션에 접근 권한이 없습니다.",
            )
    # 2026.06.30(sooyeon.choi) 추가 - 타인이 업로드한 문서의 개별 삭제 차단
    if (
        not principal.get("is_admin")
        and doc_info.get("uploaded_by") != principal["user_id"]
    ):
        raise HTTPException(
            status_code=403,
            detail="본인이 업로드한 문서만 개별 삭제할 수 있습니다.",
        )
    # 2026.10.19(sooyeon.choi) 추가 - 최신본 변경 처리 중에는 삭제하지 않는다(처리 완료·실패 후 삭제)
    # 2026.11.06(sooyeon.choi) 수정 - 복원 등 다른 변경 작업이 점유 중이어도 삭제하지 않는다(B-02)
    if not doc_info.get("deleted_at") and (
        await asyncio.to_thread(_pending_versions, [document_id])
        or (await asyncio.to_thread(_document_states, [document_id])).get(document_id, {}).get("pending_operation")
    ):
        raise HTTPException(status_code=409, detail="최신본 변경을 처리 중인 문서는 삭제할 수 없습니다. 처리가 끝난 뒤 다시 시도하세요.")
    try:
        service = IngestService()
        result = service.delete_document(
            document_id,
            actor_id=principal["user_id"],
        )
        return DeleteDocumentResponse(
            status=result["status"],
            document_id=result["document_id"],
            deleted_vector_count=result["deleted_vector_count"],
            remaining_vector_count=result["remaining_vector_count"],
            reconciled=result["reconciled"],
            message=(
                "이미 삭제된 문서입니다."
                if result["status"] == "already_deleted"
                else f"문서 '{result.get('title', '')}' 삭제 완료"
            ),
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        logger.error(f"문서 삭제 실패: {e}", exc_info=True)
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"문서 삭제 중 오류: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"문서 삭제 중 오류가 발생했습니다: {str(e)}")

"""문서 수집(Ingest) API 요청·응답 스키마.

2026.11.09(sooyeon.choi) 추가 - routes/ingest.py에서 분리.
라우트 모듈은 같은 이름으로 다시 import하므로 ``app.routes.ingest.DocumentItem`` 같은 기존 참조도 그대로 동작한다.
"""
from typing import List, Optional

from pydantic import BaseModel, Field


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
    # 2026.11.12(sooyeon.choi) 도면 파싱 기능 추가 - 도면 문서만: 품번·Rev·용지·경고 수·검수·검색 적용 상태
    drawing: Optional[dict] = None


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

"""
Data models for the Advanced RAG Framework.

This module defines the core data structures used throughout the system.
"""
# 2026.06.16(sooyeon.choi) 수정
#   - DocumentStatus, DocumentEventType Enum 추가
#   - DocumentMetadata: tb_documents v4 컬럼 구조로 재정의
#   - DocumentEvent: tb_document_events 매핑 모델 신규
#   - QueryContext: collection_name(TEXT) → collection_id(Optional[int]) 변경
#   - CollectionConfig: display_name/description으로 컬럼명 통일, is_active 추가
#   - UserCollectionPermission, UserSecurityPolicy: 권한 분리 모델 신규
#   - QueryResponse: log_id 추가 (피드백 제출 연동)
#   - Citation: collection_id 추가 (tb_query_citations 연동)

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from app.utils.datetime import now_kst


# =============================================================================
# Enums
# =============================================================================

class SecurityLevel(str, Enum):
    """보안 등급 — tb_documents.security_level / tb_user_security_policies.max_security_level"""
    PUBLIC       = "public"
    INTERNAL     = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED   = "restricted"


# 2026.06.16(sooyeon.choi) 추가 - tb_documents.status 열거형
class DocumentStatus(str, Enum):
    """문서 처리 파이프라인 단계 — tb_documents.status"""
    PENDING   = "pending"
    PARSING   = "parsing"
    EMBEDDING = "embedding"
    READY     = "ready"
    FAILED    = "failed"
    DELETED   = "deleted"


# 2026.06.16(sooyeon.choi) 추가 - tb_document_events.event_type 열거형
class DocumentEventType(str, Enum):
    """문서 이벤트 유형 — tb_document_events.event_type"""
    UPLOAD  = "upload"
    PARSE   = "parse"
    EMBED   = "embed"
    DELETE  = "delete"
    REINDEX = "reindex"
    FAIL    = "fail"
    # 2026.10.19 추가 - 문서 정보 수정(모델명 등, 재처리 없음).
    UPDATE  = "update"


# =============================================================================
# 검색 결과 모델
# =============================================================================

@dataclass
class ChunkSummary:
    """검색된 청크 요약 (QueryResponse 포함용)."""
    chunk_id: str
    document_id: str
    document_name: str
    text: str
    score: float
    section_name: Optional[str] = None
    page_number: Optional[int] = None


# =============================================================================
# 문서 모델
# =============================================================================

# 2026.06.16(sooyeon.choi) 수정 - tb_documents v4 컬럼 구조로 재정의
#   변경: collection_name(str) → collection_id(int), doc_type, source_path,
#         uploaded_by, version_no, status, deleted_at 등 컬럼명 통일
@dataclass
class DocumentMetadata:
    """tb_documents 레코드 매핑 모델."""
    document_id: str
    collection_id: int                  # FK → tb_collections.collection_id
    source_path: str                    # 서버 저장 경로
    uploaded_by: Optional[str] = None  # FK → tb_users.user_id (SET NULL)
    original_filename: Optional[str] = None
    stored_filename: Optional[str] = None
    file_size: Optional[int] = None
    doc_type: Optional[str] = None     # law / manual / general 등
    requested_doc_type: str = "auto"
    doc_type_source: Optional[str] = None
    title: Optional[str] = None
    file_format: Optional[str] = None  # pdf / docx / pptx 등
    security_level: str = SecurityLevel.PUBLIC
    parser_type: Optional[str] = None
    total_pages: Optional[int] = None
    chunk_count: Optional[int] = None
    version_no: int = 1
    status: str = DocumentStatus.PENDING
    error_message: Optional[str] = None
    # 2026.06.19(sooyeon.choi) 추가 - 문서 상태 통계용 콘텐츠 갱신·검토 예정 시각
    content_updated_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    deleted_at: Optional[str] = None   # NOT NULL = 논리 삭제 (Soft Delete)


# 2026.06.16(sooyeon.choi) 추가 - tb_document_events 레코드 매핑 모델
@dataclass
class DocumentEvent:
    """tb_document_events 레코드 매핑 모델."""
    document_id: str                   # 비정규화 보존 (FK 없음)
    event_type: str                    # DocumentEventType 값
    event_id: Optional[int] = None
    collection_id: Optional[int] = None
    event_message: Optional[str] = None
    actor_id: Optional[str] = None
    event_at: Optional[str] = None
    snapshot_json: Optional[str] = None


# =============================================================================
# 인용 모델
# =============================================================================

# 2026.06.16(sooyeon.choi) 수정 - collection_id 필드 추가 (tb_query_citations 연동)
@dataclass
class Citation:
    """응답-출처 문서 인용 매핑 (tb_query_citations 연동)."""
    citation_id: str
    document_id: str
    original_filename: str
    chunk_text: str
    chunk_id: Optional[str] = None
    section_name: Optional[str] = None
    header_path: List[str] = field(default_factory=list)
    page_number: Optional[int] = None
    response_segment: Optional[str] = None
    title: str = ""
    document_type: Optional[str] = None
    score: Optional[float] = None
    referenced_in_answer: bool = False
    collection_id: Optional[int] = None  # tb_query_citations 저장용
    # 2026.08.27(sooyeon.choi) 추가 - spreadsheet citation 원본 추적/표시 필드
    sheet_name: Optional[str] = None
    source_range: Optional[str] = None
    display_markdown: Optional[str] = None
    resource_ids: List[str] = field(default_factory=list)


# =============================================================================
# 질의 모델
# =============================================================================

# 2026.06.16(sooyeon.choi) 수정 - tb_query_sessions 매핑으로 변경
#   collection_name(str) → collection_id(Optional[int])
@dataclass
class QueryContext:
    """대화 세션 — tb_query_sessions 레코드 매핑 모델."""
    session_id: str
    user_id: str
    conversation_history: List[Dict[str, Any]] = field(default_factory=list)
    collection_id: Optional[int] = None  # FK → tb_collections (SET NULL)
    created_at: datetime = field(default_factory=now_kst)
    updated_at: datetime = field(default_factory=now_kst)
    expires_at: Optional[datetime] = None


# =============================================================================
# 권한 모델
# =============================================================================

# 2026.06.16(sooyeon.choi) 추가 - tb_user_collection_permissions 레코드 매핑
@dataclass
class UserCollectionPermission:
    """사용자-컬렉션 단위 접근 권한 — tb_user_collection_permissions."""
    user_id: str
    collection_id: int              # FK → tb_collections.collection_id
    permission_id: Optional[int] = None
    created_at: Optional[str] = None


# 2026.06.16(sooyeon.choi) 추가 - tb_user_security_policies 레코드 매핑
@dataclass
class UserSecurityPolicy:
    """사용자별 보안 정책 — tb_user_security_policies."""
    user_id: str
    max_security_level: str = SecurityLevel.PUBLIC
    allowed_doc_types: List[str] = field(default_factory=list)   # 빈 리스트 = 전체 허용
    metadata_filters: Dict[str, Any] = field(default_factory=dict)
    updated_at: Optional[str] = None


# RAG 파이프라인용 통합 권한 뷰
# (tb_user_collection_permissions + tb_user_security_policies JOIN 결과)
# 2026.06.16(sooyeon.choi) 수정 - accessible_collections는 qdrant_name 목록 유지
#   (Qdrant 필터 빌드 시 qdrant_name 필요 — 서비스 레이어에서 JOIN 후 조립)
@dataclass
class UserPermission:
    """RAG 파이프라인용 사용자 권한 통합 뷰."""
    user_id: str
    accessible_collections: List[str]   # qdrant_name 목록 (Qdrant 필터용)
    max_security_level: str
    allowed_document_types: List[str]
    metadata_filters: Dict[str, Any] = field(default_factory=dict)


# =============================================================================
# 컬렉션 모델
# =============================================================================

# 2026.06.16(sooyeon.choi) 수정 - tb_collections v4 컬럼 구조 반영
#   collection_name → display_name, collection_desc → description, is_active 추가
@dataclass
class CollectionConfig:
    """tb_collections 레코드 매핑 모델."""
    collection_id: int
    display_name: str           # UI 표시명 (기존: collection_name)
    description: str = ""       # 설명 (기존: collection_desc)
    qdrant_name: str = ""       # Qdrant 실제 컬렉션명 (변경 금지)
    created_by: Optional[str] = None
    is_active: bool = True
    created_at: str = ""
    updated_at: str = ""
    # 2026.06.29(sooyeon.choi) 추가 - 대화 주제 + 생성자 부서 스냅샷
    topic_name: Optional[str] = None
    department_id: Optional[str] = None
    # 2026.06.30(sooyeon.choi) 추가 - 컬렉션 생성 부서명 동기화 값
    department_name: str = ""


# =============================================================================
# API 응답 모델
# =============================================================================

# 2026.06.16(sooyeon.choi) 수정 - log_id 추가 (채팅 화면 피드백 제출 시 사용)
@dataclass
class QueryResponse:
    """질의 API 응답."""
    query: str
    answer: str
    chunks: List[ChunkSummary]
    citations: List[Citation]
    processing_time_ms: Optional[float] = None
    log_id: Optional[int] = None  # PATCH /query/{log_id}/feedback 에서 사용
    # 2026.10.19 추가 - 사진 답변: 검증된 [IMG:ref] 사진 목록(app/graphs/images.public_images)
    images: List[Dict[str, Any]] = field(default_factory=list)
    # 검색/리랭킹 시간을 전체 생성시간과 분리해 비교할 수 있는 노드별 시간(s).
    timing: Dict[str, float] = field(default_factory=dict)



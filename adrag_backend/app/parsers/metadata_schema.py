"""
공통 메타데이터 스키마 정의 (v2).

JSON Schema 기반 3개 문서군 공통 스키마:
- document: 문서 수준
- chunk: 청크 수준
- semantic: 시맨틱 수준

Qdrant payload와 SQLite 양쪽에서 사용한다.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ── Document 레벨 ───────────────────────────────────────────────────────────

@dataclass
class DocumentMeta:
    """문서 수준 메타데이터."""
    document_id: str
    source_path: str
    source_collection: str              # KOSHA_기술지원규정 | KOSHA_PORTAL | 산안법 | 중처법
    document_type: str                  # 법령 | 매뉴얼 | 해설서 | 가이드 | FAQ 등
    title: str
    requested_document_type: str = "auto"
    document_type_source: Optional[str] = None
    security_level: str = "public"      # public | internal | confidential
    file_format: str = "pdf"
    original_filename: Optional[str] = None  # 업로드 시 원본 파일명
    created_at: Optional[str] = None    # 제정/생성일 (YYYY-MM-DD)
    updated_at: Optional[str] = None    # 최종 개정/수정일
    version: Optional[str] = None       # 버전 또는 판본


# ── Chunk 레벨 ──────────────────────────────────────────────────────────────

@dataclass
class ChunkMeta:
    """청크 수준 메타데이터."""
    chunk_id: str
    chunk_index: int = 0
    header_path: List[str] = field(default_factory=list)  # 상위→하위 구조 경로
    content_type: str = "text"          # text | table | image
    page_number: Optional[int] = None
    section_title: Optional[str] = None
    char_start_offset: Optional[int] = None
    char_end_offset: Optional[int] = None


# ── Semantic 레벨 ───────────────────────────────────────────────────────────

@dataclass
class SemanticMeta:
    """시맨틱 수준 메타데이터."""
    summary: str = ""
    keywords: List[str] = field(default_factory=list)
    topics: Optional[List[str]] = None
    intent: Optional[str] = None        # regulation | guidance | case | faq | report
    section_title: Optional[str] = None  # LLM 추출 섹션 제목 (폴백용)

    def merge_into_payload(self, payload: Dict[str, Any]) -> None:
        """시맨틱 메타데이터를 payload dict에 병합한다.

        section_title은 규칙 기반 값이 없을 때만 LLM 추출 값으로 채운다.
        """
        payload["summary"] = self.summary or None
        payload["keywords"] = self.keywords or []
        payload["topics"] = self.topics
        payload["intent"] = self.intent
        if not payload.get("section_title") and self.section_title:
            payload["section_title"] = self.section_title


# ── 통합 Payload ────────────────────────────────────────────────────────────

@dataclass
class UnifiedChunkPayload:
    """Qdrant에 저장되는 통합 payload 구조."""
    document: DocumentMeta
    chunk: ChunkMeta
    semantic: SemanticMeta = field(default_factory=SemanticMeta)

    def to_qdrant_payload(self) -> Dict[str, Any]:
        """Qdrant payload용 flat dict로 변환."""
        return {
            # ── document ──
            "document_id": self.document.document_id,
            "source_path": self.document.source_path,
            "original_filename": self.document.original_filename,
            "source_collection": self.document.source_collection,
            "document_type": self.document.document_type,
            "requested_document_type": self.document.requested_document_type,
            "document_type_source": self.document.document_type_source,
            "title": self.document.title,
            "created_at": self.document.created_at,
            "updated_at": self.document.updated_at,
            "version": self.document.version,
            "security_level": self.document.security_level,
            "file_format": self.document.file_format,
            # ── chunk ──
            "chunk_id": self.chunk.chunk_id,
            "chunk_index": self.chunk.chunk_index,
            "page_number": self.chunk.page_number,
            "section_title": self.chunk.section_title,
            "header_path": self.chunk.header_path,
            "content_type": self.chunk.content_type,
            "char_start_offset": self.chunk.char_start_offset,
            "char_end_offset": self.chunk.char_end_offset,
            # ── semantic ──
            "summary": self.semantic.summary or None,
            "keywords": self.semantic.keywords or [],
            "topics": self.semantic.topics,
            "intent": self.semantic.intent,
            # ── text (검색용) ──
            "text": "",  # IngestService에서 채움
        }

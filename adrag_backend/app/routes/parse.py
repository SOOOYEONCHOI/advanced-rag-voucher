"""
파싱/청킹 미리보기 API
POST /api/parse/preview  - 파일 업로드 → 파싱 + 청킹 → 결과 반환 (저장 없음)
"""

import tempfile
import logging
from pathlib import Path
from typing import List, Optional, Any, Dict

from fastapi import APIRouter, File, UploadFile, Form, HTTPException
from pydantic import BaseModel

from app.parsers.processor import DocumentChunkingProcessor
from app.parsers.config import ChunkingConfig
from app.parsers.spreadsheet_contract import (
    LEGACY_XLS_UPLOAD_MESSAGE,
    OOXML_SPREADSHEET_EXTENSIONS,
)
from app.parsers.document_types import (
    DocumentTypeMismatchError,
    normalize_requested_doc_type,
    validate_document_type_compatibility,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/parse", tags=["parse"])

# 2026.08.27(sooyeon.choi) 수정 - 업로드 API와 동일한 Excel 확장자 계약 사용
ALLOWED_EXTENSIONS = {
    "pdf", "docx", "doc", "pptx", "ppt",
    *OOXML_SPREADSHEET_EXTENSIONS,
    "png", "jpg", "jpeg", "tiff", "bmp", "webp",
}


class ChunkItem(BaseModel):
    index: int
    page: Optional[int]
    page_start: Optional[int]
    page_end: Optional[int]
    pages_display: Optional[str]
    header_path: Optional[str]
    char_count: int
    content: str
    metadata: Dict[str, Any]


class ParsePreviewResponse(BaseModel):
    filename: str
    file_type: str
    doc_type: str
    is_law: bool
    is_manual: bool
    total_pages: int
    chunk_count: int
    chunks: List[ChunkItem]
    requested_doc_type: str = "auto"
    doc_type_source: Optional[str] = None
    detection_details: Optional[Dict[str, Any]] = None


@router.post(
    "/preview",
    response_model=ParsePreviewResponse,
    summary="파일 파싱 + 청킹 미리보기",
    description=(
        "파일을 업로드하면 Docling API로 파싱하고 문서 유형(법령/매뉴얼/일반)을 "
        "자동 판정하여 청킹 결과를 반환합니다. DB나 벡터 저장소에 저장하지 않습니다."
    ),
)
async def parse_preview(
    file: UploadFile = File(..., description="파싱할 문서 파일 (PDF, DOCX, PPTX, 이미지 등)"),
    parser_type: str = Form(
        default="docling",
        description="파서 선택: 'docling'(기본) 또는 'pdfplumber'(PDF 전용 로컬)",
    ),
    chunk_size: Optional[int] = Form(default=None, description="청크 크기 (기본값: 문서 유형별 자동)"),
    chunk_overlap: Optional[int] = Form(default=None, description="청크 오버랩 (기본값: 문서 유형별 자동)"),
    document_type: str = Form(default="auto", description="문서 유형: auto|law|manual|general|spreadsheet"),
):
    # 확장자 검증
    ext = Path(file.filename).suffix.lstrip(".").lower()
    # 2026.08.27(sooyeon.choi) 추가 - .xls는 최초 검증에서 명시적으로 거부
    if ext == "xls":
        raise HTTPException(status_code=400, detail=LEGACY_XLS_UPLOAD_MESSAGE)
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"지원하지 않는 파일 형식입니다: .{ext}  (지원: {', '.join(sorted(ALLOWED_EXTENSIONS))})",
        )

    if parser_type not in ("docling", "pdfplumber"):
        raise HTTPException(status_code=400, detail="parser_type은 'docling' 또는 'pdfplumber'여야 합니다.")

    if parser_type == "pdfplumber" and ext != "pdf":
        raise HTTPException(status_code=400, detail="pdfplumber는 PDF 파일에만 사용할 수 있습니다.")
    try:
        document_type = normalize_requested_doc_type(document_type)
        validate_document_type_compatibility(ext, document_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # 임시 파일에 저장
    suffix = f".{ext}"
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"파일 저장 실패: {e}")

    # 프로세서 설정
    config = ChunkingConfig(parser_type=parser_type, requested_doc_type=document_type)
    if chunk_size is not None:
        config.general_chunk_size = chunk_size
        config.law_chunk_size = chunk_size
        config.manual_chunk_size = chunk_size
    if chunk_overlap is not None:
        config.general_chunk_overlap = chunk_overlap
        config.law_chunk_overlap = chunk_overlap
        config.manual_chunk_overlap = chunk_overlap

    # 처리
    try:
        processor = DocumentChunkingProcessor(config=config)
        result = processor.process(tmp_path)
    except DocumentTypeMismatchError as e:
        logger.exception("파싱/청킹 중 유형 불일치")
        raise HTTPException(status_code=422, detail={
            "error_code": e.error_code,
            "requested_doc_type": document_type,
            "detail": str(e),
        }) from e
    except ValueError as e:
        logger.exception("파싱/청킹 중 오류 발생")
        raise HTTPException(status_code=500, detail=f"처리 실패: {e}") from e
    except Exception as e:
        logger.exception("파싱/청킹 중 오류 발생")
        raise HTTPException(status_code=500, detail=f"처리 실패: {e}")
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    # 응답 조립
    chunk_items: List[ChunkItem] = []
    for i, chunk in enumerate(result["chunks"], start=1):
        meta = chunk.metadata or {}
        chunk_items.append(ChunkItem(
            index=i,
            page=meta.get("page"),
            page_start=meta.get("page_start"),
            page_end=meta.get("page_end"),
            pages_display=meta.get("pages_display"),
            header_path=meta.get("header_path"),
            char_count=len(chunk.page_content),
            content=chunk.page_content,
            metadata={k: v for k, v in meta.items() if k not in ("source",)},
        ))

    return ParsePreviewResponse(
        filename=file.filename,
        file_type=result["file_type"],
        doc_type=result["doc_type"],
        is_law=result["is_law"],
        is_manual=result["is_manual"],
        total_pages=result["total_pages"],
        chunk_count=result["chunk_count"],
        chunks=chunk_items,
        requested_doc_type=result.get("requested_doc_type", "auto"),
        doc_type_source=result.get("doc_type_source"),
        detection_details=result.get("detection_details"),
    )

"""
문서 청킹 메인 프로세서

레퍼런스: reference_code/Chatbot_Backend_v1/app/services/pdf_chunking/pipeline/processor.py

PDF뿐 아니라 DOCX/PPTX/XLSX/이미지 등 다양한 포맷을 지원합니다.
파일 확장자에 따라 적절한 로더를 선택하고, 문서 유형(법령/매뉴얼/일반)을
자동 판정하여 최적의 청킹 전략을 적용합니다.
"""

import time
from pathlib import Path
from typing import List, Dict, Any, Optional

from .models import LCDocument, MdMeta, DocumentTypeDecision
from .config import ChunkingConfig
from app.core.config import get_settings
from .utils.converter import markdown_to_langchain
from .utils.spreadsheet_converter import spreadsheet_to_documents
from .detectors.law import is_law_like, count_law_signals
from .detectors.manual import count_manual_signals, is_manual_like, manual_score
from .chunkers.general import split_general_markdown
from .chunkers.law import split_law_markdown
from .chunkers.manual import split_manual_markdown
from .chunkers.spreadsheet import split_spreadsheet_documents
from .spreadsheet_contract import OOXML_SPREADSHEET_EXTENSIONS
from .document_types import (
    DocumentTypeSource,
    normalize_requested_doc_type,
    validate_document_type_compatibility,
)

from app.utils.log.log import LoggingLogger

# 로거 초기화
# 2026.07.16(sooyeon.choi) 수정 - 모듈별 named logger 적용
logger = LoggingLogger().getLogger(__name__)


# 2026.05.22(sooyeon.choi) 추가 - Docling 파싱 결과 마크다운을 instance 디렉터리에 저장
def _save_markdown(file_path: str, md_meta: MdMeta, save_dir: str) -> None:
    """파싱된 마크다운을 페이지 구분자와 함께 .md 파일로 저장한다."""
    out_dir = Path(save_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{Path(file_path).stem}.md"
    pages = []
    for item in md_meta:
        page_no = item.get("metadata", {}).get("page", "?")
        pages.append(f"<!-- page {page_no} -->\n{item['text']}")
    out_path.write_text("\n\n---\n\n".join(pages), encoding="utf-8")
    logger.info(f"마크다운 저장 완료: {out_path}")


# ── 파서(로더) 레지스트리 ─────────────────────────────────────────────────────
# 2026.07.16(sooyeon.choi) 추가 - 3단계 리팩토링: 파서 다중 지원 기반 (SFR-015)
#   기존 if/else 분기를 이름→팩토리 레지스트리 + 라우팅 규칙으로 전환.
#   OpenDataLoader, OCR 전용 파서 등은 DocumentParser 계약(app/interfaces/parser.py)을
#   만족하는 로더 작성 후 register_parser()로 등록하면 코드 수정 없이 편입된다.

def _create_pdfplumber_loader():
    from .loaders.pdf_loader import PdfPlumberLoader
    return PdfPlumberLoader()


def _create_docling_loader():
    from .loaders.docling_loader import DoclingApiLoader
    settings = get_settings()
    return DoclingApiLoader(
        host=settings.docling_parser_host,
        api_key=settings.docling_api_key,
        max_wait_seconds=settings.docling_max_wait_seconds,
        connect_timeout=settings.docling_connect_timeout,
        read_timeout=settings.docling_read_timeout,
    )


# 파서 이름 → 로더 팩토리
PARSER_REGISTRY: Dict[str, Any] = {
    "pdfplumber": _create_pdfplumber_loader,
    "docling": _create_docling_loader,
}


def register_parser(name: str, factory) -> None:
    """파서(로더) 팩토리를 등록한다. 동일 이름은 마지막 등록이 우선."""
    PARSER_REGISTRY[name] = factory
    logger.info("[PARSE][registry] 파서 등록: %s", name)


# 문서 파서 선택
def _resolve_parser_name(ext: str, config: ChunkingConfig) -> str:
    """확장자와 설정으로 사용할 파서 이름을 결정한다.

    라우팅 규칙:
    - PDF + parser_type="pdfplumber": pdfplumber (로컬, 빠름)
    - 그 외 모든 포맷:                docling (기본)
    - config.parser_type이 레지스트리에 등록된 이름이면 그대로 사용 (신규 파서 확장점)
    """
    if ext == "pdf" and config.parser_type == "pdfplumber":
        return "pdfplumber"
    if config.parser_type in PARSER_REGISTRY and config.parser_type != "pdfplumber":
        return config.parser_type
    return "docling"


def _get_loader(file_path: str, config: ChunkingConfig):
    """파일 확장자와 설정에 따라 적절한 로더를 반환합니다 (레지스트리 조회)."""
    ext = Path(file_path).suffix.lstrip(".").lower()
    parser_name = _resolve_parser_name(ext, config)
    return PARSER_REGISTRY[parser_name]()


# ── 청커 레지스트리 ───────────────────────────────────────────────────────────
# 2026.07.16(sooyeon.choi) 추가 - 3단계 리팩토링: 청킹 전략 다양화 기반 (SFR-019)
#   문서 유형별 if/else 분기를 doc_type→청커 레지스트리로 전환.
#   신규 전략(Semantic/Recursive 등)은 (docs, config) → chunks 계약
#   (app/interfaces/chunker.py)의 callable을 register_chunker()로 등록하면 편입된다.

def _chunk_law(docs: List[LCDocument], config: ChunkingConfig) -> List[LCDocument]:
    return split_law_markdown(
        docs,
        chunk_size=config.law_chunk_size,
        chunk_overlap=config.law_chunk_overlap,
    )


def _chunk_manual(docs: List[LCDocument], config: ChunkingConfig) -> List[LCDocument]:
    return split_manual_markdown(
        docs,
        chunk_size=config.manual_chunk_size,
        chunk_overlap=config.manual_chunk_overlap,
        section_prefix_format=config.manual_section_prefix_format,
    )


def _chunk_general(docs: List[LCDocument], config: ChunkingConfig) -> List[LCDocument]:
    # 일반 문서는 header_path 불필요
    for doc in docs:
        if doc.metadata and "header_path" in doc.metadata:
            doc.metadata["header_path"] = None
    return split_general_markdown(
        docs,
        chunk_size=config.general_chunk_size,
        chunk_overlap=config.general_chunk_overlap,
        include_header_path=config.include_header_path_in_content,
        header_path_format=config.header_path_format,
    )


def _chunk_spreadsheet(
    docs: List[LCDocument], config: ChunkingConfig
) -> List[LCDocument]:
    # 2026.08.27(sooyeon.choi) 수정 - IR block/record 기반 Excel 전용 청킹
    return split_spreadsheet_documents(docs, config)


# 문서 유형 → 청커 (Chunker 계약: (docs, config) → chunks)
CHUNKER_REGISTRY: Dict[str, Any] = {
    "law": _chunk_law,
    "manual": _chunk_manual,
    "general": _chunk_general,
    "spreadsheet": _chunk_spreadsheet,
}


def register_chunker(doc_type: str, chunker) -> None:
    """청커를 등록한다. 동일 doc_type은 마지막 등록이 우선."""
    CHUNKER_REGISTRY[doc_type] = chunker
    logger.info("[PARSE][registry] 청커 등록: %s", doc_type)


class DocumentChunkingProcessor:
    """
    다양한 문서 포맷을 처리하는 통합 청킹 프로세서.

    지원 포맷:
    - PDF  : pdfplumber(기본) 또는 Docling API
    - DOCX : Docling API (Phase 2)
    - PPTX : Docling API (Phase 3)
    - 이미지: Docling API (Phase 4)
    - XLSX : Docling API (Phase 5)
    """

    def __init__(self, config: Optional[ChunkingConfig] = None):
        self.config = config or ChunkingConfig()
        self.config.requested_doc_type = normalize_requested_doc_type(
            self.config.requested_doc_type
        )
        logger.info(f"DocumentChunkingProcessor 초기화 완료: parser={self.config.parser_type}")

    def process(
        self,
        file_path: str,
        md_meta: Optional[MdMeta] = None,
        document_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        파일을 처리하여 청킹 결과를 반환합니다.

        Args:
            file_path: 처리할 파일 경로
            md_meta: 이미 추출된 마크다운 메타데이터 (캐시 재활용 시)

        Returns:
            {
                "chunks": List[LCDocument],   # 청킹 결과
                "total_pages": int,
                "chunk_count": int,
                "is_law": bool,
                "is_manual": bool,
                "doc_type": str,              # "law" | "manual" | "general"
                "file_type": str,             # "pdf" | "docx" | ...
            }
        """
        file_path = str(file_path)
        ext = Path(file_path).suffix.lstrip(".").lower()
        process_start = time.perf_counter()
        logger.info("[PARSE][pipeline] 시작 file=%s ext=%s", file_path, ext)
        # logger.info(f"문서 처리 시작: {file_path} (ext={ext})")

        # 1. 로딩 (마크다운 메타데이터 획득)
        if md_meta is None:
            loader = _get_loader(file_path, self.config)
            load_start = time.perf_counter()
            logger.info("[PARSE][step=load] 시작 loader=%s", type(loader).__name__)
            # logger.info(f"로더 선택: {type(loader).__name__}")
            # 2026.08.27(sooyeon.choi) 추가 - Excel IR document_id 계약 전달
            if ext in OOXML_SPREADSHEET_EXTENSIONS:
                md_meta = loader.load(file_path, document_id=document_id)
            else:
                md_meta = loader.load(file_path)
            logger.info(
                "[PARSE][step=load] 완료loader=%s pages=%s elapsed=%.2fs",
                type(loader).__name__,
                len(md_meta),
                time.perf_counter() - load_start,
            )
            # logger.info(f"로딩 완료: {len(md_meta)}페이지")
            # 2026.05.22(sooyeon.choi) 추가 - 파싱 결과 마크다운 저장
            save_dir = get_settings().md_save_dir
            if save_dir:
                _save_markdown(file_path, md_meta, save_dir)
        else:
            logger.info("[PARSE][step=load] 캐시사용pages=%s", len(md_meta))
            # logger.info("캐시된 마크다운 메타데이터 재사용")

        total_pages = len(md_meta)

        if ext in OOXML_SPREADSHEET_EXTENSIONS:
            # 2026.08.27(sooyeon.choi) 수정 - backend에서도 IR 단일 처리 경로 식별
            spreadsheet_meta = md_meta[0].get("metadata", {}) if md_meta else {}
            logger.info(
                "[PARSE][step=spreadsheet_engine] processing_engine=%s processing_path=%s",
                spreadsheet_meta.get("processing_engine") or "ir",
                spreadsheet_meta.get("processing_path") or "structured_ir",
            )

        # 2. LCDocument 변환 (헤더 승격, 텍스트 정제 포함)
        convert_start = time.perf_counter()
        # 2026.08.27(sooyeon.choi) 추가 - Excel은 IR converter로 보내고 Markdown 재파싱 금지
        if ext in OOXML_SPREADSHEET_EXTENSIONS:
            docs = spreadsheet_to_documents(md_meta, source_path=file_path)
        else:
            docs = markdown_to_langchain(
                md_meta,
                flatten_tables=self.config.flatten_tables,
                source_path=file_path,
                extract_header_path=True,
            )
        logger.info(
            "[PARSE][step=preprocess] 완료 docs=%s elapsed=%.2fs",
            len(docs),
            time.perf_counter() - convert_start,
        )
        # logger.info(f"LCDocument 변환 완료: {len(docs)}개")

        # 3. 문서 유형 판정
        first_page_text = docs[0].page_content if docs else ""
        sample_text = "\n".join(
            d.page_content for d in docs[:min(self.config.sample_pages, len(docs))]
        )

        is_spreadsheet = ext in OOXML_SPREADSHEET_EXTENSIONS
        requested_doc_type = normalize_requested_doc_type(self.config.requested_doc_type)
        validate_document_type_compatibility(ext, requested_doc_type)
        decision = self._resolve_document_type(
            requested_doc_type=requested_doc_type,
            extension=ext,
            sample_text=sample_text,
            first_page_text=first_page_text,
            is_spreadsheet=is_spreadsheet,
            sample_document_count=min(self.config.sample_pages, len(docs)),
        )
        law_flag = decision.effective_doc_type == "law"
        manual_flag = decision.effective_doc_type == "manual"
        # logger.info(f"문서 유형 판정: law={law_flag}, manual={manual_flag}")

        # 4. 청킹
        # 2026.07.16(sooyeon.choi) 수정 - 유형별 if/else 분기를 청커 레지스트리 조회로 전환 (3단계)
        chunk_start = time.perf_counter()
        doc_type = decision.effective_doc_type
        if doc_type not in CHUNKER_REGISTRY:
            raise ValueError(f"등록되지 않은 문서 유형 청커입니다: {doc_type}")
        chunker = CHUNKER_REGISTRY[doc_type]
        chunks = chunker(docs, self.config)

        logger.info(
            "[PARSE][step=chunk] 완료 chunks=%s doc_type=%s elapsed=%.2fs",
            len(chunks),
            doc_type,
            time.perf_counter() - chunk_start,
        )
        # logger.info(f"청킹 완료: {len(chunks)}개 청크 (유형: {doc_type})")
        logger.info(
            "[PARSE][pipeline] 완료 file=%s pages=%s chunks=%s doc_type=%s elapsed=%.2fs",
            file_path,
            total_pages,
            len(chunks),
            doc_type,
            time.perf_counter() - process_start,
        )

        return {
            "chunks": chunks,
            "total_pages": total_pages,
            "chunk_count": len(chunks),
            "is_law": law_flag,
            "is_manual": manual_flag,
            "doc_type": doc_type,
            "file_type": ext,
            "requested_doc_type": decision.requested_doc_type,
            "doc_type_source": decision.source,
            "detection_details": decision.detector_details,
        }

    def _resolve_document_type(
        self,
        *,
        requested_doc_type: str,
        extension: str,
        sample_text: str,
        first_page_text: str,
        is_spreadsheet: bool,
        sample_document_count: int,
    ) -> DocumentTypeDecision:
        if requested_doc_type != "auto":
            return DocumentTypeDecision(
                requested_doc_type=requested_doc_type,
                effective_doc_type=requested_doc_type,
                source=DocumentTypeSource.USER_SELECTED.value,
                law_detected=requested_doc_type == "law",
                manual_detected=requested_doc_type == "manual",
                detector_details=None,
            )

        if is_spreadsheet:
            return DocumentTypeDecision(
                requested_doc_type="auto",
                effective_doc_type="spreadsheet",
                source=DocumentTypeSource.FILE_EXTENSION.value,
                detector_details={
                    "detector_skipped": True,
                    "reason": "ooxml_spreadsheet_extension",
                },
            )

        detect_start = time.perf_counter()
        law_signals = count_law_signals(sample_text)
        law_flag = is_law_like(
            sample_text,
            score_threshold=self.config.law_score_threshold,
            article_threshold=self.config.law_article_threshold,
            first_page_text=first_page_text,
        )
        manual_signals = None
        manual_score_value = None
        manual_flag = False
        if not law_flag:
            manual_signals = count_manual_signals(sample_text)
            manual_score_value = manual_score(sample_text)
            manual_flag = is_manual_like(
                sample_text,
                score_threshold=self.config.manual_score_threshold,
            )
        law_score = 2 * sum(
            law_signals.get(key, 0)
            for key in ("편", "장", "절", "관", "조", "별표", "별지")
        ) + sum(law_signals.get(key, 0) for key in ("항", "호", "목"))
        details = {
            "detector_skipped": False,
            "sample_document_count": sample_document_count,
            "law_detected": law_flag,
            "manual_detected": manual_flag if not law_flag else None,
            "law_score": law_score,
            "manual_score": manual_score_value,
            "law_signals": law_signals,
            "manual_signals": manual_signals,
        }
        logger.info(
            "event=document_type_resolved requested_type=%s effective_type=%s source=%s extension=%s law_detected=%s manual_detected=%s detector_skipped=false elapsed=%.2fs",
            requested_doc_type,
            "law" if law_flag else "manual" if manual_flag else "general",
            DocumentTypeSource.AUTO_DETECTED.value,
            extension,
            law_flag,
            manual_flag if not law_flag else None,
            time.perf_counter() - detect_start,
        )
        effective = "law" if law_flag else "manual" if manual_flag else "general"
        return DocumentTypeDecision(
            requested_doc_type="auto",
            effective_doc_type=effective,
            source=DocumentTypeSource.AUTO_DETECTED.value,
            law_detected=law_flag,
            manual_detected=manual_flag,
            detector_details=details,
        )


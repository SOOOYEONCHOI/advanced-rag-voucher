"""
Docling 파싱 서비스
GPU를 사용하여 Docling 파싱 실행
"""
import json
import re
import asyncio
import time
from pathlib import Path
from typing import Dict, Any, Optional
from app.utils.log.log import LoggingLogger
from app.core.config import EXCEL_PARSER, SUPPORTED_EXCEL_PARSERS

# 2025.12.26: Docling 라이브러리 직접 참조 (안정성 향상)
from docling.document_converter import DocumentConverter
from docling.datamodel.base_models import InputFormat
# 2026.08.13(sooyeon.choi) 수정 - 설정에 따라 Docling Excel 파서를 사용할 수 있도록 옵션 추가
from docling.document_converter import PdfFormatOption, WordFormatOption, PowerpointFormatOption, ExcelFormatOption, ImageFormatOption
from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode, TableStructureOptions, EasyOcrOptions
# 2026.08.12(sooyeon.choi) 추가 - OOXML Excel 문서를 Docling과 분리
from app.spreadsheets.parser import OpenpyxlExcelParser

logger_instance = LoggingLogger()
logger = logger_instance.getLogger()

class DocumentParser:
    """Docling 기반 문서 파싱 서비스"""

    # 2026.08.13(sooyeon.choi) 수정 - 운영 설정과 테스트 직접 주입을 모두 지원
    def __init__(self, excel_parser_type: str = EXCEL_PARSER):
        self.excel_parser_type = excel_parser_type.strip().lower()
        if self.excel_parser_type not in SUPPORTED_EXCEL_PARSERS:
            allowed = ", ".join(sorted(SUPPORTED_EXCEL_PARSERS))
            raise ValueError(
                f"Invalid Excel parser: {self.excel_parser_type}. Allowed: {allowed}"
            )
        # 2026.03.18 수정 - GPU 동시 실행 방지용 Semaphore 추가
        # asyncio.Semaphore는 이벤트 루프에 귀속되므로 parse() 첫 호출 시 lazy 초기화
        self._gpu_semaphore: Optional[asyncio.Semaphore] = None
        # 2026.08.12(sooyeon.choi) 추가 - Excel CPU 작업 동시 실행 제한
        self._excel_semaphore: Optional[asyncio.Semaphore] = None
        self.excel_parser = OpenpyxlExcelParser()

        # PDF용: OCR 비활성 (텍스트 레이어 존재)
        pipeline_options = PdfPipelineOptions()
        pipeline_options.do_ocr = False
        pipeline_options.do_table_structure = True
        pipeline_options.table_structure_options.mode = TableFormerMode.ACCURATE

        # 스캔 PDF용: OCR 활성 (텍스트 레이어 없음) - EasyOCR + GPU
        pdf_ocr_pipeline_options = PdfPipelineOptions()
        pdf_ocr_pipeline_options.do_ocr = True
        pdf_ocr_pipeline_options.ocr_options = EasyOcrOptions(use_gpu=True, lang=["ko", "en"])
        pdf_ocr_pipeline_options.do_table_structure = True
        pdf_ocr_pipeline_options.table_structure_options.mode = TableFormerMode.ACCURATE

        # 이미지용: OCR 활성 (텍스트 레이어 없음) - EasyOCR + GPU
        image_pipeline_options = PdfPipelineOptions()
        image_pipeline_options.do_ocr = True
        image_pipeline_options.ocr_options = EasyOcrOptions(use_gpu=True, lang=["ko", "en"])
        image_pipeline_options.do_table_structure = True
        image_pipeline_options.table_structure_options = TableStructureOptions(
            do_cell_matching=True
        )

        try:
            # 텍스트 레이어 PDF용 converter
            self.converter = DocumentConverter(
                format_options={
                    InputFormat.PDF:   PdfFormatOption(pipeline_options=pipeline_options),
                    InputFormat.DOCX:  WordFormatOption(),
                    InputFormat.PPTX:  PowerpointFormatOption(),
                    # 2026.08.13(sooyeon.choi) 수정 - Docling Excel 선택 경로 활성화
                    InputFormat.XLSX:  ExcelFormatOption(),
                    InputFormat.IMAGE: ImageFormatOption(pipeline_options=image_pipeline_options),
                }
            )
            # 스캔 PDF용 converter (OCR 활성)
            self.converter_ocr = DocumentConverter(
                format_options={
                    InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_ocr_pipeline_options),
                }
            )
            logger.info("INFO: DocumentConverter initialized successfully.")
        except Exception as e:
            logger.info(f"ERROR: Failed to initialize DocumentConverter: {e}")
            raise e

    def _has_text_layer(self, file_path: str, sample_pages: int = 3, min_words_per_page: int = 10) -> bool:
        """
        PDF 텍스트 레이어 존재 여부 확인 (PyMuPDF 사용).
        앞 N페이지를 샘플링하여 페이지당 평균 의미 단어(한글·영문 2자 이상) 수가
        기준치 이상이면 텍스트 레이어 있다고 판단.
        페이지 번호·워터마크 등 단순 숫자/기호만 있는 스캔본을 텍스트 PDF로 오판하는 문제 방지.
        """
        # 2026.06.17(sooyeon.choi) 수정 - 글자 수 대신 의미 단어 수 기준으로 변경하여 스캔본 오판 방지
        try:
            import re
            import fitz  # PyMuPDF (Docling 의존성에 포함)
            doc = fitz.open(file_path)
            pages_to_check = min(sample_pages, len(doc))
            total_words = 0
            for i in range(pages_to_check):
                text = doc[i].get_text()
                # 한글(가-힣) 또는 영문(a-zA-Z)을 포함하는 2자 이상 토큰만 집계
                words = re.findall(r'[가-힣a-zA-Z][가-힣a-zA-Z0-9]{1,}', text)
                total_words += len(words)
            doc.close()
            has_text = total_words >= min_words_per_page * pages_to_check
            logger.info(f"INFO: PDF text layer check - total_words={total_words}, threshold={min_words_per_page * pages_to_check}, has_text={has_text}")
            return has_text
        except Exception as e:
            # 감지 실패 시 텍스트 레이어 있다고 가정 (OCR 미적용 - 안전한 기본값)
            logger.info(f"WARN: Failed to check PDF text layer, assuming text exists: {e}")
            return True

    def _convert_sync(self, file_path: str):
        """동기식 변환 (텍스트 레이어 PDF용)"""
        logger.info(f"INFO: Converting file (Sync): {file_path}")
        return self.converter.convert(file_path)

    def _convert_sync_ocr(self, file_path: str):
        """동기식 변환 (스캔 PDF OCR용)"""
        logger.info(f"INFO: Converting file with OCR (Sync): {file_path}")
        return self.converter_ocr.convert(file_path)

    # 2026.08.13(sooyeon.choi) 수정 - 선택된 Excel 파서 실행 및 식별 로그 통합
    async def _parse_excel(
        self,
        file_path: str,
        output_format: str,
        document_id: str | None = None,
    ) -> Dict[str, Any]:
        parser_name = self.excel_parser_type
        ext = Path(file_path).suffix.lower()
        started_at = time.perf_counter()
        logger.info(
            "Excel parsing started: parser=%s extension=%s output_format=%s file=%s",
            parser_name,
            ext,
            output_format,
            Path(file_path).name,
        )

        if self._excel_semaphore is None:
            self._excel_semaphore = asyncio.Semaphore(2)

        try:
            async with self._excel_semaphore:
                if parser_name == "openpyxl":
                    result = await asyncio.to_thread(
                        self.excel_parser.parse,
                        file_path,
                        output_format,
                        document_id,
                    )
                else:
                    converted = await asyncio.to_thread(self._convert_sync, file_path)
                    result = self._build_docling_excel_result(
                        converted.document,
                        file_path,
                        output_format,
                    )

            result.setdefault("metadata", {})
            result["metadata"]["parser"] = parser_name
            result["metadata"]["source_type"] = "spreadsheet"
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            logger.info(
                "Excel parsing completed: parser=%s extension=%s format=%s pages=%s elapsed_ms=%.1f",
                parser_name,
                ext,
                result.get("format"),
                result.get("num_pages", 0),
                elapsed_ms,
            )
            return result
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            logger.error(
                "Excel parsing failed: parser=%s extension=%s elapsed_ms=%.1f error=%s",
                parser_name,
                ext,
                elapsed_ms,
                exc,
            )
            raise

    # 2026.08.13(sooyeon.choi) 수정 - Docling Excel 결과를 기존 API 응답 계약으로 변환
    def _build_docling_excel_result(
        self,
        document,
        file_path: str,
        output_format: str,
    ) -> Dict[str, Any]:
        if output_format == "json":
            content = document.export_to_dict()
            num_pages = len(document.pages) if getattr(document, "pages", None) else 1
            return {
                "format": "json",
                "content": content,
                "metadata": {
                    "file_path": file_path,
                    "num_pages": num_pages,
                    "is_scanned": False,
                },
                "num_pages": num_pages,
            }
        if output_format != "md":
            raise ValueError(f"Unsupported output format: {output_format}")

        pages_output = []
        if getattr(document, "pages", None):
            try:
                sorted_pages = sorted(document.pages.items(), key=lambda item: int(item[0]))
            except Exception:
                sorted_pages = list(document.pages.items())
            for sheet_no, _ in sorted_pages:
                sheet_md = self._sanitize_text(
                    document.export_to_markdown(page_no=sheet_no)
                )
                pages_output.append({"page_no": sheet_no, "markdown": sheet_md})
        else:
            full_md = self._sanitize_text(document.export_to_markdown())
            pages_output.append({"page_no": 1, "markdown": full_md})

        return {
            "format": "md",
            "pages": pages_output,
            "num_pages": len(pages_output),
            "metadata": {
                "file_path": file_path,
                "num_pages": len(pages_output),
                "is_scanned": False,
            },
        }

    # 2025.12.30: 텍스트 레이어 인코딩 오류 보정 (/uniXXXX -> 문자)
    def _sanitize_text(self, text: str) -> str:
        """
        PDF 텍스트 레이어 손상으로 인한 Glyph Name 누출(/uniXXXX)을 실제 유니코드 문자로 변환
        예: /uniACF5 -> 공
        """
        if not text:
            return text

        def _replace_glyph_name(match):
            try:
                return chr(int(match.group(1), 16))
            except:
                return match.group(0)

        return re.sub(r'/uni([0-9A-Fa-f]{4})', _replace_glyph_name, text)

    async def parse(
        self,
        file_path: str,
        output_format: str = "md",
        document_id: str | None = None,
    ) -> Dict[str, Any]:
        """
        문서 파싱 실행

        Args:
            file_path: 파싱할 파일 경로
            output_format: 출력 형식 ("md" or "json")

        Returns:
            파싱 결과 딕셔너리
        """
        try:
            # 2026.08.13(sooyeon.choi) 수정 - 설정에 따라 OpenPyXL 또는 Docling으로 Excel 분기
            ext = Path(file_path).suffix.lower()
            if ext in OpenpyxlExcelParser.SUPPORTED_EXTENSIONS:
                return await self._parse_excel(file_path, output_format, document_id)

            # 2026.03.18 수정 - GPU 동시 실행 방지: Semaphore lazy 초기화
            if self._gpu_semaphore is None:
                self._gpu_semaphore = asyncio.Semaphore(1)

            # 2026.04.03 수정 - 스캔 PDF 감지: 텍스트 레이어 없으면 OCR converter 사용
            # 2026.06.17(sooyeon.choi) 수정 - 스캔 여부를 결과 metadata에 포함하기 위해 is_scanned 변수 추가
            if ext == ".pdf" and not self._has_text_layer(file_path):
                logger.info("INFO: Scanned PDF detected - using OCR converter (EasyOCR+GPU).")
                convert_fn = self._convert_sync_ocr
                is_scanned = True
            else:
                convert_fn = self._convert_sync
                is_scanned = False

            async with self._gpu_semaphore:
                doc = await asyncio.to_thread(convert_fn, file_path)

            document = doc.document

            if output_format == "md":
                pages_output = []

                if ext == ".pdf":
                    if hasattr(document, "pages"):
                        try:
                            sorted_pages = sorted(document.pages.items(), key=lambda x: int(x[0]))
                        except:
                            sorted_pages = document.pages.items()

                        for page_no, page_item in sorted_pages:
                            page_md = document.export_to_markdown(page_no=page_no)
                            page_md = self._sanitize_text(page_md)
                            pages_output.append({
                                "page_no": page_no,
                                "markdown": page_md
                            })

                elif ext in [".docx", ".dotx", ".docm", ".dotm"]:
                    full_md = document.export_to_markdown()
                    full_md = self._sanitize_text(full_md)
                    pages_output.append({"page_no": 1, "markdown": full_md})

                elif ext in [".pptx", ".pptm", ".potx", ".potm"]:
                    if hasattr(document, "pages") and document.pages:
                        try:
                            sorted_pages = sorted(document.pages.items(), key=lambda x: int(x[0]))
                        except Exception:
                            sorted_pages = list(document.pages.items())

                        for slide_no, _ in sorted_pages:
                            slide_md = document.export_to_markdown(page_no=slide_no)
                            slide_md = self._sanitize_text(slide_md)
                            pages_output.append({"page_no": slide_no, "markdown": slide_md})
                    else:
                        full_md = document.export_to_markdown()
                        full_md = self._sanitize_text(full_md)
                        pages_output.append({"page_no": 1, "markdown": full_md})

                elif ext in [".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp"]:
                    if hasattr(document, "pages") and len(document.pages) > 1:
                        try:
                            sorted_pages = sorted(document.pages.items(), key=lambda x: int(x[0]))
                        except Exception:
                            sorted_pages = list(document.pages.items())

                        for page_no, _ in sorted_pages:
                            page_md = document.export_to_markdown(page_no=page_no)
                            page_md = self._sanitize_text(page_md)
                            pages_output.append({"page_no": page_no, "markdown": page_md})
                    else:
                        full_md = document.export_to_markdown()
                        full_md = self._sanitize_text(full_md)
                        pages_output.append({"page_no": 1, "markdown": full_md})

                num_pages = len(pages_output)
                result = {
                    "format": "md",
                    "pages": pages_output,
                    "num_pages": num_pages,
                    "metadata": {
                        "file_path": file_path,
                        "num_pages": num_pages,
                        "is_scanned": is_scanned,  # 2026.06.17(sooyeon.choi) 수정 - 스캔 PDF 여부 표시
                    }
                }

            else:  # JSON
                content = document.export_to_dict()

                num_pages = 0
                if hasattr(document, "num_pages"):
                    num_pages = document.num_pages() if callable(document.num_pages) else document.num_pages
                elif hasattr(document, "pages"):
                    num_pages = len(document.pages)

                result = {
                    "format": "json",
                    "content": content,
                    "metadata": {
                        "file_path": file_path,
                        "num_pages": num_pages,
                        "is_scanned": is_scanned,  # 2026.06.17(sooyeon.choi) 수정 - 스캔 PDF 여부 표시
                    }
                }

            return result

        except Exception as e:
            import traceback
            traceback.print_exc()
            raise RuntimeError(f"Error during Docling parsing: {str(e)}")

"""
PDF 로더 (pdfplumber 기반, 로컬 처리)
레퍼런스: reference_code/Chatbot_Backend_v1/app/services/pdf_chunking/document/pdf_loader.py

표 위 텍스트 누락 문제를 해결하기 위해 Y좌표 기반으로 텍스트와 표를 결합합니다.
"""

import logging
from typing import List

from .base import BaseDocumentLoader, MdMeta

logger = logging.getLogger(__name__)


class PdfPlumberLoader(BaseDocumentLoader):
    """pdfplumber를 사용한 PDF 로더 (로컬, GPU 불필요)"""

    def load(self, file_path: str) -> MdMeta:
        try:
            import pdfplumber
        except ImportError:
            raise RuntimeError("pdfplumber가 설치되지 않았습니다. pip install pdfplumber")

        logger.info(f"pdfplumber로 PDF 로드 시작: {file_path}")
        result: MdMeta = []

        with pdfplumber.open(file_path) as pdf:
            total_pages = len(pdf.pages)
            logger.info(f"총 페이지 수: {total_pages}")

            for page_num, page in enumerate(pdf.pages, start=1):
                logger.debug(f"페이지 {page_num}/{total_pages} 처리 중")
                try:
                    edges = page.edges or []
                    if edges:
                        table_settings = {
                            "horizontal_strategy": "lines",
                            "explicit_horizontal_lines": [
                                min(e["top"] for e in edges if "top" in e),
                                max(e["bottom"] for e in edges if "bottom" in e),
                            ],
                            "vertical_strategy": "lines",
                            "explicit_vertical_lines": [
                                min(e["x0"] for e in edges if "x0" in e),
                                max(e["x1"] for e in edges if "x1" in e),
                            ],
                        }
                    else:
                        table_settings = {
                            "horizontal_strategy": "lines",
                            "vertical_strategy": "lines",
                        }

                    found_tables = page.find_tables(table_settings=table_settings)
                    combined_text = _extract_page_content_with_tables(page, found_tables)

                    result.append({
                        "text": combined_text,
                        "metadata": {
                            "page": page_num,
                            "page_count": total_pages,
                            "file_path": file_path,
                            "file_type": "pdf",
                        },
                    })
                except Exception as e:
                    logger.error(f"페이지 {page_num} 처리 실패: {e}", exc_info=True)
                    raise

        logger.info(f"pdfplumber 로드 완료: {len(result)}페이지")
        return result


def _extract_page_content_with_tables(page, found_tables: List) -> str:
    """페이지의 텍스트와 표를 Y좌표 기반으로 중복 없이 결합"""
    if not found_tables:
        return page.extract_text() or ""

    found_tables.sort(key=lambda t: t.bbox[1])
    content_parts = []
    last_bottom = 0
    page_height = page.height
    page_width = page.width

    for table_obj in found_tables:
        bbox = table_obj.bbox
        table_top = bbox[1]
        table_bottom = bbox[3]

        if table_top > last_bottom and table_top - last_bottom > 1:
            try:
                cropped_page = page.crop((0, last_bottom, page_width, table_top))
                text_segment = cropped_page.extract_text()
                if text_segment:
                    content_parts.append(text_segment.strip())
            except Exception as e:
                logger.info(f"텍스트 crop 실패: {e}")

        try:
            table_data = table_obj.extract()
            if table_data:
                md_table = _table_to_markdown(table_data)
                if md_table:
                    content_parts.append(md_table)
        except Exception as e:
            logger.info(f"테이블 추출 실패: {e}")

        last_bottom = max(last_bottom, table_bottom)

    if last_bottom < page_height and page_height - last_bottom > 1:
        try:
            cropped_page = page.crop((0, last_bottom, page_width, page_height))
            text_segment = cropped_page.extract_text()
            if text_segment:
                content_parts.append(text_segment.strip())
        except Exception as e:
            logger.info(f"마지막 텍스트 crop 실패: {e}")

    result = "\n\n".join(content_parts)
    return "\n".join(line for line in result.splitlines() if line.strip() or line == "")


def _table_to_markdown(table: List) -> str:
    """표를 마크다운 테이블 형식으로 변환"""
    if not table or not table[0]:
        return ""

    def clean_cell(cell):
        if cell is None:
            return ""
        return str(cell).strip().replace("\n", "<br>").replace("\r", "").replace("|", "\\|")

    header = table[0]
    if not header:
        return ""

    cleaned_header = [clean_cell(c) for c in header]
    header_len = len(cleaned_header)
    lines = [
        "| " + " | ".join(cleaned_header) + " |",
        "| " + " | ".join(["---"] * header_len) + " |",
    ]

    for row in (table[1:] if len(table) > 1 else []):
        row_cells = [clean_cell(c) for c in row]
        if len(row_cells) < header_len:
            row_cells.extend([""] * (header_len - len(row_cells)))
        elif len(row_cells) > header_len:
            row_cells = row_cells[:header_len]
        lines.append("| " + " | ".join(row_cells) + " |")

    return "\n".join(lines)
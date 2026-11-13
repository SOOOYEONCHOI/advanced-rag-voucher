"""
Docling API 기반 범용 문서 로더
레퍼런스: reference_code/Chatbot_Backend_v1/app/services/pdf_chunking/document/pdf_loader.py
         (load_pdf_with_docling_api, _map_docling_result)

GPU 서버의 Docling API를 호출하여 PDF/DOCX/PPTX/XLSX/이미지 등을 파싱합니다.
비동기 Job 폴링 방식으로 처리합니다.
"""

import os
import time
import logging
from pathlib import Path
# 2026.11.09(sooyeon.choi) 삭제 - 미사용 import(typing.List)

import requests

from .base import BaseDocumentLoader, MdMeta
from ..utils.text_cleaner import normalize_markdown_table_separators, rm_unnecessary_char
from ..spreadsheet_contract import OOXML_SPREADSHEET_EXTENSIONS, validate_spreadsheet_ir

logger = logging.getLogger(__name__)

# ── Docling API 설정 ────────────────────────────────────────────────────────
DOCLING_PARSER_HOST = os.environ.get("DOCLING_PARSER_HOST", "")
DOCLING_API_KEY = os.environ.get("DOCLING_API_KEY", "")
# 2026.08.28(sooyeon.choi) 추가 - 파서가 resource를 회신할 이 백엔드의 주소.
#   파서는 공용이라 전역 BACKEND_INTERNAL_URL 하나로는 요청자를 구분할 수 없으므로
#   parse 요청마다 회신 주소를 함께 보낸다. 파서 쪽 allowlist에 등록돼 있어야 한다.
BACKEND_CALLBACK_URL = os.environ.get("BACKEND_CALLBACK_URL", "")
# 2026.08.28(sooyeon.choi) 추가 - resource 전달 방식.
#   pull: 파서가 보관하고 백엔드가 가져간다(백엔드가 파서에서 접근 불가해도 동작).
#   push: 파서가 백엔드로 업로드한다(백엔드가 파서에서 접근 가능해야 함).
RESOURCE_DELIVERY = os.environ.get("RESOURCE_DELIVERY", "pull")

_API_PARSE = "/api/parse"
_API_JOB   = "/api/job"

class DoclingApiLoader(BaseDocumentLoader):
    """
    GPU 서버의 Docling API를 사용하는 범용 문서 로더.

    지원 포맷: PDF, DOCX, PPTX, XLSX, PNG/JPG/TIFF/BMP/WEBP
    모든 포맷을 마크다운으로 변환하여 반환.
    """

    def __init__(
        self,
        host: str = "",
        api_key: str = "",
        poll_interval: float = 2.0,   # 폴링 간격(초)
        max_wait_seconds: int = 1200,
        connect_timeout: int = 10,
        read_timeout: int = 1200,
        callback_url: str = "",
    ):
        self.host = host or DOCLING_PARSER_HOST
        self.api_key = api_key or DOCLING_API_KEY
        self.callback_url = callback_url or BACKEND_CALLBACK_URL
        self.poll_interval = poll_interval
        self.max_retries = int(max_wait_seconds / poll_interval)
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout

        if not self.host:
            raise ValueError(
                "Docling API 호스트가 설정되지 않았습니다. "
                "환경변수 DOCLING_PARSER_HOST를 설정하거나 host 파라미터를 전달하세요."
            )

    def load(self, file_path: str, document_id: str | None = None) -> MdMeta:
        """
        파일을 Docling API로 파싱하여 페이지별 마크다운 메타데이터 반환.

        Args:
            file_path: 처리할 파일 경로

        Returns:
            MdMeta (List[{"text": str, "metadata": dict}])
        """
        ext = Path(file_path).suffix.lstrip(".").lower()
        load_start = time.perf_counter()
        logger.info("[PARSE][step=docling_api] 시작 file=%s ext=%s", file_path, ext)

        headers = {}
        if self.api_key:
            headers["X-API-KEY"] = self.api_key

        # 1. 파일 업로드 및 Job 생성
        try:
            job_id = self._submit_job(file_path, headers, document_id)
        except _SyncResponse as e:
            mapped = self._map_result(e.results, file_path, ext)
            logger.info(
                "[PARSE][step=docling_api] 완료 mode=sync pages=%s elapsed=%.2fs",
                len(mapped),
                time.perf_counter() - load_start,
            )
            return mapped

        # 2. Job 폴링
        result_data = self._poll_job(job_id, headers)

        # 3. 결과 매핑
        mapped = self._map_result(result_data, file_path, ext)
        # 2026.08.27(sooyeon.choi) 추가 - backend resource commit/rollback용 parser job ID 전달
        for item in mapped:
            item.setdefault("metadata", {})["parse_job_id"] = job_id
        logger.info(
            "[PARSE][step=docling_api] 완료mode=job job_id=%s pages=%s elapsed=%.2fs",
            job_id,
            len(mapped),
            time.perf_counter() - load_start,
        )
        return mapped

    def _submit_job(self, file_path: str, headers: dict, document_id: str | None = None) -> str:
        """파일을 업로드하고 Job ID를 반환"""
        api_url = f"{self.host}{_API_PARSE}"
        submit_start = time.perf_counter()
        # 2026.08.28(sooyeon.choi) 수정 - document_id와 callback_url을 함께 전달
        form_data: dict = {}
        if document_id:
            form_data["document_id"] = document_id
        if self.callback_url:
            form_data["callback_url"] = self.callback_url
        if RESOURCE_DELIVERY:
            form_data["resource_delivery"] = RESOURCE_DELIVERY
        try:
            with open(file_path, "rb") as f:
                response = requests.post(
                    api_url,
                    files={"file": f},
                    data=form_data or None,
                    headers=headers,
                    timeout=(self.connect_timeout, self.read_timeout),
                )
        except FileNotFoundError:
            raise FileNotFoundError(f"파일을 찾을 수 없습니다: {file_path}")

        if response.status_code not in (200, 202):
            raise RuntimeError(f"Docling API 요청 실패: {response.status_code} - {response.text}")

        res_data = response.json()
        job_id = res_data.get("job_id")

        if not job_id:
            # 동기 응답인 경우 (예외적 상황)
            if "results" in res_data:
                logger.info(
                    "[PARSE][step=docling_submit] 완료 mode=sync status_code=%s elapsed=%.2fs",
                    response.status_code,
                    time.perf_counter() - submit_start,
                )
                raise _SyncResponse(res_data["results"])
            raise RuntimeError(f"Job ID를 응답받지 못했습니다: {res_data}")

        logger.info(
            "[PARSE][step=docling_submit] 완료job_id=%s status_code=%s elapsed=%.2fs",
            job_id,
            response.status_code,
            time.perf_counter() - submit_start,
        )
        return job_id

    def _poll_job(self, job_id: str, headers: dict) -> dict:
        """Job이 완료될 때까지 폴링하여 결과 데이터 반환"""
        status_url = f"{self.host}{_API_JOB}/{job_id}"
        result_url = f"{self.host}{_API_JOB}/{job_id}/result"
        poll_start = time.perf_counter()

        for _ in range(self.max_retries):
            time.sleep(self.poll_interval)
            try:
                status_res = requests.get(status_url, headers=headers, timeout=60)
                if status_res.status_code != 200:
                    logger.info(f"상태 조회 실패 (Code: {status_res.status_code})")
                    continue

                data = status_res.json()
                status = data.get("status")

                if status == "completed":
                    logger.info(
                        "[PARSE][step=docling_poll] 완료 job_id=%s elapsed=%.2fs",
                        job_id,
                        time.perf_counter() - poll_start,
                    )
                    result_res = requests.get(result_url, headers=headers, timeout=self.read_timeout)
                    if result_res.status_code == 200:
                        return result_res.json()
                    raise RuntimeError(f"결과 조회 실패: {result_res.status_code} - {result_res.text}")
                elif status == "failed":
                    raise RuntimeError(f"Docling Job 실패: {data.get('error')}")
                else:
                    logger.debug(f"Job 진행 중... ({status})")

            except requests.exceptions.RequestException as e:
                logger.info(f"폴링 중 통신 오류 (재시도): {e}")
                continue

        raise TimeoutError(f"Docling Job 시간 초과 (최대 {self.max_retries * self.poll_interval}초)")

    def _map_result(self, docling_output: dict, file_path: str, file_type: str) -> MdMeta:
        """
        Docling API 응답을 내부 MdMeta 포맷으로 변환.

        예상 응답 구조:
        {
            "pages": [{"page_no": 1, "markdown": "..."}, ...],
            "num_pages": 10
        }

        헤더(#) 처리 전략:
        - PDF/DOCX/이미지: 제거. Docling 레이아웃 추론 헤더는 노이즈가 많고, DOCX도
          조문을 **볼드** 형식으로 혼합 출력하므로 일괄 제거 후 promote_headers()가
          법령 패턴으로 정확히 재승격하는 것이 더 신뢰성 높음.
        - PPTX/OOXML Excel: 보존. 슬라이드 및 시트 제목이 의미 있는 구조이므로 보존.
        """
        # 2026.08.27(sooyeon.choi) 추가 - Excel IR은 일반 Markdown 매퍼와 분리
        if file_type in OOXML_SPREADSHEET_EXTENSIONS:
            return self._map_spreadsheet_result(docling_output, file_path, file_type)

        # 2026.08.12(sooyeon.choi) 추가 - Excel 시트 및 표 제목 보존
        PRESERVE_HEADERS_FOR = {"pptx"}

        result: MdMeta = []
        pages = docling_output.get("pages", [])
        total_pages = docling_output.get("num_pages", len(pages))
        preserve_headers = file_type in PRESERVE_HEADERS_FOR

        for page_item in pages:
            page_num = page_item.get("page_no")
            md_text = page_item.get("markdown", "")

            if md_text:
                md_text = normalize_markdown_table_separators(md_text)
                if preserve_headers:
                    # 2026.08.12(sooyeon.choi) 추가 - PPTX/Excel의 구조화된 헤더 보존
                    final_text = rm_unnecessary_char(md_text)
                else:
                    # PDF/이미지: 헤더 제거 → promote_headers가 법령 패턴으로 재승격
                    cleaned_lines = []
                    for line in md_text.splitlines():
                        stripped = line.strip()
                        if stripped.startswith("#"):
                            cleaned_lines.append(stripped.lstrip("#").strip())
                        else:
                            cleaned_lines.append(line)
                    final_text = rm_unnecessary_char("\n".join(cleaned_lines))
            else:
                final_text = ""

            page_metadata = dict(page_item.get("metadata", {}))
            page_metadata.update({
                "page": page_num,
                "page_count": total_pages,
                "file_path": file_path,
                "file_type": file_type,
            })
            result.append({
                "text": final_text,
                "metadata": page_metadata,
            })

        logger.info(
            "[PARSE][step=docling_map] 완료 pages=%s preserve_headers=%s",
            len(result),
            preserve_headers,
        )
        return result

    def _map_spreadsheet_result(
        self,
        parser_output: dict,
        file_path: str,
        file_type: str,
    ) -> MdMeta:
        """StructuredSpreadsheet IR을 손실 없이 시트별 MdMeta envelope로 매핑한다."""
        # 2026.08.27(sooyeon.choi) 추가 - 단계 3 spreadsheet 전용 응답 매퍼
        validate_spreadsheet_ir(parser_output)
        workbook_metadata = dict(parser_output.get("metadata", {}))
        pages = parser_output.get("pages", [])
        mapped: MdMeta = []
        for page in pages:
            page_metadata = dict(page.get("metadata", {}))
            page_metadata.update({
                "page": page.get("page_no"),
                "page_count": parser_output.get("num_pages", len(pages)),
                "file_path": file_path,
                "file_type": file_type,
                "document_id": workbook_metadata.get("document_id"),
                "schema_name": parser_output.get("schema_name"),
                "schema_version": parser_output.get("schema_version"),
                "sheet_id": page.get("sheet_id"),
                "sheet_index": page.get("sheet_index"),
                "sheet_name": page.get("sheet_name"),
                "blocks": page.get("blocks", []),
                "styles": parser_output.get("styles", {}),
                "resources": parser_output.get("resources", []),
                "workbook_warnings": parser_output.get("warnings", []),
                "excluded_sheets": parser_output.get("excluded_sheets", []),
                "display_markdown": page.get("markdown", ""),
                "parser_embedding_text": page.get("embedding_text", ""),
                "workbook_metadata": workbook_metadata,
                "processing_engine": workbook_metadata.get("processing_engine", "ir"),
                "processing_path": workbook_metadata.get("processing_path", "structured_ir"),
            })
            mapped.append({
                "text": page.get("embedding_text", ""),
                "metadata": page_metadata,
            })
        logger.info(
            "[PARSE][step=spreadsheet_map] pages=%s document_id=%s schema=%s@%s",
            len(mapped),
            workbook_metadata.get("document_id"),
            parser_output.get("schema_name"),
            parser_output.get("schema_version"),
        )
        return mapped


class _SyncResponse(Exception):
    """Docling API 동기 응답 처리용 내부 예외"""
    def __init__(self, results):
        self.results = results

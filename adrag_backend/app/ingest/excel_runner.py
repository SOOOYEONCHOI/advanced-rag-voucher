"""엑셀 전용 처리기(excel_ingest) 실행 + 확인용 md 출력 (2026.10.16 Phase 1, F-3-01·F-3-02 / R2-1~3).

- excel_ingest 모듈(추출 규칙)은 수정하지 않고 그대로 호출한다(절대 규칙 5).
- .xls는 LibreOffice(soffice)로 .xlsx 변환 후 처리한다. 설치돼 있지 않으면 명확한 오류로 실패한다.
- 확인용 md: ``{md_save_dir}/excel/{doc_key}/{job_id}/`` (00_summary.md, sheets/, chunks.md, ir.json, images/)
  + ``{md_save_dir}/excel/{doc_key}/LATEST``. md_save_dir가 비어 있으면 출력하지 않는다.
  excel_ingest.export_markdown은 ``{instance_dir}/parsed_results/{doc_key}/``에 쓰므로, 작업별 임시 폴더에
  출력한 뒤 위 경로로 옮긴다(같은 파일 동시 업로드에도 충돌 없음). md 출력 실패는 경고만 남긴다.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from excel_ingest import export_md as _export_md_module
from excel_ingest.export_md import export_markdown, safe_name
from excel_ingest.parser import ParseResult, parse_workbook

from app.ingest.file_router import LEGACY_XLS_EXTENSION, file_extension

logger = logging.getLogger(__name__)

EXCEL_MD_SUBDIR = "excel"
# 2026.10.16 추가 - 같은 문서 동시 적재 시 LATEST 갱신·보관 개수 정리가 서로의 폴더를 지우며 경합하지 않게 한다
_EXPORT_FINALIZE_LOCK = threading.Lock()


class ExcelIngestError(RuntimeError):
    """엑셀 처리 실패(변환·파싱). 작업 실패 사유로 그대로 보여 준다."""


@dataclass
class ExcelIngestOutput:
    result: ParseResult
    doc_key: str
    md_dir: Optional[str]

    def summary(self) -> dict[str, Any]:
        doc = self.result.ir.get("doc", {})
        sections = self.result.ir.get("sections", [])
        # 집계 기준은 excel_ingest 00_summary.md와 같다(이미지 배치 / 고유 이미지, 인쇄영역 밖)
        return {
            "doc_key": self.doc_key,
            "sheet_count": doc.get("sheet_count", len(sections)),
            "chunk_count": len(self.result.chunks),
            "image_placement_count": sum(len(s.get("placements") or []) for s in sections),
            "unique_image_count": len(self.result.ir.get("assets") or self.result.assets),
            "out_of_print_area_count": sum(len(s.get("out_of_print_area") or []) for s in sections),
            "needs_review_count": sum(
                1 for s in sections for p in (s.get("placements") or []) if p.get("review_status") == "needs_review"
            ),
            "warning_count": len(self.result.warnings),
            "sheet_types": {s.get("name"): s.get("section_type") for s in sections},
            # 2026.10.16 추가 - Phase 2(R2-3): 관리대장에서 매칭한 시트별 제정일·개정 차수(관리대장이 없으면 빈 값).
            #   TODO(결정필요: 문서 단위 개정 차수 tb_document_versions.revision_label — 시트마다 차수가 달라 기준 미정)
            "sheet_revisions": {
                s.get("name"): {k: s["revision"].get(k) for k in ("process_name", "established", "revision_no", "revision_date", "match")}
                for s in sections if s.get("revision")
            },
            "md_dir": self.md_dir,
        }


def doc_key_for(filename: str) -> str:
    """표시·md 폴더용 문서 키(파일명 기준). 개정 판단에는 쓰지 않는다(D-01)."""
    return safe_name(Path(filename).stem) or "document"


def find_soffice() -> Optional[str]:
    for name in ("soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            return found
    for candidate in (
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        "/usr/bin/soffice",
        "/usr/lib/libreoffice/program/soffice",
    ):
        if os.path.isfile(candidate):
            return candidate
    return None


def convert_xls_to_xlsx(path: str, out_dir: str, timeout: int = 120) -> str:
    soffice = find_soffice()
    if not soffice:
        raise ExcelIngestError(
            ".xls 파일을 처리하려면 서버에 LibreOffice가 필요합니다. "
            "관리자에게 설치를 요청하거나 .xlsx로 저장해 다시 올려 주세요."
        )
    try:
        subprocess.run(
            [soffice, "--headless", "--convert-to", "xlsx", "--outdir", out_dir, path],
            check=True, capture_output=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise ExcelIngestError(f".xls 변환 시간이 {timeout}초를 넘었습니다.") from exc
    except subprocess.CalledProcessError as exc:
        raise ExcelIngestError(".xls 파일을 변환하지 못했습니다(손상되었거나 암호가 걸린 파일일 수 있습니다).") from exc
    converted = Path(out_dir) / (Path(path).stem + ".xlsx")
    if not converted.is_file():
        raise ExcelIngestError(".xls 변환 결과 파일을 찾을 수 없습니다.")
    return str(converted)


def run_excel_ingest(
    path: str,
    filename: str,
    job_id: str,
    md_save_dir: str,
    *,
    keep_last: int = 5,
    convert_timeout: int = 120,
    model: Optional[str] = None,
) -> ExcelIngestOutput:
    doc_key = doc_key_for(filename)
    with tempfile.TemporaryDirectory(prefix="excel_ingest_") as work_dir:
        source = path
        if file_extension(filename) == LEGACY_XLS_EXTENSION:
            source = convert_xls_to_xlsx(path, work_dir, timeout=convert_timeout)
        try:
            # 2026.10.16 수정 - Phase 2(P2-11): 제품 모델(비면 청크 머리말에 넣지 않음)
            result = parse_workbook(source, doc_key=doc_key, model=model or None)
        except ExcelIngestError:
            raise
        except Exception as exc:
            logger.error("[EXCEL][step=parse] 실패 filename=%s: %s", filename, exc, exc_info=True)
            raise ExcelIngestError(f"엑셀 파일을 읽지 못했습니다: {exc}") from exc

    md_dir = None
    if md_save_dir:
        try:
            md_dir = _export(result, doc_key, job_id, filename, md_save_dir, keep_last)
        except Exception as exc:  # 확인용 출력 실패는 적재를 막지 않는다
            logger.warning("[EXCEL][step=md_export] 실패(무시) filename=%s job_id=%s: %s", filename, job_id, exc)
    output = ExcelIngestOutput(result=result, doc_key=doc_key, md_dir=md_dir)
    logger.info("[EXCEL][step=parse] 완료 filename=%s summary=%s", filename, output.summary())
    return output


def _export(result: ParseResult, doc_key: str, job_id: str, filename: str, md_save_dir: str, keep_last: int) -> str:
    base = Path(md_save_dir) / EXCEL_MD_SUBDIR / safe_name(doc_key)
    base.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".staging-{safe_name(job_id)}-", dir=base.parent))
    try:
        produced = Path(export_markdown(result, instance_dir=str(staging), run_id=job_id,
                                        source_name=filename, keep_last=keep_last))
        final = base / job_id
        if final.exists():
            shutil.rmtree(final)
        os.replace(produced, final)
        # 2026.10.16 수정 - md 폴더가 자리 잡은 뒤의 LATEST·보관 정리는 잠금 안에서, 실패해도 md_dir은 돌려준다
        with _EXPORT_FINALIZE_LOCK:
            try:
                latest_tmp = base / f".LATEST-{safe_name(job_id)}.tmp"
                latest_tmp.write_text(job_id, encoding="utf-8")
                os.replace(latest_tmp, base / "LATEST")
                _export_md_module._cleanup(str(base), keep_last)
            except OSError as exc:
                logger.warning("[EXCEL][step=md_export] LATEST·보관 정리 실패(무시) job_id=%s: %s", job_id, exc)
        return str(final)
    finally:
        shutil.rmtree(staging, ignore_errors=True)

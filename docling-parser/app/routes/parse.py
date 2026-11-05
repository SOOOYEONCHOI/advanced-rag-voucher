import asyncio
import os
import shutil
import uuid
from pathlib import Path
from typing import Optional, Dict, Any
from enum import Enum

from fastapi import APIRouter, HTTPException, Header, UploadFile, File, Form, BackgroundTasks
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel

from app.services.job_manager import JobManager
from app.services.parser import DocumentParser
from app.spreadsheets.parser import OpenpyxlExcelParser
from app.resources.uploader import BackendResourceUploader, resolve_backend_url
from app.resources.store import resource_store
from app.utils.auth import verify_api_key

router = APIRouter(prefix="/api")

job_manager = JobManager()
document_parser = DocumentParser()
DEFAULT_RESOURCE_DELIVERY = os.environ.get("RESOURCE_DELIVERY", "pull").strip().lower()

ALLOWED_EXTENSIONS = {
    ".pdf", ".docx", ".dotx", ".docm", ".dotm",
    ".pptx", ".pptm", ".potx", ".potm",
    *OpenpyxlExcelParser.SUPPORTED_EXTENSIONS,
    ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp",
}

# 2026.08.27(sooyeon.choi) 추가 - 레거시 Excel 변환 안내 계약
LEGACY_XLS_UPLOAD_MESSAGE = (
    "Legacy .xls files are not supported. Save the file as .xlsx in Excel and upload it again."
)


class JobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ParseResponse(BaseModel):
    job_id: str
    status: str
    message: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    created_at: str
    completed_at: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


@router.get("/capabilities")
async def get_capabilities():
    """Parser와 backend의 배포 간 확장자 계약 확인용 endpoint."""
    # 2026.08.27(sooyeon.choi) 추가 - Excel 확장자 정본 공개
    return {
        "spreadsheet_extensions": sorted(OpenpyxlExcelParser.SUPPORTED_EXTENSIONS),
        "spreadsheet_schema_name": "StructuredSpreadsheet",
        "spreadsheet_schema_version": "1.0",
    }


@router.post("/parse", response_model=ParseResponse)
async def parse_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    x_api_key: str = Header(..., alias="X-API-KEY"),
    output_format: str = "md",
    document_id: Optional[str] = Form(None),
    # 2026.08.28(sooyeon.choi) 추가 - 요청한 백엔드로 resource를 회신하기 위한 콜백 URL
    callback_url: Optional[str] = Form(None),
    # 2026.08.28(sooyeon.choi) 추가 - resource 전달 방식.
    #   push: 파서가 백엔드로 업로드 (백엔드가 파서에서 접근 가능해야 함)
    #   pull: 파서가 보관하고 백엔드가 가져감 (백엔드가 사설망/루프백일 때)
    resource_delivery: str = Form(DEFAULT_RESOURCE_DELIVERY),
):
    """
    문서 파싱 요청 (비동기)

    - file: 업로드할 문서 파일
    - X-API-KEY: API 인증 키
    - output_format: 출력 형식 ("md" or "json")
    """
    if not verify_api_key(x_api_key):
        raise HTTPException(status_code=401, detail="Invalid API Key")

    file_ext = Path(file.filename).suffix.lower()
    if file_ext == ".xls":
        raise HTTPException(status_code=400, detail=LEGACY_XLS_UPLOAD_MESSAGE)
    if file_ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {file_ext}. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    if resource_delivery not in ("push", "pull"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid resource_delivery: {resource_delivery}. Use 'push' or 'pull'.",
        )

    # 2026.08.28(sooyeon.choi) 추가 - 허용되지 않은 콜백 URL은 요청 시점에 거절
    #   pull 모드에서는 파서가 백엔드로 나가지 않으므로 콜백 URL을 요구하지 않는다.
    try:
        resolved_callback_url = "" if resource_delivery == "pull" else resolve_backend_url(callback_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    job_id = str(uuid.uuid4())

    # 2026.06.17(sooyeon.choi) 수정 - docker-compose 볼륨 마운트 경로(./data/uploads:/app/data/uploads)에 맞게 경로 수정
    upload_dir = Path("/app/data/uploads")
    upload_dir.mkdir(parents=True, exist_ok=True)

    file_path = (upload_dir / f"{job_id}_{file.filename}").resolve()
    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)

    job_manager.create_job(
        job_id=job_id,
        file_path=str(file_path),
        output_format=output_format,
        document_id=document_id,
    )

    background_tasks.add_task(
        _process_document,
        job_id=job_id,
        file_path=str(file_path),
        output_format=output_format,
        document_id=document_id,
        callback_url=resolved_callback_url,
        resource_delivery=resource_delivery,
    )

    return ParseResponse(
        job_id=job_id,
        status=JobStatus.PENDING.value,
        message="Parsing job created successfully",
    )


async def _process_document(
    job_id: str,
    file_path: str,
    output_format: str,
    document_id: Optional[str] = None,
    callback_url: Optional[str] = None,
    resource_delivery: str = "push",
):
    """문서 파싱 백그라운드 처리"""
    try:
        job_manager.update_job_status(job_id, JobStatus.PROCESSING.value)

        result = await document_parser.parse(
            file_path=file_path,
            output_format=output_format,
            document_id=document_id,
        )

        # 2026.08.27(sooyeon.choi) 추가 - parser 로컬 resource를 backend staging으로 전송
        # 2026.08.28(sooyeon.choi) 수정 - pull 모드에서는 보관만 하고 백엔드가 가져간다
        if resource_delivery == "pull":
            retained = await asyncio.to_thread(
                resource_store.retain, result, parse_job_id=job_id
            )
            _log_info(f"Job {job_id}: retained {len(retained)} resources for pull")
        else:
            await asyncio.to_thread(
                BackendResourceUploader(callback_url).upload_result_resources,
                result,
                parse_job_id=job_id,
                document_id=document_id,
            )

        job_manager.complete_job(job_id, result)

    except Exception as e:
        # 2026.06.17(sooyeon.choi) 수정 - 백그라운드 작업 실패 원인을 로그에 기록
        import traceback
        from app.utils.log.log import LoggingLogger
        _logger = LoggingLogger().getLogger()
        _logger.info(f"ERROR: Job {job_id} failed - {str(e)}\n{traceback.format_exc()}")
        job_manager.fail_job(job_id, str(e))

    finally:
        if os.path.exists(file_path):
            os.remove(file_path)
        # 2026.08.27(sooyeon.choi) 추가 - 완료/실패와 무관하게 parser 로컬 resource 정리
        # 2026.08.28(sooyeon.choi) 수정 - pull 모드의 보관본(jobs/{job_id})은 여기서 지우지 않는다.
        #   백엔드가 DELETE로 수령을 확인하거나 TTL이 지나야 삭제된다.
        _cleanup_local_resources(document_id)
        resource_store.purge_expired(_pull_ttl_seconds())
        if resource_delivery == "pull" and job_manager.get_job(job_id) is None:
            resource_store.discard(job_id)


def _log_info(message: str) -> None:
    from app.utils.log.log import LoggingLogger
    LoggingLogger().getLogger().info(message)


def _pull_ttl_seconds() -> float:
    # 백엔드가 가져가지 못한 보관본이 무한정 쌓이지 않도록 한다.
    return float(os.environ.get("PARSER_RESOURCE_TTL_HOURS", "24")) * 3600


def _cleanup_local_resources(document_id: Optional[str]) -> None:
    """backend로 전송이 끝난 resource 원본은 parser 서버에 남기지 않는다."""
    if not document_id:
        return
    root = Path(os.environ.get("PARSER_RESOURCE_ROOT", "/app/data/resources")).resolve()
    for candidate in (root / document_id, root / ".tmp" / document_id):
        try:
            resolved = candidate.resolve()
            resolved.relative_to(root)
        except (ValueError, OSError):
            continue
        shutil.rmtree(resolved, ignore_errors=True)


@router.get("/job/{job_id}", response_model=JobStatusResponse)
async def get_job_status(
    job_id: str,
    x_api_key: str = Header(..., alias="X-API-KEY"),
):
    """Job 상태 조회"""
    if not verify_api_key(x_api_key):
        raise HTTPException(status_code=401, detail="Invalid API Key")

    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # 결과 본문은 /result 엔드포인트에서 별도 수신 (대용량 직렬화 오버헤드 방지)
    job_response = job.copy()
    job_response["result"] = None

    return JobStatusResponse(**job_response)


@router.get("/job/{job_id}/result")
async def get_job_result(
    job_id: str,
    x_api_key: str = Header(..., alias="X-API-KEY"),
):
    """파싱 결과 수신 (수신 후 메모리에서 Job 제거)"""
    if not verify_api_key(x_api_key):
        raise HTTPException(status_code=401, detail="Invalid API Key")

    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job["status"] != JobStatus.COMPLETED.value:
        raise HTTPException(
            status_code=400,
            detail=f"Job is not completed. Current status: {job['status']}",
        )

    result = job.get("result")
    if not result:
        raise HTTPException(status_code=404, detail="Result not found")

    job_manager.delete_job(job_id)

    return JSONResponse(content=result)


# 2026.08.28(sooyeon.choi) 추가 - pull 방식 resource 전달 엔드포인트.
#   백엔드가 사설망/루프백에 있어 파서가 접속할 수 없을 때, 이미 열려 있는
#   백엔드 → 파서 방향 연결만으로 resource를 회수한다.
@router.get("/job/{job_id}/resources")
async def list_job_resources(
    job_id: str,
    x_api_key: str = Header(..., alias="X-API-KEY"),
):
    """pull 모드로 보관 중인 resource metadata 목록"""
    if not verify_api_key(x_api_key):
        raise HTTPException(status_code=401, detail="Invalid API Key")

    entries = resource_store.list(job_id)
    if entries is None:
        raise HTTPException(status_code=404, detail="No retained resources for this job")
    return {"job_id": job_id, "resources": entries}


@router.get("/job/{job_id}/resources/{resource_id}")
async def download_job_resource(
    job_id: str,
    resource_id: str,
    x_api_key: str = Header(..., alias="X-API-KEY"),
):
    """resource 원본 바이트 스트림"""
    if not verify_api_key(x_api_key):
        raise HTTPException(status_code=401, detail="Invalid API Key")

    path = resource_store.path_of(job_id, resource_id)
    if path is None:
        raise HTTPException(status_code=404, detail="Resource not found")

    entries = resource_store.list(job_id) or []
    mime_type = next(
        (e.get("mime_type") for e in entries if e["resource_id"] == resource_id),
        None,
    ) or "application/octet-stream"
    return FileResponse(path, media_type=mime_type, filename=path.name)


@router.delete("/job/{job_id}/resources")
async def discard_job_resources(
    job_id: str,
    x_api_key: str = Header(..., alias="X-API-KEY"),
):
    """백엔드가 수령을 마친 보관본을 삭제한다."""
    if not verify_api_key(x_api_key):
        raise HTTPException(status_code=401, detail="Invalid API Key")

    resource_store.discard(job_id)
    return {"job_id": job_id, "status": "discarded"}

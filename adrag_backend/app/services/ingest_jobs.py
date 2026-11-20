"""Single-process asynchronous job queue for document ingestion."""

import asyncio
import os
from typing import Optional

from app.repositories.ingest_job_repository import IngestJobRepository
from app.services.ingest_service import IngestService
from app.parsers.document_types import DocumentTypeMismatchError
from app.ingest.drawing.common import DrawingError  # 2026.11.12(sooyeon.choi) 도면 파싱 기능 추가
from app.utils.log.log import LoggingLogger

logger = LoggingLogger().getLogger(__name__)


class IngestJobManager:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._repository = IngestJobRepository()
        self._worker: Optional[asyncio.Task] = None

    async def start(self) -> None:
        if self._worker and not self._worker.done():
            return
        # 2026.11.06(sooyeon.choi) 수정 - 끝났거나 없는 작업을 가리키는 문서 점유 표식 해제(설계 v1.1 6.4)
        try:
            await asyncio.to_thread(_record_repo().reconcile_pending)
        except Exception:
            logger.exception("pending_job_id 정합성 복구 실패")
        for job_id in await asyncio.to_thread(self._repository.requeue_interrupted):
            await self._queue.put(job_id)
        self._worker = asyncio.create_task(self._run(), name="ingest-worker")

    async def stop(self) -> None:
        if self._worker:
            self._worker.cancel()
            try:
                await self._worker
            except asyncio.CancelledError:
                pass
            self._worker = None

    async def enqueue(self, job_id: str) -> None:
        await self._queue.put(job_id)

    async def retry(self, job_id: str) -> None:
        job = await asyncio.to_thread(self._repository.get, job_id)
        # 2026.11.06(sooyeon.choi) 수정 - 복원 작업은 같은 작업으로 재시도하지 않는다(최신 이력 확인 후 새 요청)
        if job and job.get("operation_type") == "restore":
            raise RestoreRetryNotAllowed("RESTORE_RETRY_REQUIRES_NEW_REQUEST")
        if not job or job["status"] != "failed":
            raise ValueError("재시도 가능한 실패 작업이 아닙니다.")
        # 2026.10.19 추가 - 최신본 변경 작업 재시도: 같은 버전을 다시 처리 중(building)으로 되돌린다.
        #   그 사이 같은 문서에 다른 최신본 변경이 접수됐으면 재시도하지 않는다(문서별 처리 중 1개, D-01).
        request = job.get("request") or {}
        if request.get("target_document_id"):
            # 2026.11.06(sooyeon.choi) 수정 - 재시도 시 문서 점유 표식도 다시 잡는다
            await asyncio.to_thread(_reopen_version, request["target_document_id"], int(request["version_no"]), job_id)
        await asyncio.to_thread(
            self._repository.update, job_id, status="queued", step=job["current_step"]
        )
        await self._queue.put(job_id)

    async def _run(self) -> None:
        while True:
            job_id = await self._queue.get()
            try:
                await self._execute(job_id)
            finally:
                self._queue.task_done()

    async def _execute(self, job_id: str) -> None:
        job = await asyncio.to_thread(self._repository.get, job_id)
        if not job:
            return
        # 2026.11.06(sooyeon.choi) 수정 - 복원 작업은 파일 경로·체크포인트를 쓰지 않으므로 맨 앞에서 분기
        if job.get("operation_type") == "restore":
            from app.services.document_version_restore import run_restore_job

            await run_restore_job(job_id)
            return
        request = job["request"]
        # Jobs persisted before document-type selection was introduced may not
        # carry the field; keep their behavior identical to the auto flow.
        request.setdefault("document_type", "auto")
        # 2026.11.12(sooyeon.choi) 도면 파싱 기능 추가 - 도면 단계에서 실패한 작업도 그 단계부터 다시 한다
        resume_from = job["current_step"] if job["current_step"] in {
            "parse", "chunk", "embed", "index",
            "drawing_convert", "drawing_extract", "drawing_render", "drawing_store",
        } else None
        checkpoint_path = request["file_path"] + ".checkpoint"
        await asyncio.to_thread(self._repository.update, job_id, status="running", step="validate")

        async def progress(step: str) -> None:
            await asyncio.to_thread(self._repository.update, job_id, status="running", step=step)

        try:
            result = await IngestService().ingest(
                **{**request, "job_id": job_id},  # 2026.10.16 수정 - Phase 1 확인용 md 폴더 이름
                progress_callback=progress,
                checkpoint_path=checkpoint_path,
                resume_from=resume_from,
            )
            await asyncio.to_thread(
                self._repository.update, job_id, status="completed", step="completed", result=result
            )
            try:
                os.unlink(request["file_path"])
            except FileNotFoundError:
                pass
        except Exception as exc:
            current = await asyncio.to_thread(self._repository.get, job_id)
            step = current["current_step"] if current else "unknown"
            logger.error("ingest job failed job_id=%s step=%s: %s", job_id, step, exc, exc_info=True)
            # 2026.10.19 추가 - 최신본 변경 실패: 파이프라인 밖에서 실패해도 버전을 failed로(기존 최신본 유지)
            if request.get("target_document_id"):
                try:
                    await asyncio.to_thread(
                        _record_repo().set_version_status,
                        request["target_document_id"], int(request["version_no"]), "failed",
                        from_statuses=("building", "ready"),
                    )
                except Exception:
                    logger.exception("version failed 표시 실패 job_id=%s", job_id)
                # 2026.11.06(sooyeon.choi) 수정 - 최신본 변경 실패: 이 작업의 문서 점유 표식 해제
                try:
                    await asyncio.to_thread(_record_repo().release_pending, request["target_document_id"], job_id)
                except Exception:
                    logger.exception("pending_job_id 해제 실패 job_id=%s", job_id)
            await asyncio.to_thread(
                self._repository.update,
                job_id,
                status="failed",
                step=step,
                error=str(exc),
                # 2026.11.12(sooyeon.choi) 도면 파싱 기능 추가 - 도면 처리 오류 코드(E_…)도 남긴다
                error_code=(exc.error_code if isinstance(exc, (DocumentTypeMismatchError, DrawingError)) else None),
            )


def _record_repo():
    from app.repositories.ingest_record_repository import IngestRecordRepository

    return IngestRecordRepository()


# 2026.10.19 추가 - 실패한 최신본 변경 버전을 재시도용으로 다시 연다(문서별 처리 중 1개 보장)
def _reopen_version(document_id: str, version_no: int, job_id: str | None = None) -> None:
    repo = _record_repo()
    with repo.db.get_connection():
        repo.lock_document(document_id)
        current = repo.in_progress_version(document_id)
        if current and current["version_no"] != version_no:
            raise ValueError(f"이 문서는 v{current['version_no']} 새 버전 등록을 처리 중입니다.")
        # 2026.11.06(sooyeon.choi) 수정 - 다른 작업(복원 등)이 문서를 점유 중이면 재시도하지 않는다
        if job_id and not repo.acquire_pending(document_id, job_id):
            raise ValueError("이 문서는 다른 작업을 처리 중입니다. 완료 후 다시 시도하세요.")
        if not current and not repo.set_version_status(
            document_id, version_no, "building", vectors_purged=False, from_statuses=("failed",)
        ):
            raise ValueError("재시도할 수 있는 새 버전 등록 작업이 아닙니다.")


# 2026.11.06(sooyeon.choi) 수정 - 복원 작업 재시도 거부(라우트가 409 RESTORE_RETRY_REQUIRES_NEW_REQUEST로 응답)
class RestoreRetryNotAllowed(ValueError):
    pass


_manager: Optional[IngestJobManager] = None


def get_ingest_job_manager() -> IngestJobManager:
    global _manager
    if _manager is None:
        _manager = IngestJobManager()
    return _manager

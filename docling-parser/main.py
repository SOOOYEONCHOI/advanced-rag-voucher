"""
GPU Docling FastAPI Server
Docling 파싱 전용 서비스 - GPU 서버에서 실행
"""
import os
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
import uvicorn

from app.routes.parse import router as parse_router, job_manager
from app.core.config import (
    PARSER_RESOURCE_CLEANUP_INTERVAL_SECONDS,
    PARSER_RESOURCE_TTL_HOURS,
)
from app.resources.store import resource_store
from app.utils.log.log import LoggingLogger

# parser의 기존 LoggingLogger.getLogger() 계약과 호환한다.
logger = LoggingLogger().getLogger()


async def _resource_cleanup_loop() -> None:
    while True:
        try:
            await asyncio.sleep(PARSER_RESOURCE_CLEANUP_INTERVAL_SECONDS)
            removed = await asyncio.to_thread(
                resource_store.purge_expired, PARSER_RESOURCE_TTL_HOURS * 3600
            )
            logger.info(
                "event=parser_resource_cleanup status=completed removed_jobs=%s",
                len(removed),
            )
        except asyncio.CancelledError:
            logger.info("event=parser_resource_cleanup status=stopped")
            raise
        except Exception:
            logger.exception("event=parser_resource_cleanup status=failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    restored = await asyncio.to_thread(resource_store.restore)
    removed = await asyncio.to_thread(
        resource_store.purge_expired, PARSER_RESOURCE_TTL_HOURS * 3600
    )
    logger.info(
        "event=parser_resource_cleanup status=started restored_jobs=%s removed_jobs=%s "
        "interval_seconds=%s",
        restored,
        len(removed),
        PARSER_RESOURCE_CLEANUP_INTERVAL_SECONDS,
    )
    cleanup_task = asyncio.create_task(_resource_cleanup_loop())
    try:
        yield
    finally:
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass

app = FastAPI(
    title="GPU Docling Parsing Server",
    description="Docling 파싱 전용 GPU 서버",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(parse_router)


@app.get("/")
async def root():
    return {
        "service": "GPU Docling Parsing Server",
        "status": "running",
        "version": "1.0.0",
    }


@app.get("/lab")
async def jupyter_redirect():
    host = os.getenv("JUPYTER_HOST", "localhost")
    return RedirectResponse(url=f"http://{host}:8888/")


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "active_jobs": job_manager.get_active_job_count(),
    }


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8008))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
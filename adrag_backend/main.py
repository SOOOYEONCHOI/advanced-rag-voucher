import asyncio
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
# 2026.07.16(sooyeon.choi) 추가 - 공유 httpx.AsyncClient 종료 훅 (B6)
from app.core.http import close_shared_async_client
from app.routes.chat import router as chat_router
# 2026.04.01(sooyeon.choi) 수정 - 멀티컬렉션 관리 기능 추가
from app.routes.collections import router as collections_router
from app.routes.ingest import router as ingest_router
from app.routes.parse import router as parse_router
from app.routes.query import router as query_router
from app.routes.voice import router as voice_router
# 2026.10.20(sooyeon.choi) 삭제 - admin_auth(POST /api/admin/init, 인증 없는 최초 관리자 생성) 제거, 관리자는 app/services/admin_bootstrap.py로 생성
from app.routes.auth import router as auth_router
from app.routes.user_permissions import router as user_permissions_router
from app.routes.models import router as models_router
from app.routes.user_settings import router as user_settings_router
# 2026.09.17(woojin.jung) 추가 - 사용자 UI 연동 방식 설정 라우터 추가
from app.routes.ui_settings import router as ui_settings_router
# 2026.06.16(sooyeon.choi) 추가 - SCR-006 통계 대시보드 라우터
from app.routes.admin_stats import router as admin_stats_router
from app.routes.user_stats import router as user_stats_router
# 2026.06.29(sooyeon.choi) 추가 - 사용자 권한 관리: 부서/사용자 관리 라우터
from app.routes.admin_departments import router as admin_departments_router
from app.routes.admin_users import router as admin_users_router
from app.routes.admin_settings import router as admin_settings_router
# 2026.07.22(sychoi) 추가 - RAG 평가 자동화 API (evaluation 패키지)
from app.routes.evaluation import router as eval_router
from app.routes.spreadsheet_resources import router as spreadsheet_resources_router
from app.repositories.metadata_repository import MetadataRepository
# 2026.04.21(sooyeon.choi) 수정 - Kiwi 워밍업만 유지 (Reranker는 vLLM HTTP 전환으로 불필요)
from app.utils.kiwi_tokenizer import get_kiwi
from app.services.ingest_jobs import get_ingest_job_manager
from app.repositories.database import close_database_manager, ensure_schema_ready
from app.repositories.spreadsheet_resource_repository import SpreadsheetResourceRepository
from app.services.spreadsheet_resource_service import SpreadsheetResourceService
from pathlib import Path

from app.utils.log.log import LoggingLogger

# 로거 초기화
# 2026.07.16(sooyeon.choi) 수정 - 모듈별 named logger 적용 (B16)
logger = LoggingLogger().getLogger(__name__)

settings = get_settings()

# 2026.04.10(sooyeon.choi) 추가 - 만료된 세션 컨텍스트 주기적 정리 (24시간 간격)
_SESSION_CLEANUP_INTERVAL_SECONDS = 60 * 60 * 24


def _cleanup_spreadsheet_resources() -> None:
    """만료 staging 정리와 resource 저장소 사용량 기록."""
    started = time.perf_counter()
    # 2026.08.27(sooyeon.choi) 추가 - 운영 cleanup/metric
    root = Path(settings.resource_storage_root)
    if not root.is_absolute():
        root = Path(__file__).resolve().parent / root
    service = SpreadsheetResourceService(
        root,
        SpreadsheetResourceRepository(db_path=settings.sqlite_db_path),
        settings.resource_max_upload_bytes,
    )
    # 2026.08.27(sooyeon.choi) 수정 - 실행 중 job 제외와 삭제 실패 재시도를 함께 수행
    removed = service.cleanup_expired_staging(
        settings.resource_staging_ttl_hours,
        active_parse_job_ids=SpreadsheetResourceService.active_parse_job_ids(
            settings.resource_staging_ttl_hours
        ),
    )
    deletion = service.retry_pending_deletions()
    usage = service.usage()
    logger.info(
        "event=resource_cleanup status=completed removed_staging=%s retried_deletions=%s "
        "removed_orphan_dirs=%s resource_count=%s disk_bytes=%s elapsed_ms=%s",
        removed,
        deletion["retried_documents"],
        deletion["removed_orphan_dirs"],
        usage["resource_count"],
        usage["disk_bytes"],
        int((time.perf_counter() - started) * 1000),
    )


# 2026.10.19 추가 - 최신본 변경 후 지우지 못한 이전 버전 Qdrant 포인트를 다시 정리한다.
#   정리 전에도 검색 제외 조건(version_visibility)이 가리므로 검색에는 나오지 않는다.
def _purge_inactive_version_points() -> None:
    from app.repositories.ingest_record_repository import IngestRecordRepository
    from app.repositories.vector_repository import VectorRepository

    repo = IngestRecordRepository()
    targets = repo.documents_needing_purge()
    if not targets:
        return
    vector_repo = VectorRepository(
        host=settings.qdrant_host, port=settings.qdrant_port,
        sparse_encoder_type=settings.sparse_encoder_type, kiwi_bm25_vector_name=settings.kiwi_bm25_vector_name,
    )
    purged = 0
    for document_id, active_version, collection in targets:
        if vector_repo.delete_document_version_points(document_id, collection, keep_version_no=active_version):
            purged += repo.mark_inactive_versions_purged(document_id)
    logger.info("event=version_purge status=completed documents=%s versions=%s", len(targets), purged)


async def _session_cleanup_loop() -> None:
    """만료된 세션 컨텍스트를 매 24시간마다 삭제하는 백그라운드 태스크."""
    while True:
        try:
            logger.info("[스케줄러] 만료 세션 정리 시작")
            await asyncio.sleep(_SESSION_CLEANUP_INTERVAL_SECONDS)
            repo = MetadataRepository(settings.sqlite_db_path)
            deleted = repo.delete_expired_query_contexts()
            logger.info(f"[스케줄러] 만료 세션 정리 완료: {deleted}건 삭제")
        except asyncio.CancelledError:
            logger.info("[스케줄러] 만료 세션 정리 태스크 종료")
            break
        except Exception as e:
            logger.error(f"[스케줄러] 만료 세션 정리 중 오류: {e}")


async def _resource_cleanup_loop() -> None:
    """만료된 spreadsheet resource를 설정된 주기로 정리한다."""
    while True:
        try:
            await asyncio.sleep(settings.resource_cleanup_interval_seconds)
            await asyncio.to_thread(_cleanup_spreadsheet_resources)
            await asyncio.to_thread(_purge_inactive_version_points)  # 2026.10.19 추가
        except asyncio.CancelledError:
            logger.info("event=resource_cleanup status=stopped")
            raise
        except Exception:
            logger.exception("event=resource_cleanup status=failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 시작 시 백그라운드 정리 태스크를 시작하고, 종료 시 취소한다."""
    # 2026.10.16 추가 - Phase 1.5: DB 스키마가 Alembic head가 아니면 기동하지 않는다(자동 변경 없음, N-10)
    revision = await asyncio.to_thread(ensure_schema_ready)
    logger.info(f"[DB] PostgreSQL 스키마 확인 완료 (revision={revision})")
    # 2026.04.21(sooyeon.choi) 추가 - Kiwi 워밍업: 첫 요청 시 초기화로 발생하는 ~2100ms 지연 방지
    await asyncio.to_thread(get_kiwi)
    logger.info("[워밍업] Kiwi 형태소 분석기 초기화 완료")
    await asyncio.to_thread(_cleanup_spreadsheet_resources)
    # 2026.04.21(sooyeon.choi) 수정 - vLLM HTTP 방식 전환으로 로컬 모델 워밍업 불필요 (제거)
    cleanup_task = asyncio.create_task(_session_cleanup_loop())
    resource_cleanup_task = asyncio.create_task(_resource_cleanup_loop())
    await get_ingest_job_manager().start()
    logger.info("[스케줄러] 만료 세션 정리 태스크 시작 (24시간 간격)")
    logger.info(
        "event=resource_cleanup_scheduler status=started interval_seconds=%s",
        settings.resource_cleanup_interval_seconds,
    )

    try:
        from app.repositories.evaluation_repository import EvalRepository
        orphaned = EvalRepository().mark_orphan_runs_failed()
        if orphaned:
            logger.info(f"[평가] 중단된 run {orphaned}건을 failed로 정리")
    except Exception as exc:
        logger.warning(f"[평가] 중단된 평가 작업 정리 실패(무시): {exc}")
    try:
        yield # yield를 기준으로 앞은 시작 로직, 뒤는 종료 로직
    finally:
    # 애플리케이션 종료 시 실행
        cleanup_task.cancel()
        resource_cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            logger.info("[스케줄러] 만료 세션 정리 태스크 종료")
            pass
        try:
            await resource_cleanup_task
        except asyncio.CancelledError:
            pass
        # 2026.07.16(sooyeon.choi) 추가 - 공유 httpx.AsyncClient 종료 (B6)
        await close_shared_async_client()
        await get_ingest_job_manager().stop()
        logger.info("[종료] 공유 HTTP 클라이언트 종료 완료")
        # 2026.10.16 추가 - Phase 1.5: DB 커넥션 풀 종료
        close_database_manager()


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description="Production-ready RAG system with multi-format document ingestion and hybrid retrieval",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── API 라우터 등록 ──────────────────────────────────────
app.include_router(chat_router, prefix="/api")
# 2026.04.01(sooyeon.choi) 수정 - 멀티컬렉션 관리 기능 추가
app.include_router(collections_router, prefix="/api")
app.include_router(ingest_router, prefix="/api")
app.include_router(parse_router, prefix="/api")
app.include_router(query_router, prefix="/api")
app.include_router(voice_router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(user_permissions_router, prefix="/api")
app.include_router(models_router, prefix="/api")
app.include_router(user_settings_router, prefix="/api")
# 2026.09.17(woojin.jung) 추가 - 사용자 UI 연동 방식 설정 API 등록
app.include_router(ui_settings_router, prefix="/api")
# 2026.06.16(sooyeon.choi) 추가 - SCR-006 통계 대시보드
app.include_router(admin_stats_router, prefix="/api")
app.include_router(user_stats_router, prefix="/api")
# 2026.06.29(sooyeon.choi) 추가 - 사용자 권한 관리
# admin_departments_router보다 admin_users_router를 먼저 등록하여 /admin/summary 경로 우선순위 확보
app.include_router(admin_departments_router, prefix="/api")
app.include_router(admin_users_router, prefix="/api")
app.include_router(admin_settings_router, prefix="/api")
# 2026.07.22(sychoi) 추가 - RAG 평가 자동화 API
app.include_router(eval_router, prefix="/api")
# 2026.08.27(sooyeon.choi) 추가 - internal upload는 /api prefix 없이 정본 경로 사용
app.include_router(spreadsheet_resources_router)


@app.get("/")
async def root():
    return {"message": "Advanced RAG Framework API", "status": "running"}


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "backend"}


@app.get("/api/health")
async def api_health_check():
    return {"status": "healthy", "database": "connected", "vector_store": "connected"}

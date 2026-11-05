"""정리 작업(MAINT 큐) — 2026.10.12 Phase 3 보완(작업지시서 v2.3, 프로그램 설계서 v0.2 4.10).

별도 스케줄러 없이 tb_ingest_jobs의 MAINT 큐에 다음 실행 시각(next_run_at)으로 예약한다.
작업이 끝나면 워커가 다음 날 같은 시각으로 다시 예약한다(종류별 대기 1건 — uq_ingest_jobs_maint_pending).

| job_type | 시각(KST) | 내용 |
|---|---|---|
| PURGE_POINTS | 02:30 | 보관 기간이 지난 retired 버전의 point·행·원본 삭제 (IngestJobManager.purge_expired_versions) |
| GC_FILES | 03:00 | 만료 staging·삭제 재시도·참조 없는 asset(ASSET_GC_GRACE_DAYS) 정리 + 저장소 사용량 기록 |

RECONCILE_INDEX(02:00, PostgreSQL↔Qdrant 대조)는 job_type만 정의돼 있고 구현은 이후 작업이다.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from datetime import time as dtime
from pathlib import Path

from app.core.config import get_settings
from app.repositories.spreadsheet_resource_repository import SpreadsheetResourceRepository
from app.services.spreadsheet_resource_service import SpreadsheetResourceService
from app.utils.log.log import LoggingLogger

logger = LoggingLogger().getLogger(__name__)

KST = timezone(timedelta(hours=9))
MAINT_SCHEDULE = {
    "PURGE_POINTS": dtime(2, 30),
    "GC_FILES": dtime(3, 0),
}
_BACKEND_ROOT = Path(__file__).resolve().parents[2]


def next_run_at(job_type: str, now: datetime | None = None) -> datetime:
    """``job_type``의 다음 실행 시각(KST 기준 오늘 그 시각, 이미 지났으면 내일)."""
    now = (now or datetime.now(KST)).astimezone(KST)
    at = datetime.combine(now.date(), MAINT_SCHEDULE[job_type], tzinfo=KST)
    return at if at > now else at + timedelta(days=1)


def cleanup_files() -> dict:
    """만료 staging 정리, 문서 삭제 재시도, 참조 없는 공유 asset 정리, 저장소 사용량 기록 (GC_FILES).

    2026.10.12 이동 - main.py ``_cleanup_spreadsheet_resources``(API 프로세스 주기 실행) → MAINT 큐 작업.
    """
    settings = get_settings()
    started = time.perf_counter()
    root = Path(settings.resource_storage_root)
    if not root.is_absolute():
        root = _BACKEND_ROOT / root
    service = SpreadsheetResourceService(root, SpreadsheetResourceRepository(), settings.resource_max_upload_bytes)
    # 실행 중 job 제외와 삭제 실패 재시도를 함께 수행
    removed = service.cleanup_expired_staging(
        settings.resource_staging_ttl_hours,
        active_parse_job_ids=SpreadsheetResourceService.active_parse_job_ids(settings.resource_staging_ttl_hours),
    )
    deletion = service.retry_pending_deletions()
    # 참조가 없어진 공유 asset 정리 — 유예 기간은 설계 A-4.6(7일)
    removed_assets = service.cleanup_unreferenced_assets(settings.asset_gc_grace_days * 24)
    usage = service.usage()
    result = {
        "removed_staging": removed,
        "retried_deletions": deletion["retried_documents"],
        "removed_orphan_dirs": deletion["removed_orphan_dirs"],
        "removed_assets": removed_assets,
        "resource_count": usage["resource_count"],
        "disk_bytes": usage["disk_bytes"],
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
    }
    logger.info(
        "event=resource_cleanup status=completed removed_staging=%s retried_deletions=%s "
        "removed_orphan_dirs=%s removed_assets=%s resource_count=%s disk_bytes=%s elapsed_ms=%s",
        *result.values(),
    )
    return result

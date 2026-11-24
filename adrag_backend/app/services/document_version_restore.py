"""문서 이전 버전 복원 (2026.11.06(sooyeon.choi) 수정 - 신규, UI-12 / R1-5 / SC-06 / VR-01~06 / D-22).

설계: docs/design/문서_이전버전_복원_백엔드_최종설계_v1.1.md 6·8절, API 명세 v1.1
- 복원은 보존된 과거 버전을 다시 적용하는 RDB 전환이다. 파싱·임베딩·포인트 쓰기를 하지 않는다.
- 접수(submit_restore): 문서 잠금 아래 멱등 키·상태 검사 → queued 작업 + 점유 표식(pending_job_id)을 한 트랜잭션으로 저장.
- 실행(run_restore_job): validate(권한·상태·사전 판정 재검사) → snapshot(원본·청크·사진·Qdrant 포인트 실물 확인)
  → activate(짧은 트랜잭션에서 최종 재검사 후 전환·적용 이력·점유 해제·작업 완료).
- 커밋 전 실패는 기존 적용 버전 유지 + 작업 failed + 점유 해제. 커밋 후 실패를 실패로 바꾸거나 되돌리지 않는다.
- 가능 여부는 서버만 판단한다. 이력 GET은 저장된 검증 기록으로만 판정(Qdrant 전체 읽기 없음), 실행 시 실물을 다시 확인한다.
- 2026.11.06(sooyeon.choi) 수정 - 권한(사용자 결정, D-22 변경): 관리자 전용 → **문서를 볼 수 있는 모든 사용자**.
  볼 수 있는지(대화 주제 접근 + 보안 등급)는 라우트의 기존 판정(_load_visible_document, 볼 수 없으면 404)을 그대로 쓰고,
  실행 시점에 실행자가 여전히 문서를 볼 수 있는지 다시 확인한다(권한이 빠졌으면 NOT_FOUND로 실패).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass
# 2026.11.09(sooyeon.choi) 삭제 - 미사용 import(pathlib.Path, get_database_manager)
from typing import Any, Callable, Optional
from uuid import uuid4

from app.core.config import get_settings
from app.repositories.ingest_job_repository import IngestJobRepository
from app.repositories.ingest_record_repository import IngestRecordRepository, RestoreStateError
from app.repositories.metadata_repository import MetadataRepository
# 2026.11.09(sooyeon.choi) 수정 - 열람 범위는 공통 함수로 판정
from app.utils.security import document_scope, in_document_scope
from app.services.embedding_profile import current_profile_id

logger = logging.getLogger(__name__)

# 화면에 그대로 보여 줄 문구(내부 경로·주소·DB 오류는 넣지 않는다). 명세 v1.1 8절
BLOCK_MESSAGES = {
    "FEATURE_DISABLED": "버전 적용 기능이 꺼져 있습니다.",
    "ALREADY_ACTIVE": "현재 적용 중인 버전입니다.",
    "JOB_IN_PROGRESS": "다른 작업이 진행 중입니다.",
    "VERSION_NOT_FOUND": "선택한 버전을 찾을 수 없습니다.",
    "VERSION_NOT_RESTORABLE": "정상 처리·적용된 이력이 없는 버전입니다.",
    "PROFILE_UNKNOWN": "이 버전을 만든 검색 모델 정보를 확인할 수 없어 적용할 수 없습니다.",
    "MODEL_UNSUPPORTED": "현재 지원되지 않는 검색 모델로 생성된 버전입니다.",
    "METADATA_MISSING": "이 버전의 정보가 부족해 적용할 수 없습니다.",
    "VERIFICATION_REQUIRED": "보관 데이터 검증이 끝나지 않아 아직 적용할 수 없습니다.",
    "VECTOR_MISSING": "보관된 벡터 데이터가 없어 적용할 수 없습니다.",
    "SOURCE_MISSING": "이 버전의 원본 파일이 없어 적용할 수 없습니다.",
    "RESOURCE_MISSING": "이 버전의 사진 등 연결 자료가 없어 적용할 수 없습니다.",
    "VECTOR_INTEGRITY_MISMATCH": "보관된 검색 데이터가 기록과 달라 적용할 수 없습니다.",
    "STATE_CHANGED": "현재 적용 버전이 변경되었습니다. 버전 이력을 다시 확인하세요.",
    "IDEMPOTENCY_KEY_REUSED": "이미 다른 적용 요청에 사용한 요청 키입니다. 버전 이력을 다시 열어 적용하세요.",
    "RESTORE_RETRY_REQUIRES_NEW_REQUEST": "버전 적용 작업은 다시 시도할 수 없습니다. 버전 이력에서 새로 적용하세요.",
    "DEPENDENCY_UNAVAILABLE": "검색 데이터 확인 중 연결이 끊어졌습니다.",
    "INVALID_REQUEST": "요청 형식이 올바르지 않습니다.",
    # 2026.11.12(sooyeon.choi) 도면 파싱 기능 추가 - 도면 버전은 검색 데이터가 없어 적용 대상이 아니다
    "DRAWING_NOT_SUPPORTED": "도면은 아직 검색에 쓰이지 않아 이전 버전 적용 대상이 아닙니다.",
    # 2026.11.23(woojin.jung) 추가 - 부서 기준 수정 권한(이력 화면 표시용, 실행은 라우트가 403으로 차단)
    "NO_PERMISSION": "소속 부서의 운영관리자만 버전을 적용할 수 있습니다.",
    "DEPARTMENT_INACTIVE": "소속 부서가 비활성화되어 버전을 적용할 수 없습니다.",
}
STATUS_BY_CODE = {
    "INVALID_REQUEST": 422, "FEATURE_DISABLED": 403, "VERSION_NOT_FOUND": 404,
    "NOT_FOUND": 404, "ALREADY_ACTIVE": 409, "JOB_IN_PROGRESS": 409, "STATE_CHANGED": 409,
    "IDEMPOTENCY_KEY_REUSED": 409, "RESTORE_RETRY_REQUIRES_NEW_REQUEST": 409, "DEPENDENCY_UNAVAILABLE": 503,
}
_DOC_LEVEL_ORDER = ("FEATURE_DISABLED", "JOB_IN_PROGRESS")  # 2026.11.06(sooyeon.choi) 수정 - 관리자 사유 제거


class RestoreError(Exception):
    """API 오류(detail={code, message}) 또는 작업 실패 코드."""

    def __init__(self, code: str, message: Optional[str] = None, status: Optional[int] = None) -> None:
        super().__init__(message or BLOCK_MESSAGES.get(code, code))
        self.code = code
        self.message = message or BLOCK_MESSAGES.get(code, code)
        self.status = status or STATUS_BY_CODE.get(code, 422)


def restore_enabled(settings=None) -> bool:
    return bool(getattr(settings or get_settings(), "document_version_restore_enabled", False))


# ── 가능 여부 판정(이력 GET·접수·실행 공통) ─────────────────────────────────────

def document_block_code(*, settings, principal: dict, pending_job: Optional[dict]) -> Optional[str]:
    """문서 단위 사유(설계 8절 1). 우선순위: 기능 → 진행 작업.
    2026.11.06(sooyeon.choi) 수정 - 관리자 여부는 보지 않는다(문서를 볼 수 있으면 복원 가능, 호출 전 라우트가 확인)."""
    if not restore_enabled(settings):
        return "FEATURE_DISABLED"
    if pending_job:
        return "JOB_IN_PROGRESS"
    return None


def version_block_code(version: dict, *, profile_id: Optional[int]) -> Optional[str]:
    """행 고유 사유(문서 단위 사유가 없을 때). 저장된 검증 기록만 본다(Qdrant·파일 실물 확인은 실행 시).

    순서: 정상 적용 이력 → 벡터 없음(삭제 확정) → 프로필 → snapshot → 검증. 기존 버전 대부분이 '벡터 삭제됨'이므로
    그 사유를 프로필 불명보다 먼저 보여 준다(설계 8절 순서에서 VECTOR_MISSING만 앞당김 — 보고서에 기록).
    """
    # 2026.11.12(sooyeon.choi) 도면 파싱 기능 추가 - 도면 버전(봉인·벡터 없음)은 항상 거부
    if version.get("processing_engine") == "drawing_ingest":
        return "DRAWING_NOT_SUPPORTED"
    if version.get("status") != "retired" or not version.get("activated_at"):
        return "VERSION_NOT_RESTORABLE"
    if version.get("vector_storage_state") == "missing":
        return "VECTOR_MISSING"
    if version.get("embedding_profile_id") is None:
        return "PROFILE_UNKNOWN"
    if profile_id is None or int(version["embedding_profile_id"]) != int(profile_id):
        return "MODEL_UNSUPPORTED"
    if not version.get("has_snapshot", version.get("document_snapshot_json") is not None):
        return "METADATA_MISSING"
    if version.get("vector_storage_state") != "available":
        return "VERIFICATION_REQUIRED"
    if not version.get("source_path"):
        return "SOURCE_MISSING"
    return None


def evaluate_versions(versions: list[dict], *, doc_code: Optional[str], profile_id: Optional[int], pending_busy: bool):
    """행마다 (can_restore, code, reason). 현재 적용 행은 항상 ALREADY_ACTIVE, 그 외는 문서 단위 사유를 복사."""
    rows = []
    for version in versions:
        if version.get("status") == "active":
            code = "ALREADY_ACTIVE"
        elif doc_code:
            code = doc_code
        else:
            code = version_block_code(version, profile_id=profile_id)
        rows.append((code is None, code, BLOCK_MESSAGES.get(code) if code else None))
    return rows


# ── 작업 응답 공통 ──────────────────────────────────────────────────────────

def operation_type_of(job: dict) -> str:
    """외부 응답용 작업 유형: restore / replace(최신본 변경) / upload."""
    if job.get("operation_type") == "restore":
        return "restore"
    return "replace" if (job.get("request") or {}).get("target_document_id") else "upload"


def job_payload(job: dict) -> dict[str, Any]:
    request = job.get("request") or {}
    if job.get("operation_type") == "restore":
        return {
            "operation_type": "restore",
            "document_id": job.get("document_id") or request.get("document_id"),
            "from_version_no": request.get("from_version_no"),
            "target_version_no": request.get("target_version_no"),
        }
    payload = {"operation_type": operation_type_of(job)}
    if request.get("target_document_id"):
        payload.update(document_id=request["target_document_id"], target_version_no=request.get("version_no"))
    return payload


def _fingerprint(document_id: str, target_version_no: int, expected_version_no: int, expected_revision: int) -> str:
    canonical = json.dumps({
        "document_id": document_id, "target_version_no": target_version_no,
        "expected_current_version_no": expected_version_no, "expected_activation_revision": expected_revision,
    }, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ── 접수 ────────────────────────────────────────────────────────────────────

@dataclass
class SubmitResult:
    job: dict
    created: bool  # True면 새로 접수(202), False면 같은 키 재전송(진행 중 202·끝났으면 200)


def submit_restore(
    document_id: str, version_no: int, *, expected_version_no: int, expected_revision: int, idempotency_key: str,
    principal: dict, settings=None,
) -> SubmitResult:
    """6.1 접수 트랜잭션. 문서 가시성(=복원 권한)은 호출자(라우트)가 이미 확인했다. 실패하면 RestoreError."""
    settings = settings or get_settings()
    repo = IngestRecordRepository()
    jobs = IngestJobRepository()
    actor = principal["user_id"]
    fingerprint = _fingerprint(document_id, version_no, expected_version_no, expected_revision)
    with repo.db.get_connection():
        repo.lock_document(document_id)
        # 같은 키 재전송이면 상태가 이미 바뀌었어도(또는 기능이 꺼졌어도) 기존 작업을 돌려준다
        existing = jobs.find_by_idempotency_key(actor, "restore", idempotency_key)
        if existing:
            if existing.get("request_fingerprint") != fingerprint:
                raise RestoreError("IDEMPOTENCY_KEY_REUSED")
            return SubmitResult(existing, created=False)
        if not restore_enabled(settings):
            raise RestoreError("FEATURE_DISABLED")
        doc = repo.db.execute_query(
            "SELECT version_no, activation_revision, pending_job_id FROM tb_documents "
            "WHERE document_id = ? AND deleted_at IS NULL FOR UPDATE",
            (document_id,),
        )
        if not doc:
            raise RestoreError("NOT_FOUND", "해당 문서를 찾을 수 없습니다.")
        doc = dict(doc[0])
        current_version_no = int(doc["version_no"] or 1)
        version = repo.get_version(document_id, version_no)
        if not version:
            raise RestoreError("VERSION_NOT_FOUND")
        if current_version_no != expected_version_no or int(doc["activation_revision"]) != expected_revision:
            raise RestoreError("STATE_CHANGED")
        if version_no == current_version_no or version.get("status") == "active":
            raise RestoreError("ALREADY_ACTIVE")
        if doc["pending_job_id"] or repo.in_progress_version(document_id):
            raise RestoreError("JOB_IN_PROGRESS")
        code = version_block_code(version, profile_id=current_profile_id(repo.db, settings))
        if code:
            raise RestoreError(code)
        job_id = str(uuid4())
        request = {
            "document_id": document_id,
            "target_version_no": version_no,
            "from_version_no": current_version_no,
            "expected_current_version_no": expected_version_no,
            "expected_activation_revision": expected_revision,
            "actor_id": actor,
        }
        jobs.create(
            job_id, request, actor, operation_type="restore", document_id=document_id,
            idempotency_key=idempotency_key, request_fingerprint=fingerprint,
        )
        if not repo.acquire_pending(document_id, job_id):
            raise RestoreError("JOB_IN_PROGRESS")
    logger.info("event=version_restore status=queued document_id=%s from=%s to=%s job_id=%s",
                document_id, current_version_no, version_no, job_id)
    return SubmitResult(jobs.get(job_id), created=True)


# ── 실행 ────────────────────────────────────────────────────────────────────

def _default_vector_repo():
    from app.repositories.vector_repository import VectorRepository

    settings = get_settings()
    return VectorRepository(
        host=settings.qdrant_host, port=settings.qdrant_port,
        sparse_encoder_type=settings.sparse_encoder_type, kiwi_bm25_vector_name=settings.kiwi_bm25_vector_name,
    )


def _default_source_exists(source_path: str) -> bool:
    from app.services.ingest_service import get_original_file_storage

    try:
        return get_original_file_storage(get_settings()).resolve(source_path).is_file()
    except ValueError:
        return False


def _default_resource_exists(resource_id: str) -> bool:
    from app.routes.spreadsheet_resources import _service

    try:
        _service().resolve_resource(resource_id)
        return True
    except (FileNotFoundError, ValueError):
        return False


def _check_points(vector_repo, collection_name: str, document_id: str, version_no: int, point_ids: list[str]) -> None:
    """Qdrant에 이 버전 포인트가 모두 있고 문서·버전이 맞는지 확인(벡터는 읽지 않음)."""
    client = getattr(vector_repo, "client", None)
    if client is None:
        raise RestoreError("DEPENDENCY_UNAVAILABLE")
    found = 0
    try:
        for start in range(0, len(point_ids), 256):
            batch = point_ids[start:start + 256]
            records = client.retrieve(
                collection_name=collection_name, ids=batch, with_payload=["document_id", "version_no"],
                with_vectors=False,
            )
            for record in records:
                payload = record.payload or {}
                if payload.get("document_id") != document_id or int(payload.get("version_no") or 0) != version_no:
                    raise RestoreError("VECTOR_INTEGRITY_MISMATCH")
            found += len(records)
    except RestoreError:
        raise
    except Exception as exc:
        logger.warning("event=version_restore step=snapshot qdrant_error=%s", type(exc).__name__)
        raise RestoreError("DEPENDENCY_UNAVAILABLE") from exc
    if found != len(point_ids):
        raise RestoreError("VECTOR_MISSING")


def verify_version_data(
    document_id: str, version_no: int, *, repo: IngestRecordRepository, collection_name: str, vector_repo,
    source_exists: Callable[[str], bool], resource_exists: Callable[[str], bool],
) -> None:
    """snapshot 단계: 원본·청크·사진·포인트 실물을 봉인된 명세와 대조한다."""
    version = repo.get_version(document_id, version_no)
    if not version:
        raise RestoreError("VERSION_NOT_FOUND")
    if not version.get("source_path") or not source_exists(version["source_path"]):
        raise RestoreError("SOURCE_MISSING")
    manifest = version.get("vector_manifest_json")
    if isinstance(manifest, str):
        manifest = json.loads(manifest)
    if not manifest:
        raise RestoreError("VERIFICATION_REQUIRED")
    point_ids = repo.version_point_ids(document_id, version_no)
    digest = hashlib.sha256("\n".join(sorted(point_ids)).encode("utf-8")).hexdigest()
    if len(point_ids) != manifest.get("point_count") or digest != manifest.get("point_ids_sha256"):
        raise RestoreError("VECTOR_INTEGRITY_MISMATCH")
    for resource_id in repo.version_resources(document_id, version_no):
        if not resource_exists(resource_id):
            raise RestoreError("RESOURCE_MISSING")
    _check_points(vector_repo, collection_name, document_id, version_no, point_ids)


# 2026.11.06(sooyeon.choi) 수정 - 관리자 확인 → 실행자가 지금도 문서를 볼 수 있는지 확인(라우트의 판정과 같은 규칙:
#   관리자는 전체, 그 외는 접근 가능한 대화 주제 + 보안 등급 계층)
def _actor_can_view(db, actor_id: Optional[str], collection_name: Optional[str], security_level: Optional[str]) -> bool:
    rows = db.execute_query("SELECT role FROM tb_users WHERE user_id = ?", (actor_id,))
    if not rows:
        return False
    if rows[0][0] == "admin":
        return True
    permissions = MetadataRepository().get_user_permissions(actor_id)
    # 2026.11.09(sooyeon.choi) 수정 - 열람 범위 공통 함수 사용(권한 행이 없으면 불가)
    return in_document_scope(document_scope(permissions), collection_name, security_level or "public")


async def run_restore_job(
    job_id: str, *, vector_repo=None, source_exists: Optional[Callable[[str], bool]] = None,
    resource_exists: Optional[Callable[[str], bool]] = None,
) -> None:
    """작업 관리자가 호출한다(6.2). 파일 경로·체크포인트 로직을 쓰지 않는다."""
    jobs = IngestJobRepository()
    repo = IngestRecordRepository()
    job = await asyncio.to_thread(jobs.get, job_id)
    if not job or job.get("status") in ("completed", "failed"):
        return
    request = job["request"]
    document_id, target = request["document_id"], int(request["target_version_no"])

    # 재시작 복구: 이미 전환이 커밋됐으면(적용 이력에 이 작업) 작업만 완료로 맞춘다
    done = await asyncio.to_thread(
        repo.db.execute_query,
        "SELECT activation_id FROM tb_document_version_activations WHERE job_id = ?", (job_id,),
    )
    if done:
        await asyncio.to_thread(jobs.update, job_id, status="completed", step="completed", result=job.get("result"))
        return

    step = "validate"

    async def progress(name: str) -> None:
        nonlocal step
        step = name
        await asyncio.to_thread(jobs.update, job_id, status="running", step=name)

    try:
        await progress("validate")
        settings = get_settings()
        db = repo.db

        def _validate():
            doc = db.execute_query(
                """SELECT d.version_no, d.activation_revision, d.pending_job_id, d.security_level, c.qdrant_name
                   FROM tb_documents d LEFT JOIN tb_collections c ON c.collection_id = d.collection_id
                   WHERE d.document_id = ? AND d.deleted_at IS NULL""",
                (document_id,),
            )
            if not doc:
                raise RestoreError("NOT_FOUND", "문서가 없거나 삭제되었습니다.")
            doc = dict(doc[0])
            if not _actor_can_view(db, request.get("actor_id"), doc["qdrant_name"], doc["security_level"]):
                raise RestoreError("NOT_FOUND", "문서를 찾을 수 없거나 접근 권한이 없습니다.")
            if doc["pending_job_id"] != job_id:
                raise RestoreError("JOB_IN_PROGRESS")
            if (int(doc["version_no"] or 1) != int(request["expected_current_version_no"])
                    or int(doc["activation_revision"]) != int(request["expected_activation_revision"])):
                raise RestoreError("STATE_CHANGED")
            version = repo.get_version(document_id, target)
            if not version:
                raise RestoreError("VERSION_NOT_FOUND")
            code = version_block_code(version, profile_id=current_profile_id(db, settings))
            if code:
                raise RestoreError(code)
            return doc["qdrant_name"]

        collection_name = await asyncio.to_thread(_validate)

        await progress("snapshot")
        await asyncio.to_thread(
            verify_version_data, document_id, target, repo=repo, collection_name=collection_name,
            vector_repo=vector_repo or _default_vector_repo(),
            source_exists=source_exists or _default_source_exists,
            resource_exists=resource_exists or _default_resource_exists,
        )

        await progress("activate")

        def _activate():
            with db.get_connection():
                result = repo.restore_version(
                    document_id, target, job_id=job_id, actor_id=request.get("actor_id"),
                    expected_version_no=int(request["expected_current_version_no"]),
                    expected_revision=int(request["expected_activation_revision"]),
                )
                actor_name = db.execute_query(
                    "SELECT nullif(user_name, '') FROM tb_users WHERE user_id = ?", (request.get("actor_id"),)
                )
                result["activated_by"] = request.get("actor_id")
                result["activated_by_name"] = actor_name[0][0] if actor_name else None
                db.execute_update(
                    """INSERT INTO tb_document_events (document_id, collection_id, event_type, event_message, actor_id,
                                                      snapshot_json)
                       SELECT d.document_id, d.collection_id, 'restore', ?,
                              (SELECT user_id FROM tb_users WHERE user_id = ?), ?
                       FROM tb_documents d WHERE d.document_id = ?""",
                    (
                        f"restore: v{result['from_version_no']} -> v{target}", request.get("actor_id"),
                        json.dumps({"from_version_no": result["from_version_no"], "to_version_no": target,
                                    "job_id": job_id}),
                        document_id,
                    ),
                )
                jobs.update(job_id, status="completed", step="completed", result=_jsonable(result))
            return result

        result = await asyncio.to_thread(_activate)
        logger.info("event=version_restore status=completed document_id=%s from=%s to=%s job_id=%s",
                    document_id, result["from_version_no"], target, job_id)
    except Exception as exc:
        if isinstance(exc, RestoreError):
            code, message = exc.code, exc.message
        elif isinstance(exc, RestoreStateError):
            code, message = exc.code, BLOCK_MESSAGES.get(exc.code, str(exc))
        else:
            logger.exception("event=version_restore status=error document_id=%s job_id=%s", document_id, job_id)
            code, message = "RESTORE_FAILED", "버전 적용을 처리하는 중 오류가 발생했습니다."
        logger.warning("event=version_restore status=failed document_id=%s to=%s job_id=%s code=%s",
                       document_id, target, job_id, code)

        def _fail():
            with repo.db.get_connection():
                repo.release_pending(document_id, job_id)
                jobs.update(job_id, status="failed", step=step, error=message, error_code=code)

        await asyncio.to_thread(_fail)


def _jsonable(result: dict) -> dict:
    from app.utils.datetime import format_kst_datetime

    out = dict(result)
    if out.get("activated_at") is not None and not isinstance(out["activated_at"], str):
        out["activated_at"] = format_kst_datetime(out["activated_at"])
    return out

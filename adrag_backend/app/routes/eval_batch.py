# 2026.11.18(sooyeon.choi) 추가 - 시험 대응 일괄 질의 API (설계 6.1~6.6, R8-7, N-4)
"""질의 파일 업로드 → 순차 실행 → 진행 조회 → 결과 CSV/xlsx 다운로드 → 정답 근거 대조·Recall@10.

- 모두 관리자 인증(get_current_admin). 설정 eval_batch_query_enabled=false면 404(F-17).
- 질의는 작업 등록 관리자 계정으로 RAGService.query()를 실행한다(F-02, F-15).
"""

import time
from datetime import datetime
from typing import Any, Dict, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response

from app.core.config import get_settings
from app.evaluation.batch import runner
from app.evaluation.batch.exporter import build_gold_review_xlsx, build_results_csv, build_results_xlsx
from app.evaluation.batch.file_reader import QueryFileError, read_query_file
from app.evaluation.batch.gold_matcher import match_all, read_gold_file, read_gold_review
from app.evaluation.batch.recall import compute_recall, summary_view
from app.repositories.collection_repository import CollectionRepository
from app.repositories.eval_batch_repository import EvalBatchRepository
from app.utils.log.log import LoggingLogger
from app.utils.security import get_current_admin

logger = LoggingLogger().getLogger(__name__)


def require_batch_enabled() -> None:
    if not get_settings().eval_batch_query_enabled:
        raise HTTPException(status_code=404, detail="Not Found")


router = APIRouter(
    prefix="/eval/batch-jobs",
    tags=["Evaluation Batch"],
    dependencies=[Depends(require_batch_enabled)],
)

_FINISHED = ("completed", "failed", "cancelled")


def _repo() -> EvalBatchRepository:
    return EvalBatchRepository()


def _config_snapshot() -> Dict[str, Any]:
    """실행 시점 검색·생성 설정(재현 근거). 비밀값·주소는 넣지 않는다."""
    try:
        from app.core.runtime_settings import get_runtime_settings

        settings = get_runtime_settings()
    except Exception:
        settings = get_settings()
    return {
        "llm_model": getattr(settings, "vllm_model_name", None),
        "metric_version": "rule-v1.3",
        "response_time_basis": "service_request_elapsed_all_items",
        "embedding_model": getattr(settings, "embedding_model_name", None),
        "candidate_top_k": getattr(settings, "candidate_top_k", None),
        "reranker_top_k": getattr(settings, "reranker_top_k", None),
        "context_top_k": getattr(settings, "context_top_k", None),
        "relevance_threshold": getattr(settings, "relevance_threshold", None),
        "retrieval_engine": getattr(settings, "retrieval_engine", None),
        "top_n_record": get_settings().eval_batch_top_n_record,
        "query_timeout_s": get_settings().eval_batch_query_timeout_s,
        "retry_count": get_settings().eval_batch_retry_count,
    }


def _get_job_or_404(repo: EvalBatchRepository, job_id: int) -> Dict[str, Any]:
    job = repo.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="일괄 질의 작업을 찾을 수 없습니다")
    return job


def _doc_version_changed(repo: EvalBatchRepository, job: Dict[str, Any]) -> bool:
    """등록 시점 문서 버전과 지금이 다른지(F-18)."""
    return repo.collection_doc_versions(job["collection_name"]) != (job.get("doc_versions_json") or {})


# 2026.11.18(sooyeon.choi) 추가 - 정답 확정 후 Recall@k(기본: 재랭킹 전 상위 10, F-08) 계산
def _recall(repo: EvalBatchRepository, job: Dict[str, Any], basis: str = "retrieved", k: int = 10) -> Optional[Dict[str, Any]]:
    if job.get("gold_status") != "confirmed":
        return None
    gold_rows = repo.list_gold(job["job_id"])
    # 2026.11.19(sooyeon.choi) 수정 - 정답 청크(포인트 ID)의 문서 버전은 DB에서 조회
    gold_ids = sorted({cid for row in gold_rows for cid in (row.get("confirmed_ids") or [])})
    return compute_recall(
        repo.list_items(job["job_id"]), gold_rows,
        basis=basis, k=k, doc_versions=job.get("doc_versions_json") or {},
        chunk_versions=repo.chunk_versions(gold_ids),
    )


def _with_recall_summary(repo: EvalBatchRepository, job: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """요약에 Recall@10을 붙인다(정답 확정 전이면 None). 질의별 결과(recall_by_key)를 함께 반환."""
    recall = _recall(repo, job)
    if job.get("summary_json") is not None:
        job["summary_json"] = {
            **job["summary_json"], "recall_at_10": summary_view(recall) if recall else None,
        }
    return recall["per_query"] if recall else None


def _job_view(repo: EvalBatchRepository, job: Dict[str, Any]) -> Dict[str, Any]:
    _with_recall_summary(repo, job)
    eta_seconds: Optional[int] = None
    if job["status"] in ("pending", "running"):
        remaining = int(job["total_count"]) - int(job["done_count"])
        avg_ms = repo.average_response_ms(job["job_id"])
        if avg_ms is not None:
            eta_seconds = int(round(remaining * avg_ms / 1000))
    return {
        "job_id": job["job_id"],
        "name": job["name"],
        "collection_name": job["collection_name"],
        "status": job["status"],
        "total": job["total_count"],
        "done": job["done_count"],
        "errors": job["error_count"],
        "warmup_count": job["warmup_count"],
        "queue_position": repo.queue_position(job["job_id"]) if job["status"] == "pending" else 0,
        "created_at": job["created_at"],
        "started_at": job["started_at"],
        "finished_at": job["finished_at"],
        "eta_seconds": eta_seconds,
        "doc_version_changed": _doc_version_changed(repo, job),
        "summary": job.get("summary_json"),
        "gold_status": job["gold_status"],
        "error_message": job.get("error_message"),
        "config": job.get("config_json"),
    }


# ── 6.1 작업 등록 ───────────────────────────────────────────────────────────

@router.post("", status_code=202)
async def create_batch_job(
    file: UploadFile = File(...),
    collection_name: str = Form(...),
    name: Optional[str] = Form(default=None),
    warmup_count: Optional[int] = Form(default=None, ge=0, le=20),
    admin: dict = Depends(get_current_admin),
):
    settings = get_settings()
    collection = CollectionRepository().get_by_qdrant_name(collection_name)
    if not collection:
        raise HTTPException(status_code=404, detail="컬렉션을 찾을 수 없습니다")

    content = await file.read(settings.eval_batch_upload_max_mb * 1024 * 1024 + 1)
    if len(content) > settings.eval_batch_upload_max_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"파일은 {settings.eval_batch_upload_max_mb}MB 이하만 올릴 수 있습니다")
    try:
        parsed = read_query_file(
            file.filename or "",
            content,
            max_rows=settings.eval_batch_max_rows,
            max_chars=settings.eval_batch_query_max_chars,
        )
    except QueryFileError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc), "errors": []})
    if parsed.errors:
        raise HTTPException(
            status_code=400,
            detail={"message": "질의 파일에 오류가 있어 작업을 만들지 않았습니다", "errors": parsed.errors},
        )

    repo = _repo()
    job_id = repo.create_job(
        name=(name or file.filename or "일괄 질의").strip()[:200],
        collection_name=collection_name,
        items=parsed.items,
        warmup_count=settings.eval_batch_warmup_count if warmup_count is None else warmup_count,
        config=_config_snapshot(),
        doc_versions=repo.collection_doc_versions(collection_name),
        created_by=admin.get("admin_id"),
    )
    logger.info(
        "[eval-batch] 작업 등록 job=%s admin=%s items=%s", job_id, admin.get("admin_id"), len(parsed.items)
    )
    runner.kick()
    return {
        "job_id": job_id,
        "status": "pending",
        "total": len(parsed.items),
        "queue_position": repo.queue_position(job_id),
    }


# ── 6.2 진행 조회 · 6.3 목록 ────────────────────────────────────────────────

@router.get("")
async def list_batch_jobs(
    limit: int = Query(default=20, ge=1, le=100),
    _: dict = Depends(get_current_admin),
):
    return {"items": _repo().list_jobs(limit)}


@router.get("/{job_id}")
async def get_batch_job(job_id: int, _: dict = Depends(get_current_admin)):
    repo = _repo()
    return _job_view(repo, _get_job_or_404(repo, job_id))


# ── 6.4 취소 · 6.5 삭제 ─────────────────────────────────────────────────────

@router.post("/{job_id}/cancel")
async def cancel_batch_job(job_id: int, _: dict = Depends(get_current_admin)):
    repo = _repo()
    job = _get_job_or_404(repo, job_id)
    if job["status"] in _FINISHED:
        raise HTTPException(status_code=409, detail="이미 끝난 작업입니다")
    if job["status"] == "pending":
        repo.finish_job(job_id, "cancelled", summary=runner.compute_summary(repo.list_items(job_id)))
    else:
        # 실행기가 다음 질의 전에 상태를 확인하고 멈춘다(완료 결과 보존)
        repo.finish_job(job_id, "cancelled")
    return {"job_id": job_id, "status": "cancelled"}


@router.delete("/{job_id}")
async def delete_batch_job(job_id: int, _: dict = Depends(get_current_admin)):
    repo = _repo()
    job = _get_job_or_404(repo, job_id)
    if job["status"] in ("pending", "running"):
        raise HTTPException(status_code=409, detail="대기·실행 중인 작업은 삭제할 수 없습니다. 먼저 취소해 주세요.")
    repo.delete_job(job_id)
    return {"deleted": True}


# ── 6.6 결과 다운로드 ───────────────────────────────────────────────────────

def _download(job: Dict[str, Any], content: bytes, ext: str, media_type: str) -> Response:
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    filename = f"batch_{job['job_id']}_{stamp}.{ext}"
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"; filename*=UTF-8\'\'{quote(filename)}',
            "Cache-Control": "no-store",
        },
    )


def _finished_job_or_409(repo: EvalBatchRepository, job_id: int) -> Dict[str, Any]:
    job = _get_job_or_404(repo, job_id)
    if job["status"] not in ("completed", "cancelled"):
        raise HTTPException(status_code=409, detail="완료되거나 취소된 작업만 내려받을 수 있습니다")
    # 취소 직후 실행기가 요약을 아직 쓰지 않았으면 지금 계산한다
    if not job.get("summary_json"):
        job["summary_json"] = runner.compute_summary(repo.list_items(job_id))
    job["doc_version_changed"] = _doc_version_changed(repo, job)
    return job


@router.get("/{job_id}/results.csv")
async def download_batch_results_csv(job_id: int, admin: dict = Depends(get_current_admin)):
    repo = _repo()
    job = _finished_job_or_409(repo, job_id)
    started = time.perf_counter()
    recall_by_key = _with_recall_summary(repo, job)
    content = build_results_csv(repo.list_items(job_id), recall_by_key)
    logger.info(
        "[eval-batch] CSV 생성 job=%s admin=%s elapsed_ms=%s",
        job_id, admin.get("admin_id"), round((time.perf_counter() - started) * 1000),
    )
    return _download(job, content, "csv", "text/csv; charset=utf-8")


@router.get("/{job_id}/results.xlsx")
async def download_batch_results_xlsx(job_id: int, admin: dict = Depends(get_current_admin)):
    repo = _repo()
    job = _finished_job_or_409(repo, job_id)
    recall_by_key = _with_recall_summary(repo, job)
    content = build_results_xlsx(job, repo.list_items(job_id), recall_by_key)
    logger.info("[eval-batch] xlsx 생성 job=%s admin=%s", job_id, admin.get("admin_id"))
    return _download(
        job, content, "xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


# ── 6.7 정답 근거 대조 ──────────────────────────────────────────────────────
# 2026.11.18(sooyeon.choi) 추가 - 정답 파일 → 자동 매칭 → 검토 Excel → 확정 → Recall@10

async def _read_upload(file: UploadFile) -> bytes:
    limit = get_settings().eval_batch_upload_max_mb * 1024 * 1024
    content = await file.read(limit + 1)
    if len(content) > limit:
        raise HTTPException(status_code=413, detail=f"파일은 {get_settings().eval_batch_upload_max_mb}MB 이하만 올릴 수 있습니다")
    return content


@router.post("/{job_id}/gold")
async def upload_batch_gold(
    job_id: int,
    file: UploadFile = File(...),
    admin: dict = Depends(get_current_admin),
):
    """정답 파일(질의ID·근거순번·근거 문서명·근거 위치·근거 내용) 업로드 → 자동 매칭. 다시 올리면 덮어씀.

    2026.11.19(sooyeon.choi) 추가 - '청크ID' 열이 있는 근거는 매칭 없이 확정한다.
    모든 근거에 청크ID가 있으면 검토 단계 없이 바로 gold_status='confirmed'(시험 데이터셋 정답 근거 시트).
    """
    repo = _repo()
    job = _get_job_or_404(repo, job_id)
    content = await _read_upload(file)
    try:
        evidences, errors = read_gold_file(file.filename or "", content, repo.list_query_keys(job_id))
    except QueryFileError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc), "errors": []})
    direct_ids = sorted({cid for ev in evidences for cid in ev.get("chunk_ids") or []})
    if direct_ids:
        known_ids = repo.existing_chunk_ids(job["collection_name"], direct_ids)
        unknown = [cid for cid in direct_ids if cid not in known_ids]
        if unknown:
            errors.append({
                "row": None, "column": "청크ID",
                "reason": f"컬렉션에 없는 청크ID {len(unknown)}건: {', '.join(unknown[:3])}",
            })
    if errors:
        raise HTTPException(
            status_code=400,
            detail={"message": "정답 파일에 오류가 있어 반영하지 않았습니다", "errors": errors},
        )
    documents = repo.collection_documents(job["collection_name"])
    matched = match_all(
        evidences, documents, repo.active_chunks(documents),
        float(get_settings().eval_batch_gold_match_threshold),
    )
    # 2026.11.19(sooyeon.choi) 수정 - 청크ID 직접 지정 근거는 확정값 유지, 모두 직접 지정이면 바로 확정
    all_direct = all(row["match_status"] == "confirmed" for row in matched)
    gold_status = "confirmed" if all_direct else "matched"
    repo.replace_gold(
        job_id,
        [{**row, "confirmed_ids": row.get("confirmed_ids") if row["match_status"] == "confirmed" else None}
         for row in matched],
        gold_status=gold_status,
    )
    counts: Dict[str, int] = {}
    for row in matched:
        counts[row["match_status"]] = counts.get(row["match_status"], 0) + 1
    doc_missing = sum(1 for row in matched if row["matched_json"]["doc_match"] == "none")
    logger.info("[eval-batch] 정답 매칭 job=%s admin=%s evidences=%s", job_id, admin.get("admin_id"), len(matched))
    response = {
        "job_id": job_id,
        "gold_status": gold_status,
        "evidences": len(matched),
        "queries": len({row["query_key"] for row in matched}),
        "auto": counts.get("auto", 0),
        "unmatched": counts.get("unmatched", 0),
        "confirmed": counts.get("confirmed", 0),
        "document_not_found": doc_missing,
    }
    if all_direct:
        recall = _recall(repo, _get_job_or_404(repo, job_id))
        response["recall_at_10"] = summary_view(recall) if recall else None
    return response


@router.get("/{job_id}/gold-review.xlsx")
async def download_batch_gold_review(job_id: int, _: dict = Depends(get_current_admin)):
    repo = _repo()
    job = _get_job_or_404(repo, job_id)
    gold_rows = repo.list_gold(job_id)
    if not gold_rows:
        raise HTTPException(status_code=409, detail="정답 파일을 먼저 올려 주세요")
    return _download(
        {**job, "job_id": f"{job_id}_gold_review"}, build_gold_review_xlsx(job, gold_rows), "xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.post("/{job_id}/gold-review")
async def upload_batch_gold_review(
    job_id: int,
    file: UploadFile = File(...),
    admin: dict = Depends(get_current_admin),
):
    """사람이 고친 검토 Excel 업로드 → 확정 청크 저장 → gold_status='confirmed' → Recall@10."""
    repo = _repo()
    job = _get_job_or_404(repo, job_id)
    gold_rows = repo.list_gold(job_id)
    if not gold_rows:
        raise HTTPException(status_code=409, detail="정답 파일을 먼저 올려 주세요")
    try:
        reviewed = read_gold_review(await _read_upload(file))
    except QueryFileError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc), "errors": []})

    by_key = {(row["query_key"], row["evidence_seq"]): row for row in gold_rows}
    errors = []
    updates = []
    all_ids = sorted({cid for row in reviewed for cid in row["confirmed_ids"]})
    known_ids = repo.existing_chunk_ids(job["collection_name"], all_ids)
    seen = set()
    for row in reviewed:
        gold = by_key.get((row["query_key"], row["evidence_seq"]))
        if gold is None:
            errors.append({"row": row["row"], "column": "질의ID·근거순번", "reason": "정답 파일에 없는 근거"})
            continue
        seen.add(gold["gold_id"])
        unknown = [cid for cid in row["confirmed_ids"] if cid not in known_ids]
        if unknown:
            errors.append({"row": row["row"], "column": "확정 청크ID", "reason": f"컬렉션에 없는 청크ID: {', '.join(unknown[:3])}"})
            continue
        if row["excluded"]:
            status = "excluded"
        elif row["confirmed_ids"]:
            status = "confirmed"
        else:
            status = "unmatched"
        updates.append({"gold_id": gold["gold_id"], "confirmed_ids": row["confirmed_ids"], "match_status": status})
    missing = [row for row in gold_rows if row["gold_id"] not in seen]
    for row in missing:
        errors.append({
            "row": None, "column": "질의ID·근거순번",
            "reason": f"검토 파일에 빠진 근거: {row['query_key']} / {row['evidence_seq']}",
        })
    if errors:
        raise HTTPException(
            status_code=400,
            detail={"message": "검토 파일에 오류가 있어 확정하지 않았습니다", "errors": errors},
        )
    repo.confirm_gold(job_id, updates)
    job = _get_job_or_404(repo, job_id)
    recall = _recall(repo, job)
    logger.info("[eval-batch] 정답 확정 job=%s admin=%s evidences=%s", job_id, admin.get("admin_id"), len(updates))
    return {
        "job_id": job_id,
        "gold_status": "confirmed",
        "confirmed": sum(1 for u in updates if u["match_status"] == "confirmed"),
        "excluded": sum(1 for u in updates if u["match_status"] == "excluded"),
        "unmatched": sum(1 for u in updates if u["match_status"] == "unmatched"),
        "recall_at_10": summary_view(recall) if recall else None,
    }


@router.get("/{job_id}/recall")
async def get_batch_recall(
    job_id: int,
    basis: str = Query(default="retrieved", pattern="^(retrieved|reranked)$"),
    k: int = Query(default=10, ge=1, le=50),
    _: dict = Depends(get_current_admin),
):
    """기준(재랭킹 전/후)·k를 바꿔 재계산(C-01 대응, 재실행 불필요). 질의별 적중 포함."""
    repo = _repo()
    job = _get_job_or_404(repo, job_id)
    if job.get("gold_status") != "confirmed":
        raise HTTPException(status_code=409, detail="정답 근거를 먼저 확정해 주세요")
    top_n = int((job.get("config_json") or {}).get("top_n_record") or 10)
    if k > top_n:
        raise HTTPException(status_code=400, detail=f"저장된 상위 결과가 {top_n}개라 k는 {top_n} 이하만 가능합니다")
    return _recall(repo, job, basis=basis, k=k)

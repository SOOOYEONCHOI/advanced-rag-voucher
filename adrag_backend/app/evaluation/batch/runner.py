# 2026.11.18(sooyeon.choi) 추가 - 일괄 질의 단일 실행기 (설계 5.1, F-02~F-07, F-16)
"""앱 프로세스 안에서 대기 작업을 하나씩, 질의를 1건씩 순차 실행한다.

- 답변 경로: 운영 질의 API와 같은 ``RAGService.query()`` (평가 전용 그래프 실행 안 씀, F-02)
- 동시 실행 작업 1개(claim 시 running 작업이 있으면 대기), 질의 순차·대기 없음(F-03)
- 응답시간 = 서비스 요청 시작 → 반환/실패까지 단조 시계로 측정(F-04/F-05)
- 워밍업 N건은 결과·평균에서 제외(F-06), 재시도 없음(F-07)
- 취소: 라우트가 DB 상태를 cancelled로 바꾸면 다음 질의 전에 멈춘다(완료 결과 보존)
"""

import asyncio
import math
import time
from dataclasses import asdict
from typing import Any, Dict, List, Optional

from app.core.config import get_settings
from app.evaluation.batch.text_clean import clean_answer_text
from app.repositories.eval_batch_repository import EvalBatchRepository
from app.utils.log.log import LoggingLogger

logger = LoggingLogger().getLogger(__name__)

INPUT_MODE = "batch_eval"
# 답변 오류도 경과 시간과 검색·재랭킹 결과를 독립적으로 보존한다.
ERROR_OUTCOMES = frozenset({"validation_error", "retrieval_error", "llm_error", "system_error", "cancelled"})

# 설계 5.2 단계별 시간 묶음(timed_node 이름)
STAGE_NODES = {
    "search_ms": ("validate_input", "guardrail", "analyze_and_rewrite", "build_metadata_filter", "retrieve"),
    "rerank_ms": ("rerank",),
    "generate_ms": (
        "assemble_context", "collect_answer_images", "generate_answer",
        "format_citations", "fallback_handler", "build_response",
    ),
}

_worker_task: Optional[asyncio.Task] = None
_rag_service = None


def _get_rag_service():
    global _rag_service
    if _rag_service is None:
        from app.services.rag_service import RAGService

        _rag_service = RAGService()
    return _rag_service


def kick() -> None:
    """대기 작업이 있으면 실행 태스크를 띄운다(이미 돌고 있으면 그대로)."""
    global _worker_task
    if _worker_task is not None and not _worker_task.done():
        return
    _worker_task = asyncio.create_task(_worker_loop())


async def _worker_loop() -> None:
    repo = EvalBatchRepository()
    while True:
        job_id = await asyncio.to_thread(repo.claim_next_pending)
        if job_id is None:
            return
        try:
            await run_job(job_id, repo)
        except Exception as exc:  # 실행기 자체 오류도 작업 실패로 남기고 다음 작업으로
            logger.exception("[eval-batch] job=%s 실행기 오류", job_id)
            await asyncio.to_thread(repo.finish_job, job_id, "failed", error_message=str(exc)[:500])


def stage_timings(timing: Dict[str, float]) -> Dict[str, Optional[int]]:
    """노드별 시간(s) → 검색·재랭킹·답변생성(ms). 해당 노드 기록이 없으면 None."""
    output: Dict[str, Optional[int]] = {}
    for column, nodes in STAGE_NODES.items():
        values = [timing.get(f"{node}_s") for node in nodes]
        values = [v for v in values if isinstance(v, (int, float))]
        output[column] = int(round(sum(values) * 1000)) if values else None
    return output


def _ranked_chunks(chunks: List[Any], limit: int) -> List[Dict[str, Any]]:
    rows = []
    for index, chunk in enumerate(chunks[:limit], start=1):
        data = asdict(chunk) if not isinstance(chunk, dict) else dict(chunk)
        rows.append({
            "rank": data.get("rank") or index,
            "chunk_id": data.get("chunk_id"),
            "document_id": data.get("document_id"),
            "filename": data.get("document_name"),
            "sheet_name": data.get("sheet_name"),
            "step_no": data.get("step_no"),
            "page_number": data.get("page_number"),
            "score": data.get("score"),
            "text": data.get("text"),
        })
    return rows


def _citations(citations: List[Any]) -> List[Dict[str, Any]]:
    rows = []
    for citation in citations:
        data = asdict(citation) if not isinstance(citation, dict) else dict(citation)
        rows.append({
            "citation_id": data.get("citation_id"),
            "document_id": data.get("document_id"),
            "filename": data.get("original_filename"),
            "sheet_name": data.get("sheet_name"),
            "source_range": data.get("source_range"),
            "section_name": data.get("section_name"),
            "page_number": data.get("page_number"),
            "referenced_in_answer": bool(data.get("referenced_in_answer")),
            "chunk_text": data.get("chunk_text"),
        })
    return rows


def build_item_fields(response: Any, top_n: int) -> Dict[str, Any]:
    """QueryResponse → tb_eval_batch_items 저장 필드."""
    outcome = getattr(response, "outcome_code", None) or "unknown"
    answer = response.answer or ""
    is_error = outcome in ERROR_OUTCOMES
    return {
        "status": "error" if is_error else "ok",
        "outcome_code": outcome,
        "answer_text": answer,
        "answer_plain": clean_answer_text(answer) if not is_error else "",
        "citations_json": _citations(response.citations or []),
        "retrieved_top_json": _ranked_chunks(response.retrieved_chunks or [], top_n),
        "reranked_top_json": _ranked_chunks(response.chunks or [], top_n),
        "response_ms": (
            int(round(response.processing_time_ms))
            if response.processing_time_ms is not None else None
        ),
        # 2026.11.18(sooyeon.choi) 수정 - 첫 토큰 시간(ms)도 timing_json에 함께 저장(마이그레이션 없음)
        "timing_json": {
            **dict(response.timing or {}),
            "first_token_ms": getattr(response, "first_token_ms", None),
            "stage_statuses": dict(getattr(response, "stage_statuses", {}) or {}),
            "server_processing_ms": response.processing_time_ms,
        },
        "log_id": response.log_id,
        "error_message": outcome if is_error else None,
    }


async def _run_query(job: Dict[str, Any], query_text: str, timeout_s: float):
    return await asyncio.wait_for(
        _get_rag_service().query(
            query=query_text,
            user_id=job.get("created_by") or "eval_batch",
            collection_name=job["collection_name"],
            input_mode=INPUT_MODE,
            capture_retrieval=True,
        ),
        timeout=timeout_s,
    )


async def _is_cancelled(repo: EvalBatchRepository, job_id: int) -> bool:
    job = await asyncio.to_thread(repo.get_job, job_id)
    return not job or job["status"] == "cancelled"


async def run_job(job_id: int, repo: Optional[EvalBatchRepository] = None) -> None:
    repo = repo or EvalBatchRepository()
    settings = get_settings()
    job = await asyncio.to_thread(repo.get_job, job_id)
    if not job:
        return
    timeout_s = float(settings.eval_batch_query_timeout_s)
    top_n = int(settings.eval_batch_top_n_record)
    items = await asyncio.to_thread(repo.list_pending_items, job_id)
    logger.info("[eval-batch] job=%s 시작 items=%s warmup=%s", job_id, len(items), job["warmup_count"])

    # 워밍업(F-06): 앞 N건을 먼저 실행하고 결과는 버린다. 실패하면 LLM·검색 서버 이상으로 보고 중단.
    for warm in items[: int(job["warmup_count"] or 0)]:
        try:
            response = await _run_query(job, warm["query_text"], timeout_s)
        except Exception as exc:
            await asyncio.to_thread(
                repo.finish_job, job_id, "failed",
                error_message=f"워밍업 실패: {type(exc).__name__}",
            )
            return
        if getattr(response, "outcome_code", None) in ERROR_OUTCOMES:
            await asyncio.to_thread(
                repo.finish_job, job_id, "failed",
                error_message=f"워밍업 실패: {response.outcome_code}",
            )
            return

    for item in items:
        if await _is_cancelled(repo, job_id):
            break
        await asyncio.to_thread(repo.mark_item_started, item["item_id"])
        started = time.perf_counter()
        try:
            response = await _run_query(job, item["query_text"], timeout_s)
            fields = build_item_fields(response, top_n)
        except asyncio.TimeoutError:
            fields = {"status": "error", "outcome_code": "timeout",
                      "error_message": f"제한 시간 {timeout_s:g}초 초과"}
        except Exception as exc:
            logger.warning("[eval-batch] job=%s seq=%s 실패 type=%s", job_id, item["seq"], type(exc).__name__)
            fields = {"status": "error", "outcome_code": "system_error",
                      "error_message": f"{type(exc).__name__}: {str(exc)[:300]}"}
        # F-04/F-05: 성공·오류·타임아웃을 같은 요청 경계로 측정한다.
        fields["response_ms"] = int(round((time.perf_counter() - started) * 1000))
        await asyncio.to_thread(repo.save_item_result, job_id, item["item_id"], fields)

    rows = await asyncio.to_thread(repo.list_items, job_id)
    summary = compute_summary(rows)
    if await _is_cancelled(repo, job_id):
        await asyncio.to_thread(repo.finish_job, job_id, "cancelled", summary=summary)
        logger.info("[eval-batch] job=%s 취소(완료 %s건 보존)", job_id, summary["done"])
    else:
        await asyncio.to_thread(repo.finish_job, job_id, "completed", summary=summary)
        logger.info("[eval-batch] job=%s 완료 ok=%s error=%s", job_id, summary["ok"], summary["error"])


# ── 요약 통계 (설계 6.6) ─────────────────────────────────────────────────────

def percentile(values: List[float], pct: float) -> Optional[float]:
    """선형 보간 백분위(엑셀 PERCENTILE.INC와 같은 방식)."""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * pct / 100.0
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def response_stats(values: List[float]) -> Optional[Dict[str, Any]]:
    if not values:
        return None
    return {
        "count": len(values),
        "mean": round(sum(values) / len(values), 1),
        "p50": round(percentile(values, 50), 1),
        "p90": round(percentile(values, 90), 1),
        "p95": round(percentile(values, 95), 1),
        "max": max(values),
        "min": min(values),
    }


def compute_summary(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """F-05: 전체 질의의 시간이 있어야 평균을 확정한다. 오류 시간도 포함한다."""
    done = [r for r in rows if r.get("status") in ("ok", "error")]
    measured = [r for r in done if isinstance(r.get("response_ms"), (int, float))
                and not isinstance(r["response_ms"], bool) and math.isfinite(r["response_ms"])
                and r["response_ms"] >= 0]
    complete = bool(rows) and len(measured) == len(rows)
    ok_rows = [r for r in measured if r.get("status") == "ok"]
    # 2026.11.18(sooyeon.choi) 추가 - 첫 토큰 시간(정상 건 중 답변을 생성한 건만)
    first_token_values = [
        float(ft) for r in ok_rows
        if isinstance(ft := (r.get("timing_json") or {}).get("first_token_ms"), (int, float))
    ]
    by_outcome: Dict[str, List[float]] = {}
    for row in measured:
        by_outcome.setdefault(row.get("outcome_code") or "unknown", []).append(float(row["response_ms"]))
    return {
        "total": len(rows),
        "done": len(done),
        "ok": sum(1 for r in done if r.get("status") == "ok"),
        "error": sum(1 for r in done if r.get("status") == "error"),
        "not_run": len(rows) - len(done),
        "response_ms": response_stats([float(r["response_ms"]) for r in measured]) if complete else None,
        "response_time_status": "complete" if complete else "incomplete",
        "response_time_measured": len(measured),
        "response_time_missing": len(rows) - len(measured),
        "response_ms_success": response_stats([float(r["response_ms"]) for r in ok_rows]),
        "response_ms_by_outcome": {key: response_stats(vals) for key, vals in sorted(by_outcome.items())},
        "first_token_ms": response_stats(first_token_values),
        "recall_at_10": None,  # 정답 근거 확정 후 계산(설계 6.7, 다음 단계)
    }

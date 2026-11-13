"""RAG 평가 자동화 API — /api/eval

admin 인증 필수 (기존 admin_stats.py 패턴 준수).
runner/generator는 지연 import — 평가 패키지 부분 배포 시에도 서버 기동 가능.
(reference app/evaluation/routes.py 이식 — 인증/import 경로 적응 + ①축 필드)
"""

import json
from time import perf_counter
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.evaluation.excel_exporter import (
    build_approved_dataset_workbook,
    build_excel_filename,
    build_run_excel_filename,
    build_run_result_workbook,
)
from app.repositories.evaluation_repository import EvalRepository
from app.evaluation.metric_catalog import present_run_metrics
from app.evaluation.schemas import (
    BulkReviewRequest,
    DatasetCreateRequest,
    EvalOpenAIKeyRequest,
    FinalizeRequest,
    GoldsetImportRequest,
    QaItemUpdateRequest,
    RunCreateRequest,
)
from app.utils.encryption import decrypt_api_key, encrypt_api_key
from app.utils.log.log import LoggingLogger
from app.utils.security import get_current_admin

logger = LoggingLogger().getLogger(__name__)

_METRIC_VERSION = "rule-v1.1"
_ANSWER_NORMALIZATION_VERSION = "v2"

router = APIRouter(prefix="/eval", tags=["Evaluation"])


def _repo() -> EvalRepository:
    return EvalRepository()


def resolve_dataset_generation_openai_key(admin_id: str) -> Optional[str]:
    """관리자가 저장한 데이터셋 생성용 OpenAI 키를 반환한다.

    (chat query.py의 저장 키 재사용 패턴을 평가용으로 이식 — 원문은 DB/응답에 노출하지 않음)
    """
    enc = _repo().get_dataset_generation_openai_key_enc(admin_id)
    if not enc:
        return None
    try:
        return decrypt_api_key(enc)
    except Exception:
        logger.warning("평가 OpenAI 키 복호화 실패: admin=%s", admin_id)
        return None


# ── 데이터셋 생성용 설정 (관리자 OpenAI 키 1회 저장) ───────────────────────

@router.get("/settings/dataset-generation/openai-key")
async def get_dataset_generation_openai_key(admin: dict = Depends(get_current_admin)):
    """저장 여부만 반환(원문 미노출) — chat의 has_api_key 패턴."""
    enc = _repo().get_dataset_generation_openai_key_enc(admin.get("admin_id"))
    return {"has_openai_api_key": enc is not None}


@router.put("/settings/dataset-generation/openai-key")
async def save_dataset_generation_openai_key(
    body: EvalOpenAIKeyRequest, admin: dict = Depends(get_current_admin)
):
    """평가 전용 OpenAI 키를 암호화 저장(관리자 계정 단위, 1회)."""
    _repo().save_dataset_generation_openai_key(
        admin.get("admin_id"), encrypt_api_key(body.openai_api_key)
    )
    return {"has_openai_api_key": True}


@router.delete("/settings/dataset-generation/openai-key")
async def delete_dataset_generation_openai_key(admin: dict = Depends(get_current_admin)):
    _repo().delete_dataset_generation_openai_key(admin.get("admin_id"))
    return {"has_openai_api_key": False}


# ── 데이터셋 (테스트셋 생성/검토) ────────────────────────────────────────────

@router.post("/datasets", status_code=202)
async def create_dataset(
    body: DatasetCreateRequest,
    admin: dict = Depends(get_current_admin),
):
    """테스트셋 자동 생성을 시작한다 (백그라운드). 생성기는 P4에서 추가된다."""
    repo = _repo()
    # 2026.07.24(sychoi) 수정 - OpenAI 생성 시 저장된 평가 전용 키를 서버에서 리졸브.
    #   키 원문은 gen_config_json에 저장하지 않는다(런타임 config에만 주입).
    persist_config = {k: v for k, v in body.gen_config.items() if k != "openai_api_key"}
    runtime_config = dict(body.gen_config)
    if body.gen_config.get("llm_backend") == "openai" and not runtime_config.get("openai_api_key"):
        key = resolve_dataset_generation_openai_key(admin.get("admin_id"))
        if not key:
            raise HTTPException(
                status_code=400,
                detail="OpenAI 생성에는 저장된 데이터셋 생성용 OpenAI 키가 필요합니다. 생성 설정에서 키를 먼저 등록하세요.",
            )
        runtime_config["openai_api_key"] = key
    dataset = repo.create_dataset(
        name=body.name,
        collection_id=body.collection_id,
        gen_config=persist_config,
        created_by=admin.get("admin_id"),
    )
    # 생성 파이프라인은 dataset/generator.py — 지연 import
    from app.evaluation.dataset.generator import start_generation
    start_generation(dataset_id=dataset, gen_config=runtime_config)
    return {"dataset_id": dataset, "status": "generating"}


@router.get("/datasets")
async def list_datasets(_: dict = Depends(get_current_admin)):
    return {"items": _repo().list_datasets()}


@router.get("/datasets/{dataset_id}")
async def get_dataset(dataset_id: int, _: dict = Depends(get_current_admin)):
    dataset = _repo().get_dataset(dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="데이터셋을 찾을 수 없습니다")
    return dataset


@router.get("/datasets/{dataset_id}/approved-items.xlsx")
async def download_approved_dataset_excel(
    dataset_id: int,
    admin: dict = Depends(get_current_admin),
):
    """호출 시점의 승인·수정 QA 전체를 Excel 파일로 내려준다."""
    started_at = perf_counter()
    repo = _repo()
    dataset = repo.get_dataset(dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="평가 데이터셋을 찾을 수 없습니다.")
    items = repo.list_approved_qa_items(dataset_id)
    if not items:
        raise HTTPException(status_code=400, detail="다운로드할 승인 QA 항목이 없습니다.")

    stream = build_approved_dataset_workbook(dataset, items)
    filename = build_excel_filename(dataset)
    ascii_filename = f"eval_dataset_{dataset_id}.xlsx"
    content_disposition = (
        f'attachment; filename="{ascii_filename}"; filename*=UTF-8\'\'{quote(filename)}'
    )
    logger.info(
        "평가 데이터셋 Excel 생성 완료: admin=%s dataset_id=%s items=%s elapsed_ms=%s",
        admin.get("admin_id"), dataset_id, len(items), round((perf_counter() - started_at) * 1000),
    )
    return StreamingResponse(
        stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": content_disposition,
            "Cache-Control": "no-store",
        },
    )


@router.delete("/datasets/{dataset_id}")
async def delete_dataset(dataset_id: int, _: dict = Depends(get_current_admin)):
    """데이터셋을 삭제한다. 확정된 골드셋/그 골드셋으로 실행한 run이 있으면 함께 삭제된다."""
    repo = _repo()
    if not repo.get_dataset(dataset_id):
        raise HTTPException(status_code=404, detail="데이터셋을 찾을 수 없습니다")
    repo.delete_dataset(dataset_id)
    return {"deleted": True}


@router.get("/datasets/{dataset_id}/items")
async def list_qa_items(
    dataset_id: int,
    status: Optional[str] = Query(default=None),
    type: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    _: dict = Depends(get_current_admin),
):
    return _repo().list_qa_items(
        dataset_id, review_status=status, question_type=type,
        page=page, page_size=page_size,
    )


@router.patch("/items/{qa_id}")
async def update_qa_item(
    qa_id: int,
    body: QaItemUpdateRequest,
    admin: dict = Depends(get_current_admin),
):
    repo = _repo()
    if not repo.get_qa_item(qa_id):
        raise HTTPException(status_code=404, detail="QA 항목을 찾을 수 없습니다")
    repo.update_qa_item(
        qa_id,
        question=body.question,
        gold_answer=body.gold_answer,
        gold_chunk_ids=body.gold_chunk_ids,
        gold_document_ids=body.gold_document_ids,
        expected_behavior=body.expected_behavior,
        tags=body.tags,
        review_status="edited",
        reviewed_by=admin.get("admin_id"),
    )
    return {"qa_id": qa_id, "review_status": "edited"}


@router.post("/items/{qa_id}/approve")
async def approve_qa_item(qa_id: int, admin: dict = Depends(get_current_admin)):
    repo = _repo()
    if not repo.get_qa_item(qa_id):
        raise HTTPException(status_code=404, detail="QA 항목을 찾을 수 없습니다")
    repo.update_qa_item(qa_id, review_status="approved", reviewed_by=admin.get("admin_id"))
    return {"qa_id": qa_id, "review_status": "approved"}


@router.post("/items/{qa_id}/reject")
async def reject_qa_item(qa_id: int, admin: dict = Depends(get_current_admin)):
    repo = _repo()
    if not repo.get_qa_item(qa_id):
        raise HTTPException(status_code=404, detail="QA 항목을 찾을 수 없습니다")
    repo.update_qa_item(qa_id, review_status="rejected", reviewed_by=admin.get("admin_id"))
    return {"qa_id": qa_id, "review_status": "rejected"}


@router.post("/items/bulk-review")
async def bulk_review(body: BulkReviewRequest, admin: dict = Depends(get_current_admin)):
    repo = _repo()
    status = "approved" if body.action == "approve" else "rejected"
    for qa_id in body.qa_ids:
        repo.update_qa_item(qa_id, review_status=status, reviewed_by=admin.get("admin_id"))
    return {"updated": len(body.qa_ids), "review_status": status}


@router.post("/datasets/{dataset_id}/finalize")
async def finalize_dataset(
    dataset_id: int,
    body: FinalizeRequest,
    admin: dict = Depends(get_current_admin),
):
    repo = _repo()
    if not repo.get_dataset(dataset_id):
        raise HTTPException(status_code=404, detail="데이터셋을 찾을 수 없습니다")
    goldset_id = repo.create_goldset(dataset_id, note=body.note, created_by=admin.get("admin_id"))
    if goldset_id is None:
        raise HTTPException(status_code=400, detail="승인된 QA 항목이 없습니다")
    return {"goldset_id": goldset_id}


# ── 골드셋 ──────────────────────────────────────────────────────────────────

@router.get("/goldsets")
async def list_goldsets(
    dataset_id: Optional[int] = Query(default=None),
    _: dict = Depends(get_current_admin),
):
    return {"items": _repo().list_goldsets(dataset_id)}


@router.post("/goldsets/import")
async def import_goldset(body: GoldsetImportRequest, admin: dict = Depends(get_current_admin)):
    """수동 JSON 골드셋 등록 (검증·초기 구축용)."""
    repo = _repo()
    if not repo.get_dataset(body.dataset_id):
        raise HTTPException(status_code=404, detail="데이터셋을 찾을 수 없습니다")
    items = [item.model_dump() for item in body.items]
    # 스냅샷 형식 통일: DB 컬럼과 동일한 JSON 문자열 필드로 저장
    for i, item in enumerate(items):
        item["qa_id"] = -(i + 1)  # 수동 항목은 음수 qa_id로 구분
        item["gold_chunk_ids"] = json.dumps(item["gold_chunk_ids"], ensure_ascii=False)
        item["gold_document_ids"] = json.dumps(item["gold_document_ids"], ensure_ascii=False)
        item["gold_chunk_texts"] = "[]"
        item["tags"] = json.dumps(item.get("tags", []), ensure_ascii=False)
    goldset_id = repo.import_goldset(
        body.dataset_id, items, note=body.note, created_by=admin.get("admin_id")
    )
    return {"goldset_id": goldset_id, "item_count": len(items)}


# ── 평가 실행 ────────────────────────────────────────────────────────────────

@router.post("/runs", status_code=202)
async def create_run(body: RunCreateRequest, admin: dict = Depends(get_current_admin)):
    repo = _repo()
    goldset = repo.get_goldset(body.goldset_id)
    if not goldset:
        raise HTTPException(status_code=404, detail="골드셋을 찾을 수 없습니다")

    items = json.loads(goldset["items_snapshot_json"])
    config = body.config.model_dump()
    config["metric_version"] = _METRIC_VERSION
    if body.scope == "full":
        from app.core.config import get_settings

        settings = get_settings()
        embedding_model = getattr(settings, "embedding_model_name", "unknown")
        config["answer_correctness_primary"] = settings.answer_correctness_primary
        config["answer_correctness_fallback_chain"] = settings.answer_correctness_fallback_chain
        config["answer_correctness"] = {
            "method": "embedding_cosine",
            "embedding_model": embedding_model,
            # 별도 배포 hash 설정이 생기기 전까지 모델 식별자를 버전 snapshot으로 사용한다.
            "model_version": embedding_model,
            "normalization_version": _ANSWER_NORMALIZATION_VERSION,
        }
        # 2026.08.03(sooyeon.choi) 수정 - rule-v1.1 공식 점수와 병행할 rule-v2 shadow 조건 고정
        config["answer_correctness_v2"] = {
            "enabled": True,
            "mode": "shadow",
            "method": "sentence_alignment_f1",
            "metric_version": "rule-v2-shadow.2",
            "embedding_model": embedding_model,
            "model_version": embedding_model,
            "normalization_version": _ANSWER_NORMALIZATION_VERSION,
            "sentence_split_version": "ko-rule-v2",
            "min_sentence_chars": settings.answer_correctness_v2_min_sentence_chars,
            "max_sentences_per_answer": settings.answer_correctness_v2_max_sentences_per_answer,
            # 2026.08.03(sooyeon.choi) 수정 - 반복 문장과 과도한 형식 문장 패널티 완화 조건 고정
            "semantic_dedupe_threshold": settings.answer_correctness_v2_dedupe_threshold,
            "precision_candidate_ratio": settings.answer_correctness_v2_precision_candidate_ratio,
        }
        config["answer_correctness_f2"] = {
            "enabled": True,
            "mode": "shadow",
            "method": "sentence_alignment_f2",
            "metric_version": "f2.1",
            "beta": 2.0,
            "source_metric": "answer.correctness.v2",
        }
        config["answer_correctness_judge"] = {
            "enabled": True,
            "method": "ragas_answer_accuracy",
            "metric_version": "answer_accuracy.1",
            "backend": settings.answer_correctness_judge_backend,
            "model": settings.answer_correctness_judge_model,
            "temperature": settings.answer_correctness_judge_temperature,
        }

    run_type = body.scope
    run_id = repo.create_run(
        goldset_id=body.goldset_id,
        run_type=run_type,
        config=config,
        total=len(items),
        created_by=admin.get("admin_id"),
    )
    # 러너는 runner/eval_runner.py — 지연 import
    from app.evaluation.runner.eval_runner import start_run
    start_run(run_id=run_id)
    return {
        "run_id": run_id,
        "scope": body.scope,
        "status": "pending",
        "total": len(items),
    }


@router.get("/runs")
async def list_runs(
    goldset_id: Optional[int] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    _: dict = Depends(get_current_admin),
):
    items = _repo().list_runs(goldset_id, limit)
    for item in items:
        item["scope"] = item.get("run_type")
    return {"items": items}


@router.get("/runs/{run_id}")
async def get_run(run_id: int, _: dict = Depends(get_current_admin)):
    repo = _repo()
    run = repo.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="실행을 찾을 수 없습니다")
    run["scope"] = run.get("run_type")
    metrics = repo.get_run_metrics(run_id)
    config = json.loads(run.get("config_json") or "{}")
    run["config"] = config
    run["metric_version"] = config.get("metric_version", "legacy")
    run["legacy"] = "metric_version" not in config
    run["metrics"] = metrics
    run.update(present_run_metrics(run["scope"], config, metrics))
    return run


@router.get("/runs/{run_id}/results.xlsx")
async def download_run_results_excel(
    run_id: int,
    admin: dict = Depends(get_current_admin),
):
    """완료된 평가 실행의 집계 지표와 전체 항목 결과를 Excel로 내려준다."""
    started_at = perf_counter()
    repo = _repo()
    run = repo.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="평가 실행을 찾을 수 없습니다.")
    if run.get("status") != "completed":
        raise HTTPException(status_code=409, detail="완료된 평가 실행만 다운로드할 수 있습니다.")

    metrics = repo.get_run_metrics(run_id)
    items = repo.list_item_results_for_export(run_id)
    if not metrics or not items:
        raise HTTPException(status_code=400, detail="다운로드할 평가 결과가 없습니다.")

    config = json.loads(run.get("config_json") or "{}")
    presented = present_run_metrics(run.get("run_type", "retrieval"), config, metrics)
    stream = build_run_result_workbook(
        run,
        presented["primary_metrics"],
        presented["secondary_metrics"],
        items,
    )
    filename = build_run_excel_filename(run)
    content_disposition = (
        f'attachment; filename="eval_run_{run_id}.xlsx"; filename*=UTF-8\'\'{quote(filename)}'
    )
    logger.info(
        "평가 실행 Excel 생성 완료: admin=%s run_id=%s items=%s elapsed_ms=%s",
        admin.get("admin_id"), run_id, len(items), round((perf_counter() - started_at) * 1000),
    )
    return StreamingResponse(
        stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": content_disposition,
            "Cache-Control": "no-store",
        },
    )


@router.delete("/runs/{run_id}")
async def delete_run(run_id: int, _: dict = Depends(get_current_admin)):
    repo = _repo()
    run = repo.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="실행을 찾을 수 없습니다")
    if run["status"] in ("pending", "running"):
        raise HTTPException(status_code=409, detail="실행 중인 run은 삭제할 수 없습니다. 먼저 취소해주세요.")
    repo.delete_run(run_id)
    return {"deleted": True}


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: int, _: dict = Depends(get_current_admin)):
    from app.evaluation.runner.run_registry import request_cancel
    if not request_cancel(run_id):
        raise HTTPException(status_code=404, detail="실행 중인 run이 아닙니다")
    return {"run_id": run_id, "status": "cancelling"}


@router.get("/runs/{run_id}/results")
async def list_run_results(
    run_id: int,
    status: Optional[str] = Query(default=None),
    type: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    _: dict = Depends(get_current_admin),
):
    result = _repo().list_item_results(
        run_id, status=status, question_type=type, page=page, page_size=page_size
    )
    for item in result["items"]:
        raw = item.get("metric_status_json")
        item["metrics"] = json.loads(raw) if raw else {}
    return result


# ── 대시보드 ────────────────────────────────────────────────────────────────

@router.get("/dashboard/trend")
async def dashboard_trend(
    metric_keys: str = Query(..., description="쉼표 구분 지표 키"),
    collection_id: Optional[int] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    _: dict = Depends(get_current_admin),
):
    keys = [k.strip() for k in metric_keys.split(",") if k.strip()]
    if not keys:
        raise HTTPException(status_code=400, detail="metric_keys가 비어 있습니다")
    return {"items": _repo().get_metrics_trend(keys, collection_id, limit)}


@router.get("/dashboard/compare")
async def dashboard_compare(
    run_ids: str = Query(..., description="쉼표 구분 run ID"),
    _: dict = Depends(get_current_admin),
):
    repo = _repo()
    result = []
    for raw in run_ids.split(","):
        raw = raw.strip()
        if not raw:
            continue
        run_id = int(raw)
        run = repo.get_run(run_id)
        if run:
            config = json.loads(run["config_json"])
            metrics = repo.get_run_metrics(run_id)
            result.append({
                "run_id": run_id,
                "run_type": run["run_type"],
                "created_at": run["created_at"],
                "config": config,
                "metric_version": config.get("metric_version", "legacy"),
                "legacy": "metric_version" not in config,
                "metrics": metrics,
                **present_run_metrics(run["run_type"], config, metrics),
            })
    return {"items": result}


# ── 청크 검색 (QA 편집 시 gold 청크 교체용) ─────────────────────────────────

@router.get("/chunks/search")
async def search_chunks(
    q: str = Query(..., min_length=1),
    collection_name: str = Query(...),
    top_k: int = Query(default=10, ge=1, le=50),
    _: dict = Depends(get_current_admin),
):
    from app.evaluation.adapters.retrieval_adapter import EvalRetriever
    retriever = EvalRetriever()
    hits = await retriever.search_rrf(q, top_k, collection_name)
    return {
        "items": [
            {
                "chunk_id": chunk_id,
                "score": score,
                "document_id": payload.get("document_id"),
                "original_filename": payload.get("original_filename"),
                "section_title": payload.get("section_title"),
                "text": (payload.get("text") or "")[:500],
            }
            for chunk_id, score, payload in hits
        ]
    }

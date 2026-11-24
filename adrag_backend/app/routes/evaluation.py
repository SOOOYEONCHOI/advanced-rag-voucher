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
    build_testset_filename,
    build_testset_workbook,
)
from app.repositories.evaluation_repository import EvalRepository
from app.evaluation.metric_catalog import present_run_metrics
from app.evaluation.schemas import (
    BulkReviewRequest,
    DatasetCreateRequest,
    DatasetMergeRequest,
    DatasetQueryIdPrefixRequest,
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

# 2026.11.17(sooyeon.choi) 수정 - 지표 정리(Hit@N 주 지표, F2 단일, 화이트리스트 집계)로 버전 올림
_METRIC_VERSION = "rule-v1.3"
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


@router.get("/settings/dataset-generation/models")
async def list_dataset_generation_models(_: dict = Depends(get_current_admin)):
    """2026.11.18(sooyeon.choi) 추가 - 데이터셋 생성에 쓸 수 있는 vLLM 모델(모델명·기본 여부·켜짐 여부, 주소 제외)."""
    from app.evaluation.adapters.gen_model_catalog import list_generation_models
    return {"items": await list_generation_models()}


# ── 데이터셋 (테스트셋 생성/검토) ────────────────────────────────────────────

@router.post("/datasets", status_code=202)
async def create_dataset(
    body: DatasetCreateRequest,
    admin: dict = Depends(get_current_admin),
):
    """테스트셋 자동 생성을 시작한다 (백그라운드). 생성기는 P4에서 추가된다."""
    repo = _repo()
    # 2026.11.19(sooyeon.choi) 추가 - 생성 방식 확인(기본 typed = 기존 유형별 생성)
    if body.gen_config.get("generation_mode", "typed") not in ("typed", "law_article", "single_section"):
        raise HTTPException(status_code=400, detail="생성 방식은 typed, law_article, single_section 중 하나입니다.")
    # 2026.07.24(sychoi) 수정 - OpenAI 생성 시 저장된 평가 전용 키를 서버에서 리졸브.
    #   키 원문은 gen_config_json에 저장하지 않는다(런타임 config에만 주입).
    persist_config = {k: v for k, v in body.gen_config.items() if k not in ("openai_api_key", "vllm_api_url")}
    # 2026.11.18(sooyeon.choi) 수정 - vllm_api_url은 요청에서 받지 않는다(아래에서 서버 설정으로만 채움)
    runtime_config = {k: v for k, v in body.gen_config.items() if k != "vllm_api_url"}
    if body.gen_config.get("llm_backend") == "openai" and not runtime_config.get("openai_api_key"):
        key = resolve_dataset_generation_openai_key(admin.get("admin_id"))
        if not key:
            raise HTTPException(
                status_code=400,
                detail="OpenAI 생성에는 저장된 데이터셋 생성용 OpenAI 키가 필요합니다. 생성 설정에서 키를 먼저 등록하세요.",
            )
        runtime_config["openai_api_key"] = key
    # 2026.11.18(sooyeon.choi) 추가 - vLLM 생성 모델 선택. 모델명으로 서버 주소를 찾고(화면에서 주소를 받지 않음),
    #   켜져 있는지 확인한다. 주소는 런타임 config에만 넣고, 모델명은 gen_config_json에 남긴다.
    if body.gen_config.get("llm_backend", "vllm") == "vllm":
        from app.evaluation.adapters.gen_model_catalog import (
            generation_model_candidates,
            is_model_served,
            resolve_generation_model,
        )
        requested = body.gen_config.get("llm_model")
        candidate = (
            resolve_generation_model(requested) if requested else generation_model_candidates()[0]
        )
        if candidate is None:
            raise HTTPException(status_code=400, detail="선택한 생성 모델이 목록에 없습니다.")
        if requested and not candidate["is_default"] and not await is_model_served(candidate):
            raise HTTPException(
                status_code=400,
                detail=f"생성 모델({candidate['model']}) 서버가 응답하지 않습니다. 모델 서버를 켠 뒤 다시 시도하세요.",
            )
        persist_config["llm_model"] = candidate["model"]
        runtime_config["llm_model"] = candidate["model"]
        runtime_config["vllm_api_url"] = candidate["url"]
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


# ── 2026.11.20(sooyeon.choi) 수정 - 합본 데이터셋 (eval-merged-dataset-design-v1.0.md) ──────────────

def _ensure_not_merged(repo: EvalRepository, dataset_id: int) -> None:
    """합본 문항은 원본에서 수정·확정한 뒤 합본을 다시 만든다(합본 직접 수정 금지)."""
    from app.evaluation.dataset.merge import is_merged_dataset

    dataset = repo.get_dataset(dataset_id)
    if dataset and is_merged_dataset(dataset):
        raise HTTPException(
            status_code=409,
            detail="합본 데이터셋의 문항은 수정할 수 없습니다. 원본 데이터셋에서 수정·확정한 뒤 합본을 다시 만들어 주세요.",
        )


def _ensure_item_not_merged(repo: EvalRepository, qa_id: int) -> dict:
    item = repo.get_qa_item(qa_id)
    if not item:
        raise HTTPException(status_code=404, detail="QA 항목을 찾을 수 없습니다")
    _ensure_not_merged(repo, item["dataset_id"])
    return item


def _attach_query_ids(repo: EvalRepository, run: dict, items: list) -> None:
    """결과 항목에 질의ID·법령(합본)을 붙인다. 질의ID는 시험 데이터셋 Excel과 같은 규칙."""
    from app.evaluation.dataset.merge import source_query_ids

    dataset = repo.get_dataset(run["dataset_id"]) if run.get("dataset_id") else None
    computed = source_query_ids(dataset, repo.qa_snapshot_items(run["run_id"])) if dataset else {}
    for item in items:
        meta = item.get("source_meta_json")
        meta = json.loads(meta) if isinstance(meta, str) and meta else (meta or {})
        meta = meta if isinstance(meta, dict) else {}
        item["query_id"] = meta.get("query_id") or computed.get(item.get("qa_id"))
        item["law_label"] = meta.get("law_label")


@router.post("/datasets/merge", status_code=201)
async def merge_datasets(body: DatasetMergeRequest, admin: dict = Depends(get_current_admin)):
    """확정 데이터셋 여러 개의 최신 골드셋 문항을 이어 붙여 합본 데이터셋(바로 확정 v1)을 만든다."""
    from app.core.config import get_settings
    from app.evaluation.dataset.merge import (
        MergeError,
        build_merged_items,
        is_merged_dataset,
        merged_config,
    )

    if not get_settings().eval_dataset_merge_enabled:
        raise HTTPException(status_code=404, detail="Not Found")
    if len(set(body.dataset_ids)) != len(body.dataset_ids):
        raise HTTPException(status_code=400, detail="같은 데이터셋을 두 번 고를 수 없습니다.")
    repo = _repo()
    sources = []
    for dataset_id in body.dataset_ids:
        dataset = repo.get_dataset(dataset_id)
        if not dataset:
            raise HTTPException(status_code=404, detail=f"데이터셋({dataset_id})을 찾을 수 없습니다.")
        if is_merged_dataset(dataset):
            raise HTTPException(status_code=400, detail=f"합본 데이터셋({dataset['name']})은 다시 합칠 수 없습니다.")
        if not dataset.get("qdrant_name"):
            raise HTTPException(status_code=400, detail=f"데이터셋({dataset['name']})의 컬렉션을 찾을 수 없습니다.")
        goldset = repo.latest_goldset(dataset_id)
        if not goldset:
            raise HTTPException(status_code=400, detail=f"데이터셋({dataset['name']})에 확정본(골드셋)이 없습니다. 먼저 확정해 주세요.")
        sources.append({"dataset": dataset, "goldset": goldset, "items": json.loads(goldset["items_snapshot_json"])})
    try:
        items = build_merged_items(sources)
    except MergeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not items:
        raise HTTPException(status_code=400, detail="합칠 문항이 없습니다.")
    note = " + ".join(f"{s['dataset']['name']} v{s['goldset']['version']}" for s in sources)
    result = repo.create_merged_dataset(
        name=body.name.strip(),
        collection_id=sources[0]["dataset"]["collection_id"],
        gen_config=merged_config(sources),
        items=items,
        note=f"합본: {note}"[:500],
        created_by=admin.get("admin_id"),
    )
    logger.info(
        "합본 데이터셋 생성: admin=%s dataset_id=%s sources=%s items=%s",
        admin.get("admin_id"), result["dataset_id"], body.dataset_ids, result["item_count"],
    )
    return result


@router.get("/datasets")
async def list_datasets(_: dict = Depends(get_current_admin)):
    from app.core.config import get_settings

    # 2026.11.20(sooyeon.choi) 수정 - 화면의 [합본 데이터셋 만들기] 버튼 표시 여부
    return {"items": _repo().list_datasets(), "merge_enabled": get_settings().eval_dataset_merge_enabled}


@router.get("/datasets/{dataset_id}")
async def get_dataset(dataset_id: int, _: dict = Depends(get_current_admin)):
    dataset = _repo().get_dataset(dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="데이터셋을 찾을 수 없습니다")
    return dataset


# 2026.11.23(sooyeon.choi) 추가 - 질의ID 접두어 변경(확정 데이터셋도 가능, 합본 충돌 해소용)
@router.patch("/datasets/{dataset_id}/query-id-prefix")
async def update_dataset_query_id_prefix(
    dataset_id: int,
    body: DatasetQueryIdPrefixRequest,
    admin: dict = Depends(get_current_admin),
):
    """접두어만 바꾼다. 질의ID는 다운로드·결과 조회 때 다시 계산되므로 문항·골드셋은 그대로다.
    합본은 만들 때 원본 질의ID를 문항에 저장하므로 바꿀 수 없다."""
    from app.evaluation.dataset.merge import is_merged_dataset
    from app.evaluation.excel_exporter import normalize_query_id_prefix

    repo = _repo()
    dataset = repo.get_dataset(dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="데이터셋을 찾을 수 없습니다")
    if is_merged_dataset(dataset):
        raise HTTPException(
            status_code=409,
            detail="합본 데이터셋의 질의ID는 원본에서 가져온 값이라 바꿀 수 없습니다. 원본 접두어를 바꾼 뒤 합본을 다시 만들어 주세요.",
        )
    raw = (body.query_id_prefix or "").strip()
    prefix = normalize_query_id_prefix(raw)
    if raw and not prefix:
        raise HTTPException(status_code=400, detail="접두어에는 한글·영문·숫자·_·- 만 쓸 수 있습니다.")
    repo.update_dataset_query_id_prefix(dataset_id, prefix)
    logger.info("질의ID 접두어 변경: admin=%s dataset_id=%s prefix=%s", admin.get("admin_id"), dataset_id, prefix or "Q")
    return {"dataset_id": dataset_id, "query_id_prefix": prefix or "Q"}


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


@router.get("/datasets/{dataset_id}/test-set.xlsx")
async def download_testset_excel(
    dataset_id: int,
    admin: dict = Depends(get_current_admin),
):
    """2026.11.19(sooyeon.choi) 추가 - 시험 데이터셋(질의·정답 근거·요약) Excel. 승인·수정 문항만 포함."""
    repo = _repo()
    dataset = repo.get_dataset(dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="평가 데이터셋을 찾을 수 없습니다.")
    items = repo.list_approved_qa_items(dataset_id)
    if not items:
        raise HTTPException(status_code=400, detail="다운로드할 승인 QA 항목이 없습니다.")
    document_ids = set()
    for item in items:
        meta = item.get("source_meta_json")
        meta = json.loads(meta) if isinstance(meta, str) else (meta or {})
        if isinstance(meta, dict) and meta.get("document_id"):
            document_ids.add(str(meta["document_id"]))
    stream = build_testset_workbook(dataset, items, repo.document_versions(sorted(document_ids)))
    filename = build_testset_filename(dataset)
    content_disposition = (
        f'attachment; filename="eval_testset_{dataset_id}.xlsx"; filename*=UTF-8\'\'{quote(filename)}'
    )
    logger.info("시험 데이터셋 Excel 생성: admin=%s dataset_id=%s items=%s", admin.get("admin_id"), dataset_id, len(items))
    return StreamingResponse(
        stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": content_disposition, "Cache-Control": "no-store"},
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
    _ensure_item_not_merged(repo, qa_id)  # 2026.11.20(sooyeon.choi) 수정 - 합본 문항 수정 금지
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
    _ensure_item_not_merged(repo, qa_id)  # 2026.11.20(sooyeon.choi) 수정 - 합본 문항 수정 금지
    repo.update_qa_item(qa_id, review_status="approved", reviewed_by=admin.get("admin_id"))
    return {"qa_id": qa_id, "review_status": "approved"}


async def _regeneration_llm_config(persisted: dict, admin_id: Optional[str]) -> dict:
    """2026.11.19(sooyeon.choi) 추가 - 데이터셋 생성 때 쓴 모델로 다시 생성(주소·키는 서버에서만 채움)."""
    config = {k: v for k, v in (persisted or {}).items() if k not in ("openai_api_key", "vllm_api_url")}
    if config.get("llm_backend") == "openai":
        key = resolve_dataset_generation_openai_key(admin_id)
        if not key:
            raise HTTPException(status_code=400, detail="저장된 데이터셋 생성용 OpenAI 키가 없습니다.")
        config["openai_api_key"] = key
        return config
    from app.evaluation.adapters.gen_model_catalog import (
        generation_model_candidates,
        is_model_served,
        resolve_generation_model,
    )
    model = config.get("llm_model")
    candidate = resolve_generation_model(model) if model else generation_model_candidates()[0]
    if candidate is None:
        raise HTTPException(status_code=400, detail=f"생성 모델({model})이 목록에 없습니다.")
    if not candidate["is_default"] and not await is_model_served(candidate):
        raise HTTPException(
            status_code=400,
            detail=f"생성 모델({candidate['model']}) 서버가 응답하지 않습니다. 모델 서버를 켠 뒤 다시 시도하세요.",
        )
    config["llm_model"] = candidate["model"]
    config["vllm_api_url"] = candidate["url"]
    return config


@router.post("/items/{qa_id}/regenerate")
async def regenerate_qa_item(qa_id: int, admin: dict = Depends(get_current_admin)):
    """2026.11.19(sooyeon.choi) 추가 - '검색 확인 필요' 문항을 같은 조항(섹션)으로 다시 생성.

    법령 조항·일반 문서 방식으로 만든 문항만, 사람이 누를 때 1회 실행한다. 결과는 검수 대기로 돌아간다.
    """
    repo = _repo()
    item = _ensure_item_not_merged(repo, qa_id)  # 2026.11.20(sooyeon.choi) 수정 - 합본 문항 다시 생성 금지
    if item.get("question_type") not in ("law", "general"):
        raise HTTPException(status_code=400, detail="법령 조항·일반 문서 방식으로 생성한 문항만 다시 생성할 수 있습니다.")
    if item.get("self_valid_rank") is not None:
        raise HTTPException(status_code=409, detail="'검색 확인 필요' 문항만 다시 생성할 수 있습니다.")
    dataset = repo.get_dataset(item["dataset_id"])
    if not dataset or not dataset.get("qdrant_name"):
        raise HTTPException(status_code=400, detail="데이터셋의 컬렉션을 찾을 수 없습니다.")
    if dataset.get("status") == "generating":
        raise HTTPException(status_code=409, detail="데이터셋 생성 중에는 다시 생성할 수 없습니다.")
    persisted = dataset.get("gen_config_json")
    persisted = json.loads(persisted) if isinstance(persisted, str) else (persisted or {})
    config = await _regeneration_llm_config(persisted, admin.get("admin_id"))

    from app.evaluation.dataset.generator import RegenerationError, regenerate_single_source_item
    try:
        return await regenerate_single_source_item(repo, item, dataset["qdrant_name"], config)
    except RegenerationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/items/{qa_id}/reject")
async def reject_qa_item(qa_id: int, admin: dict = Depends(get_current_admin)):
    repo = _repo()
    _ensure_item_not_merged(repo, qa_id)  # 2026.11.20(sooyeon.choi) 수정 - 합본 문항 수정 금지
    repo.update_qa_item(qa_id, review_status="rejected", reviewed_by=admin.get("admin_id"))
    return {"qa_id": qa_id, "review_status": "rejected"}


@router.post("/items/bulk-review")
async def bulk_review(body: BulkReviewRequest, admin: dict = Depends(get_current_admin)):
    repo = _repo()
    status = "approved" if body.action == "approve" else "rejected"
    # 2026.11.20(sooyeon.choi) 수정 - 합본 문항 수정 금지(하나라도 있으면 전체 거부)
    for qa_id in body.qa_ids:
        item = repo.get_qa_item(qa_id)
        if item:
            _ensure_not_merged(repo, item["dataset_id"])
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
    _ensure_not_merged(repo, dataset_id)  # 2026.11.20(sooyeon.choi) 수정 - 합본은 만들 때 확정(v1)
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
    # 2026.11.20(sooyeon.choi) 수정 - 합본 문항의 검색 컬렉션이 모두 있는지 실행 전에 확인
    from app.evaluation.runner.eval_runner import item_collection
    from app.repositories.collection_repository import CollectionRepository

    #   단독 데이터셋 문항(qdrant_name 없음)은 기존처럼 확인하지 않는다
    needed = {item_collection(item, "") for item in items} - {""}
    missing = sorted(name for name in needed if not CollectionRepository().get_by_qdrant_name(name))
    if missing:
        raise HTTPException(status_code=400, detail=f"검색 컬렉션을 찾을 수 없습니다: {', '.join(missing)}")
    config = body.config.model_dump()
    config["metric_version"] = _METRIC_VERSION
    if body.scope == "full":
        from app.core.config import get_settings

        settings = get_settings()
        embedding_model = getattr(settings, "embedding_model_name", "unknown")
        # 2026.11.17(sooyeon.choi) 삭제 - answer_correctness_primary·fallback_chain, v1(embedding_cosine)·judge snapshot
        #   Answer Correctness는 F2 한 종류로 고정. 아래 v2(문장 정렬)는 F2 계산 입력 조건이다.
        config["answer_correctness_v2"] = {
            "enabled": True,
            "mode": "f2_input",
            "method": "sentence_alignment_f1",
            "metric_version": "rule-v2.3",
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
            "mode": "primary",
            "method": "sentence_alignment_f2",
            "metric_version": "f2.1",
            "beta": 2.0,
            "source_metric": "answer_correctness_v2",
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
    _attach_query_ids(repo, run, items)  # 2026.11.20(sooyeon.choi) 수정 - 질의ID·법령 열
    stream = build_run_result_workbook(
        run,
        presented["primary_metrics"],
        presented["secondary_metrics"],
        items,
        law_metrics=presented["law_metrics"],
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
    law: Optional[str] = Query(default=None, max_length=100),  # 2026.11.20(sooyeon.choi) 수정 - 합본 법령 필터
    _: dict = Depends(get_current_admin),
):
    repo = _repo()
    result = repo.list_item_results(
        run_id, status=status, question_type=type, page=page, page_size=page_size, law=law
    )
    # 2026.11.20(sooyeon.choi) 수정 - 항목 표 질의ID·법령 열
    run = repo.get_run(run_id)
    if run:
        _attach_query_ids(repo, run, result["items"])
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

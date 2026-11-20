"""평가 배치 실행 오케스트레이터.

- asyncio.create_task 기반 백그라운드 실행 (run_registry로 추적/취소)
- 항목 단위 Semaphore 동시성 제어, 항목별 부분실패 허용
- 진행률은 항목 완료 시마다 DB 갱신
- run_type:
    retrieval  — 채널별 검색 + 리랭크만 (LLM 미사용, 저비용)
    full       — 검색 + 규칙 기반 답변/Citation 평가

집계 세그먼트: all + type:{question_type} + tag:{tag} (①축 한국어 세그먼트 보존).
(reference app/evaluation/runner/eval_runner.py 이식 + tag 세그먼트 확장)
"""

import asyncio
import json
import time
from collections import defaultdict
from typing import Any, Dict, List, Set

from app.evaluation.metric_catalog import (
    ALL_DENOMINATOR_KEYS,
    FIRST_TOKEN_KEY,
    JUDGE_ACCURACY_KEY,
    RESPONSE_TIME_KEY,
    metric_catalog,
)
from app.evaluation.metrics.models import MetricAggregate, MetricResult
from app.evaluation.metrics.retrieval_metrics import (
    compute_channel_metrics,
    is_aggregated_retrieval_metric,
)
from app.repositories.evaluation_repository import EvalRepository
from app.evaluation.runner import run_registry
from app.utils.log.log import LoggingLogger

logger = LoggingLogger().getLogger(__name__)

_DEFAULT_CHANNELS = ["dense", "kiwi_bm25", "rrf"]   # 기본 평가 채널
_K_VALUES = (1, 3, 5, 10)
_SKIP_RETRIEVAL_BEHAVIORS = {"guardrail", "permission_denied"}
_CITATION_METRIC_KEYS = ("correctness", "completeness")

def start_run(run_id: int) -> None:
    """이벤트 루프에 run 실행 태스크를 등록한다 (라우터에서 호출)."""
    task = asyncio.create_task(_execute_run(run_id))
    run_registry.register(run_id, task)


async def _execute_run(run_id: int) -> None:
    repo = EvalRepository()
    try:
        run = repo.get_run(run_id)
        if not run:
            return
        goldset = repo.get_goldset(run["goldset_id"])
        items = json.loads(goldset["items_snapshot_json"])
        config = json.loads(run["config_json"])
        collection_name = goldset.get("qdrant_name")
        if not collection_name:
            repo.update_run_status(run_id, "failed", "컬렉션(qdrant_name)을 찾을 수 없습니다")
            return

        repo.update_run_status(run_id, "running")
        logger.info(f"[eval] run {run_id} 시작 — {len(items)}건, type={run['run_type']}")

        run_type = run["run_type"]
        # 시험 4: 답변 생성 시간이 포함된 평가는 질의를 순차 실행한다.
        semaphore = asyncio.Semaphore(1 if run_type in ("full", "end_to_end") else int(config.get("concurrency", 3)))

        async def _process(item: Dict[str, Any]) -> None:
            async with semaphore:
                if run_registry.is_cancel_requested(run_id):
                    return
                qa_id = item.get("qa_id", 0)
                started = time.monotonic()
                try:
                    # 2026.11.20(sooyeon.choi) 수정 - 합본 문항은 원본 컬렉션에서 검색(없으면 골드셋 컬렉션, 기존 동작)
                    fields = await _evaluate_item(item, run_type, config, item_collection(item, collection_name))
                    repo.insert_item_result(run_id, qa_id, **fields)
                except Exception as e:
                    logger.error(f"[eval] run {run_id} qa {qa_id} 실패: {e}")
                    repo.insert_item_result(
                        run_id, qa_id, status="error", error_message=str(e)[:500],
                        latency_ms=int((time.monotonic() - started) * 1000),
                    )
                finally:
                    repo.increment_run_progress(run_id)

        await asyncio.gather(*[_process(item) for item in items])

        if run_registry.is_cancel_requested(run_id):
            repo.update_run_status(run_id, "cancelled")
            logger.info(f"[eval] run {run_id} 취소됨")
        else:
            _aggregate_and_save_metrics(repo, run_id, items)
            repo.update_run_status(run_id, "completed")
            logger.info(f"[eval] run {run_id} 완료")
    except Exception as e:
        logger.error(f"[eval] run {run_id} 실행 오류: {e}")
        repo.update_run_status(run_id, "failed", str(e)[:500])
    finally:
        run_registry.unregister(run_id)

# 각 QA 마다 실행
async def _evaluate_item(
    item: Dict[str, Any],
    run_type: str,
    config: Dict[str, Any],
    collection_name: str,
) -> Dict[str, Any]:
    """QA 1건을 평가하고 tb_eval_item_results 필드 dict를 반환한다."""
    fields: Dict[str, Any] = {"status": "ok"}
    started = time.monotonic()

    # 평가 유형 분기
    if run_type == "retrieval":
        fields["retrieval_json"] = await _evaluate_retrieval(item, config, collection_name)

    if run_type in ("end_to_end", "full"):
        # 운영 RAG 1회 실행 결과로 검색·답변·Citation을 함께 평가한다.
        from app.evaluation.runner.e2e_evaluator import evaluate_end_to_end
        # 운영 RAG 파이프라인 실행
        e2e_fields = await evaluate_end_to_end(item, config, collection_name)
        fields.update(e2e_fields)

    # 2026.11.17(sooyeon.choi) 수정 - full은 그래프 실행 시간(어댑터 측정)을 쓰고, 없을 때만 항목 전체 시간
    if fields.get("latency_ms") is None:
        fields["latency_ms"] = int((time.monotonic() - started) * 1000)
    # 2026.11.19(sooyeon.choi) 수정 - 반환 시간 지표(시험 4)를 넣기 위해 latency_ms 확정 뒤에 정규화
    fields["metric_status_json"] = _build_item_metric_status(fields, run_type, config)
    return fields


def _number(value: Any) -> Any:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _timing_metrics(latency_ms: Any, timing: Any) -> Dict[str, MetricResult]:
    """2026.11.19(sooyeon.choi) 추가 - 시험 4 답변 생성 반환 시간(ms)·첫 토큰 시간(ms) 항목 지표."""
    if isinstance(timing, str):
        try:
            timing = json.loads(timing)
        except json.JSONDecodeError:
            timing = {}
    output: Dict[str, MetricResult] = {}
    latency = _number(latency_ms)
    output[RESPONSE_TIME_KEY] = (
        MetricResult(latency, "evaluated") if latency is not None else MetricResult(None, "excluded", "missing_latency")
    )
    first_token = _number((timing or {}).get("first_token_ms")) if isinstance(timing, dict) else None
    output[FIRST_TOKEN_KEY] = (
        MetricResult(first_token, "evaluated") if first_token is not None
        else MetricResult(None, "excluded", "no_first_token")
    )
    return output


def _build_item_metric_status(
    fields: Dict[str, Any], scope: str, config: Dict[str, Any]
) -> Dict[str, Dict[str, Any]]:
    """항목 JSON을 공식 MetricResult 형태로 정규화해 함께 저장한다."""
    output: Dict[str, Dict[str, Any]] = {}
    retrieval = fields.get("retrieval_json") or {}
    for channel, metrics in retrieval.items():
        if not isinstance(metrics, dict):
            continue
        status = "error" if metrics.get("error") else "excluded" if metrics.get("skipped") else "evaluated"
        reason = metrics.get("reason") or ("retrieval_error" if metrics.get("error") else None)
        for key, value in metrics.items():
            # 2026.11.17(sooyeon.choi) 수정 - hit/recall/ndcg/rr@k만 지표로 저장(순위·건수·임계값 제외),
            #   rerank mrr@k 별칭 삭제(rr@k와 같은 값)
            if not is_aggregated_retrieval_metric(key):
                continue
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                output[f"retrieval.{channel}.{key}"] = MetricResult(float(value), "evaluated").as_dict()
            elif value is None:
                output[f"retrieval.{channel}.{key}"] = MetricResult(
                    None, "excluded", "missing_gold_chunks"
                ).as_dict()
        if status != "evaluated":
            output[f"retrieval.{channel}"] = MetricResult(None, status, reason).as_dict()

    # 2026.11.17(sooyeon.choi) 수정 - Answer Correctness는 F2 한 종류(answer.correctness)만 저장.
    #   v1·v2·judge 및 별칭(correctness_mean, *_shadow, .f2) 삭제
    answer = fields.get("answer_correctness_json")
    if isinstance(answer, dict):
        output["answer.correctness"] = answer
    citation = fields.get("citation_json")
    if isinstance(citation, dict):
        citation_status = "excluded" if citation.get("skipped") else "evaluated"
        reason = citation.get("reason")
        # 2026.11.17(sooyeon.choi) 수정 - citation_f1·citation_validity 삭제
        for key in _CITATION_METRIC_KEYS:
            value = citation.get(key)
            status = citation_status if value is not None else "excluded"
            output[f"citation.{key}"] = MetricResult(
                float(value) if value is not None else None, status,
                reason if reason else ("missing_gold_chunks" if value is None else None),
            ).as_dict()

    if scope in ("full", "end_to_end"):
        for key, result in _timing_metrics(fields.get("latency_ms"), fields.get("timing_json")).items():
            output[key] = result.as_dict()

    primary, secondary = metric_catalog(scope, config)
    for definition in [*primary, *secondary]:
        key = definition["key"]
        if key in output:
            continue
        channel_key = ".".join(key.split(".")[:2])
        if channel_key in output:
            output[key] = output[channel_key]
    return output

# 검색 평가 본체
async def _evaluate_retrieval(
    item: Dict[str, Any],
    config: Dict[str, Any],
    collection_name: str,
) -> Dict[str, Any]:
    """채널별 검색 + 리랭킹 지표를 계산한다."""
    from app.evaluation.adapters.retrieval_adapter import EvalRetriever
    from app.evaluation.adapters.reranker_adapter import EvalReranker

    question = item["question"]
    gold_ids: Set[str] = set(_parse_json_list(item.get("gold_chunk_ids")))
    top_k = int(config.get("retrieval_top_n", config.get("top_k", 10)))
    rerank_top_k = int(config.get("rerank_top_k", 5))
    channels = config.get("channels", _DEFAULT_CHANNELS)

    if item.get("expected_behavior") in _SKIP_RETRIEVAL_BEHAVIORS:
        return {
            channel: {
                "skipped": True,
                "reason": item["expected_behavior"],
            }
            for channel in [*channels, *(["rerank"] if config.get("enable_rerank", True) else [])]
        }

    retriever = EvalRetriever()
    result: Dict[str, Any] = {}
    rrf_hits = None

    for channel in channels:
        if channel == "rrf":
            hits = await retriever.search_rrf(question, top_k, collection_name)
            rrf_hits = hits
        else:
            hits = await retriever.search_channel(channel, question, top_k, collection_name)
        retrieved_ids = [chunk_id for chunk_id, _, _ in hits]
        retrieval_k_values = tuple(sorted(set((*_K_VALUES, top_k))))
        # 2026.11.17(sooyeon.choi) 삭제 - 문서 단위(document_*) 지표(청크 정답 기준과 이중 집계)
        result[channel] = compute_channel_metrics(
            retrieved_ids, gold_ids, retrieval_k_values
        )

    # 리랭킹 평가: RRF(또는 운영 병합) 결과 기반
    if config.get("enable_rerank", True):
        from app.core.config import get_settings
        settings = get_settings()
        # 2026.11.17(sooyeon.choi) 수정 - 재랭킹 입력·출력 수를 운영과 맞춤
        #   기존: RRF 상위 N(10)개만 재랭킹해 상위 K(5)개 → 운영(후보 candidate_top_k개 → reranker_top_k개)보다
        #   후보가 적어 NDCG@5가 운영과 다르게 나왔다. 지표 cutoff는 1,3,5,10 + K로 통일(full 평가와 동일).
        candidate_top_k = max(top_k, int(settings.candidate_top_k))
        rerank_output_k = max(rerank_top_k, int(settings.reranker_top_k))
        if rrf_hits is None or len(rrf_hits) < candidate_top_k:
            rrf_hits = await retriever.search_rrf(question, candidate_top_k, collection_name)
        try:
            reranked = await EvalReranker().rerank(question, rrf_hits, top_k=rerank_output_k)
            reranked_ids = [chunk_id for chunk_id, _, _ in reranked]
            rerank_metrics = compute_channel_metrics(
                reranked_ids, gold_ids, tuple(sorted({*_K_VALUES, rerank_top_k}))
            )
            threshold = settings.relevance_threshold
            score_map = {chunk_id: score for chunk_id, score, _ in reranked}
            rerank_metrics["threshold"] = threshold
            rerank_metrics["evidence_above_threshold"] = (
                any(score_map.get(chunk_id, 0.0) >= threshold for chunk_id in gold_ids)
                if gold_ids else None
            )
            result["rerank"] = rerank_metrics
        except Exception as e:
            result["rerank"] = {"error": str(e)[:200]}

    return result


def _parse_json_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def _item_meta(item: Dict[str, Any]) -> Dict[str, Any]:
    meta = item.get("source_meta_json")
    if isinstance(meta, str) and meta:
        try:
            meta = json.loads(meta)
        except json.JSONDecodeError:
            return {}
    return meta if isinstance(meta, dict) else {}


def item_collection(item: Dict[str, Any], default: str) -> str:
    """2026.11.20(sooyeon.choi) 수정 - 문항별 검색 컬렉션. 합본 문항은 source_meta_json.qdrant_name."""
    return str(_item_meta(item).get("qdrant_name") or default)


def _item_segments(item: Dict[str, Any]) -> List[str]:
    """이 QA 항목이 속하는 집계 세그먼트 목록: all + type:* + tag:* (+ 합본 문항은 law:*)."""
    segments = ["all"]
    # 2026.11.20(sooyeon.choi) 수정 - 합본 법령별 값: 같은 실행의 항목 결과를 법령으로 나눠 같은 식으로 집계
    law = _item_meta(item).get("law_label")
    if law:
        segments.append(f"law:{law}")
    qa_type = item.get("question_type")
    if qa_type:
        segments.append(f"type:{qa_type}")
    for tag in _parse_json_list(item.get("tags")):
        if tag:
            segments.append(f"tag:{tag}")
    return segments


def _aggregate_and_save_metrics(
    repo: EvalRepository,
    run_id: int,
    items: List[Dict[str, Any]],
) -> None:
    """항목별 결과를 세그먼트(all + type:* + tag:*)로 집계해 저장한다."""
    results = repo.list_item_results(run_id, page_size=10000)["items"]
    result_ids = {row["qa_id"] for row in results}
    results = [*results, *[
        {"qa_id": item.get("qa_id"), "status": "error"}
        for item in items if item.get("qa_id") not in result_ids
    ]]
    seg_map = {item.get("qa_id"): _item_segments(item) for item in items}

    buckets: Dict[str, Dict[str, List[MetricResult]]] = defaultdict(lambda: defaultdict(list))
    error_count = 0
    run = repo.get_run(run_id) or {}
    config = json.loads(run.get("config_json") or "{}")
    scope = run.get("run_type", "retrieval")
    primary, secondary = metric_catalog(scope, config)
    # 2026.11.19(sooyeon.choi) 수정 - 3종 LLM 심사(시험 3)는 아직 계산하지 않으므로 오류로 채우지 않는다('미측정' 표시)
    official_keys = [metric["key"] for metric in [*primary, *secondary] if metric["key"] != JUDGE_ACCURACY_KEY]
    # 2026.11.17(sooyeon.choi) 삭제 - v1·v2·f2·judge shadow 키 집계(Answer Correctness는 F2 한 종류)

    def add(segments: List[str], key: str, result: MetricResult) -> None:
        for segment in segments:
            buckets[segment][key].append(result)

    def add_bool_rate(segments: List[str], key: str, value: Any) -> None:
        if isinstance(value, bool):
            add(segments, key, MetricResult(1.0 if value else 0.0, "evaluated"))

    for row in results:
        segments = seg_map.get(row["qa_id"], ["all"])
        if row["status"] != "ok":
            error_count += 1
            # 단계 결과가 남아 있으면 검색·재랭킹은 독립적으로 집계한다.
        if row["status"] != "ok" and not row.get("retrieval_json"):
            for key in official_keys:
                if key in (RESPONSE_TIME_KEY, FIRST_TOKEN_KEY):
                    continue
                add(segments, key, MetricResult(None, "error", "item_execution_error"))
            if scope in ("full", "end_to_end"):
                for key, result in _timing_metrics(row.get("latency_ms"), row.get("timing_json")).items():
                    add(segments, key, result)
            continue

        if row.get("retrieval_json"):
            retrieval = json.loads(row["retrieval_json"])
            for channel, metrics in retrieval.items():
                if not isinstance(metrics, dict):
                    continue
                if metrics.get("skipped") or metrics.get("error"):
                    status = "excluded" if metrics.get("skipped") else "error"
                    reason = metrics.get("reason") or f"{channel}_error"
                    prefix = f"retrieval.{channel}."
                    for official_key in official_keys:
                        if official_key.startswith(prefix):
                            add(segments, official_key, MetricResult(None, status, reason))
                    continue
                for key, value in metrics.items():
                    # 2026.11.17(sooyeon.choi) 수정 - hit/recall/ndcg/rr@k만 평균(순위·건수·임계값 평균 금지),
                    #   rerank mrr@k 별칭 삭제
                    if not is_aggregated_retrieval_metric(key):
                        continue
                    metric_key = f"retrieval.{channel}.{key}"
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        add(segments, metric_key, MetricResult(float(value), "evaluated"))
                    elif value is None and metric_key in official_keys:
                        add(segments, metric_key, MetricResult(None, "excluded", "missing_gold_chunks"))

        # 2026.11.17(sooyeon.choi) 수정 - Answer Correctness는 F2(answer_correctness_json)만 집계.
        #   v1·v2·judge·similarity 별칭(correctness_mean, similarity.mean, *_shadow) 삭제
        if row.get("answer_correctness_json"):
            answer_metric = json.loads(row["answer_correctness_json"])
            add(segments, "answer.correctness", MetricResult(
                answer_metric.get("value"),
                answer_metric["status"],
                answer_metric.get("reason"),
                answer_metric.get("metadata") or {},
            ))

        if row.get("citation_json"):
            citation = json.loads(row["citation_json"])
            # 2026.11.17(sooyeon.choi) 수정 - correctness·completeness만 집계(인용 건수 평균 등 삭제)
            for key in _CITATION_METRIC_KEYS:
                value = citation.get(key)
                if citation.get("skipped"):
                    result = MetricResult(None, "excluded", citation.get("reason"))
                elif isinstance(value, (int, float)) and not isinstance(value, bool):
                    result = MetricResult(float(value), "evaluated")
                else:
                    result = MetricResult(None, "excluded", "missing_gold_chunks")
                add(segments, f"citation.{key}", result)

        # ①축 — threshold-fallback 분기 정확성 (expected_behavior 대비)
        if row.get("threshold_fallback_json"):
            tf = json.loads(row["threshold_fallback_json"])
            add_bool_rate(segments, "answer.behavior_correct_rate", tf.get("correct"))

        # ①축 — not_enough_info 거절 적합성 (해당 케이스만)
        # 2026.11.17(sooyeon.choi) 삭제 - answer.format_correct_rate(check_format),
        #   answer.rule_match.mean(rule_check), latency.mean_ms(지표 계산 시간이 섞인 항목 전체 시간)
        if row.get("guardrail_json"):
            guardrail = json.loads(row["guardrail_json"])
            add_bool_rate(segments, "answer.refusal_correct_rate", guardrail.get("refusal_correct"))

        # 2026.11.19(sooyeon.choi) 추가 - 시험 4 답변 생성 평균 반환 시간(ms)·첫 토큰 시간(전체 RAG 평가만)
        if scope in ("full", "end_to_end"):
            for key, result in _timing_metrics(row.get("latency_ms"), row.get("timing_json")).items():
                add(segments, key, result)

    metrics: Dict[str, Dict[str, Any]] = {}
    for seg, kv in buckets.items():
        seg_metrics: Dict[str, Any] = {}
        for key, results_for_key in kv.items():
            aggregate = MetricAggregate.from_results(results_for_key)
            value = aggregate.as_dict()
            # 시험 4: 측정 누락을 제외한 부분 평균을 공식 평균으로 표시하지 않는다.
            if key == RESPONSE_TIME_KEY and aggregate.evaluated_count != aggregate.total_count:
                value["value"] = None
                value["std"] = None
            # 2026.11.19(sooyeon.choi) 추가 - 합의서 시험 1·2 계산식: 분모 = 전체 시험 질의 수.
            #   실행 오류·정답 없음(제외) 질의는 0으로 센다(평가 건수·제외·오류 건수는 그대로 표시)
            if key in ALL_DENOMINATOR_KEYS and aggregate.total_count:
                evaluated_sum = sum(float(r.value) for r in results_for_key if r.status == "evaluated")
                value["value"] = evaluated_sum / aggregate.total_count
            # 2026.11.17(sooyeon.choi) 수정 - answer.correctness는 F2 지표 버전으로 기록
            if key == "answer.correctness":
                metric_version = (config.get("answer_correctness_f2") or {}).get(
                    "metric_version", "f2.1"
                )
            else:
                metric_version = config.get("metric_version", "legacy")
            value["metric_version"] = metric_version
            seg_metrics[key] = value
            if value["std"] is not None:
                seg_metrics[f"{key}.std"] = value["std"]
        metrics[seg] = seg_metrics
    total = len(results)
    if total:
        metrics.setdefault("all", {})["run.error_rate"] = error_count / total
    repo.save_run_metrics(run_id, metrics)

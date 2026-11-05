"""평가 배치 실행 오케스트레이터.

- asyncio.create_task 기반 백그라운드 실행 (run_registry로 추적/취소)
- 항목 단위 Semaphore 동시성 제어, 항목별 부분실패 허용
- 진행률은 항목 완료 시마다 DB 갱신
- run_type:
    retrieval  — 채널별 검색 + 리랭크만 (LLM 미사용, 저비용)  [P2 구현]
    full       — 검색 + 규칙 기반 답변/Citation 평가

집계 세그먼트: all + type:{question_type} + tag:{tag} (①축 한국어 세그먼트 보존).
(reference app/evaluation/runner/eval_runner.py 이식 + tag 세그먼트 확장)
"""

import asyncio
import json
import time
from collections import defaultdict
from typing import Any, Dict, List, Set

from app.evaluation.metric_catalog import metric_catalog
from app.evaluation.metrics.models import MetricAggregate, MetricResult
from app.evaluation.metrics.retrieval_metrics import compute_channel_metrics
from app.repositories.evaluation_repository import EvalRepository
from app.evaluation.runner import run_registry
from app.utils.log.log import LoggingLogger

logger = LoggingLogger().getLogger(__name__)

_DEFAULT_CHANNELS = ["dense", "kiwi_bm25", "rrf"]   # 기본 평가 채널
_K_VALUES = (1, 3, 5, 10)
_SKIP_RETRIEVAL_BEHAVIORS = {"guardrail", "permission_denied"}

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

        semaphore = asyncio.Semaphore(int(config.get("concurrency", 3)))
        run_type = run["run_type"]

        async def _process(item: Dict[str, Any]) -> None:
            async with semaphore:
                if run_registry.is_cancel_requested(run_id):
                    return
                qa_id = item.get("qa_id", 0)
                try:
                    fields = await _evaluate_item(item, run_type, config, collection_name)
                    repo.insert_item_result(run_id, qa_id, **fields)
                except Exception as e:
                    logger.error(f"[eval] run {run_id} qa {qa_id} 실패: {e}")
                    repo.insert_item_result(
                        run_id, qa_id, status="error", error_message=str(e)[:500]
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

    fields["metric_status_json"] = _build_item_metric_status(fields, run_type, config)
    fields["latency_ms"] = int((time.monotonic() - started) * 1000)
    return fields


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
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                output[f"retrieval.{channel}.{key}"] = MetricResult(float(value), "evaluated").as_dict()
                if channel == "rerank" and key.startswith("rr@"):
                    cutoff = key.split("@", 1)[1]
                    output[f"retrieval.rerank.mrr@{cutoff}"] = MetricResult(
                        float(value), "evaluated"
                    ).as_dict()
            elif value is None:
                output[f"retrieval.{channel}.{key}"] = MetricResult(
                    None, "excluded", "missing_gold_chunks"
                ).as_dict()
        if status != "evaluated":
            output[f"retrieval.{channel}"] = MetricResult(None, status, reason).as_dict()

    answer = fields.get("answer_correctness_v1_json")
    if isinstance(answer, dict):
        output["answer.correctness.v1"] = answer
        output["answer.correctness_mean"] = answer
    # 2026.08.03(sooyeon.choi) 수정 - rule-v2 shadow 상태를 공식 v1과 분리 저장
    answer_v2 = fields.get("answer_correctness_v2_json")
    if isinstance(answer_v2, dict):
        output["answer.correctness.v2"] = answer_v2
        output["answer.correctness_v2_shadow"] = answer_v2
    answer_v2_f2 = fields.get("answer_correctness_f2_json")
    if isinstance(answer_v2_f2, dict):
        output["answer.correctness_v2_f2_shadow"] = answer_v2_f2
        output["answer.correctness.f2"] = answer_v2_f2
    answer_judge = fields.get("answer_correctness_judge_json")
    if isinstance(answer_judge, dict):
        output["answer.correctness.judge"] = answer_judge
    answer_best = fields.get("answer_correctness_json")
    if isinstance(answer_best, dict):
        output["answer.correctness"] = answer_best
    citation = fields.get("citation_json")
    if isinstance(citation, dict):
        citation_status = "excluded" if citation.get("skipped") else "evaluated"
        reason = citation.get("reason")
        for key in ("correctness", "completeness", "citation_f1", "citation_validity"):
            value = citation.get(key)
            status = citation_status if value is not None else "excluded"
            output[f"citation.{key}"] = MetricResult(
                float(value) if value is not None else None, status,
                reason if reason else ("missing_gold_chunks" if value is None else None),
            ).as_dict()

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
    gold_document_ids: Set[str] = set(_parse_json_list(item.get("gold_document_ids")))
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
        channel_metrics = compute_channel_metrics(
            retrieved_ids, gold_ids, retrieval_k_values
        )
        document_ids = list(dict.fromkeys(
            payload.get("document_id")
            for _, _, payload in hits
            if payload.get("document_id")
        ))
        document_metrics = compute_channel_metrics(
            document_ids, gold_document_ids, retrieval_k_values
        )
        channel_metrics.update({
            f"document_{key}": value
            for key, value in document_metrics.items()
            if key != "gold_ranks"
        })
        result[channel] = channel_metrics

    # 리랭킹 평가: RRF(또는 운영 병합) 결과 기반
    if config.get("enable_rerank", True):
        if rrf_hits is None:
            rrf_hits = await retriever.search_rrf(question, top_k, collection_name)
        try:
            reranked = await EvalReranker().rerank(question, rrf_hits, top_k=rerank_top_k)
            reranked_ids = [chunk_id for chunk_id, _, _ in reranked]
            rerank_metrics = compute_channel_metrics(
                reranked_ids, gold_ids, (1, 3, rerank_top_k)
            )
            from app.core.config import get_settings
            threshold = get_settings().relevance_threshold
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


def _item_segments(item: Dict[str, Any]) -> List[str]:
    """이 QA 항목이 속하는 집계 세그먼트 목록: all + type:* + tag:*."""
    segments = ["all"]
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
    seg_map = {item.get("qa_id"): _item_segments(item) for item in items}

    buckets: Dict[str, Dict[str, List[MetricResult]]] = defaultdict(lambda: defaultdict(list))
    error_count = 0
    run = repo.get_run(run_id) or {}
    config = json.loads(run.get("config_json") or "{}")
    scope = run.get("run_type", "retrieval")
    primary, secondary = metric_catalog(scope, config)
    official_keys = [metric["key"] for metric in [*primary, *secondary]]
    # 2026.08.03(sooyeon.choi) 수정 - catalog 비노출 shadow도 오류·제외 건수를 독립 집계
    shadow_keys = []
    if scope == "full":
        shadow_keys.extend([
            "answer.correctness.v1",
            "answer.correctness.v2",
            "answer.correctness.f2",
            "answer.correctness.judge",
            "answer.correctness",
        ])

    def add(segments: List[str], key: str, result: MetricResult) -> None:
        for segment in segments:
            buckets[segment][key].append(result)

    for row in results:
        segments = seg_map.get(row["qa_id"], ["all"])
        if row["status"] != "ok":
            error_count += 1
            for key in [*official_keys, *shadow_keys]:
                add(segments, key, MetricResult(None, "error", "item_execution_error"))
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
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        add(segments, f"retrieval.{channel}.{key}", MetricResult(float(value), "evaluated"))
                        if channel == "rerank" and key.startswith("rr@"):
                            cutoff = key.split("@", 1)[1]
                            add(segments, f"retrieval.rerank.mrr@{cutoff}", MetricResult(float(value), "evaluated"))
                    elif value is None:
                        metric_key = f"retrieval.{channel}.{key}"
                        if metric_key in official_keys:
                            add(segments, metric_key, MetricResult(None, "excluded", "missing_gold_chunks"))
                        if channel == "rerank" and key.startswith("rr@"):
                            cutoff = key.split("@", 1)[1]
                            mrr_key = f"retrieval.rerank.mrr@{cutoff}"
                            if mrr_key in official_keys:
                                add(segments, mrr_key, MetricResult(None, "excluded", "missing_gold_chunks"))

        answer_v1_json = row.get("answer_correctness_v1_json")
        answer_metric = json.loads(answer_v1_json) if answer_v1_json else None
        if answer_metric:
            answer_result = MetricResult(
                answer_metric.get("value"), answer_metric["status"], answer_metric.get("reason"),
                answer_metric.get("metadata") or {},
            )
            add(segments, "answer.correctness.v1", answer_result)
            add(segments, "answer.correctness_mean", answer_result)
            if answer_result.status == "evaluated":
                add(segments, "answer.similarity.mean", answer_result)
        elif row.get("similarity") is not None:
            similarity = float(row["similarity"])
            add(segments, "answer.correctness_mean", MetricResult(similarity, "evaluated"))
            add(segments, "answer.similarity.mean", MetricResult(similarity, "evaluated"))

        answer_v2_json = row.get("answer_correctness_v2_json")
        if answer_v2_json:
            answer_metric_v2 = json.loads(answer_v2_json)
            answer_v2_result = MetricResult(
                answer_metric_v2.get("value"),
                answer_metric_v2["status"],
                answer_metric_v2.get("reason"),
                answer_metric_v2.get("metadata") or {},
            )
            add(segments, "answer.correctness.v2", answer_v2_result)
            add(segments, "answer.correctness_v2_shadow", answer_v2_result)

        answer_f2_json = row.get("answer_correctness_f2_json")
        if answer_f2_json:
            answer_metric_v2_f2 = json.loads(answer_f2_json)
            answer_v2_f2_result = MetricResult(
                answer_metric_v2_f2.get("value"),
                answer_metric_v2_f2["status"],
                answer_metric_v2_f2.get("reason"),
                answer_metric_v2_f2.get("metadata") or {},
            )
            add(segments, "answer.correctness_v2_f2_shadow", answer_v2_f2_result)
            add(segments, "answer.correctness.f2", answer_v2_f2_result)

        if row.get("answer_correctness_judge_json"):
            judge_metric = json.loads(row["answer_correctness_judge_json"])
            judge_result = MetricResult(
                judge_metric.get("value"),
                judge_metric["status"],
                judge_metric.get("reason"),
                judge_metric.get("metadata") or {},
            )
            add(segments, "answer.correctness.judge", judge_result)

        if row.get("answer_correctness_json"):
            best_metric = json.loads(row["answer_correctness_json"])
            best_result = MetricResult(
                best_metric.get("value"),
                best_metric["status"],
                best_metric.get("reason"),
                best_metric.get("metadata") or {},
            )
            add(segments, "answer.correctness", best_result)

        if row.get("citation_json"):
            citation = json.loads(row["citation_json"])
            if citation.get("skipped"):
                for key in ("correctness", "completeness"):
                    add(segments, f"citation.{key}", MetricResult(None, "excluded", citation.get("reason")))
            else:
                for key, value in citation.items():
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        add(segments, f"citation.{key}", MetricResult(float(value), "evaluated"))
                for key in ("correctness", "completeness"):
                    if citation.get(key) is None:
                        add(segments, f"citation.{key}", MetricResult(None, "excluded", "missing_gold_chunks"))

        # ①축 — threshold-fallback 분기 정확성 (expected_behavior 대비)
        if row.get("threshold_fallback_json"):
            tf = json.loads(row["threshold_fallback_json"])
            if isinstance(tf.get("correct"), bool):
                for seg in segments:
                    add([seg], "answer.behavior_correct_rate", MetricResult(1.0 if tf["correct"] else 0.0, "evaluated"))

        # ①축 — not_enough_info 거절 적합성 (해당 케이스만)
        if row.get("guardrail_json"):
            guardrail = json.loads(row["guardrail_json"])
            if isinstance(guardrail.get("format_correct"), bool):
                for seg in segments:
                    add([seg], "answer.format_correct_rate", MetricResult(1.0 if guardrail["format_correct"] else 0.0, "evaluated"))
            if isinstance(guardrail.get("refusal_correct"), bool):
                for seg in segments:
                    add([seg], "answer.refusal_correct_rate", MetricResult(1.0 if guardrail["refusal_correct"] else 0.0, "evaluated"))

        # ①축 — 수치·법규조항 규칙 일치율
        if row.get("rule_check_json"):
            rule = json.loads(row["rule_check_json"])
            if isinstance(rule.get("match_ratio"), (int, float)):
                for seg in segments:
                    add([seg], "answer.rule_match.mean", MetricResult(float(rule["match_ratio"]), "evaluated"))

        if row.get("latency_ms") is not None:
            for seg in segments:
                add([seg], "latency.mean_ms", MetricResult(float(row["latency_ms"]), "evaluated"))

    metrics: Dict[str, Dict[str, Any]] = {}
    for seg, kv in buckets.items():
        seg_metrics: Dict[str, Any] = {}
        for key, results_for_key in kv.items():
            aggregate = MetricAggregate.from_results(results_for_key)
            value = aggregate.as_dict()
            if key in {"answer.correctness.v2", "answer.correctness_v2_shadow"}:
                metric_version = (config.get("answer_correctness_v2") or {}).get(
                    "metric_version", "rule-v2-shadow.2"
                )
            elif key == "answer.correctness.f2":
                metric_version = (config.get("answer_correctness_f2") or {}).get(
                    "metric_version", "f2.1"
                )
            elif key == "answer.correctness.judge":
                metric_version = (config.get("answer_correctness_judge") or {}).get(
                    "metric_version", "answer_accuracy.1"
                )
            else:
                metric_version = config.get("metric_version", "legacy")
            value["metric_version"] = metric_version
            seg_metrics[key] = value
            if aggregate.std is not None:
                seg_metrics[f"{key}.std"] = aggregate.std
        metrics[seg] = seg_metrics
    total = len(results)
    if total:
        metrics.setdefault("all", {})["run.error_rate"] = error_count / total
    repo.save_run_metrics(run_id, metrics)

"""Full 평가 — 운영 RAG 실행 + 규칙 기반 답변/Citation 지표.

eval_runner._evaluate_item()에서 run_type이 end_to_end/full일 때 호출된다.
"""

import json
from typing import Any, Dict, List, Optional, Set

from app.evaluation.adapters.embedder_adapter import EvalEmbedder
from app.evaluation.metrics.answer_correctness_v1 import check_format, check_refusal
from app.evaluation.metrics.answer_correctness_v2 import (
    compute_sentence_alignment,
    split_sentences_ko_rule_v2,
)
from app.evaluation.metrics.answer_correctness_f2 import build_answer_correctness_f2
from app.evaluation.metrics.answer_correctness_judge import evaluate_correctness_judge
from app.evaluation.metrics.citation_metrics import (
    compute_evaluation_citation_metrics,
)
from app.evaluation.metrics.retrieval_metrics import compute_channel_metrics
from app.evaluation.metrics.similarity import (
    InvalidEmbeddingVector,
    clamp_similarity,
    cosine_similarity,
    count_citation_tags,
    normalize_answer_v2,
    rule_check,
)
from app.utils.log.log import LoggingLogger

logger = LoggingLogger().getLogger(__name__)

_pipeline = None

_SKIP_ANSWER_CORRECTNESS_BEHAVIORS = {
    "guardrail", "permission_denied", "not_enough_info"
}
_SKIP_RETRIEVAL_BEHAVIORS = {"guardrail", "permission_denied"}


def _get_pipeline():
    """RAG 파이프라인 어댑터를 지연 로드한다.

    rag_pipeline_adapter는 langgraph(무거운 그래프)에 의존하므로 모듈 import 시점이
    아니라 실제 end_to_end 실행 시점에만 로드한다 (지연 로딩 + 테스트 격리).
    """
    global _pipeline
    if _pipeline is None:
        from app.evaluation.adapters.rag_pipeline_adapter import EvalRagPipeline
        _pipeline = EvalRagPipeline()
    return _pipeline

# Full 평가 본체 (RAG 전체 실행 + 규칙 기반 답변/Citation 지표)
async def evaluate_end_to_end(
    item: Dict[str, Any],
    config: Dict[str, Any],
    collection_name: str,
) -> Dict[str, Any]:
    """QA 1건의 end-to-end 평가 결과 필드를 반환한다."""
    question = item["question"]
    gold_answer = item.get("gold_answer", "")
    gold_chunk_ids: Set[str] = set(_parse_list(item.get("gold_chunk_ids")))
    gold_document_ids: Set[str] = set(_parse_list(item.get("gold_document_ids")))
    expected_behavior = item.get("expected_behavior", "answer")

    # 1) RAG 전체 실행 (그래프 직접 호출 — reranked_chunks에 chunk_id 포함)
    result = await _get_pipeline().run(
        query=question,
        collection_name=collection_name,
        retrieval_top_n=int(config.get("retrieval_top_n", config.get("top_k", 10))),
        rerank_top_k=int(config.get("rerank_top_k", 5)),
    )

    system_answer = result["answer"]
    fields: Dict[str, Any] = {
        "answer_text": system_answer,
        "timing_json": result["timing"],
        "token_usage_json": result["usage"],
        # ①축 — 가드레일/threshold-fallback (답변 유무와 무관하게 항상 기록)
        "guardrail_json": _guardrail(result, expected_behavior, system_answer),
        "threshold_fallback_json": _threshold_fallback(
            result, expected_behavior, system_answer, gold_chunk_ids
        ),
    }
    if expected_behavior in _SKIP_RETRIEVAL_BEHAVIORS:
        fields["retrieval_json"] = {
            channel: {"skipped": True, "reason": expected_behavior}
            for channel in ("rrf", "rerank")
        }
    else:
        fields["retrieval_json"] = _compute_pipeline_retrieval_metrics(
            result=result,
            gold_chunk_ids=gold_chunk_ids,
            gold_document_ids=gold_document_ids,
            retrieval_top_n=int(config.get("retrieval_top_n", config.get("top_k", 10))),
            rerank_top_k=int(config.get("rerank_top_k", 5)),
        )

    if not system_answer:
        if expected_behavior != "answer":
            fields["status"] = "ok"
        else:
            # 평가 실행은 완료됐으므로 제외하지 않고 답변 품질 실패로 집계한다.
            fields["status"] = "ok"

    # 2026.08.03(sooyeon.choi) 수정 - rule-v1.1 공식 점수와 rule-v2 shadow를 병행 계산
    answer_metric, answer_metric_v2 = await _evaluate_answer_correctness_pair(
        gold_answer=gold_answer,
        system_answer=system_answer,
        expected_behavior=expected_behavior,
        config=config,
    )
    fields["answer_correctness_v1_json"] = answer_metric
    fields["answer_correctness_v2_json"] = answer_metric_v2
    if answer_metric["status"] == "evaluated":
        fields["similarity"] = answer_metric["value"]

    # F2: v2 결과 재사용 (추가 임베딩 불필요)
    f2_result = build_answer_correctness_f2(answer_metric_v2, config)
    fields["answer_correctness_f2_json"] = f2_result

    # Judge: 별도 LLM 호출
    judge_result = await evaluate_correctness_judge(
        question,
        gold_answer,
        system_answer,
        config,
        expected_behavior=expected_behavior,
    )
    fields["answer_correctness_judge_json"] = judge_result

    # Aggregation: 4가지 중 최선값 선택
    fields["answer_correctness_json"] = _aggregate_correctness(
        {"v1": answer_metric, "v2": answer_metric_v2, "f2": f2_result, "judge": judge_result},
        config,
    )

    # 3) 규칙 기반 체크 (수치·법규조항)
    fields["rule_check_json"] = rule_check(gold_answer, system_answer)

    # 5) 규칙 기반 Citation 지표와 공통 diagnostics
    citation_metrics = compute_evaluation_citation_metrics(
        answer=system_answer,
        citations=result["citations"],
        context_chunks=result.get("context_chunks") or [],
        gold_chunk_ids=gold_chunk_ids,
        gold_document_ids=gold_document_ids,
        expected_behavior=expected_behavior,
    )
    fields["citation_json"] = citation_metrics

    # 5) 상세 화면 표시용 원본 정보
    fields["citation_detail_json"] = {
        "diagnostics": citation_metrics,
        "cited": [
            {
                "citation_id": c.get("citation_id"),
                "chunk_id": c.get("chunk_id", ""),
                "document_id": c.get("document_id", ""),
                "original_filename": c.get("original_filename", ""),
                "header_path": c.get("header_path") or [],
                "page_number": c.get("page_number"),
                "referenced_in_answer": bool(c.get("referenced_in_answer")),
                "chunk_text": (c.get("chunk_text") or "")[:300],
            }
            for c in result["citations"]
        ],
        "used_chunks": [
            {
                "chunk_id": c.get("chunk_id", ""),
                "document_id": c.get("document_id", ""),
                "text": (c.get("text") or "")[:300],
                "score": c.get("score"),
            }
            for c in result["reranked_chunks"][:5]
        ],
    }

    return fields


async def _evaluate_answer_correctness(
    *,
    gold_answer: str,
    system_answer: str,
    expected_behavior: str,
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """기존 호출부 호환: 병행 계산 결과 중 공식 rule-v1.1만 반환한다."""
    answer_metric, _ = await _evaluate_answer_correctness_pair(
        gold_answer=gold_answer,
        system_answer=system_answer,
        expected_behavior=expected_behavior,
        config=config,
    )
    return answer_metric


def _aggregate_correctness(
    results: Dict[str, Any],
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """중앙 설정 snapshot에서 선택한 지표를 반환한다."""
    primary = config.get("answer_correctness_primary", "v1")
    fallback_chain = config.get("answer_correctness_fallback_chain", ["f2", "v2", "v1"])

    evaluated = {
        k: v for k, v in results.items()
        if v and v.get("status") == "evaluated" and v.get("value") is not None
    }

    def _with_source(result: Dict[str, Any], source: str) -> Dict[str, Any]:
        meta = {
            **(result.get("metadata") or {}),
            "selected_metric": source,
            "configured_primary": primary,
            "fallback_used": source != primary,
        }
        return {**result, "metadata": meta}

    chain = [primary] + [k for k in fallback_chain if k != primary]
    for key in chain:
        if key in evaluated:
            return _with_source(evaluated[key], key)

    # 모두 evaluated 아님 — 첫 번째 non-None 결과 반환
    for key in chain:
        if results.get(key):
            return _with_source(results[key], key)

    return {"value": None, "status": "excluded", "reason": "all_methods_unavailable", "metadata": {}}


# 2026.08.03(sooyeon.choi) 수정 - v1 전체답변 cosine과 v2 문장정렬 F1을 한 batch로 계산
async def _evaluate_answer_correctness_pair(
    *,
    gold_answer: str,
    system_answer: str,
    expected_behavior: str,
    config: Dict[str, Any],
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    answer_config = config.get("answer_correctness") or {}
    v2_config = config.get("answer_correctness_v2") or {}
    metadata: Dict[str, Any] = {
        "method": "embedding_cosine",
        "model": answer_config.get("embedding_model"),
        "model_version": answer_config.get("model_version"),
        "normalization_version": answer_config.get("normalization_version", "v2"),
        "metric_version": config.get("metric_version", "rule-v1.1"),
        "citation_tags_removed": count_citation_tags(gold_answer)
        + count_citation_tags(system_answer),
    }
    v2_metadata: Dict[str, Any] = {
        "method": "sentence_alignment_f1",
        "model": v2_config.get("embedding_model") or answer_config.get("embedding_model"),
        "model_version": v2_config.get("model_version") or answer_config.get("model_version"),
        "normalization_version": v2_config.get("normalization_version", "v2"),
        "sentence_split_version": v2_config.get("sentence_split_version", "ko-rule-v2"),
        "metric_version": v2_config.get("metric_version", "rule-v2-shadow.2"),
    }

    def result_pair(value, status, reason):
        return (
            {"value": value, "status": status, "reason": reason, "metadata": metadata},
            {"value": value, "status": status, "reason": reason, "metadata": v2_metadata},
        )

    if expected_behavior in _SKIP_ANSWER_CORRECTNESS_BEHAVIORS:
        return result_pair(None, "excluded", "expected_behavior_not_answer")

    normalized_gold = normalize_answer_v2(gold_answer)
    normalized_answer = normalize_answer_v2(system_answer)
    metadata.update({
        "gold_normalized_length": len(normalized_gold),
        "system_normalized_length": len(normalized_answer),
    })

    if not normalized_gold:
        return result_pair(None, "excluded", "missing_gold_answer")
    if not normalized_answer:
        metadata.update({"raw_cosine": None, "normalization_delta": None})
        v2_metadata.update({
            "gold_sentence_count": 0,
            "system_sentence_count": 0,
            "gold_coverage": 0.0,
            "system_precision": 0.0,
        })
        return result_pair(0.0, "evaluated", "empty_system_answer")

    min_chars = int(v2_config.get("min_sentence_chars", 10))
    max_sentences = int(v2_config.get("max_sentences_per_answer", 30))
    # 문장 정렬용 텍스트는 인용 태그를 제거하되 Markdown의 줄 경계를 보존한다.
    # 전체 답변 정규화 결과는 줄바꿈도 공백으로 접기 때문에, 제목으로 시작하는
    # 답변 전체가 하나의 Markdown 제목으로 오인되어 제거될 수 있다.
    normalized_gold_lines = "\n".join(
        normalize_answer_v2(line) for line in gold_answer.splitlines()
    )
    normalized_answer_lines = "\n".join(
        normalize_answer_v2(line) for line in system_answer.splitlines()
    )
    gold_sentences = split_sentences_ko_rule_v2(
        normalized_gold_lines, min_sentence_chars=min_chars, max_sentences=max_sentences
    )
    system_sentences = split_sentences_ko_rule_v2(
        normalized_answer_lines, min_sentence_chars=min_chars, max_sentences=max_sentences
    )
    v2_metadata.update({
        "gold_sentence_count": len(gold_sentences),
        "system_sentence_count": len(system_sentences),
    })
    requested_texts = [
        gold_answer, system_answer, normalized_gold, normalized_answer,
        *gold_sentences, *system_sentences,
    ]
    unique_texts = list(dict.fromkeys(requested_texts))
    try:
        unique_embeddings = await EvalEmbedder().embed(unique_texts)
        if len(unique_embeddings) != len(unique_texts):
            raise InvalidEmbeddingVector("embedding_count_mismatch")
        embedding_by_text = dict(zip(unique_texts, unique_embeddings))
        normalized_cosine = clamp_similarity(cosine_similarity(
            embedding_by_text[normalized_gold],
            embedding_by_text[normalized_answer],
        ))

        raw_cosine = None
        try:
            raw_cosine = clamp_similarity(cosine_similarity(
                embedding_by_text[gold_answer],
                embedding_by_text[system_answer],
            ))
        except InvalidEmbeddingVector:
            # 공식 normalized 계산이 성공했다면 raw 비교 실패는 진단값에만 영향을 준다.
            pass

        metadata.update({
            "raw_cosine": raw_cosine,
            "normalization_delta": (
                normalized_cosine - raw_cosine
                if raw_cosine is not None else None
            ),
        })
        v1_result = {
            "value": normalized_cosine,
            "status": "evaluated",
            "reason": None,
            "metadata": metadata,
        }
        if not gold_sentences:
            return (v1_result, {
                "value": None,
                "status": "excluded",
                "reason": "missing_gold_sentences",
                "metadata": v2_metadata,
            })
        if not system_sentences:
            return (v1_result, {
                "value": 0.0,
                "status": "evaluated",
                "reason": "empty_system_sentences",
                "metadata": v2_metadata,
            })

        # 2026.08.03(sooyeon.choi) 수정 - 중복 제거와 Gold 비례 precision 후보 제한 적용
        v2 = compute_sentence_alignment(
            gold_sentences,
            system_sentences,
            embedding_by_text,
            dedupe_threshold=float(v2_config.get("semantic_dedupe_threshold", 0.92)),
            precision_candidate_ratio=int(v2_config.get("precision_candidate_ratio", 3)),
        )
        v2_metadata.update({
            "gold_coverage": v2["gold_coverage"],
            "system_precision": v2["system_precision"],
            "gold_matches": v2["gold_matches"],
            "system_matches": v2["system_matches"],
            "alignment_pair_count": v2["pair_count"],
            "deduped_gold_sentence_count": v2["deduped_gold_sentence_count"],
            "deduped_system_sentence_count": v2["deduped_system_sentence_count"],
            "removed_gold_sentence_indices": v2["removed_gold_sentence_indices"],
            "removed_system_sentence_indices": v2["removed_system_sentence_indices"],
            "precision_candidate_count": v2["precision_candidate_count"],
            "embedding_request_text_count": len(requested_texts),
            "embedding_unique_text_count": len(unique_texts),
        })
        return (v1_result, {
            "value": v2["value"],
            "status": "evaluated",
            "reason": None,
            "metadata": v2_metadata,
        })
    except InvalidEmbeddingVector as exc:
        reason = str(exc)
        logger.warning("[eval][e2e] Answer Correctness 계산 불가: %s", reason)
        return ({
            "value": None,
            "status": "error",
            "reason": reason,
            "metadata": metadata,
        }, {
            "value": None,
            "status": "error",
            "reason": reason,
            "metadata": v2_metadata,
        })
    except Exception as exc:
        logger.warning(
            "[eval][e2e] Answer Correctness 임베딩 실패 type=%s",
            type(exc).__name__,
        )
        return ({
            "value": None,
            "status": "error",
            "reason": "embedding_error",
            "metadata": {**metadata, "error_type": type(exc).__name__},
        }, {
            "value": None,
            "status": "error",
            "reason": "embedding_error",
            "metadata": {**v2_metadata, "error_type": type(exc).__name__},
        })


def _compute_pipeline_retrieval_metrics(
    *,
    result: Dict[str, Any],
    gold_chunk_ids: Set[str],
    gold_document_ids: Set[str],
    retrieval_top_n: int,
    rerank_top_k: int,
) -> Dict[str, Any]:
    """운영 RAG가 실제 사용한 RRF·rerank 결과로 검색 지표를 계산한다."""

    def _metrics(
        chunks: List[Dict[str, Any]],
        gold_ids: Set[str],
        cutoff: int,
        id_key: str,
    ) -> Dict[str, Any]:
        ranked_ids = [str(chunk.get(id_key)) for chunk in chunks if chunk.get(id_key)]
        return compute_channel_metrics(ranked_ids, gold_ids, (cutoff,))

    retrieved = result.get("retrieved_chunks") or []
    reranked = result.get("reranked_chunks") or []

    rrf_metrics = _metrics(
        retrieved, gold_chunk_ids, retrieval_top_n, "chunk_id"
    )
    rerank_metrics = _metrics(
        reranked, gold_chunk_ids, rerank_top_k, "chunk_id"
    )

    rrf_document_metrics = _metrics(
        retrieved, gold_document_ids, retrieval_top_n, "document_id"
    )
    rerank_document_metrics = _metrics(
        reranked, gold_document_ids, rerank_top_k, "document_id"
    )
    rrf_metrics.update({
        f"document_{key}": value
        for key, value in rrf_document_metrics.items()
        if key != "gold_ranks"
    })
    rerank_metrics.update({
        f"document_{key}": value
        for key, value in rerank_document_metrics.items()
        if key != "gold_ranks"
    })

    return {"rrf": rrf_metrics, "rerank": rerank_metrics}


# ── ①축 병합 헬퍼 ────────────────────────────────────────────────────────────

def _guardrail(result: Dict[str, Any], expected_behavior: str, answer: str) -> Dict[str, Any]:
    """가드레일 관측값 + not_enough_info 거절 적합성."""
    return {
        "intent": result.get("intent"),
        "should_retrieve": result.get("should_retrieve"),
        "format_correct": check_format(answer),
        "refusal_correct": check_refusal(expected_behavior, answer),
    }


def _threshold_fallback(
    result: Dict[str, Any],
    expected_behavior: str,
    answer: str,
    gold_chunk_ids: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """expected_behavior 대비 파이프라인 분기 정확성 (CLI threshold_fallback 로직 이식)."""
    has_answer = bool(answer)
    metrics: Dict[str, Any] = {
        "correct": False,
        "false_fallback": False,   # answer인데 답변 없음(답변해야 하는데 답변 없음)
        "false_answer": False,     # not_enough_info인데 답변 생성(정보 부족인데 답변한 false_answer)
        "retry_count": result.get("retry_count", 0),
        "retry_recovered": None,
    }
    if expected_behavior == "answer":
        metrics["false_fallback"] = not has_answer
        metrics["correct"] = has_answer
    elif expected_behavior == "not_enough_info":
        metrics["false_answer"] = has_answer
        metrics["correct"] = not has_answer
    elif expected_behavior == "guardrail":
        metrics["correct"] = result.get("should_retrieve") is False and not has_answer
    elif expected_behavior == "permission_denied":
        metrics["correct"] = bool(result.get("error")) and not has_answer
    if metrics["retry_count"] > 0 and gold_chunk_ids:
        reranked_ids = {
            chunk.get("chunk_id")
            for chunk in result.get("reranked_chunks", [])
            if chunk.get("chunk_id")
        }
        metrics["retry_recovered"] = bool(reranked_ids & gold_chunk_ids)
    return metrics


def _check_refusal(expected_behavior: str, answer: str) -> Optional[bool]:
    """not_enough_info 케이스에서 거절 문구 포함 여부. 그 외 None."""
    return check_refusal(expected_behavior, answer)


def _parse_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []

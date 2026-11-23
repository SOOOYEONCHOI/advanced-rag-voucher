"""Full 평가 — 운영 RAG 실행 + 규칙 기반 답변/Citation 지표.

eval_runner._evaluate_item()에서 run_type이 end_to_end/full일 때 호출된다.

2026.11.17(sooyeon.choi) 수정 - 지표 정리
  - Answer Correctness는 F2(문장 정렬 Coverage 중심) 하나로 고정. v1(전체 답변 코사인),
    RAGAS Judge, 항목별 fallback 선택 삭제(항목마다 다른 방식 점수가 한 평균에 섞이던 문제)
  - 규칙 일치(rule_check)·형식(check_format) 지표 삭제
  - 검색 지표는 K=1,3,5,10 고정 + 설정 N/K를 함께 계산(시험 항목 Hit@10·NDCG@5)
"""

import json
from typing import Any, Dict, List, Optional, Set

from app.evaluation.adapters.embedder_adapter import EvalEmbedder
from app.evaluation.metrics.answer_correctness_v1 import check_refusal
from app.evaluation.metrics.answer_correctness_v2 import (
    compute_sentence_alignment,
    split_sentences_ko_rule_v2,
)
from app.evaluation.metrics.answer_correctness_f2 import build_answer_correctness_f2
from app.evaluation.metrics.citation_metrics import (
    compute_evaluation_citation_metrics,
)
from app.evaluation.metrics.retrieval_metrics import compute_channel_metrics
from app.evaluation.metrics.similarity import (
    InvalidEmbeddingVector,
    normalize_answer_v2,
)
from app.utils.log.log import LoggingLogger

logger = LoggingLogger().getLogger(__name__)

_pipeline = None

_SKIP_ANSWER_CORRECTNESS_BEHAVIORS = {
    "guardrail", "permission_denied", "not_enough_info"
}
_SKIP_RETRIEVAL_BEHAVIORS = {"guardrail", "permission_denied"}
# 2026.11.17(sooyeon.choi) 추가 - 검색 지표 고정 cutoff(retrieval 평가와 동일, 시험 Hit@10·NDCG@5 포함)
_K_VALUES = (1, 3, 5, 10)


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
    # [AI+ 시험] 반환 시간 - 1) 시험 데이터를 불러오는 코드
    question = item["question"]
    gold_answer = item.get("gold_answer", "")
    gold_chunk_ids: Set[str] = set(_parse_list(item.get("gold_chunk_ids")))
    gold_document_ids: Set[str] = set(_parse_list(item.get("gold_document_ids")))
    expected_behavior = item.get("expected_behavior", "answer")

    # 1) RAG 전체 실행 (그래프 직접 호출 — reranked_chunks에 chunk_id 포함)
    # [AI+ 시험] 반환 시간 - 2) 시험 데이터를 We.RAG에 입력하여 질의별 답변 생성을 요청하는 코드
    result = await _get_pipeline().run(
        query=question,
        collection_name=collection_name,
        retrieval_top_n=int(config.get("retrieval_top_n", config.get("top_k", 10))),
        rerank_top_k=int(config.get("rerank_top_k", 5)),
    )

    system_answer = result["answer"]
    fields: Dict[str, Any] = {
        # 2026.11.17(sooyeon.choi) 추가 - 응답시간은 그래프 실행(검색→재랭킹→답변 생성)만 측정
        # [AI+ 시험] 반환 시간 - 4) 질의별 답변 생성 반환 시간을 저장하는 코드
        "latency_ms": result.get("latency_ms"),
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
            retrieval_top_n=int(config.get("retrieval_top_n", config.get("top_k", 10))),
            rerank_top_k=int(config.get("rerank_top_k", 5)),
        )

    outcome = result.get("outcome_code")
    fields["status"] = "error" if outcome in {
        "validation_error", "retrieval_error", "llm_error", "system_error", "cancelled"
    } else "ok"
    fields["timing_json"] = {
        **(result.get("timing") or {}),
        "stage_statuses": {
            "retrieval": result.get("retrieval_status"),
            "rerank": result.get("rerank_status"),
            "answer": "error" if outcome == "llm_error" else "ok" if system_answer else "not_run",
        },
    }

    # 2026.11.17(sooyeon.choi) 수정 - 문장 정렬(v2)은 F2 계산 입력으로만 쓰고 F2를 공식 점수로 저장
    if fields["status"] == "error":
        fields["error_message"] = result.get("error") or outcome
    alignment = await _evaluate_answer_alignment(
        gold_answer=gold_answer,
        system_answer=system_answer,
        expected_behavior=expected_behavior,
        config=config,
    )
    fields["answer_correctness_json"] = build_answer_correctness_f2(alignment, config)

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


# 2026.11.17(sooyeon.choi) 삭제 - _evaluate_answer_correctness()(v1 호환 래퍼), _aggregate_correctness()(항목별 fallback 선택)


# 2026.11.17(sooyeon.choi) 수정 - v1(전체 답변 cosine) 계산 제거, 문장 정렬(v2) 결과만 반환
#   반환값은 F2 계산 입력(gold_coverage·system_precision)이며 별도 지표로 저장하지 않는다.
async def _evaluate_answer_alignment(
    *,
    gold_answer: str,
    system_answer: str,
    expected_behavior: str,
    config: Dict[str, Any],
) -> Dict[str, Any]:
    v2_config = config.get("answer_correctness_v2") or {}
    metadata: Dict[str, Any] = {
        "method": "sentence_alignment_f1",
        "model": v2_config.get("embedding_model"),
        "model_version": v2_config.get("model_version"),
        "normalization_version": v2_config.get("normalization_version", "v2"),
        "sentence_split_version": v2_config.get("sentence_split_version", "ko-rule-v2"),
        "metric_version": v2_config.get("metric_version", "rule-v2.3"),
    }

    def result(value, status, reason):
        return {"value": value, "status": status, "reason": reason, "metadata": metadata}

    if expected_behavior in _SKIP_ANSWER_CORRECTNESS_BEHAVIORS:
        return result(None, "excluded", "expected_behavior_not_answer")
    if not normalize_answer_v2(gold_answer):
        return result(None, "excluded", "missing_gold_answer")
    if not normalize_answer_v2(system_answer):
        metadata.update({
            "gold_sentence_count": 0,
            "system_sentence_count": 0,
            "gold_coverage": 0.0,
            "system_precision": 0.0,
        })
        return result(0.0, "evaluated", "empty_system_answer")

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
    metadata.update({
        "gold_sentence_count": len(gold_sentences),
        "system_sentence_count": len(system_sentences),
    })
    if not gold_sentences:
        return result(None, "excluded", "missing_gold_sentences")
    if not system_sentences:
        metadata.update({"gold_coverage": 0.0, "system_precision": 0.0})
        return result(0.0, "evaluated", "empty_system_sentences")

    unique_texts = list(dict.fromkeys([*gold_sentences, *system_sentences]))
    try:
        unique_embeddings = await EvalEmbedder().embed(unique_texts)
        if len(unique_embeddings) != len(unique_texts):
            raise InvalidEmbeddingVector("embedding_count_mismatch")
        embedding_by_text = dict(zip(unique_texts, unique_embeddings))

        # 2026.08.03(sooyeon.choi) 수정 - 중복 제거와 Gold 비례 precision 후보 제한 적용
        v2 = compute_sentence_alignment(
            gold_sentences,
            system_sentences,
            embedding_by_text,
            dedupe_threshold=float(v2_config.get("semantic_dedupe_threshold", 0.92)),
            precision_candidate_ratio=int(v2_config.get("precision_candidate_ratio", 3)),
        )
        metadata.update({
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
            "embedding_unique_text_count": len(unique_texts),
        })
        return result(v2["value"], "evaluated", None)
    except InvalidEmbeddingVector as exc:
        reason = str(exc)
        logger.warning("[eval][e2e] Answer Correctness 계산 불가: %s", reason)
        return result(None, "error", reason)
    except Exception as exc:
        logger.warning(
            "[eval][e2e] Answer Correctness 임베딩 실패 type=%s",
            type(exc).__name__,
        )
        metadata["error_type"] = type(exc).__name__
        return result(None, "error", "embedding_error")


def _compute_pipeline_retrieval_metrics(
    *,
    result: Dict[str, Any],
    gold_chunk_ids: Set[str],
    retrieval_top_n: int,
    rerank_top_k: int,
) -> Dict[str, Any]:
    """운영 RAG가 실제 사용한 RRF(재랭킹 전)·rerank 결과로 검색 지표를 계산한다.

    2026.11.17(sooyeon.choi) 수정 - 설정 N/K 단일 cutoff → K=1,3,5,10 + N/K로 확장,
    문서 단위(document_*) 지표 삭제(청크 단위 정답 기준과 이중 집계되던 문제)
    """

    def _metrics(chunks: List[Dict[str, Any]], cutoffs: tuple) -> Dict[str, Any]:
        ranked_ids = [str(chunk.get("chunk_id")) for chunk in chunks if chunk.get("chunk_id")]
        return compute_channel_metrics(ranked_ids, gold_chunk_ids, cutoffs)

    retrieved = result.get("retrieved_chunks") or []
    reranked = result.get("reranked_chunks") or []
    metrics = {
        "rrf": _metrics(retrieved, tuple(sorted({*_K_VALUES, retrieval_top_n}))),
        "rerank": _metrics(reranked, tuple(sorted({*_K_VALUES, rerank_top_k}))),
    }
    # F-08/F-09: 재랭킹 대체 결과를 정상 재랭킹으로 평가하지 않는다.
    if result.get("retrieval_status") in ("error", "not_run"):
        metrics["rrf"] = {"error": True, "reason": "retrieval_error"}
    rerank_status = result.get("rerank_status")
    if rerank_status in ("error", "not_run"):
        metrics["rerank"] = {"error": True, "reason": "rerank_error"}
    elif rerank_status == "skipped":
        metrics["rerank"] = {"skipped": True, "reason": "reranker_disabled"}
    return metrics


# ── ①축 병합 헬퍼 ────────────────────────────────────────────────────────────

def _guardrail(result: Dict[str, Any], expected_behavior: str, answer: str) -> Dict[str, Any]:
    """가드레일 관측값 + not_enough_info 거절 적합성."""
    return {
        "intent": result.get("intent"),
        "should_retrieve": result.get("should_retrieve"),
        # 2026.11.17(sooyeon.choi) 삭제 - format_correct(check_format)
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


# 2026.11.17(sooyeon.choi) 삭제 - 사용처 없는 _check_refusal() 래퍼


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

# 2026.06.29(sooyeon.choi) 수정 - Task 9 핵심 지표, 하위집합, Before/After 비교 검증
import sys
import types

# LLM judge와 무관한 집계 단위 테스트이므로 외부 설정 의존 모듈을 대체한다.
answer_stub = types.ModuleType("offline_evaluation.evaluators.answer")
answer_stub.AnswerEvaluator = object
ollama_stub = types.ModuleType("offline_evaluation.ollama_client")
ollama_stub.OllamaJudgeClient = object
sys.modules.setdefault("offline_evaluation.evaluators.answer", answer_stub)
sys.modules.setdefault("offline_evaluation.ollama_client", ollama_stub)

from offline_evaluation.comparison import (
    build_comparison,
    render_markdown,
    save_comparison,
)
from offline_evaluation.config import EvalConfig
from offline_evaluation.reporter import EvalReporter


def _record(record_id, question, tags=None, behavior="answer"):
    return {
        "id": record_id,
        "collection_name": "safety",
        "user_id": "eval_user",
        "question": question,
        "expected_answer": "answer",
        "expected_evidence": [{"chunk_id": f"chunk-{record_id}"}],
        "expected_behavior": behavior,
        "question_type": "factual",
        "difficulty": "normal",
        "split": "test",
        "tags": tags or [],
        "notes": None,
    }


def _result(record_id, latency_ms, has_context):
    return {
        "record_id": record_id,
        "intent": "rag_query",
        "should_retrieve": True,
        "retrieved_chunks": [],
        "reranked_chunks": [],
        "relevance_threshold_used": 0.3,
        "final_context": "context" if has_context else None,
        "context_chunk_count": 1 if has_context else 0,
        "generated_answer": "answer",
        "citations": [],
        "retry_count": 0,
        "error": None,
        "timing": {},
        "total_latency_ms": latency_ms,
    }


def _stage_metrics(hit_by_id):
    metrics = {}
    for record_id, hit in hit_by_id.items():
        if hit is None:
            metrics[record_id] = {
                "retrieval": {"skipped": True},
                "rerank": {"skipped": True},
                "threshold_fallback": {
                    "correct": True,
                    "false_fallback": None,
                    "false_answer": None,
                    "retry_count": 0,
                },
                "citation": {"skipped": True},
                "answer": {},
            }
            continue
        metrics[record_id] = {
            "retrieval": {
                "skipped": False,
                "recall_at_k": 1.0 if hit else 0.0,
                "hit_at_k": hit,
                "evidence_count": 1 if hit else 0,
            },
            "rerank": {
                "skipped": False,
                "mrr": 1.0 if hit else 0.0,
                "ndcg_at_k": 1.0 if hit else 0.0,
                "hit_at_k": hit,
                "evidence_above_threshold": hit,
                "evidence_rank": 1 if hit else None,
            },
            "threshold_fallback": {
                "correct": True,
                "false_fallback": False,
                "false_answer": False,
                "retry_count": 0,
            },
            "citation": {"skipped": True},
            "answer": {},
        }
    return metrics


def test_task9_summary_calculates_required_metrics_and_subsets():
    records = [
        _record("law", "제17조 기준은?"),
        _record("abbr", "PSM 대상 사업장은?"),
        _record("compound", "위험성 평가 방법은?"),
        _record("guard", "안녕하세요", behavior="guardrail"),
    ]
    results = [
        _result("law", 100.0, True),
        _result("abbr", 200.0, False),
        _result("compound", 300.0, True),
        _result("guard", 50.0, False),
    ]
    reporter = EvalReporter(
        records,
        results,
        _stage_metrics({"law": True, "abbr": False, "compound": True, "guard": None}),
        EvalConfig(run_label="After Task 4-5"),
    )

    task9 = reporter.summary()["task9"]

    assert task9["recall_at_10"] == 0.6667
    assert task9["hit_at_5"] == 0.6667
    assert task9["ndcg_at_5"] == 0.6667
    assert task9["no_context_rate"] == 0.3333
    assert task9["avg_latency_ms"] == 162.5
    assert task9["subset_failure_rates"]["law_reference"]["failure_rate"] == 0.0
    assert task9["subset_failure_rates"]["abbreviation"]["failure_rate"] == 1.0
    assert task9["subset_failure_rates"]["compound_term"]["failure_rate"] == 0.0


def test_comparison_flags_latency_and_saves_markdown(tmp_path):
    before = {
        "summary": {
            "task9": {
                "recall_at_10": 0.5,
                "hit_at_5": 0.5,
                "ndcg_at_5": 0.4,
                "no_context_rate": 0.3,
                "avg_latency_ms": 100.0,
                "subset_failure_rates": {},
            }
        }
    }
    after = {
        "summary": {
            "task9": {
                "recall_at_10": 0.8,
                "hit_at_5": 0.7,
                "ndcg_at_5": 0.65,
                "no_context_rate": 0.1,
                "avg_latency_ms": 125.0,
                "subset_failure_rates": {},
            }
        }
    }

    comparison = build_comparison(
        [("Before", before), ("After Task 4-5", after)],
        latency_limit_pct=20.0,
    )

    assert comparison["latency_checks"]["After Task 4-5"]["exceeded"] is True
    markdown = render_markdown(comparison)
    assert "Recall@10" in markdown
    assert "After Task 4-5" in markdown
    assert "초과" in markdown

    paths = save_comparison(comparison, str(tmp_path))
    assert paths["markdown"].endswith(".md")
    assert paths["json"].endswith(".json")

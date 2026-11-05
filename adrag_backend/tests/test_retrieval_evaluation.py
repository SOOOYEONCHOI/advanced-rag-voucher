import asyncio
import csv
import json
import math
from pathlib import Path

from offline_evaluation.config import EvalConfig
from offline_evaluation.evaluators import document_retrieval
from offline_evaluation.evaluators import retrieval as retrieval_evaluator
from offline_evaluation.retrieval_reporter import (
    RetrievalEvalReporter,
    evaluate_retrieval_results,
)
from offline_evaluation.retrieval_runner import RetrievalEvaluationRunner


def _record():
    return {
        "id": "gold_1",
        "collection_name": "docs",
        "user_id": "eval_user",
        "question": "정답은?",
        "expected_answer": "정답",
        "expected_evidence": [{
            "document_id": "doc-a",
            "chunk_id": "chunk-answer",
            "filename": "a.pdf",
            "page_number": 1,
            "evidence_text": "정답 근거",
        }],
        "expected_behavior": "answer",
        "question_type": "factual",
        "difficulty": "easy",
        "split": "test",
        "tags": [],
        "notes": None,
    }


def _chunk(chunk_id, document_id="doc-a", score=0.8):
    return {
        "chunk_id": chunk_id,
        "document_id": document_id,
        "text": chunk_id,
        "score": score,
        "metadata": {},
    }


def _result(retrieved, reranked=None):
    return {
        "record_id": "gold_1",
        "intent": None,
        "should_retrieve": True,
        "retrieved_chunks": retrieved,
        "reranked_chunks": reranked or [],
        "relevance_threshold_used": 0.3,
        "final_context": None,
        "context_chunk_count": None,
        "context_chunks": [],
        "generated_answer": None,
        "citations": [],
        "retry_count": 0,
        "error": None,
        "timing": {"retrieve_s": 0.1},
    }


def test_document_hit_distinguishes_wrong_chunk_in_right_document():
    metrics = document_retrieval.evaluate(
        _record(), _result([_chunk("wrong-chunk")]), k=5
    )
    assert metrics["hit_at_k"] is True

    stage_metrics = evaluate_retrieval_results(
        [_record()],
        [_result([_chunk("wrong-chunk")])],
        EvalConfig(retrieval_k=5),
        "dense_only",
    )
    assert stage_metrics["gold_1"]["retrieval"]["hit_at_k"] is False
    assert stage_metrics["gold_1"]["document_retrieval"]["hit_at_k"] is True


def test_non_rerank_mode_marks_rerank_as_not_executed():
    metrics = evaluate_retrieval_results(
        [_record()],
        [_result([_chunk("chunk-answer")])],
        EvalConfig(),
        "hybrid_retrieval",
    )
    assert metrics["gold_1"]["rerank"] == {
        "skipped": True,
        "reason": "stage_not_executed",
    }


def test_retrieval_evaluator_calculates_rank_mrr_ndcg_and_top1():
    record = _record()
    record["expected_evidence"].append({
        "document_id": "doc-b",
        "chunk_id": "chunk-second",
        "filename": "b.pdf",
        "page_number": 2,
        "evidence_text": "두 번째 근거",
    })
    result = _result([
        _chunk("noise", "doc-x"),
        _chunk("chunk-answer", "doc-a"),
        _chunk("chunk-second", "doc-b"),
    ])

    metrics = retrieval_evaluator.evaluate(record, result, k=3)

    assert metrics["evidence_rank"] == 2
    assert metrics["mrr"] == 0.5
    assert metrics["top1_is_relevant"] is False
    assert metrics["ndcg_at_k"] == (
        1 / math.log2(3) + 1 / math.log2(4)
    ) / (1 + 1 / math.log2(3))


def test_retrieval_rank_metrics_ignore_evidence_outside_k():
    result = _result([
        _chunk("noise-1", "doc-x"),
        _chunk("noise-2", "doc-y"),
        _chunk("chunk-answer", "doc-a"),
    ])

    metrics = retrieval_evaluator.evaluate(_record(), result, k=2)

    assert metrics["hit_at_k"] is False
    assert metrics["evidence_rank"] is None
    assert metrics["mrr"] == 0.0
    assert metrics["ndcg_at_k"] == 0.0


def test_hybrid_rerank_runner_calls_operating_nodes(monkeypatch):
    calls = []

    async def fake_retrieve(state):
        calls.append("retrieve")
        return {
            "retrieved_chunks": [_chunk("chunk-answer")],
            "error": None,
            "timing": {"retrieve_s": 0.1},
        }

    async def fake_rerank(state):
        calls.append("rerank")
        return {
            "reranked_chunks": [_chunk("chunk-answer", score=0.9)],
            "timing": {"retrieve_s": 0.1, "rerank_s": 0.2},
        }

    monkeypatch.setattr("offline_evaluation.retrieval_runner.retrieve", fake_retrieve)
    monkeypatch.setattr("offline_evaluation.retrieval_runner.rerank", fake_rerank)

    result = asyncio.run(
        RetrievalEvaluationRunner("hybrid_rerank").run_single(_record())
    )
    assert calls == ["retrieve", "rerank"]
    assert result["reranked_chunks"][0]["chunk_id"] == "chunk-answer"
    assert result["timing"]["rerank_s"] == 0.2


def test_retrieval_reporter_writes_question_level_csv(tmp_path: Path):
    records = [_record()]
    result_chunk = _chunk("chunk-answer")
    result_chunk["metadata"] = {
        "filename": "guide.pdf",
        "page_number": 3,
        "section_name": "검색 평가",
    }
    result_chunk["text"] = "검색된 청크 본문"
    results = [_result([result_chunk])]
    config = EvalConfig(retrieval_k=5)
    metrics = evaluate_retrieval_results(
        records, results, config, "dense_only"
    )
    paths = RetrievalEvalReporter(
        records, results, metrics, config, "dense_only"
    ).save(str(tmp_path))

    with Path(paths["csv"]).open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["record_id"] == "gold_1"
    assert rows[0]["chunk_hit"] == "True"
    assert rows[0]["retrieval_first_rank"] == "1"
    assert rows[0]["retrieval_mrr"] == "1.0"
    details = json.loads(rows[0]["retrieved_results"])
    assert details[0]["filename"] == "guide.pdf"
    assert details[0]["section_name"] == "검색 평가"
    assert details[0]["text_preview"] == "검색된 청크 본문"
    assert Path(paths["json"]).exists()
    assert Path(paths["markdown"]).exists()

import pytest


def test_answer_correctness_settings_reject_invalid_selection():
    from app.core.config import Settings

    with pytest.raises(ValueError):
        Settings.validate_answer_correctness_primary("highest")
    with pytest.raises(ValueError):
        Settings.validate_answer_correctness_fallback_chain(["v1", "v1"])
    with pytest.raises(ValueError):
        Settings.validate_answer_correctness_judge_backend("custom")


def test_ragas_answer_accuracy_judge_maps_result(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from app.evaluation.metrics import answer_correctness_judge as judge

    class FakeScorer:
        async def ascore(self, **kwargs):
            assert kwargs == {
                "user_input": "작업발판 폭 기준은?",
                "response": "작업발판 폭은 40cm 이상이다.",
                "reference": "작업발판의 폭은 40cm 이상이어야 한다.",
            }
            return SimpleNamespace(value=0.75, reason="대체로 일치")

    monkeypatch.setattr(judge, "_build_answer_accuracy", lambda *args: FakeScorer())
    monkeypatch.setattr(judge, "_ragas_version", lambda: "0.4.3")

    result = asyncio.run(judge.evaluate_correctness_judge(
        "작업발판 폭 기준은?",
        "작업발판의 폭은 40cm 이상이어야 한다.",
        "작업발판 폭은 40cm 이상이다.",
        {"answer_correctness_judge": {"backend": "vllm", "temperature": 0.0}},
    ))

    assert result["value"] == pytest.approx(0.75)
    assert result["status"] == "evaluated"
    assert result["reason"] == "대체로 일치"
    assert result["metadata"]["method"] == "ragas_answer_accuracy"
    assert result["metadata"]["ragas_version"] == "0.4.3"


def test_ragas_answer_accuracy_judge_excludes_missing_question():
    import asyncio

    from app.evaluation.metrics.answer_correctness_judge import evaluate_correctness_judge

    result = asyncio.run(evaluate_correctness_judge(
        "",
        "정답",
        "응답",
        {"answer_correctness_judge": {}},
    ))

    assert result["status"] == "excluded"
    assert result["reason"] == "missing_question"


def test_answer_correctness_f2_weights_gold_coverage():
    from app.evaluation.metrics.answer_correctness_f2 import (
        build_answer_correctness_f2,
    )

    result = build_answer_correctness_f2(
        {
            "value": 0.737,
            "status": "evaluated",
            "reason": None,
            "metadata": {
                "metric_version": "rule-v2-shadow.2",
                "gold_coverage": 0.85,
                "system_precision": 0.65,
            },
        },
        {"answer_correctness_f2": {"metric_version": "f2.1"}},
    )

    assert result["status"] == "evaluated"
    assert result["value"] == pytest.approx(5 * 0.85 * 0.65 / (4 * 0.65 + 0.85))
    assert result["metadata"]["beta"] == pytest.approx(2.0)

def test_full_metric_catalog_exposes_only_citation_completeness():
    from app.evaluation.metric_catalog import metric_catalog

    primary, _ = metric_catalog(
        "full", {"retrieval_top_n": 10, "rerank_top_k": 5}
    )
    keys = [metric["key"] for metric in primary]

    assert "answer.correctness" in keys
    assert "answer.correctness_mean" not in keys
    assert "citation.completeness" in keys
    assert "citation.correctness" not in keys


def test_answer_correctness_selects_configured_primary_and_fallback():
    from app.evaluation.runner.e2e_evaluator import _aggregate_correctness

    results = {
        "v1": {"value": 0.6, "status": "evaluated", "reason": None, "metadata": {}},
        "v2": {"value": 0.7, "status": "evaluated", "reason": None, "metadata": {}},
        "f2": {"value": 0.8, "status": "evaluated", "reason": None, "metadata": {}},
        "judge": {"value": None, "status": "error", "reason": "failed", "metadata": {}},
    }
    selected = _aggregate_correctness(
        results,
        {
            "answer_correctness_primary": "judge",
            "answer_correctness_fallback_chain": ["f2", "v2", "v1"],
        },
    )

    assert selected["value"] == pytest.approx(0.8)
    assert selected["metadata"]["configured_primary"] == "judge"
    assert selected["metadata"]["selected_metric"] == "f2"
    assert selected["metadata"]["fallback_used"] is True


def test_metric_aggregate_separates_zero_excluded_and_error():
    from app.evaluation.metrics.models import MetricAggregate, MetricResult

    aggregate = MetricAggregate.from_results([
        MetricResult(0.8, "evaluated"),
        MetricResult(0.0, "evaluated", "empty_system_answer"),
        MetricResult(None, "excluded", "missing_gold_answer"),
        MetricResult(None, "error", "embedding_timeout"),
    ])

    assert aggregate.value == pytest.approx(0.4)
    assert aggregate.evaluated_count == 2
    assert aggregate.excluded_count == 1
    assert aggregate.error_count == 1
    assert aggregate.total_count == 4


def test_retrieval_metrics_reject_non_positive_cutoff():
    from app.evaluation.metrics.retrieval_metrics import recall_at_k

    with pytest.raises(ValueError, match="cutoff"):
        recall_at_k(["A", "B"], {"A"}, 0)
    with pytest.raises(ValueError, match="cutoff"):
        recall_at_k(["A", "B"], {"A"}, -1)


def test_evidence_count_uses_deduped_rank_before_cutoff():
    from app.evaluation.metrics.retrieval_metrics import compute_channel_metrics

    metrics = compute_channel_metrics(["X", "X", "A"], {"A"}, (2,))

    assert metrics["recall@2"] == pytest.approx(1.0)
    assert metrics["evidence_count"] == 1


def test_cosine_rejects_invalid_vectors_and_answer_score_is_clamped():
    from app.evaluation.metrics.similarity import (
        InvalidEmbeddingVector,
        clamp_similarity,
        cosine_similarity,
    )

    with pytest.raises(InvalidEmbeddingVector, match="empty_vector"):
        cosine_similarity([], [1.0])
    with pytest.raises(InvalidEmbeddingVector, match="dimension_mismatch"):
        cosine_similarity([1.0], [1.0, 2.0])
    with pytest.raises(InvalidEmbeddingVector, match="zero_norm"):
        cosine_similarity([0.0, 0.0], [1.0, 0.0])

    assert clamp_similarity(-0.2) == 0.0
    assert clamp_similarity(1.2) == 1.0


def test_answer_normalization_removes_only_numeric_citation_tags():
    from app.evaluation.metrics.similarity import normalize_answer_v2

    assert normalize_answer_v2(" 높이는 90cm입니다 [1] [2, 3]. ") == "높이는 90cm입니다."
    assert normalize_answer_v2("[별표 1]과 [제3조]를 따릅니다 [1].") == (
        "[별표 1]과 [제3조]를 따릅니다."
    )


def test_answer_correctness_v2_bidirectional_alignment_penalizes_extra_sentence():
    from app.evaluation.metrics.answer_correctness_v2 import compute_sentence_alignment

    embeddings = {
        "필수 사실": [1.0, 0.0],
        "필수 사실 설명": [1.0, 0.0],
        "무관한 추가 설명": [0.0, 1.0],
    }
    result = compute_sentence_alignment(
        ["필수 사실"],
        ["필수 사실 설명", "무관한 추가 설명"],
        embeddings,
    )

    assert result["gold_coverage"] == pytest.approx(1.0)
    assert result["system_precision"] == pytest.approx(0.5)
    assert result["value"] == pytest.approx(2 / 3)


def test_answer_correctness_v2_ignores_markdown_format_and_caps_precision_candidates():
    from app.evaluation.metrics.answer_correctness_v2 import (
        compute_sentence_alignment,
        split_sentences_ko_rule_v2,
    )

    sentences = split_sentences_ko_rule_v2(
        "# 답변 제목\n검사 항목은 다음과 같습니다.\n- 핵심 검사 항목입니다."
    )
    assert sentences == ["핵심 검사 항목입니다."]

    embeddings = {
        "골드": [1.0, 0.0, 0.0, 0.0],
        "일치": [1.0, 0.0, 0.0, 0.0],
        "관련1": [0.8, 0.6, 0.0, 0.0],
        "관련2": [0.6, 0.0, 0.8, 0.0],
        "무관": [0.0, 0.0, 0.0, 1.0],
    }
    result = compute_sentence_alignment(
        ["골드"], ["일치", "관련1", "관련2", "무관"], embeddings
    )

    assert result["precision_candidate_count"] == 3
    assert result["system_precision"] == pytest.approx(0.8)
    assert result["value"] == pytest.approx(8 / 9)


def test_answer_correctness_markdown_heading_preserves_body_and_v1_score(monkeypatch):
    import asyncio
    from app.evaluation.runner import e2e_evaluator as e2e

    class _SameEmbedder:
        async def embed(self, texts):
            return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(e2e, "EvalEmbedder", lambda: _SameEmbedder())
    v1, v2 = asyncio.run(e2e._evaluate_answer_correctness_pair(
        gold_answer="핵심 안전 기준입니다.",
        system_answer="## 답변 제목\n핵심 안전 기준입니다. [1]",
        expected_behavior="answer",
        config={"metric_version": "rule-v1.1"},
    ))

    assert v1["value"] == pytest.approx(1.0)
    assert v1["reason"] is None
    assert v2["value"] == pytest.approx(1.0)
    assert v2["metadata"]["system_sentence_count"] == 1


def test_answer_correctness_v2_empty_sentences_do_not_zero_v1(monkeypatch):
    import asyncio
    from app.evaluation.runner import e2e_evaluator as e2e

    class _SameEmbedder:
        async def embed(self, texts):
            return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(e2e, "EvalEmbedder", lambda: _SameEmbedder())
    v1, v2 = asyncio.run(e2e._evaluate_answer_correctness_pair(
        gold_answer="골드 답변입니다.",
        system_answer="## 제목만 있는 답변",
        expected_behavior="answer",
        config={"metric_version": "rule-v1.1"},
    ))

    assert v1["value"] == pytest.approx(1.0)
    assert v1["reason"] is None
    assert v2["value"] == 0.0
    assert v2["reason"] == "empty_system_sentences"


def test_citation_metrics_without_gold_are_excluded_not_perfect():
    from app.evaluation.metrics.citation_metrics import citation_precision_recall

    metrics = citation_precision_recall([], set(), prefix="doc")

    assert metrics == {
        "doc_precision": None,
        "doc_recall": None,
        "doc_f1": None,
    }


def test_citation_diagnostics_include_validity_and_gold_differences():
    from app.evaluation.metrics.citation_metrics import (
        compute_evaluation_citation_metrics,
    )

    metrics = compute_evaluation_citation_metrics(
        answer="정답 [1], 다른 근거 [2], 잘못된 번호 [9]",
        citations=[
            {"citation_id": 1, "chunk_id": "A"},
            {"citation_id": 2, "chunk_id": "X"},
        ],
        context_chunks=[],
        gold_chunk_ids={"A", "B", "C"},
        expected_behavior="answer",
    )

    assert metrics["correctness"] == pytest.approx(1 / 3)
    assert metrics["completeness"] == pytest.approx(1 / 3)
    assert metrics["citation_validity"] == pytest.approx(2 / 3)
    assert metrics["valid_numbers"] == [1, 2]
    assert metrics["invalid_numbers"] == [9]
    assert metrics["matched_gold_chunk_ids"] == ["A"]
    assert metrics["missing_gold_chunk_ids"] == ["B", "C"]


def test_citation_analysis_deduplicates_chunks_and_excludes_missing_document_gold():
    from app.evaluation.metrics.citation_metrics import (
        compute_evaluation_citation_metrics,
    )

    metrics = compute_evaluation_citation_metrics(
        answer="같은 근거 [2]를 다시 [1] 인용하고 잘못된 번호 [9]도 사용한다.",
        citations=[
            {"citation_id": 1, "chunk_id": "A", "document_id": "D1"},
            {"citation_id": 2, "chunk_id": "A", "document_id": "D1"},
        ],
        context_chunks=[],
        gold_chunk_ids={"A"},
        expected_behavior="answer",
    )

    assert metrics["cited_numbers"] == [2, 1, 9]
    assert metrics["cited_chunk_ids"] == ["A"]
    assert metrics["correctness"] == pytest.approx(0.5)
    assert metrics["completeness"] == pytest.approx(1.0)
    assert metrics["document_correctness"] is None
    assert metrics["document_completeness"] is None
    assert metrics["doc_precision"] is None
    assert metrics["doc_recall"] is None


def test_answer_correctness_reports_zero_norm_as_error(monkeypatch):
    import asyncio
    from app.evaluation.runner import e2e_evaluator as e2e

    class _ZeroEmbedder:
        async def embed(self, texts):
            return [[0.0, 0.0] for _ in texts]

    monkeypatch.setattr(e2e, "EvalEmbedder", lambda: _ZeroEmbedder())
    result = asyncio.run(e2e._evaluate_answer_correctness(
        gold_answer="골드 답변",
        system_answer="시스템 답변 [1]",
        expected_behavior="answer",
        config={"metric_version": "rule-v1.1"},
    ))

    assert result["value"] is None
    assert result["status"] == "error"
    assert result["reason"] == "zero_norm"


def test_answer_correctness_reports_embedding_failure_without_error_text(monkeypatch):
    import asyncio
    from app.evaluation.runner import e2e_evaluator as e2e

    class _FailingEmbedder:
        async def embed(self, texts):
            raise RuntimeError("secret endpoint detail")

    monkeypatch.setattr(e2e, "EvalEmbedder", lambda: _FailingEmbedder())
    result = asyncio.run(e2e._evaluate_answer_correctness(
        gold_answer="골드 답변",
        system_answer="시스템 답변",
        expected_behavior="answer",
        config={},
    ))

    assert result["value"] is None
    assert result["status"] == "error"
    assert result["reason"] == "embedding_error"
    assert result["metadata"]["error_type"] == "RuntimeError"
    assert "secret" not in str(result)


def test_answer_correctness_keeps_raw_cosine_as_diagnostic(monkeypatch):
    import asyncio
    from app.evaluation.runner import e2e_evaluator as e2e

    class _MappedEmbedder:
        async def embed(self, texts):
            vectors = {
                "정답": [1.0, 0.0],
                "정답 [1]": [0.6, 0.8],
            }
            return [vectors[text] for text in texts]

    monkeypatch.setattr(e2e, "EvalEmbedder", lambda: _MappedEmbedder())
    result = asyncio.run(e2e._evaluate_answer_correctness(
        gold_answer="정답",
        system_answer="정답 [1]",
        expected_behavior="answer",
        config={"metric_version": "rule-v1.1"},
    ))

    assert result["value"] == pytest.approx(1.0)
    assert result["metadata"]["raw_cosine"] == pytest.approx(0.6)
    assert result["metadata"]["normalization_delta"] == pytest.approx(0.4)

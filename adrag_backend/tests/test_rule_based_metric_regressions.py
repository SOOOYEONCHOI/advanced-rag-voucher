import pytest


def test_removed_answer_correctness_selection_settings():
    # 2026.11.17(sooyeon.choi) 수정 - primary·fallback_chain·judge 설정과 RAGAS Judge 모듈 삭제
    import importlib.util
    from pathlib import Path

    # 일부 기존 테스트가 수집 단계에서 sys.modules["app.core.config"]를 stub으로 바꿔 두므로 원본 파일을 직접 로드한다.
    config_path = Path(__file__).resolve().parents[1] / "app" / "core" / "config.py"
    spec = importlib.util.spec_from_file_location("_eval_config_check", config_path)
    config_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config_module)
    Settings = config_module.Settings

    for name in (
        "answer_correctness_primary",
        "answer_correctness_fallback_chain",
        "answer_correctness_judge_backend",
        "answer_correctness_judge_model",
    ):
        assert name not in Settings.model_fields
    assert importlib.util.find_spec("app.evaluation.metrics.answer_correctness_judge") is None
    # 2026.11.17(sooyeon.choi) 추가 - 평가 전용 인용 보정은 기본 끔(운영 답변 그대로 평가)
    assert Settings.model_fields["eval_citation_repair_enabled"].default is False


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

def test_full_metric_catalog_follows_ai_plus_agreement():
    # 2026.11.19(sooyeon.choi) 수정 - 주요 지표 = 합의서 시험 1~4, 나머지는 보조 지표
    from app.evaluation.metric_catalog import metric_catalog, present_run_metrics

    primary, secondary = metric_catalog("full", {"retrieval_top_n": 10, "rerank_top_k": 5})
    # 2026.11.19(sooyeon.choi) 수정 - 지표 4 판정 = 첫 토큰 반환 시간 평균 ≤ 5초, 전체 반환 시간은 함께 표시(보조)
    assert [metric["key"] for metric in primary] == [
        "retrieval.rrf.hit@10", "retrieval.rerank.ndcg@5", "answer.judge_accuracy", "answer.first_token_ms",
    ]
    assert [metric["target"] for metric in primary] == [0.80, 0.80, 0.80, 5000]
    assert primary[3]["unit"] == "ms" and primary[3]["direction"] == "le"
    assert primary[3]["companion_key"] == "answer.response_time_ms"
    secondary_keys = [metric["key"] for metric in secondary]
    assert secondary_keys == [
        "retrieval.rrf.recall@10", "retrieval.rerank.hit@5", "retrieval.rerank.rr@5", "retrieval.rrf.ndcg@10",
        "answer.correctness", "citation.completeness", "citation.correctness", "answer.response_time_ms",
    ]
    assert all(metric["target"] is None for metric in secondary)
    # 검색·재정렬 평가는 시험 1·2만, 실행 설정 N·K가 다르면 보조 지표에 추가
    primary, secondary = metric_catalog("retrieval", {"retrieval_top_n": 20, "rerank_top_k": 3})
    assert [metric["key"] for metric in primary] == ["retrieval.rrf.hit@10", "retrieval.rerank.ndcg@5"]
    assert {"retrieval.rrf.hit@20", "retrieval.rerank.ndcg@3"} <= {metric["key"] for metric in secondary}
    # 심사 미구현 지표는 '미측정'으로 표시
    presented = present_run_metrics("full", {}, [
        {"metric_key": "retrieval.rrf.hit@10", "segment": "all", "metric_value": 0.9, "evaluated_count": 9, "total_count": 10},
    ])
    judge = [m for m in presented["primary_metrics"] if m["key"] == "answer.judge_accuracy"][0]
    assert judge["status"] == "not_measured" and judge["value"] is None
    assert [m["key"] for m in presented["primary_metrics"]] == ["retrieval.rrf.hit@10", "answer.judge_accuracy"]


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


# 2026.11.17(sooyeon.choi) 수정 - v1(전체 답변 cosine) 삭제, 문장 정렬(_evaluate_answer_alignment) 기준으로 변경
def test_answer_alignment_markdown_heading_preserves_body(monkeypatch):
    import asyncio
    from app.evaluation.runner import e2e_evaluator as e2e

    class _SameEmbedder:
        async def embed(self, texts):
            return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(e2e, "EvalEmbedder", lambda: _SameEmbedder())
    result = asyncio.run(e2e._evaluate_answer_alignment(
        gold_answer="핵심 안전 기준을 반드시 지켜야 합니다.",
        system_answer="## 답변 제목\n핵심 안전 기준을 반드시 지켜야 합니다. [1]",
        expected_behavior="answer",
        config={},
    ))

    assert result["value"] == pytest.approx(1.0)
    assert result["reason"] is None
    assert result["metadata"]["system_sentence_count"] == 1


def test_answer_alignment_empty_system_sentences_scores_zero(monkeypatch):
    import asyncio
    from app.evaluation.runner import e2e_evaluator as e2e

    class _FailIfCalledEmbedder:
        async def embed(self, texts):
            raise AssertionError("문장이 없으면 임베딩하지 않는다")

    monkeypatch.setattr(e2e, "EvalEmbedder", lambda: _FailIfCalledEmbedder())
    result = asyncio.run(e2e._evaluate_answer_alignment(
        gold_answer="골드 답변 문장은 충분히 길어야 합니다.",
        system_answer="## 제목만 있는 답변",
        expected_behavior="answer",
        config={},
    ))

    assert result["value"] == 0.0
    assert result["reason"] == "empty_system_sentences"


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
    assert "citation_validity" not in metrics
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
    # 2026.11.17(sooyeon.choi) 수정 - 문서 단위 지표·doc_* 별칭 삭제
    for removed in ("document_correctness", "document_completeness", "doc_precision", "doc_recall"):
        assert removed not in metrics


def test_answer_correctness_reports_zero_norm_as_error(monkeypatch):
    import asyncio
    from app.evaluation.runner import e2e_evaluator as e2e

    class _ZeroEmbedder:
        async def embed(self, texts):
            return [[0.0, 0.0] for _ in texts]

    monkeypatch.setattr(e2e, "EvalEmbedder", lambda: _ZeroEmbedder())
    result = asyncio.run(e2e._evaluate_answer_alignment(
        gold_answer="골드 답변 문장은 충분히 길어야 합니다.",
        system_answer="시스템 답변 문장도 충분히 길게 씁니다. [1]",
        expected_behavior="answer",
        config={},
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
    result = asyncio.run(e2e._evaluate_answer_alignment(
        gold_answer="골드 답변 문장은 충분히 길어야 합니다.",
        system_answer="시스템 답변 문장도 충분히 길게 씁니다.",
        expected_behavior="answer",
        config={},
    ))

    assert result["value"] is None
    assert result["status"] == "error"
    assert result["reason"] == "embedding_error"
    assert result["metadata"]["error_type"] == "RuntimeError"
    assert "secret" not in str(result)

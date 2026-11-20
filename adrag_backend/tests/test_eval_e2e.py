"""End-to-End 평가기(P3-②) 테스트.

라이브 LLM/Qdrant 없이 검증:
  - e2e 모듈/어댑터/metrics import
  - 순수 지표: cosine_similarity, citation correctness/completeness
  (2026.11.17(sooyeon.choi) 수정 - rule_check·citation P/R/F1·v1·judge 지표 삭제 반영)
  - 규칙 기반 헬퍼와 evaluate_end_to_end 오케스트레이션
"""

import asyncio
import json
from types import SimpleNamespace

import pytest

from app.repositories import database
from app.repositories.evaluation_repository import EvalRepository


def test_eval_citation_validation_requires_in_range_number():
    from app.evaluation.adapters.citation_repair import has_valid_citation

    assert has_valid_citation("근거입니다 [1].", 2) is True
    assert has_valid_citation("범위 밖입니다 [3].", 2) is False
    assert has_valid_citation("인용이 없습니다.", 2) is False


@pytest.mark.asyncio
async def test_eval_repairs_missing_citation_once(monkeypatch):
    from app.evaluation.adapters.citation_repair import repair_missing_citations

    class FakeProvider:
        async def chat(self, messages, *, temperature=None, max_tokens=None):
            assert temperature == 0.0
            return SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content="보정된 답변입니다 [1].")
            )])

    repaired = await repair_missing_citations(
        answer="인용 없는 답변입니다.",
        final_context="[문서 1]\n근거",
        context_count=1,
        llm_provider=FakeProvider(),
    )

    assert repaired == "보정된 답변입니다 [1]."


@pytest.fixture(autouse=True)
def reset_database_singletons():
    database._db_manager = None
    database.DatabaseManager._instance = None
    yield
    manager = database.DatabaseManager._instance
    if manager is not None:
        manager.close_all_connections()
    database._db_manager = None
    database.DatabaseManager._instance = None


# ── import ───────────────────────────────────────────────────────────────────

def test_e2e_modules_import():
    # e2e_evaluator는 rag_pipeline_adapter(langgraph)를 지연 로드하므로 무거운 그래프 없이 import 가능
    import app.evaluation.runner.e2e_evaluator  # noqa: F401
    import app.evaluation.adapters.llm_adapter  # noqa: F401
    import app.evaluation.adapters.embedder_adapter  # noqa: F401
    import app.evaluation.metrics.similarity  # noqa: F401
    import app.evaluation.metrics.citation_metrics  # noqa: F401


def test_pipeline_adapter_imports_when_langgraph_available():
    pytest.importorskip("langgraph")
    import app.evaluation.adapters.rag_pipeline_adapter  # noqa: F401


# ── 순수 지표 ────────────────────────────────────────────────────────────────

def test_cosine_similarity():
    from app.evaluation.metrics.similarity import cosine_similarity
    assert cosine_similarity([1, 0], [1, 0]) == pytest.approx(1.0)
    assert cosine_similarity([1, 0], [0, 1]) == pytest.approx(0.0)
    from app.evaluation.metrics.similarity import InvalidEmbeddingVector
    with pytest.raises(InvalidEmbeddingVector, match="empty_vector"):
        cosine_similarity([], [1])


def test_removed_metric_helpers_are_gone():
    # 2026.11.17(sooyeon.choi) 추가 - 삭제한 지표 함수가 다시 쓰이지 않게 확인
    import app.evaluation.metrics.citation_metrics as citation_metrics
    import app.evaluation.metrics.similarity as similarity

    assert not hasattr(similarity, "rule_check")
    assert not hasattr(citation_metrics, "citation_precision_recall")
    assert not hasattr(citation_metrics, "map_cited_chunk_ids")


def test_evaluation_citation_metrics_use_actual_context_order():
    from app.evaluation.metrics.citation_metrics import (
        compute_evaluation_citation_metrics,
    )

    metrics = compute_evaluation_citation_metrics(
        answer="근거입니다 [1].",
        citations=[{"citation_id": 1}],
        context_chunks=[{"chunk_id": "gold1"}],
        gold_chunk_ids={"gold1"},
        expected_behavior="answer",
    )
    assert metrics["all_numbers_valid"] is True
    assert "citation_relevance" not in metrics
    assert metrics["correctness"] == 1.0
    assert metrics["completeness"] == 1.0
    assert metrics["missing_citation"] is False

    # format_citations 메타데이터가 유실돼도 [N]은 실제 context 순서로 복구한다.
    recovered = compute_evaluation_citation_metrics(
        answer="근거입니다 [1].",
        citations=[],
        context_chunks=[{"chunk_id": "gold1", "document_id": "doc1"}],
        gold_chunk_ids={"gold1"},
        gold_document_ids={"doc1"},
        expected_behavior="answer",
    )
    assert recovered["valid_numbers"] == [1]
    assert recovered["cited_chunk_ids"] == ["gold1"]
    assert recovered["completeness"] == pytest.approx(1.0)

    skipped = compute_evaluation_citation_metrics(
        answer="",
        citations=[],
        context_chunks=[],
        gold_chunk_ids=set(),
        expected_behavior="guardrail",
    )
    assert skipped == {"skipped": True, "reason": "guardrail"}


def test_evaluation_citation_metrics_penalize_invalid_and_non_gold_citations():
    from app.evaluation.metrics.citation_metrics import (
        compute_evaluation_citation_metrics,
    )

    metrics = compute_evaluation_citation_metrics(
        answer="근거 [1], 추가 근거 [2], 잘못된 번호 [9].",
        citations=[
            {"citation_id": 1, "chunk_id": "gold-a"},
            {"citation_id": 2, "chunk_id": "other-x"},
        ],
        context_chunks=[],
        gold_chunk_ids={"gold-a", "gold-b", "gold-c"},
        expected_behavior="answer",
    )

    assert metrics["correctness"] == pytest.approx(1 / 3)
    assert metrics["completeness"] == pytest.approx(1 / 3)
    assert metrics["invalid_citation_count"] == 1


# ── ①축 헬퍼 ─────────────────────────────────────────────────────────────────

def test_threshold_fallback_branches():
    from app.evaluation.runner.e2e_evaluator import _threshold_fallback
    # answer인데 답변 있음 → correct
    assert _threshold_fallback({"retry_count": 1}, "answer", "답변")["correct"] is True
    # answer인데 답변 없음 → false_fallback
    tf = _threshold_fallback({}, "answer", "")
    assert tf["correct"] is False and tf["false_fallback"] is True
    # not_enough_info인데 답변 생성 → false_answer
    tf2 = _threshold_fallback({}, "not_enough_info", "억지 답변")
    assert tf2["correct"] is False and tf2["false_answer"] is True
    # not_enough_info + 거절(답변없음) → correct
    assert _threshold_fallback({}, "not_enough_info", "")["correct"] is True
    # guardrail: should_retrieve=False + 답변없음 → correct
    assert _threshold_fallback({"should_retrieve": False}, "guardrail", "")["correct"] is True


def test_guardrail_and_refusal():
    from app.evaluation.metrics.answer_correctness_v1 import check_refusal
    from app.evaluation.runner.e2e_evaluator import _guardrail
    g = _guardrail({"intent": "rag_query", "should_retrieve": True}, "answer", "답변입니다")
    assert g["intent"] == "rag_query" and g["refusal_correct"] is None
    assert "format_correct" not in g
    # not_enough_info + 거절 문구 포함 → True
    assert check_refusal("not_enough_info", "제공된 문서에서 찾을 수 없습니다") is True
    assert check_refusal("not_enough_info", "제38조는 ...") is False
    assert check_refusal("answer", "아무거나") is None


# ── evaluate_end_to_end 오케스트레이션 (목킹) ─────────────────────────────────

def test_evaluate_end_to_end_assembles_all_fields(monkeypatch):
    from app.evaluation.runner import e2e_evaluator as e2e

    pipeline_calls = []

    class _FakePipeline:
        async def run(self, query, collection_name, retrieval_top_n=10, rerank_top_k=5):
            pipeline_calls.append((retrieval_top_n, rerank_top_k))
            return {
                "answer": "작업발판 폭은 40cm 이상이어야 합니다 [1].",
                "error": None,
                "outcome_code": "answered",
                "intent": "rag_query",
                "should_retrieve": True,
                "retry_count": 0,
                "retrieved_chunks": [
                    {"chunk_id": "gold1", "document_id": "doc1",
                     "text": "작업발판 폭은 40cm 이상 이어야 한다", "score": 0.8},
                ],
                 "reranked_chunks": [
                     {"chunk_id": "gold1", "document_id": "doc1",
                      "text": "작업발판 폭은 40cm 이상 이어야 한다", "score": 0.9},
                 ],
                "final_context": "작업발판 폭은 40cm 이상 이어야 한다",
                "context_chunks": [
                    {"chunk_id": "gold1", "document_id": "doc1",
                     "text": "작업발판 폭은 40cm 이상 이어야 한다", "score": 0.9},
                ],
                    "citations": [
                        {"citation_id": 1, "chunk_id": "gold1", "document_id": "doc1",
                         "referenced_in_answer": True,
                         "original_filename": "안전.pdf", "chunk_text": "작업발판 폭은 40cm 이상"},
                ],
                "timing": {"retrieve": 12.0},
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                "latency_ms": 1234,
            }

    class _FakeEmbedder:
        async def embed(self, texts):
            return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(e2e, "_get_pipeline", lambda: _FakePipeline())
    monkeypatch.setattr(e2e, "EvalEmbedder", lambda: _FakeEmbedder())

    item = {
        "question": "작업발판 폭 기준은?",
        "gold_answer": "작업발판 폭은 40cm 이상이어야 한다.",
        "gold_chunk_ids": json.dumps(["gold1"]),
        "gold_document_ids": json.dumps(["doc1"]),
        "gold_chunk_texts": json.dumps(["작업발판 폭은 40cm 이상 이어야 한다"]),
        "expected_behavior": "answer",
    }
    fields = asyncio.run(e2e.evaluate_end_to_end(
        item,
        {
            "retrieval_top_n": 12,
            "rerank_top_k": 4,
            "answer_correctness_f2": {"enabled": True},
        },
        "coll",
    ))

    assert pipeline_calls == [(12, 4)]
    assert fields["answer_text"].startswith("작업발판")
    assert "judge_json" not in fields
    # 2026.11.17(sooyeon.choi) 수정 - Answer Correctness는 F2 단일(answer_correctness_json),
    #   v1·v2·judge·similarity·rule_check 필드는 더 이상 만들지 않는다.
    for removed in (
        "similarity", "answer_correctness_v1_json", "answer_correctness_v2_json",
        "answer_correctness_f2_json", "answer_correctness_judge_json", "rule_check_json",
    ):
        assert removed not in fields
    correctness = fields["answer_correctness_json"]
    assert correctness["status"] == "evaluated"
    assert correctness["value"] == pytest.approx(1.0)
    assert correctness["metadata"]["method"] == "sentence_alignment_f2"
    assert correctness["metadata"]["beta"] == pytest.approx(2.0)
    assert correctness["metadata"]["gold_coverage"] == pytest.approx(1.0)
    # 응답시간은 어댑터가 잰 그래프 실행 시간
    assert fields["latency_ms"] == 1234
    # 검색 지표는 K=1,3,5,10 고정 + 설정 N/K
    rrf = fields["retrieval_json"]["rrf"]
    assert rrf["hit@10"] == pytest.approx(1.0)
    assert rrf["recall@12"] == pytest.approx(1.0)
    assert "fail@10" not in rrf and "top1_is_relevant" not in rrf and "rr" not in rrf
    assert not any(key.startswith("document_") for key in rrf)
    rerank = fields["retrieval_json"]["rerank"]
    assert rerank["ndcg@4"] == pytest.approx(1.0)
    assert rerank["ndcg@5"] == pytest.approx(1.0)
    # 규칙 기반 citation 주요 지표
    assert fields["citation_json"]["correctness"] == pytest.approx(1.0)
    assert fields["citation_json"]["completeness"] == pytest.approx(1.0)
    for removed in ("citation_f1", "citation_validity", "doc_recall", "document_f1", "citation_relevance"):
        assert removed not in fields["citation_json"]
    assert "accuracy" not in fields["citation_json"]
    # 상세 + ①축
    assert fields["citation_detail_json"]["cited"][0]["citation_id"] == 1
    assert fields["citation_detail_json"]["diagnostics"]["cited_chunk_ids"] == ["gold1"]
    assert fields["guardrail_json"]["intent"] == "rag_query"
    assert fields["threshold_fallback_json"]["correct"] is True


def test_evaluate_end_to_end_refusal_case_is_ok(monkeypatch):
    """not_enough_info 케이스에서 답변 미생성은 정상(status ok)."""
    from app.evaluation.runner import e2e_evaluator as e2e

    class _FakePipeline:
        async def run(self, query, collection_name, retrieval_top_n=10, rerank_top_k=5):
            return {"answer": "", "error": None, "outcome_code": "refused",
                    "intent": "rag_query", "should_retrieve": True, "retry_count": 0,
                    "reranked_chunks": [], "final_context": "", "context_chunks": [],
                    "citations": [], "timing": {}, "usage": None}

    monkeypatch.setattr(e2e, "_get_pipeline", lambda: _FakePipeline())
    item = {"question": "문서에 없는 질문", "gold_answer": "",
            "gold_chunk_ids": "[]", "gold_document_ids": "[]", "gold_chunk_texts": "[]",
            "expected_behavior": "not_enough_info"}
    fields = asyncio.run(e2e.evaluate_end_to_end(item, {}, "coll"))
    assert fields["status"] == "ok"
    assert fields["threshold_fallback_json"]["correct"] is True


@pytest.mark.parametrize("rerank_status,marker", [("ok", None), ("error", "error"), ("skipped", "skipped")])
def test_pipeline_search_metrics_are_independent_of_answer_error(rerank_status, marker):
    from app.evaluation.runner.e2e_evaluator import _compute_pipeline_retrieval_metrics

    metrics = _compute_pipeline_retrieval_metrics(
        result={"outcome_code": "llm_error", "retrieval_status": "ok", "rerank_status": rerank_status,
                "retrieved_chunks": [{"chunk_id": "g"}], "reranked_chunks": [{"chunk_id": "g"}]},
        gold_chunk_ids={"g"}, retrieval_top_n=10, rerank_top_k=5,
    )
    assert metrics["rrf"]["hit@10"] == 1.0
    if marker:
        assert metrics["rerank"][marker] is True
        assert "ndcg@5" not in metrics["rerank"]
    else:
        assert metrics["rerank"]["ndcg@5"] == 1.0


def test_evaluate_end_to_end_scores_missing_required_answer_as_zero(monkeypatch):
    from app.evaluation.runner import e2e_evaluator as e2e

    class _FakePipeline:
        async def run(self, query, collection_name, retrieval_top_n=10, rerank_top_k=5):
            return {
                "answer": "", "error": None, "outcome_code": "no_answer",
                "intent": "rag_query", "should_retrieve": True, "retry_count": 0,
                "reranked_chunks": [], "final_context": "", "context_chunks": [],
                "citations": [], "timing": {}, "usage": None,
            }

    monkeypatch.setattr(e2e, "_get_pipeline", lambda: _FakePipeline())
    fields = asyncio.run(e2e.evaluate_end_to_end(
        {
            "question": "답변이 필요한 질문",
            "gold_answer": "골드 답변",
            "gold_chunk_ids": json.dumps(["gold1"]),
            "gold_document_ids": json.dumps(["doc1"]),
            "gold_chunk_texts": "[]",
            "expected_behavior": "answer",
        },
        {},
        "coll",
    ))

    assert fields["status"] == "ok"
    assert fields["answer_correctness_json"]["status"] == "evaluated"
    assert fields["answer_correctness_json"]["value"] == 0.0
    assert fields["answer_correctness_json"]["reason"] == "empty_system_answer"
    assert fields["citation_json"]["correctness"] == 0.0
    assert fields["citation_json"]["completeness"] == 0.0


@pytest.mark.parametrize("expected_behavior", ["guardrail", "permission_denied"])
def test_evaluate_end_to_end_skips_similarity_for_blocked_behaviors(
    monkeypatch, expected_behavior
):
    from app.evaluation.runner import e2e_evaluator as e2e

    class _FakePipeline:
        async def run(self, query, collection_name, retrieval_top_n=10, rerank_top_k=5):
            return {
                "answer": "차단되어야 하지만 생성된 답변입니다.",
                "error": "permission denied" if expected_behavior == "permission_denied" else None,
                "outcome_code": "answered",
                "intent": "blocked",
                "should_retrieve": expected_behavior != "guardrail",
                "retry_count": 0,
                "reranked_chunks": [],
                "final_context": "",
                "context_chunks": [],
                "citations": [],
                "timing": {},
                "usage": None,
            }

    class _FailIfCalledEmbedder:
        async def embed(self, texts):
            raise AssertionError("blocked behavior must not calculate similarity")

    monkeypatch.setattr(e2e, "_get_pipeline", lambda: _FakePipeline())
    monkeypatch.setattr(e2e, "EvalEmbedder", lambda: _FailIfCalledEmbedder())

    fields = asyncio.run(e2e.evaluate_end_to_end(
        {
            "question": "차단 대상 질문",
            "gold_answer": "비교 대상 기준 답변",
            "gold_chunk_ids": "[]",
            "gold_document_ids": "[]",
            "gold_chunk_texts": "[]",
            "expected_behavior": expected_behavior,
        },
        {},
        "coll",
    ))

    assert "similarity" not in fields
    assert fields["answer_correctness_json"]["status"] == "excluded"
    assert fields["answer_correctness_json"]["reason"] == "expected_behavior_not_answer"
    assert fields["citation_json"]["skipped"] is True
    assert fields["retrieval_json"]["rrf"] == {
        "skipped": True,
        "reason": expected_behavior,
    }


# ── ①축 집계 ─────────────────────────────────────────────────────────────────

@pytest.fixture
def repo(tmp_path):
    db = database.get_database_manager()
    db.execute_update(
        "INSERT INTO tb_collections (display_name, qdrant_name) VALUES (?, ?)",
        ("컬렉션", "e2e_agg_coll"),
    )
    cid = db.execute_query(
        "SELECT collection_id FROM tb_collections WHERE qdrant_name = ?", ("e2e_agg_coll",),
    )[0]["collection_id"]
    r = EvalRepository()
    r._cid = cid
    return r


def test_aggregate_includes_first_class_axis_metrics(repo):
    from app.evaluation.runner.eval_runner import _aggregate_and_save_metrics
    ds = repo.create_dataset("d", repo._cid, {})
    qa1 = repo.insert_qa_item(ds, "q1", "a1", ["c1"], ["d1"], ["t1"], "factual",
                              expected_behavior="answer", tags=["legal_reference"])
    qa2 = repo.insert_qa_item(ds, "q2", "거절", [], [], [], "factual",
                              expected_behavior="not_enough_info")
    repo.update_qa_item(qa1, review_status="approved")
    repo.update_qa_item(qa2, review_status="approved")
    goldset_id = repo.create_goldset(ds)
    snap = json.loads(repo.get_goldset(goldset_id)["items_snapshot_json"])
    run_id = repo.create_run(goldset_id, "full", {}, total=2)

    repo.insert_item_result(
        run_id, snap[0]["qa_id"], status="ok",
        citation_json={"correctness": 1.0, "completeness": 1.0, "citation_count": 3},
        answer_correctness_json={"value": 0.8, "status": "evaluated", "reason": None, "metadata": {}},
        threshold_fallback_json={"correct": True},
        latency_ms=1500,
    )
    repo.insert_item_result(
        run_id, snap[1]["qa_id"], status="ok",
        threshold_fallback_json={"correct": True},
        guardrail_json={"refusal_correct": True, "format_correct": False},
    )
    _aggregate_and_save_metrics(repo, run_id, snap)
    mets = {(m["metric_key"], m["segment"]): m["metric_value"] for m in repo.get_run_metrics(run_id)}

    assert mets[("answer.correctness", "all")] == pytest.approx(0.8)
    assert ("answer.llm_correctness_mean", "all") not in mets
    assert ("judge.accuracy.mean", "all") not in mets
    assert mets[("citation.correctness", "all")] == pytest.approx(1.0)
    assert mets[("answer.behavior_correct_rate", "all")] == pytest.approx(1.0)  # 둘 다 correct
    assert mets[("answer.refusal_correct_rate", "all")] == pytest.approx(1.0)   # 해당 1건만
    # 2026.11.17(sooyeon.choi) 수정 - 삭제 지표는 집계되지 않는다
    for removed in (
        "answer.correctness_mean", "answer.similarity.mean", "answer.rule_match.mean",
        "answer.format_correct_rate", "latency.mean_ms", "citation.citation_count",
    ):
        assert (removed, "all") not in mets
    # tag 세그먼트도 유지
    assert mets[("citation.correctness", "tag:legal_reference")] == pytest.approx(1.0)

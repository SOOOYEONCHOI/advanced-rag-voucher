"""평가 실행 파이프라인(runner/adapters/metrics) 테스트 — P2.

라이브 Qdrant/vLLM 없이 검증 가능한 범위:
  - ports/adapters/metrics/runner 모듈 import (어댑터 wiring 컴파일)
  - compute_channel_metrics 핵심 KPI(recall@5/hit@5)
  - _item_segments (all + type:* + tag:*)
  - _aggregate_and_save_metrics: KPI 키(retrieval.rrf.recall@5 / retrieval.rerank.hit@5),
    Answer Correctness 정규화, tag/type 세그먼트 저장
  - run_registry 취소 토큰
실제 검색 어댑터→Qdrant 연동은 라이브 스택에서 P3 실행 검증으로 확인한다.
"""

import json
import asyncio

import pytest

from app.repositories import database
from app.repositories.evaluation_repository import EvalRepository


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


@pytest.fixture
def repo(tmp_path):
    db = database.get_database_manager(str(tmp_path / "eval.db"))
    db.execute_update(
        "INSERT INTO tb_collections (display_name, qdrant_name) VALUES (?, ?)",
        ("평가용 컬렉션", "eval_runner_coll"),
    )
    cid = db.execute_query(
        "SELECT collection_id FROM tb_collections WHERE qdrant_name = ?",
        ("eval_runner_coll",),
    )[0]["collection_id"]
    r = EvalRepository()
    r._test_collection_id = cid
    return r


# ── 모듈 import (어댑터 wiring 컴파일) ────────────────────────────────────────

def test_service_modules_import():
    import app.evaluation.ports  # noqa: F401
    import app.evaluation.metrics.retrieval_metrics  # noqa: F401
    import app.evaluation.adapters.retrieval_adapter  # noqa: F401
    import app.evaluation.adapters.reranker_adapter  # noqa: F401
    import app.evaluation.runner.eval_runner  # noqa: F401
    import app.evaluation.runner.run_registry  # noqa: F401


# ── 순수 지표 ────────────────────────────────────────────────────────────────

def test_compute_channel_metrics_recall_and_hit_at_5():
    from app.evaluation.metrics.retrieval_metrics import compute_channel_metrics
    # 정답 2개 중 top5에 1개(3순위) 포함
    retrieved = ["x", "y", "gold1", "z", "w", "gold2"]
    gold = {"gold1", "gold2"}
    m = compute_channel_metrics(retrieved, gold, (1, 3, 5, 10))
    assert m["hit@5"] == 1.0
    assert m["recall@5"] == 0.5          # top5에 정답 1/2
    assert m["recall@10"] == 1.0
    assert m["rr"] == pytest.approx(1 / 3)
    assert m["gold_ranks"] == [3, 6]


def test_compute_channel_metrics_matches_evaluation_na_and_top_k_mrr():
    from app.evaluation.metrics.retrieval_metrics import compute_channel_metrics

    empty_gold = compute_channel_metrics(["x"], set(), (5,))
    assert empty_gold["recall@5"] is None
    assert empty_gold["hit@5"] is None
    assert empty_gold["ndcg@5"] is None
    assert empty_gold["rr"] is None

    outside_k = compute_channel_metrics(
        ["x1", "x2", "x3", "x4", "x5", "gold"], {"gold"}, (5,)
    )
    assert outside_k["rr"] == 0.0
    assert outside_k["evidence_rank"] is None


# ── 세그먼트 산정 ────────────────────────────────────────────────────────────

def test_item_segments_includes_type_and_tags():
    from app.evaluation.runner.eval_runner import _item_segments
    item = {"question_type": "factual", "tags": json.dumps(["legal_reference", "abbreviation"])}
    assert _item_segments(item) == ["all", "type:factual", "tag:legal_reference", "tag:abbreviation"]

    # tags가 리스트로 들어와도 처리
    assert _item_segments({"question_type": "multihop", "tags": ["compound_term"]}) == [
        "all", "type:multihop", "tag:compound_term"
    ]
    assert _item_segments({}) == ["all"]


def test_full_item_uses_single_e2e_result_for_retrieval(monkeypatch):
    from app.evaluation.runner import e2e_evaluator
    from app.evaluation.runner.eval_runner import _evaluate_item

    calls = []

    async def fake_evaluate(item, config, collection_name):
        calls.append((item["question"], config["retrieval_top_n"], collection_name))
        return {
            "status": "ok",
            "retrieval_json": {
                "rrf": {"recall@10": 1.0},
                "rerank": {"ndcg@5": 1.0},
            },
        }

    monkeypatch.setattr(e2e_evaluator, "evaluate_end_to_end", fake_evaluate)
    fields = asyncio.run(_evaluate_item(
        {"question": "q"},
        "full",
        {"retrieval_top_n": 10, "rerank_top_k": 5},
        "collection",
    ))

    assert calls == [("q", 10, "collection")]
    assert fields["retrieval_json"]["rrf"]["recall@10"] == 1.0


# ── 집계 (KPI 키 + 세그먼트) ─────────────────────────────────────────────────

def _seed_run_with_two_items(repo, tags1):
    ds = repo.create_dataset("데이터셋", repo._test_collection_id, {})
    qa1 = repo.insert_qa_item(ds, "q1", "a1", ["c1"], ["d1"], ["t1"], "factual",
                              tags=tags1)
    qa2 = repo.insert_qa_item(ds, "q2", "a2", ["c2"], ["d2"], ["t2"], "multihop")
    repo.update_qa_item(qa1, review_status="approved")
    repo.update_qa_item(qa2, review_status="approved")
    goldset_id = repo.create_goldset(ds)
    snapshot = json.loads(repo.get_goldset(goldset_id)["items_snapshot_json"])
    run_id = repo.create_run(
        goldset_id, "full",
        {
            "top_k": 10,
            "rerank_top_k": 5,
            "answer_correctness_f2": {"enabled": True, "metric_version": "f2.1"},
        },
        total=2,
    )
    return run_id, snapshot


def test_aggregate_produces_kpi_keys_and_segments(repo):
    from app.evaluation.runner.eval_runner import _aggregate_and_save_metrics
    run_id, snapshot = _seed_run_with_two_items(repo, tags1=["legal_reference"])

    # 신규 규칙 기반 실행은 judge와 legacy citation accuracy를 집계하지 않는다.
    repo.insert_item_result(
        run_id, snapshot[0]["qa_id"], status="ok",
        retrieval_json={"rrf": {"recall@5": 1.0}, "rerank": {"hit@5": 1.0}},
        similarity=0.9,
        answer_correctness_v2_json={"value": 0.8, "status": "evaluated", "metadata": {"metric_version": "rule-v2-shadow.1"}},
        answer_correctness_f2_json={"value": 0.9, "status": "evaluated", "metadata": {"metric_version": "rule-v2-f2-shadow.1"}},
        citation_json={"correctness": 1.0, "completeness": 1.0},
        latency_ms=1000,
    )
    repo.insert_item_result(
        run_id, snapshot[1]["qa_id"], status="ok",
        retrieval_json={"rrf": {"recall@5": 0.0}, "rerank": {"hit@5": 0.0}},
        similarity=0.7,
        answer_correctness_v2_json={"value": 0.6, "status": "evaluated", "metadata": {"metric_version": "rule-v2-shadow.1"}},
        answer_correctness_f2_json={"value": 0.8, "status": "evaluated", "metadata": {"metric_version": "rule-v2-f2-shadow.1"}},
        citation_json={"correctness": 0.0, "completeness": 0.0},
        latency_ms=2000,
    )

    _aggregate_and_save_metrics(repo, run_id, snapshot)
    mets = {(m["metric_key"], m["segment"]): m["metric_value"] for m in repo.get_run_metrics(run_id)}

    # 핵심 KPI 키 (all)
    assert mets[("retrieval.rrf.recall@5", "all")] == pytest.approx(0.5)
    assert mets[("retrieval.rerank.hit@5", "all")] == pytest.approx(0.5)
    assert mets[("citation.correctness", "all")] == pytest.approx(0.5)
    assert mets[("answer.correctness_mean", "all")] == pytest.approx(0.8)
    assert mets[("answer.correctness_v2_shadow", "all")] == pytest.approx(0.7)
    assert mets[("answer.correctness_v2_f2_shadow", "all")] == pytest.approx(0.85)
    assert ("citation.accuracy", "all") not in mets
    assert ("answer.llm_correctness_mean", "all") not in mets
    assert ("judge.accuracy.mean", "all") not in mets

    # type 세그먼트
    assert mets[("retrieval.rrf.recall@5", "type:factual")] == pytest.approx(1.0)
    assert mets[("retrieval.rrf.recall@5", "type:multihop")] == pytest.approx(0.0)
    # ①축 tag 세그먼트 (legal_reference는 item1에만)
    assert mets[("retrieval.rrf.recall@5", "tag:legal_reference")] == pytest.approx(1.0)
    # std 보조지표 + latency + error_rate
    assert ("retrieval.rrf.recall@5.std", "all") in mets
    assert mets[("latency.mean_ms", "all")] == pytest.approx(1500.0)
    assert mets[("run.error_rate", "all")] == pytest.approx(0.0)


def test_aggregate_counts_error_rate(repo):
    from app.evaluation.runner.eval_runner import _aggregate_and_save_metrics
    run_id, snapshot = _seed_run_with_two_items(repo, tags1=[])
    repo.insert_item_result(run_id, snapshot[0]["qa_id"], status="ok",
                            retrieval_json={"rrf": {"recall@5": 1.0}})
    repo.insert_item_result(run_id, snapshot[1]["qa_id"], status="error",
                            error_message="boom")
    _aggregate_and_save_metrics(repo, run_id, snapshot)
    mets = {(m["metric_key"], m["segment"]): m["metric_value"] for m in repo.get_run_metrics(run_id)}
    assert mets[("run.error_rate", "all")] == pytest.approx(0.5)
    # error 항목은 지표 평균에서 제외 → recall@5 all = 1.0 (성공 1건만)
    assert mets[("retrieval.rrf.recall@5", "all")] == pytest.approx(1.0)


# ── 취소 레지스트리 ──────────────────────────────────────────────────────────

def test_run_registry_cancel_flow():
    from app.evaluation.runner import run_registry

    class _FakeTask:
        pass

    run_registry.register(999, _FakeTask())
    assert run_registry.is_cancel_requested(999) is False
    assert run_registry.request_cancel(999) is True
    assert run_registry.is_cancel_requested(999) is True
    run_registry.unregister(999)
    # 등록되지 않은 run 취소는 False
    assert run_registry.request_cancel(999) is False

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
    db = database.get_database_manager()
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
    assert m["rr@5"] == pytest.approx(1 / 3)
    assert m["gold_ranks"] == [3, 6]
    # 2026.11.17(sooyeon.choi) 수정 - 중복 지표(fail@k, rr, top1_is_relevant) 삭제
    assert "fail@5" not in m and "rr" not in m and "top1_is_relevant" not in m


def test_is_aggregated_retrieval_metric_whitelist():
    # 2026.11.17(sooyeon.choi) 추가 - 순위·건수·임계값은 평균 대상이 아니다
    from app.evaluation.metrics.retrieval_metrics import is_aggregated_retrieval_metric

    for key in ("hit@10", "recall@10", "ndcg@5", "rr@5"):
        assert is_aggregated_retrieval_metric(key)
    for key in ("evidence_rank", "evidence_count", "total_retrieved", "threshold", "gold_ranks", "fail@5"):
        assert not is_aggregated_retrieval_metric(key)


def test_compute_channel_metrics_matches_evaluation_na_and_top_k_mrr():
    from app.evaluation.metrics.retrieval_metrics import compute_channel_metrics

    empty_gold = compute_channel_metrics(["x"], set(), (5,))
    assert empty_gold["recall@5"] is None
    assert empty_gold["hit@5"] is None
    assert empty_gold["ndcg@5"] is None
    assert empty_gold["rr@5"] is None

    outside_k = compute_channel_metrics(
        ["x1", "x2", "x3", "x4", "x5", "gold"], {"gold"}, (5,)
    )
    assert outside_k["rr@5"] == 0.0
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
    # 2026.11.17(sooyeon.choi) 수정 - answer.correctness(F2)만 집계, 진단값(evidence_rank 등)은 평균하지 않음
    repo.insert_item_result(
        run_id, snapshot[0]["qa_id"], status="ok",
        retrieval_json={"rrf": {"recall@5": 1.0, "evidence_rank": 1, "total_retrieved": 40},
                        "rerank": {"hit@5": 1.0, "threshold": 0.3}},
        answer_correctness_json={"value": 0.9, "status": "evaluated", "metadata": {}},
        citation_json={"correctness": 1.0, "completeness": 1.0},
        latency_ms=1000,
    )
    repo.insert_item_result(
        run_id, snapshot[1]["qa_id"], status="ok",
        retrieval_json={"rrf": {"recall@5": 0.0}, "rerank": {"hit@5": 0.0}},
        answer_correctness_json={"value": 0.8, "status": "evaluated", "metadata": {}},
        citation_json={"correctness": 0.0, "completeness": 0.0},
        latency_ms=2000,
    )

    _aggregate_and_save_metrics(repo, run_id, snapshot)
    mets = {(m["metric_key"], m["segment"]): m["metric_value"] for m in repo.get_run_metrics(run_id)}

    # 핵심 KPI 키 (all)
    assert mets[("retrieval.rrf.recall@5", "all")] == pytest.approx(0.5)
    assert mets[("retrieval.rerank.hit@5", "all")] == pytest.approx(0.5)
    assert mets[("citation.correctness", "all")] == pytest.approx(0.5)
    assert mets[("answer.correctness", "all")] == pytest.approx(0.85)
    for removed in (
        "answer.correctness_mean", "answer.correctness_v2_shadow", "answer.correctness_v2_f2_shadow",
        "answer.correctness.f2", "retrieval.rrf.evidence_rank", "retrieval.rrf.total_retrieved",
        "retrieval.rerank.threshold", "latency.mean_ms",
    ):
        assert (removed, "all") not in mets
    assert ("citation.accuracy", "all") not in mets
    assert ("answer.llm_correctness_mean", "all") not in mets
    assert ("judge.accuracy.mean", "all") not in mets

    # type 세그먼트
    assert mets[("retrieval.rrf.recall@5", "type:factual")] == pytest.approx(1.0)
    assert mets[("retrieval.rrf.recall@5", "type:multihop")] == pytest.approx(0.0)
    # ①축 tag 세그먼트 (legal_reference는 item1에만)
    assert mets[("retrieval.rrf.recall@5", "tag:legal_reference")] == pytest.approx(1.0)
    # std 보조지표 + error_rate
    assert ("retrieval.rrf.recall@5.std", "all") in mets
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


def test_aggregate_agreement_metrics_use_all_queries_and_response_time(repo):
    # 2026.11.19(sooyeon.choi) 추가 - 합의서 시험 1·2 분모 = 전체 질의 수, 시험 4 평균 반환 시간(ms)
    from app.evaluation.runner.eval_runner import _aggregate_and_save_metrics

    ds = repo.create_dataset("데이터셋", repo._test_collection_id, {})
    qa_ids = [repo.insert_qa_item(ds, f"q{i}", "a", [f"c{i}"], ["d"], ["t"], "law") for i in range(4)]
    for qa_id in qa_ids:
        repo.update_qa_item(qa_id, review_status="approved")
    goldset_id = repo.create_goldset(ds)
    snapshot = json.loads(repo.get_goldset(goldset_id)["items_snapshot_json"])
    run_id = repo.create_run(goldset_id, "full", {"retrieval_top_n": 10, "rerank_top_k": 5}, total=4)

    def ok(qa_id, hit, ndcg, latency, first_token):
        repo.insert_item_result(
            run_id, qa_id, status="ok",
            retrieval_json={"rrf": {"hit@10": hit}, "rerank": {"ndcg@5": ndcg}},
            latency_ms=latency, timing_json={"first_token_ms": first_token},
        )

    ok(qa_ids[0], 1.0, 1.0, 9000, 2000.0)
    ok(qa_ids[1], 1.0, 0.5, 11000, None)
    repo.insert_item_result(  # 정답 청크 없음 → 제외(분모에는 포함, 0)
        run_id, qa_ids[2], status="ok",
        retrieval_json={"rrf": {"hit@10": None}, "rerank": {"ndcg@5": None}}, latency_ms=10000,
    )
    repo.insert_item_result(run_id, qa_ids[3], status="error", error_message="boom")

    _aggregate_and_save_metrics(repo, run_id, snapshot)
    rows = {m["metric_key"]: m for m in repo.get_run_metrics(run_id) if m["segment"] == "all"}

    recall = rows["retrieval.rrf.hit@10"]
    assert recall["metric_value"] == pytest.approx(2 / 4)                     # 2 적중 / 전체 4
    assert (recall["evaluated_count"], recall["excluded_count"], recall["error_count"]) == (2, 1, 1)
    assert rows["retrieval.rerank.ndcg@5"]["metric_value"] == pytest.approx(1.5 / 4)
    response = rows["answer.response_time_ms"]
    assert response["metric_value"] is None  # 오류 항목의 시간 누락 → 부분 평균 금지
    assert response["excluded_count"] == 1
    assert rows["answer.first_token_ms"]["metric_value"] == pytest.approx(2000.0)
    assert "answer.judge_accuracy" not in rows                                 # 미구현 → 미측정(오류로 채우지 않음)


def test_aggregate_keeps_successful_search_and_error_latency():
    from types import SimpleNamespace
    from app.evaluation.runner.eval_runner import _aggregate_and_save_metrics

    saved = {}
    rows = [
        {"qa_id": 1, "status": "error", "latency_ms": 9000,
         "retrieval_json": json.dumps({"rrf": {"hit@10": 1.0}, "rerank": {"error": True}})},
        {"qa_id": 2, "status": "error", "latency_ms": 11000},
    ]
    repo = SimpleNamespace(
        list_item_results=lambda *_a, **_k: {"items": rows},
        get_run=lambda _id: {"run_type": "full", "config_json": "{}"},
        save_run_metrics=lambda _id, metrics: saved.update(metrics),
    )
    _aggregate_and_save_metrics(repo, 1, [{"qa_id": 1}, {"qa_id": 2}])
    assert saved["all"]["retrieval.rrf.hit@10"]["value"] == 0.5
    assert saved["all"]["retrieval.rerank.ndcg@5"]["value"] == 0.0
    assert saved["all"]["answer.response_time_ms"]["value"] == 10000
    assert saved["all"]["answer.response_time_ms"]["evaluated_count"] == 2
    saved.clear()
    repo.list_item_results = lambda *_a, **_k: {"items": rows[:1]}
    _aggregate_and_save_metrics(repo, 1, [{"qa_id": 1}, {"qa_id": 2}])
    assert saved["all"]["answer.response_time_ms"]["value"] is None
    assert saved["all"]["answer.response_time_ms"]["total_count"] == 2
    assert "answer.response_time_ms.std" not in saved["all"]


def test_full_run_executes_queries_sequentially(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from app.evaluation.runner import eval_runner as runner

    order = []
    items = [{"qa_id": 1}, {"qa_id": 2}]
    repo = SimpleNamespace(
        get_run=lambda _id: {"goldset_id": 1, "run_type": "full", "config_json": '{"concurrency": 8}'},
        get_goldset=lambda _id: {"qdrant_name": "test", "items_snapshot_json": json.dumps(items)},
        update_run_status=lambda *_a: None, increment_run_progress=lambda *_a: None,
        insert_item_result=lambda *_a, **_k: None,
    )

    async def evaluate(item, *_args):
        order.append(("start", item["qa_id"]))
        await asyncio.sleep(0)
        order.append(("end", item["qa_id"]))
        return {"status": "ok"}

    monkeypatch.setattr(runner, "EvalRepository", lambda: repo)
    monkeypatch.setattr(runner, "_evaluate_item", evaluate)
    monkeypatch.setattr(runner, "_aggregate_and_save_metrics", lambda *_args: None)
    asyncio.run(runner._execute_run(999))
    assert order == [("start", 1), ("end", 1), ("start", 2), ("end", 2)]

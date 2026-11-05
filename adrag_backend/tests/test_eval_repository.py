"""평가 시스템 저장소(EvalRepository) 테스트 — P1.

통합 schema.sql에 추가된 tb_eval_* 6테이블 CRUD와 ①축 확장 컬럼
(expected_behavior/tags/threshold_fallback_json/guardrail_json), 골드셋 스냅샷,
지표 세그먼트 집계, RESTRICT 삭제 경로를 검증한다.
"""

import json

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
    """임시 DB 초기화 + 부모 컬렉션 1건 생성 후 EvalRepository 반환."""
    db = database.get_database_manager(str(tmp_path / "eval.db"))
    db.execute_update(
        "INSERT INTO tb_collections (display_name, qdrant_name) VALUES (?, ?)",
        ("평가용 컬렉션", "eval_test_coll"),
    )
    rows = db.execute_query(
        "SELECT collection_id FROM tb_collections WHERE qdrant_name = ?",
        ("eval_test_coll",),
    )
    collection_id = rows[0]["collection_id"]
    r = EvalRepository()
    r._test_collection_id = collection_id  # 테스트 편의
    return r


def _seed_finalized_run(repo):
    """dataset → 승인 QA 2건 → goldset 확정 → run 생성까지 만들고 (run_id, goldset_id, snapshot) 반환."""
    ds = repo.create_dataset("데이터셋", repo._test_collection_id, {"target_count": 2})
    qa1 = repo.insert_qa_item(
        ds, "제7조의3 안전관리자 선임 기준은?", "정답1",
        ["chunk-a"], ["doc-a"], ["근거텍스트1"], "factual",
        self_valid_rank=1, expected_behavior="answer", tags=["legal_reference"],
    )
    qa2 = repo.insert_qa_item(
        ds, "문서에 없는 질문", "근거 없음",
        [], [], [], "factual", expected_behavior="not_enough_info", tags=["unanswerable"],
    )
    repo.update_qa_item(qa1, review_status="approved")
    repo.update_qa_item(qa2, review_status="edited", gold_answer="수정된 정답")
    goldset_id = repo.create_goldset(ds, note="v1")
    snapshot = json.loads(repo.get_goldset(goldset_id)["items_snapshot_json"])
    run_id = repo.create_run(goldset_id, "full", {"top_k": 10, "rerank_top_k": 5}, total=2)
    return ds, goldset_id, run_id, snapshot


def test_dataset_join_exposes_qdrant_name(repo):
    ds = repo.create_dataset("데이터셋", repo._test_collection_id, {"target_count": 5})
    got = repo.get_dataset(ds)
    assert got["qdrant_name"] == "eval_test_coll"
    assert got["collection_name"] == "평가용 컬렉션"


def test_qa_item_persists_first_class_axis_columns(repo):
    ds = repo.create_dataset("데이터셋", repo._test_collection_id, {})
    qa = repo.insert_qa_item(
        ds, "질문", "정답", ["c1"], ["d1"], ["t1"], "factual",
        expected_behavior="not_enough_info", tags=["abbreviation", "compound_term"],
    )
    row = repo.get_qa_item(qa)
    assert row["expected_behavior"] == "not_enough_info"
    assert json.loads(row["tags"]) == ["abbreviation", "compound_term"]


def test_qa_review_bumps_dataset_updated_at(repo):
    """검수(승인/수정)가 데이터셋의 최종 수정일(updated_at)에 반영되어야 한다."""
    ds = repo.create_dataset("데이터셋", repo._test_collection_id, {})
    qa = repo.insert_qa_item(ds, "q1", "a1", ["c1"], ["d1"], ["t1"], "factual")

    # updated_at을 과거로 고정해 두고, 검수 후 값이 바뀌는지 확인
    # 2026.10.16 수정 - 0002의 updated_at 트리거가 과거 값을 덮어쓰므로 준비 단계에서만 트리거를 끈다
    with repo._db.get_connection() as conn:
        conn.execute("ALTER TABLE tb_eval_datasets DISABLE TRIGGER trg_tb_eval_datasets_touch_updated_at")
        conn.execute(
            "UPDATE tb_eval_datasets SET updated_at = ? WHERE dataset_id = ?",
            ("2000-01-01T00:00:00+09:00", ds),
        )
        conn.execute("ALTER TABLE tb_eval_datasets ENABLE TRIGGER trg_tb_eval_datasets_touch_updated_at")
    before = repo.get_dataset(ds)["updated_at"]
    assert before == "2000-01-01T00:00:00+09:00"

    repo.update_qa_item(qa, review_status="approved")

    after = repo.get_dataset(ds)["updated_at"]
    assert after != before, "검수 후 데이터셋 updated_at이 갱신되어야 함"
    assert after > before


def test_create_goldset_snapshots_only_approved_and_edited(repo):
    ds = repo.create_dataset("데이터셋", repo._test_collection_id, {})
    qa_ok = repo.insert_qa_item(ds, "q1", "a1", ["c1"], ["d1"], ["t1"], "factual")
    repo.insert_qa_item(ds, "q2", "a2", ["c2"], ["d2"], ["t2"], "factual")  # pending → 제외
    qa_rej = repo.insert_qa_item(ds, "q3", "a3", ["c3"], ["d3"], ["t3"], "factual")
    repo.update_qa_item(qa_ok, review_status="approved")
    repo.update_qa_item(qa_rej, review_status="rejected")

    goldset_id = repo.create_goldset(ds)
    snapshot = json.loads(repo.get_goldset(goldset_id)["items_snapshot_json"])
    assert len(snapshot) == 1 and snapshot[0]["qa_id"] == qa_ok
    assert repo.get_dataset(ds)["status"] == "finalized"


def test_create_goldset_returns_none_without_approved_items(repo):
    ds = repo.create_dataset("데이터셋", repo._test_collection_id, {})
    repo.insert_qa_item(ds, "q1", "a1", ["c1"], ["d1"], ["t1"], "factual")  # pending
    assert repo.create_goldset(ds) is None


def test_item_results_join_snapshot_and_axis_json(repo):
    _, _, run_id, snapshot = _seed_finalized_run(repo)
    repo.update_run_status(run_id, "running")
    repo.insert_item_result(
        run_id, snapshot[0]["qa_id"], status="ok",
        retrieval_json={"rrf": {"recall@5": 1.0}, "rerank": {"hit@5": 1.0}},
        judge_json={"accuracy": 5},
        answer_correctness_v1_json={"value": 0.9, "status": "evaluated", "metadata": {}},
        answer_correctness_v2_json={"value": 0.85, "status": "evaluated", "metadata": {}},
        answer_correctness_f2_json={"value": 0.92, "status": "evaluated", "metadata": {}},
        answer_correctness_judge_json={
            "value": 0.75,
            "status": "evaluated",
            "metadata": {"method": "ragas_answer_accuracy"},
        },
        answer_correctness_json={
            "value": 0.75,
            "status": "evaluated",
            "metadata": {"selected_metric": "judge"},
        },
        threshold_fallback_json={"correct": True, "retry_count": 0},
        guardrail_json={"intent": "qa", "should_retrieve": True},
        latency_ms=1234,
    )
    repo.increment_run_progress(run_id)

    res = repo.list_item_results(run_id)
    assert res["total"] == 1
    item = res["items"][0]
    # 스냅샷 조인으로 질문/유형이 채워짐
    assert item["question"] == "제7조의3 안전관리자 선임 기준은?"
    assert item["question_type"] == "factual"
    assert item["dataset_sequence"] == 1
    # ①축 JSON 왕복
    assert json.loads(item["threshold_fallback_json"])["correct"] is True
    assert json.loads(item["guardrail_json"])["intent"] == "qa"
    assert json.loads(item["answer_correctness_v1_json"])["value"] == pytest.approx(0.9)
    assert json.loads(item["answer_correctness_v2_json"])["value"] == pytest.approx(0.85)
    assert json.loads(item["answer_correctness_f2_json"])["value"] == pytest.approx(0.92)
    assert json.loads(item["answer_correctness_judge_json"])["metadata"]["method"] == "ragas_answer_accuracy"
    assert json.loads(item["answer_correctness_json"])["metadata"]["selected_metric"] == "judge"


def test_item_results_filter_by_question_type(repo):
    _, _, run_id, snapshot = _seed_finalized_run(repo)
    for s in snapshot:
        repo.insert_item_result(run_id, s["qa_id"], status="ok")
    assert repo.list_item_results(run_id, question_type="factual")["total"] == 2
    assert repo.list_item_results(run_id, question_type="multihop")["total"] == 0


def test_item_results_keep_dataset_sequence_when_results_are_partial(repo):
    _, _, run_id, snapshot = _seed_finalized_run(repo)
    repo.insert_item_result(run_id, snapshot[1]["qa_id"], status="ok")

    item = repo.list_item_results(run_id)["items"][0]
    assert item["qa_id"] == snapshot[1]["qa_id"]
    assert item["dataset_sequence"] == 2


def test_metrics_save_and_trend_with_segments(repo):
    _, _, run_id, _ = _seed_finalized_run(repo)
    repo.save_run_metrics(run_id, {
        "all": {
            "retrieval.rrf.recall@5": 0.5, "retrieval.rerank.hit@5": 0.5,
            "answer.correctness_mean": 1.0, "citation.accuracy": 1.0,
        },
        "type:factual": {"retrieval.rrf.recall@5": 0.5},
        "tag:legal_reference": {"retrieval.rrf.recall@5": 1.0},
    })
    repo.update_run_status(run_id, "completed")

    mets = repo.get_run_metrics(run_id)
    keys = {(m["metric_key"], m["segment"]) for m in mets}
    assert ("answer.correctness_mean", "all") in keys
    assert ("retrieval.rrf.recall@5", "tag:legal_reference") in keys

    # 추이는 완료 run + segment='all'만
    trend = repo.get_metrics_trend(
        ["retrieval.rrf.recall@5", "citation.accuracy"],
        collection_id=repo._test_collection_id,
    )
    assert trend
    assert trend[0]["dataset_name"] == "데이터셋"
    assert all(row["metric_key"] in ("retrieval.rrf.recall@5", "citation.accuracy") for row in trend)


def test_metrics_store_null_value_with_status_counts(repo):
    _, _, run_id, _ = _seed_finalized_run(repo)
    repo.save_run_metrics(run_id, {
        "all": {
            "answer.correctness_mean": {
                "value": None,
                "std": None,
                "evaluated_count": 0,
                "excluded_count": 2,
                "error_count": 1,
                "total_count": 3,
                "metric_version": "rule-v1.1",
            }
        }
    })

    metric = repo.get_run_metrics(run_id)[0]
    assert metric["metric_value"] is None
    assert metric["evaluated_count"] == 0
    assert metric["excluded_count"] == 2
    assert metric["error_count"] == 1
    assert metric["total_count"] == 3
    assert metric["metric_version"] == "rule-v1.1"


def test_delete_dataset_cascades_through_restricted_goldset_and_run(repo):
    ds, goldset_id, run_id, _ = _seed_finalized_run(repo)
    # RESTRICT FK(goldset/run)이 걸려 있어도 delete_dataset이 run→goldset 순으로 정리해야 함
    repo.delete_dataset(ds)
    assert repo.get_dataset(ds) is None
    assert repo.get_goldset(goldset_id) is None
    assert repo.get_run(run_id) is None


def test_mark_orphan_runs_failed(repo):
    _, _, run_id, _ = _seed_finalized_run(repo)
    repo.update_run_status(run_id, "running")
    affected = repo.mark_orphan_runs_failed()
    assert affected >= 1
    assert repo.get_run(run_id)["status"] == "failed"

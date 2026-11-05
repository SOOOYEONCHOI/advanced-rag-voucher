"""평가 API(/api/eval) 라우터 테스트 — P3-①.

FastAPI TestClient + get_current_admin 오버라이드 + 실제 EvalRepository(임시 DB).
백그라운드 실행(start_run)은 no-op으로 패치하여 API 계약만 검증한다
(실제 Qdrant/vLLM 실행 검증은 라이브 스택에서 수행).
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.repositories import database
from app.repositories.evaluation_repository import EvalRepository
from app.routes.evaluation import router as eval_router
from app.utils.security import get_current_admin


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
def client(tmp_path, monkeypatch):
    # 임시 DB 초기화 + 부모 컬렉션
    db = database.get_database_manager(str(tmp_path / "eval.db"))
    db.execute_update(
        "INSERT INTO tb_collections (display_name, qdrant_name) VALUES (?, ?)",
        ("평가용 컬렉션", "eval_api_coll"),
    )
    cid = db.execute_query(
        "SELECT collection_id FROM tb_collections WHERE qdrant_name = ?",
        ("eval_api_coll",),
    )[0]["collection_id"]

    # 백그라운드 실행은 no-op (API 계약만 검증)
    import app.evaluation.runner.eval_runner as runner_mod
    monkeypatch.setattr(runner_mod, "start_run", lambda run_id: None)

    app = FastAPI()
    app.include_router(eval_router, prefix="/api")
    app.dependency_overrides[get_current_admin] = lambda: {"admin_id": "admin", "is_superadmin": False}

    c = TestClient(app)
    c._collection_id = cid
    return c


def _make_goldset(client):
    """dataset(repo 직접 생성) → goldset import(API) → goldset_id 반환."""
    repo = EvalRepository()
    ds = repo.create_dataset("데이터셋", client._collection_id, {})
    resp = client.post("/api/eval/goldsets/import", json={
        "dataset_id": ds,
        "note": "manual",
        "items": [
            {"question": "제7조의3 기준은?", "gold_answer": "정답1",
             "gold_chunk_ids": ["c1"], "gold_document_ids": ["d1"],
             "question_type": "factual", "expected_behavior": "answer",
             "tags": ["legal_reference"]},
            {"question": "문서에 없는 질문", "gold_answer": "",
             "gold_chunk_ids": [], "gold_document_ids": [],
             "question_type": "factual", "expected_behavior": "not_enough_info",
             "tags": ["unanswerable"]},
        ],
    })
    assert resp.status_code == 200, resp.text
    return ds, resp.json()["goldset_id"]


# ── 골드셋 import + 목록 ─────────────────────────────────────────────────────

def test_goldset_import_and_list(client):
    ds, goldset_id = _make_goldset(client)
    resp = client.get("/api/eval/goldsets", params={"dataset_id": ds})
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["goldset_id"] == goldset_id
    assert items[0]["item_count"] == 2
    assert items[0]["qdrant_name"] == "eval_api_coll"


def test_goldset_import_rejects_missing_dataset(client):
    resp = client.post("/api/eval/goldsets/import", json={
        "dataset_id": 99999, "items": [{"question": "q", "gold_answer": "a"}],
    })
    assert resp.status_code == 404


# ── run 생성/조회/삭제 계약 ──────────────────────────────────────────────────

def test_create_run_returns_pending_and_persists(client):
    _, goldset_id = _make_goldset(client)
    resp = client.post("/api/eval/runs", json={
        "goldset_id": goldset_id, "scope": "retrieval",
        "config": {"retrieval_top_n": 10, "rerank_top_k": 5},
    })
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["status"] == "pending" and body["total"] == 2
    assert body["scope"] == "retrieval"
    run_id = body["run_id"]

    # 상세 조회 — metrics 포함(빈 배열)
    got = client.get(f"/api/eval/runs/{run_id}")
    assert got.status_code == 200
    assert got.json()["run_type"] == "retrieval"
    assert got.json()["scope"] == "retrieval"
    saved_config = __import__("json").loads(got.json()["config_json"])
    assert saved_config == {
        "retrieval_top_n": 10,
        "rerank_top_k": 5,
        "retrieval_channel": "rrf",
        "metric_version": "rule-v1.1",
    }
    assert got.json()["metrics"] == []

    # 목록
    listed = client.get("/api/eval/runs")
    assert any(r["run_id"] == run_id for r in listed.json()["items"])


def test_create_run_rejects_missing_goldset(client):
    resp = client.post("/api/eval/runs", json={"goldset_id": 99999, "scope": "retrieval"})
    assert resp.status_code == 404


@pytest.mark.parametrize(
    "config",
    [
        {"retrieval_top_n": 0, "rerank_top_k": 1},
        {"retrieval_top_n": 10, "rerank_top_k": 0},
        {"retrieval_top_n": 3, "rerank_top_k": 4},
    ],
)
def test_create_run_rejects_invalid_cutoffs(client, config):
    _, goldset_id = _make_goldset(client)
    resp = client.post("/api/eval/runs", json={
        "goldset_id": goldset_id,
        "scope": "retrieval",
        "config": config,
    })
    assert resp.status_code == 422


def test_create_run_rejects_legacy_run_type_and_judge_config(client):
    _, goldset_id = _make_goldset(client)
    legacy = client.post("/api/eval/runs", json={
        "goldset_id": goldset_id,
        "run_type": "end_to_end",
        "config": {},
    })
    assert legacy.status_code == 422

    judge = client.post("/api/eval/runs", json={
        "goldset_id": goldset_id,
        "scope": "full",
        "config": {"judge_backend": "openai"},
    })
    assert judge.status_code == 422


def test_openai_key_endpoint_is_dataset_generation_only(client):
    current = client.get("/api/eval/settings/dataset-generation/openai-key")
    assert current.status_code == 200
    assert current.json() == {"has_openai_api_key": False}
    assert client.get("/api/eval/settings/openai-key").status_code == 404


def test_create_full_run_snapshots_answer_correctness_config(client):
    _, goldset_id = _make_goldset(client)
    resp = client.post("/api/eval/runs", json={
        "goldset_id": goldset_id,
        "scope": "full",
        "config": {"retrieval_top_n": 10, "rerank_top_k": 5},
    })
    assert resp.status_code == 202, resp.text

    run = client.get(f"/api/eval/runs/{resp.json()['run_id']}").json()
    config = __import__("json").loads(run["config_json"])
    assert config["metric_version"] == "rule-v1.1"
    assert config["answer_correctness"]["method"] == "embedding_cosine"
    assert config["answer_correctness"]["normalization_version"] == "v2"
    assert config["answer_correctness"]["embedding_model"]
    assert config["answer_correctness_v2"]["mode"] == "shadow"
    assert config["answer_correctness_v2"]["metric_version"] == "rule-v2-shadow.2"
    assert config["answer_correctness_v2"]["semantic_dedupe_threshold"] == pytest.approx(0.92)
    assert config["answer_correctness_v2"]["precision_candidate_ratio"] == 3
    assert config["answer_correctness_f2"]["enabled"] is True
    assert config["answer_correctness_f2"]["mode"] == "shadow"
    assert config["answer_correctness_f2"]["metric_version"] == "f2.1"
    assert config["answer_correctness_f2"]["beta"] == pytest.approx(2.0)
    assert config["answer_correctness_primary"] in {"v1", "v2", "f2", "judge"}
    assert config["answer_correctness_fallback_chain"]
    assert config["answer_correctness_judge"]["method"] == "ragas_answer_accuracy"
    assert config["answer_correctness_judge"]["metric_version"] == "answer_accuracy.1"


def test_delete_running_run_conflicts_then_succeeds_after_complete(client):
    _, goldset_id = _make_goldset(client)
    run_id = client.post("/api/eval/runs", json={
        "goldset_id": goldset_id, "scope": "retrieval", "config": {},
    }).json()["run_id"]

    # pending 상태 → 삭제 409
    assert client.delete(f"/api/eval/runs/{run_id}").status_code == 409

    # 완료 처리 후 삭제 200
    EvalRepository().update_run_status(run_id, "completed")
    assert client.delete(f"/api/eval/runs/{run_id}").status_code == 200
    assert client.get(f"/api/eval/runs/{run_id}").status_code == 404


def test_cancel_non_active_run_returns_404(client):
    _, goldset_id = _make_goldset(client)
    run_id = client.post("/api/eval/runs", json={
        "goldset_id": goldset_id, "scope": "retrieval", "config": {},
    }).json()["run_id"]
    # start_run이 no-op이라 레지스트리에 등록되지 않음 → 취소 대상 아님
    assert client.post(f"/api/eval/runs/{run_id}/cancel").status_code == 404


# ── 결과/대시보드 ────────────────────────────────────────────────────────────

def test_run_results_join_snapshot(client):
    _, goldset_id = _make_goldset(client)
    run_id = client.post("/api/eval/runs", json={
        "goldset_id": goldset_id, "scope": "retrieval", "config": {},
    }).json()["run_id"]

    repo = EvalRepository()
    snap = __import__("json").loads(repo.get_goldset(goldset_id)["items_snapshot_json"])
    repo.insert_item_result(run_id, snap[0]["qa_id"], status="ok",
                            retrieval_json={"rrf": {"recall@5": 1.0}})

    resp = client.get(f"/api/eval/runs/{run_id}/results")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["question"] == "제7조의3 기준은?"
    assert data["items"][0]["question_type"] == "factual"


def test_dashboard_trend_and_compare(client):
    _, goldset_id = _make_goldset(client)
    repo = EvalRepository()
    run_id = repo.create_run(goldset_id, "retrieval", {"top_k": 10}, total=2)
    repo.save_run_metrics(run_id, {"all": {"retrieval.rrf.recall@5": 0.9, "citation.accuracy": 0.8}})
    repo.update_run_status(run_id, "completed")

    trend = client.get("/api/eval/dashboard/trend",
                       params={"metric_keys": "retrieval.rrf.recall@5,citation.accuracy"})
    assert trend.status_code == 200
    assert any(row["metric_key"] == "retrieval.rrf.recall@5" for row in trend.json()["items"])

    cmp = client.get("/api/eval/dashboard/compare", params={"run_ids": str(run_id)})
    assert cmp.status_code == 200
    assert cmp.json()["items"][0]["run_id"] == run_id

    # metric_keys 비면 400
    assert client.get("/api/eval/dashboard/trend", params={"metric_keys": " "}).status_code == 400


def test_run_summary_separates_primary_and_secondary_metrics(client):
    _, goldset_id = _make_goldset(client)
    repo = EvalRepository()
    run_id = repo.create_run(
        goldset_id, "retrieval",
        {"retrieval_top_n": 10, "rerank_top_k": 5, "metric_version": "rule-v1.1"},
        total=1,
    )
    aggregate = {
        "value": 0.75, "std": 0.0, "evaluated_count": 1,
        "excluded_count": 0, "error_count": 0, "total_count": 1,
        "metric_version": "rule-v1.1",
    }
    repo.save_run_metrics(run_id, {"all": {
        "retrieval.rrf.recall@10": aggregate,
        "retrieval.rerank.ndcg@5": aggregate,
        "retrieval.rerank.mrr@5": aggregate,
        "retrieval.rrf.ndcg@10": aggregate,
    }})

    data = client.get(f"/api/eval/runs/{run_id}").json()
    assert [metric["key"] for metric in data["primary_metrics"]] == [
        "retrieval.rrf.recall@10", "retrieval.rerank.ndcg@5",
    ]
    assert len(data["secondary_metrics"]) == 2
    assert data["primary_metrics"][0]["evaluated_count"] == 1
    assert data["metric_version"] == "rule-v1.1"
    assert data["legacy"] is False
    assert not any(metric["key"].startswith("answer.") for metric in data["primary_metrics"])

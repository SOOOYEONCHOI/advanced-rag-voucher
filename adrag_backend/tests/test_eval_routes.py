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
    db = database.get_database_manager()
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
        "metric_version": "rule-v1.3",
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
    # 2026.11.17(sooyeon.choi) 수정 - F2 단일 지표 snapshot(v1·judge·primary·fallback 삭제)
    assert config["metric_version"] == "rule-v1.3"
    assert config["answer_correctness_v2"]["mode"] == "f2_input"
    assert config["answer_correctness_v2"]["metric_version"] == "rule-v2.3"
    assert config["answer_correctness_v2"]["normalization_version"] == "v2"
    assert config["answer_correctness_v2"]["embedding_model"]
    assert config["answer_correctness_v2"]["semantic_dedupe_threshold"] == pytest.approx(0.92)
    assert config["answer_correctness_v2"]["precision_candidate_ratio"] == 3
    assert config["answer_correctness_f2"]["enabled"] is True
    assert config["answer_correctness_f2"]["mode"] == "primary"
    assert config["answer_correctness_f2"]["metric_version"] == "f2.1"
    assert config["answer_correctness_f2"]["beta"] == pytest.approx(2.0)
    for removed in (
        "answer_correctness", "answer_correctness_primary",
        "answer_correctness_fallback_chain", "answer_correctness_judge",
    ):
        assert removed not in config


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
    # 2026.11.17(sooyeon.choi) 수정 - 주 지표 Hit@N, 보조 지표 Recall@N·rr@K·NDCG@N
    repo.save_run_metrics(run_id, {"all": {
        "retrieval.rrf.hit@10": aggregate,
        "retrieval.rrf.recall@10": aggregate,
        "retrieval.rerank.ndcg@5": aggregate,
        "retrieval.rerank.rr@5": aggregate,
        "retrieval.rrf.ndcg@10": aggregate,
    }})

    data = client.get(f"/api/eval/runs/{run_id}").json()
    assert [metric["key"] for metric in data["primary_metrics"]] == [
        "retrieval.rrf.hit@10", "retrieval.rerank.ndcg@5",
    ]
    assert [metric["key"] for metric in data["secondary_metrics"]] == [
        "retrieval.rrf.recall@10", "retrieval.rerank.rr@5", "retrieval.rrf.ndcg@10",
    ]
    assert data["primary_metrics"][0]["evaluated_count"] == 1
    assert data["metric_version"] == "rule-v1.1"
    assert data["legacy"] is False
    assert not any(metric["key"].startswith("answer.") for metric in data["primary_metrics"])


# ── 데이터셋 생성 모델 선택 (2026.11.18(sooyeon.choi) 추가) ─────────────────────

def _gen_settings(extra=""):
    from types import SimpleNamespace
    return SimpleNamespace(
        vllm_model_name="Qwen3.5-9B",
        vllm_api_url="http://llm:8101/",
        vllm_api_key="k",
        eval_gen_vllm_models=extra,
    )


@pytest.fixture
def gen_models(monkeypatch):
    """생성 모델 설정 + /v1/models 응답(served) + start_generation 캡처."""
    import app.evaluation.adapters.gen_model_catalog as catalog
    import app.evaluation.dataset.generator as generator_mod

    state = {"served": {"http://llm:8101": ["Qwen3.5-9B"]}, "started": []}
    settings = _gen_settings("gemma-4-31B-it-FP8=http://gen:8112, 잘못된항목")
    monkeypatch.setattr(catalog, "get_settings", lambda: settings)

    class _Resp:
        def __init__(self, ids):
            self.status_code = 200
            self._ids = ids

        def json(self):
            return {"data": [{"id": i} for i in self._ids]}

    class _Client:
        async def get(self, url, **kwargs):
            base = url[: -len("/v1/models")]
            if base not in state["served"]:
                raise ConnectionError("down")
            return _Resp(state["served"][base])

    monkeypatch.setattr(catalog, "get_shared_async_client", lambda: _Client())
    monkeypatch.setattr(
        generator_mod, "start_generation",
        lambda dataset_id, gen_config: state["started"].append(gen_config),
    )
    return state


def _stored_gen_config(dataset_id):
    import json as _json
    row = database.get_database_manager().execute_query(
        "SELECT gen_config_json FROM tb_eval_datasets WHERE dataset_id = ?", (dataset_id,)
    )[0]
    return _json.loads(row["gen_config_json"])


def test_generation_models_list_hides_url_and_marks_down_server(client, gen_models):
    resp = client.get("/api/eval/settings/dataset-generation/models")
    assert resp.status_code == 200
    assert resp.json()["items"] == [
        {"model": "Qwen3.5-9B", "is_default": True, "available": True},
        {"model": "gemma-4-31B-it-FP8", "is_default": False, "available": False},
    ]
    assert "http" not in resp.text

    gen_models["served"]["http://gen:8112"] = ["gemma-4-31B-it-FP8"]
    items = client.get("/api/eval/settings/dataset-generation/models").json()["items"]
    assert items[1]["available"] is True


def test_create_dataset_with_selected_vllm_model(client, gen_models):
    gen_models["served"]["http://gen:8112"] = ["gemma-4-31B-it-FP8"]
    resp = client.post("/api/eval/datasets", json={
        "name": "gemma 생성", "collection_id": client._collection_id,
        "gen_config": {"llm_backend": "vllm", "llm_model": "gemma-4-31B-it-FP8",
                       "vllm_api_url": "http://attacker:1"},
    })
    assert resp.status_code == 202, resp.text
    runtime = gen_models["started"][-1]
    assert runtime["vllm_api_url"] == "http://gen:8112"
    assert runtime["llm_model"] == "gemma-4-31B-it-FP8"
    stored = _stored_gen_config(resp.json()["dataset_id"])
    assert stored["llm_model"] == "gemma-4-31B-it-FP8"
    assert "vllm_api_url" not in stored


def test_create_dataset_without_model_uses_chatbot_default(client, gen_models):
    resp = client.post("/api/eval/datasets", json={
        "name": "기본 생성", "collection_id": client._collection_id,
        "gen_config": {"llm_backend": "vllm"},
    })
    assert resp.status_code == 202, resp.text
    runtime = gen_models["started"][-1]
    assert runtime["vllm_api_url"] == "http://llm:8101"
    assert runtime["llm_model"] == "Qwen3.5-9B"


def test_create_dataset_rejects_unknown_or_down_model(client, gen_models):
    unknown = client.post("/api/eval/datasets", json={
        "name": "x", "collection_id": client._collection_id,
        "gen_config": {"llm_backend": "vllm", "llm_model": "없는모델"},
    })
    assert unknown.status_code == 400
    down = client.post("/api/eval/datasets", json={
        "name": "x", "collection_id": client._collection_id,
        "gen_config": {"llm_backend": "vllm", "llm_model": "gemma-4-31B-it-FP8"},
    })
    assert down.status_code == 400
    assert "응답하지 않습니다" in down.json()["detail"]
    assert gen_models["started"] == []


@pytest.mark.asyncio
async def test_eval_llm_uses_selected_vllm_target(monkeypatch):
    import app.evaluation.adapters.llm_adapter as adapter
    from app.core.config import get_settings

    calls = []

    class _FakeLLMClient:
        def __init__(self, settings):
            self.target = (settings.vllm_api_url, settings.vllm_model_name)

        async def chat(self, messages, **kwargs):
            calls.append(self.target)
            return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(adapter, "LLMClient", _FakeLLMClient)
    monkeypatch.setattr(adapter, "_vllm_clients_by_target", {})
    monkeypatch.setattr(adapter, "_vllm_client", None)

    llm = adapter.EvalLLM(vllm_api_url="http://gen:8112", vllm_model="gemma-4-31B-it-FP8")
    assert await llm.chat([{"role": "user", "content": "q"}]) == "ok"
    assert await adapter.EvalLLM().chat([{"role": "user", "content": "q"}]) == "ok"
    default = get_settings()
    assert calls == [
        ("http://gen:8112", "gemma-4-31B-it-FP8"),
        (default.vllm_api_url, default.vllm_model_name),
    ]

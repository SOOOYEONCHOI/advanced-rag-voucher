# 2026.11.20(sooyeon.choi) 수정 - 합본 평가 데이터셋 (docs/design/reports/eval-merged-dataset-design-v1.0.md)
"""- 합본 문항: 원본 골드셋 스냅샷 복사, 질의ID 유지, 문항별 검색 컬렉션·법령 이름 저장, 질의ID 중복 거부
- 평가: 문항별 컬렉션으로 검색, 지표는 항목별 계산 후 전체 집계(법령별 = 같은 실행 항목을 법령으로 나눔)
- 화면·Excel: 법령별 주요 지표, 결과 Excel 질의ID·법령·정답 답변·생성 답변·인용 출처 열
- 합본 문항 수정·확정·다시 생성 금지, 설정을 끄면 합본 API 404
"""

import json
from io import BytesIO

import pytest
from openpyxl import load_workbook

from app.repositories import database


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


def _snapshot_item(qa_id, question, order, chunk="c"):
    return {
        "qa_id": qa_id, "question": question, "gold_answer": f"{question} 답변",
        "gold_chunk_ids": json.dumps([f"{chunk}{qa_id}"]), "gold_document_ids": json.dumps(["d1"]),
        "gold_chunk_texts": json.dumps(["근거"]), "question_type": "law", "difficulty": "normal",
        "self_valid_rank": 1, "expected_behavior": "answer", "tags": "[]", "review_status": "approved",
        "source_meta_json": json.dumps({"unit_order": order, "article": f"제{order}조"}, ensure_ascii=False),
    }


def _source(dataset_id, name, law, prefix, items):
    return {
        "dataset": {"dataset_id": dataset_id, "name": name, "collection_name": law,
                    "qdrant_name": f"AIE_{law}", "gen_config_json": json.dumps({"query_id_prefix": prefix})},
        "goldset": {"goldset_id": dataset_id * 10, "version": 1},
        "items": items,
    }


# ── 합본 문항 만들기 ────────────────────────────────────────────────────────

def test_build_merged_items_keeps_source_query_ids_and_collections():
    from app.evaluation.dataset.merge import build_merged_items, merged_config

    first = _source(3, "산안", "산업안전보건법", "산안",
                    [_snapshot_item(12, "둘째", 2), _snapshot_item(11, "첫째", 1)])
    second = _source(4, "중처", "중대재해처벌법", "중처", [_snapshot_item(21, "중처 첫째", 1)])
    items = build_merged_items([first, second])

    assert [item["question"] for item in items] == ["첫째", "둘째", "중처 첫째"]  # 원본 시험셋 순서 → 합친 순서
    metas = [item["source_meta"] for item in items]
    assert [m["query_id"] for m in metas] == ["산안-001", "산안-002", "중처-001"]
    assert [m["qdrant_name"] for m in metas] == ["AIE_산업안전보건법"] * 2 + ["AIE_중대재해처벌법"]
    assert [m["law_label"] for m in metas] == ["산업안전보건법"] * 2 + ["중대재해처벌법"]
    assert [m["merge_order"] for m in metas] == [1, 2, 3]
    assert metas[0]["merged_source"] == {"dataset_id": 3, "goldset_id": 30, "qa_id": 11}
    assert metas[0]["article"] == "제1조"                       # 원본 출처 정보 유지
    assert items[0]["gold_chunk_ids"] == ["c11"] and items[0]["review_status"] == "approved"

    config = merged_config([first, second])
    assert config["dataset_kind"] == "merged"
    assert [s["item_count"] for s in config["merged_from"]] == [2, 1]


def test_build_merged_items_rejects_duplicate_query_ids():
    from app.evaluation.dataset.merge import MergeError, build_merged_items

    same_prefix = [_source(3, "A", "법A", "Q", [_snapshot_item(1, "a", 1)]),
                   _source(4, "B", "법B", "Q", [_snapshot_item(2, "b", 1)])]
    with pytest.raises(MergeError, match="Q-001"):
        build_merged_items(same_prefix)


# ── 평가 실행: 문항별 컬렉션·법령 세그먼트 ──────────────────────────────────

def test_item_collection_and_law_segment():
    from app.evaluation.runner.eval_runner import _item_segments, item_collection

    merged = {"question_type": "law", "source_meta_json": json.dumps(
        {"qdrant_name": "AIE_중대재해처벌법", "law_label": "중대재해처벌법"}, ensure_ascii=False)}
    assert item_collection(merged, "AIE_산업안전보건법") == "AIE_중대재해처벌법"
    assert _item_segments(merged) == ["all", "law:중대재해처벌법", "type:law"]
    single = {"question_type": "law", "source_meta_json": json.dumps({"article": "제4조"}, ensure_ascii=False)}
    assert item_collection(single, "AIE_산업안전보건법") == "AIE_산업안전보건법"   # 단독 데이터셋: 기존 동작
    assert _item_segments(single) == ["all", "type:law"]


def test_present_law_metrics_from_segments():
    from app.evaluation.metric_catalog import AGREEMENT_RECALL_KEY, present_run_metrics

    rows = [
        {"metric_key": AGREEMENT_RECALL_KEY, "segment": "all", "metric_value": 0.75, "metric_std": None,
         "evaluated_count": 4, "excluded_count": 0, "error_count": 0, "total_count": 4},
        {"metric_key": AGREEMENT_RECALL_KEY, "segment": "law:중대재해처벌법", "metric_value": 0.5, "metric_std": None,
         "evaluated_count": 2, "excluded_count": 0, "error_count": 0, "total_count": 2},
        {"metric_key": AGREEMENT_RECALL_KEY, "segment": "law:산업안전보건법", "metric_value": 1.0, "metric_std": None,
         "evaluated_count": 2, "excluded_count": 0, "error_count": 0, "total_count": 2},
        {"metric_key": AGREEMENT_RECALL_KEY, "segment": "type:law", "metric_value": 0.75, "metric_std": None,
         "evaluated_count": 4, "excluded_count": 0, "error_count": 0, "total_count": 4},
    ]
    presented = present_run_metrics("retrieval", {}, rows)
    assert [row["law"] for row in presented["law_metrics"]] == ["산업안전보건법", "중대재해처벌법"]
    assert presented["law_metrics"][1]["metrics"][AGREEMENT_RECALL_KEY]["value"] == 0.5
    assert present_run_metrics("retrieval", {}, rows[:1])["law_metrics"] == []   # 단독 실행


def test_aggregate_counts_each_law_with_all_items_denominator():
    """법령별 값도 전체와 같은 식: 지표 1·2 분모 = 그 법령의 전체 질의 수(오류 0점)."""
    from app.evaluation.metric_catalog import AGREEMENT_NDCG_KEY, AGREEMENT_RECALL_KEY
    from app.evaluation.runner.eval_runner import _aggregate_and_save_metrics
    from app.repositories.evaluation_repository import EvalRepository

    db = database.get_database_manager()
    db.execute_update("INSERT INTO tb_collections (display_name, qdrant_name) VALUES (?, ?)", ("합본 집계", "merged_agg"))
    collection_id = db.execute_query(
        "SELECT collection_id FROM tb_collections WHERE qdrant_name = ?", ("merged_agg",))[0]["collection_id"]
    repo = EvalRepository()
    items = []
    for index, law in enumerate(["법A", "법A", "법B", "법B"], start=1):
        items.append({
            "question": f"질문 {index}", "gold_answer": "답", "gold_chunk_ids": [f"c{index}"], "gold_document_ids": [],
            "gold_chunk_texts": [], "question_type": "factual", "difficulty": "normal", "self_valid_rank": 1,
            "expected_behavior": "answer", "tags": [], "review_status": "approved",
            "source_meta": {"qdrant_name": "merged_agg", "law_label": law, "query_id": f"Q-{index:03d}", "merge_order": index},
        })
    created = repo.create_merged_dataset("합본 집계", collection_id, {"dataset_kind": "merged"}, items)
    try:
        snapshot = json.loads(repo.get_goldset(created["goldset_id"])["items_snapshot_json"])
        run_id = repo.create_run(created["goldset_id"], "retrieval", {"metric_version": "rule-v1.3"}, 4)
        hits = [1.0, 0.0, 1.0]  # 4번째(법B)는 실행 오류
        for item, hit in zip(snapshot, hits):
            repo.insert_item_result(run_id, item["qa_id"], status="ok", retrieval_json={
                "rrf": {"hit@10": hit, "recall@10": hit}, "rerank": {"ndcg@5": hit}})
        repo.insert_item_result(run_id, snapshot[3]["qa_id"], status="error", error_message="x")
        _aggregate_and_save_metrics(repo, run_id, snapshot)

        rows = {(row["segment"], row["metric_key"]): row for row in repo.get_run_metrics(run_id)}
        assert rows[("all", AGREEMENT_RECALL_KEY)]["metric_value"] == pytest.approx(2 / 4)
        assert rows[("law:법A", AGREEMENT_RECALL_KEY)]["metric_value"] == pytest.approx(1 / 2)
        assert rows[("law:법B", AGREEMENT_RECALL_KEY)]["metric_value"] == pytest.approx(1 / 2)  # 오류 = 0점
        assert rows[("law:법B", AGREEMENT_NDCG_KEY)]["total_count"] == 2
    finally:
        repo.delete_dataset(created["dataset_id"])


# ── 결과 Excel ──────────────────────────────────────────────────────────────

def test_run_workbook_adds_answer_columns_and_law_table():
    from app.evaluation.excel_exporter import build_run_result_workbook

    run = {"run_id": 9, "dataset_name": "합본", "run_type": "full", "status": "completed",
           "config_json": json.dumps({"retrieval_top_n": 10, "rerank_top_k": 5})}
    primary = [
        {"key": "retrieval.rrf.hit@10", "label": "검색 완전성 Recall@10", "value": 0.75, "std": None,
         "evaluated_count": 4, "excluded_count": 0, "error_count": 0, "total_count": 4},
        {"key": "answer.judge_accuracy", "label": "답변 생성 정확도", "value": None, "std": None,
         "status": "not_measured", "evaluated_count": 0, "excluded_count": 0, "error_count": 0, "total_count": 0},
        {"key": "answer.first_token_ms", "label": "답변 생성 평균 반환 시간", "unit": "ms", "value": 2400.0, "std": None,
         "evaluated_count": 4, "excluded_count": 0, "error_count": 0, "total_count": 4},
    ]
    law_metrics = [
        {"law": "산업안전보건법", "metrics": {
            "retrieval.rrf.hit@10": {"value": 1.0, "total_count": 2},
            "answer.first_token_ms": {"value": 2000.0, "total_count": 2}}},
        {"law": "중대재해처벌법", "metrics": {"retrieval.rrf.hit@10": {"value": 0.5, "total_count": 2}}},
    ]
    items = [{
        "result_id": 1, "dataset_sequence": 1, "query_id": "산안-001", "law_label": "산업안전보건법",
        "question_type": "law", "question": "질문", "gold_answer": "정답", "answer_text": "생성된 답변 [1]",
        "status": "ok", "latency_ms": 9000, "timing_json": json.dumps({"first_token_ms": 2000.0}),
        "citation_detail_json": json.dumps({"cited": [{"citation_id": 1, "original_filename": "산업안전보건법.pdf",
                                                        "header_path": ["제2장", "제4조"], "page_number": 3}]},
                                           ensure_ascii=False),
        "metric_status_json": json.dumps({"retrieval.rrf.hit@10": {"value": 1.0, "status": "evaluated"},
                                          "retrieval.rerank.ndcg@5": {"value": 0.63, "status": "evaluated"}}),
    }]
    workbook = load_workbook(build_run_result_workbook(run, primary, [], items, law_metrics=law_metrics))

    results = workbook["항목별 결과"]
    headers = [cell.value for cell in results[1]]
    assert headers[:8] == ["번호", "질의ID", "법령", "유형", "질문", "정답 답변", "생성 답변", "인용 출처"]
    row = [cell.value for cell in results[2]]
    assert row[:8] == [1, "산안-001", "산업안전보건법", "법령", "질문", "정답", "생성된 답변 [1]",
                       "[1] 산업안전보건법.pdf · 제4조 · p.3"]
    assert row[8:10] == [1.0, 0.63] and results.cell(2, 9).number_format == "0.0%"
    assert row[12:14] == [9.0, 2.0] and results.cell(2, 13).number_format == "0.00"

    summary = [[cell.value for cell in r] for r in workbook["지표 요약"].iter_rows()]
    start = next(i for i, r in enumerate(summary) if str(r[0]).startswith("법령별 주요 지표"))
    assert summary[start + 1][:5] == ["구분", "검색 완전성 Recall@10", "답변 생성 정확도", "답변 생성 평균 반환 시간", "문항 수"]
    assert summary[start + 2][:5] == ["전체 (판정 기준)", 0.75, "미측정", 2.4, 4]
    assert summary[start + 3][:5] == ["산업안전보건법", 1.0, "미측정", 2.0, 2]
    assert summary[start + 4][:5] == ["중대재해처벌법", 0.5, "미측정", "-", 2]


def test_single_run_workbook_has_no_law_column():
    from app.evaluation.excel_exporter import build_run_result_workbook

    run = {"run_id": 9, "run_type": "retrieval", "config_json": "{}"}
    items = [{"result_id": 1, "dataset_sequence": 1, "query_id": "Q-001", "question": "질문", "gold_answer": "정답",
              "status": "ok", "metric_status_json": "{}"}]
    workbook = load_workbook(build_run_result_workbook(run, [], [], items))
    headers = [cell.value for cell in workbook["항목별 결과"][1]]
    assert "법령" not in headers and headers[1] == "질의ID"
    assert [workbook["항목별 결과"].cell(2, c).value for c in (6, 7)] == ["해당 없음", "해당 없음"]  # 검색 평가: 답변 없음
    assert not any(str(cell.value or "").startswith("법령별") for cell in workbook["지표 요약"]["A"])


# ── API ────────────────────────────────────────────────────────────────────

def _seed_source(repo, db, qdrant_name, display_name, prefix, questions):
    db.execute_update("INSERT INTO tb_collections (display_name, qdrant_name) VALUES (?, ?)", (display_name, qdrant_name))
    collection_id = db.execute_query(
        "SELECT collection_id FROM tb_collections WHERE qdrant_name = ?", (qdrant_name,))[0]["collection_id"]
    dataset_id = repo.create_dataset(f"{display_name} 시험", collection_id, {"query_id_prefix": prefix})
    for order, question in enumerate(questions, start=1):
        qa_id = repo.insert_qa_item(
            dataset_id, question, f"{question} 답변", [f"{prefix}-{order}"], ["d"], ["근거"], "factual",
            source_meta={"unit_order": order},
        )
        repo.update_qa_item(qa_id, review_status="approved")
    return dataset_id


def test_merge_api_flow_and_guards(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.repositories.evaluation_repository import EvalRepository
    from app.routes.evaluation import router as eval_router
    from app.utils.security import get_current_admin

    db = database.get_database_manager()
    repo = EvalRepository()
    created = []
    try:
        first = _seed_source(repo, db, "merge_api_a", "법A", "가", ["가 질문1", "가 질문2"])
        second = _seed_source(repo, db, "merge_api_b", "법B", "나", ["나 질문1"])
        unfinalized = _seed_source(repo, db, "merge_api_c", "법C", "다", ["다 질문1"])
        created += [first, second, unfinalized]
        repo.create_goldset(first)
        repo.create_goldset(second)

        app = FastAPI()
        app.include_router(eval_router, prefix="/api")
        app.dependency_overrides[get_current_admin] = lambda: {"admin_id": "admin"}
        client = TestClient(app)

        assert client.get("/api/eval/datasets").json()["merge_enabled"] is True
        assert client.post("/api/eval/datasets/merge", json={"name": "x", "dataset_ids": [first]}).status_code == 422
        assert client.post("/api/eval/datasets/merge", json={"name": "x", "dataset_ids": [first, first]}).status_code == 400
        no_goldset = client.post("/api/eval/datasets/merge", json={"name": "x", "dataset_ids": [first, unfinalized]})
        assert no_goldset.status_code == 400 and "확정본" in no_goldset.json()["detail"]

        response = client.post("/api/eval/datasets/merge", json={"name": "시험 합본", "dataset_ids": [first, second]})
        assert response.status_code == 201, response.text
        merged = response.json()
        created.append(merged["dataset_id"])
        assert merged["item_count"] == 3 and merged["goldset_id"]

        dataset = repo.get_dataset(merged["dataset_id"])
        assert dataset["status"] == "finalized"
        goldsets = client.get("/api/eval/goldsets", params={"dataset_id": merged["dataset_id"]}).json()["items"]
        assert goldsets[0]["dataset_kind"] == "merged" and goldsets[0]["item_count"] == 3

        # 합본 문항 수정·확정·다시 합치기 금지
        qa_id = client.get(f"/api/eval/datasets/{merged['dataset_id']}/items").json()["items"][0]["qa_id"]
        assert client.post(f"/api/eval/items/{qa_id}/approve").status_code == 409
        assert client.post(f"/api/eval/items/{qa_id}/reject").status_code == 409
        assert client.post(f"/api/eval/items/{qa_id}/regenerate").status_code == 409
        assert client.post("/api/eval/items/bulk-review", json={"qa_ids": [qa_id], "action": "approve"}).status_code == 409
        assert client.post(f"/api/eval/datasets/{merged['dataset_id']}/finalize", json={}).status_code == 409
        again = client.post("/api/eval/datasets/merge", json={"name": "y", "dataset_ids": [merged["dataset_id"], first]})
        assert again.status_code == 400

        # 합본 시험셋 Excel: 머리글 1행, 원본 질의ID, 법령 열
        workbook = load_workbook(BytesIO(client.get(f"/api/eval/datasets/{merged['dataset_id']}/test-set.xlsx").content))
        rows = [[cell.value for cell in row] for row in workbook["질의"].iter_rows()]
        assert rows[0] == ["질의ID", "질의문", "정답 답변", "법령"]
        assert [row[0] for row in rows[1:]] == ["가-001", "가-002", "나-001"]
        assert [row[3] for row in rows[1:]] == ["법A", "법A", "법B"]
        assert [row[0] for row in workbook["정답 근거"].iter_rows(min_row=2, values_only=True)] == ["가-001", "가-002", "나-001"]

        # 설정을 끄면 404
        from app.core import config as config_module

        class _Off:
            eval_dataset_merge_enabled = False

        monkeypatch.setattr(config_module, "get_settings", lambda: _Off())
        assert client.post("/api/eval/datasets/merge", json={"name": "z", "dataset_ids": [first, second]}).status_code == 404
    finally:
        for dataset_id in created:
            repo.delete_dataset(dataset_id)

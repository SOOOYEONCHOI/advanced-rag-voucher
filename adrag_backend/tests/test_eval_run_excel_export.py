import json
from datetime import datetime
from io import BytesIO

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app.evaluation.excel_exporter import (
    build_run_excel_filename,
    build_run_result_workbook,
)
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


def _run():
    return {
        "run_id": 42,
        "dataset_id": 7,
        "dataset_name": "산업안전 평가",
        "goldset_version": 3,
        "collection_name": "안전 법령",
        "run_type": "full",
        "status": "completed",
        "started_at": "2026-08-06T13:40:00+09:00",
        "finished_at": "2026-08-06T13:45:00+09:00",
        "config_json": json.dumps({
            "retrieval_top_n": 12, "rerank_top_k": 4, "metric_version": "rule-v1.1",
        }),
    }


def _metrics():
    primary = [
        {"key": "retrieval.rrf.recall@12", "label": "Retriever Recall@12", "value": .92,
         "std": .1, "evaluated_count": 8, "excluded_count": 2, "error_count": 0, "total_count": 10},
        {"key": "answer.correctness", "label": "Answer Correctness", "value": .84,
         "std": .2, "evaluated_count": 10, "excluded_count": 0, "error_count": 0, "total_count": 10},
    ]
    secondary = [
        {"key": "retrieval.rerank.mrr@4", "label": "Reranked MRR@4", "value": .88,
         "std": .05, "evaluated_count": 8, "excluded_count": 2, "error_count": 0, "total_count": 10},
    ]
    return primary, secondary


def test_workbook_has_two_sheets_summary_tables_and_numeric_percentages():
    primary, secondary = _metrics()
    item_metrics = {
        "retrieval.rrf.recall@12": {"value": 1.0, "status": "evaluated"},
        "retrieval.rerank.ndcg@4": {"value": .75, "status": "evaluated"},
        "answer.correctness": {"value": .8, "status": "evaluated"},
        "citation.completeness": {"value": .9, "status": "evaluated"},
    }
    items = [{
        "result_id": 1, "dataset_sequence": 2, "question_type": "multihop",
        "question": "작업발판과 안전대의 기준은 무엇인가요?", "status": "ok",
        "metric_status_json": json.dumps(item_metrics),
    }]

    workbook = load_workbook(build_run_result_workbook(_run(), primary, secondary, items))

    assert workbook.sheetnames == ["지표 요약", "항목별 결과"]
    summary = workbook["지표 요약"]
    assert summary["A14"].value == "주요 지표"
    assert summary["B16"].value == pytest.approx(.92)
    assert summary["B16"].number_format == "0.0%"
    results = workbook["항목별 결과"]
    assert [cell.value for cell in results[1]] == [
        "번호", "유형", "질문", "Retriever Recall@12", "Reranked NDCG@4",
        "Answer Correctness", "Citation Completeness",
    ]
    assert [results.cell(2, column).value for column in range(1, 8)] == [
        2, "멀티홉", "작업발판과 안전대의 기준은 무엇인가요?", 1.0, .75, .8, .9,
    ]
    assert results["D2"].number_format == "0.0%"


def test_retrieval_run_uses_status_text_and_legacy_metrics():
    run = {**_run(), "run_type": "retrieval"}
    items = [{
        "result_id": 1, "dataset_sequence": 1, "question_type": "factual", "question": "질문입니다.",
        "status": "ok",
        "retrieval_json": json.dumps({"rrf": {"recall@12": .5}, "rerank": {"ndcg@4": None}}),
        "metric_status_json": json.dumps({"retrieval.rerank.ndcg@4": {"value": None, "status": "excluded"}}),
    }]
    workbook = load_workbook(build_run_result_workbook(run, [], [], items))
    row = [workbook["항목별 결과"].cell(2, column).value for column in range(4, 8)]
    assert row == [.5, "제외", "해당 없음", "해당 없음"]


def test_repository_export_returns_all_results_in_dataset_order(tmp_path):
    db = database.get_database_manager(str(tmp_path / "run-export.db"))
    db.execute_update(
        "INSERT INTO tb_collections (display_name, qdrant_name) VALUES (?, ?)",
        ("컬렉션", "run_export"),
    )
    collection_id = db.execute_query(
        "SELECT collection_id FROM tb_collections WHERE qdrant_name = ?", ("run_export",)
    )[0]["collection_id"]
    repo = EvalRepository()
    dataset_id = repo.create_dataset("데이터셋", collection_id, {})
    first = repo.insert_qa_item(dataset_id, "첫 번째 질문입니다.", "첫 답변입니다.", ["c1"], ["d1"], ["t1"], "factual")
    second = repo.insert_qa_item(dataset_id, "두 번째 질문입니다.", "둘째 답변입니다.", ["c2"], ["d2"], ["t2"], "procedural")
    repo.update_qa_item(first, review_status="approved")
    repo.update_qa_item(second, review_status="approved")
    goldset_id = repo.create_goldset(dataset_id)
    run_id = repo.create_run(goldset_id, "retrieval", {}, 2)
    repo.insert_item_result(run_id, second, status="ok")
    repo.insert_item_result(run_id, first, status="ok")

    items = repo.list_item_results_for_export(run_id)

    assert [item["qa_id"] for item in items] == [first, second]
    assert [item["dataset_sequence"] for item in items] == [1, 2]


def test_run_filename_is_sanitized():
    filename = build_run_excel_filename(
        {"run_id": 42, "dataset_id": 7, "dataset_name": ' 안전<>:"/\\|?*평가. '},
        datetime(2026, 8, 6, 14, 30, 12),
    )
    assert filename == "평가실행_안전_________평가_run_42_20260806_143012.xlsx"


@pytest.fixture
def client(tmp_path):
    db = database.get_database_manager(str(tmp_path / "run-api.db"))
    db.execute_update(
        "INSERT INTO tb_collections (display_name, qdrant_name) VALUES (?, ?)",
        ("평가용 컬렉션", "run_excel_api"),
    )
    collection_id = db.execute_query(
        "SELECT collection_id FROM tb_collections WHERE qdrant_name = ?", ("run_excel_api",)
    )[0]["collection_id"]
    app = FastAPI()
    app.include_router(eval_router, prefix="/api")
    app.dependency_overrides[get_current_admin] = lambda: {"admin_id": "admin"}
    test_client = TestClient(app)
    test_client._collection_id = collection_id
    return test_client


def _seed_api_run(client, status="completed", with_metrics=True):
    repo = EvalRepository()
    dataset_id = repo.create_dataset("한글 평가 실행", client._collection_id, {})
    qa_id = repo.insert_qa_item(
        dataset_id, "안전난간 높이 기준은 무엇인가요?", "기준 답변입니다.",
        ["c1"], ["d1"], ["근거"], "factual",
    )
    repo.update_qa_item(qa_id, review_status="approved")
    goldset_id = repo.create_goldset(dataset_id)
    run_id = repo.create_run(
        goldset_id, "full", {"retrieval_top_n": 10, "rerank_top_k": 5, "metric_version": "rule-v1.1"}, 1,
    )
    item_metrics = {
        "retrieval.rrf.recall@10": {"value": 1.0, "status": "evaluated"},
        "retrieval.rerank.ndcg@5": {"value": .9, "status": "evaluated"},
        "answer.correctness": {"value": .8, "status": "evaluated"},
        "citation.completeness": {"value": .7, "status": "evaluated"},
    }
    repo.insert_item_result(run_id, qa_id, status="ok", metric_status_json=item_metrics)
    if with_metrics:
        repo.save_run_metrics(run_id, {"all": {
            "retrieval.rrf.recall@10": {"value": 1.0, "std": 0.0, "evaluated_count": 1, "total_count": 1},
            "retrieval.rerank.ndcg@5": {"value": .9, "std": 0.0, "evaluated_count": 1, "total_count": 1},
            "answer.correctness": {"value": .8, "std": 0.0, "evaluated_count": 1, "total_count": 1},
            "citation.completeness": {"value": .7, "std": 0.0, "evaluated_count": 1, "total_count": 1},
            "retrieval.rerank.mrr@5": {"value": .9, "std": 0.0, "evaluated_count": 1, "total_count": 1},
            "retrieval.rrf.ndcg@10": {"value": .95, "std": 0.0, "evaluated_count": 1, "total_count": 1},
        }})
    repo.update_run_status(run_id, status)
    return run_id


def test_download_run_api_returns_two_sheet_workbook_and_headers(client):
    run_id = _seed_api_run(client)

    response = client.get(f"/api/eval/runs/{run_id}/results.xlsx")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert f'filename="eval_run_{run_id}.xlsx"' in response.headers["content-disposition"]
    assert "filename*=UTF-8''" in response.headers["content-disposition"]
    assert response.headers["cache-control"] == "no-store"
    workbook = load_workbook(filename=BytesIO(response.content))
    assert workbook.sheetnames == ["지표 요약", "항목별 결과"]
    assert workbook["항목별 결과"]["C2"].value == "안전난간 높이 기준은 무엇인가요?"


def test_download_run_api_rejects_missing_incomplete_and_empty_results(client):
    missing = client.get("/api/eval/runs/99999/results.xlsx")
    assert missing.status_code == 404

    running_id = _seed_api_run(client, status="running")
    running = client.get(f"/api/eval/runs/{running_id}/results.xlsx")
    assert running.status_code == 409
    assert running.json()["detail"] == "완료된 평가 실행만 다운로드할 수 있습니다."

    empty_id = _seed_api_run(client, with_metrics=False)
    empty = client.get(f"/api/eval/runs/{empty_id}/results.xlsx")
    assert empty.status_code == 400
    assert empty.json()["detail"] == "다운로드할 평가 결과가 없습니다."


def test_download_run_api_requires_admin_authentication():
    app = FastAPI()
    app.include_router(eval_router, prefix="/api")
    response = TestClient(app).get("/api/eval/runs/1/results.xlsx")
    assert response.status_code == 401

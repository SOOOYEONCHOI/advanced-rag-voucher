import json
from datetime import datetime
from io import BytesIO

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app.evaluation.excel_exporter import (
    QA_HEADERS,
    build_approved_dataset_workbook,
    build_excel_filename,
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


def test_repository_lists_only_approved_and_edited_in_qa_order(tmp_path):
    db = database.get_database_manager()
    db.execute_update(
        "INSERT INTO tb_collections (display_name, qdrant_name) VALUES (?, ?)",
        ("컬렉션", "excel_export"),
    )
    collection_id = db.execute_query(
        "SELECT collection_id FROM tb_collections WHERE qdrant_name = ?", ("excel_export",)
    )[0]["collection_id"]
    repo = EvalRepository()
    dataset_id = repo.create_dataset("데이터셋", collection_id, {})
    approved_id = repo.insert_qa_item(
        dataset_id, "승인 질문", "승인 답변", ["c1"], ["d1"], ["근거1"], "factual"
    )
    repo.insert_qa_item(
        dataset_id, "대기 질문", "대기 답변", ["c2"], ["d2"], ["근거2"], "factual"
    )
    edited_id = repo.insert_qa_item(
        dataset_id, "수정 질문", "수정 답변", ["c3"], ["d3"], ["근거3"], "procedural"
    )
    rejected_id = repo.insert_qa_item(
        dataset_id, "반려 질문", "반려 답변", ["c4"], ["d4"], ["근거4"], "comparative"
    )
    repo.update_qa_item(approved_id, review_status="approved")
    repo.update_qa_item(edited_id, review_status="edited")
    repo.update_qa_item(rejected_id, review_status="rejected")

    items = repo.list_approved_qa_items(dataset_id)

    assert [item["qa_id"] for item in items] == [approved_id, edited_id]
    assert [item["review_status"] for item in items] == ["approved", "edited"]


def test_workbook_contains_expected_sheets_content_and_safe_text():
    dataset = {
        "dataset_id": 7,
        "name": "안전 데이터셋",
        "collection_name": "법령",
        "status": "review",
        "created_at": "2026-08-01T10:00:00+09:00",
        "updated_at": "2026-08-02T10:00:00+09:00",
    }
    items = [{
        "qa_id": 3,
        "question_type": "multihop",
        "question": "=SUM(A1:A2)",
        "gold_answer": "정답",
        "source_meta_json": json.dumps({
            "original_filename": "규칙.pdf", "section_title": "제316조", "page_number": 57,
        }, ensure_ascii=False),
        "gold_chunk_texts": json.dumps(["첫 근거", "둘째 근거"], ensure_ascii=False),
        "difficulty": "hard",
        "expected_behavior": "answer",
        "tags": json.dumps(["legal_reference", "compound_term"]),
        "review_status": "approved",
        "reviewed_by": "admin",
        "reviewed_at": "2026-08-02T11:00:00+09:00",
        "gold_document_ids": json.dumps(["d1", "d2"]),
        "gold_chunk_ids": json.dumps(["c1", "c2"]),
        "self_valid_rank": 1,
        "created_at": "2026-08-01T10:00:00+09:00",
    }]

    workbook = load_workbook(build_approved_dataset_workbook(dataset, items))
    qa = workbook["QA"]

    assert workbook.sheetnames == ["QA", "정보"]
    assert [cell.value for cell in qa[1]] == QA_HEADERS
    assert [qa.cell(2, column).value for column in range(1, 6)] == [
        "멀티홉", "'=SUM(A1:A2)", "정답", "규칙.pdf · 제316조 · p.57", "첫 근거\n\n둘째 근거",
    ]
    assert qa.freeze_panes == "A2"
    assert qa.auto_filter.ref == qa.dimensions
    assert workbook["정보"]["B5"].value == 1


def test_workbook_keeps_invalid_json_as_text_and_filename_is_sanitized():
    item = {
        "qa_id": 1, "question_type": "factual", "question": "질문", "gold_answer": "답변",
        "source_meta_json": "{broken", "gold_chunk_texts": "[broken", "tags": "[broken",
        "gold_document_ids": "[broken", "gold_chunk_ids": "[broken", "review_status": "edited",
    }
    workbook = load_workbook(build_approved_dataset_workbook({"dataset_id": 1}, [item]))
    qa = workbook["QA"]

    assert qa["D2"].value == "{broken"
    assert qa["E2"].value == "[broken"
    assert build_excel_filename(
        {"dataset_id": 1, "name": ' 금지<>:"/\\|?*이름. '}, datetime(2026, 8, 6, 12, 30, 45)
    ) == "평가데이터셋_금지_________이름_20260806_123045.xlsx"


@pytest.fixture
def client(tmp_path):
    db = database.get_database_manager()
    db.execute_update(
        "INSERT INTO tb_collections (display_name, qdrant_name) VALUES (?, ?)",
        ("평가용 컬렉션", "excel_api"),
    )
    collection_id = db.execute_query(
        "SELECT collection_id FROM tb_collections WHERE qdrant_name = ?", ("excel_api",)
    )[0]["collection_id"]
    app = FastAPI()
    app.include_router(eval_router, prefix="/api")
    app.dependency_overrides[get_current_admin] = lambda: {"admin_id": "admin"}
    test_client = TestClient(app)
    test_client._collection_id = collection_id
    return test_client


def test_download_api_returns_openable_workbook_and_headers(client):
    repo = EvalRepository()
    dataset_id = repo.create_dataset("한글 데이터셋", client._collection_id, {})
    qa_id = repo.insert_qa_item(
        dataset_id, "질문", "답변", ["c1"], ["d1"], ["근거"], "factual"
    )
    repo.update_qa_item(qa_id, review_status="approved")

    response = client.get(f"/api/eval/datasets/{dataset_id}/approved-items.xlsx")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert 'filename="eval_dataset_' in response.headers["content-disposition"]
    assert "filename*=UTF-8''" in response.headers["content-disposition"]
    assert response.headers["cache-control"] == "no-store"
    workbook = load_workbook(filename=BytesIO(response.content))
    assert workbook["QA"]["B2"].value == "질문"


def test_download_api_returns_404_and_400(client):
    missing = client.get("/api/eval/datasets/99999/approved-items.xlsx")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "평가 데이터셋을 찾을 수 없습니다."

    dataset_id = EvalRepository().create_dataset("빈 데이터셋", client._collection_id, {})
    empty = client.get(f"/api/eval/datasets/{dataset_id}/approved-items.xlsx")
    assert empty.status_code == 400
    assert empty.json()["detail"] == "다운로드할 승인 QA 항목이 없습니다."


def test_download_api_requires_admin_authentication():
    app = FastAPI()
    app.include_router(eval_router, prefix="/api")

    response = TestClient(app).get("/api/eval/datasets/1/approved-items.xlsx")

    assert response.status_code == 401

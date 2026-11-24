"""UI-12 모델명(tb_documents.product_model) 업로드·조회·수정·백필 (2026.10.19 모델명 관리 1단계).

근거: docs/design/문서 관리 모델명·버전 관리 개선 요청서.md 3·5·9절. 관련 ID: UI-12, SC-06(후속 버전 관리 전제).
- 업로드: 파일별 product_model 전달, 필드 누락 = 파일명 기본값, 명시적 빈 값·공백·101자 = 422, 100자 허용.
- 목록: 대화 주제 지정·전체 조회 모두 product_model·version_no·updated_at·can_edit 반환.
- 수정: PATCH /ingest/documents/{id}/model-name — 버전·작업 변화 없음, 'update' 이벤트, 권한·404·422.
- 백필(Alembic 0004): 빈 값만 파일명 기본값으로 채우고 입력값·최근 변경일은 그대로.
"""
import json
from types import SimpleNamespace

import pytest
from alembic import command
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.ingest.model_name import default_model_name, validate_model_name
from app.repositories.database import get_database_manager
from app.routes import ingest
from app.utils.security import get_current_principal

NAME_100 = "가" * 100
NAME_101 = "가" * 101


def _settings(tmp_path):
    return SimpleNamespace(
        uploaded_files_base_dir=str(tmp_path / "instance" / "data"), instance_dir=str(tmp_path / "instance"),
        excel_parse_mode="docling",
    )


def _seed():
    db = get_database_manager()
    db.execute_update(
        "INSERT INTO tb_collections (display_name, qdrant_name) VALUES ('documents', 'documents'), ('secret', 'secret')"
    )
    for user_id in ("owner", "worker", "outsider"):
        db.execute_update("INSERT INTO tb_users (user_id, user_pwd, role) VALUES (?, 'x', 'user')", (user_id,))
    return db


def _insert_document(db, document_id, *, collection="documents", uploaded_by="owner", product_model=None,
                     filename="C2.assembly.rev2.pdf", deleted=False):
    db.execute_update(
        """INSERT INTO tb_documents (document_id, collection_id, uploaded_by, original_filename, source_path,
                                     product_model, version_no, updated_at, deleted_at)
           VALUES (?, (SELECT collection_id FROM tb_collections WHERE qdrant_name = ?), ?, ?, 'p', ?, 3,
                   '2026-01-02T03:04:05+00:00', CASE WHEN ? THEN now() END)""",
        (document_id, collection, uploaded_by, filename, product_model, deleted),
    )


@pytest.fixture
def api(monkeypatch, tmp_path):
    queued = []

    async def enqueue(job_id):
        queued.append(job_id)

    db = _seed()
    principal = dict(user_id="admin", is_admin=True)
    permissions = {"worker": ["documents"], "outsider": ["documents"]}
    monkeypatch.setattr(ingest, "get_settings", lambda: _settings(tmp_path))
    monkeypatch.setattr(ingest, "MetadataRepository", lambda *_: SimpleNamespace(
        get_user_permissions=lambda user_id: SimpleNamespace(
            accessible_collections=permissions.get(user_id, []), max_security_level="public"
        ) if user_id in permissions else None
    ))
    monkeypatch.setattr(ingest, "get_ingest_job_manager", lambda: SimpleNamespace(enqueue=enqueue))
    # 목록 조회는 IngestService.list_documents만 쓰므로 임베딩 등 초기화 없이 저장소만 붙인다
    #   (다른 테스트가 설정 모듈을 stub으로 바꿔도 순서와 무관하게 동작 — phase-1_5 7절의 순서 의존 문제 회피)
    #   sys.modules 쪽 모듈도 stub일 수 있어, 라우트·서비스가 import 시점에 잡은 실제 클래스를 쓴다.
    IngestService = ingest.IngestService
    DocumentRepository = ingest.DocumentRepository
    CollectionRepository = IngestService.list_documents.__globals__["CollectionRepository"]

    def _list_service():
        service = object.__new__(IngestService)
        service.db, service.doc_repo, service.collection_repo = db, DocumentRepository(), CollectionRepository()
        return service

    monkeypatch.setattr(ingest, "IngestService", _list_service)
    app = FastAPI()
    app.include_router(ingest.router, prefix="/api")
    app.dependency_overrides[get_current_principal] = lambda: principal
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, db=db, queued=queued, principal=principal, permissions=permissions)


def _upload(client, filename, **form):
    return client.post("/api/ingest/upload", files={"file": (filename, b"fixture", "application/pdf")}, data=form)


def _job_model(job_id):
    return ingest.IngestJobRepository().get(job_id)["request"]["product_model"]


# ── 규칙 ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("filename, expected", [
    ("C2.assembly.rev2.pdf", "C2.assembly.rev2"),   # 마지막 확장자만 제거
    ("NEOCON C2 제조 관리 문서 대장.xlsx", "NEOCON C2 제조 관리 문서 대장"),
    ("README", "README"),
    ("  공백 파일 .pdf", "공백 파일"),
    (".pdf", ""),
])
def test_default_model_name_removes_only_last_extension(filename, expected):
    assert default_model_name(filename) == expected


def test_validate_model_name_trims_and_limits_length():
    assert validate_model_name("  NEOCON C2  ") == "NEOCON C2"
    assert validate_model_name(NAME_100) == NAME_100
    for bad in ("", "   ", None, NAME_101):
        with pytest.raises(ValueError):
            validate_model_name(bad)


# ── 업로드 ──────────────────────────────────────────────────────────────────

def test_each_upload_keeps_its_own_model_name(api):
    first = _upload(api.client, "a.pdf", product_model="NEOCON C2 제조 관리 문서 대장")
    second = _upload(api.client, "b.pdf", product_model="  NEOCON C3 조립 절차서  ")
    assert first.status_code == second.status_code == 202
    assert _job_model(first.json()["job_id"]) == "NEOCON C2 제조 관리 문서 대장"
    assert _job_model(second.json()["job_id"]) == "NEOCON C3 조립 절차서"   # 앞뒤 공백 제거


def test_missing_field_uses_filename_default(api):
    response = _upload(api.client, "C2.assembly.rev2.pdf")
    assert response.status_code == 202
    assert _job_model(response.json()["job_id"]) == "C2.assembly.rev2"


@pytest.mark.parametrize("value", ["", "   ", NAME_101])
def test_explicit_invalid_model_name_is_rejected(api, value):
    response = _upload(api.client, "a.pdf", product_model=value)
    assert response.status_code == 422
    assert "모델명" in response.json()["detail"]
    assert api.queued == []


def test_hundred_characters_allowed_and_long_default_rejected(api):
    assert _upload(api.client, "a.pdf", product_model=NAME_100).status_code == 202
    long_default = _upload(api.client, f"{NAME_101}.pdf")
    assert long_default.status_code == 422          # 자동 생성값도 잘라내지 않는다
    assert len(api.queued) == 1


# ── 목록 ────────────────────────────────────────────────────────────────────

def test_document_list_returns_model_version_and_change_time(api):
    _insert_document(api.db, "doc-1", product_model="NEOCON C2 제조 관리 문서 대장")
    for params in ({}, {"collection_name": "documents"}):
        documents = api.client.get("/api/ingest/documents", params=params).json()["documents"]
        assert len(documents) == 1
        item = documents[0]
        assert item["product_model"] == "NEOCON C2 제조 관리 문서 대장"
        assert item["filename"] == "C2.assembly.rev2.pdf"
        assert item["version_no"] == 3
        assert item["updated_at"] == "2026-01-02 12:04:05"     # KST
        assert item["can_edit"] is True


# ── 수정 ────────────────────────────────────────────────────────────────────

def _patch(client, document_id, body):
    return client.patch(f"/api/ingest/documents/{document_id}/model-name", json=body)


def test_patch_updates_only_model_name_and_records_event(api):
    _insert_document(api.db, "doc-1", product_model="old")
    response = _patch(api.client, "doc-1", {"product_model": "  NEOCON C2 제조 관리 문서 대장 "})
    assert response.status_code == 200
    assert response.json()["product_model"] == "NEOCON C2 제조 관리 문서 대장"
    row = api.db.execute_query(
        "SELECT product_model, version_no, updated_at > '2026-01-02T03:04:05+00:00' AS touched "
        "FROM tb_documents WHERE document_id = 'doc-1'"
    )[0]
    assert (row["product_model"], row["version_no"], row["touched"]) == ("NEOCON C2 제조 관리 문서 대장", 3, True)
    events = api.db.execute_query("SELECT event_type, actor_id, snapshot_json FROM tb_document_events")
    assert [(e["event_type"], e["actor_id"]) for e in events] == [("update", "admin")]
    snapshot = events[0]["snapshot_json"]
    snapshot = json.loads(snapshot) if isinstance(snapshot, str) else snapshot
    assert (snapshot["field"], snapshot["before"]) == ("product_model", "old")
    # 재파싱·재임베딩 없음: 작업이 생기지 않는다
    assert api.queued == []
    assert api.db.execute_query("SELECT count(*) FROM tb_ingest_jobs")[0][0] == 0
    # 새로고침(재조회) 후에도 유지
    listed = api.client.get("/api/ingest/documents").json()["documents"][0]
    assert listed["product_model"] == "NEOCON C2 제조 관리 문서 대장"


def test_patch_same_value_does_not_record_event(api):
    _insert_document(api.db, "doc-1", product_model="same")
    assert _patch(api.client, "doc-1", {"product_model": "same"}).status_code == 200
    assert api.db.execute_query("SELECT count(*) FROM tb_document_events")[0][0] == 0


@pytest.mark.parametrize("body", [{"product_model": ""}, {"product_model": "  "}, {"product_model": NAME_101}, {}])
def test_patch_rejects_invalid_or_missing_value(api, body):
    _insert_document(api.db, "doc-1", product_model="keep")
    assert _patch(api.client, "doc-1", body).status_code == 422
    assert api.db.execute_query("SELECT product_model FROM tb_documents")[0][0] == "keep"


def test_patch_hundred_characters_allowed(api):
    _insert_document(api.db, "doc-1")
    assert _patch(api.client, "doc-1", {"product_model": NAME_100}).status_code == 200


def test_patch_missing_or_deleted_document_is_404(api):
    _insert_document(api.db, "gone", deleted=True)
    assert _patch(api.client, "nope", {"product_model": "x"}).status_code == 404
    assert _patch(api.client, "gone", {"product_model": "x"}).status_code == 404


def test_patch_permissions_follow_delete_rule(api):
    _insert_document(api.db, "mine", uploaded_by="worker", product_model="keep")
    _insert_document(api.db, "others", uploaded_by="owner", product_model="keep")
    _insert_document(api.db, "hidden", collection="secret", uploaded_by="worker", product_model="keep")
    api.principal.update(user_id="worker", is_admin=False)
    assert _patch(api.client, "mine", {"product_model": "changed"}).status_code == 200
    assert _patch(api.client, "others", {"product_model": "changed"}).status_code == 403
    # 접근 권한 없는 대화 주제의 문서는 존재를 숨긴다(D-04)
    assert _patch(api.client, "hidden", {"product_model": "changed"}).status_code == 404
    listed = {d["document_id"]: d for d in api.client.get("/api/ingest/documents").json()["documents"]}
    assert set(listed) == {"mine", "others"}
    assert (listed["mine"]["can_edit"], listed["others"]["can_edit"]) == (True, False)
    models = dict(api.db.execute_query("SELECT document_id, product_model FROM tb_documents"))
    assert models == {"mine": "changed", "others": "keep", "hidden": "keep"}


# ── 백필(Alembic 0004) ─────────────────────────────────────────────────────

def test_0004_backfills_only_empty_model_names(postgres_schema):
    command.downgrade(postgres_schema, "0003_versions_chunks_images")
    try:
        db = _seed()
        _insert_document(db, "null", product_model=None, filename="C2.assembly.rev2.pdf")
        _insert_document(db, "blank", product_model="   ", filename="NEOCON C3 조립 절차서.xlsx")
        _insert_document(db, "kept", product_model="사용자 입력값", filename="other.pdf")
        _insert_document(db, "too-long", product_model=None, filename=f"{NAME_101}.pdf")
        _insert_document(db, "deleted", product_model=None, filename="del.pdf", deleted=True)
    finally:
        command.upgrade(postgres_schema, "head")
    rows = {r["document_id"]: r for r in db.execute_query(
        "SELECT document_id, product_model, updated_at = '2026-01-02T03:04:05+00:00' AS same_time FROM tb_documents"
    )}
    assert {k: r["product_model"] for k, r in rows.items()} == {
        "null": "C2.assembly.rev2",
        "blank": "NEOCON C3 조립 절차서",
        "kept": "사용자 입력값",
        "too-long": None,        # 잘라내지 않고 남김(목록에서 직접 입력)
        "deleted": None,
    }
    assert all(r["same_time"] for r in rows.values())   # 백필은 최근 변경일을 바꾸지 않는다
    # 'update' 이벤트 유형 허용
    db.execute_update(
        "INSERT INTO tb_document_events (document_id, event_type) VALUES ('kept', 'update')"
    )

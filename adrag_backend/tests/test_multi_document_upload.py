"""Existing single-file API contracts used by the multi-file screen.

Storage and the ingestion service are isolated; no production documents are written.
2026.10.08 수정 - Phase 3: job 저장소는 실제 PostgreSQL 테스트 DB(tb_ingest_jobs 큐)를 쓴다.
워커 복구·순차 실행 검증은 tests/test_ingest_queue_versions.py로 옮겼다.
"""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.repositories.database import get_database_manager
from app.routes import ingest
from app.utils.security import get_current_principal


def upload_settings(tmp_path, **overrides):
    values = dict(
        # 2026.10.16 Phase 1.5: 업로드 큐 폴더가 sqlite_db_path 기준(routes/ingest.py)이라 tmp 아래로 둔다
        sqlite_db_path=str(tmp_path / "instance" / "db" / "unused.db"), instance_dir=str(tmp_path / "instance"),
        excel_parse_mode="docling",
        ingest_rate_limit_per_minute=0,
        ingest_max_active_jobs_per_user=0,
        ingest_max_upload_mb=200,
        ingest_max_attempts=3,
        ingest_queue_warn_threshold=20,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def seed_upload_db(*users):
    db = get_database_manager()
    db.execute_update(
        "INSERT INTO tb_collections (display_name, qdrant_name) VALUES ('documents', 'documents') "
        "ON CONFLICT (qdrant_name) DO NOTHING"
    )
    for user_id in users:
        db.execute_update(
            "INSERT INTO tb_users (user_id, user_pwd, role) VALUES (?, 'x', 'user') ON CONFLICT DO NOTHING", (user_id,)
        )


@pytest.fixture
def upload_api(monkeypatch, tmp_path):
    queued = []

    async def enqueue(job_id):
        queued.append(job_id)

    async def retry(job_id):
        if not ingest.IngestJobRepository().requeue_failed(job_id):
            raise ValueError("Not failed")
        queued.append(job_id)

    seed_upload_db("owner", "another-user")
    principal = dict(user_id="owner", is_admin=True)
    monkeypatch.setattr(ingest, "get_settings", lambda: upload_settings(tmp_path))
    monkeypatch.setattr(ingest, "MetadataRepository", lambda *_: SimpleNamespace(get_user_permissions=lambda _: None))
    monkeypatch.setattr(ingest, "get_ingest_job_manager", lambda: SimpleNamespace(enqueue=enqueue, retry=retry))
    app = FastAPI()
    app.include_router(ingest.router, prefix="/api")
    app.dependency_overrides[get_current_principal] = lambda: principal
    with TestClient(app) as client:
        yield client, ingest.IngestJobRepository(), queued, principal


def test_ten_individual_uploads_create_ten_independent_jobs(upload_api):
    client, jobs, queued, _ = upload_api
    for index in range(10):
        response = client.post(
            "/api/ingest/upload", files={"file": (f"{index}.pdf", f"fixture {index}".encode(), "application/pdf")}
        )
        assert response.status_code == 202
        assert response.json()["status"] == "queued"
    assert len(queued) == len(set(queued)) == 10
    assert [jobs.get(job_id)["request"]["filename"] for job_id in queued] == [f"{i}.pdf" for i in range(10)]


def test_rejected_file_does_not_prevent_following_upload(upload_api):
    client, jobs, queued, _ = upload_api
    invalid = client.post("/api/ingest/upload", files={"file": ("bad.xls", b"fixture")})
    valid = client.post("/api/ingest/upload", files={"file": ("good.pdf", b"fixture")})
    assert invalid.status_code == 400
    assert valid.status_code == 202
    assert len(queued) == 1


def test_job_owner_permissions_and_retry_contract(upload_api):
    client, jobs, queued, principal = upload_api
    job_id = client.post("/api/ingest/upload", files={"file": ("one.pdf", b"fixture")}).json()["job_id"]
    principal.update(user_id="another-user", is_admin=False)
    assert client.get(f"/api/ingest/jobs/{job_id}").status_code == 403
    assert client.post(f"/api/ingest/jobs/{job_id}/retry").status_code == 403
    principal["user_id"] = "owner"
    assert client.get(f"/api/ingest/jobs/{job_id}").status_code == 200
    assert client.post(f"/api/ingest/jobs/{job_id}/retry").status_code == 409
    jobs.fail(job_id, "embed", "임베딩 서버 오류")
    response = client.post(f"/api/ingest/jobs/{job_id}/retry")
    assert response.status_code == 202
    assert response.json()["job_id"] == job_id
    assert response.json()["status"] == "queued"
    assert response.json()["current_step"] == "embed"
    assert queued == [job_id, job_id]

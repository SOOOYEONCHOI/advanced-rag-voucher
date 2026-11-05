"""Phase 3 - 작업 큐·동시 업로드·버전 전환 테스트 (2026.10.08, 설계 A-3·A-4).

업로드 API → PostgreSQL 큐(tb_ingest_jobs) → 워커(IngestJobManager) → 적재·버전 전환을 실제 경로로 실행한다.
외부 서버(임베딩·Qdrant·docling)만 가짜(tests/excel_ingest_fakes.py), DB는 PostgreSQL 테스트 DB.

설계 A-3 테스트 시나리오
1. 동일 파일 10명 동시 업로드 → active 1건, 나머지 duplicate
2. 서로 다른 파일 20건 동시 업로드 → 전부 active, 이미지 키 충돌 0건
3. 같은 doc_key 새 버전 3건 연속 업로드 → 순차 적재, 최종 버전만 active
4. 적재 중 워커 강제 종료 → 재시도 후 정상 active, 중복 청크 0건
+ A-4 적재 중 검색 시 신·구 버전 혼재 0건, 롤백, 작업지시서 "동시 업로드 10건 데드락·커넥션 고갈 0건"

2026.10.12 추가 - Phase 3 보완(작업지시서 v2.3 완료 기준)
+ 워커 3개 동시 꺼내기에서 같은 작업 중복 처리 0건
+ 처리 중 워커 프로세스 강제 종료 → 임대 만료 후 다른 워커가 회수해 정상 완료
+ LISTEN/NOTIFY 깨우기, 재시도 백오프(JOB_RETRY_BASE_S × 2^n), 우선순위·큐 구분, MAINT 예약
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import openpyxl
import pytest
from fastapi import FastAPI
from openpyxl.drawing.image import Image as XLImage
from PIL import Image

from app.ingest.doc_key import normalize_doc_key
from app.parsers.models import LCDocument
from app.repositories.database import get_database_manager
from app.repositories.ingest_job_repository import IngestJobRepository
from app.repositories.ingest_record_repository import IngestRecordRepository, version_key

from app.routes import ingest
from app.services import ingest_jobs, ingest_pipeline, maintenance
from app.utils.security import get_current_principal
from excel_ingest_fakes import FakeVectorRepository, make_ingest_service
from test_multi_document_upload import seed_upload_db, upload_settings

COLLECTION = "documents"
USERS = [f"user{i}" for i in range(10)]


# ── 조립 ──────────────────────────────────────────────────────────────────

def worker_settings(**overrides):
    values = dict(
        excel_parse_mode="docling", resource_delivery="pull", md_save_dir="", max_chunk_size=800,
        excel_md_keep_last=5, excel_xls_convert_timeout=120,
        ingest_workers=1, job_poll_s=0.05, job_lease_s=60, job_heartbeat_s=15, job_retry_base_s=30,
        ingest_max_attempts=3, version_retain_days=7,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def text_chunks(file_path: str) -> list[LCDocument]:
    """가짜 docling 파서: 파일 내용 줄마다 청크 1개."""
    lines = Path(file_path).read_bytes().decode("utf-8", "replace").splitlines()
    return [LCDocument(page_content=line, metadata={"page": i + 1}) for i, line in enumerate(lines) if line.strip()]


class Env:
    """업로드 API 클라이언트 + 가짜 외부 서버를 쓰는 워커."""

    def __init__(self, tmp_path: Path, monkeypatch, **settings):
        self.tmp_path = tmp_path
        self.settings = worker_settings(**settings)
        self.vector_repo = FakeVectorRepository()
        self.upsert_hooks: list = []
        self.service = make_ingest_service(tmp_path / "xl_res", tmp_path / "chunk", vector_repo=self.vector_repo)
        self.service._parse_and_chunk = lambda file_path, *args, **kwargs: {
            "chunks": text_chunks(file_path), "doc_type": "general", "total_pages": 1,
            "chunk_count": len(text_chunks(file_path)), "is_law": False, "is_manual": False,
        }
        original_upsert = self.vector_repo.upsert_points

        def upsert(collection_name, points, batch_size=None):
            original_upsert(collection_name, points, batch_size)
            for hook in list(self.upsert_hooks):
                hook(points)

        self.vector_repo.upsert_points = upsert
        monkeypatch.setattr(ingest_pipeline, "get_settings", lambda: self.settings)
        monkeypatch.setattr(ingest_jobs, "get_settings", lambda: self.settings)
        monkeypatch.setattr(ingest_jobs, "IngestService", lambda: self.service)
        seed_upload_db(*USERS, "admin")
        monkeypatch.setattr(ingest, "get_settings", lambda: upload_settings(tmp_path))
        monkeypatch.setattr(ingest, "MetadataRepository", lambda *_: SimpleNamespace(get_user_permissions=lambda _: None))

        async def enqueue(job_id):
            return None

        monkeypatch.setattr(ingest, "get_ingest_job_manager", lambda: SimpleNamespace(enqueue=enqueue))
        self.principal = {"user_id": "user0", "is_admin": True}
        app = FastAPI()
        app.include_router(ingest.router, prefix="/api")
        app.dependency_overrides[get_current_principal] = lambda: self.principal
        self.app = app

    def client(self, user_id: str = "user0") -> httpx.AsyncClient:
        principal = {"user_id": user_id, "is_admin": True}
        app = FastAPI()
        app.include_router(ingest.router, prefix="/api")
        app.dependency_overrides[get_current_principal] = lambda: principal
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://backend")

    async def upload(self, filename: str, content: bytes, *, user_id: str = "user0", **form) -> dict:
        async with self.client(user_id) as client:
            response = await client.post(
                "/api/ingest/upload", files={"file": (filename, content)},
                data={"collection_name": COLLECTION, **form},
            )
        assert response.status_code == 202, response.text
        return response.json()

    async def drain(self, concurrency: int = 1, timeout: float = 120, *, managers: int = 1) -> None:
        """대기·실행 중 INGEST job이 없어질 때까지 워커를 돌린다(``managers``개 = 워커 프로세스 여러 개 흉내)."""
        workers = [
            ingest_jobs.IngestJobManager(concurrency=concurrency, name=f"test{i}", queues=("INGEST",))
            for i in range(managers)
        ]
        for manager in workers:
            await manager.start()
        try:
            await wait_ingest_idle(timeout)
        finally:
            for manager in workers:
                await manager.stop()


async def wait_ingest_idle(timeout: float = 120) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        rows = get_database_manager().execute_query(
            "SELECT count(*) FROM tb_ingest_jobs WHERE queue_cd='INGEST' AND status IN ('queued','running') "
            "AND next_run_at <= now()"
        )
        if rows[0][0] == 0:
            return
        await asyncio.sleep(0.05)
    raise AssertionError("워커가 시간 안에 job을 끝내지 못했습니다.")


def jobs_by_status() -> dict[str, int]:
    rows = get_database_manager().execute_query("SELECT status, count(*) FROM tb_ingest_jobs GROUP BY status")
    return {row[0]: int(row[1]) for row in rows}


def versions_of(document_id: str) -> dict[int, str]:
    rows = get_database_manager().execute_query(
        "SELECT version, status FROM tb_document_versions WHERE document_id=? ORDER BY version", (document_id,)
    )
    return {int(row[0]): row[1] for row in rows}


def visible_points(vector_repo: FakeVectorRepository) -> list:
    """검색이 보는 point = 비활성 버전 키를 must_not으로 제외한 나머지(build_metadata_filter와 같은 규칙)."""
    excluded = set(IngestRecordRepository().inactive_version_keys())
    return [p for p in vector_repo.points.get(COLLECTION, []) if p.payload.get("version_key") not in excluded]


# ── 설계 A-3 테스트 시나리오 ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_same_file_uploaded_by_ten_users_concurrently_one_active_rest_duplicate(tmp_path, monkeypatch):
    env = Env(tmp_path, monkeypatch)
    content = "안전 수칙 1\n안전 수칙 2\n안전 수칙 3\n".encode()
    responses = await asyncio.gather(*(env.upload("안전수칙.pdf", content, user_id=u) for u in USERS))
    assert len({r["job_id"] for r in responses}) == 10
    await env.drain(concurrency=4)

    assert jobs_by_status() == {"completed": 1, "skipped": 9}
    active = get_database_manager().execute_query(
        "SELECT document_id FROM tb_document_versions WHERE status='active'"
    )
    assert len(active) == 1
    skipped = get_database_manager().execute_query(
        "SELECT result_json FROM tb_ingest_jobs WHERE status='skipped'"
    )
    assert all('"duplicate"' in str(row[0]) and active[0][0] in str(row[0]) for row in skipped)
    assert len(env.vector_repo.points[COLLECTION]) == 3

    # 활성화된 뒤 같은 파일을 다시 올리면 업로드 단계에서 바로 skipped
    again = await env.upload("안전수칙(1).pdf", content, user_id="user1")
    assert again["status"] == "skipped" and again["result"]["reason"] == "duplicate"


def _photo(tmp_path: Path) -> Path:
    path = tmp_path / "photo.png"
    if not path.exists():
        buffer = io.BytesIO()
        Image.new("RGB", (40, 30), "red").save(buffer, format="PNG")
        path.write_bytes(buffer.getvalue())
    return path


def _workbook_bytes(tmp_path: Path, index: int) -> bytes:
    """서로 다른 내용 + 같은 사진 2장(이미지 키 공유)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f"작업{index}"
    ws.append(["No", "사진", "작업 내용", "Check Point"])
    ws.append([1, "", f"문서 {index} 조립", "볼트 체결"])
    ws.append([2, "", f"문서 {index} 검사", "외관 확인"])
    for row in (2, 3):
        ws.row_dimensions[row].height = 60
        ws.add_image(XLImage(str(_photo(tmp_path))), f"B{row}")
    path = tmp_path / f"wb{index}.xlsx"
    wb.save(path)
    return path.read_bytes()


@pytest.mark.asyncio
async def test_twenty_different_files_all_active_and_ten_concurrent_without_deadlock(tmp_path, monkeypatch):
    env = Env(tmp_path, monkeypatch, excel_parse_mode="backend")
    files = [(f"작업표준_{chr(65 + i)}{i}.xlsx", _workbook_bytes(tmp_path, i)) for i in range(20)]
    await asyncio.gather(*(env.upload(name, data, user_id=USERS[i % 10]) for i, (name, data) in enumerate(files)))

    db = get_database_manager()
    peak = {"connections": 0}
    deadlock_sql = "SELECT deadlocks FROM pg_stat_database WHERE datname = current_database()"
    deadlocks_before = int(db.execute_query(deadlock_sql)[0][0])

    async def sample_connections():
        while True:
            rows = db.execute_query(
                "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()"
            )
            peak["connections"] = max(peak["connections"], int(rows[0][0]))
            await asyncio.sleep(0.05)

    sampler = asyncio.create_task(sample_connections())
    try:
        await env.drain(concurrency=10)
    finally:
        sampler.cancel()

    assert jobs_by_status() == {"completed": 20}
    assert db.execute_query("SELECT count(*) FROM tb_document_versions WHERE status='active'")[0][0] == 20
    # 이미지 키(해시) 충돌 0건: 같은 사진은 asset 1건, 배치는 문서마다 2건
    assert db.execute_query("SELECT count(*) FROM tb_image_assets")[0][0] == 1
    assert db.execute_query("SELECT count(*) FROM tb_image_placements")[0][0] == 40
    assert len(list((tmp_path / "xl_res" / "assets").glob("*/*"))) == 1
    # 커넥션 고갈 없음: 워커 10개 + LISTEN 1 + 샘플러가 풀 상한(10+20) 안에서 동작
    max_connections = int(db.execute_query("SHOW max_connections")[0][0])
    assert peak["connections"] < max_connections
    # 데드락 없음: PostgreSQL deadlock 카운터가 늘지 않음(통계 반영 지연 대비 잠시 대기)
    await asyncio.sleep(0.6)
    assert int(db.execute_query(deadlock_sql)[0][0]) == deadlocks_before


@pytest.mark.asyncio
async def test_three_versions_of_same_doc_key_load_in_order_and_only_last_is_active(tmp_path, monkeypatch):
    env = Env(tmp_path, monkeypatch)
    names = ["작업표준_v1.pdf", "작업표준_v2.pdf", "작업표준 v3 (최종).pdf"]
    assert len({normalize_doc_key(n) for n in names}) == 1
    for index, name in enumerate(names, start=1):
        await env.upload(name, f"버전 {index} 내용\n공통 항목\n".encode())
    await env.drain(concurrency=3)

    db = get_database_manager()
    docs = db.execute_query("SELECT document_id, active_version, original_filename FROM tb_documents")
    assert len(docs) == 1
    document_id = docs[0]["document_id"]
    assert (docs[0]["active_version"], docs[0]["original_filename"]) == (3, names[2])
    assert versions_of(document_id) == {1: "retired", 2: "retired", 3: "active"}
    # 순차 적재: job 생성 순서 = 버전 순서, 실행 구간이 겹치지 않음
    jobs = db.execute_query(
        "SELECT version, started_at, finished_at FROM tb_ingest_jobs ORDER BY created_at"
    )
    assert [int(j["version"]) for j in jobs] == [1, 2, 3]
    for before, after in zip(jobs, jobs[1:]):
        assert before["finished_at"] <= after["started_at"]
    # 검색에는 최종 버전만: 보관 중인 v1·v2 point는 must_not으로 제외
    visible = visible_points(env.vector_repo)
    assert {p.payload["version"] for p in visible} == {3}
    assert {p.payload["text"] for p in visible} >= {"버전 3 내용"}
    # 원본 파일은 버전마다 따로 보존(롤백 대비)
    assert len({p.payload["source_path"] for p in env.vector_repo.points[COLLECTION]}) == 3


@pytest.mark.asyncio
async def test_worker_killed_mid_index_is_reclaimed_and_finishes_without_duplicate_chunks(tmp_path, monkeypatch):
    env = Env(tmp_path, monkeypatch)
    job = await env.upload("설비점검.pdf", "점검 1\n점검 2\n점검 3\n점검 4\n".encode())
    worker = ingest_jobs.IngestJobManager(concurrency=1, name="worker-a")
    claimed = IngestJobRepository().claim("worker-a:0")
    task = asyncio.create_task(worker.run_job(claimed, "worker-a:0"))
    loop = asyncio.get_running_loop()
    killed = asyncio.Event()

    def kill_after_points_written(points):
        # point 적재 직후(DB 커밋 전) 프로세스 강제 종료처럼 중단 — 훅은 적재 스레드에서 실행된다
        loop.call_soon_threadsafe(killed.set)
        loop.call_soon_threadsafe(task.cancel)

    env.upsert_hooks.append(kill_after_points_written)
    with pytest.raises(asyncio.CancelledError):
        await task
    assert killed.is_set()
    env.upsert_hooks.clear()
    stuck = IngestJobRepository().get(job["job_id"])
    assert stuck["status"] == "running" and stuck["current_step"] == "index"
    # 중단된 버전의 point는 검색에서 제외(job에 배정된 버전)
    assert visible_points(env.vector_repo) == []

    # 임대가 끝난 뒤 회수 → 다른 워커가 같은 단계(index)부터 재실행
    get_database_manager().execute_update(
        "UPDATE tb_ingest_jobs SET locked_until = now() - interval '1 second' WHERE job_id=?", (job["job_id"],)
    )
    summary = await ingest_jobs.IngestJobManager(concurrency=1, name="worker-b").reclaim_expired()
    assert summary == {"requeued": 1, "exhausted": 0}
    await env.drain()

    done = IngestJobRepository().get(job["job_id"])
    assert (done["status"], done["attempts"]) == ("completed", 2)
    points = env.vector_repo.points[COLLECTION]
    chunk_rows = get_database_manager().execute_query("SELECT chunk_id FROM tb_chunks")
    assert len(points) == len({p.id for p in points}) == len(chunk_rows) == 4  # 중복 청크 0건
    assert versions_of(done["document_id"]) == {1: "active"}
    assert len(visible_points(env.vector_repo)) == 4


# ── 설계 A-4: 적재 중 검색 일관성·롤백 ─────────────────────────────────────

@pytest.mark.asyncio
async def test_search_never_mixes_old_and_new_versions_during_reingest(tmp_path, monkeypatch):
    env = Env(tmp_path, monkeypatch)
    await env.upload("품질기준.pdf", "구버전 A\n구버전 B\n".encode())
    await env.drain()
    document_id = get_database_manager().execute_query("SELECT document_id FROM tb_documents")[0][0]

    observed = []

    def check_during_index(points):
        # 새 버전 point가 Qdrant에 들어갔지만 DB 활성화 전: 검색은 구버전만 본다
        observed.append({p.payload["version"] for p in visible_points(env.vector_repo)})

    env.upsert_hooks.append(check_during_index)
    await env.upload("품질기준.pdf", "신버전 A\n신버전 B\n신버전 C\n".encode())
    await env.drain()

    assert observed == [{1}]
    visible = visible_points(env.vector_repo)
    assert {p.payload["version"] for p in visible} == {2} and len(visible) == 3
    assert versions_of(document_id) == {1: "retired", 2: "active"}

    # 롤백(관리자 API): DB 전환만으로 즉시 구버전 검색
    async with env.client("admin") as client:
        started = time.monotonic()
        response = await client.post(f"/api/ingest/documents/{document_id}/versions/1/activate")
        elapsed = time.monotonic() - started
        assert response.status_code == 200, response.text
        listed = (await client.get(f"/api/ingest/documents/{document_id}/versions")).json()
    assert response.json() == {"document_id": document_id, "active_version": 1, "previous_version": 2}
    assert elapsed < 60
    assert {p.payload["version"] for p in visible_points(env.vector_repo)} == {1}
    assert [(v["version"], v["status"]) for v in listed["versions"]] == [(2, "retired"), (1, "active")]
    restored = get_database_manager().execute_query(
        "SELECT source_path, chunk_count FROM tb_documents WHERE document_id=?", (document_id,)
    )[0]
    assert restored["chunk_count"] == 2 and not restored["source_path"].endswith("_v2")


def _real_vector_repository_class():
    """일부 기존 테스트가 sys.modules의 vector_repository를 stub으로 바꿔 끼우므로 원본 파일에서 직접 읽는다."""
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "app" / "repositories" / "vector_repository.py"
    spec = importlib.util.spec_from_file_location("_vector_repository_original", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.VectorRepository


def test_qdrant_filter_carries_must_not_for_every_channel():
    cls = _real_vector_repository_class()
    repo = cls.__new__(cls)
    built = repo._build_filter({"must": {"security_level": ["public"]}, "must_not": {"version_key": ["d:1", "d:2"]}})
    assert built.must[0].key == "security_level"
    assert built.must_not[0].key == "version_key" and built.must_not[0].match.any == ["d:1", "d:2"]
    assert repo._build_filter({"must_not": {"version_key": ["d:1"]}}).must is None
    assert repo._build_filter(None) is None
    flat = repo._build_filter({"document_id": "x"})
    assert flat.must[0].key == "document_id" and flat.must_not is None


@pytest.mark.asyncio
async def test_retired_versions_are_purged_after_retention(tmp_path, monkeypatch):
    env = Env(tmp_path, monkeypatch)
    await env.upload("교육자료.pdf", "1판\n".encode())
    await env.drain()
    await env.upload("교육자료.pdf", "2판\n".encode())
    await env.drain()
    document_id = get_database_manager().execute_query("SELECT document_id FROM tb_documents")[0][0]
    manager = ingest_jobs.IngestJobManager(concurrency=1, name="gc")
    assert manager.purge_expired_versions() == 0  # 보관 기간(7일) 안
    get_database_manager().execute_update("UPDATE tb_document_versions SET retired_at = now() - interval '8 days'")
    assert manager.purge_expired_versions() == 1
    assert versions_of(document_id) == {2: "active"}
    assert {p.payload["version"] for p in env.vector_repo.points[COLLECTION]} == {2}
    assert IngestRecordRepository().inactive_version_keys() == []

    # 보관 0일: 전환 즉시 이전 버전 point·행 삭제
    env.settings.version_retain_days = 0
    await env.upload("교육자료.pdf", "3판\n".encode())
    await env.drain()
    assert versions_of(document_id) == {3: "active"}
    assert {p.payload["version"] for p in env.vector_repo.points[COLLECTION]} == {3}


# ── 업로드 보호·큐 ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_upload_limits_idempotency_and_explicit_target(tmp_path, monkeypatch):
    env = Env(tmp_path, monkeypatch)
    monkeypatch.setattr(ingest, "get_settings", lambda: upload_settings(
        tmp_path, ingest_max_upload_mb=1, ingest_rate_limit_per_minute=3, ingest_max_active_jobs_per_user=2,
    ))
    async with env.client("user1") as client:
        too_big = await client.post("/api/ingest/upload", files={"file": ("big.pdf", b"x" * (1024 * 1024 + 1))})
        assert too_big.status_code == 413
        assert list((tmp_path / "instance" / "ingest_jobs").iterdir()) == []

        first = await client.post("/api/ingest/upload", files={"file": ("a.pdf", b"a\n")},
                                  headers={"Idempotency-Key": "k-1"})
        replay = await client.post("/api/ingest/upload", files={"file": ("a.pdf", b"a\n")},
                                   headers={"Idempotency-Key": "k-1"})
        assert first.status_code == replay.status_code == 202
        assert replay.json()["job_id"] == first.json()["job_id"]
        second = await client.post("/api/ingest/upload", files={"file": ("b.pdf", b"b\n")})
        assert second.status_code == 202
        busy = await client.post("/api/ingest/upload", files={"file": ("c.pdf", b"c\n")})
        assert busy.status_code == 429 and "처리 중" in busy.json()["detail"]

    await env.drain()
    async with env.client("user1") as client:
        limited = await client.post("/api/ingest/upload", files={"file": ("d.pdf", b"d\n")})
        assert limited.status_code == 202  # 3번째(분당 3건)
        rate = await client.post("/api/ingest/upload", files={"file": ("e.pdf", b"e\n")})
        assert rate.status_code == 429 and "분당" in rate.json()["detail"]
    await env.drain()

    # 파일명이 달라도 document_id를 지정하면 그 문서의 새 버전
    monkeypatch.setattr(ingest, "get_settings", lambda: upload_settings(tmp_path))
    target = get_database_manager().execute_query(
        "SELECT document_id FROM tb_documents WHERE original_filename='a.pdf'"
    )[0][0]
    await env.upload("완전히_다른_이름.pdf", b"a v2\n", user_id="user2", document_id=target)
    await env.drain()
    assert versions_of(target) == {1: "retired", 2: "active"}


def _create_jobs(repo, specs, **fields):
    collection_id = get_database_manager().execute_query("SELECT collection_id FROM tb_collections")[0][0]
    for job_id, key in specs:
        repo.create(job_id, {"filename": f"{key}.pdf", "file_path": "x", "collection_name": COLLECTION}, "u",
                    collection_id=collection_id, doc_key=key, **fields)
        time.sleep(0.01)


def test_claim_serializes_same_document_and_reclaims_exhausted_jobs():
    seed_upload_db("u")
    repo = IngestJobRepository()
    _create_jobs(repo, (("j1", "doc-a"), ("j2", "doc-a"), ("j3", "doc-b")), max_attempts=1)
    first = repo.claim("w1", lease_seconds=60)
    second = repo.claim("w2", lease_seconds=60)
    assert (first["job_id"], second["job_id"]) == ("j1", "j3")  # j2는 같은 문서 j1이 끝날 때까지 대기
    assert first["locked_until"] is not None and first["queue_cd"] == "INGEST"
    assert repo.claim("w3") is None
    repo.complete("j1", {"ok": True})
    assert repo.claim("w3")["job_id"] == "j2"

    # 임대 안이면 회수하지 않고, 하트비트가 임대를 연장한다
    assert repo.reclaim_expired() == ([], [])
    get_database_manager().execute_update("UPDATE tb_ingest_jobs SET locked_until = now() - interval '1 second'")
    assert repo.heartbeat("j3", "w2", 60) is True
    assert repo.heartbeat("j3", "someone-else", 60) is False
    requeued, exhausted = repo.reclaim_expired()
    assert requeued == [] and {j["job_id"] for j in exhausted} == {"j2"}  # max_attempts=1, j3은 방금 연장


def test_claim_order_priority_and_queue_separation():
    seed_upload_db("u")
    repo = IngestJobRepository()
    _create_jobs(repo, (("low", "doc-low"),))
    _create_jobs(repo, (("high", "doc-high"),), priority=5)
    repo.create("vlm", {}, "u", queue="VLM", job_type="VLM_IMAGES", payload={"doc": "x"}, priority=-10)
    assert repo.claim("w", "INGEST")["job_id"] == "high"  # 늦게 들어왔어도 우선순위 먼저
    assert repo.claim("w", "INGEST")["job_id"] == "low"
    assert repo.claim("w", "INGEST") is None  # VLM 작업은 INGEST 워커가 가져가지 않는다
    vlm = repo.claim("w", "VLM")
    assert (vlm["job_id"], vlm["job_type"], vlm["payload"]) == ("vlm", "VLM_IMAGES", {"doc": "x"})


def test_three_workers_claiming_concurrently_never_take_the_same_job():
    """작업지시서 v2.3: 워커 3개 동시 꺼내기에서 같은 작업 중복 처리 0건 (각자 다른 DB 커넥션)."""
    seed_upload_db("u")
    repo = IngestJobRepository()
    _create_jobs(repo, [(f"job{i:02d}", f"doc-{i}") for i in range(30)])
    start = threading.Barrier(3)
    taken: dict[str, list[str]] = {}

    def worker(name: str) -> None:
        start.wait()
        mine = taken.setdefault(name, [])
        while (job := IngestJobRepository().claim(name, lease_seconds=60)) is not None:
            mine.append(job["job_id"])

    threads = [threading.Thread(target=worker, args=(f"w{i}",)) for i in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
    claimed = [job_id for jobs in taken.values() for job_id in jobs]
    assert len(claimed) == len(set(claimed)) == 30
    rows = get_database_manager().execute_query("SELECT locked_by, count(*) FROM tb_ingest_jobs GROUP BY locked_by")
    assert {row[0]: int(row[1]) for row in rows} == {name: len(jobs) for name, jobs in taken.items() if jobs}


@pytest.mark.asyncio
async def test_three_worker_managers_process_each_job_exactly_once(tmp_path, monkeypatch):
    env = Env(tmp_path, monkeypatch)
    executed: list[str] = []
    original = ingest_jobs.IngestJobManager.run_job

    async def recording_run_job(self, job, worker_id):
        executed.append(job["job_id"])
        await asyncio.sleep(0.05)  # 꺼내기 경쟁이 겹치도록 처리 시간을 둔다
        return await original(self, job, worker_id)

    monkeypatch.setattr(ingest_jobs.IngestJobManager, "run_job", recording_run_job)
    uploaded = await asyncio.gather(*(env.upload(f"점검표_{chr(65 + i)}.pdf", f"점검 {i}\n".encode()) for i in range(12)))
    await env.drain(concurrency=1, managers=3)
    assert sorted(executed) == sorted(job["job_id"] for job in uploaded)  # 중복 0, 누락 0
    assert jobs_by_status() == {"completed": 12}


_KILLED_WORKER = """
import sys, time
from app.repositories.ingest_job_repository import IngestJobRepository
job = IngestJobRepository().claim("killed-worker:0", "INGEST", float(sys.argv[1]))
print(job["job_id"] if job else "", flush=True)
time.sleep(600)
"""


@pytest.mark.asyncio
async def test_killed_worker_process_lease_expires_and_another_worker_reclaims(tmp_path, monkeypatch):
    """작업지시서 v2.3: 처리 중 워커 프로세스 강제 종료 → 임대 만료 후 다른 워커가 회수해 정상 완료."""
    env = Env(tmp_path, monkeypatch)
    job = await env.upload("설비점검_프로세스.pdf", "점검 1\n점검 2\n".encode())
    backend_root = Path(__file__).resolve().parents[1]
    process = subprocess.Popen(
        [sys.executable, "-c", _KILLED_WORKER, "2"], cwd=backend_root, stdout=subprocess.PIPE, text=True,
        env={**os.environ, "PYTHONPATH": str(backend_root)},
    )
    try:
        claimed_id = await asyncio.to_thread(process.stdout.readline)
        assert claimed_id.strip() == job["job_id"]
    finally:
        process.kill()  # 처리 중 강제 종료 — 하트비트도 상태 기록도 없이 사라진다
        process.wait(10)
    stuck = IngestJobRepository().get(job["job_id"])
    assert (stuck["status"], stuck["locked_by"]) == ("running", "killed-worker:0")

    # 다른 워커: 회수 주기를 짧게. 임대(2초)가 지나기 전에는 회수하지 않는다
    monkeypatch.setattr(ingest_jobs, "_RECLAIM_INTERVAL_SECONDS", 0.2)
    other = ingest_jobs.IngestJobManager(concurrency=1, name="worker-b", queues=("INGEST",))
    await other.start()
    try:
        await asyncio.sleep(0.5)
        assert IngestJobRepository().get(job["job_id"])["locked_by"] == "killed-worker:0"
        await wait_ingest_idle(30)
    finally:
        await other.stop()
    done = IngestJobRepository().get(job["job_id"])
    assert (done["status"], done["attempts"], done["locked_by"]) == ("completed", 2, None)
    assert versions_of(done["document_id"]) == {1: "active"}
    assert len(env.vector_repo.points[COLLECTION]) == 2


@pytest.mark.asyncio
async def test_listen_notify_wakes_worker_before_poll_interval(tmp_path, monkeypatch):
    env = Env(tmp_path, monkeypatch, job_poll_s=30)  # 주기 조회로는 30초 — 알림으로만 빨리 깨어난다
    manager = ingest_jobs.IngestJobManager(concurrency=1, name="listener", queues=("INGEST",))
    await manager.start()
    try:
        assert await asyncio.to_thread(manager.listening.wait, 10)
        await asyncio.sleep(0.2)  # 첫 조회 후 대기 상태로 들어가도록
        started = time.monotonic()
        job = await env.upload("알림시험.pdf", "알림 1\n".encode())  # 업로드 API는 같은 프로세스 깨우기를 하지 않음(가짜)
        await wait_ingest_idle(20)
        elapsed = time.monotonic() - started
    finally:
        await manager.stop()
    assert IngestJobRepository().get(job["job_id"])["status"] == "completed"
    assert elapsed < 10


@pytest.mark.asyncio
async def test_failed_job_retries_with_exponential_backoff(tmp_path, monkeypatch):
    env = Env(tmp_path, monkeypatch, job_retry_base_s=10)

    def broken(*args, **kwargs):
        raise RuntimeError("임베딩 서버 일시 장애")

    env.service._parse_and_chunk = broken
    job = await env.upload("장애시험.pdf", "내용\n".encode())
    db = get_database_manager()
    delay_sql = "SELECT extract(epoch FROM next_run_at - updated_at) FROM tb_ingest_jobs WHERE job_id=?"
    delays = []
    for _ in range(2):
        await env.drain()
        current = IngestJobRepository().get(job["job_id"])
        assert current["status"] == "queued" and current["locked_until"] is None
        delays.append(round(float(db.execute_query(delay_sql, (job["job_id"],))[0][0])))
        db.execute_update("UPDATE tb_ingest_jobs SET next_run_at = now() WHERE job_id=?", (job["job_id"],))
    await env.drain()
    assert delays == [10, 20]  # JOB_RETRY_BASE_S × 2^재시도횟수
    failed = IngestJobRepository().get(job["job_id"])
    assert (failed["status"], failed["attempts"]) == ("failed", 3)


@pytest.mark.asyncio
async def test_maintenance_jobs_are_scheduled_once_and_rescheduled_after_run(tmp_path, monkeypatch):
    env = Env(tmp_path, monkeypatch)
    manager = ingest_jobs.IngestJobManager(concurrency=1, name="maint", queues=("MAINT",))
    assert sorted(manager.ensure_maintenance_scheduled()) == ["GC_FILES", "PURGE_POINTS"]
    assert manager.ensure_maintenance_scheduled() == []  # 종류별 대기 1건
    db = get_database_manager()
    rows = db.execute_query(
        "SELECT job_type, next_run_at FROM tb_ingest_jobs WHERE queue_cd='MAINT' AND status='queued'"
    )
    scheduled = {row[0]: datetime.fromisoformat(str(row[1])) for row in rows}
    for job_type, at in scheduled.items():
        local = at.astimezone(maintenance.KST)
        assert (local.hour, local.minute) == (maintenance.MAINT_SCHEDULE[job_type].hour,
                                              maintenance.MAINT_SCHEDULE[job_type].minute)
        assert timedelta(0) < local - datetime.now(maintenance.KST) <= timedelta(days=1)

    # 보관 기간이 지난 retired 버전 1건 → PURGE_POINTS를 지금 실행
    await env.upload("교육자료.pdf", "1판\n".encode())
    await env.drain()
    await env.upload("교육자료.pdf", "2판\n".encode())
    await env.drain()
    db.execute_update("UPDATE tb_document_versions SET retired_at = now() - interval '8 days' WHERE status='retired'")
    db.execute_update("UPDATE tb_ingest_jobs SET next_run_at = now() WHERE job_type='PURGE_POINTS'")
    await manager.start()
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            done = db.execute_query(
                "SELECT result_json FROM tb_ingest_jobs WHERE job_type='PURGE_POINTS' AND status='completed'"
            )
            if done:
                break
            await asyncio.sleep(0.05)
    finally:
        await manager.stop()
    assert done and '"purged_versions": 1' in str(done[0][0])
    assert {p.payload["version"] for p in env.vector_repo.points[COLLECTION]} == {2}
    # 끝나면 다음 날 같은 시각으로 다시 예약, GC_FILES는 시각 전이라 실행되지 않음
    pending = db.execute_query(
        "SELECT job_type, next_run_at FROM tb_ingest_jobs WHERE queue_cd='MAINT' AND status='queued'"
    )
    assert sorted(row[0] for row in pending) == ["GC_FILES", "PURGE_POINTS"]
    assert maintenance.next_run_at("PURGE_POINTS") - datetime.now(maintenance.KST) > timedelta(0)


def test_doc_key_normalization_and_version_key():
    assert normalize_doc_key("산업안전보건법 시행령(대통령령)(제34603호)(20260626).pdf") == \
        normalize_doc_key("산업안전보건법 시행령(대통령령)(제35000호)(20261001).pdf")
    assert normalize_doc_key("작업표준_v2.xlsx") == normalize_doc_key("작업표준 v1.3 (최종).xlsx") == "작업표준"
    assert normalize_doc_key("2026 사업계획.pptx") == "2026_사업계획"
    assert normalize_doc_key("v2.pdf") == "v2"
    assert version_key("doc", 3) == "doc:3"

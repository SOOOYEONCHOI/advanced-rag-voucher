"""UI-12 최신본 변경·버전 이력 (2026.10.19, SC-06, D-01·D-18, 요청서 4절·9.2 5단계).

- 접수: POST /ingest/documents/{id}/versions → building 버전 + 작업. 처리 중 1개(409), 같은 파일(409),
  볼 수 없거나 본인 문서가 아니면 404, 처리 중 삭제 409.
- 처리: 기존 document_id·모델명 유지, 성공 시에만 한 트랜잭션으로 최신본 전환(문서 행·버전·청크), 이전 버전 포인트 정리.
- 실패: 새 버전 포인트·리소스만 정리, failed, 기존 최신본·문서 행·포인트 그대로. 재시도는 같은 버전을 다시 연다.
- 검색: 활성 버전이 아닌 포인트를 모든 검색에서 제외(in-memory Qdrant로 실제 필터 동작 확인).
외부 서버(임베딩·Qdrant·docling)만 가짜, DB는 PostgreSQL 테스트 DB.
"""
import asyncio
import threading
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, FieldCondition, Filter, MatchValue, PointStruct, VectorParams

from app.parsers.models import LCDocument
from app.repositories.database import get_database_manager
from app.routes import ingest
from app.services import ingest_jobs, ingest_pipeline, version_visibility
from app.services.ingest_pipeline import IngestPipeline
from app.utils.security import get_current_principal


# ── 가짜 외부 서버 ──────────────────────────────────────────────────────────

def _fake_vectors():
    from excel_ingest_fakes import FakeVectorRepository

    class VersionedFakeVectors(FakeVectorRepository):
        def delete_document_version_points(self, document_id, collection_name, *, version_no=None, keep_version_no=None):
            def drop(p):
                if p.payload.get("document_id") != document_id:
                    return False
                v = p.payload.get("version_no")
                return v == version_no if version_no is not None else v != keep_version_no
            self.points[collection_name] = [p for p in self.points.get(collection_name, []) if not drop(p)]
            return True

        def count_document_version_points(self, document_id, version_no, collection_name):
            return sum(1 for p in self.points.get(collection_name, [])
                       if p.payload.get("document_id") == document_id and p.payload.get("version_no") == version_no)

    return VersionedFakeVectors()


def _parse_result(pages, n, prefix):
    return {
        "chunks": [LCDocument(f"{prefix} 본문 {i}", {"section_title": f"절 {i}"}) for i in range(n)],
        "doc_type": "general", "requested_doc_type": "auto", "doc_type_source": "auto_detected",
        "detection_details": None, "is_law": False, "is_manual": False, "total_pages": pages, "chunk_count": n,
    }


@pytest.fixture
def env(tmp_path, monkeypatch):
    from excel_ingest_fakes import make_ingest_service

    monkeypatch.setattr(ingest_pipeline, "get_settings", lambda: SimpleNamespace(
        excel_parse_mode="docling", md_save_dir="", excel_md_keep_last=5, excel_xls_convert_timeout=120,
        resource_delivery="pull", max_chunk_size=800,
    ))
    service = make_ingest_service(tmp_path / "xl_res", tmp_path / "chunk", vector_repo=_fake_vectors())
    service._parse_and_chunk = lambda *a, **k: _parse_result(2, 3, "v1")
    db = get_database_manager()
    for user_id in ("owner", "other"):
        db.execute_update("INSERT INTO tb_users (user_id, user_pwd, role) VALUES (?, 'x', 'user')", (user_id,))

    queued = []

    async def enqueue(job_id):
        queued.append(job_id)

    principal = dict(user_id="owner", is_admin=False)
    permissions = {"owner": ["documents"], "other": ["documents"]}
    monkeypatch.setattr(ingest, "get_settings", lambda: SimpleNamespace(
        uploaded_files_base_dir=str(tmp_path / "instance" / "data"), excel_parse_mode="docling",
        document_version_replace_enabled=True,
    ))
    monkeypatch.setattr(ingest, "MetadataRepository", lambda *_: SimpleNamespace(
        get_user_permissions=lambda uid: SimpleNamespace(
            accessible_collections=permissions.get(uid, []), max_security_level="public")
    ))
    monkeypatch.setattr(ingest, "get_ingest_job_manager", lambda: SimpleNamespace(enqueue=enqueue))
    # 목록 조회는 list_documents만 쓰므로 초기화(임베딩 등) 없이 실제 저장소만 붙인다(전체 실행 순서 의존 회피)
    real_service = ingest.IngestService

    def _list_service():
        svc = object.__new__(real_service)
        svc.db, svc.doc_repo = db, ingest.DocumentRepository()
        svc.collection_repo = real_service.list_documents.__globals__["CollectionRepository"]()
        return svc

    monkeypatch.setattr(ingest, "IngestService", _list_service)
    app = FastAPI()
    app.include_router(ingest.router, prefix="/api")
    app.dependency_overrides[get_current_principal] = lambda: principal
    with TestClient(app) as client:
        yield SimpleNamespace(service=service, db=db, client=client, queued=queued, principal=principal,
                              permissions=permissions, tmp=tmp_path)


async def _create_v1(env, filename="C2.assembly.rev1.pdf"):
    pdf = env.tmp / filename
    pdf.write_bytes(b"%PDF-1.7 v1")
    result = await IngestPipeline().run(env.service, {
        "file_path": str(pdf), "filename": filename, "collection_name": "documents",
        "parser_type": "docling", "document_type": "auto", "job_id": None,
        "uploaded_by": "owner", "product_model": "NEOCON C2 제조 관리 문서 대장",
    })
    return result["document_id"]


def _replace(env, document_id, name="C2.assembly.rev2.pdf", content=b"%PDF-1.7 v2"):
    return env.client.post(f"/api/ingest/documents/{document_id}/versions",
                           files={"file": (name, content, "application/pdf")})


async def _run_job(env, job_id):
    job = ingest.IngestJobRepository().get(job_id)
    return await IngestPipeline().run(env.service, {**job["request"], "job_id": job_id})


def _doc(env, document_id):
    return dict(env.db.execute_query(
        "SELECT document_id, original_filename, total_pages, chunk_count, version_no, product_model, source_path "
        "FROM tb_documents WHERE document_id = ?", (document_id,))[0])


def _versions(env, document_id):
    return [(r[0], r[1]) for r in env.db.execute_query(
        "SELECT version_no, status FROM tb_document_versions WHERE document_id = ? ORDER BY version_no", (document_id,))]


def _point_versions(env, document_id):
    return sorted({p.payload["version_no"] for p in env.service.vector_repo.points["documents"]
                   if p.payload["document_id"] == document_id})


# ── 성공 경로 ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_replace_keeps_id_and_model_and_switches_only_after_success(env):
    document_id = await _create_v1(env)
    response = _replace(env, document_id)
    assert response.status_code == 202, response.text
    body = response.json()
    assert (body["document_id"], body["version_no"]) == (document_id, 2) and env.queued == [body["job_id"]]

    # 처리 전: 기존 최신본 그대로 + 목록에 처리 중 표시 + 검색 제외 대상(v2 숨김)
    assert _versions(env, document_id) == [(1, "active"), (2, "building")]
    assert _doc(env, document_id)["version_no"] == 1
    listed = env.client.get("/api/ingest/documents").json()["documents"][0]
    assert (listed["version_no"], listed["pending_version_no"], listed["pending_job_id"]) == (1, 2, body["job_id"])
    assert version_visibility.documents_with_hidden_versions() == [(document_id, 1)]
    # 처리 중에는 두 번째 교체·삭제 불가
    assert _replace(env, document_id, "other.pdf", b"%PDF other").status_code == 409
    assert env.client.delete(f"/api/ingest/documents/{document_id}").status_code == 409

    env.service._parse_and_chunk = lambda *a, **k: _parse_result(5, 4, "v2")
    result = await _run_job(env, body["job_id"])
    assert (result["document_id"], result["version_no"]) == (document_id, 2)

    doc = _doc(env, document_id)
    assert (doc["original_filename"], doc["total_pages"], doc["chunk_count"], doc["version_no"]) == (
        "C2.assembly.rev2.pdf", 5, 4, 2)
    assert doc["product_model"] == "NEOCON C2 제조 관리 문서 대장"          # 모델명 유지
    assert doc["source_path"].endswith("_v2")                               # 이전 버전 원본 보존(버전별 파일명)
    assert _versions(env, document_id) == [(1, "retired"), (2, "active")]
    assert _point_versions(env, document_id) == [2]                         # 이전 버전 포인트 정리
    assert version_visibility.documents_with_hidden_versions() == []        # 정리 완료 → 제외 조건 없음
    chunks = env.db.execute_query(
        "SELECT version_no, count(*) FROM tb_chunks WHERE document_id = ? GROUP BY 1 ORDER BY 1", (document_id,))
    assert [tuple(r) for r in chunks] == [(1, 3), (2, 4)]                   # 버전별 청크 이력 보존

    history = env.client.get(f"/api/ingest/documents/{document_id}/versions").json()
    assert history["current_version_no"] == 2 and history["restore_supported"] is False
    assert [(v["version_no"], v["status"], v["is_active"], v["original_filename"]) for v in history["versions"]] == [
        (2, "active", True, "C2.assembly.rev2.pdf"), (1, "retired", False, "C2.assembly.rev1.pdf")]
    v2 = history["versions"][0]
    assert v2["uploaded_by"] == "owner" and v2["chunk_count"] == 4 and v2["activated_at"]
    listed = env.client.get("/api/ingest/documents").json()["documents"][0]
    assert (listed["filename"], listed["total_pages"], listed["version_no"], listed["pending_version_no"]) == (
        "C2.assembly.rev2.pdf", 5, 2, None)


# ── 접수 거부 ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_replace_rejects_duplicate_hidden_and_others_documents(env):
    document_id = await _create_v1(env)
    duplicate = _replace(env, document_id, "same.pdf", b"%PDF-1.7 v1")
    assert duplicate.status_code == 409 and "DUPLICATE_FILE" in duplicate.json()["detail"]
    assert _replace(env, "nope").status_code == 404
    env.principal.update(user_id="other")                       # 볼 수 있지만 본인 문서 아님 → 404(D-01)
    assert _replace(env, document_id).status_code == 404
    assert env.client.get(f"/api/ingest/documents/{document_id}/versions").status_code == 200
    env.permissions["other"] = []                               # 볼 수 없는 대화 주제 → 이력도 404
    assert env.client.get(f"/api/ingest/documents/{document_id}/versions").status_code == 404
    env.principal.update(user_id="admin", is_admin=True)        # 관리자는 모든 문서
    assert _replace(env, document_id).status_code == 202
    assert _versions(env, document_id) == [(1, "active"), (2, "building")]


def test_concurrent_replacements_accept_only_one(env):
    document_id = asyncio.run(_create_v1(env))
    results = []

    def submit(i):
        request = dict(file_path=f"x{i}", filename=f"v{i}.pdf", collection_name="documents", parser_type="docling",
                       document_type="auto", chunk_size=None, uploaded_by="owner", security_level="public",
                       product_model="m", target_document_id=document_id, file_sha256=f"sha{i}", file_size=1)
        try:
            results.append(ingest._register_version_job(document_id, f"job-c{i}", request, "owner"))
        except ingest._VersionConflict as exc:
            results.append(str(exc))

    threads = [threading.Thread(target=submit, args=(i,)) for i in range(5)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results.count(2) == 1 and sum("JOB_IN_PROGRESS" in str(r) for r in results) == 4
    assert _versions(env, document_id) == [(1, "active"), (2, "building")]


# ── 실패 경로 ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_failed_parse_keeps_current_version_and_can_retry(env, monkeypatch):
    document_id = await _create_v1(env)
    before = _doc(env, document_id)
    job_id = _replace(env, document_id).json()["job_id"]

    def broken(*a, **k):
        raise RuntimeError("파싱 서버 오류")

    env.service._parse_and_chunk = broken
    with pytest.raises(RuntimeError):
        await _run_job(env, job_id)
    assert _versions(env, document_id) == [(1, "active"), (2, "failed")]
    assert _doc(env, document_id) == before                                 # 문서 행·표시 정보 그대로
    assert env.db.execute_query("SELECT source_path FROM tb_document_versions WHERE document_id = ? AND version_no = 2",
                                (document_id,))[0][0].endswith("_v2")       # 실패 버전 원본도 기록(삭제 시 정리)
    assert _point_versions(env, document_id) == [1]                         # 기존 검색본 그대로
    assert version_visibility.documents_with_hidden_versions() == []        # 지울 포인트 없음(정리 완료)
    assert ingest._pending_versions([document_id]) == {}                    # 처리 중 아님 → 삭제 가능

    # 같은 작업 재시도: 실패 버전을 다시 building으로(다른 교체가 처리 중이면 거부)
    monkeypatch.setattr(ingest_jobs, "IngestJobRepository", lambda: SimpleNamespace(
        get=lambda jid: {"status": "failed", "current_step": "chunk", "request": {
            "target_document_id": document_id, "version_no": 2}},
        update=lambda *a, **k: None,
    ))
    manager = ingest_jobs.IngestJobManager()
    await manager.retry(job_id)
    assert _versions(env, document_id)[-1] == (2, "building")


@pytest.mark.asyncio
async def test_failure_after_vector_store_removes_only_new_points(env):
    document_id = await _create_v1(env)
    job_id = _replace(env, document_id).json()["job_id"]
    env.service._parse_and_chunk = lambda *a, **k: _parse_result(5, 4, "v2")
    original = env.service.record_repo.insert_chunks

    def fail_insert(rows):
        raise RuntimeError("DB 저장 실패")

    env.service.record_repo.insert_chunks = fail_insert                      # 전환 트랜잭션 중 실패 → 롤백
    with pytest.raises(RuntimeError):
        await _run_job(env, job_id)
    env.service.record_repo.insert_chunks = original
    assert _versions(env, document_id) == [(1, "active"), (2, "failed")]
    assert _doc(env, document_id)["version_no"] == 1 and _doc(env, document_id)["original_filename"] == "C2.assembly.rev1.pdf"
    assert _point_versions(env, document_id) == [1]
    assert [r[0] for r in env.db.execute_query(
        "SELECT DISTINCT version_no FROM tb_chunks WHERE document_id = ?", (document_id,))] == [1]


# ── 검색 제외 필터(실제 Qdrant 필터 동작) ─────────────────────────────────────

def test_visibility_filter_hides_non_active_versions_in_qdrant(env):
    db = env.db
    db.execute_update("INSERT INTO tb_collections (display_name, qdrant_name) VALUES ('c', 'c') ON CONFLICT DO NOTHING")
    for doc_id, version in (("doc-a", 1), ("doc-b", 2), ("doc-c", 1)):
        db.execute_update(
            "INSERT INTO tb_documents (document_id, collection_id, source_path, version_no) "
            "VALUES (?, (SELECT collection_id FROM tb_collections WHERE qdrant_name = 'c'), 'p', ?)", (doc_id, version))
    # doc-a: v2 처리 중(building) / doc-b: v2 활성, v1 정리 전(retired) / doc-c: 개정 없음
    db.execute_update("INSERT INTO tb_document_versions (document_id, version_no, status, source_path) VALUES "
                      "('doc-a', 1, 'active', 'p'), ('doc-a', 2, 'building', ''), "
                      "('doc-b', 1, 'retired', 'p'), ('doc-b', 2, 'active', 'p'), ('doc-c', 1, 'active', 'p')")
    client = QdrantClient(":memory:")
    client.create_collection("t", vectors_config=VectorParams(size=2, distance=Distance.COSINE))
    points = [("doc-a", 1), ("doc-a", 2), ("doc-b", 1), ("doc-b", 2), ("doc-c", 1), ("doc-c", None)]
    client.upsert("t", [
        PointStruct(id=i, vector=[1.0, 0.5], payload={"document_id": d, **({"version_no": v} if v else {})})
        for i, (d, v) in enumerate(points)
    ])

    def visible(base=None):
        hits = client.query_points("t", query=[1.0, 0.5], limit=20,
                                   query_filter=version_visibility.with_version_exclusion(base)).points
        return sorted((h.payload["document_id"], h.payload.get("version_no", 0)) for h in hits)

    assert visible() == [("doc-a", 1), ("doc-b", 2), ("doc-c", 0), ("doc-c", 1)]   # 0 = payload에 버전 없음(Phase 2 이전)
    # 기존 권한 필터(must)와 함께 써도 유지
    base = Filter(must=[FieldCondition(key="document_id", match=MatchValue(value="doc-b"))])
    assert visible(base) == [("doc-b", 2)]
    # doc-a 전환 완료 + doc-b 정리 완료 → doc-a는 v2만, doc-b 조건 해제
    db.execute_update("UPDATE tb_document_versions SET status = 'retired' WHERE document_id = 'doc-a' AND version_no = 1")
    db.execute_update("UPDATE tb_document_versions SET status = 'active' WHERE document_id = 'doc-a' AND version_no = 2")
    db.execute_update("UPDATE tb_documents SET version_no = 2 WHERE document_id = 'doc-a'")
    db.execute_update("UPDATE tb_document_versions SET vectors_purged_at = now() WHERE document_id = 'doc-b' AND version_no = 1")
    # 2026.11.06(sooyeon.choi) 수정 - 삭제 시각만으로는 필터를 풀지 않는다(보존·백업 복구 포인트 대비, 설계 v1.1 B-07)
    assert visible() == [("doc-a", 2), ("doc-b", 2), ("doc-c", 0), ("doc-c", 1)]
    db.execute_update("UPDATE tb_document_versions SET vector_storage_state = 'missing' "
                      "WHERE document_id = 'doc-b' AND version_no = 1")
    assert visible() == [("doc-a", 2), ("doc-b", 1), ("doc-b", 2), ("doc-c", 0), ("doc-c", 1)]
    assert version_visibility.documents_with_hidden_versions() == [("doc-a", 2)]

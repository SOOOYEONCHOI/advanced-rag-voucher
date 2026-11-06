"""UI-12 이전 버전 복원 (2026.11.06(sooyeon.choi) 수정 - 신규, R1-5 / SC-06 / VR-01~06 / D-22).

설계: docs/design/문서_이전버전_복원_백엔드_최종설계_v1.1.md, 명세: 문서_이전버전_복원_화면영역별_API_명세_v1.1.md
- 보존 ON: 최신본 변경 후 이전 버전 포인트가 남고(검색에서는 제외), 봉인(프로필·명세·snapshot)과 적용 이력이 기록된다.
- 복원: 이력 판정 → 접수(멱등 키·점유) → 실행(validate·snapshot·activate) → 문서 행·버전 전환, 재임베딩 없음.
- 거부·실패: 볼 수 없는 문서(404)·실행 전 권한 상실·기능 꺼짐·상태 변경·이미 적용·없는 버전·작업 중·벡터 누락·키 재사용·작업 재시도.
- 2026.11.06(sooyeon.choi) 수정 - 권한 변경(D-22): 문서를 볼 수 있는 모든 사용자가 복원한다. 기본 실행자는 업로더가 아닌 일반 사용자.
- 복원 후 새 업로드는 MAX+1 번호.
외부 서버(임베딩·Qdrant·docling)만 가짜, DB는 PostgreSQL 테스트 DB.
"""
from types import SimpleNamespace

import pytest

from app.routes import ingest
from app.services import document_version_restore, embedding_profile, ingest_jobs, ingest_pipeline, version_visibility
from test_document_versions import _create_v1, _doc, _parse_result, _point_versions, _replace, _run_job, _versions, env  # noqa: F401

KEY = "restore-key-0001"
KEY2 = "restore-key-0002"


@pytest.fixture
def restore_env(env, monkeypatch):
    """env(test_document_versions)에 보존·복원 설정을 켠다. 모든 모듈이 같은 설정 객체를 본다(같은 임베딩 프로필)."""
    cfg = SimpleNamespace(
        sqlite_db_path=str(env.tmp / "instance" / "db" / "unused.db"), excel_parse_mode="docling",
        document_version_replace_enabled=True, md_save_dir="", excel_md_keep_last=5, excel_xls_convert_timeout=120,
        resource_delivery="pull", max_chunk_size=800,
        document_version_vector_retention_enabled=True, document_version_restore_enabled=True,
        embedding_provider="vllm", embedding_model_name="test-embed", embedding_dim=8,
        embedding_instruct_template="q: {query}", embedding_truncate_prompt_tokens=-1,
        sparse_encoder_type="kiwi", kiwi_bm25_vector_name="kiwi_bm25", kiwi_bm25_encoder_version="v1",
    )
    for module in (ingest, ingest_pipeline, embedding_profile, document_version_restore):
        monkeypatch.setattr(module, "get_settings", lambda: cfg)
    # 실행자: 업로더(owner)가 아닌 일반 사용자 other — 같은 대화 주제를 볼 수 있으면 복원 가능
    env.db.execute_update("UPDATE tb_users SET user_name = '작업자' WHERE user_id = 'other'")
    env.principal.update(user_id="other", is_admin=False)
    # 실행 시점 권한 재확인도 env의 가짜 권한 저장소를 쓴다
    monkeypatch.setattr(document_version_restore, "MetadataRepository", ingest.MetadataRepository)
    env.cfg = cfg
    # 작업 재시도 API는 실제 관리자 retry(복원 거부 규칙)를 쓰고, 접수는 env의 가짜 enqueue를 그대로 쓴다
    stub = ingest.get_ingest_job_manager()
    monkeypatch.setattr(ingest, "get_ingest_job_manager", lambda: SimpleNamespace(
        enqueue=stub.enqueue, retry=ingest_jobs.IngestJobManager().retry))
    return env


class _FakeClient:
    def __init__(self, vectors):
        self.vectors = vectors

    def retrieve(self, collection_name, ids, with_payload=None, with_vectors=False):
        wanted = set(map(str, ids))
        return [SimpleNamespace(id=p.id, payload=p.payload)
                for p in self.vectors.points.get(collection_name, []) if str(p.id) in wanted]


async def _run_restore(env, job_id, **overrides):
    env.service.vector_repo.client = _FakeClient(env.service.vector_repo)
    kwargs = dict(vector_repo=env.service.vector_repo, source_exists=lambda path: True, resource_exists=lambda rid: True)
    kwargs.update(overrides)
    await document_version_restore.run_restore_job(job_id, **kwargs)


async def _two_versions(env):
    # 최신본 변경은 업로더(owner)만 가능 → 준비는 owner로, 복원은 fixture의 실행자(other)로
    actor = dict(env.principal)
    env.principal.update(user_id="owner", is_admin=False)
    document_id = await _create_v1(env)
    job_id = _replace(env, document_id).json()["job_id"]
    env.service._parse_and_chunk = lambda *a, **k: _parse_result(5, 4, "v2")
    await _run_job(env, job_id)
    env.principal.update(actor)
    return document_id


def _post_restore(env, document_id, version_no, *, key=KEY, current=2, revision=2):
    return env.client.post(f"/api/ingest/documents/{document_id}/versions/{version_no}/restore", json={
        "expected_current_version_no": current, "expected_activation_revision": revision, "idempotency_key": key})


def _history(env, document_id):
    return env.client.get(f"/api/ingest/documents/{document_id}/versions").json()


@pytest.mark.asyncio
async def test_retention_keeps_old_points_hidden_and_records_seal_and_activations(restore_env):
    env = restore_env
    document_id = await _two_versions(env)
    assert _versions(env, document_id) == [(1, "retired"), (2, "active")]
    assert _point_versions(env, document_id) == [1, 2]                                   # v1 포인트 보존
    # C안: 새 포인트에는 버전별 고정 키 doc_version이 기록된다
    assert {p.payload["doc_version"] for p in env.service.vector_repo.points["documents"]
            if p.payload["document_id"] == document_id} == {f"{document_id}:1", f"{document_id}:2"}
    assert version_visibility.documents_with_hidden_versions() == [(document_id, 2)]      # 검색은 v2만
    sealed = env.db.execute_query(
        "SELECT version_no, vector_storage_state, embedding_profile_id IS NOT NULL, document_snapshot_json->>'doc_type' "
        "FROM tb_document_versions WHERE document_id = ? ORDER BY 1", (document_id,))
    assert [tuple(r) for r in sealed] == [(1, "available", True, "general"), (2, "available", True, "general")]
    acts = env.client.get(f"/api/ingest/documents/{document_id}/activations").json()["activations"]
    assert [(a["operation_type"], a["from_version_no"], a["to_version_no"], a["activation_revision"]) for a in acts] == [
        ("replace", 1, 2, 2), ("upload", None, 1, 1)]
    listed = env.client.get("/api/ingest/documents").json()["documents"][0]
    assert (listed["activation_revision"], listed["pending_operation"]) == (2, None)


@pytest.mark.asyncio
async def test_restore_end_to_end_switches_without_reembedding(restore_env):
    env = restore_env
    document_id = await _two_versions(env)
    history = _history(env, document_id)
    assert (history["restore_supported"], history["can_restore"], history["next_version_no"],
            history["activation_revision"], history["total_versions"]) == (True, True, 3, 2, 2)
    rows = {v["version_no"]: v for v in history["versions"]}
    assert (rows[2]["can_restore"], rows[2]["restore_block_code"]) == (False, "ALREADY_ACTIVE")
    assert (rows[1]["can_restore"], rows[1]["restore_block_code"]) == (True, None)
    points_before = sorted(str(p.id) for p in env.service.vector_repo.points["documents"])

    response = _post_restore(env, document_id, 1)
    assert response.status_code == 202, response.text
    job = response.json()
    assert (job["operation_type"], job["status"], job["from_version_no"], job["target_version_no"]) == (
        "restore", "queued", 2, 1)
    assert env.queued[-1] == job["job_id"]
    # 같은 키·같은 본문 재전송 → 같은 작업(202), 같은 키·다른 본문 → 409
    again = _post_restore(env, document_id, 1)
    assert again.status_code == 202 and again.json()["job_id"] == job["job_id"]
    reused = _post_restore(env, document_id, 1, revision=9)
    assert reused.status_code == 409 and reused.json()["detail"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    # 진행 중: 목록 pending_operation, 최신본 변경·삭제·다른 복원 거부, 기존 최신본 필드는 비어 있음
    listed = env.client.get("/api/ingest/documents").json()["documents"][0]
    assert listed["pending_operation"]["operation_type"] == "restore" and listed["pending_job_id"] is None
    env.principal.update(user_id="owner")                   # 업로더도 진행 중 복원이 있으면 변경·삭제 불가
    assert _replace(env, document_id, "v3.pdf", b"%PDF v3").status_code == 409
    assert env.client.delete(f"/api/ingest/documents/{document_id}").status_code == 409
    env.principal.update(user_id="other")
    busy = _post_restore(env, document_id, 1, key=KEY2)
    assert busy.status_code == 409 and busy.json()["detail"]["code"] == "JOB_IN_PROGRESS"
    assert _history(env, document_id)["restore_block_code"] == "JOB_IN_PROGRESS"

    await _run_restore(env, job["job_id"])
    done = env.client.get(f"/api/ingest/jobs/{job['job_id']}").json()
    assert (done["status"], done["current_step"], done["operation_type"]) == ("completed", "completed", "restore")
    assert (done["result"]["current_version_no"], done["result"]["activation_revision"],
            done["result"]["activated_by_name"]) == (1, 3, "작업자")
    doc = _doc(env, document_id)
    assert (doc["version_no"], doc["original_filename"], doc["total_pages"], doc["chunk_count"]) == (
        1, "C2.assembly.rev1.pdf", 2, 3)
    assert doc["product_model"] == "NEOCON C2 제조 관리 문서 대장"                      # 모델명 유지
    assert _versions(env, document_id) == [(1, "active"), (2, "retired")]
    assert sorted(str(p.id) for p in env.service.vector_repo.points["documents"]) == points_before  # 재임베딩·삭제 없음
    assert version_visibility.documents_with_hidden_versions() == [(document_id, 1)]
    assert env.db.execute_query("SELECT pending_job_id FROM tb_documents WHERE document_id = ?",
                                (document_id,))[0][0] is None
    assert env.db.execute_query("SELECT count(*) FROM tb_document_events WHERE document_id = ? AND event_type = 'restore'",
                                (document_id,))[0][0] == 1
    # 끝난 작업에 같은 키 재전송 → 200 + 같은 작업
    replay = _post_restore(env, document_id, 1)
    assert replay.status_code == 200 and replay.json()["job_id"] == job["job_id"]
    acts = env.client.get(f"/api/ingest/documents/{document_id}/activations", params={"limit": 2}).json()
    assert [a["operation_type"] for a in acts["activations"]] == ["restore", "replace"]
    assert acts["activations"][0]["activated_by_name"] == "작업자" and acts["next_before_activation_id"]
    more = env.client.get(f"/api/ingest/documents/{document_id}/activations",
                          params={"before_activation_id": acts["next_before_activation_id"]}).json()
    assert [a["operation_type"] for a in more["activations"]] == ["upload"]
    # restore 작업은 기존 재시도 API로 다시 실행하지 않는다
    retry = env.client.post(f"/api/ingest/jobs/{job['job_id']}/retry")
    assert retry.status_code == 409 and retry.json()["detail"]["code"] == "RESTORE_RETRY_REQUIRES_NEW_REQUEST"

    # 반복 적용 v1 → v2: 적용 순번 4
    back = _post_restore(env, document_id, 2, key=KEY2, current=1, revision=3)
    assert back.status_code == 202, back.text
    await _run_restore(env, back.json()["job_id"])
    assert _doc(env, document_id)["version_no"] == 2 and _history(env, document_id)["activation_revision"] == 4

    # 복원 후 새 업로드는 MAX+1(v3) — 최신본 변경은 업로더만
    env.principal.update(user_id="owner")
    up = _replace(env, document_id, "C2.assembly.rev3.pdf", b"%PDF-1.7 v3")
    assert up.status_code == 202 and up.json()["version_no"] == 3


@pytest.mark.asyncio
async def test_rejections_by_permission_state_and_version(restore_env):
    env = restore_env
    document_id = await _two_versions(env)
    assert _post_restore(env, document_id, 9).json()["detail"]["code"] == "VERSION_NOT_FOUND"
    assert _post_restore(env, document_id, 2, key="k-active-01").json()["detail"]["code"] == "ALREADY_ACTIVE"
    changed = _post_restore(env, document_id, 1, key="k-state-001", revision=1)
    assert changed.status_code == 409 and changed.json()["detail"]["code"] == "STATE_CHANGED"
    assert _post_restore(env, "nope", 1, key="k-nodoc-01").status_code == 404
    bad = env.client.post(f"/api/ingest/documents/{document_id}/versions/1/restore", json={"idempotency_key": "x"})
    assert bad.status_code == 422

    # 볼 수 있는 일반 사용자(업로더 아님): 복원 가능 행이 열린다
    history = _history(env, document_id)
    assert (history["can_restore"], history["restore_block_code"]) == (True, None)
    assert {v["version_no"]: v["restore_block_code"] for v in history["versions"]} == {2: "ALREADY_ACTIVE", 1: None}
    # 볼 수 없는 사용자(대화 주제 권한 없음): 이력·복원 모두 404(존재 숨김)
    env.permissions["other"] = []
    assert env.client.get(f"/api/ingest/documents/{document_id}/versions").status_code == 404
    assert _post_restore(env, document_id, 1, key="k-hidden-01").status_code == 404
    env.permissions["other"] = ["documents"]

    # 접수 뒤 실행 전에 권한이 빠지면 실행 단계에서 실패(기존 버전 유지, 점유 해제)
    job_id = _post_restore(env, document_id, 1, key="k-revoke-01").json()["job_id"]
    env.permissions["other"] = []
    await _run_restore(env, job_id)
    env.permissions["other"] = ["documents"]
    job = env.client.get(f"/api/ingest/jobs/{job_id}").json()
    assert (job["status"], job["error_code"]) == ("failed", "NOT_FOUND")
    assert _doc(env, document_id)["version_no"] == 2

    # 기능 꺼짐: 신규 접수 403, 이력은 restore_supported=false
    env.cfg.document_version_restore_enabled = False
    assert _history(env, document_id)["restore_supported"] is False
    off = _post_restore(env, document_id, 1, key="k-off-00001")
    assert off.status_code == 403 and off.json()["detail"]["code"] == "FEATURE_DISABLED"


@pytest.mark.asyncio
async def test_failed_verification_keeps_current_version_and_releases_lock(restore_env):
    env = restore_env
    document_id = await _two_versions(env)
    job_id = _post_restore(env, document_id, 1).json()["job_id"]
    # 보관 포인트가 사라진 상황(예: 운영 중 수동 삭제) → VECTOR_MISSING, 기존 v2 유지
    env.service.vector_repo.points["documents"] = [
        p for p in env.service.vector_repo.points["documents"] if p.payload.get("version_no") != 1]
    await _run_restore(env, job_id)
    job = env.client.get(f"/api/ingest/jobs/{job_id}").json()
    assert (job["status"], job["error_code"], job["current_step"]) == ("failed", "VECTOR_MISSING", "snapshot")
    assert _doc(env, document_id)["version_no"] == 2
    assert _versions(env, document_id) == [(1, "retired"), (2, "active")]
    assert env.db.execute_query("SELECT pending_job_id FROM tb_documents WHERE document_id = ?",
                                (document_id,))[0][0] is None
    assert env.client.get(f"/api/ingest/documents/{document_id}/activations").json()["activations"][0][
        "operation_type"] == "replace"                                                      # 실패는 이력에 없음

    # 원본 파일 없음 → SOURCE_MISSING
    job2 = _post_restore(env, document_id, 1, key=KEY2).json()["job_id"]
    await _run_restore(env, job2, source_exists=lambda path: False)
    assert env.client.get(f"/api/ingest/jobs/{job2}").json()["error_code"] == "SOURCE_MISSING"


@pytest.mark.asyncio
async def test_legacy_purged_version_is_blocked_with_specific_reason(restore_env):
    env = restore_env
    env.cfg.document_version_vector_retention_enabled = False          # 기존 동작: 교체 직후 이전 버전 포인트 삭제
    env.cfg.document_version_restore_enabled = False
    document_id = await _two_versions(env)
    assert _point_versions(env, document_id) == [2]
    env.cfg.document_version_vector_retention_enabled = True
    env.cfg.document_version_restore_enabled = True
    row = {v["version_no"]: v for v in _history(env, document_id)["versions"]}[1]
    assert (row["can_restore"], row["restore_block_code"]) == (False, "VECTOR_MISSING")
    # 프로필이 다른 버전은 차원이 같아도 MODEL_UNSUPPORTED
    env.db.execute_update("UPDATE tb_document_versions SET vector_storage_state = 'available' "
                          "WHERE document_id = ? AND version_no = 1", (document_id,))
    env.cfg.embedding_model_name = "other-embed"
    assert {v["version_no"]: v for v in _history(env, document_id)["versions"]}[1]["restore_block_code"] == "MODEL_UNSUPPORTED"


def test_settings_reject_restore_without_retention():
    from app.core import config

    # 다른 테스트가 설정 모듈을 가짜로 바꿔 둔 실행 순서에서는 검사 대상이 없다
    validator = getattr(getattr(config, "Settings", None), "validate_document_version_restore", None)
    if validator is None:
        pytest.skip("app.core.config가 테스트용 가짜 모듈로 대체된 실행 순서")
    with pytest.raises(ValueError):
        validator(SimpleNamespace(document_version_restore_enabled=True, document_version_vector_retention_enabled=False))
    ok = SimpleNamespace(document_version_restore_enabled=True, document_version_vector_retention_enabled=True)
    assert validator(ok) is ok

"""비활성 버전 제외 조건 C안(doc_version match any) (2026.11.06(sooyeon.choi) 수정 - 신규, 설계 v1.1 7.3, UI-12 R1-5).

- 실제 Qdrant 필터 동작(in-memory)으로 nested(기존)와 doc_version 방식의 검색 결과가 같은지 확인한다.
- doc_version은 문서 수와 관계없이 조건 1개, nested는 문서 수만큼.
- 백필 스크립트: dry-run은 쓰지 않고, apply는 옛 포인트(version_no 없음 = v1)까지 채워 미기록 0건.
- 요청 단위 snapshot 안에서는 DB를 한 번만 읽는다.
DB는 PostgreSQL 테스트 DB.
"""
import importlib.util
from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, FieldCondition, Filter, MatchValue, PointStruct, VectorParams

from app.repositories.database import get_database_manager
from app.services import version_visibility as vv

COLLECTION = "vf"


def _load_backfill():
    path = Path(__file__).resolve().parents[1] / "scripts" / "backfill_doc_version_payload.py"
    spec = importlib.util.spec_from_file_location("backfill_doc_version_payload", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seed_db(db):
    db.execute_update("INSERT INTO tb_collections (display_name, qdrant_name) VALUES ('vf', 'vf') ON CONFLICT DO NOTHING")
    # doc-a: v1 retired(보존)·v2 active / doc-b: v1 active·v2 building / doc-c: 개정 없음 / doc-d: v1·v2 retired, v3 active
    for doc_id, version in (("doc-a", 2), ("doc-b", 1), ("doc-c", 1), ("doc-d", 3)):
        db.execute_update(
            "INSERT INTO tb_documents (document_id, collection_id, source_path, version_no) "
            "VALUES (?, (SELECT collection_id FROM tb_collections WHERE qdrant_name = 'vf'), 'p', ?)", (doc_id, version))
    db.execute_update(
        "INSERT INTO tb_document_versions (document_id, version_no, status, source_path) VALUES "
        "('doc-a', 1, 'retired', 'p'), ('doc-a', 2, 'active', 'p'), ('doc-b', 1, 'active', 'p'), "
        "('doc-b', 2, 'building', ''), ('doc-c', 1, 'active', 'p'), ('doc-d', 1, 'retired', 'p'), "
        "('doc-d', 2, 'retired', 'p'), ('doc-d', 3, 'active', 'p')")


def _client(with_doc_version: bool):
    client = QdrantClient(":memory:")
    client.create_collection(COLLECTION, vectors_config=VectorParams(size=2, distance=Distance.COSINE))
    # (문서, payload version_no) — None은 Phase 2 이전 포인트(version_no 없음)
    points = [("doc-a", 1), ("doc-a", 2), ("doc-b", None), ("doc-b", 2), ("doc-c", 1), ("doc-c", None),
              ("doc-d", 1), ("doc-d", 2), ("doc-d", 3)]
    client.upsert(COLLECTION, [
        PointStruct(id=i, vector=[1.0, 0.5], payload={
            "document_id": d,
            **({"version_no": v} if v else {}),
            **({"doc_version": vv.doc_version_key(d, v or 1)} if with_doc_version else {}),
        })
        for i, (d, v) in enumerate(points)
    ])
    return client


def _visible(client, mode, base=None):
    hits = client.query_points(COLLECTION, query=[1.0, 0.5], limit=50,
                               query_filter=vv.with_version_exclusion(base, mode=mode)).points
    return sorted((h.payload["document_id"], h.payload.get("version_no", 0)) for h in hits)


EXPECTED = [("doc-a", 2), ("doc-b", 0), ("doc-c", 0), ("doc-c", 1), ("doc-d", 3)]


def test_doc_version_mode_matches_nested_with_single_condition():
    db = get_database_manager()
    _seed_db(db)
    client = _client(with_doc_version=True)
    assert _visible(client, vv.FILTER_MODE_NESTED) == EXPECTED
    assert _visible(client, vv.FILTER_MODE_DOC_VERSION) == EXPECTED
    base = Filter(must=[FieldCondition(key="document_id", match=MatchValue(value="doc-d"))])  # 기존 권한 필터와 함께
    assert _visible(client, vv.FILTER_MODE_DOC_VERSION, base) == [("doc-d", 3)]
    # 조건 개수: nested는 문서 수(3), doc_version은 1개(비활성 키 4개를 한 조건으로)
    assert len(vv.inactive_version_conditions(mode=vv.FILTER_MODE_NESTED)) == 3
    [condition] = vv.inactive_version_conditions(mode=vv.FILTER_MODE_DOC_VERSION)
    assert sorted(condition.match.any) == ["doc-a:1", "doc-b:2", "doc-d:1", "doc-d:2"]

    # 복원(doc-d를 v1로) — RDB만 바꾸면 두 방식 모두 바로 v1만 보인다(Qdrant 쓰기 없음)
    db.execute_update("UPDATE tb_documents SET version_no = 1 WHERE document_id = 'doc-d'")
    restored = [("doc-a", 2), ("doc-b", 0), ("doc-c", 0), ("doc-c", 1), ("doc-d", 1)]
    assert _visible(client, vv.FILTER_MODE_NESTED) == restored
    assert _visible(client, vv.FILTER_MODE_DOC_VERSION) == restored
    # 삭제가 확정된(missing) 버전은 키 목록에서 빠진다
    db.execute_update("UPDATE tb_document_versions SET vectors_purged_at = now(), vector_storage_state = 'missing' "
                      "WHERE document_id = 'doc-a' AND version_no = 1")
    assert "doc-a:1" not in vv.inactive_version_keys()


def test_backfill_fills_legacy_points_then_doc_version_mode_is_safe():
    db = get_database_manager()
    _seed_db(db)
    backfill = _load_backfill()
    client = _client(with_doc_version=False)
    # 키가 없는 상태에서 doc_version 방식은 비활성 버전을 거르지 못한다(그래서 백필 전에는 켜지 않는다)
    assert _visible(client, vv.FILTER_MODE_DOC_VERSION) != EXPECTED

    dry = backfill.backfill(client, db, apply=False)
    assert dry[COLLECTION] == {"before": 9, "groups": 8, "after": 9}
    assert backfill.missing_count(client, COLLECTION) == 9                     # dry-run은 쓰지 않음
    applied = backfill.backfill(client, db, apply=True)
    assert applied[COLLECTION]["after"] == 0
    legacy = client.scroll(COLLECTION, scroll_filter=Filter(must=[
        FieldCondition(key="document_id", match=MatchValue(value="doc-c"))]), limit=10)[0]
    assert sorted(p.payload["doc_version"] for p in legacy) == ["doc-c:1", "doc-c:1"]   # version_no 없는 옛 포인트 = v1
    assert _visible(client, vv.FILTER_MODE_DOC_VERSION) == EXPECTED
    assert backfill.backfill(client, db, apply=True)[COLLECTION]["after"] == 0           # 다시 실행해도 안전


def test_snapshot_reads_database_once():
    db = get_database_manager()
    _seed_db(db)
    calls = []

    class CountingDb:
        def execute_query(self, query, params=()):
            calls.append(query)
            return db.execute_query(query, params)

    counting = CountingDb()
    with vv.version_snapshot(counting):
        vv.with_version_exclusion(None, counting, mode=vv.FILTER_MODE_NESTED)
        vv.with_version_exclusion(None, counting, mode=vv.FILTER_MODE_DOC_VERSION)
        vv.documents_with_hidden_versions(counting)
    assert len(calls) == 1

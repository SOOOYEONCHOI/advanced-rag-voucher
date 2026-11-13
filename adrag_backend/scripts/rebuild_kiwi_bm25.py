"""기존 Qdrant 포인트의 Kiwi BM25 벡터를 현재 토큰 정책으로 다시 계산 (2026.11.10(sooyeon.choi) 추가 - 신규).

KIWI_BM25_ENCODER_VERSION을 바꾼 뒤(예: kiwi-bm25-v1 → kiwi-bm25-v2) 실행한다. 문서와 질의가 같은 토큰 정책을
써야 BM25가 맞으므로, 설정만 바꾸고 이 도구를 실행하지 않으면 기존 문서의 BM25 점수가 어긋난다.

- 대상: tb_collections에 등록되어 Qdrant에 있는 컬렉션의 모든 포인트(모든 버전). Dense 벡터는 건드리지 않는다.
- 포인트마다 payload `text`로 `KIWI_BM25_VECTOR_NAME` 벡터를 다시 만들고 `kiwi_text`·`bm25_encoder_version`을 갱신한다.
- 끝까지 실패 없이 갱신되면 tb_document_versions.embedding_profile_id를 현재 프로필로 바꾼다.
  단, 옛 프로필과 현재 프로필이 KIWI_BM25_ENCODER_VERSION 말고는 같을 때만 바꾼다(다른 설정이 바뀐 버전은 그대로 → 복원 차단 유지).
  이렇게 해야 이전 버전 복원(UI-12)이 계속 동작한다.
- 기본은 읽기 전용(dry-run): 컬렉션별 포인트 수·다시 계산할 포인트 수·프로필을 바꿀 버전 수만 보여 준다.
- 이미 현재 버전으로 계산된 포인트는 건너뛰어 여러 번 실행해도 된다(--force면 전부 다시 계산).

사용법 (adrag_backend 폴더에서, .env의 KIWI_BM25_ENCODER_VERSION을 먼저 바꾼 뒤. 운영 반영은 사용자가 직접 실행)
    python scripts/rebuild_kiwi_bm25.py            # 대상 건수 확인
    python scripts/rebuild_kiwi_bm25.py --apply    # 다시 계산 + 프로필 갱신
출력에는 컬렉션 이름·건수만 쓴다(서버 주소 미출력).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_VERSION_KEY = "kiwi_bm25_encoder_version"


def target_collections(client, db) -> list[str]:
    rows = db.execute_query("SELECT DISTINCT qdrant_name FROM tb_collections WHERE qdrant_name IS NOT NULL")
    existing = {c.name for c in client.get_collections().collections}
    return sorted({r[0] for r in rows} & existing)


def _iter_points(client, collection: str, batch: int):
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=collection, limit=batch, offset=offset,
            with_payload=["text", "bm25_encoder_version"], with_vectors=False,
        )
        yield from points
        if offset is None:
            break


def rebuild_collection(client, encoder, vector_name: str, collection: str, *, apply: bool, force: bool,
                       batch: int = 64) -> dict[str, int]:
    """{points, stale, updated, no_text, failed}. apply=False면 updated=0."""
    from qdrant_client.models import PointVectors

    stats = {"points": 0, "stale": 0, "updated": 0, "no_text": 0, "failed": 0}
    pending: list[tuple[Any, str]] = []

    def flush() -> None:
        if not pending:
            return
        try:
            client.update_vectors(
                collection_name=collection,
                points=[PointVectors(id=pid, vector={vector_name: encoder.encode_document(text)}) for pid, text in pending],
                wait=True,
            )
            for pid, text in pending:
                client.set_payload(
                    collection_name=collection,
                    payload={"kiwi_text": encoder.normalize_document(text), "bm25_encoder_version": encoder.version},
                    points=[pid], wait=False,
                )
            stats["updated"] += len(pending)
        except Exception as exc:  # 다른 묶음은 계속 진행하고 실패 수만 보고
            stats["failed"] += len(pending)
            print(f"[{collection}] 묶음 갱신 실패 {len(pending)}건: {type(exc).__name__}", file=sys.stderr)
        pending.clear()

    for point in _iter_points(client, collection, batch):
        stats["points"] += 1
        payload = point.payload or {}
        if not force and payload.get("bm25_encoder_version") == encoder.version:
            continue
        text = (payload.get("text") or "").strip()
        if not text:
            stats["no_text"] += 1
            continue
        stats["stale"] += 1
        if apply:
            pending.append((point.id, text))
            if len(pending) >= batch:
                flush()
    if apply:
        flush()
    return stats


def _definition(value: Any) -> dict[str, Any]:
    return json.loads(value) if isinstance(value, str) else dict(value or {})


def profile_targets(db, collections: list[str], current_id: int, current_def: dict[str, Any]) -> list[tuple[str, int]]:
    """프로필을 현재로 바꿀 (document_id, version_no): 인코더 버전 말고는 현재 프로필과 같은 버전만."""
    if not collections:
        return []
    marks = ", ".join("?" for _ in collections)
    rows = db.execute_query(
        f"""SELECT v.document_id, v.version_no, p.definition_json
            FROM tb_document_versions v
            JOIN tb_documents d ON d.document_id = v.document_id
            JOIN tb_collections c ON c.collection_id = d.collection_id
            JOIN tb_embedding_profiles p ON p.embedding_profile_id = v.embedding_profile_id
            WHERE c.qdrant_name IN ({marks}) AND v.embedding_profile_id <> ?""",
        (*collections, current_id),
    )
    base = {k: v for k, v in current_def.items() if k != _VERSION_KEY}
    result = []
    for document_id, version_no, definition in rows:
        old = {k: v for k, v in _definition(definition).items() if k != _VERSION_KEY}
        if old == base:
            result.append((document_id, int(version_no)))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Kiwi BM25 벡터 다시 계산(기본 읽기 전용)")
    parser.add_argument("--apply", action="store_true", help="다시 계산 + 버전 프로필 갱신")
    parser.add_argument("--force", action="store_true", help="이미 현재 버전인 포인트도 다시 계산")
    args = parser.parse_args()

    from qdrant_client import QdrantClient

    from app.clients.kiwi_bm25_encoder import KiwiBm25Encoder
    from app.core.config import get_settings
    from app.repositories.database import get_database_manager
    from app.services.embedding_profile import current_profile_definition, ensure_current_profile_id, profile_hash

    settings = get_settings()
    db = get_database_manager()
    client = QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)
    encoder = KiwiBm25Encoder(settings)
    print(f"현재 인코더 버전: {encoder.version} (토큰 정책 {encoder.token_policy})")

    collections = target_collections(client, db)
    print("collection\tpoints\tto_rebuild\tupdated\tno_text\tfailed")
    failed = 0
    for collection in collections:
        stats = rebuild_collection(client, encoder, settings.kiwi_bm25_vector_name, collection,
                                   apply=args.apply, force=args.force)
        failed += stats["failed"]
        print(f"{collection}\t{stats['points']}\t{stats['stale']}\t{stats['updated']}\t{stats['no_text']}\t{stats['failed']}")

    current_def = current_profile_definition(settings)
    if args.apply:
        if failed:
            print(f"\n실패 {failed}건이 있어 버전 프로필은 바꾸지 않았습니다. 다시 실행하세요(성공한 포인트는 건너뜀).")
            return 1
        current_id = ensure_current_profile_id(db, settings)
        targets = profile_targets(db, collections, current_id, current_def)
        for document_id, version_no in targets:
            db.execute_update(
                "UPDATE tb_document_versions SET embedding_profile_id = ? WHERE document_id = ? AND version_no = ?",
                (current_id, document_id, version_no),
            )
        print(f"\n[기록함(--apply)] 버전 프로필 갱신: {len(targets)}건")
    else:
        rows = db.execute_query(
            "SELECT embedding_profile_id FROM tb_embedding_profiles WHERE profile_hash = ?",
            (profile_hash(current_def),),
        )
        current_id = int(rows[0][0]) if rows else -1  # 아직 없으면 모든 버전이 후보
        targets = profile_targets(db, collections, current_id, current_def)
        print(f"\n[읽기 전용(dry-run)] 프로필을 바꿀 버전: {len(targets)}건. --apply로 실행하세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

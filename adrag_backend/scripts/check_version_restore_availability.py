"""이전 버전 복원 가용성 점검 도구 (2026.11.06(sooyeon.choi) 수정 - 신규, UI-12 R1-5, 설계 v1.1 9.1).

문서·버전별로 Qdrant 포인트, 청크 기록, 원본 파일, 문서 snapshot, 임베딩 프로필을 확인해 복원 가능 여부를 표로 보여 준다.
기본은 읽기 전용(dry-run). --apply일 때만 확인 결과를 버전 행에 기록한다.

사용법 (adrag_backend 폴더에서, 운영 반영은 사용자가 직접 실행)
    python scripts/check_version_restore_availability.py                      # 전체 점검(읽기 전용)
    python scripts/check_version_restore_availability.py --document-id <ID>   # 한 문서만
    python scripts/check_version_restore_availability.py --apply              # 결과 기록(available/missing·명세·검증 시각)
    python scripts/check_version_restore_availability.py --apply --assume-current-profile
        # 프로필 기록이 없는 버전에 현재 프로필을 기록한다. 그 버전이 현재 임베딩 설정으로 적재됐음을 운영자가
        # 확인한 경우에만 쓴다(설계 v1.1 5.5: 증명할 수 없으면 PROFILE_UNKNOWN 유지)

출력에는 문서 ID·버전·상태·건수만 쓰고 파일 경로·서버 주소는 쓰지 않는다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.repositories.database import get_database_manager  # noqa: E402
from app.repositories.ingest_record_repository import IngestRecordRepository  # noqa: E402
from app.services.embedding_profile import ensure_current_profile_id  # noqa: E402
from app.services.ingest_service import get_original_file_storage  # noqa: E402


def _source_exists(source_path: str) -> bool:
    if not source_path:
        return False
    try:
        return get_original_file_storage(get_settings()).resolve(source_path).is_file()
    except ValueError:
        return False


def _found_points(vector_repo, collection: str, document_id: str, version_no: int, point_ids: list[str]) -> int:
    found = 0
    for start in range(0, len(point_ids), 256):
        records = vector_repo.client.retrieve(
            collection_name=collection, ids=point_ids[start:start + 256],
            with_payload=["document_id", "version_no"], with_vectors=False,
        )
        found += sum(
            1 for r in records
            if (r.payload or {}).get("document_id") == document_id
            and int((r.payload or {}).get("version_no") or 1) == version_no
        )
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description="이전 버전 복원 가용성 점검(기본 읽기 전용)")
    parser.add_argument("--document-id")
    parser.add_argument("--apply", action="store_true", help="점검 결과를 버전 행에 기록")
    parser.add_argument("--assume-current-profile", action="store_true",
                        help="프로필 기록이 없는 버전에 현재 프로필을 기록(운영자 확인 시에만)")
    args = parser.parse_args()

    from app.repositories.vector_repository import VectorRepository

    settings = get_settings()
    db = get_database_manager()
    repo = IngestRecordRepository(db)
    vector_repo = VectorRepository(
        host=settings.qdrant_host, port=settings.qdrant_port,
        sparse_encoder_type=settings.sparse_encoder_type, kiwi_bm25_vector_name=settings.kiwi_bm25_vector_name,
    )
    where, params = "d.deleted_at IS NULL", []
    if args.document_id:
        where += " AND d.document_id = ?"
        params.append(args.document_id)
    rows = db.execute_query(
        f"""SELECT v.document_id, v.version_no, v.status, v.source_path, v.vector_storage_state,
                   v.embedding_profile_id, v.document_snapshot_json IS NOT NULL AS has_snapshot, c.qdrant_name
            FROM tb_document_versions v
            JOIN tb_documents d ON d.document_id = v.document_id
            LEFT JOIN tb_collections c ON c.collection_id = d.collection_id
            WHERE {where} ORDER BY v.document_id, v.version_no""",
        tuple(params),
    )
    profile_id = ensure_current_profile_id(db, settings) if args.apply else None
    print("document_id\tversion\tstatus\tpoints(found/expected)\tsource\tsnapshot\tprofile\tresult")
    summary = {"available": 0, "missing": 0, "skipped": 0}
    for row in rows:
        r = dict(row)
        if r["status"] not in ("active", "retired"):
            summary["skipped"] += 1
            continue
        point_ids = repo.version_point_ids(r["document_id"], r["version_no"])
        try:
            found = _found_points(vector_repo, r["qdrant_name"], r["document_id"], r["version_no"], point_ids)
        except Exception as exc:  # Qdrant 장애는 판정하지 않고 건너뜀
            print(f"{r['document_id']}\tv{r['version_no']}\t{r['status']}\t-\t-\t-\t-\tQDRANT_ERROR({type(exc).__name__})")
            summary["skipped"] += 1
            continue
        complete = bool(point_ids) and found == len(point_ids)
        source_ok = _source_exists(r["source_path"])
        state = "available" if complete and source_ok else "missing"
        profile = "있음" if r["embedding_profile_id"] else "없음"
        print(f"{r['document_id']}\tv{r['version_no']}\t{r['status']}\t{found}/{len(point_ids)}\t"
              f"{'있음' if source_ok else '없음'}\t{'있음' if r['has_snapshot'] else '없음'}\t{profile}\t{state}")
        summary[state] += 1
        if not args.apply:
            continue
        manifest = None
        if complete:
            manifest = {
                "point_count": len(point_ids),
                "point_ids_sha256": hashlib.sha256("\n".join(sorted(point_ids)).encode("utf-8")).hexdigest(),
            }
        assign_profile = args.assume_current_profile and r["embedding_profile_id"] is None and complete
        db.execute_update(
            """UPDATE tb_document_versions SET vector_storage_state = ?, restore_verified_at = now(),
                   vector_manifest_json = coalesce(?, vector_manifest_json),
                   embedding_profile_id = coalesce(embedding_profile_id, ?)
               WHERE document_id = ? AND version_no = ?""",
            (state, json.dumps(manifest) if manifest else None, profile_id if assign_profile else None,
             r["document_id"], r["version_no"]),
        )
    mode = "기록함(--apply)" if args.apply else "읽기 전용(dry-run)"
    print(f"\n[{mode}] available={summary['available']} missing={summary['missing']} skipped={summary['skipped']}")
    print("snapshot이 없는 과거 버전은 METADATA_MISSING으로 계속 차단된다(이 도구는 snapshot을 추정해 채우지 않음).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

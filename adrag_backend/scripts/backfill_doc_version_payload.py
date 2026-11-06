"""기존 Qdrant 포인트에 doc_version payload 채우기 (2026.11.06(sooyeon.choi) 수정 - 신규, 설계 v1.1 7.3 C안).

검색의 비활성 버전 제외 조건을 DOCUMENT_VERSION_FILTER_MODE=doc_version(match any 1개)으로 바꾸기 전에 실행한다.
키가 없는 포인트는 doc_version 조건으로 걸러지지 않으므로, 이 도구로 채우고 "미기록 0건"을 확인한 뒤 설정을 바꾼다.

- 값: "{document_id}:{version_no}". payload에 version_no가 없는 옛 포인트는 v1로 본다(기존 nested 필터와 같은 규칙).
- 대상: RDB에 있는 삭제되지 않은 문서의 버전. 벡터·다른 payload는 바꾸지 않는다(set_payload 병합).
- 기본은 읽기 전용(dry-run): 컬렉션별 미기록 포인트 수만 보여 준다. --apply일 때만 인덱스 생성·기록 후 다시 센다.
- 이미 키가 있는 포인트는 건드리지 않아 여러 번 실행해도 된다.

사용법 (adrag_backend 폴더에서, 운영 반영은 사용자가 직접 실행)
    python scripts/backfill_doc_version_payload.py            # 미기록 건수 확인
    python scripts/backfill_doc_version_payload.py --apply    # 채우기 + 재확인
출력에는 컬렉션 이름·건수만 쓴다(서버 주소 미출력).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdrant_client.models import (  # noqa: E402
    FieldCondition,
    Filter,
    IsEmptyCondition,
    MatchValue,
    PayloadField,
    PayloadSchemaType,
)

from app.services.version_visibility import DOC_VERSION_FIELD, doc_version_key  # noqa: E402

_MISSING = IsEmptyCondition(is_empty=PayloadField(key=DOC_VERSION_FIELD))


def missing_count(client, collection: str) -> int:
    return client.count(collection_name=collection, count_filter=Filter(must=[_MISSING]), exact=True).count


def version_targets(db) -> list[tuple[str, str, int]]:
    """(qdrant 컬렉션, document_id, version_no) — 삭제되지 않은 문서의 모든 버전."""
    rows = db.execute_query(
        """SELECT c.qdrant_name, v.document_id, v.version_no
           FROM tb_document_versions v
           JOIN tb_documents d ON d.document_id = v.document_id AND d.deleted_at IS NULL
           JOIN tb_collections c ON c.collection_id = d.collection_id
           ORDER BY c.qdrant_name, v.document_id, v.version_no"""
    )
    return [(r[0], r[1], int(r[2])) for r in rows]


def backfill(client, db, *, apply: bool) -> dict[str, dict[str, int]]:
    """컬렉션별 {before, groups, after}. apply=False면 after는 before와 같다."""
    targets = version_targets(db)
    existing = {c.name for c in client.get_collections().collections}
    report: dict[str, dict[str, int]] = {}
    for collection in sorted({t[0] for t in targets} & existing):
        report[collection] = {"before": missing_count(client, collection), "groups": 0, "after": 0}
        if apply:
            client.create_payload_index(
                collection_name=collection, field_name=DOC_VERSION_FIELD, field_schema=PayloadSchemaType.KEYWORD,
                wait=True,
            )
    for collection, document_id, version_no in targets:
        if collection not in report:
            continue
        report[collection]["groups"] += 1
        if not apply:
            continue
        doc = FieldCondition(key="document_id", match=MatchValue(value=document_id))
        selectors = [Filter(must=[doc, FieldCondition(key="version_no", match=MatchValue(value=version_no)), _MISSING])]
        if version_no == 1:  # version_no가 없는 옛 포인트 = v1
            selectors.append(Filter(must=[doc, IsEmptyCondition(is_empty=PayloadField(key="version_no")), _MISSING]))
        for selector in selectors:
            client.set_payload(
                collection_name=collection, payload={DOC_VERSION_FIELD: doc_version_key(document_id, version_no)},
                points=selector, wait=True,
            )
    for collection, item in report.items():
        item["after"] = missing_count(client, collection) if apply else item["before"]
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Qdrant 포인트 doc_version payload 채우기(기본 읽기 전용)")
    parser.add_argument("--apply", action="store_true", help="인덱스 생성 + 기록")
    args = parser.parse_args()

    from qdrant_client import QdrantClient

    from app.core.config import get_settings
    from app.repositories.database import get_database_manager

    settings = get_settings()
    client = QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)
    report = backfill(client, get_database_manager(), apply=args.apply)
    print("collection\tmissing_before\tversion_groups\tmissing_after")
    for collection, item in report.items():
        print(f"{collection}\t{item['before']}\t{item['groups']}\t{item['after']}")
    remaining = sum(item["after"] for item in report.values())
    mode = "기록함(--apply)" if args.apply else "읽기 전용(dry-run)"
    print(f"\n[{mode}] 미기록 포인트 합계: {remaining}")
    if args.apply and remaining == 0:
        print("모두 채워졌습니다. DOCUMENT_VERSION_FILTER_MODE=doc_version으로 바꿔도 됩니다.")
    elif args.apply:
        print("미기록 포인트가 남았습니다(RDB에 없는 문서의 포인트일 수 있음). 확인 전에는 nested를 유지하세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

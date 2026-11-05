"""검색에서 활성 버전만 보이게 하는 Qdrant 제외 조건 (2026.10.19 추가).

- 최신본 변경 중(building·ready)인 새 버전 포인트와, 전환 후 아직 지우지 못한 이전 버전 포인트가
  Qdrant에 함께 있을 수 있다. RDB(tb_documents.version_no = 활성 버전)를 기준으로
  "그 문서의 활성 버전이 아닌 포인트"를 모든 검색 채널에서 제외한다.
- 최신본 전환은 RDB 한 트랜잭션(tb_documents.version_no 갱신)으로 끝나므로, 이 필터 덕분에
  검색 결과가 새 버전으로 한 번에 바뀌고 구 버전 포인트 정리가 실패해도 구 버전은 검색되지 않는다.
- 제외 대상 문서: 활성 버전이 아니면서 포인트 정리가 끝나지 않은(vectors_purged_at IS NULL) 버전이 있는 문서.
  개정 이력이 없거나 정리가 끝난 문서는 조건을 붙이지 않는다(기존 검색과 같음).
"""
from __future__ import annotations

import logging
from typing import Optional

from qdrant_client.models import FieldCondition, Filter, IsEmptyCondition, MatchValue, PayloadField

from app.repositories.database import get_database_manager

logger = logging.getLogger(__name__)

_INACTIVE_SQL = """
SELECT d.document_id, d.version_no
FROM tb_documents d
WHERE d.deleted_at IS NULL
  AND EXISTS (
      SELECT 1 FROM tb_document_versions v
      WHERE v.document_id = d.document_id
        AND v.version_no <> d.version_no
        AND v.vectors_purged_at IS NULL
  )
"""


def documents_with_hidden_versions(db=None) -> list[tuple[str, int]]:
    """(document_id, 활성 version_no) 목록 — 이 문서들은 활성 버전 포인트만 검색에 남긴다."""
    rows = (db or get_database_manager()).execute_query(_INACTIVE_SQL)
    return [(row["document_id"], int(row["version_no"])) for row in rows]


def inactive_version_conditions(db=None) -> list[Filter]:
    """Qdrant ``must_not``에 넣을 조건 목록.

    문서마다: document_id = X 이고 version_no ≠ 활성 버전인 포인트를 제외한다.
    DB 조회에 실패하면 예외를 올린다(구 버전이 섞인 결과를 내지 않도록 호출자가 검색을 실패 처리).
    """
    conditions: list[Filter] = []
    for document_id, active_version in documents_with_hidden_versions(db):
        keep = [FieldCondition(key="version_no", match=MatchValue(value=active_version))]
        if active_version == 1:
            keep.append(IsEmptyCondition(is_empty=PayloadField(key="version_no")))
        conditions.append(Filter(
            must=[FieldCondition(key="document_id", match=MatchValue(value=document_id))],
            must_not=[Filter(should=keep)],
        ))
    return conditions


def with_version_exclusion(query_filter: Optional[Filter], db=None) -> Optional[Filter]:
    """기존 검색 필터에 비활성 버전 제외 조건을 더한다(제외할 것이 없으면 그대로)."""
    exclusions = inactive_version_conditions(db)
    if not exclusions:
        return query_filter
    if query_filter is None:
        return Filter(must_not=exclusions)
    return Filter(
        must=query_filter.must,
        should=query_filter.should,
        min_should=query_filter.min_should,
        must_not=list(query_filter.must_not or []) + exclusions,
    )

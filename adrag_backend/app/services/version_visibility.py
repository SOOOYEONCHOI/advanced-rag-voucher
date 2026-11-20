"""검색에서 활성 버전만 보이게 하는 Qdrant 제외 조건 (2026.10.19 추가).

- 최신본 변경 중(building·ready)인 새 버전 포인트와, 전환 후 아직 지우지 못한 이전 버전 포인트가
  Qdrant에 함께 있을 수 있다. RDB(tb_documents.version_no = 활성 버전)를 기준으로
  "그 문서의 활성 버전이 아닌 포인트"를 모든 검색 채널에서 제외한다.
- 최신본 전환은 RDB 한 트랜잭션(tb_documents.version_no 갱신)으로 끝나므로, 이 필터 덕분에
  검색 결과가 새 버전으로 한 번에 바뀌고 구 버전 포인트 정리가 실패해도 구 버전은 검색되지 않는다.
- 제외 대상 문서: 활성 버전이 아니면서 포인트 정리가 끝나지 않은(vectors_purged_at IS NULL) 버전이 있는 문서.
  개정 이력이 없거나 정리가 끝난 문서는 조건을 붙이지 않는다(기존 검색과 같음).
- 2026.11.06(sooyeon.choi) 수정 - 이전 버전 복원
  · 삭제 시각만 믿지 않는다: 보관 상태가 missing이 아닌 비활성 버전(보존·백업 복구 포인트)도 제외 대상
  · 요청 단위 snapshot: ``version_snapshot()`` 안에서는 활성 버전 목록을 한 번만 읽어 모든 검색 채널이 같은 버전을 본다
    (하이브리드 검색 도중 복원·최신본 전환이 커밋돼도 한 응답 안에서 버전이 섞이지 않음)
- 2026.11.06(sooyeon.choi) 수정 - 제외 조건 모양 선택(설계 v1.1 7.3 C안, 설정 DOCUMENT_VERSION_FILTER_MODE)
  · nested(기본·기존): 문서마다 {document_id = X, version_no ≠ 활성} 중첩 조건 1개 → 문서 수만큼 조건이 늘어남
  · doc_version: 포인트 payload ``doc_version = "{document_id}:{version_no}"``(keyword 인덱스)에 대한
    ``match any [비활성 버전 키…]`` 조건 1개. Qdrant 문서 권장("같은 필드 조건은 match any가 더 빠름")
    기준(어느 버전이 활성인지)은 두 방식 모두 RDB다. Qdrant 포인트의 값은 버전마다 고정이라 전환 때 쓰지 않는다.
  · doc_version은 기존 포인트에 키가 채워진 뒤에만 켠다(scripts/backfill_doc_version_payload.py로 채우고 0건 확인).
    키가 없는 포인트는 이 조건으로 걸러지지 않기 때문이다.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator, Optional

from qdrant_client.models import FieldCondition, Filter, IsEmptyCondition, MatchAny, MatchValue, PayloadField

from app.repositories.database import get_database_manager

logger = logging.getLogger(__name__)

# 2026.11.06(sooyeon.choi) 수정 - payload 키 이름·값 형식(적재·백필·필터 공통)
DOC_VERSION_FIELD = "doc_version"
FILTER_MODE_NESTED = "nested"
FILTER_MODE_DOC_VERSION = "doc_version"


def doc_version_key(document_id: str, version_no: int) -> str:
    return f"{document_id}:{int(version_no)}"


# 2026.11.06(sooyeon.choi) 수정 - 문서 단위 대신 비활성 버전 행 단위로 읽는다(두 방식이 같은 조회 결과를 쓴다)
_INACTIVE_SQL = """
SELECT v.document_id, coalesce(d.version_no, 1) AS active_version_no, v.version_no
FROM tb_document_versions v
JOIN tb_documents d ON d.document_id = v.document_id
WHERE d.deleted_at IS NULL
  AND v.version_no <> coalesce(d.version_no, 1)
  AND (v.vectors_purged_at IS NULL OR v.vector_storage_state <> 'missing')
ORDER BY v.document_id, v.version_no
"""


# 2026.11.06(sooyeon.choi) 수정 - 한 번 읽은 제외 대상(활성 버전 목록 + 비활성 버전 키)
@dataclass(frozen=True)
class _HiddenVersions:
    documents: tuple[tuple[str, int], ...]   # (document_id, 활성 version_no)
    inactive_keys: tuple[str, ...]           # "document_id:version_no"


# 2026.11.06(sooyeon.choi) 수정 - 요청 단위 snapshot(없으면 조회할 때마다 DB에서 읽음)
_snapshot: ContextVar[Optional[_HiddenVersions]] = ContextVar("version_visibility_snapshot", default=None)


@contextmanager
def version_snapshot(db=None) -> Iterator[_HiddenVersions]:
    """이 블록 안의 모든 검색이 같은 활성 버전 목록을 쓰게 한다. 이미 열려 있으면 바깥 snapshot을 그대로 쓴다."""
    current = _snapshot.get()
    if current is not None:
        yield current
        return
    token = _snapshot.set(_read_hidden_versions(db))
    try:
        yield _snapshot.get()
    finally:
        _snapshot.reset(token)


def _read_hidden_versions(db=None) -> _HiddenVersions:
    rows = (db or get_database_manager()).execute_query(_INACTIVE_SQL)
    documents: dict[str, int] = {}
    keys: list[str] = []
    for row in rows:
        documents.setdefault(row["document_id"], int(row["active_version_no"]))
        keys.append(doc_version_key(row["document_id"], row["version_no"]))
    return _HiddenVersions(tuple(documents.items()), tuple(keys))


def _hidden(db=None) -> _HiddenVersions:
    current = _snapshot.get()
    return current if current is not None else _read_hidden_versions(db)


def documents_with_hidden_versions(db=None) -> list[tuple[str, int]]:
    """(document_id, 활성 version_no) 목록 — 이 문서들은 활성 버전 포인트만 검색에 남긴다."""
    # 2026.11.06(sooyeon.choi) 수정 - 요청 단위 snapshot이 있으면 그것을 쓴다
    return list(_hidden(db).documents)


# 2026.11.06(sooyeon.choi) 추가 - 검색에서 뺄 비활성 버전 키 목록(doc_version 방식)
def inactive_version_keys(db=None) -> list[str]:
    return list(_hidden(db).inactive_keys)


# 2026.11.06(sooyeon.choi) 추가 - 제외 조건 방식(설정). 설정을 읽을 수 없으면 기존 방식
def filter_mode() -> str:
    try:
        from app.core.config import get_settings

        mode = getattr(get_settings(), "document_version_filter_mode", FILTER_MODE_NESTED)
    except Exception:
        return FILTER_MODE_NESTED
    return mode if mode in (FILTER_MODE_NESTED, FILTER_MODE_DOC_VERSION) else FILTER_MODE_NESTED


def inactive_version_conditions(db=None, mode: Optional[str] = None) -> list:
    """Qdrant ``must_not``에 넣을 조건 목록.

    nested: 문서마다 document_id = X 이고 version_no ≠ 활성 버전인 포인트를 제외한다.
    doc_version: doc_version이 비활성 버전 키 중 하나인 포인트를 조건 1개로 제외한다(2026.11.06 C안).
    DB 조회에 실패하면 예외를 올린다(구 버전이 섞인 결과를 내지 않도록 호출자가 검색을 실패 처리).
    """
    mode = mode or filter_mode()
    hidden = _hidden(db)
    if mode == FILTER_MODE_DOC_VERSION:
        if not hidden.inactive_keys:
            return []
        return [FieldCondition(key=DOC_VERSION_FIELD, match=MatchAny(any=list(hidden.inactive_keys)))]
    conditions: list[Filter] = []
    for document_id, active_version in hidden.documents:
        keep = [FieldCondition(key="version_no", match=MatchValue(value=active_version))]
        if active_version == 1:
            keep.append(IsEmptyCondition(is_empty=PayloadField(key="version_no")))
        conditions.append(Filter(
            must=[FieldCondition(key="document_id", match=MatchValue(value=document_id))],
            must_not=[Filter(should=keep)],
        ))
    return conditions


def with_version_exclusion(query_filter: Optional[Filter], db=None, mode: Optional[str] = None) -> Optional[Filter]:
    """기존 검색 필터에 비활성 버전 제외 조건을 더한다(제외할 것이 없으면 그대로)."""
    exclusions = inactive_version_conditions(db, mode)
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

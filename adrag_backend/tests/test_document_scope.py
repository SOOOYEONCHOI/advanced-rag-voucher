"""문서 열람 범위 공통 함수(app/utils/security.document_scope·in_document_scope) 단위 테스트.

2026.11.09(sooyeon.choi) 추가 - 리팩토링: routes/ingest.py·routes/spreadsheet_resources.py·
services/document_version_restore.py가 각자 하던 계산을 한 함수로 모았다(CLAUDE.md 규칙 8).
기존 세 구현과 같은 결과인지 확인한다. 검색 필터(build_metadata_filter)는 규칙이 달라 대상이 아니다.
"""
from types import SimpleNamespace

import pytest

from app.utils.security import SECURITY_HIERARCHY, document_scope, in_document_scope


def _perm(collections, level):
    return SimpleNamespace(accessible_collections=collections, max_security_level=level)


def _legacy_scope(permissions):
    """리팩토링 전 routes/ingest.py _get_user_accessible의 계산(비교 기준)."""
    if not permissions:
        return (set(), set())
    accessible = set(permissions.accessible_collections or [])
    allowed = set(SECURITY_HIERARCHY.get(permissions.max_security_level or "public", ["public"]))
    return (accessible, allowed)


@pytest.mark.parametrize("permissions", [
    None,
    _perm(None, None),
    _perm([], "public"),
    _perm(["documents"], "public"),
    _perm(["documents", "secret"], "internal"),
    _perm(["documents"], "confidential"),
    _perm(["documents"], "restricted"),
    _perm(["documents"], "unknown-level"),
])
def test_document_scope_matches_legacy_calculation(permissions):
    assert document_scope(permissions) == _legacy_scope(permissions)


def test_no_permission_row_sees_nothing():
    scope = document_scope(None)
    assert not in_document_scope(scope, "documents", "public")


def test_empty_collection_list_sees_nothing():
    # 라우트 규칙: 빈 목록 = 열람 불가(검색 필터의 "빈 목록 = 전체 허용"과 다름)
    assert not in_document_scope(document_scope(_perm([], "restricted")), "documents", "public")


@pytest.mark.parametrize("max_level, doc_level, expected", [
    ("public", "public", True),
    ("public", "internal", False),
    ("internal", "public", True),
    ("internal", "confidential", False),
    ("confidential", "confidential", True),
    ("restricted", "restricted", True),
    (None, "public", True),
    (None, "internal", False),
])
def test_security_level_hierarchy(max_level, doc_level, expected):
    assert in_document_scope(document_scope(_perm(["documents"], max_level)), "documents", doc_level) is expected


def test_collection_outside_scope_is_denied():
    assert not in_document_scope(document_scope(_perm(["documents"], "restricted")), "secret", "public")


def test_security_level_default_is_caller_rule():
    # None 기본값 처리는 호출하는 쪽이 정한다(_load_visible_document는 `or "public"`, 시트 자료 API는 그대로 비교)
    scope = document_scope(_perm(["documents"], "public"))
    assert not in_document_scope(scope, "documents", None)
    assert in_document_scope(scope, "documents", None or "public")

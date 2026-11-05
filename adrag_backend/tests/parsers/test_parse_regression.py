"""파싱·청킹 회귀 테스트.

2026.09.09(sooyeon.choi) 추가 - SFR-051 AC-051-4 대응.

목차 기반 논리 구조화(SFR-044~051) 진행 중 기존 동작이 의도치 않게 바뀌는 것을
막는다. 기준선은 tests/parsers/baseline_parse_snapshot.json에 커밋되어 있고,
픽스처(실제 업무 문서)는 VCS에 포함하지 않으므로 없으면 skip한다.

기준선을 갱신하려면:

    python tests/parsers/make_parse_baseline.py

갱신은 "현행 동작이 정답"이라는 선언이므로 변경 의도를 확인한 뒤에만 수행한다.
"""

from __future__ import annotations

import os

import pytest

from tests.parsers.parse_baseline import (
    BASELINE_SCHEMA,
    discover_fixtures,
    load_baseline,
    snapshot_fixture,
)

_BASELINE = load_baseline()
_FIXTURES = {f.doc_key: f for f in discover_fixtures()} if _BASELINE else {}

pytestmark = pytest.mark.skipif(
    not _BASELINE or not _FIXTURES,
    reason="기준선 또는 픽스처가 없습니다. make_parse_baseline.py를 먼저 실행하세요.",
)


def _baseline_docs() -> dict:
    return (_BASELINE or {}).get("documents", {})


def _covered_keys() -> list[str]:
    """기준선과 픽스처에 모두 있는 문서만 대상으로 한다."""
    return sorted(set(_baseline_docs()) & set(_FIXTURES))


def test_baseline_schema_matches() -> None:
    assert _BASELINE["schema"] == BASELINE_SCHEMA, (
        "기준선 스키마 버전이 다릅니다. make_parse_baseline.py로 재생성하세요."
    )


def test_no_fixture_disappeared_silently() -> None:
    """기준선에 있는 문서가 픽스처에서 빠지면 실패한다.

    doc_key는 픽스처 내용의 해시다. 같은 입력에 같은 출력을 보장하려면
    이 키가 맞아야 하지만, 반대로 픽스처가 한 글자라도 바뀌면 키가 달라져
    '검증 대상에서 조용히 빠지는' 형태로 커버리지가 사라진다.
    그 상태를 통과로 처리하면 회귀 테스트의 의미가 없으므로 실패로 다룬다.

    일부 픽스처만 보유한 로컬 환경에서는
    PARSE_BASELINE_ALLOW_PARTIAL=1로 경고 수준으로 낮출 수 있다.
    """
    missing = sorted(set(_baseline_docs()) - set(_FIXTURES))
    if not missing:
        return

    detail = "\n".join(
        f"  - {key} ({_baseline_docs()[key]['label']})" for key in missing[:10]
    )
    message = (
        f"기준선 {len(_baseline_docs())}건 중 {len(missing)}건의 픽스처를 찾지 못했습니다.\n"
        f"{detail}\n"
        "픽스처가 교체·변경되었을 수 있습니다. 의도한 변경이면 "
        "make_parse_baseline.py로 기준선을 갱신하세요."
    )
    if os.environ.get("PARSE_BASELINE_ALLOW_PARTIAL") == "1":
        pytest.skip(message)
    pytest.fail(message)


@pytest.mark.parametrize("doc_key", _covered_keys())
def test_chunking_matches_baseline(doc_key: str) -> None:
    """청크 수·본문·페이지 귀속이 기준선과 동일해야 한다."""
    expected = _baseline_docs()[doc_key]
    actual = snapshot_fixture(_FIXTURES[doc_key])
    label = expected["label"]

    assert actual["doc_type"] == expected["doc_type"], (
        f"[{label}] 문서 유형 변경: {expected['doc_type']} → {actual['doc_type']}"
    )
    assert actual["chunk_count"] == expected["chunk_count"], (
        f"[{label}] 청크 수 변경: {expected['chunk_count']} → {actual['chunk_count']}"
    )
    assert actual["text_digest"] == expected["text_digest"], (
        f"[{label}] 청크 본문이 변경되었습니다."
    )
    assert actual["attribution_digest"] == expected["attribution_digest"], (
        f"[{label}] 페이지·header_path 귀속이 변경되었습니다."
    )


@pytest.mark.parametrize("doc_key", _covered_keys())
def test_no_article_regression(doc_key: str) -> None:
    """기존에 탐지되던 조문이 사라지면 안 된다 (AC-048-2).

    구조화 작업으로 조문이 '추가'되는 것은 허용하고, '유실'만 실패로 본다.
    조문이 추가되면 test_chunking_matches_baseline이 함께 실패하므로,
    기준선 갱신 시 의도한 증가인지 검토하게 된다.
    """
    expected = set(_baseline_docs()[doc_key].get("article_numbers", []))
    if not expected:
        pytest.skip("법령 조문이 없는 문서")

    actual = set(snapshot_fixture(_FIXTURES[doc_key])["article_numbers"])
    lost = sorted(expected - actual)
    assert not lost, (
        f"[{_baseline_docs()[doc_key]['label']}] 조문 유실 {len(lost)}건: {lost[:20]}"
    )


@pytest.mark.parametrize(
    "doc_key",
    [k for k in _covered_keys() if _baseline_docs()[k].get("bookmark_article_count")],
)
def test_article_detection_rate_not_worse(doc_key: str) -> None:
    """북마크 정답 대비 조문 탐지율이 기준선보다 낮아지면 안 된다 (AC-048-1)."""
    expected = _baseline_docs()[doc_key]
    actual = snapshot_fixture(_FIXTURES[doc_key])
    assert actual["article_detection_rate"] >= expected["article_detection_rate"], (
        f"[{expected['label']}] 조문 탐지율 하락: "
        f"{expected['article_detection_rate']:.1%} → {actual['article_detection_rate']:.1%}"
    )

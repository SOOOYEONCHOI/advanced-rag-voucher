"""
Golden 데이터셋 로더.

파일 입출력, tune/test 분리, 기본 무결성 검증을 담당한다.
실질적인 chunk_id 존재 확인은 validator.py에서 별도로 수행한다.
"""

import json
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional

from offline_evaluation.dataset.schema import GoldenRecord


# ── 로드 / 저장 ────────────────────────────────────────────────

def load(path: str) -> List[GoldenRecord]:
    """JSON 파일에서 GoldenRecord 목록을 읽는다.

    단일 레코드 dict 또는 레코드 배열 둘 다 허용한다.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Golden 데이터셋 파일을 찾을 수 없습니다: {path}")

    with p.open(encoding="utf-8-sig") as f:  # BOM 있는 파일도 허용
        data = json.load(f)

    if isinstance(data, dict):
        data = [data]

    _validate_schema(data, path)
    return data


def save(records: List[GoldenRecord], path: str) -> None:
    """GoldenRecord 목록을 JSON 파일로 저장한다."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


# ── 필터링 헬퍼 ───────────────────────────────────────────────

def filter_by(
    records: List[GoldenRecord],
    *,
    split: Optional[str] = None,
    collection_name: Optional[str] = None,
    question_type: Optional[str] = None,
    difficulty: Optional[str] = None,
    expected_behavior: Optional[str] = None,
    tags: Optional[List[str]] = None,
) -> List[GoldenRecord]:
    """조건에 맞는 레코드만 반환한다."""
    result = records
    if split:
        result = [r for r in result if r.get("split") == split]
    if collection_name:
        result = [r for r in result if r["collection_name"] == collection_name]
    if question_type:
        result = [r for r in result if r["question_type"] == question_type]
    if difficulty:
        result = [r for r in result if r["difficulty"] == difficulty]
    if expected_behavior:
        result = [r for r in result if r["expected_behavior"] == expected_behavior]
    if tags:
        result = [r for r in result if any(t in r.get("tags", []) for t in tags)]
    return result


def stats(records: List[GoldenRecord]) -> Dict:
    """데이터셋 구성 통계를 반환한다."""
    return {
        "total": len(records),
        "by_split": dict(Counter(r.get("split", "unset") for r in records)),
        "by_question_type": dict(Counter(r["question_type"] for r in records)),
        "by_difficulty": dict(Counter(r["difficulty"] for r in records)),
        "by_expected_behavior": dict(Counter(r["expected_behavior"] for r in records)),
        "collections": sorted({r["collection_name"] for r in records}),
    }


# ── 내부 검증 ─────────────────────────────────────────────────

_REQUIRED_FIELDS = {
    "id", "collection_name", "user_id", "question",
    "expected_answer", "expected_evidence",
    "expected_behavior", "question_type", "difficulty",
}

_VALID_BEHAVIORS = {"answer", "not_enough_info", "guardrail", "permission_denied"}
_VALID_QTYPES = {"factual", "procedural", "comparative", "multi_evidence", "unanswerable"}
_VALID_DIFFICULTIES = {"easy", "normal", "hard"}


def _validate_schema(records: list, path: str) -> None:
    """필수 필드 존재 여부와 허용 값 범위만 검사한다."""
    ids = set()
    errors = []

    for i, r in enumerate(records):
        prefix = f"[{path}] 레코드 #{i} (id={r.get('id', '?')})"

        missing = _REQUIRED_FIELDS - set(r.keys())
        if missing:
            errors.append(f"{prefix}: 필수 필드 누락 — {missing}")
            continue

        if r["id"] in ids:
            errors.append(f"{prefix}: id 중복")
        ids.add(r["id"])

        if r["expected_behavior"] not in _VALID_BEHAVIORS:
            errors.append(f"{prefix}: expected_behavior 값 오류 — {r['expected_behavior']!r}")
        if r["question_type"] not in _VALID_QTYPES:
            errors.append(f"{prefix}: question_type 값 오류 — {r['question_type']!r}")
        if r["difficulty"] not in _VALID_DIFFICULTIES:
            errors.append(f"{prefix}: difficulty 값 오류 — {r['difficulty']!r}")

        if not isinstance(r.get("expected_evidence"), list):
            errors.append(f"{prefix}: expected_evidence가 리스트가 아님")
        elif r["expected_behavior"] == "answer" and len(r["expected_evidence"]) == 0:
            errors.append(f"{prefix}: expected_behavior=answer 인데 expected_evidence가 비어 있음")

    if errors:
        raise ValueError("Golden 데이터셋 스키마 오류:\n" + "\n".join(errors))

"""파싱·청킹 회귀 기준선 생성 CLI.

2026.09.09(sooyeon.choi) 추가 - SFR-051 AC-051-1 대응.

사용법 (adrag_backend 디렉터리에서):

    python tests/parsers/make_parse_baseline.py            # 생성/갱신
    python tests/parsers/make_parse_baseline.py --check    # 비교만 (기록 안 함)

기준선을 갱신하는 것은 "현행 동작이 정답"이라고 선언하는 것과 같다.
구조화 작업(SFR-044~051) 진행 중에는 변경 의도를 확인한 뒤에만 갱신한다.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.parsers.parse_baseline import (  # noqa: E402
    BASELINE_PATH,
    build_snapshot,
    json_fixture_dir,
    md_fixture_dir,
    load_baseline,
    save_baseline,
)


def _diff(old: dict, new: dict) -> list[str]:
    """기준선 간 차이를 사람이 읽을 수 있는 줄로 만든다."""
    lines: list[str] = []
    old_docs, new_docs = old.get("documents", {}), new.get("documents", {})

    for key in sorted(set(old_docs) - set(new_docs)):
        lines.append(f"  - 사라진 문서 {key} ({old_docs[key]['label']})")
    for key in sorted(set(new_docs) - set(old_docs)):
        lines.append(f"  + 새 문서 {key} ({new_docs[key]['label']})")

    for key in sorted(set(old_docs) & set(new_docs)):
        o, n = old_docs[key], new_docs[key]
        changed = [
            f"{field}: {o.get(field)} → {n.get(field)}"
            for field in (
                "doc_type",
                "chunk_count",
                "header_path_unique_count",
                "text_digest",
                "attribution_digest",
            )
            if o.get(field) != n.get(field)
        ]
        old_arts, new_arts = set(o.get("article_numbers", [])), set(n.get("article_numbers", []))
        if old_arts != new_arts:
            changed.append(
                f"조문: {len(old_arts)}개 → {len(new_arts)}개 "
                f"(추가 {len(new_arts - old_arts)}, 유실 {len(old_arts - new_arts)})"
            )
            if old_arts - new_arts:
                changed.append(f"  유실 조문: {sorted(old_arts - new_arts)[:20]}")
        if changed:
            lines.append(f"  * {n['label']} [{key}]")
            lines.extend(f"      {c}" for c in changed)
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description="파싱·청킹 회귀 기준선 생성")
    parser.add_argument("--check", action="store_true", help="비교만 수행하고 기록하지 않는다")
    args = parser.parse_args()

    # 파이프라인 로그가 결과를 덮지 않도록 낮춘다.
    logging.disable(logging.INFO)

    json_dir, md_dir = json_fixture_dir(), md_fixture_dir()
    if not json_dir.is_dir() and not md_dir.is_dir():
        print("[오류] 픽스처 디렉터리를 찾을 수 없습니다.", file=sys.stderr)
        print(f"       json: {json_dir}", file=sys.stderr)
        print(f"       md  : {md_dir}", file=sys.stderr)
        print("       PARSE_FIXTURE_JSON_DIR / PARSE_FIXTURE_MD_DIR로 지정할 수 있습니다.",
              file=sys.stderr)
        return 2

    print(f"픽스처 json: {json_dir}")
    print(f"픽스처 md  : {md_dir}")
    snapshot = build_snapshot()
    if not snapshot["documents"]:
        print("[오류] 사용 가능한 픽스처가 없습니다.", file=sys.stderr)
        return 2

    logging.disable(logging.NOTSET)

    print(f"\n{'문서':<44}{'종류':<6}{'유형':<10}{'쪽':>5}{'청크':>6}{'조문':>6}{'탐지율':>8}")
    print("-" * 92)
    for _key, doc in sorted(
        snapshot["documents"].items(), key=lambda kv: (-kv[1]["page_count"], kv[0])
    ):
        rate = doc.get("article_detection_rate")
        rate_s = f"{rate * 100:.0f}%" if rate is not None else "-"
        print(
            f"{doc['label'][:42]:<44}{doc['kind']:<6}{doc['doc_type']:<10}"
            f"{doc['page_count']:>5}{doc['chunk_count']:>6}"
            f"{len(doc['article_numbers']):>6}{rate_s:>8}"
        )
    print("-" * 92)
    print(f"문서 {snapshot['fixture_count']}건")

    previous = load_baseline()
    if previous:
        lines = _diff(previous, snapshot)
        if lines:
            print("\n[기존 기준선과의 차이]")
            print("\n".join(lines))
        else:
            print("\n기존 기준선과 동일합니다.")

    if args.check:
        print("\n--check 모드: 기록하지 않았습니다.")
        return 0

    save_baseline(snapshot)
    print(f"\n기준선 저장: {BASELINE_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

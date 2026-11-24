# 2026.11.23(sooyeon.choi) 추가 - AI+ 인증 시험 1 검색 완전성(Recall@10) 산출 스크립트 (시험합의서 시험 1, R8-7)
"""시험 데이터를 하이브리드 검색 시스템에 입력하여 질의별 상위 10개 문서 청크를 추출하고,
정답 근거 청크의 포함 여부를 비교하여 검색 완전성(Recall@10)을 산출한다.

    검색 완전성(Recall@10) = (상위 10개 검색 결과에 정답 근거 청크가 1개 이상 포함된 질의 수
                              / 전체 시험 질의 수) × 100 %

실행 위치: 백엔드 실행 환경(백엔드 컨테이너 안, 또는 같은 .env를 쓰는 adrag_backend 가상환경)
    python scripts/aiplus_test1_recall10.py --file 시험데이터셋_120.xlsx \
        --collection-map "산업안전보건법=AIE_산업안전보건법,중대재해처벌법=AIE_중대재해처벌법" --out ./aiplus_result
    # 단일 법령 데이터셋이면 --collection AIE_산업안전보건법

출력: 화면에 Recall@10(%), --out 폴더에 test1_recall10_items.csv(질의별)·test1_recall10_summary.json
"""

import argparse
import asyncio
import time
from datetime import datetime
from pathlib import Path

from aiplus_common import assign_collections, load_testset, parse_collection_map, print_banner, write_csv, write_json
from aiplus_search import chunk_label, describe, hybrid_search, load_components  # sys.path에 adrag_backend 추가

from app.evaluation.metrics.retrieval_metrics import first_rank, hit_at_k  # noqa: E402

TOP_K = 10


def top_k_chunk_ids(chunks, k: int):
    """[확인 항목] 통합 검색 결과에서 질의별 상위 k개 문서 청크 ID를 뽑는다(같은 ID 중복은 첫 순위만)."""
    seen, ids = set(), []
    for chunk in chunks:
        if chunk["chunk_id"] not in seen:
            seen.add(chunk["chunk_id"])
            ids.append(chunk["chunk_id"])
    return ids[:k]


async def run(args) -> None:
    # 1. 시험 데이터 및 정답 데이터 불러오기
    queries = load_testset(args.file)
    assign_collections(queries, args.collection, parse_collection_map(args.collection_map))

    # 2. 임베딩 모델 및 하이브리드 검색 구성 요소 불러오기
    deps = load_components(with_reranker=False)
    print_banner([f"[시험 1] 검색 완전성(Recall@10) · 시험 질의 {len(queries)}건", *describe(deps, False)])

    rows, hits = [], 0
    started_at = datetime.now().isoformat(timespec="seconds")
    for index, item in enumerate(queries, start=1):
        top_ids, labels, status, error, search_ms = [], [], "ok", "", None
        try:
            # 3·4. 의미 검색 + BM25 키워드 검색 → 통합 → 상위 10개
            found = await hybrid_search(item.question, item.collection, deps)
            search_ms = found["ms"]
            top_ids = top_k_chunk_ids(found["chunks"], TOP_K)
            by_id = {chunk["chunk_id"]: chunk for chunk in found["chunks"]}
            labels = [chunk_label(by_id[cid]) for cid in top_ids]
        except Exception as exc:  # 검색 오류 질의는 미포함(0)으로 센다 — 분모는 전체 질의 수
            status, error = "error", f"{type(exc).__name__}: {exc}"

        # 5. 상위 10개와 정답 근거 청크 비교 → 포함 여부
        hit = int(hit_at_k(top_ids, item.gold_chunk_ids, TOP_K) or 0) if item.gold_chunk_ids else 0
        rank = first_rank(top_ids, item.gold_chunk_ids, TOP_K) if item.gold_chunk_ids else None
        if not item.gold_chunk_ids:
            status, error = status if status == "error" else "no_gold", error or "정답 청크ID 없음(0점)"
        hits += hit
        rows.append([
            item.query_id, item.law, item.collection, item.question, status,
            hit, rank or "", "\n".join(sorted(item.gold_chunk_ids)),
            "\n".join(f"{n}. {cid} | {label}" for n, (cid, label) in enumerate(zip(top_ids, labels), start=1)),
            search_ms if search_ms is not None else "", error,
        ])
        print(f"[{index:>3}/{len(queries)}] {item.query_id} 포함={hit} 순위={rank or '-'} {status}", flush=True)

    # 6. 전체 시험 데이터에 대한 Recall@10
    total = len(queries)
    recall = hits / total * 100 if total else 0.0
    out = Path(args.out)
    write_csv(out / "test1_recall10_items.csv", [
        "질의ID", "법령", "컬렉션", "질의문", "상태", "정답포함(1/0)", "정답 첫 순위",
        "정답 청크ID", "검색 상위10(순위. 청크ID | 문서 > 조항)", "검색시간(ms)", "오류",
    ], rows)
    by_law = {}
    for row in rows:
        stat = by_law.setdefault(row[1] or "-", [0, 0])
        stat[0] += row[5]
        stat[1] += 1
    summary = {
        "test": "시험 1 검색 완전성(Recall@10)",
        "file": Path(args.file).name,
        "started_at": started_at,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "settings": describe(deps, False),
        "total": total,
        "hit": hits,
        "errors": sum(1 for row in rows if row[4] == "error"),
        "no_gold": sum(1 for row in rows if row[4] == "no_gold"),
        "recall_at_10_percent": round(recall, 2),
        "by_law": {law: {"hit": h, "total": n, "recall_at_10_percent": round(h / n * 100, 2)} for law, (h, n) in by_law.items()},
        "target": "80% 이상",
        "pass": recall >= 80.0,
    }
    write_json(out / "test1_recall10_summary.json", summary)
    print_banner([
        f"[시험 1] 검색 완전성 Recall@10 = {recall:.2f}%  ({hits}/{total})  목표 80% 이상 → {'만족' if summary['pass'] else '불만족'}",
        *(f"  - {law}: {v['recall_at_10_percent']:.2f}% ({v['hit']}/{v['total']}, 참고)" for law, v in summary["by_law"].items()),
        f"  검색 오류 {summary['errors']}건 · 정답 없음 {summary['no_gold']}건 (모두 0으로 계산, 분모 = 전체 질의 수)",
        f"  결과: {out / 'test1_recall10_items.csv'}",
    ])


def main() -> None:
    parser = argparse.ArgumentParser(description="AI+ 시험 1 검색 완전성(Recall@10)")
    parser.add_argument("--file", required=True, help="시험 데이터셋 xlsx('질의'·'정답 근거' 시트)")
    parser.add_argument("--collection", help="모든 질의에 쓸 컬렉션 qdrant_name")
    parser.add_argument("--collection-map", help='법령별 컬렉션: "산업안전보건법=AIE_산업안전보건법,중대재해처벌법=AIE_중대재해처벌법"')
    parser.add_argument("--out", default="./aiplus_result")
    parser.add_argument("--verbose", action="store_true", help="노드 INFO 로그도 출력")
    args = parser.parse_args()
    started = time.perf_counter()
    asyncio.run(run(args))
    print(f"소요 {time.perf_counter() - started:.1f}초")


if __name__ == "__main__":
    main()

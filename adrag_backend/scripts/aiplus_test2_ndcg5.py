# 2026.11.23(sooyeon.choi) 추가 - AI+ 인증 시험 2 검색 최종 정합성(NDCG@5) 산출 스크립트 (시험합의서 시험 2, R8-7)
"""시험 데이터를 하이브리드 검색 시스템에 입력하여 검색된 문서 청크를 Reranker 모델로 재정렬하고,
상위 5개 문서 청크의 관련도 및 순위를 정답 데이터와 비교하여 검색 최종 정합성(NDCG@5)을 산출한다.

    질의별 NDCG@5 = DCG@5 / IDCG@5
        DCG@5  = Σ(순위 i = 1..5) rel_i / log2(i + 1)     rel_i = 정답 근거 청크면 1, 아니면 0
        IDCG@5 = 정답 청크가 1위부터 min(정답 수, 5)개 있을 때의 DCG (가장 이상적인 순위)
    검색 최종 정합성(NDCG@5) = 질의별 NDCG@5의 합 / 전체 시험 질의 수

실행 위치: 백엔드 실행 환경(백엔드 컨테이너 안, 또는 같은 .env를 쓰는 adrag_backend 가상환경)
    python scripts/aiplus_test2_ndcg5.py --file 시험데이터셋_120.xlsx \
        --collection-map "산업안전보건법=AIE_산업안전보건법,중대재해처벌법=AIE_중대재해처벌법" --out ./aiplus_result

출력: 화면에 NDCG@5, --out 폴더에 test2_ndcg5_items.csv(질의별)·test2_ndcg5_summary.json
"""

import argparse
import asyncio
import time
from datetime import datetime
from pathlib import Path

from aiplus_common import assign_collections, load_testset, parse_collection_map, print_banner, write_csv, write_json
from aiplus_search import chunk_label, describe, hybrid_search, load_components, rerank_chunks  # sys.path에 adrag_backend 추가

from app.evaluation.metrics.retrieval_metrics import gold_ranks, ndcg_at_k  # noqa: E402

TOP_K = 5


async def run(args) -> None:
    # 1. 시험 데이터 및 정답 데이터 불러오기
    queries = load_testset(args.file)
    assign_collections(queries, args.collection, parse_collection_map(args.collection_map))

    # 2. 임베딩 모델 및 Reranker 모델 불러오기
    deps = load_components(with_reranker=True)
    print_banner([f"[시험 2] 검색 최종 정합성(NDCG@5) · 시험 질의 {len(queries)}건", *describe(deps, True)])

    rows, ndcg_sum = [], 0.0
    started_at = datetime.now().isoformat(timespec="seconds")
    for index, item in enumerate(queries, start=1):
        top_ids, lines, status, error, search_ms, rerank_ms = [], [], "ok", "", None, None
        try:
            # 3. 의미 검색 + BM25 키워드 검색 (하이브리드 검색 후보)
            found = await hybrid_search(item.question, item.collection, deps)
            search_ms = found["ms"]
            # 4. Reranker로 질의-청크 관련도 평가 → 재정렬
            reranked = await rerank_chunks(found["state"], deps)
            rerank_ms = reranked["ms"]
            top = reranked["chunks"][:TOP_K]
            top_ids = [chunk["chunk_id"] for chunk in top]
            lines = [
                f"{n}. {chunk['chunk_id']} | 점수 {chunk['score']:.4f} | {'정답' if chunk['chunk_id'] in item.gold_chunk_ids else '-'} | {chunk_label(chunk)}"
                for n, chunk in enumerate(top, start=1)
            ]
        except Exception as exc:  # 검색·재랭킹 오류 질의는 0점 — 분모는 전체 질의 수
            status, error = "error", f"{type(exc).__name__}: {exc}"

        # 5. 재정렬 상위 5개의 관련도·순위를 정답과 비교 → 질의별 NDCG@5
        ndcg = (ndcg_at_k(top_ids, item.gold_chunk_ids, TOP_K) or 0.0) if item.gold_chunk_ids else 0.0
        if not item.gold_chunk_ids and status != "error":
            status, error = "no_gold", "정답 청크ID 없음(0점)"
        ndcg_sum += ndcg
        ranks = gold_ranks(top_ids, item.gold_chunk_ids) if item.gold_chunk_ids else []
        rows.append([
            item.query_id, item.law, item.collection, item.question, status,
            round(ndcg, 4), ", ".join(map(str, ranks)), "\n".join(sorted(item.gold_chunk_ids)),
            "\n".join(lines), search_ms if search_ms is not None else "",
            rerank_ms if rerank_ms is not None else "", error,
        ])
        print(f"[{index:>3}/{len(queries)}] {item.query_id} NDCG@5={ndcg:.4f} 정답순위={ranks or '-'} {status}", flush=True)

    # 6. 전체 시험 데이터의 질의별 NDCG@5 평균
    total = len(queries)
    mean_ndcg = ndcg_sum / total if total else 0.0
    out = Path(args.out)
    write_csv(out / "test2_ndcg5_items.csv", [
        "질의ID", "법령", "컬렉션", "질의문", "상태", "NDCG@5", "정답 순위(상위5 안)",
        "정답 청크ID", "재랭킹 상위5(순위. 청크ID | 점수 | 정답 | 문서 > 조항)", "검색시간(ms)", "재랭킹시간(ms)", "오류",
    ], rows)
    by_law = {}
    for row in rows:
        stat = by_law.setdefault(row[1] or "-", [0.0, 0])
        stat[0] += row[5]
        stat[1] += 1
    summary = {
        "test": "시험 2 검색 최종 정합성(NDCG@5)",
        "file": Path(args.file).name,
        "started_at": started_at,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "settings": describe(deps, True),
        "total": total,
        "errors": sum(1 for row in rows if row[4] == "error"),
        "no_gold": sum(1 for row in rows if row[4] == "no_gold"),
        "ndcg_at_5": round(mean_ndcg, 4),
        "ndcg_at_5_percent": round(mean_ndcg * 100, 2),
        "by_law": {law: {"total": n, "ndcg_at_5": round(s / n, 4)} for law, (s, n) in by_law.items()},
        "target": "80% 이상",
        "pass": mean_ndcg >= 0.8,
    }
    write_json(out / "test2_ndcg5_summary.json", summary)
    print_banner([
        f"[시험 2] 검색 최종 정합성 NDCG@5 = {mean_ndcg:.4f} ({mean_ndcg * 100:.2f}%)  질의 {total}건 평균  "
        f"목표 80% 이상 → {'만족' if summary['pass'] else '불만족'}",
        *(f"  - {law}: {v['ndcg_at_5']:.4f} ({v['total']}건, 참고)" for law, v in summary["by_law"].items()),
        f"  검색·재랭킹 오류 {summary['errors']}건 · 정답 없음 {summary['no_gold']}건 (모두 0점, 분모 = 전체 질의 수)",
        f"  결과: {out / 'test2_ndcg5_items.csv'}",
    ])


def main() -> None:
    parser = argparse.ArgumentParser(description="AI+ 시험 2 검색 최종 정합성(NDCG@5)")
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

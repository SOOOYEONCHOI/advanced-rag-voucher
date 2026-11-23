# 2026.11.23(sooyeon.choi) 추가 - AI+ 인증 시험 4 근거 기반 답변 생성 평균 반환 시간 측정 스크립트 (시험합의서 시험 4, R8-7)
"""시험 데이터 120개를 We.RAG에 순차적으로 입력하여 문서 검색, 재랭킹 및 답변 생성을 수행하고,
질의별 답변 생성 요청 시점부터 최종 답변 생성 완료 시점까지의 소요 시간을 측정한 후 평균 반환 시간을 산출한다.

    답변 생성 평균 반환 시간(ms) = 전체 시험 데이터의 답변 생성 반환 시간 합계 / 전체 시험 데이터 수
    (참고) 첫 토큰 평균 응답 시간(ms) = 첫 답변 토큰을 받은 질의의 첫 토큰 시간 합계 / 그 질의 수

측정 방법
  - 호출: 챗봇 화면과 같은 We.RAG 스트리밍 질의 API  POST /api/query/stream  (SSE)
    서버 안에서 입력 검증 → 질의 분석 → 하이브리드 검색 → 재랭킹 → 답변 생성 → 인용 정리를 수행한다.
  - 시작 시점 : 이 스크립트가 질의 요청을 보내기 직전 (time.perf_counter)
  - 첫 토큰   : 첫 번째 `token` 이벤트(답변 글자)를 받은 시점
  - 최종 완료 : `done` 이벤트(답변·인용·기록까지 끝)를 받은 시점. `error` 이벤트나 연결 오류면 그 시점까지를 기록
  - 질의는 1건씩 순서대로 보낸다(동시 요청 없음).
  - 워밍업(선택): --warmup-query로 준 질의(시험 데이터가 아닌 것)를 먼저 보내고 결과·평균에서 뺀다.

실행 위치: 시험 PC (Python 3.10+, httpx·openpyxl). 서버 코드·.env는 필요 없다.
    # 로그인 계정은 환경변수로만 받는다(명령 인자·결과 파일에 남기지 않음). 시험 전용 계정 권장.
    set AIPLUS_USER_ID=<계정 ID>            (bash: export AIPLUS_USER_ID=...)
    set AIPLUS_PASSWORD=<비밀번호>
    python aiplus_test4_latency.py --base-url <We.RAG 주소> --file 시험데이터셋_120.xlsx \
        --collection-map "산업안전보건법=AIE_산업안전보건법,중대재해처벌법=AIE_중대재해처벌법" \
        --warmup-query "안전보건관리책임자의 업무는 무엇인가요" --out ./aiplus_result

출력: 화면에 평균 반환 시간(ms), --out 폴더에 test4_latency_items.csv(질의별 첫 토큰·최종 완료 시간·답변)·test4_latency_summary.json
"""

import argparse
import json
import os
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import httpx

from aiplus_common import assign_collections, load_testset, parse_collection_map, print_banner, write_csv, write_json

TARGET_MS = 5000


def login(client: httpx.Client) -> str:
    """계정 로그인 → Bearer 토큰. 계정 정보는 환경변수에서만 읽는다."""
    user_id = os.environ.get("AIPLUS_USER_ID")
    password = os.environ.get("AIPLUS_PASSWORD")
    if not user_id or not password:
        sys.exit("환경변수 AIPLUS_USER_ID, AIPLUS_PASSWORD를 설정하세요.")
    resp = client.post("/api/auth/login", json={"user_id": user_id, "password": password})
    if resp.status_code != 200:
        sys.exit(f"로그인 실패: HTTP {resp.status_code}")
    return resp.json()["access_token"]


def ask(client: httpx.Client, question: str, collection: str, timeout_s: float) -> Dict:
    """[확인 항목] 질의 1건을 We.RAG에 입력해 답변 생성을 요청하고, 첫 토큰·최종 완료 시간을 잰다."""
    result: Dict = {"status": "ok", "first_token_ms": None, "total_ms": None, "answer": "", "citations": 0, "error": ""}
    kind = None
    started = time.perf_counter()                                  # 요청 시작 시점

    def elapsed() -> float:
        return round((time.perf_counter() - started) * 1000, 1)

    try:
        with client.stream(
            "POST", "/api/query/stream",
            json={"query": question, "collection_name": collection},
            timeout=httpx.Timeout(timeout_s, connect=10.0),
        ) as resp:
            if resp.status_code != 200:
                resp.read()
                raise RuntimeError(f"HTTP {resp.status_code} {resp.text[:200]}")
            for line in resp.iter_lines():
                if not line.startswith("data:"):
                    continue
                event = json.loads(line[5:].strip())
                kind = event.get("type")
                if kind == "token" and event.get("content"):
                    if result["first_token_ms"] is None:
                        result["first_token_ms"] = elapsed()       # 첫 토큰 응답 시점
                    result["answer"] += event["content"]
                elif kind == "reset":                              # 서버가 LLM 재시도로 앞 토큰을 지우라고 보냄
                    result["answer"] = ""
                elif kind == "citations":
                    result["citations"] = len(event.get("data") or [])
                elif kind == "error":
                    result["status"], result["error"] = "error", event.get("message") or "error"
                    break
                elif kind == "done":
                    break
            result["total_ms"] = elapsed()                         # 최종 답변 생성 완료 시점
            if result["status"] == "ok" and kind != "done":
                result["status"], result["error"] = "error", "done 이벤트 없이 연결 종료"
    except Exception as exc:
        result["status"], result["error"] = "error", f"{type(exc).__name__}: {exc}"
        result["total_ms"] = elapsed()
    return result


def stats(values: List[float]) -> Optional[Dict]:
    if not values:
        return None
    ordered = sorted(values)

    def pct(p: float) -> float:
        return round(ordered[min(len(ordered) - 1, max(0, int(round(p / 100 * len(ordered))) - 1))], 1)

    return {
        "count": len(values), "mean": round(statistics.fmean(values), 1),
        "min": round(ordered[0], 1), "p50": pct(50), "p90": pct(90), "p95": pct(95), "max": round(ordered[-1], 1),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="AI+ 시험 4 근거 기반 답변 생성 평균 반환 시간")
    parser.add_argument("--base-url", required=True, help="We.RAG 주소 (예: http://<서버>:<포트>)")
    parser.add_argument("--file", required=True, help="시험 데이터셋 xlsx('질의' 시트)")
    parser.add_argument("--collection", help="모든 질의에 쓸 컬렉션 qdrant_name")
    parser.add_argument("--collection-map", help='법령별 컬렉션: "산업안전보건법=AIE_산업안전보건법,중대재해처벌법=AIE_중대재해처벌법"')
    parser.add_argument("--warmup-query", action="append", default=[], help="시험 데이터가 아닌 워밍업 질의(여러 번 지정 가능)")
    parser.add_argument("--timeout", type=float, default=120.0, help="질의 1건 제한 시간(초)")
    parser.add_argument("--out", default="./aiplus_result")
    args = parser.parse_args()

    # 1. 시험 데이터 불러오기 (정답 데이터는 쓰지 않음)
    queries = load_testset(args.file, with_gold=False)
    assign_collections(queries, args.collection, parse_collection_map(args.collection_map))

    with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=30.0) as client:
        client.headers["Authorization"] = f"Bearer {login(client)}"
        print_banner([
            f"[시험 4] 근거 기반 답변 생성 평균 반환 시간 · 시험 질의 {len(queries)}건 · 순차 실행",
            "측정: 요청 직전 → 첫 token 이벤트(첫 토큰) / done 이벤트(최종 완료), POST /api/query/stream",
        ])
        warmup_collection = queries[0].collection if queries else args.collection
        for n, question in enumerate(args.warmup_query, start=1):
            warm = ask(client, question, warmup_collection, args.timeout)
            print(f"[워밍업 {n}] {warm['status']} 최종 {warm['total_ms']}ms (평균에서 제외)")

        # 2~4. 질의별 답변 생성 요청 → 시간 측정 → 저장
        rows, results = [], []
        started_at = datetime.now().isoformat(timespec="seconds")
        for index, item in enumerate(queries, start=1):
            result = ask(client, item.question, item.collection, args.timeout)
            results.append(result)
            rows.append([
                item.query_id, item.law, item.collection, item.question, result["status"],
                result["first_token_ms"] if result["first_token_ms"] is not None else "",
                result["total_ms"], len(result["answer"]), result["citations"], result["answer"], result["error"],
            ])
            print(f"[{index:>3}/{len(queries)}] {item.query_id} 첫 토큰 {result['first_token_ms']}ms · "
                  f"최종 {result['total_ms']}ms {result['status']}", flush=True)

    # 5. 전체 시험 데이터의 반환 시간 평균 (분모 = 전체 시험 데이터 수, 오류 질의도 오류까지 걸린 시간으로 포함)
    total_values = [r["total_ms"] for r in results]
    first_values = [r["first_token_ms"] for r in results if r["first_token_ms"] is not None]
    total_stats, first_stats = stats(total_values), stats(first_values)
    errors = sum(1 for r in results if r["status"] != "ok")
    out = Path(args.out)
    write_csv(out / "test4_latency_items.csv", [
        "질의ID", "법령", "컬렉션", "질의문", "상태", "첫 토큰 응답 시간(ms)", "최종 답변 완료 시간(ms)",
        "답변 글자 수", "인용 수", "생성 답변", "오류",
    ], rows)
    mean_total = total_stats["mean"] if total_stats else None
    mean_first = first_stats["mean"] if first_stats else None
    summary = {
        "test": "시험 4 근거 기반 답변 생성 평균 반환 시간",
        "file": Path(args.file).name,
        "endpoint": "POST /api/query/stream",
        "started_at": started_at,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "total": len(results),
        "errors": errors,
        "warmup_queries": len(args.warmup_query),
        "total_ms": total_stats,
        "first_token_ms": first_stats,
        "target_ms": TARGET_MS,
        "pass_total": mean_total is not None and mean_total <= TARGET_MS,
        "pass_first_token": mean_first is not None and mean_first <= TARGET_MS,
    }
    write_json(out / "test4_latency_summary.json", summary)
    print_banner([
        f"[시험 4] 답변 생성 평균 반환 시간(최종 완료) = {mean_total}ms  (전체 {len(results)}건, 오류 {errors}건 포함)  "
        f"목표 {TARGET_MS}ms 이내 → {'만족' if summary['pass_total'] else '불만족'}",
        f"         첫 토큰 평균 응답 시간          = {mean_first}ms  ({len(first_values)}건)  "
        f"목표 {TARGET_MS}ms 이내 → {'만족' if summary['pass_first_token'] else '불만족'}",
        f"  최종 완료 p50 {total_stats and total_stats['p50']} · p90 {total_stats and total_stats['p90']} · 최대 {total_stats and total_stats['max']} ms",
        f"  결과: {out / 'test4_latency_items.csv'}",
    ])


if __name__ == "__main__":
    main()

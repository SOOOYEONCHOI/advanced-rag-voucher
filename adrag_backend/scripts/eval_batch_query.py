# 2026.11.18(sooyeon.choi) 추가 - 시험 대응 일괄 질의 호출 스크립트 (설계 10장, REQ-B-11)
"""질의 파일을 We.RAG 서버에 올려 순차 실행하고 결과 CSV·xlsx를 저장한다.

사용법
------
    # 로그인 계정은 환경변수로만 받는다(명령 인자·기록에 남기지 않음)
    set EVAL_ADMIN_ID=<관리자 ID>            (bash: export EVAL_ADMIN_ID=...)
    set EVAL_ADMIN_PASSWORD=<비밀번호>

    python scripts/eval_batch_query.py --base-url <서버 주소> --collection <컬렉션 qdrant_name> \
        --file 시험질의_120.xlsx --out ./result [--name "시험 120"] [--warmup 3]

    # 이미 등록한 작업의 결과만 다시 받기
    python scripts/eval_batch_query.py --base-url <서버 주소> --job-id 12 --out ./result

    # 정답 근거 대조 (2026.11.18(sooyeon.choi) 추가)
    #  1) 정답 파일 업로드 → 자동 매칭 → 검토 Excel(gold_review.xlsx) 저장
    python scripts/eval_batch_query.py --base-url <서버 주소> --job-id 12 --gold 정답근거.xlsx --out ./result
    #  2) 검토 Excel을 사람이 확인·수정한 뒤 업로드 → 확정 → Recall@10 → 결과 파일 다시 저장
    python scripts/eval_batch_query.py --base-url <서버 주소> --job-id 12 --gold-review ./result/batch_12_gold_review.xlsx --out ./result

    # 시험 실행 (2026.11.19(sooyeon.choi) 추가) - 시험 데이터셋 xlsx 하나로 질의 등록 → 실행 → 정답 확정 → 지표 출력
    #   '질의' 시트(질의ID·질의문)로 작업을 등록하고, '정답 근거' 시트(청크ID 포함)로 바로 확정한다
    python scripts/eval_batch_query.py --base-url <서버 주소> --collection <컬렉션> \
        --file 시험데이터셋.xlsx --gold 시험데이터셋.xlsx --out ./result
    #   출력: 검색 완전성 Recall@10(%) · 검색 최종 정합성 NDCG@5 · 평균 반환 시간(ms)  ※ 분모 = 전체 시험 질의 수

정답 파일: 첫 행 머리글 `질의ID`, `근거순번`(선택), `근거 문서명`, `근거 위치`(선택), `근거 내용`.
  `청크ID` 열이 있으면 자동 매칭 없이 그 청크를 정답으로 확정한다(시험 데이터셋 '정답 근거' 시트).

질의 파일: CSV(UTF-8/CP949) 또는 xlsx. 첫 행 머리글에 `질의ID`, `질의문` 열이 있어야 한다.
동작: 로그인 → 작업 등록 → 10초마다 진행률 출력 → 완료 시 results.csv·results.xlsx 저장.
응답시간: 서버가 질의 1건씩 순차로 실행하며, 질의별 "요청 시작 → 문서 검색 → 재랭킹 → 답변 생성 완료"
시간을 잰다(비스트리밍, 앞 워밍업 N건 제외). 서버 설정 EVAL_BATCH_QUERY_ENABLED=true가 필요하다.
"""

import argparse
import os
import sys
import time
from pathlib import Path

import httpx

_FINISHED = ("completed", "failed", "cancelled")


def _login(client: httpx.Client) -> str:
    user_id = os.environ.get("EVAL_ADMIN_ID")
    password = os.environ.get("EVAL_ADMIN_PASSWORD")
    if not user_id or not password:
        sys.exit("환경변수 EVAL_ADMIN_ID, EVAL_ADMIN_PASSWORD를 설정하세요.")
    resp = client.post("/api/auth/login", json={"user_id": user_id, "password": password})
    if resp.status_code != 200:
        sys.exit(f"로그인 실패: HTTP {resp.status_code}")
    body = resp.json()
    if not body.get("is_admin"):
        sys.exit("관리자 계정이 아닙니다.")
    return body["access_token"]


def _create_job(client: httpx.Client, args) -> int:
    path = Path(args.file)
    data = {"collection_name": args.collection}
    if args.name:
        data["name"] = args.name
    if args.warmup is not None:
        data["warmup_count"] = str(args.warmup)
    with path.open("rb") as fp:
        resp = client.post("/api/eval/batch-jobs", data=data, files={"file": (path.name, fp)})
    if resp.status_code == 404:
        sys.exit("일괄 질의 기능이 꺼져 있거나 컬렉션이 없습니다(EVAL_BATCH_QUERY_ENABLED 확인).")
    if resp.status_code == 400:
        detail = resp.json().get("detail") or {}
        print(detail.get("message", "질의 파일 오류"))
        for error in detail.get("errors", []):
            print(f"  - {error.get('row') or '-'}행 {error.get('column') or ''}: {error.get('reason')}")
        sys.exit(1)
    resp.raise_for_status()
    body = resp.json()
    print(f"작업 등록: job_id={body['job_id']} 질의 {body['total']}건 (대기 순번 {body['queue_position']})")
    return int(body["job_id"])


def _wait(client: httpx.Client, job_id: int, interval: float) -> dict:
    while True:
        resp = client.get(f"/api/eval/batch-jobs/{job_id}")
        resp.raise_for_status()
        job = resp.json()
        eta = f", 남은 시간 약 {job['eta_seconds']}초" if job.get("eta_seconds") is not None else ""
        print(f"[{time.strftime('%H:%M:%S')}] {job['status']} {job['done']}/{job['total']} 오류 {job['errors']}{eta}")
        if job["status"] in _FINISHED:
            return job
        time.sleep(interval)


def _download(client: httpx.Client, job_id: int, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for ext in ("csv", "xlsx"):
        resp = client.get(f"/api/eval/batch-jobs/{job_id}/results.{ext}")
        resp.raise_for_status()
        target = out_dir / f"batch_{job_id}_results.{ext}"
        target.write_bytes(resp.content)
        print(f"저장: {target}")


def _print_test_metrics(recall: dict, summary: dict) -> None:
    """2026.11.19(sooyeon.choi) 추가 - 합의서 시험 1·2·4 지표 출력(분모 = 전체 시험 질의 수)."""
    stats = summary.get("response_ms") or {}
    total = recall.get("total")
    value = recall.get("value")
    ndcg = recall.get("ndcg")
    print("=" * 60)
    print(f"[시험 1] 검색 완전성 Recall@10 : "
          f"{'-' if value is None else f'{value * 100:.2f}%'} ({recall.get('hit')}/{total}, 재랭킹 전 상위 10)")
    print(f"[시험 2] 검색 최종 정합성 NDCG@5 : {'-' if ndcg is None else f'{ndcg:.4f}'} (재랭킹 후 상위 5, 질의 {total}건 평균)")
    if summary.get("response_time_status") == "complete":
        print(f"[시험 4] 평균 반환 시간       : {stats.get('mean')}ms (전체 {stats.get('count')}건, 오류 {summary.get('error')}건 포함)")
    else:
        print(f"[시험 4] 평균 반환 시간       : 미완료 (시간 측정 누락 {summary.get('response_time_missing')}건)")
    if recall.get("excluded") or recall.get("item_errors"):
        print(f"  참고: 정답 없음·제외 {recall.get('excluded')}건은 0점, 실행 오류 {recall.get('item_errors')}건은 검색·재랭킹 단계별로 평가")
    if recall.get("version_mismatch"):
        print(f"  경고: 정답 청크의 문서 버전이 실행 당시와 다른 질의 {recall.get('version_mismatch')}건")
    print("=" * 60)


def _upload_gold(client: httpx.Client, job_id: int, path: Path, out_dir: Path, summary: dict) -> None:
    with path.open("rb") as fp:
        resp = client.post(f"/api/eval/batch-jobs/{job_id}/gold", files={"file": (path.name, fp)})
    _exit_on_file_error(resp, "정답 파일 오류")
    body = resp.json()
    print(
        f"정답 매칭: 근거 {body['evidences']}건(질의 {body['queries']}건) · 청크ID 확정 {body.get('confirmed', 0)} · "
        f"자동 매칭 {body['auto']} · 매칭 없음 {body['unmatched']} · 문서 못 찾음 {body['document_not_found']}"
    )
    # 2026.11.19(sooyeon.choi) 추가 - 모든 근거에 청크ID가 있으면 검토 없이 바로 확정 → 지표 출력
    if body.get("gold_status") == "confirmed":
        _print_test_metrics(body.get("recall_at_10") or {}, summary)
        return
    resp = client.get(f"/api/eval/batch-jobs/{job_id}/gold-review.xlsx")
    resp.raise_for_status()
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"batch_{job_id}_gold_review.xlsx"
    target.write_bytes(resp.content)
    print(f"검토 Excel 저장: {target} - 확인·수정 후 --gold-review로 올리세요")


def _upload_gold_review(client: httpx.Client, job_id: int, path: Path, summary: dict) -> None:
    with path.open("rb") as fp:
        resp = client.post(f"/api/eval/batch-jobs/{job_id}/gold-review", files={"file": (path.name, fp)})
    _exit_on_file_error(resp, "검토 파일 오류")
    body = resp.json()
    print(f"정답 확정: 확정 {body['confirmed']} · 제외 {body['excluded']} · 미확정 {body['unmatched']}")
    _print_test_metrics(body.get("recall_at_10") or {}, summary)  # 2026.11.19(sooyeon.choi) 수정


def _exit_on_file_error(resp: httpx.Response, title: str) -> None:
    if resp.status_code in (400, 409):
        detail = resp.json().get("detail")
        if isinstance(detail, dict):
            print(detail.get("message", title))
            for error in detail.get("errors", []):
                print(f"  - {error.get('row') or '-'}행 {error.get('column') or ''}: {error.get('reason')}")
        else:
            print(f"{title}: {detail}")
        sys.exit(1)
    resp.raise_for_status()


def main() -> None:
    parser = argparse.ArgumentParser(description="We.RAG 일괄 질의 실행·결과 저장")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--collection", help="컬렉션 qdrant_name (새 작업 등록 시 필수)")
    parser.add_argument("--file", help="질의 파일(CSV/xlsx)")
    parser.add_argument("--job-id", type=int, help="이미 등록한 작업 ID(결과만 받기)")
    parser.add_argument("--name")
    parser.add_argument("--warmup", type=int)
    parser.add_argument("--out", default="./result")
    parser.add_argument("--interval", type=float, default=10.0)
    parser.add_argument("--timeout", type=float, default=60.0, help="HTTP 요청 1건 제한(초)")
    parser.add_argument("--gold", help="정답 근거 파일(CSV/xlsx) - 업로드 후 검토 Excel 저장")
    parser.add_argument("--gold-review", help="사람이 확인한 검토 Excel - 업로드하면 정답 확정·Recall@10")
    args = parser.parse_args()
    if args.job_id is None and not (args.file and args.collection):
        parser.error("--file과 --collection, 또는 --job-id가 필요합니다")

    with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=args.timeout) as client:
        client.headers["Authorization"] = f"Bearer {_login(client)}"
        job_id = args.job_id if args.job_id is not None else _create_job(client, args)
        job = _wait(client, job_id, args.interval)
        summary = job.get("summary") or {}
        stats = summary.get("response_ms") or {}
        print(
            f"결과: {job['status']} 정상 {summary.get('ok')} / 오류 {summary.get('error')} · "
            f"응답시간 평균 {stats.get('mean')}ms p90 {stats.get('p90')}ms 최대 {stats.get('max')}ms"
        )
        if job.get("doc_version_changed"):
            print("경고: 작업 등록 이후 컬렉션 문서 버전이 바뀌었습니다.")
        if job["status"] == "failed":
            sys.exit(f"작업 실패: {job.get('error_message')}")
        out_dir = Path(args.out)
        if args.gold:
            _upload_gold(client, job_id, Path(args.gold), out_dir, summary)
        if args.gold_review:
            _upload_gold_review(client, job_id, Path(args.gold_review), summary)
        _download(client, job_id, out_dir)


if __name__ == "__main__":
    main()

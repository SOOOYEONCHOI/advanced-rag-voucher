"""
평가 시스템 CLI.

사용법:
  python -m offline_evaluation generate --collection <name> [옵션]
  python -m offline_evaluation retrieval --golden <path>  [옵션]
  python -m offline_evaluation run      --golden <path>     [옵션]
  python -m offline_evaluation report   --results <path>    [옵션]
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m offline_evaluation",
        description="RAG 평가 시스템",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # ── generate ──────────────────────────────────────────────
    g = sub.add_parser("generate", help="Qdrant 청크에서 후보 QA 생성 (사람 검수 전)")
    g.add_argument("--collection", required=True, help="대상 컬렉션 이름")
    g.add_argument("--sample",     type=int, default=50,   help="샘플링할 청크 수 (기본: 50)")
    g.add_argument("--per-chunk",  type=int, default=2,    help="청크당 QA 생성 수 (기본: 2)")
    g.add_argument("--out",        default="offline_evaluation/data/candidates", help="출력 디렉토리")
    g.add_argument("--ollama-url", default="http://49.247.45.119:11434")
    g.add_argument("--model",      default="qwen3:14b")
    g.add_argument("--seed",       type=int, default=42)

    # ── run ───────────────────────────────────────────────────
    r = sub.add_parser("run", help="Golden 데이터셋으로 파이프라인 평가 실행")
    r.add_argument("--golden",      required=True, help="Golden JSON 파일 경로")
    r.add_argument("--out",         default="offline_evaluation/results", help="리포트 출력 디렉토리")
    r.add_argument("--split",       choices=["tune", "test", "all"], default="test",
                   help="평가할 split (기본: test)")
    r.add_argument("--concurrency", type=int, default=2,   help="동시 실행 수 (기본: 2)")
    r.add_argument("--top-k",       type=int, default=10,  help="검색 top-k (기본: 10)")
    r.add_argument("--ollama-url",  default="http://49.247.45.119:11434")
    r.add_argument("--model",       default="qwen3:14b")
    r.add_argument("--no-llm-judge", action="store_true",
                   help="LLM judge(faithfulness/correctness) 평가 건너뜀")

    # ── retrieval ─────────────────────────────────────────────
    rt = sub.add_parser("retrieval", help="답변 생성 없이 검색 단계만 평가")
    rt.add_argument("--golden", required=True, help="Golden JSON 파일 경로")
    rt.add_argument(
        "--mode",
        choices=["dense_only", "hybrid_retrieval", "hybrid_rerank"],
        required=True,
        help="평가할 검색 단계",
    )
    rt.add_argument("--out", default="offline_evaluation/results/retrieval")
    rt.add_argument("--split", choices=["tune", "test", "all"], default="test")
    rt.add_argument("--concurrency", type=int, default=2)
    rt.add_argument("--top-k", type=int, default=10, help="평가 기준 검색 K")
    rt.add_argument("--rerank-k", type=int, default=5, help="rerank 평가 기준 K")

    # ── report ────────────────────────────────────────────────
    rp = sub.add_parser("report", help="저장된 results JSON에서 리포트 재생성")
    rp.add_argument("--results", required=True, help="results_*.json 파일 경로")
    rp.add_argument("--out",     default="offline_evaluation/results", help="리포트 출력 디렉토리")

    args = parser.parse_args()

    if args.cmd == "generate":
        asyncio.run(_cmd_generate(args))
    elif args.cmd == "retrieval":
        asyncio.run(_cmd_retrieval(args))
    elif args.cmd == "run":
        asyncio.run(_cmd_run(args))
    elif args.cmd == "report":
        _cmd_report(args)


# ── generate 핸들러 ───────────────────────────────────────────

async def _cmd_generate(args) -> None:
    from offline_evaluation.dataset.generator import GoldenDatasetGenerator

    generator = GoldenDatasetGenerator(
        ollama_url=args.ollama_url,
        model=args.model,
    )
    path = await generator.generate_for_collection(
        collection_name=args.collection,
        sample_size=args.sample,
        n_per_chunk=args.per_chunk,
        output_dir=args.out,
        seed=args.seed,
    )
    print(f"\n후보 파일 저장 완료: {path}")
    print("다음 단계: 파일을 열어 사람이 검수한 뒤 split을 test/tune으로 설정하세요.")


# ── run 핸들러 ────────────────────────────────────────────────

async def _cmd_run(args) -> None:
    from offline_evaluation.config import EvalConfig
    from offline_evaluation.dataset.loader import filter_by, load
    from offline_evaluation.reporter import EvalReporter, evaluate_all
    from offline_evaluation.runner import EvaluationRunner

    # 1. Golden 데이터셋 로드
    records = load(args.golden)
    if args.split != "all":
        records = filter_by(records, split=args.split)
    if not records:
        print(f"[오류] split='{args.split}'에 해당하는 레코드가 없습니다.")
        sys.exit(1)
    print(f"평가 대상: {len(records)}건 (split={args.split})")

    # 2. 설정 구성
    cfg = EvalConfig(
        ollama_url=args.ollama_url,
        judge_model=args.model,
        top_k=args.top_k,
        runner_concurrency=args.concurrency,
        results_dir=args.out,
    )

    # 3. 파이프라인 실행
    print("파이프라인 실행 중...")
    runner = EvaluationRunner(cfg)
    results = await runner.run_all(records)

    errors = [r for r in results if r["error"]]
    if errors:
        print(f"  파이프라인 오류 {len(errors)}건:")
        for e in errors:
            print(f"    {e['record_id']}: {e['error']}")

    # 4. 단계별 평가
    print("단계별 평가 중...")
    stage_metrics = await evaluate_all(records, results, cfg, skip_llm_judge=args.no_llm_judge)

    # 5. 리포트 저장
    reporter = EvalReporter(records, results, stage_metrics, cfg)
    paths = reporter.save(args.out)

    # 6. KPI 요약 출력
    summ = reporter.summary()
    print("\n─── 핵심 KPI ───────────────────────────────")
    for name, v in summ["kpi"].items():
        val = f"{v['value']:.4f}" if v["value"] is not None else "N/A"
        status = "PASS ✅" if v["pass"] else ("FAIL ❌" if v["pass"] is False else "N/A  —")
        print(f"  {name:<35} {val}  {status}")

    failures = reporter.failure_cases()
    print(f"\n실패 케이스: {len(failures)}건 / 전체 {len(records)}건")
    print(f"\n리포트 저장: {paths['markdown']}")


# ── 검색 전용 평가 핸들러 ─────────────────────────────────────

async def _cmd_retrieval(args) -> None:
    from offline_evaluation.config import EvalConfig
    from offline_evaluation.dataset.loader import filter_by, load
    from offline_evaluation.retrieval_reporter import (
        RetrievalEvalReporter,
        evaluate_retrieval_results,
    )
    from offline_evaluation.retrieval_runner import RetrievalEvaluationRunner

    records = load(args.golden)
    if args.split != "all":
        records = filter_by(records, split=args.split)
    if not records:
        print(f"[오류] split='{args.split}'에 해당하는 레코드가 없습니다.")
        sys.exit(1)

    config = EvalConfig(
        top_k=args.top_k,
        retrieval_k=args.top_k,
        rerank_k=args.rerank_k,
        runner_concurrency=args.concurrency,
        results_dir=args.out,
    )
    print(
        f"검색 평가 대상: {len(records)}건 "
        f"(mode={args.mode}, split={args.split}, K={args.top_k})"
    )
    runner = RetrievalEvaluationRunner(args.mode, config)
    results = await runner.run_all(records)
    metrics = evaluate_retrieval_results(records, results, config, args.mode)
    reporter = RetrievalEvalReporter(
        records, results, metrics, config, args.mode
    )
    paths = reporter.save(args.out)

    print("\n─── 검색 평가 요약 ─────────────────────────")
    for key, value in reporter.summary().items():
        print(f"  {key}: {value}")
    print(f"\nJSON: {paths['json']}")
    print(f"Markdown: {paths['markdown']}")
    print(f"CSV: {paths['csv']}")


# ── report 핸들러 ─────────────────────────────────────────────

def _cmd_report(args) -> None:
    """저장된 results JSON에서 요약을 출력하고 Markdown을 재생성한다."""
    path = Path(args.results)
    if not path.exists():
        print(f"[오류] 파일을 찾을 수 없습니다: {args.results}")
        sys.exit(1)

    with path.open(encoding="utf-8") as f:
        data = json.load(f)

    summ = data.get("summary", {})
    failures = data.get("failure_cases", [])

    print(f"\n리포트 타임스탬프: {data.get('timestamp')}")
    print(f"총 레코드: {summ.get('total_records')}")

    print("\n─── 핵심 KPI ───────────────────────────────")
    for name, v in summ.get("kpi", {}).items():
        val = f"{v['value']:.4f}" if v.get("value") is not None else "N/A"
        status = "PASS ✅" if v.get("pass") else ("FAIL ❌" if v.get("pass") is False else "N/A  —")
        print(f"  {name:<35} {val}  {status}")

    if failures:
        print(f"\n실패 케이스 {len(failures)}건:")
        for f in failures[:10]:
            print(f"  [{f['record_id']}] {f['question'][:50]} → {', '.join(f['failed_stages'])}")
        if len(failures) > 10:
            print(f"  ... 외 {len(failures) - 10}건 (전체 확인: {args.results})")

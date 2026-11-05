"""
평가 결과 집계 및 리포트 생성기.

evaluate_all(): 모든 evaluator를 순서대로 호출해 stage_metrics를 구성한다.
EvalReporter  : stage_metrics를 집계하고 JSON + Markdown 리포트를 저장한다.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from offline_evaluation.config import EvalConfig
from offline_evaluation.dataset.schema import GoldenRecord
from offline_evaluation.evaluators import answer, citation, rerank, retrieval, threshold_fallback
from offline_evaluation.evaluators.answer import AnswerEvaluator
from offline_evaluation.evaluators.base import EvalResult
from offline_evaluation.ollama_client import OllamaJudgeClient

logger = logging.getLogger(__name__)


# ── 전체 evaluator 실행 ────────────────────────────────────────

async def evaluate_all(
    records: List[GoldenRecord],
    results: List[EvalResult],
    config: EvalConfig,
    skip_llm_judge: bool = False,
) -> Dict[str, Dict]:
    """모든 evaluator를 실행하고 {record_id: {stage: metrics}} 를 반환한다."""
    ollama_client = OllamaJudgeClient(
        base_url=config.ollama_url,
        model=config.judge_model,
        timeout=config.judge_timeout,
    )
    answer_evaluator = AnswerEvaluator(ollama_client, skip_llm_judge=skip_llm_judge)
    record_map = {r["id"]: r for r in records}

    stage_metrics: Dict[str, Dict] = {}

    for result in results:
        rid = result["record_id"]
        record = record_map.get(rid)
        if record is None:
            logger.warning(f"record_id={rid} 에 해당하는 Golden 레코드가 없습니다.")
            continue

        stage_metrics[rid] = {
            "retrieval": retrieval.evaluate(record, result, k=config.retrieval_k),
            "rerank": rerank.evaluate(record, result, k=config.rerank_k),
            "threshold_fallback": threshold_fallback.evaluate(record, result),
            "citation": citation.evaluate(record, result),
            "answer": await answer_evaluator.evaluate(record, result),
        }
        logger.info(f"[reporter] {rid} 평가 완료")

    return stage_metrics


# ── 리포트 생성기 ─────────────────────────────────────────────

class EvalReporter:
    """stage_metrics를 집계하고 JSON + Markdown 리포트를 생성한다."""

    def __init__(
        self,
        records: List[GoldenRecord],
        results: List[EvalResult],
        stage_metrics: Dict[str, Dict],
        config: EvalConfig,
    ):
        self._records = {r["id"]: r for r in records}
        self._results = {r["record_id"]: r for r in results}
        self._metrics = stage_metrics
        self._config = config

    # ── 공개 인터페이스 ───────────────────────────────────────

    def summary(self) -> Dict:
        """핵심 KPI 4종과 단계별 집계를 반환한다."""
        retrieval_agg = self._agg_retrieval()
        rerank_agg = self._agg_rerank()
        citation_agg = self._agg_citation()
        answer_agg = self._agg_answer()
        tf_agg = self._agg_threshold_fallback()
        task9 = self._agg_task9()

        kpi = self._compute_kpi(retrieval_agg, rerank_agg, citation_agg, answer_agg)

        return {
            "kpi": kpi,
            "task9": task9,
            "retrieval": retrieval_agg,
            "rerank": rerank_agg,
            "threshold_fallback": tf_agg,
            "citation": citation_agg,
            "answer": answer_agg,
            "total_records": len(self._metrics),
        }

    def failure_cases(self) -> List[Dict]:
        """KPI 기준을 충족하지 못한 레코드 목록을 반환한다."""
        failures = []
        cfg = self._config

        for rid, stages in self._metrics.items():
            record = self._records.get(rid, {})
            failed_stages = []

            r = stages.get("retrieval", {})
            if not r.get("skipped") and r.get("recall_at_k") is not None:
                if r["recall_at_k"] < cfg.kpi_retrieval_recall:
                    failed_stages.append(
                        f"retrieval recall@{cfg.retrieval_k}={r['recall_at_k']:.2f}"
                        f" < {cfg.kpi_retrieval_recall}"
                    )

            rr = stages.get("rerank", {})
            if not rr.get("skipped") and rr.get("hit_at_k") is not None:
                if not rr["hit_at_k"]:
                    failed_stages.append(f"rerank hit@{cfg.rerank_k}=False")

            c = stages.get("citation", {})
            if not c.get("skipped"):
                if c.get("missing_citation"):
                    failed_stages.append("citation missing")
                if not c.get("all_numbers_valid"):
                    failed_stages.append("citation number out of range")

            tf = stages.get("threshold_fallback", {})
            if not tf.get("correct", True):
                failed_stages.append(
                    f"threshold_fallback incorrect "
                    f"(behavior={record.get('expected_behavior')})"
                )

            if failed_stages:
                failures.append({
                    "record_id": rid,
                    "question": record.get("question", ""),
                    "expected_behavior": record.get("expected_behavior", ""),
                    "difficulty": record.get("difficulty", ""),
                    "failed_stages": failed_stages,
                    "error": self._results.get(rid, {}).get("error"),
                })

        return failures

    def save(self, output_dir: str) -> Dict[str, str]:
        """JSON + Markdown 리포트를 저장하고 파일 경로를 반환한다."""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        json_path = out / f"results_{ts}.json"
        md_path = out / f"results_{ts}.md"

        summ = self.summary()
        failures = self.failure_cases()

        full_data = {
            "timestamp": ts,
            "summary": summ,
            "failure_cases": failures,
            "stage_metrics": self._metrics,
        }

        with json_path.open("w", encoding="utf-8") as f:
            json.dump(full_data, f, ensure_ascii=False, indent=2)

        md_path.write_text(
            self._render_markdown(summ, failures, ts),
            encoding="utf-8",
        )

        logger.info(f"리포트 저장 완료: {json_path}, {md_path}")
        return {"json": str(json_path), "markdown": str(md_path)}

    # ── 단계별 집계 ───────────────────────────────────────────

    def _agg_retrieval(self) -> Dict:
        vals = [
            m["retrieval"] for m in self._metrics.values()
            if not m.get("retrieval", {}).get("skipped")
        ]
        return {
            "count": len(vals),
            f"avg_recall_at_{self._config.retrieval_k}": _avg(
                [v["recall_at_k"] for v in vals]
            ),
            f"hit_rate_at_{self._config.retrieval_k}": _rate(
                [v["hit_at_k"] for v in vals]
            ),
            "avg_evidence_count": _avg([v["evidence_count"] for v in vals]),
            "avg_mrr": _avg([v.get("mrr") for v in vals]),
            f"avg_ndcg_at_{self._config.retrieval_k}": _avg(
                [v.get("ndcg_at_k") for v in vals]
            ),
            "top1_relevant_rate": _rate(
                [v.get("top1_is_relevant") for v in vals]
            ),
            "avg_evidence_rank": _avg(
                [v.get("evidence_rank") for v in vals]
            ),
        }

    def _agg_rerank(self) -> Dict:
        vals = [
            m["rerank"] for m in self._metrics.values()
            if not m.get("rerank", {}).get("skipped")
        ]
        return {
            "count": len(vals),
            "avg_mrr": _avg([v["mrr"] for v in vals]),
            f"avg_ndcg_at_{self._config.rerank_k}": _avg(
                [v["ndcg_at_k"] for v in vals]
            ),
            f"hit_rate_at_{self._config.rerank_k}": _rate(
                [v["hit_at_k"] for v in vals]
            ),
            "above_threshold_rate": _rate(
                [v["evidence_above_threshold"] for v in vals]
            ),
            "avg_evidence_rank": _avg(
                [v["evidence_rank"] for v in vals if v.get("evidence_rank") is not None]
            ),
        }

    def _agg_threshold_fallback(self) -> Dict:
        all_vals = list(self._metrics.values())
        tf_vals = [m["threshold_fallback"] for m in all_vals]
        return {
            "count": len(tf_vals),
            "correct_rate": _rate([v["correct"] for v in tf_vals]),
            "false_fallback_rate": _rate(
                [v.get("false_fallback") for v in tf_vals if v.get("false_fallback") is not None]
            ),
            "false_answer_rate": _rate(
                [v.get("false_answer") for v in tf_vals if v.get("false_answer") is not None]
            ),
            "avg_retry_count": _avg([v["retry_count"] for v in tf_vals]),
        }

    def _agg_citation(self) -> Dict:
        vals = [
            m["citation"] for m in self._metrics.values()
            if not m.get("citation", {}).get("skipped")
        ]
        return {
            "count": len(vals),
            "valid_number_rate": _rate([v["all_numbers_valid"] for v in vals]),
            "avg_relevance": _avg([v["citation_relevance"] for v in vals]),
            "missing_citation_rate": _rate([v["missing_citation"] for v in vals]),
        }

    def _agg_answer(self) -> Dict:
        vals = [m["answer"] for m in self._metrics.values()]
        return {
            "count": len(vals),
            "format_correct_rate": _rate(
                [v["format_correct"] for v in vals if v.get("format_correct") is not None]
            ),
            "refusal_correct_rate": _rate(
                [v["refusal_correct"] for v in vals if v.get("refusal_correct") is not None]
            ),
            "avg_faithfulness": _avg(
                [v["faithfulness"] for v in vals if v.get("faithfulness") is not None]
            ),
            "avg_correctness": _avg(
                [v["correctness"] for v in vals if v.get("correctness") is not None]
            ),
        }

    def _agg_task9(self) -> Dict:
        cfg = self._config

        retrieval_vals = [
            m.get("retrieval", {})
            for m in self._metrics.values()
            if not m.get("retrieval", {}).get("skipped")
            and m.get("retrieval", {}).get("recall_at_k") is not None
        ]
        rerank_vals = [
            m.get("rerank", {})
            for m in self._metrics.values()
            if not m.get("rerank", {}).get("skipped")
            and m.get("rerank", {}).get("ndcg_at_k") is not None
        ]
        evaluated_records = [
            rid
            for rid, metric in self._metrics.items()
            if not metric.get("retrieval", {}).get("skipped")
        ]

        no_context_count = 0
        for rid in evaluated_records:
            result = self._results.get(rid, {})
            if not result.get("final_context"):
                no_context_count += 1

        return {
            f"recall_at_{cfg.retrieval_k}": _avg(
                [v["recall_at_k"] for v in retrieval_vals]
            ),
            f"hit_at_{cfg.rerank_k}": _rate(
                [v["hit_at_k"] for v in rerank_vals]
            ),
            f"ndcg_at_{cfg.rerank_k}": _avg(
                [v["ndcg_at_k"] for v in rerank_vals]
            ),
            "no_context_rate": (
                round(no_context_count / len(evaluated_records), 4)
                if evaluated_records else None
            ),
            "avg_latency_ms": _avg(
                [r.get("total_latency_ms") for r in self._results.values()]
            ),
            "subset_failure_rates": self._task9_subset_failure_rates(),
        }

    def _task9_subset_failure_rates(self) -> Dict[str, Dict[str, float]]:
        subset_tags = {
            "law_reference": {"legal_reference"},
            "abbreviation": {"abbreviation"},
            "compound_term": {"compound_term"},
        }
        result: Dict[str, Dict[str, float]] = {}

        for subset_name, tags in subset_tags.items():
            total = 0
            failures = 0
            for rid, record in self._records.items():
                if not self._task9_record_in_subset(rid, record, tags):
                    continue
                retrieval = self._metrics.get(rid, {}).get("retrieval", {})
                recall = retrieval.get("recall_at_k")
                if recall is None:
                    continue
                total += 1
                if recall < 1.0:
                    failures += 1
            result[subset_name] = {
                "count": total,
                "failure_rate": round(failures / total, 4) if total else None,
            }

        return result

    @staticmethod
    def _task9_record_in_subset(rid: str, record: Dict, tags: set[str]) -> bool:
        record_tags = set(record.get("tags", []))
        if tags.intersection(record_tags):
            return True

        question = (record.get("question") or "").lower()
        record_id = (rid or "").lower()

        if "legal_reference" in tags:
            if any(marker in question for marker in ["조", "법", "시행", "기준"]):
                return True
            if "law" in record_id:
                return True

        if "abbreviation" in tags:
            if any(token in question.upper() for token in ["PSM", "MSDS", "LOTO", "TBM", "SDS", "RA", "GHS"]):
                return True
            if "abbr" in record_id:
                return True

        if "compound_term" in tags:
            if "compound" in record_id:
                return True
            if "평가" in question or "방법" in question:
                return True

        return False

    def _compute_kpi(
        self,
        retrieval_agg: Dict,
        rerank_agg: Dict,
        citation_agg: Dict,
        answer_agg: Dict,
    ) -> Dict:
        cfg = self._config

        recall = retrieval_agg.get(f"avg_recall_at_{cfg.retrieval_k}")
        rerank_hit = rerank_agg.get(f"hit_rate_at_{cfg.rerank_k}")
        cite_acc = _citation_accuracy(self._metrics)
        refusal = answer_agg.get("refusal_correct_rate")

        return {
            f"retrieval_recall_at_{cfg.retrieval_k}": {
                "value": recall,
                "threshold": cfg.kpi_retrieval_recall,
                "pass": recall >= cfg.kpi_retrieval_recall if recall is not None else None,
            },
            f"rerank_hit_at_{cfg.rerank_k}": {
                "value": rerank_hit,
                "threshold": cfg.kpi_rerank_hit,
                "pass": rerank_hit >= cfg.kpi_rerank_hit if rerank_hit is not None else None,
            },
            "citation_accuracy": {
                "value": cite_acc,
                "threshold": cfg.kpi_citation_accuracy,
                "pass": cite_acc >= cfg.kpi_citation_accuracy if cite_acc is not None else None,
            },
            "unanswerable_refusal": {
                "value": refusal,
                "threshold": cfg.kpi_unanswerable_refusal,
                "pass": refusal >= cfg.kpi_unanswerable_refusal if refusal is not None else None,
            },
        }

    # ── Markdown 렌더링 ───────────────────────────────────────

    def _render_markdown(self, summ: Dict, failures: List[Dict], ts: str) -> str:
        cfg = self._config
        kpi = summ["kpi"]
        lines = [
            f"# RAG 평가 리포트 — {ts[:8]}",
            f"\n총 {summ['total_records']}건 평가\n",
            "## 핵심 KPI\n",
            "| 지표 | 값 | 기준 | 통과 |",
            "|------|----|------|------|",
        ]
        for name, v in kpi.items():
            val = f"{v['value']:.4f}" if v["value"] is not None else "N/A"
            passed = "✅" if v["pass"] else ("❌" if v["pass"] is False else "—")
            lines.append(f"| {name} | {val} | ≥ {v['threshold']} | {passed} |")

        lines += [
            "\n## 단계별 지표\n",
            "### 검색 (Retrieve)\n",
            _dict_to_md_table(summ["retrieval"]),
            "\n### 리랭킹 (Rerank)\n",
            _dict_to_md_table(summ["rerank"]),
            "\n### Threshold / Fallback\n",
            _dict_to_md_table(summ["threshold_fallback"]),
            "\n### 인용 (Citation)\n",
            _dict_to_md_table(summ["citation"]),
            "\n### 생성 답변 (Answer)\n",
            _dict_to_md_table(summ["answer"]),
        ]

        if failures:
            lines += [f"\n## 실패 케이스 ({len(failures)}건)\n"]
            for f in failures:
                lines.append(
                    f"- **{f['record_id']}** [{f['expected_behavior']} / {f['difficulty']}]"
                    f"  \n  질문: {f['question'][:60]}  \n"
                    f"  실패: {', '.join(f['failed_stages'])}"
                )
                if f.get("error"):
                    lines.append(f"  오류: {f['error']}")
        else:
            lines.append("\n## 실패 케이스\n\n모든 케이스 통과 ✅")

        return "\n".join(lines) + "\n"


# ── 내부 헬퍼 ────────────────────────────────────────────────

def _avg(values: List) -> Optional[float]:
    clean = [v for v in values if v is not None]
    return round(sum(clean) / len(clean), 4) if clean else None


def _rate(values: List) -> Optional[float]:
    """bool 또는 0/1 값 목록에서 True 비율을 계산한다."""
    clean = [v for v in values if v is not None]
    return round(sum(bool(v) for v in clean) / len(clean), 4) if clean else None


def _citation_accuracy(metrics: Dict[str, Dict]) -> Optional[float]:
    """all_numbers_valid=True AND citation_relevance >= 0.5 인 비율."""
    cite_vals = [
        m["citation"] for m in metrics.values()
        if not m.get("citation", {}).get("skipped")
    ]
    if not cite_vals:
        return None
    passed = sum(
        1 for v in cite_vals
        if v.get("all_numbers_valid") and (v.get("citation_relevance") or 0.0) >= 0.5
    )
    return round(passed / len(cite_vals), 4)


def _dict_to_md_table(d: Dict) -> str:
    """dict를 2열 Markdown 표로 변환한다."""
    rows = ["| 지표 | 값 |", "|------|---|"]
    for k, v in d.items():
        if isinstance(v, float):
            v = f"{v:.4f}"
        rows.append(f"| {k} | {v} |")
    return "\n".join(rows)

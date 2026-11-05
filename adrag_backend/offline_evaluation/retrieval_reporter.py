"""검색 전용 평가 집계와 JSON/Markdown/CSV 출력."""

import csv
import json
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Dict, List

from offline_evaluation.config import EvalConfig
from offline_evaluation.dataset.schema import GoldenRecord
from offline_evaluation.evaluators import document_retrieval, rerank, retrieval
from offline_evaluation.evaluators.base import EvalResult


def evaluate_retrieval_results(
    records: List[GoldenRecord],
    results: List[EvalResult],
    config: EvalConfig,
    mode: str,
) -> Dict[str, Dict]:
    records_by_id = {r["id"]: r for r in records}
    metrics = {}
    for result in results:
        record = records_by_id[result["record_id"]]
        stages = {
            "retrieval": retrieval.evaluate(record, result, config.retrieval_k),
            "document_retrieval": document_retrieval.evaluate(
                record, result, config.retrieval_k
            ),
        }
        stages["rerank"] = (
            rerank.evaluate(record, result, config.rerank_k)
            if mode == "hybrid_rerank"
            else {"skipped": True, "reason": "stage_not_executed"}
        )
        metrics[result["record_id"]] = stages
    return metrics


class RetrievalEvalReporter:
    def __init__(
        self,
        records: List[GoldenRecord],
        results: List[EvalResult],
        metrics: Dict[str, Dict],
        config: EvalConfig,
        mode: str,
    ):
        self.records = {r["id"]: r for r in records}
        self.results = {r["record_id"]: r for r in results}
        self.metrics = metrics
        self.config = config
        self.mode = mode

    def summary(self) -> Dict:
        retrieval_values = [
            m["retrieval"] for m in self.metrics.values()
            if not m["retrieval"].get("skipped")
            and m["retrieval"].get("recall_at_k") is not None
        ]
        document_values = [
            m["document_retrieval"] for m in self.metrics.values()
            if not m["document_retrieval"].get("skipped")
            and m["document_retrieval"].get("recall_at_k") is not None
        ]
        rerank_values = [
            m["rerank"] for m in self.metrics.values()
            if not m["rerank"].get("skipped")
            and m["rerank"].get("ndcg_at_k") is not None
        ]
        latencies = [
            sum(v for key, v in r["timing"].items() if key.endswith("_s")) * 1000
            for r in self.results.values() if not r.get("error")
        ]
        return {
            "mode": self.mode,
            "total_records": len(self.results),
            "error_count": sum(bool(r.get("error")) for r in self.results.values()),
            f"chunk_recall_at_{self.config.retrieval_k}": _avg(
                [v["recall_at_k"] for v in retrieval_values]
            ),
            f"chunk_hit_rate_at_{self.config.retrieval_k}": _rate(
                [v["hit_at_k"] for v in retrieval_values]
            ),
            "retrieval_mrr": _avg([v.get("mrr") for v in retrieval_values]),
            f"retrieval_ndcg_at_{self.config.retrieval_k}": _avg(
                [v.get("ndcg_at_k") for v in retrieval_values]
            ),
            "retrieval_top1_relevant_rate": _rate(
                [v.get("top1_is_relevant") for v in retrieval_values]
            ),
            "avg_retrieval_evidence_rank": _avg(
                [v.get("evidence_rank") for v in retrieval_values]
            ),
            f"document_hit_rate_at_{self.config.retrieval_k}": _rate(
                [v["hit_at_k"] for v in document_values]
            ),
            "rerank_mrr": _avg([v["mrr"] for v in rerank_values]),
            f"rerank_ndcg_at_{self.config.rerank_k}": _avg(
                [v["ndcg_at_k"] for v in rerank_values]
            ),
            f"rerank_hit_rate_at_{self.config.rerank_k}": _rate(
                [v["hit_at_k"] for v in rerank_values]
            ),
            "avg_latency_ms": round(mean(latencies), 2) if latencies else None,
        }

    def save(self, output_dir: str) -> Dict[str, str]:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        base = f"retrieval_{self.mode}_{timestamp}"
        json_path = out / f"{base}.json"
        md_path = out / f"{base}.md"
        csv_path = out / f"{base}.csv"
        summary = self.summary()

        json_path.write_text(json.dumps({
            "timestamp": timestamp,
            "summary": summary,
            "stage_metrics": self.metrics,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        md_path.write_text(self._markdown(summary), encoding="utf-8")
        self._write_csv(csv_path)
        return {"json": str(json_path), "markdown": str(md_path), "csv": str(csv_path)}

    def _write_csv(self, path: Path) -> None:
        fields = [
            "record_id", "question", "expected_chunk_ids", "expected_document_ids",
            "retrieved_chunk_ids", "retrieved_document_ids", "reranked_chunk_ids",
            "retrieved_results", "chunk_recall", "chunk_hit", "document_hit",
            "retrieval_first_rank", "retrieval_mrr", "retrieval_ndcg",
            "retrieval_top1_relevant", "mrr", "ndcg",
            "latency_ms", "error",
        ]
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for rid, result in self.results.items():
                record = self.records[rid]
                stages = self.metrics[rid]
                rr = stages["rerank"]
                writer.writerow({
                    "record_id": rid,
                    "question": record["question"],
                    "expected_chunk_ids": json.dumps(
                        [e["chunk_id"] for e in record["expected_evidence"]], ensure_ascii=False
                    ),
                    "expected_document_ids": json.dumps(
                        [e["document_id"] for e in record["expected_evidence"]], ensure_ascii=False
                    ),
                    "retrieved_chunk_ids": json.dumps(
                        [c["chunk_id"] for c in result["retrieved_chunks"]], ensure_ascii=False
                    ),
                    "retrieved_document_ids": json.dumps(
                        [c["document_id"] for c in result["retrieved_chunks"]], ensure_ascii=False
                    ),
                    "reranked_chunk_ids": json.dumps(
                        [c["chunk_id"] for c in result["reranked_chunks"]], ensure_ascii=False
                    ),
                    "retrieved_results": json.dumps(
                        [self._retrieved_detail(c, rank) for rank, c in enumerate(
                            result["retrieved_chunks"][:self.config.retrieval_k], start=1
                        )],
                        ensure_ascii=False,
                    ),
                    "chunk_recall": stages["retrieval"].get("recall_at_k"),
                    "chunk_hit": stages["retrieval"].get("hit_at_k"),
                    "document_hit": stages["document_retrieval"].get("hit_at_k"),
                    "retrieval_first_rank": stages["retrieval"].get("evidence_rank"),
                    "retrieval_mrr": stages["retrieval"].get("mrr"),
                    "retrieval_ndcg": stages["retrieval"].get("ndcg_at_k"),
                    "retrieval_top1_relevant": stages["retrieval"].get("top1_is_relevant"),
                    "mrr": rr.get("mrr"),
                    "ndcg": rr.get("ndcg_at_k"),
                    "latency_ms": round(
                        sum(v for k, v in result["timing"].items() if k.endswith("_s")) * 1000, 2
                    ),
                    "error": result.get("error"),
                })

    @staticmethod
    def _retrieved_detail(chunk: Dict, rank: int) -> Dict:
        metadata = chunk.get("metadata") or {}
        return {
            "rank": rank,
            "chunk_id": chunk.get("chunk_id"),
            "document_id": chunk.get("document_id"),
            "score": chunk.get("score"),
            "filename": metadata.get("filename"),
            "page_number": metadata.get("page_number"),
            "section_name": metadata.get("section_name"),
            "text_preview": (chunk.get("text") or "")[:300],
        }

    def _markdown(self, summary: Dict) -> str:
        lines = [f"# Retrieval Evaluation: {self.mode}", "", "## Summary", ""]
        lines.extend(f"- {key}: {value}" for key, value in summary.items())
        return "\n".join(lines) + "\n"


def _avg(values):
    clean = [v for v in values if v is not None]
    return round(mean(clean), 4) if clean else None


def _rate(values):
    clean = [v for v in values if v is not None]
    return round(sum(bool(v) for v in clean) / len(clean), 4) if clean else None

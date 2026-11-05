"""DB 지표 키를 UI용 주요/보조 지표로 변환한다."""

from typing import Any


def metric_catalog(scope: str, config: dict[str, Any]) -> tuple[list[dict], list[dict]]:
    n = int(config.get("retrieval_top_n", config.get("top_k", 10)))
    k = int(config.get("rerank_top_k", 5))
    primary = [
        {"key": f"retrieval.rrf.recall@{n}", "label": f"Retriever Recall@{n}"},
        {"key": f"retrieval.rerank.ndcg@{k}", "label": f"Reranked NDCG@{k}"},
    ]
    if scope == "full":
        primary.extend([
            {"key": "answer.correctness", "label": "Answer Correctness"},
            {"key": "citation.completeness", "label": "Citation Completeness"},
        ])
    secondary = [
        {"key": f"retrieval.rerank.mrr@{k}", "label": f"Reranked MRR@{k}"},
        {"key": f"retrieval.rrf.ndcg@{n}", "label": f"Retriever NDCG@{n}"},
    ]
    return primary, secondary


def present_run_metrics(scope: str, config: dict[str, Any], rows: list[dict]) -> dict[str, Any]:
    by_key = {
        row["metric_key"]: row
        for row in rows
        if row.get("segment") == "all"
    }
    primary_defs, secondary_defs = metric_catalog(scope, config)

    def present(definitions: list[dict]) -> list[dict]:
        output = []
        for definition in definitions:
            row = by_key.get(definition["key"])
            if row is None:
                continue
            output.append({
                **definition,
                "value": row.get("metric_value"),
                "std": row.get("metric_std"),
                "evaluated_count": row.get("evaluated_count", 0),
                "excluded_count": row.get("excluded_count", 0),
                "error_count": row.get("error_count", 0),
                "total_count": row.get("total_count", 0),
            })
        return output

    return {"primary_metrics": present(primary_defs), "secondary_metrics": present(secondary_defs)}

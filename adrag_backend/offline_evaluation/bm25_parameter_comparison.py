"""동일 golden dataset으로 BM25 파라미터 전후 Recall@K를 비교한다."""

from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from rank_bm25 import BM25Okapi

from app.utils.kiwi_tokenizer import tokenize_corpus, tokenize_query_for_bm25


def _fetch_candidates(
    qdrant_url: str,
    collection_name: str,
    match_text: str,
    limit: int,
) -> list[tuple[str, str]]:
    body = json.dumps({
        "limit": limit,
        "with_payload": True,
        "with_vector": False,
        "filter": {
            "must": [{"key": "text", "match": {"text": match_text}}],
        },
    }).encode("utf-8")
    collection = urllib.parse.quote(collection_name, safe="")
    request = urllib.request.Request(
        f"{qdrant_url.rstrip('/')}/collections/{collection}/points/scroll",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.load(response)["result"]["points"]
    return [
        (str(point["id"]), str((point.get("payload") or {}).get("text", "")))
        for point in result
    ]


def _rank_candidates(
    candidates: list[tuple[str, str]],
    query_tokens: list[str],
    *,
    k1: float,
    b: float,
    top_k: int,
) -> list[str]:
    if not candidates or not query_tokens:
        return []
    corpus = [tokenize_corpus(text) for _, text in candidates]
    scores = BM25Okapi(corpus, k1=k1, b=b).get_scores(query_tokens)
    ranked = sorted(
        zip(candidates, scores.tolist()),
        key=lambda item: item[1],
        reverse=True,
    )
    return [point_id for ((point_id, _), score) in ranked if score > 0][:top_k]


def compare(
    records: list[dict[str, Any]],
    *,
    qdrant_url: str,
    top_k: int = 10,
    before: tuple[float, float] = (1.5, 0.75),
    after: tuple[float, float] = (1.2, 0.5),
) -> dict[str, Any]:
    rows = []
    errors = []
    for record in records:
        query_tokens = tokenize_query_for_bm25(record["question"])
        match_text = " ".join(query_tokens) or record["question"]
        try:
            candidates = _fetch_candidates(
                qdrant_url,
                record["collection_name"],
                match_text,
                top_k * 3,
            )
        except Exception as exc:
            errors.append({"id": record["id"], "error": str(exc)})
            continue

        expected = {
            str(item["chunk_id"])
            for item in record.get("expected_evidence", [])
            if item.get("chunk_id")
        }
        before_ids = _rank_candidates(
            candidates, query_tokens, k1=before[0], b=before[1], top_k=top_k
        )
        after_ids = _rank_candidates(
            candidates, query_tokens, k1=after[0], b=after[1], top_k=top_k
        )
        rows.append({
            "id": record["id"],
            "question": record["question"],
            "candidate_count": len(candidates),
            "before_hit": bool(expected.intersection(before_ids)),
            "after_hit": bool(expected.intersection(after_ids)),
        })

    count = len(rows)
    before_hits = sum(row["before_hit"] for row in rows)
    after_hits = sum(row["after_hit"] for row in rows)
    return {
        "dataset_records": len(records),
        "evaluated_records": count,
        "errors": errors,
        "top_k": top_k,
        "before": {
            "k1": before[0],
            "b": before[1],
            "hits": before_hits,
            "recall_at_k": round(before_hits / count, 4) if count else 0.0,
        },
        "after": {
            "k1": after[0],
            "b": after[1],
            "hits": after_hits,
            "recall_at_k": round(after_hits / count, 4) if count else 0.0,
        },
        "rows": rows,
    }


def _render_markdown(result: dict[str, Any]) -> str:
    top_k = result["top_k"]
    before = result["before"]
    after = result["after"]
    delta = after["recall_at_k"] - before["recall_at_k"]
    return "\n".join([
        "# BM25 파라미터 변경 전후 비교",
        "",
        f"- 평가 레코드: {result['evaluated_records']} / {result['dataset_records']}",
        f"- 오류: {len(result['errors'])}",
        "",
        f"| 설정 | k1 | b | Hit | Recall@{top_k} |",
        "|---|---:|---:|---:|---:|",
        f"| Before | {before['k1']} | {before['b']} | {before['hits']} | {before['recall_at_k']:.4f} |",
        f"| After | {after['k1']} | {after['b']} | {after['hits']} | {after['recall_at_k']:.4f} |",
        "",
        f"Recall@{top_k} 변화: {delta:+.4f}",
        "",
        "후보군은 동일한 Kiwi MatchText 결과를 사용하고 BM25Okapi의 k1/b만 변경했다.",
    ])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--golden", required=True)
    parser.add_argument("--qdrant-url", default="http://localhost:6333")
    parser.add_argument("--out", default="offline_evaluation/results/bm25_parameters")
    parser.add_argument("--top-k", type=int, default=10)
    args = parser.parse_args()

    records = json.loads(Path(args.golden).read_text(encoding="utf-8"))
    result = compare(records, qdrant_url=args.qdrant_url, top_k=args.top_k)
    output_dir = Path(args.out)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"bm25_parameter_comparison_{timestamp}.json"
    markdown_path = output_dir / f"bm25_parameter_comparison_{timestamp}.md"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(_render_markdown(result), encoding="utf-8")
    print(markdown_path)


if __name__ == "__main__":
    main()

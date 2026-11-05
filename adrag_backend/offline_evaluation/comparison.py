"""Task 9 comparison helpers."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


def build_comparison(
    labeled_summaries: list[tuple[str, dict[str, Any]]],
    *,
    latency_limit_pct: float = 20.0,
) -> dict[str, Any]:
    runs: list[dict[str, Any]] = []
    baseline_latency = None

    for index, (label, payload) in enumerate(labeled_summaries):
        task9 = payload.get("summary", {}).get("task9", {})
        latency = task9.get("avg_latency_ms")
        if index == 0:
            baseline_latency = latency

        delta_pct = None
        exceeded = False
        if baseline_latency is not None and latency is not None and baseline_latency > 0:
            delta_pct = round(((latency - baseline_latency) / baseline_latency) * 100.0, 4)
            exceeded = delta_pct > latency_limit_pct

        runs.append({
            "label": label,
            "task9": task9,
            "latency_delta_pct": delta_pct,
            "latency_exceeded": exceeded,
        })

    latency_checks = {
        run["label"]: {
            "avg_latency_ms": run["task9"].get("avg_latency_ms"),
            "delta_pct": run["latency_delta_pct"],
            "limit_pct": latency_limit_pct,
            "exceeded": run["latency_exceeded"],
        }
        for run in runs
    }

    return {
        "latency_limit_pct": latency_limit_pct,
        "baseline_label": runs[0]["label"] if runs else None,
        "runs": runs,
        "latency_checks": latency_checks,
    }


def render_markdown(comparison: dict[str, Any]) -> str:
    runs = comparison.get("runs", [])
    baseline_label = comparison.get("baseline_label")

    lines = [
        "# Task 9 Comparison",
        "",
        "## 총괄",
        "",
        f"- Baseline: {baseline_label}",
        f"- Latency limit: {comparison.get('latency_limit_pct')}%",
        "",
        "| Label | Recall@10 | Hit@5 | NDCG@5 | no_context_rate | avg_latency_ms | Delta(%) |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]

    for run in runs:
        task9 = run.get("task9", {})
        lines.append(
            "| {label} | {recall} | {hit} | {ndcg} | {no_context} | {latency} | {delta} |".format(
                label=run["label"],
                recall=_fmt(task9.get("recall_at_10")),
                hit=_fmt(task9.get("hit_at_5")),
                ndcg=_fmt(task9.get("ndcg_at_5")),
                no_context=_fmt(task9.get("no_context_rate")),
                latency=_fmt(task9.get("avg_latency_ms")),
                delta=_fmt(run.get("latency_delta_pct")),
            )
        )

    checks = comparison.get("latency_checks", {})
    if checks:
        lines += [
            "",
            "## Latency Checks",
            "",
            "| Label | Avg latency | Limit | Status |",
            "|---|---:|---:|---|",
        ]
        for label, item in checks.items():
            status = "초과" if item.get("exceeded") else "정상"
            lines.append(
                f"| {label} | {_fmt(item.get('avg_latency_ms'))} | "
                f"{_fmt(item.get('limit_pct'))} | {status} |"
            )

    return "\n".join(lines) + "\n"


def save_comparison(comparison: dict[str, Any], output_dir: str) -> dict[str, str]:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    json_path = out / f"task9_comparison_{ts}.json"
    md_path = out / f"task9_comparison_{ts}.md"

    json_path.write_text(
        json.dumps(comparison, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    md_path.write_text(render_markdown(comparison), encoding="utf-8")

    return {"json": str(json_path), "markdown": str(md_path)}


def _fmt(value: Any) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)

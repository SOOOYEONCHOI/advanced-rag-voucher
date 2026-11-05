"""Answer Correctness F2 — v2 문장 정렬 결과를 Coverage 중심 F2로 결합.

v2의 Gold Coverage와 System Precision을 재사용(추가 임베딩 불필요)하여
β=2 F-score로 변환한다. Coverage(정답 내용 커버율)를 2배 중시하므로
중요 내용 누락이 치명적인 산업안전 도메인에 적합하다.
"""

from typing import Any, Dict


def build_answer_correctness_f2(
    answer_correctness_v2: Dict[str, Any],
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """v2 임베딩 결과를 재사용해 Gold Coverage 중심 F2 점수를 반환한다."""
    f2_config = config.get("answer_correctness_f2") or {}
    source_metadata = answer_correctness_v2.get("metadata") or {}
    metadata = {
        "method": "sentence_alignment_f2",
        "metric_version": f2_config.get("metric_version", "f2.1"),
        "source_metric_version": source_metadata.get("metric_version"),
        "model": source_metadata.get("model"),
        "model_version": source_metadata.get("model_version"),
        "gold_coverage": source_metadata.get("gold_coverage"),
        "system_precision": source_metadata.get("system_precision"),
        "beta": 2.0,
    }

    status = answer_correctness_v2.get("status")
    if status != "evaluated":
        return {
            "value": None,
            "status": status,
            "reason": answer_correctness_v2.get("reason"),
            "metadata": metadata,
        }

    coverage = metadata["gold_coverage"]
    precision = metadata["system_precision"]
    if not isinstance(coverage, (int, float)) or not isinstance(precision, (int, float)):
        return {
            "value": None,
            "status": "error",
            "reason": "missing_alignment_components",
            "metadata": metadata,
        }

    # F2 공식: (1 + β²) × P × R / (β² × P + R), β=2
    denominator = 4.0 * precision + coverage
    value = 0.0 if denominator == 0 else 5.0 * coverage * precision / denominator
    return {
        "value": max(0.0, min(1.0, value)),
        "status": "evaluated",
        "reason": answer_correctness_v2.get("reason"),
        "metadata": metadata,
    }

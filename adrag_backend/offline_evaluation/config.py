"""평가 시스템 설정. 파이프라인 설정(app/core/config.py)과 독립적으로 관리한다."""

from dataclasses import dataclass


@dataclass
class EvalConfig:
    # ── Ollama LLM judge ────────────────────────────────
    ollama_url: str = "http://49.247.45.119:11434"
    judge_model: str = "qwen3:14b"
    judge_timeout: float = 60.0

    # ── 파이프라인 실행 ─────────────────────────────────
    top_k: int = 10
    runner_concurrency: int = 2   # 동시 실행 수 (vLLM 부하 고려)

    # ── 검색/rerank 평가 기준 K ──────────────────────────
    retrieval_k: int = 10         # Recall@K, Hit@K 기준
    rerank_k: int = 5             # nDCG@K, Rerank Hit@K 기준

    # ── 핵심 KPI 기준치 ─────────────────────────────────
    kpi_retrieval_recall: float = 0.80
    kpi_rerank_hit: float = 0.75
    kpi_citation_accuracy: float = 0.70
    kpi_unanswerable_refusal: float = 0.80

    # ── 경로 ────────────────────────────────────────────
    results_dir: str = "offline_evaluation/results"
    run_label: str = ""

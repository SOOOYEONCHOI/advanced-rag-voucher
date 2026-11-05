"""
평가 공통 타입 및 수식.

EvalResult: runner.py가 파이프라인 실행 후 채우는 중간 상태 캡처.
수식 함수: 모든 evaluator가 import해서 사용하는 검색 품질 지표.
"""

import math
from typing import Any, Dict, List, Optional
from typing_extensions import TypedDict

from app.graphs.state import ChunkResult


class EvalResult(TypedDict):
    """파이프라인 1회 실행 결과 — runner.py가 PipelineState에서 추출."""

    record_id: str

    # ── 가드레일 ──────────────────────────────────────────
    intent: Optional[str]           # guardrail이 분류한 intent
    should_retrieve: Optional[bool] # False면 파이프라인 중단

    # ── 검색 ──────────────────────────────────────────────
    retrieved_chunks: List[ChunkResult]   # rerank 전 원본 검색 결과
    reranked_chunks: List[ChunkResult]    # rerank 후 최종 순서

    # ── 컨텍스트 ──────────────────────────────────────────
    relevance_threshold_used: float       # 실제 적용된 threshold
    final_context: Optional[str]
    context_chunk_count: Optional[int]    # assemble_context에 포함된 청크 수
    # 2026.07.10(sooyeon.choi) 수정 - 평가도 LLM에 실제 전달된 번호 순서의 청크를 사용
    context_chunks: List[ChunkResult]

    # ── 생성 ──────────────────────────────────────────────
    generated_answer: Optional[str]
    citations: List[Dict[str, Any]]       # format_citations 결과

    # ── 흐름 메타 ─────────────────────────────────────────
    retry_count: int
    error: Optional[str]
    timing: Dict[str, float]              # 노드별 처리 시간 (ms)


# ── 검색 품질 수식 ────────────────────────────────────────────

def recall_at_k(relevant: set, retrieved: List[str], k: int) -> float:
    """Recall@K: relevant chunk가 top-K 안에 몇 개 포함되는지."""
    if not relevant:
        return 0.0
    return len(relevant & set(retrieved[:k])) / len(relevant)


def hit_at_k(relevant: set, retrieved: List[str], k: int) -> bool:
    """Hit@K: relevant chunk가 top-K 안에 하나라도 있는지."""
    return bool(relevant & set(retrieved[:k]))


def mrr(relevant: set, ranked: List[str]) -> float:
    """MRR: 첫 번째 relevant chunk의 역순위."""
    for i, chunk_id in enumerate(ranked, 1):
        if chunk_id in relevant:
            return 1.0 / i
    return 0.0


def ndcg_at_k(relevant: set, ranked: List[str], k: int) -> float:
    """nDCG@K: 순위를 고려한 relevant chunk 누적 품질."""
    dcg = sum(
        1.0 / math.log2(i + 1)
        for i, chunk_id in enumerate(ranked[:k], 1)
        if chunk_id in relevant
    )
    # 이상적 순서: relevant chunk가 모두 상위에 있을 때
    ideal = sum(
        1.0 / math.log2(i + 2)
        for i in range(min(len(relevant), k))
    )
    return dcg / ideal if ideal else 0.0


def first_rank(relevant: set, ranked: List[str]) -> Optional[int]:
    """ranked 리스트에서 첫 번째 relevant chunk의 1-based 순위. 없으면 None."""
    for i, chunk_id in enumerate(ranked, 1):
        if chunk_id in relevant:
            return i
    return None

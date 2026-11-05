"""검색 정확성 지표 — 순수 함수 (외부 의존성 없음).

모든 함수는 다음 입력을 받는다:
  retrieved_ids : 검색 결과 chunk_id 리스트 (순위순)
  gold_ids      : 정답 chunk_id 집합 (멀티홉은 2개 이상)

"""

import math
from typing import Any, Dict, List, Optional, Sequence, Set


def _dedup_preserve_order(ids: Sequence[str]) -> List[str]:
    """검색 결과의 중복 chunk_id를 순서 보존하며 제거한다.

    운영 검색은 여러 채널 병합으로 같은 청크가 2회 이상 등장할 수 있는데, 순위·nDCG는
    사용자가 실제 보는 '중복 제거된 순위' 기준으로 계산해야 한다. 중복을 남기면
    (a) nDCG의 DCG가 이중 계산되어 값이 1.0을 초과하고, (b) 뒤 정답의 순위가 밀린다.
    (설계서 C1) — 모든 순위/집합 지표는 dedup 후 top-k를 자른다.
    """
    seen: Set[str] = set()
    out: List[str] = []
    for cid in ids:
        if cid not in seen:
            seen.add(cid)
            out.append(cid)
    return out


def _validate_cutoff(k: int) -> None:
    """잘못된 cutoff가 Python 음수 슬라이싱으로 계산되지 않게 차단한다."""
    if k <= 0:
        raise ValueError("평가 cutoff는 1 이상이어야 합니다")


# ── 검색 지표 수식 ──────────────────────────────────────

# Hit@k: 상위 k개 안에 정답이 1개라도 있으면 1.0, 아니면 0.0
def hit_at_k(
    retrieved_ids: Sequence[str], gold_ids: Set[str], k: int
) -> Optional[float]:
    """상위 k개(중복 제거 후) 안에 정답이 1개라도 있으면 1.0, 아니면 0.0."""
    _validate_cutoff(k)
    if not gold_ids:
        return None
    deduped = _dedup_preserve_order(retrieved_ids)
    return 1.0 if any(cid in gold_ids for cid in deduped[:k]) else 0.0


# Recall@k: 전체 정답 중 상위 k개 안에서 찾은 정답의 비율
def recall_at_k(
    retrieved_ids: Sequence[str], gold_ids: Set[str], k: int   # 검색된 문서 ID 목록, 반드시 찾아야 하는 정답 문서 ID 집합, 상위 k까지 평가할지
) -> Optional[float]:
    """상위 k개(중복 제거 후)가 커버한 정답 비율 (멀티홉 gold 다건 대응)."""
    _validate_cutoff(k)
    if not gold_ids:
        return None
    # 중복 ID 제거하되 순서 유지
    deduped = _dedup_preserve_order(retrieved_ids)
    found = sum(1 for cid in deduped[:k] if cid in gold_ids)
    return found / len(gold_ids)   # 찾은 정답 개수 / 전체 정답 개수


# Reciprocal Rank: 가장 먼저 발견된 정답의 순위에 역수를 적용한 값 (1위=1.0, 2위=0.5, 미검출=0.0)
def reciprocal_rank(
    retrieved_ids: Sequence[str], gold_ids: Set[str], k: Optional[int] = None
) -> Optional[float]:
    """첫 번째 정답의 역순위(중복 제거 순위 기준). 미검출 시 0.0."""
    if k is not None:
        _validate_cutoff(k)
    if not gold_ids:
        return None
    deduped = _dedup_preserve_order(retrieved_ids)
    ranked = deduped[:k] if k is not None else deduped
    for rank, cid in enumerate(ranked, start=1):
        if cid in gold_ids:
            return 1.0 / rank
    return 0.0


# NDCG@k: 상위 k개의 정답 개수와 순위를 함께 평가한 값 (정답이 상위에 많을수록 1.0에 가까움)
def ndcg_at_k(
    retrieved_ids: Sequence[str], gold_ids: Set[str], k: int
) -> Optional[float]:
    """이진 관련도(rel=1) NDCG@k. 중복 제거 후 계산해 DCG 이중 계산을 방지한다."""
    _validate_cutoff(k)
    if not gold_ids:
        return None
    deduped = _dedup_preserve_order(retrieved_ids)
    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, cid in enumerate(deduped[:k], start=1)
        if cid in gold_ids
    )
    ideal_hits = min(len(gold_ids), k)
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return dcg / idcg if idcg > 0 else 0.0


def gold_ranks(retrieved_ids: Sequence[str], gold_ids: Set[str]) -> List[int]:
    """정답 청크들의 검색 순위 목록 (중복 제거 후 1-based, 미검출 정답은 제외)."""
    deduped = _dedup_preserve_order(retrieved_ids)
    return [
        rank for rank, cid in enumerate(deduped, start=1) if cid in gold_ids
    ]


def first_rank(
    retrieved_ids: Sequence[str], gold_ids: Set[str], k: Optional[int] = None
) -> Optional[int]:
    """첫 번째 정답의 1-based 순위(중복 제거 후). k가 주어지면 top-k 밖 정답은 제외한다."""
    if k is not None:
        _validate_cutoff(k)
    deduped = _dedup_preserve_order(retrieved_ids)
    ranked = deduped[:k] if k is not None else deduped
    for rank, cid in enumerate(ranked, start=1):
        if cid in gold_ids:
            return rank
    return None


def compute_channel_metrics(
    retrieved_ids: Sequence[str],
    gold_ids: Set[str],
    k_values: Sequence[int] = (1, 3, 5, 10),
) -> Dict[str, Any]:
    """한 채널의 검색 결과에 대한 전체 지표를 계산한다."""
    for k in k_values:
        _validate_cutoff(k)

    metrics: Dict[str, Any] = {}
    for k in k_values:
        hit = hit_at_k(retrieved_ids, gold_ids, k)
        metrics[f"hit@{k}"] = hit
        # 검색 실패율 — top-k에서 정답을 하나도 못 찾은 질문이면 1.0. gold가 없으면
        # None(집계 분모 제외). 항목별 평균 = 완전 실패 질문 비율(핵심 KPI ④, 낮을수록 좋음).
        metrics[f"fail@{k}"] = None if hit is None else 1.0 - hit
        metrics[f"recall@{k}"] = recall_at_k(retrieved_ids, gold_ids, k)
        metrics[f"ndcg@{k}"] = ndcg_at_k(retrieved_ids, gold_ids, k)
        # C2 — MRR을 K별로 산출한다. 기존 단일 rr은 max_k 고정(=MRR@10)이라 화면의
        # "MRR@5" 라벨과 불일치했다. rr@5 등 K별 값을 명시적으로 제공한다.
        metrics[f"rr@{k}"] = reciprocal_rank(retrieved_ids, gold_ids, k)
    max_k = max(k_values) if k_values else None
    metrics["rr"] = reciprocal_rank(retrieved_ids, gold_ids, max_k)  # 하위호환(=rr@max_k)
    metrics["gold_ranks"] = gold_ranks(retrieved_ids, gold_ids)
    metrics["evidence_rank"] = first_rank(retrieved_ids, gold_ids, max_k)
    deduped = _dedup_preserve_order(retrieved_ids)
    metrics["evidence_count"] = (
        len(gold_ids & set(deduped[:max_k])) if gold_ids and max_k else 0
    )
    metrics["total_retrieved"] = len(retrieved_ids)
    metrics["top1_is_relevant"] = (
        (bool(retrieved_ids) and retrieved_ids[0] in gold_ids) if gold_ids else None
    )
    return metrics


def aggregate_mean(per_item_values: Sequence[float]) -> float:
    """항목별 지표 평균 (빈 리스트는 0.0)."""
    if not per_item_values:
        return 0.0
    return sum(per_item_values) / len(per_item_values)


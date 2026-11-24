# 2026.11.18(sooyeon.choi) 추가 - 검색 완전성 Recall@10 계산 (설계 7.3, F-08·F-09, 시험 항목 1)
"""질의별 정답 집합 = 제외되지 않은 근거들의 확정 청크 ID 합집합.

- 적중 = 정답 청크 1개 이상이 상위 k(중복 제거)에 있으면 1 (retrieval_metrics.hit_at_k 재사용)
- basis: retrieved(재랭킹 전, 시험 기본) | reranked(재랭킹 후) — 저장값으로 재계산, 재실행 불필요
- 2026.11.19(sooyeon.choi) 수정 - 분모 = 전체 시험 질의 수(합의서 시험 1·2 계산식).
  검색 단계 오류와 정답이 없거나 모두 '제외'인 질의는 0으로 센다. 답변 오류는 검색 성과와 분리한다.
  (evaluated = 정답이 확정된 질의 수, 참고용)
- 실행 당시 문서 버전(doc_versions_json)과 정답 청크의 버전이 다르면 version_mismatch 표시.
  2026.11.19(sooyeon.choi) 수정 - 청크ID가 포인트 ID(UUID)라 버전은 chunk_versions(DB 조회 결과)로 확인
- 2026.11.18(sooyeon.choi) 추가 - NDCG@5(시험 항목 2): 재랭킹 후 상위 5(중복 제거), 이진 관련도.
  basis와 무관하게 항상 재랭킹 결과 기준. 재랭킹 오류·비활성화·정답 미확정은 0(분모 = 전체 질의 수).
"""

from typing import Any, Dict, List, Optional, Set

from app.evaluation.metrics.retrieval_metrics import first_rank, hit_at_k, ndcg_at_k

BASIS_FIELDS = {"retrieved": "retrieved_top_json", "reranked": "reranked_top_json"}


def gold_sets(gold_rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """{query_key: {ids:set, excluded:bool}} — 근거가 모두 제외면 excluded."""
    output: Dict[str, Dict[str, Any]] = {}
    for row in gold_rows:
        entry = output.setdefault(row["query_key"], {"ids": set(), "all_excluded": True})
        if row.get("match_status") == "excluded":
            continue
        entry["all_excluded"] = False
        entry["ids"].update(row.get("confirmed_ids") or [])
    return output


def compute_recall(
    items: List[Dict[str, Any]],
    gold_rows: List[Dict[str, Any]],
    *,
    basis: str = "retrieved",
    k: int = 10,
    doc_versions: Optional[Dict[str, int]] = None,
    ndcg_k: int = 5,
    chunk_versions: Optional[Dict[str, tuple]] = None,
) -> Dict[str, Any]:
    if basis not in BASIS_FIELDS:
        raise ValueError("basis는 retrieved 또는 reranked")
    golds = gold_sets(gold_rows)
    doc_versions = doc_versions or {}
    chunk_versions = chunk_versions or {}
    per_query: Dict[str, Dict[str, Any]] = {}
    hits = evaluated = excluded = errors = mismatched = 0
    ndcg_sum = 0.0

    for item in items:
        key = item["query_key"]
        gold = golds.get(key)
        if not gold or gold["all_excluded"] or not gold["ids"]:
            excluded += 1
            per_query[key] = {"hit": 0, "rank": None, "ndcg": 0.0, "reason": "excluded" if gold else "no_gold"}
            continue
        mismatch = any(
            (ver := chunk_versions.get(cid)) is not None
            and str(ver[0]) in doc_versions
            and doc_versions[str(ver[0])] != ver[1]
            for cid in gold["ids"]
        )
        mismatched += int(mismatch)
        evaluated += 1
        if item.get("status") != "ok":
            errors += 1
        stages = (item.get("timing_json") or {}).get("stage_statuses") or {}

        def stage_ok(stage: str, field: str) -> bool:
            status = stages.get(stage)
            if status is not None:
                return status in ("ok", "empty")
            # 기존 저장 결과는 단계 상태가 없으므로 결과 존재 여부로 보완한다.
            return item.get("status") == "ok" or bool(item.get(field))

        retrieval_ok = stage_ok("retrieval", "retrieved_top_json")
        rerank_ok = stage_ok("rerank", "reranked_top_json")
        basis_ok = retrieval_ok if basis == "retrieved" else rerank_ok
        ranked: List[str] = [
            r.get("chunk_id") for r in (item.get(BASIS_FIELDS[basis]) or []) if r.get("chunk_id")
        ]
        hit = hit_at_k(ranked, gold["ids"], k) if basis_ok else 0.0
        hits += int(hit or 0)
        reranked_ids = [r.get("chunk_id") for r in (item.get("reranked_top_json") or []) if r.get("chunk_id")]
        ndcg = (ndcg_at_k(reranked_ids, gold["ids"], ndcg_k) or 0.0) if rerank_ok else 0.0
        ndcg_sum += ndcg
        per_query[key] = {
            "hit": int(hit or 0),
            "rank": first_rank(ranked, gold["ids"], k) if basis_ok else None,
            "ndcg": round(ndcg, 4),
            "reason": None if basis_ok else "retrieval_error" if basis == "retrieved" else "rerank_error",
            "version_mismatch": mismatch,
        }

    total = len(items)
    return {
        "basis": basis,
        "k": k,
        "value": round(hits / total, 4) if total else None,
        "ndcg_k": ndcg_k,
        "ndcg": round(ndcg_sum / total, 4) if total else None,
        "hit": hits,
        "total": total,
        "evaluated": evaluated,
        "excluded": excluded,
        "item_errors": errors,
        "version_mismatch": mismatched,
        "per_query": per_query,
    }


def summary_view(result: Dict[str, Any]) -> Dict[str, Any]:
    """작업 요약용(질의별 목록 제외)."""
    return {key: value for key, value in result.items() if key != "per_query"}


def parse_chunk_ids(value: Any) -> List[str]:
    """검토 Excel의 확정 청크ID 칸: 쉼표·줄바꿈·공백 구분."""
    if value is None:
        return []
    text = str(value).replace("，", ",")
    ids: List[str] = []
    seen: Set[str] = set()
    for token in text.replace("\n", ",").replace(";", ",").split(","):
        for part in token.split():
            part = part.strip()
            if part and part not in seen:
                seen.add(part)
                ids.append(part)
    return ids

"""
인용(citation) 단계 평가기.

format_citations 결과와 답변 본문을 함께 평가한다.

구현 주의사항:
  citations 딕셔너리에는 chunk_id가 없다.
  citation_id(1-based)가 context_chunks의 인덱스와 대응하므로
  context_chunks[citation_id - 1]로 chunk_id를 역추적한다.
"""

from typing import Dict, List, Set

from app.utils.citation_parser import extract_citation_ids
from offline_evaluation.dataset.schema import GoldenRecord
from offline_evaluation.evaluators.base import EvalResult

_SKIP_BEHAVIORS = {"guardrail", "permission_denied"}


def evaluate(record: GoldenRecord, result: EvalResult) -> Dict:
    """citation 단계 지표를 계산해 반환한다.

    Returns:
        skipped                : True면 이 케이스는 citation 평가 대상이 아님
        citation_count         : 답변에서 추출된 [N] 인용 수 (중복 포함)
        unique_citation_count  : 고유 [N] 인용 수
        all_numbers_valid      : 모든 [N]이 citations 목록 범위 안에 있는지
        citation_relevance     : citations 중 expected_evidence chunk인 비율 (0.0~1.0)
        missing_citation       : answer 케이스인데 [N]이 하나도 없는 경우
    """
    behavior = record["expected_behavior"]

    if behavior in _SKIP_BEHAVIORS:
        return {"skipped": True, "reason": behavior}

    answer = result.get("generated_answer") or ""
    citations: List[Dict] = result.get("citations") or []
    # 2026.07.10(sooyeon.choi) 수정 - 운영과 동일한 parser 및 실제 컨텍스트 매핑 기준 사용
    context_chunks = result.get("context_chunks") or []

    # 답변에서 [N] 번호 추출
    cited_numbers = extract_citation_ids(answer)
    unique_cited = set(cited_numbers)
    citation_ids = {
        int(c["citation_id"])
        for c in citations
        if c.get("citation_id") is not None
    }

    # 2026.07.10(sooyeon.choi) 수정 - 배열 길이가 아닌 실제 citation_id 존재 여부 검증
    all_numbers_valid = unique_cited <= citation_ids

    # citation_id → chunk_id 역추적 후 expected_evidence와 비교
    relevant_chunk_ids: Set[str] = {e["chunk_id"] for e in record["expected_evidence"]}
    cited_chunk_ids: Set[str] = set()
    for c in citations:
        cid = c.get("citation_id")
        if cid is None:
            continue
        cid = int(cid)
        if 1 <= cid <= len(context_chunks):
            cited_chunk_ids.add(context_chunks[cid - 1]["chunk_id"])

    citation_relevance = (
        len(cited_chunk_ids & relevant_chunk_ids) / len(cited_chunk_ids)
        if cited_chunk_ids else 0.0
    )

    # answer 케이스인데 인용이 전혀 없는 경우
    missing_citation = (
        behavior == "answer"
        and len(relevant_chunk_ids) > 0
        and len(cited_numbers) == 0
    )

    return {
        "skipped": False,
        "citation_count": len(cited_numbers),
        "unique_citation_count": len(unique_cited),
        "all_numbers_valid": all_numbers_valid,
        "citation_relevance": citation_relevance,
        "missing_citation": missing_citation,
    }

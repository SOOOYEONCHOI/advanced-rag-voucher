"""Citation 정확도 지표 — 청크 단위 Correctness·Completeness (순수 함수).

2026.11.17(sooyeon.choi) 수정 - 공식 지표를 correctness·completeness 2종으로 정리
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set

from app.utils.citation_parser import extract_citation_ids


_SKIP_BEHAVIORS = {"guardrail", "permission_denied", "not_enough_info"}


@dataclass(frozen=True)
class CitationAnalysis:
    """답변 citation 번호를 실제 청크·문서 ID로 해석한 공통 분석 결과."""

    cited_numbers: List[int]
    unique_cited_numbers: List[int]
    valid_numbers: List[int]
    invalid_numbers: List[int]
    cited_chunk_ids: List[str]
    cited_document_ids: List[str]
    matched_gold_chunk_ids: List[str]
    missing_gold_chunk_ids: List[str]
    matched_gold_document_ids: List[str]
    missing_gold_document_ids: List[str]


def _dedup_preserve_order(values: List[Any]) -> List[Any]:
    return list(dict.fromkeys(values))


def analyze_citations(
    *,
    answer: str,
    citations: List[Dict[str, Any]],
    context_chunks: List[Dict[str, Any]],
    gold_chunk_ids: Set[str],
    gold_document_ids: Set[str],
) -> CitationAnalysis:
    """citation 번호를 직접 저장된 ID에 매핑하고 안정적인 순서로 진단한다."""
    cited_numbers = extract_citation_ids(answer)
    unique_numbers = _dedup_preserve_order(cited_numbers)

    # [N]은 LLM에 전달된 context_chunks의 1-based 순번이다. format_citations의
    # 메타데이터가 일부 유실돼도 유효한 [N]을 실제 청크로 복구할 수 있게 컨텍스트를
    # 기본 매핑으로 사용하고, citation의 명시 ID로 보완한다.
    citation_map: Dict[int, Dict[str, str]] = {
        index: {
            "chunk_id": str(chunk.get("chunk_id") or ""),
            "document_id": str(chunk.get("document_id") or ""),
        }
        for index, chunk in enumerate(context_chunks, start=1)
        if chunk.get("chunk_id")
    }
    for citation in citations:
        raw_id = citation.get("citation_id")
        if raw_id is None:
            continue
        citation_id = int(raw_id)
        chunk_id = citation.get("chunk_id") or ""
        document_id = citation.get("document_id") or ""
        if 1 <= citation_id <= len(context_chunks):
            context_chunk = context_chunks[citation_id - 1]
            chunk_id = chunk_id or context_chunk.get("chunk_id") or ""
            document_id = document_id or context_chunk.get("document_id") or ""
        if chunk_id:
            citation_map[citation_id] = {
                "chunk_id": str(chunk_id),
                "document_id": str(document_id) if document_id else "",
            }

    valid_numbers = [number for number in unique_numbers if number in citation_map]
    invalid_numbers = [number for number in unique_numbers if number not in citation_map]
    cited_chunk_ids = _dedup_preserve_order([
        citation_map[number]["chunk_id"] for number in valid_numbers
    ])
    cited_document_ids = _dedup_preserve_order([
        citation_map[number]["document_id"]
        for number in valid_numbers
        if citation_map[number]["document_id"]
    ])

    return CitationAnalysis(
        cited_numbers=cited_numbers,
        unique_cited_numbers=unique_numbers,
        valid_numbers=valid_numbers,
        invalid_numbers=invalid_numbers,
        cited_chunk_ids=cited_chunk_ids,
        cited_document_ids=cited_document_ids,
        matched_gold_chunk_ids=[cid for cid in cited_chunk_ids if cid in gold_chunk_ids],
        missing_gold_chunk_ids=sorted(gold_chunk_ids - set(cited_chunk_ids)),
        matched_gold_document_ids=[
            did for did in cited_document_ids if did in gold_document_ids
        ],
        missing_gold_document_ids=sorted(
            gold_document_ids - set(cited_document_ids)
        ),
    )


# 2026.11.17(sooyeon.choi) 삭제 - 사용처 없는 citation_precision_recall(), map_cited_chunk_ids()
#   (citation에 chunk_id가 항상 있어 텍스트 역추적이 필요 없음, analyze_citations로 대체)


def compute_evaluation_citation_metrics(
    *,
    answer: str,
    citations: List[Dict[str, Any]],
    context_chunks: List[Dict[str, Any]],
    gold_chunk_ids: Set[str],
    expected_behavior: str,
    gold_document_ids: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """규칙 기반 Citation Correctness와 Citation Completeness를 계산한다.

    답변의 ``[N]`` 인용 번호를 citation의 chunk_id로 변환한 뒤, 중복을 제거한
    인용 청크 집합 C와 정답 청크 집합 G를 비교한다.

    - Citation Correctness = |C ∩ G| / (|C| + 유효하지 않은 고유 인용 번호 수)
      즉, 인용한 근거 중 정답 근거가 차지하는 비율이며 잘못된 인용 번호도 감점한다.
    - Citation Completeness = |C ∩ G| / |G|
      즉, 반드시 인용해야 할 정답 근거를 얼마나 빠짐없이 인용했는지 나타낸다.

    정답 청크가 없으면 두 지표는 ``None``이며, 평가 제외 동작이면 전체 계산을
    건너뛴다. 같은 인용 번호나 같은 청크의 반복 인용은 한 번만 계산한다.
    """
    if expected_behavior in _SKIP_BEHAVIORS:
        return {"skipped": True, "reason": expected_behavior}

    gold_document_ids = gold_document_ids or set()
    analysis = analyze_citations(
        answer=answer,
        citations=citations,
        context_chunks=context_chunks,
        gold_chunk_ids=gold_chunk_ids,
        gold_document_ids=gold_document_ids,
    )
    true_positive = len(analysis.matched_gold_chunk_ids)

    # Correctness = TP / (고유 인용 청크 수 + 유효하지 않은 고유 인용 번호 수)
    correctness_denominator = (
        len(analysis.cited_chunk_ids) + len(analysis.invalid_numbers)
    )
    correctness = (
        true_positive / correctness_denominator
        if gold_chunk_ids and correctness_denominator
        else 0.0 if gold_chunk_ids
        else None
    )

    # Completeness = TP / 전체 정답 청크 수
    completeness = (
        true_positive / len(gold_chunk_ids)
        if gold_chunk_ids
        else None
    )
    # 2026.11.17(sooyeon.choi) 삭제 - citation_f1·citation_validity·document_*·doc_* 별칭·citation_relevance
    #   (citation_relevance는 잘못된 번호를 빼고 계산해 correctness와 값만 다른 중복 지표였음)
    return {
        "skipped": False,
        "citation_count": len(analysis.cited_numbers),
        "unique_citation_count": len(analysis.unique_cited_numbers),
        "all_numbers_valid": not analysis.invalid_numbers,
        "correctness": correctness,
        "completeness": completeness,
        "invalid_citation_count": len(analysis.invalid_numbers),
        "cited_numbers": analysis.unique_cited_numbers,
        "valid_numbers": analysis.valid_numbers,
        "invalid_numbers": analysis.invalid_numbers,
        "cited_chunk_ids": analysis.cited_chunk_ids,
        "cited_document_ids": analysis.cited_document_ids,
        "matched_gold_chunk_ids": analysis.matched_gold_chunk_ids,
        "missing_gold_chunk_ids": analysis.missing_gold_chunk_ids,
        "matched_gold_document_ids": analysis.matched_gold_document_ids,
        "missing_gold_document_ids": analysis.missing_gold_document_ids,
        "missing_citation": (
            expected_behavior == "answer"
            and bool(gold_chunk_ids)
            and not analysis.cited_numbers
        ),
    }

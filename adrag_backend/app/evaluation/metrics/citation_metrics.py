"""Citation 정확도 지표 — 문서/청크 단위 Precision·Recall·F1 (순수 함수).

"""

import re
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


def citation_precision_recall(
    cited_ids: List[str],
    gold_ids: Set[str],
    retrieved_ids: Optional[Set[str]] = None,
    prefix: str = "doc",
) -> Dict[str, Optional[float]]:
    """인용 ID 목록과 정답 ID 집합의 엄격한 Precision/Recall/F1을 계산한다.

    중복을 제거한 인용 집합을 C, 정답 집합을 G라고 할 때:
    - Precision = |C ∩ G| / |C|
    - Recall = |C ∩ G| / |G|
    - F1 = 2 × Precision × Recall / (Precision + Recall)

    ``retrieved_ids``는 기존 호출부와의 호환성을 위해 유지하며 계산에는 사용하지 않는다.
    """
    cited_set = {c for c in cited_ids if c}
    if not gold_ids:
        return {
            f"{prefix}_precision": None,
            f"{prefix}_recall": None,
            f"{prefix}_f1": None,
        }
    if not cited_set:
        return {f"{prefix}_precision": 0.0, f"{prefix}_recall": 0.0, f"{prefix}_f1": 0.0}

    true_positive = len(cited_set & gold_ids)
    precision = true_positive / len(cited_set)
    recall = true_positive / len(gold_ids)
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )
    return {
        f"{prefix}_precision": precision,
        f"{prefix}_recall": recall,
        f"{prefix}_f1": f1,
    }


_REVISION_MARKUP_PATTERN = re.compile(r'[<>]')


def _normalize_for_match(text: str) -> str:
    """청크 텍스트 매칭용 정규화 — 개정일자 등에 붙는 <> 표기, 공백 차이를 흡수한다."""
    return re.sub(r'\s+', '', _REVISION_MARKUP_PATTERN.sub('', text))


def map_cited_chunk_ids(
    referenced_citations: List[Dict[str, Any]],
    reranked_chunks: List[Dict[str, Any]],
) -> List[str]:
    """답변에서 참조된 citation을 실제 chunk_id 목록으로 변환한다.

    citation에 ``chunk_id``가 있으면 그대로 사용한다. 이전 데이터처럼 ``chunk_id``가
    없으면 citation의 ``chunk_text``를 reranked chunk의 text와 비교해 역추적한다.
    텍스트 비교 시 ``<개정 ...>`` 같은 표기와 공백 차이를 정규화한다.
    """
    cited_chunk_ids: List[str] = []
    for citation in referenced_citations:
        chunk_id = citation.get("chunk_id")
        if chunk_id:
            cited_chunk_ids.append(chunk_id)
            continue
        snippet = _normalize_for_match((citation.get("chunk_text") or "").rstrip("…. ")[:200])
        if not snippet:
            continue
        for chunk in reranked_chunks:
            text = _normalize_for_match(chunk.get("text") or "")
            if text.startswith(snippet) or snippet in text[:600]:
                cited_chunk_ids.append(chunk.get("chunk_id", ""))
                break
    return cited_chunk_ids


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
    citation_f1 = (
        2 * correctness * completeness / (correctness + completeness)
        if correctness is not None
        and completeness is not None
        and correctness + completeness > 0
        else 0.0
        if correctness == 0.0 and completeness == 0.0
        else None
    )
    citation_validity = (
        len(analysis.valid_numbers) / len(analysis.unique_cited_numbers)
        if analysis.unique_cited_numbers else None
    )

    document_true_positive = len(analysis.matched_gold_document_ids)
    document_denominator = (
        len(analysis.cited_document_ids) + len(analysis.invalid_numbers)
    )
    document_correctness = (
        document_true_positive / document_denominator
        if gold_document_ids and document_denominator
        else 0.0 if gold_document_ids
        else None
    )
    document_completeness = (
        document_true_positive / len(gold_document_ids)
        if gold_document_ids else None
    )
    document_f1 = (
        2 * document_correctness * document_completeness
        / (document_correctness + document_completeness)
        if document_correctness is not None
        and document_completeness is not None
        and document_correctness + document_completeness > 0
        else 0.0
        if document_correctness == 0.0 and document_completeness == 0.0
        else None
    )

    relevance = (
        true_positive / len(analysis.cited_chunk_ids)
        if analysis.cited_chunk_ids else 0.0
    )
    return {
        "skipped": False,
        "citation_count": len(analysis.cited_numbers),
        "unique_citation_count": len(analysis.unique_cited_numbers),
        "all_numbers_valid": not analysis.invalid_numbers,
        "correctness": correctness,
        "completeness": completeness,
        "citation_f1": citation_f1,
        "citation_validity": citation_validity,
        "document_correctness": document_correctness,
        "document_completeness": document_completeness,
        "document_f1": document_f1,
        # 상세 화면의 기존 doc_* 참조를 위한 조회 호환 alias.
        "doc_precision": document_correctness,
        "doc_recall": document_completeness,
        "doc_f1": document_f1,
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
        "citation_relevance": relevance,
        "missing_citation": (
            expected_behavior == "answer"
            and bool(gold_chunk_ids)
            and not analysis.cited_numbers
        ),
    }

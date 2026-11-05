"""Answer Correctness v2 — 문장 정렬 기반 F1 (Gold Coverage × System Precision).

문장 단위로 분리 후 양방향 코사인 유사도 행렬을 구성하여
Gold Coverage와 System Precision의 조화 평균(F1)을 반환한다.
전체 문서 임베딩 희석 문제를 해결하며 길이 차이에 강인하다.
"""

import re
from typing import Dict, List, Sequence

from app.evaluation.metrics.similarity import clamp_similarity, cosine_similarity


_BULLET_PREFIX = re.compile(r"^\s*(?:[-*+]\s+|\(\d+\)\s*|\d+[.)]\s*)")
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")
_MARKDOWN_HEADING = re.compile(r"^\s*#{1,6}\s+")
_TABLE_SEPARATOR = re.compile(r"^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*$")
_BOILERPLATE = re.compile(r"(?:다음과 같습니다|정리하면 다음과 같습니다)\.?$")


def split_sentences_ko_rule_v1(
    text: str,
    *,
    min_sentence_chars: int = 10,
    max_sentences: int = 30,
) -> List[str]:
    """개행·종결부호를 기준으로 분리하고 짧은 조각을 인접 문장에 병합한다."""
    if not isinstance(text, str) or not text.strip():
        return []
    if min_sentence_chars < 1 or max_sentences < 1:
        raise ValueError("sentence split limits must be positive")

    fragments: List[str] = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        cleaned = _BULLET_PREFIX.sub("", line).strip()
        if not cleaned:
            continue
        fragments.extend(
            part.strip() for part in _SENTENCE_BOUNDARY.split(cleaned) if part.strip()
        )

    merged: List[str] = []
    pending = ""
    for fragment in fragments:
        if pending:
            fragment = f"{pending} {fragment}".strip()
            pending = ""
        if len(fragment) < min_sentence_chars:
            if merged:
                merged[-1] = f"{merged[-1]} {fragment}".strip()
            else:
                pending = fragment
        else:
            merged.append(fragment)
    if pending:
        if merged:
            merged[-1] = f"{merged[-1]} {pending}".strip()
        else:
            merged.append(pending)

    while len(merged) > max_sentences:
        tail = merged.pop()
        merged[-1] = f"{merged[-1]} {tail}".strip()
    return merged


def split_sentences_ko_rule_v2(
    text: str,
    *,
    min_sentence_chars: int = 10,
    max_sentences: int = 30,
) -> List[str]:
    """제목·표 구분선·도입 문구를 제외하되 목록과 표의 실제 내용은 보존한다."""
    content_lines: List[str] = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = line.strip()
        if not stripped or _MARKDOWN_HEADING.match(stripped) or _TABLE_SEPARATOR.match(stripped):
            continue
        cleaned = stripped.strip("|").replace("|", " ")
        cleaned = re.sub(r"[*_`]+", "", cleaned).strip()
        if not cleaned or _BOILERPLATE.search(cleaned):
            continue
        content_lines.append(cleaned)
    return split_sentences_ko_rule_v1(
        "\n".join(content_lines),
        min_sentence_chars=min_sentence_chars,
        max_sentences=max_sentences,
    )


def deduplicate_semantic_sentences(
    sentences: Sequence[str],
    embeddings: Dict[str, Sequence[float]],
    *,
    threshold: float = 0.92,
) -> tuple[List[str], List[int]]:
    """의미 중복 문장을 제거하여 precision 이중 차감을 방지한다."""
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("dedupe threshold must be between 0 and 1")
    kept: List[str] = []
    removed_indices: List[int] = []
    for index, sentence in enumerate(sentences):
        is_duplicate = any(
            clamp_similarity(cosine_similarity(embeddings[sentence], embeddings[existing]))
            >= threshold
            for existing in kept
        )
        if is_duplicate:
            removed_indices.append(index)
        else:
            kept.append(sentence)
    return kept, removed_indices


def compute_sentence_alignment(
    gold_sentences: Sequence[str],
    system_sentences: Sequence[str],
    embeddings: Dict[str, Sequence[float]],
    *,
    dedupe_threshold: float = 0.92,
    precision_candidate_ratio: int = 3,
) -> Dict[str, object]:
    """의미 중복을 제거한 뒤 Coverage와 제한된 Precision의 F1을 반환한다."""
    if precision_candidate_ratio < 1:
        raise ValueError("precision candidate ratio must be positive")
    deduped_gold, removed_gold_indices = deduplicate_semantic_sentences(
        gold_sentences, embeddings, threshold=dedupe_threshold
    )
    deduped_system, removed_system_indices = deduplicate_semantic_sentences(
        system_sentences, embeddings, threshold=dedupe_threshold
    )
    matrix = [
        [
            clamp_similarity(cosine_similarity(embeddings[gold], embeddings[system]))
            for system in deduped_system
        ]
        for gold in deduped_gold
    ]

    gold_matches = []
    gold_best = []
    for gold_index, row in enumerate(matrix):
        system_index = max(range(len(row)), key=row.__getitem__)
        score = row[system_index]
        gold_best.append(score)
        gold_matches.append({
            "gold_index": gold_index,
            "system_index": system_index,
            "score": score,
        })

    system_matches = []
    system_best = []
    for system_index in range(len(deduped_system)):
        column = [matrix[gold_index][system_index] for gold_index in range(len(deduped_gold))]
        gold_index = max(range(len(column)), key=column.__getitem__)
        score = column[gold_index]
        system_best.append(score)
        system_matches.append({
            "system_index": system_index,
            "gold_index": gold_index,
            "score": score,
        })

    gold_coverage = sum(gold_best) / len(gold_best)
    precision_candidate_count = min(
        len(system_best), len(deduped_gold) * precision_candidate_ratio
    )
    precision_scores = sorted(system_best, reverse=True)[:precision_candidate_count]
    system_precision = sum(precision_scores) / len(precision_scores)
    denominator = gold_coverage + system_precision
    f1 = 0.0 if denominator == 0 else (
        2 * gold_coverage * system_precision / denominator
    )
    return {
        "value": f1,
        "gold_coverage": gold_coverage,
        "system_precision": system_precision,
        "gold_matches": gold_matches,
        "system_matches": system_matches,
        "pair_count": len(deduped_gold) * len(deduped_system),
        "deduped_gold_sentence_count": len(deduped_gold),
        "deduped_system_sentence_count": len(deduped_system),
        "removed_gold_sentence_indices": removed_gold_indices,
        "removed_system_sentence_indices": removed_system_indices,
        "precision_candidate_count": precision_candidate_count,
    }
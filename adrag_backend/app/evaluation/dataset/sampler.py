"""청크 샘플링 — 문서/섹션 층화 샘플링 + 멀티홉용 인접 청크 페어.

(reference app/evaluation/dataset/sampler.py 이식)
"""

import random
from collections import defaultdict
from typing import Any, Dict, List, Tuple


def sample_chunks(
    chunks: List[Dict[str, Any]],
    *,
    target_count: int = 50,
    max_per_doc: int = 5,
    per_doc_limits: Dict[str, int] | None = None,
    min_chunk_chars: int = 200,
    seed: int | None = None,
) -> List[Dict[str, Any]]:
    """단일 청크 샘플을 층화 추출한다.

    - per_doc_limits가 주어지면 문서별 청크 수 비율 기반 상한 사용
    - per_doc_limits가 없으면 max_per_doc 고정값 사용
    - 같은 섹션(header_path) 중복 회피
    - 텍스트 길이 하한 필터
    """
    rng = random.Random(seed)

    eligible = [
        c for c in chunks
        if len((c.get("text") or "").strip()) >= min_chunk_chars
    ]

    by_doc: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for chunk in eligible:
        by_doc[chunk.get("document_id", "?")].append(chunk)

    selected: List[Dict[str, Any]] = []
    doc_ids = list(by_doc.keys())
    rng.shuffle(doc_ids)

    # 라운드로빈: 문서마다 1개씩 뽑아 다양성 확보 → 상한 도달 문서는 제외
    picked_per_doc: Dict[str, int] = defaultdict(int)
    used_sections: Dict[str, set] = defaultdict(set)

    progress = True
    while len(selected) < target_count and progress:
        progress = False
        for doc_id in doc_ids:
            if len(selected) >= target_count:
                break
            limit = per_doc_limits.get(doc_id, max_per_doc) if per_doc_limits else max_per_doc
            if picked_per_doc[doc_id] >= limit:
                continue
            pool = by_doc[doc_id]
            rng.shuffle(pool)
            for chunk in pool:
                section = str(chunk.get("header_path") or chunk.get("section_title") or "")
                if chunk in selected:
                    continue
                if section and section in used_sections[doc_id]:
                    continue
                selected.append(chunk)
                picked_per_doc[doc_id] += 1
                if section:
                    used_sections[doc_id].add(section)
                progress = True
                break

    return selected


def sample_multihop_pairs(
    chunks: List[Dict[str, Any]],
    *,
    target_count: int = 5,
    min_chunk_chars: int = 200,
    seed: int | None = None,
) -> List[Tuple[Dict[str, Any], Dict[str, Any]]]:
    """멀티홉용 인접 청크 페어를 샘플링한다.

    같은 문서 내 chunk_index가 연속인 청크 2개를 페어로 묶는다.
    """
    rng = random.Random(seed)

    by_doc: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for chunk in chunks:
        if len((chunk.get("text") or "").strip()) >= min_chunk_chars:
            by_doc[chunk.get("document_id", "?")].append(chunk)

    pairs: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    for doc_chunks in by_doc.values():
        doc_chunks.sort(key=lambda c: c.get("chunk_index", 0))
        for i in range(len(doc_chunks) - 1):
            a, b = doc_chunks[i], doc_chunks[i + 1]
            if b.get("chunk_index", 0) - a.get("chunk_index", 0) == 1:
                pairs.append((a, b))

    rng.shuffle(pairs)
    return pairs[:target_count]

# 2026.11.20(sooyeon.choi) 수정 - 합본 평가 데이터셋 (eval-merged-dataset-design-v1.0.md 4장)
"""확정된 데이터셋 여러 개의 최신 골드셋 문항을 이어 붙여 합본 문항 목록을 만든다.

- 문항은 원본 골드셋 스냅샷에서 복사한다(확정 이후 원본 수정분은 들어가지 않음).
- 문항별 source_meta_json에 검색 컬렉션(qdrant_name)·질의ID·법령 이름·원본 위치를 넣는다.
  평가 실행은 qdrant_name이 있으면 그 컬렉션에서 검색한다(지표 계산은 단독과 같음).
- 질의ID는 원본 시험 데이터셋 다운로드와 같은 규칙(접두어 + 정렬 순서)으로 계산해 저장한다.
"""

import json
from typing import Any, Dict, List

from app.evaluation.excel_exporter import _testset_sort_key, testset_query_id_prefix

MERGED_KIND = "merged"


class MergeError(ValueError):
    """합본을 만들 수 없는 입력(사용자에게 그대로 보여 줄 문구)."""


def _loads(value: Any, fallback: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback
    return fallback if value is None else value


def dataset_config(dataset: Dict[str, Any]) -> Dict[str, Any]:
    config = _loads(dataset.get("gen_config_json"), {})
    return config if isinstance(config, dict) else {}


def is_merged_dataset(dataset: Dict[str, Any]) -> bool:
    return dataset_config(dataset).get("dataset_kind") == MERGED_KIND


def law_label(dataset: Dict[str, Any]) -> str:
    """법령별 값의 구분 이름 = 원본 데이터셋의 컬렉션 표시 이름(예: 산업안전보건법)."""
    return str(dataset.get("collection_name") or dataset.get("qdrant_name") or dataset.get("name") or "")


def source_query_ids(dataset: Dict[str, Any], items: List[Dict[str, Any]]) -> Dict[Any, str]:
    """원본 시험 데이터셋 Excel과 같은 질의ID {qa_id: 질의ID}."""
    prefix = testset_query_id_prefix(dataset)
    ordered = sorted(items, key=_testset_sort_key)
    width = max(3, len(str(len(ordered))))
    return {item.get("qa_id"): f"{prefix}-{index:0{width}d}" for index, item in enumerate(ordered, start=1)}


def build_merged_items(sources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """sources: [{dataset, goldset, items(골드셋 스냅샷)}] (합칠 순서). 합본 문항 dict 목록을 반환한다."""
    merged: List[Dict[str, Any]] = []
    seen_ids: Dict[str, Dict[str, Any]] = {}
    duplicates: List[str] = []
    # 2026.11.23(sooyeon.choi) 수정 - 겹친 데이터셋 이름·접두어를 문구에 보여 줌(겹친 순서 유지)
    conflict_labels: List[str] = []
    for source in sources:
        dataset, goldset, items = source["dataset"], source["goldset"], source["items"]
        query_ids = source_query_ids(dataset, items)
        for item in sorted(items, key=_testset_sort_key):
            query_id = query_ids[item.get("qa_id")]
            if query_id in seen_ids:
                duplicates.append(query_id)
                for owner in (seen_ids[query_id], dataset):
                    label = _conflict_label(owner)
                    if label not in conflict_labels:
                        conflict_labels.append(label)
                continue
            seen_ids[query_id] = dataset
            meta = _loads(item.get("source_meta_json"), {})
            meta = dict(meta) if isinstance(meta, dict) else {}
            meta.update({
                "qdrant_name": dataset.get("qdrant_name"),
                "query_id": query_id,
                "law_label": law_label(dataset),
                "merge_order": len(merged) + 1,
                "merged_source": {
                    "dataset_id": dataset.get("dataset_id"),
                    "goldset_id": goldset.get("goldset_id"),
                    "qa_id": item.get("qa_id"),
                },
            })
            merged.append({
                "question": item.get("question") or "",
                "gold_answer": item.get("gold_answer") or "",
                "gold_chunk_ids": _loads(item.get("gold_chunk_ids"), []),
                "gold_document_ids": _loads(item.get("gold_document_ids"), []),
                "gold_chunk_texts": _loads(item.get("gold_chunk_texts"), []),
                "question_type": item.get("question_type") or "factual",
                "difficulty": item.get("difficulty") or "normal",
                "self_valid_rank": item.get("self_valid_rank"),
                "expected_behavior": item.get("expected_behavior") or "answer",
                "tags": _loads(item.get("tags"), []),
                "review_status": item.get("review_status") if item.get("review_status") in ("approved", "edited") else "approved",
                "reviewed_by": item.get("reviewed_by"),
                "source_meta": meta,
            })
    if duplicates:
        shown = ", ".join(duplicates[:10])
        more = f" 외 {len(duplicates) - 10}건" if len(duplicates) > 10 else ""
        raise MergeError(
            f"{' · '.join(conflict_labels)}의 질의ID가 겹칩니다({shown}{more}). "
            "데이터셋 목록에서 원본의 질의ID 접두어를 서로 다르게 바꾼 뒤 다시 합쳐 주세요."
        )
    return merged


def _conflict_label(dataset: Dict[str, Any]) -> str:
    """에러 문구용 '데이터셋 이름(접두어 X)'."""
    return f"{dataset.get('name') or dataset.get('dataset_id')}(접두어 {testset_query_id_prefix(dataset)})"


def merged_config(sources: List[Dict[str, Any]]) -> Dict[str, Any]:
    """합본 데이터셋 gen_config_json(원본 구성 기록)."""
    return {
        "dataset_kind": MERGED_KIND,
        "merged_from": [
            {
                "dataset_id": source["dataset"].get("dataset_id"),
                "dataset_name": source["dataset"].get("name"),
                "goldset_id": source["goldset"].get("goldset_id"),
                "goldset_version": source["goldset"].get("version"),
                "collection_name": source["dataset"].get("qdrant_name"),
                "law_label": law_label(source["dataset"]),
                "item_count": len(source["items"]),
            }
            for source in sources
        ],
    }

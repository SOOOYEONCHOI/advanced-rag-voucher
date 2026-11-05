"""답변 사진 — 후보 수집·프롬프트 블록·인용 검증 (2026.10.19).


1. 후보 수집(``collect_image_candidates``): LLM에 넘긴 컨텍스트 청크에 연결된 사진을 모은다.
   - 청크 payload ``resource_ids``(excel_ingest Step 청크·docling 스프레드시트 청크 공통)
   - excel_ingest 청크에 연결 사진이 없으면(예: 핵심 부품 List 표) 같은 시트·청크 행 범위(``source_range`` "5:12") 안의 사진
   검색 단계에서 이미 권한·활성 버전 필터를 통과한 청크의 **같은 문서** 사진만 쓰고, 문서의 현재 버전 사진만 남긴다.
   브라우저가 표시할 수 없는 형식(emf·wmf·도형 XML)·장식·양식 머리글·검수에서 "연결 안 함" 처리된 사진은 뺀다.
   정렬: 질의어가 주변 텍스트에 많이 나오는 사진 → 역할(Step 사진 > 확대도 > 도면 > …) → 컨텍스트 순서 → 같은 시트·Step → 신뢰도.
   같은 이미지(내용 해시)가 여러 곳에 배치돼 있으면 1건.
2. 프롬프트(``image_prompt_block``): 후보를 ``[IMG:ref] 설명`` 목록으로만 준다(URL·경로 없음).
3. 검증(``validate_answer_images``): 답변의 ``[IMG:ref]`` 중 후보에 있는 것만 남기고 나머지 태그는 지운다(최대 ``rag_max_images``).
   인용이 없으면 1순위 컨텍스트가 Step 청크일 때 그 Step 사진 1장, 또는 질의어가 분명히 겹치는 사진 1장을 자동 첨부(설정).
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Optional

from app.repositories.database import get_database_manager
# 2026.10.19 - 제목·역할 라벨·표시 형식은 사진 목록 API와 공용(app/services/resource_labels.py)
from app.services.resource_labels import DISPLAYABLE_MIME_TYPES, EXCLUDED_ROLES, resource_title
from app.utils.log.log import LoggingLogger

logger = LoggingLogger().getLogger(__name__)

ROLE_PRIORITY = {
    "step_photo": 0, "same_image_as_step_photo": 0, "detail_view": 1, "drawing": 2,
    "part_photo": 3, "flowchart": 4, "step_related": 5, "figure": 6,
}
IMG_TAG = re.compile(r"\[IMG:\s*([A-Za-z0-9_-]{1,64})\s*\]")
_REF_LENGTH = 6
_CONTEXT_TEXT_LIMIT = 200
_ROW_RANGE = re.compile(r"^\s*(\d+)\s*:\s*(\d+)\s*$")
_CELL_ROW = re.compile(r"(\d+)")

_RESOURCE_SQL = """
    SELECT r.resource_id, r.document_id, r.version_no, r.sheet_name, r.from_cell, r.to_cell, r.role_cd,
           r.step_no, r.step_title, r.link_confidence, r.surrounding_text, r.content_hash, r.in_print_area,
           d.original_filename
    FROM tb_spreadsheet_resources r
    JOIN tb_documents d ON d.document_id = r.document_id AND d.deleted_at IS NULL
    WHERE r.status <> 'deleted'   -- committed·analysis_* (분석 진행과 무관하게 표시)
      AND r.mime_type = ANY(?)
      AND r.review_status <> 'unlinked'
      AND (r.role_cd IS NULL OR r.role_cd <> ALL(?))
      AND (r.version_no IS NULL OR r.version_no = d.version_no)
"""


def _role_rank(role: Optional[str]) -> int:
    return ROLE_PRIORITY.get(role or "", len(ROLE_PRIORITY))


def _row_range(metadata: dict[str, Any]) -> Optional[tuple[int, int]]:
    match = _ROW_RANGE.match(str(metadata.get("source_range") or ""))
    if not match:
        return None
    start, end = int(match.group(1)), int(match.group(2))
    return (start, end) if start <= end else (end, start)


def _cell_row(cell: Optional[str]) -> Optional[int]:
    match = _CELL_ROW.search(cell or "")
    return int(match.group(1)) if match else None


def _lookup_resources(chunk: dict[str, Any], db) -> list[dict[str, Any]]:
    """청크 1개에 연결된 표시 가능한 사진 행. 청크와 같은 문서의 사진만 돌려준다."""
    metadata = chunk.get("metadata") or {}
    document_id = chunk.get("document_id") or metadata.get("document_id")
    if not document_id:
        return []
    base = (DISPLAYABLE_MIME_TYPES, sorted(EXCLUDED_ROLES))
    resource_ids = [str(r) for r in metadata.get("resource_ids") or [] if r]
    if resource_ids:
        rows = db.execute_query(
            f"{_RESOURCE_SQL} AND r.document_id = ? AND r.resource_id = ANY(?)", (*base, document_id, resource_ids)
        )
        order = {rid: i for i, rid in enumerate(resource_ids)}
        return sorted((dict(row) for row in rows), key=lambda row: order.get(row["resource_id"], len(order)))
    # 연결 사진이 없는 excel_ingest 청크(예: 핵심 부품 List 표) → 같은 시트·같은 행 범위 안의 인쇄 영역 사진
    rows_range = _row_range(metadata)
    if (metadata.get("processing_engine") == "excel_ingest" and rows_range and metadata.get("sheet_name")
            and metadata.get("version_no") is not None):
        rows = db.execute_query(
            f"{_RESOURCE_SQL} AND r.document_id = ? AND r.version_no = ? AND r.sheet_name = ? AND r.in_print_area",
            (*base, document_id, int(metadata["version_no"]), metadata["sheet_name"]),
        )
        return [
            dict(row) for row in rows
            if (row_no := _cell_row(row["from_cell"])) is not None and rows_range[0] <= row_no <= rows_range[1]
        ]
    return []


_TOKEN = re.compile(r"[0-9A-Za-z가-힣]{2,}")


def _query_match(resource: dict[str, Any], query: Optional[str]) -> int:
    """질의어가 사진의 주변 텍스트·Step 제목에 몇 개 나오는지(후보 정렬용)."""
    if not query:
        return 0
    haystack = f"{resource.get('surrounding_text') or ''} {resource.get('step_title') or ''}".lower()
    return sum(1 for token in set(_TOKEN.findall(query.lower())) if token in haystack)


def _placement_score(resource: dict[str, Any], sheet: Optional[str], step_no) -> tuple:
    """같은 시트·같은 Step 사진을 먼저, 그다음 신뢰도."""
    same_sheet = sheet is not None and resource.get("sheet_name") == sheet
    same_step = same_sheet and step_no is not None and resource.get("step_no") == step_no
    return (not same_step, not same_sheet, -(resource.get("link_confidence") or 0))


def _image_key(resource: dict[str, Any]) -> str:
    """같은 이미지(내용 해시) 판정 키. 해시가 없으면 resource_id."""
    content_hash = str(resource.get("content_hash") or "")
    return content_hash.split(":", 1)[-1] or resource["resource_id"]


def collect_image_candidates(
    chunks: Iterable[dict[str, Any]], limit: int = 8, db=None, query: Optional[str] = None
) -> list[dict[str, Any]]:
    """컨텍스트 청크(LLM에 넘긴 순서)에서 사진 후보를 모은다. DB 오류는 경고만 남기고 빈 목록."""
    if limit <= 0:
        return []
    db = db or get_database_manager()
    best: dict[str, tuple[tuple, dict[str, Any]]] = {}
    try:
        for order, chunk in enumerate(chunks):
            metadata = chunk.get("metadata") or {}
            sheet, step_no = metadata.get("sheet_name"), metadata.get("step_no")
            for resource in _lookup_resources(chunk, db):
                match = _query_match(resource, query)
                key = (-match, _role_rank(resource.get("role_cd")), order, *_placement_score(resource, sheet, step_no))
                image_key = _image_key(resource)
                current = best.get(image_key)
                if current is None or key < current[0]:
                    best[image_key] = (key, {**resource, "context_no": order + 1, "query_match": match})
    except Exception as exc:  # 사진은 부가 정보 — 답변은 계속
        logger.warning("[RAG][images] 후보 조회 실패: %s", exc)
        return []
    ordered = [(image_key, entry[1]) for image_key, entry in sorted(best.items(), key=lambda pair: pair[1][0])]
    ordered = ordered[:limit]
    candidates, used_refs = [], set()
    for image_key, resource in ordered:
        source = re.sub(r"[^0-9A-Za-z]", "", image_key) or resource["resource_id"]
        size = _REF_LENGTH
        ref = source[:size]
        while ref in used_refs and size < len(source):
            size += 2
            ref = source[:size]
        if ref in used_refs:
            ref = f"{source[:_REF_LENGTH]}{len(candidates)}"
        used_refs.add(ref)
        candidates.append({
            "ref": ref,
            "resource_id": resource["resource_id"],
            "document_id": resource["document_id"],
            "title": resource_title(resource),
            "role": resource.get("role_cd"),
            "sheet_name": resource.get("sheet_name"),
            "from_cell": resource.get("from_cell"),
            "to_cell": resource.get("to_cell"),
            "step_no": resource.get("step_no"),
            "step_title": resource.get("step_title"),
            "surrounding_text": " ".join(str(resource.get("surrounding_text") or "").split())[:_CONTEXT_TEXT_LIMIT],
            "original_filename": resource.get("original_filename"),
            "context_no": resource["context_no"],
            "query_match": resource.get("query_match", 0),
        })
    return candidates


def image_prompt_block(candidates: list[dict[str, Any]]) -> str:
    """컨텍스트 뒤에 붙일 사진 후보 목록. 후보가 없으면 빈 문자열(프롬프트 그대로)."""
    if not candidates:
        return ""
    # 2026.10.19 수정 - dev 실측: 규칙 한 줄만으로는 LLM이 태그를 거의 쓰지 않아 실제 후보 ID로 예시를 준다
    example = candidates[0]["ref"]
    lines = [
        "[관련 이미지 후보]",
        "이미지 인용 규칙:",
        f"- 답변 문장이 아래 이미지의 작업 단계·부품·도면을 설명하면 그 문장 끝 출처 번호 뒤에 [IMG:ID]를 붙인다. "
        f"(예: ...체결합니다[1][IMG:{example}].)",
        "- 같은 이미지는 한 번만 인용한다. 목록에 없는 ID는 만들지 않는다. 관련 없는 이미지는 인용하지 않는다.",
    ]
    for item in candidates:
        cell = item["from_cell"] + (f":{item['to_cell']}" if item.get("to_cell") else "") if item.get("from_cell") else ""
        lines.append(f"[IMG:{item['ref']}] {item['title']} (문서 [{item['context_no']}]{' ' + cell if cell else ''})")
    return "\n".join(lines)


def validate_answer_images(
    answer: str,
    candidates: list[dict[str, Any]],
    *,
    context_chunks: Optional[list[dict[str, Any]]] = None,
    max_images: int = 4,
    auto_step_image: bool = True,
) -> tuple[str, list[dict[str, Any]]]:
    """답변의 사진 인용을 검증한다. 반환: (후보에 없는 태그를 지운 답변, 표시할 사진 목록)."""
    by_ref = {item["ref"]: item for item in candidates}
    cited: list[dict[str, Any]] = []
    removed: list[str] = []

    def keep_or_drop(match: re.Match) -> str:
        ref = match.group(1)
        item = by_ref.get(ref)
        if item is None:
            removed.append(ref)
            return ""
        if item not in cited:
            if len(cited) >= max_images:
                return ""
            cited.append(item)
        return f"[IMG:{ref}]"

    cleaned = IMG_TAG.sub(keep_or_drop, answer or "")
    if removed:
        cleaned = re.sub(r"[ \t]+([.,。])", r"\1", re.sub(r"[ \t]{2,}", " ", cleaned))
        logger.warning("[RAG][images] 후보에 없는 사진 인용 제거: %s", removed)
    images = [{**item, "cited": True} for item in cited]
    if max_images <= 0:
        return cleaned, []
    if not images and auto_step_image and candidates and context_chunks:
        top = (context_chunks[0].get("metadata") or {})
        if top.get("step_no") is not None:
            for item in candidates:
                if (item.get("role") in ("step_photo", "same_image_as_step_photo") and item["context_no"] == 1
                        and item.get("step_no") == top.get("step_no")):
                    images.append({**item, "cited": False})
                    break
    # Step 답변이 아니어도, 질의어가 2개 이상 겹치는 사진이 하나로 분명하면 1장 첨부
    #   (예: "재생 FAN 품번?" → 핵심 부품 List의 "재생 FAN · 품번" 부품 사진)
    if not images and auto_step_image and candidates:
        ranked = sorted(candidates, key=lambda item: -(item.get("query_match") or 0))
        best_match = ranked[0].get("query_match") or 0
        runner_up = (ranked[1].get("query_match") or 0) if len(ranked) > 1 else 0
        if best_match >= 2 and best_match > runner_up:
            images.append({**ranked[0], "cited": False})
    return cleaned, images


_PUBLIC_FIELDS = (
    "ref", "resource_id", "document_id", "title", "role", "sheet_name", "from_cell", "to_cell", "step_no",
    "step_title", "surrounding_text", "original_filename", "context_no", "cited",
)


def public_images(images: Optional[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """응답·이력에 넣을 사진 필드만 남긴다(파일 경로·내부 점수 제외)."""
    return [{key: image.get(key) for key in _PUBLIC_FIELDS} for image in images or []]

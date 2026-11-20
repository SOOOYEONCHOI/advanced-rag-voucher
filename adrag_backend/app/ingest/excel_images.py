"""excel_ingest 사진 → 리소스 파일·배치 행 (2026.10.16 Phase 2, F-3-04 / R3-1·R3-2).

설계: docs/design/reports/phase-2-plan.md
- 배치(placement) 1개 = `tb_spreadsheet_resources` 1행. resource_id는 백엔드가 `{document_id}-v{version}-i{순번}`으로
  발급한다(파서 발급 ID와 겹치지 않음). staging 없이 바로 committed.
- 원본은 기존 저장 규칙 `documents/{document_id}/resources/{resource_id}/original/{sha256}.{ext}`에 그대로 둔다
  (해시 공유 저장소는 만들지 않음 — 문서 삭제 로직과 충돌). emf/wmf는 변환하지 않고 원본 보존.
- 순번은 시트 순서·시트 안 배치 순서로 정해 재실행(재시도)해도 같은 ID가 나온다.
"""
from __future__ import annotations

import os
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

_MIME_BY_EXT = {
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "bmp": "image/bmp",
    "tif": "image/tiff", "tiff": "image/tiff", "webp": "image/webp", "emf": "image/emf", "wmf": "image/wmf",
    "svg": "image/svg+xml",
}


@dataclass
class ExcelImagePlan:
    """배치별 리소스 행과, 청크 연결용 (시트, image_id) → resource_id 목록."""
    rows: list[dict[str, Any]] = field(default_factory=list)
    by_sheet_image: dict[tuple[str, str], list[str]] = field(default_factory=dict)
    _data: dict[str, bytes] = field(default_factory=dict)   # resource_id → 원본 바이트
    # 2026.10.22(sooyeon.choi) 추가 - 사진 전부 자동 연결: 배치 순서대로 (시트, placement, resource_id)
    items: list[tuple[str, dict[str, Any], str]] = field(default_factory=list)


def _cells(cell_range: str | None) -> tuple[str | None, str | None]:
    if not cell_range:
        return None, None
    start, _, end = cell_range.partition(":")
    return start or None, (end or start) or None


def plan_excel_images(result, document_id: str, version_no: int, parse_job_id: str) -> ExcelImagePlan:
    plan = ExcelImagePlan()
    assets = result.assets or {}
    seq = 0
    for section in result.ir.get("sections", []):
        sheet = section.get("name")
        for placement in section.get("placements") or []:
            asset = assets.get(placement.get("sha256"))
            if not asset or asset.get("data") is None:
                continue
            seq += 1
            resource_id = f"{document_id}-v{version_no}-i{seq:04d}"
            ext = (asset.get("ext") or "bin").lower()
            from_cell, to_cell = _cells(placement.get("cell_range"))
            confidence = placement.get("confidence")
            plan.rows.append({
                "resource_id": resource_id,
                "document_id": document_id,
                "parse_job_id": parse_job_id,
                "resource_type": "image",
                "resource_path": (
                    f"documents/{document_id}/resources/{resource_id}/original/{placement['sha256']}.{ext}"
                ),
                "content_hash": f"sha256:{placement['sha256']}",
                "mime_type": _MIME_BY_EXT.get(ext, "application/octet-stream"),
                "file_size": len(asset["data"]),
                "sheet_name": sheet,
                "from_cell": from_cell,
                "to_cell": to_cell,
                "surrounding_range": placement.get("cell_range"),
                "surrounding_text": placement.get("context_text"),
                "status": "committed",
                "version_no": version_no,
                "role_cd": placement.get("role"),
                "section_type": placement.get("section_type"),
                "step_no": placement.get("step_no"),
                "step_title": placement.get("step_title"),
                "anchor_type": placement.get("anchor_type"),
                "in_print_area": bool(placement.get("in_print_area", True)),
                "overlay_json": {
                    "callouts": placement.get("callouts") or [],
                    "markers": placement.get("markers") or [],
                    "overlay_texts": placement.get("overlay_texts") or [],
                },
                "link_method": placement.get("link_method"),
                "link_confidence": None if confidence is None else max(0.0, min(1.0, float(confidence))),
                "review_status": "needs_review" if placement.get("review_status") == "needs_review" else "auto",
            })
            plan._data[resource_id] = asset["data"]
            plan.by_sheet_image.setdefault((sheet, placement.get("image_id")), []).append(resource_id)
            plan.items.append((sheet, placement, resource_id))
    return plan


def write_excel_images(plan: ExcelImagePlan, resource_service) -> int:
    """원본 파일을 저장한다(같은 경로가 있으면 덮어씀 — 재시도에서도 같은 결과). 실패하면 예외."""
    for row in plan.rows:
        destination: Path = resource_service.resolve_relative_path(row["resource_path"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        for sub in ("renditions", "analyses"):
            (destination.parent.parent / sub).mkdir(exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".writing")
        temporary.write_bytes(plan._data[row["resource_id"]])
        os.replace(temporary, destination)
    return len(plan.rows)


def resource_ids_for(plan: ExcelImagePlan, sheet: str | None, image_ids: list[str] | None) -> list[str]:
    """Step 청크의 image_ids(sha256 앞 16자리)를 같은 시트의 배치 resource_id로 바꾼다(순서 유지, 중복 제거)."""
    found: list[str] = []
    for image_id in image_ids or []:
        for resource_id in plan.by_sheet_image.get((sheet, image_id), []):
            if resource_id not in found:
                found.append(resource_id)
    return found


# ── 2026.10.22 추가(sooyeon.choi) - 사진 전부 자동 연결(EXCEL_IMAGE_LINK_ALL, R3-2) ──────────────────────────
# 장식·양식 머리글을 뺀 모든 사진을, 청크 내용이 놓인 셀 위치 기준으로 청크에 연결한다(검수 화면 없음, UI-15 1차 제외).
#   1. step       : 파서가 Step을 정한 사진 → 같은 Step 번호 청크(행 범위에 사진 시작 행이 드는 청크 우선)
#   2. row_overlap: 사진 행 범위와 겹치는 청크 전부
#   3. nearest    : 같은 시트에서 행 거리가 가장 가까운 청크(같으면 위쪽 청크)
#   4. image_chunk: 위치가 있는 글자 청크가 없는 시트 → excel_ingest 이미지 청크(위치 설명)를 적재하고 연결
# 청크 위치: Step·공정단계=IR steps[].rows, 표=meta.rows, 안내문=shape_range, 개요=IR header_kv 행. 체크박스·흐름도는 위치 없음.
LINK_EXCLUDED_ROLES = frozenset({"decoration", "form_header"})
LINK_METHODS = ("step", "row_overlap", "nearest", "image_chunk")
_STEP_KINDS = frozenset({"step", "flow_stage"})
_ROW_NUMBER = re.compile(r"(\d+)")


@dataclass
class ExcelImageLinks:
    by_chunk: dict[int, list[str]] = field(default_factory=dict)   # result.chunks 순번 → resource_id(연결 순서)
    keep_image_chunks: set[int] = field(default_factory=set)       # 적재할 이미지 청크 순번(4번 규칙)
    summary: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class _ChunkPosition:
    index: int
    kind: str
    step_no: Any
    rows: tuple[int, int]


def _rows_of(cell_range: Optional[str]) -> Optional[tuple[int, int]]:
    """``C13:F20`` → (13, 20), ``AE72`` → (72, 72)."""
    numbers = [int(n) for n in _ROW_NUMBER.findall(cell_range or "")]
    return (min(numbers), max(numbers)) if numbers else None


def _chunk_positions(result) -> dict[str, list[_ChunkPosition]]:
    """시트별 위치가 있는 글자 청크. 적재하지 않는 빈 청크·이미지 청크는 뺀다."""
    sheets = {s.get("name"): s for s in result.ir.get("sections", [])}
    step_seen: Counter = Counter()
    positions: dict[str, list[_ChunkPosition]] = {}
    for index, chunk in enumerate(result.chunks):
        kind, sheet = chunk.get("content_type"), chunk.get("sheet")
        meta, sheet_ir = chunk.get("meta") or {}, sheets.get(chunk.get("sheet")) or {}
        rows = None
        if kind in _STEP_KINDS:
            # Step 번호가 겹치는 시트(예: Step 0 두 번)는 청크 순서 = IR steps 순서로 맞춘다
            same_no = [st for st in sheet_ir.get("steps") or [] if st.get("no") == meta.get("step_no")]
            nth = step_seen[(sheet, meta.get("step_no"))]
            step_seen[(sheet, meta.get("step_no"))] += 1
            if same_no:
                rows = tuple(same_no[min(nth, len(same_no) - 1)]["rows"])
        elif kind == "table_section":
            meta_rows = meta.get("rows")
            if isinstance(meta_rows, (list, tuple)) and len(meta_rows) == 2:
                rows = (min(meta_rows), max(meta_rows))
        elif kind == "guide_note":
            rows = _rows_of(meta.get("shape_range"))
        elif kind == "summary":
            header_rows = [h["row"] for h in sheet_ir.get("header_kv") or [] if h.get("row")]
            rows = (min(header_rows), max(header_rows)) if header_rows else None
        if rows and (chunk.get("text") or "").strip():
            step_no = meta.get("step_no") if kind in _STEP_KINDS else None
            positions.setdefault(sheet, []).append(_ChunkPosition(index, kind, step_no, rows))
    return positions


def _distance(chunk_rows: tuple[int, int], image_rows: tuple[int, int]) -> tuple[int, int]:
    """(행 거리, 위쪽이면 0·아래쪽이면 1). 겹치면 거리 0."""
    if chunk_rows[1] < image_rows[0]:
        return image_rows[0] - chunk_rows[1], 0
    if chunk_rows[0] > image_rows[1]:
        return chunk_rows[0] - image_rows[1], 1
    return 0, 0


def _targets(placement: dict[str, Any], candidates: list[_ChunkPosition]) -> tuple[Optional[str], list[int]]:
    image_rows = _rows_of(placement.get("cell_range"))
    if image_rows is None or not candidates:
        return None, []
    step_no = placement.get("step_no")
    if step_no is not None:
        same_step = [c for c in candidates if c.kind in _STEP_KINDS and c.step_no == step_no]
        containing = [c for c in same_step if c.rows[0] <= image_rows[0] <= c.rows[1]]
        if containing or same_step:
            return "step", [c.index for c in (containing or same_step[:1])]
    overlap = [c for c in candidates if c.rows[0] <= image_rows[1] and image_rows[0] <= c.rows[1]]
    if overlap:
        return "row_overlap", [c.index for c in overlap]
    best = min(_distance(c.rows, image_rows) for c in candidates)
    return "nearest", [c.index for c in candidates if _distance(c.rows, image_rows) == best]


def link_excel_images(result, plan: ExcelImagePlan) -> ExcelImageLinks:
    """장식·양식 머리글을 뺀 모든 사진 배치를 청크에 연결한다. 결정적(같은 입력 → 같은 연결)."""
    links = ExcelImageLinks()
    positions = _chunk_positions(result)
    image_chunks = {
        (chunk.get("sheet"), (chunk.get("chunk_id") or "").partition(":image:")[2]): index
        for index, chunk in enumerate(result.chunks)
        if chunk.get("content_type") == "image" and (chunk.get("text") or "").strip()
    }
    ordered: dict[int, list[tuple[int, int, str]]] = {}
    methods: Counter = Counter()
    unlinked: list[str] = []
    for seq, (sheet, placement, resource_id) in enumerate(plan.items):
        if placement.get("role") in LINK_EXCLUDED_ROLES:
            methods["excluded"] += 1
            continue
        method, targets = _targets(placement, positions.get(sheet, []))
        if not targets:
            index = image_chunks.get((sheet, f"{placement.get('image_id')}@{placement.get('cell_range')}"))
            if index is not None:
                method, targets = "image_chunk", [index]
                links.keep_image_chunks.add(index)
        if not targets:
            unlinked.append(resource_id)
            continue
        methods[method] += 1
        for index in targets:
            ordered.setdefault(index, []).append((LINK_METHODS.index(method), seq, resource_id))
    links.by_chunk = {index: [rid for _, _, rid in sorted(items)] for index, items in ordered.items()}
    total = len(plan.items)
    links.summary = {
        "mode": "all",
        "placements": total,
        "excluded": methods.pop("excluded", 0),
        "linked": sum(methods.values()),
        "unlinked": len(unlinked),
        "unlinked_resource_ids": unlinked[:20],
        "by_method": {m: methods.get(m, 0) for m in LINK_METHODS},
        "image_chunks": len(links.keep_image_chunks),
    }
    return links

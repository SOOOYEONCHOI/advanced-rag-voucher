"""도면 처리 결과·검수 API (2026.11.12(sooyeon.choi) 도면 파싱 기능 추가).

- 처리 결과: 문서를 볼 수 있는 사용자 모두(열람 범위 판정은 routes.ingest._load_visible_document 한 곳)
- 검수 완료·취소: 업로드한 본인 또는 관리자. 현재 버전만. 상태는 버전 summary_json.drawing.review에 두고
  문서 이력(tb_document_events, 'update')에 남긴다
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, HTTPException

from app.core.config import get_settings
from app.ingest.drawing.ir import read_ir
from app.repositories.database import get_database_manager
from app.routes.ingest import _load_visible_document
from app.services.ingest_service import get_original_file_storage
from app.utils.datetime import format_kst_datetime
from app.utils.security import get_current_principal

router = APIRouter(prefix="/ingest", tags=["drawings"])

_DIMENSION_LIMIT = 300


def _version_row(document_id: str, version_no: int) -> dict[str, Any]:
    rows = get_database_manager().execute_query(
        """SELECT v.version_no, v.status, v.processing_engine, v.summary_json, v.warnings_json, v.original_filename,
                  v.file_size, v.md_dir, v.created_at, d.version_no AS current_version_no
           FROM tb_document_versions v JOIN tb_documents d ON d.document_id = v.document_id
           WHERE v.document_id = ? AND v.version_no = ?""",
        (document_id, version_no),
    )
    if not rows:
        raise HTTPException(status_code=404, detail="해당 버전을 찾을 수 없습니다.")
    row = dict(rows[0])
    for key in ("summary_json", "warnings_json"):
        if isinstance(row.get(key), str):
            row[key] = json.loads(row[key])
    if row.get("processing_engine") != "drawing_ingest" or not (row.get("summary_json") or {}).get("drawing"):
        raise HTTPException(status_code=404, detail="도면 처리 결과가 없는 버전입니다.")
    return row


def _resolve_ir(ir_path: str) -> Path:
    """IR 경로를 원본 저장소 안에서만 푼다(저장소 밖이면 404)."""
    storage = get_original_file_storage(get_settings())
    path = (storage._adrag_root / ir_path).resolve() if not Path(ir_path).is_absolute() else Path(ir_path).resolve()
    try:
        path.relative_to(storage.base_dir)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="도면 처리 결과 파일을 찾을 수 없습니다.") from exc
    if not path.exists():
        raise HTTPException(status_code=404, detail="도면 처리 결과 파일을 찾을 수 없습니다.")
    return path


def _can_review(principal: dict, doc: dict) -> bool:
    return bool(principal.get("is_admin") or doc.get("uploaded_by") == principal["user_id"])


def _review_view(review: Optional[dict]) -> dict[str, Any]:
    review = review or {}
    return {"status": review.get("status", "pending"), "reviewer": review.get("reviewer"),
            "reviewed_at": review.get("reviewed_at")}


def _build_result(document_id: str, version_no: int, principal: dict) -> dict[str, Any]:
    doc = _load_visible_document(document_id, principal)
    row = _version_row(document_id, version_no)
    drawing = row["summary_json"]["drawing"]
    ir = read_ir(_resolve_ir(drawing["ir_path"]))
    dimensions = ir.get("dimensions") or []
    return {
        "document_id": document_id,
        "version_no": version_no,
        "is_current": row["version_no"] == row["current_version_no"],
        "product_model": doc.get("product_model"),
        "filename": row.get("original_filename"),
        "collection_name": doc.get("source_collection"),
        "uploaded_by": doc.get("uploaded_by"),
        "can_review": _can_review(principal, doc) and row["version_no"] == row["current_version_no"],
        "review": _review_view(drawing.get("review")),
        "summary": {k: v for k, v in drawing.items() if k not in ("review", "ir_path", "images", "md_dir")},
        "metadata": ir.get("metadata") or {},
        "title_block": ir.get("title_block") or {},
        "sheet": ir.get("sheet") or {},
        "tables": ir.get("tables") or [],
        "notes": ir.get("notes") or {},
        "dimensions": dimensions[:_DIMENSION_LIMIT],
        "dimension_count": len(dimensions),
        "tolerance_summary": ir.get("tolerance_summary") or {},
        "misc_texts": ir.get("misc_texts") or [],
        "confidential": bool(ir.get("confidential")),
        "warnings": ir.get("warnings") or row.get("warnings_json") or [],
        "images": drawing.get("images") or {},
        "processing": {
            "source": {k: v for k, v in (ir.get("source") or {}).items() if k != "sha256"},
            "versions": ir.get("versions") or {},
            "stats": ir.get("stats") or {},
            "timings": drawing.get("timings") or {},
            "md_dir": row.get("md_dir"),
            "file_size": row.get("file_size"),
            "created_at": format_kst_datetime(row.get("created_at")) or None,
        },
        "search_status": drawing.get("search_status", "not_indexed"),
    }


@router.get("/documents/{document_id}/versions/{version_no}/drawing-result")
async def get_drawing_result(document_id: str, version_no: int, principal: dict = Depends(get_current_principal)):
    """도면 처리 결과(표제란·표·주기·치수·경고·이미지·처리 정보)."""
    return await asyncio.to_thread(_build_result, document_id, version_no, principal)


def _set_review(document_id: str, version_no: int, principal: dict, status: str, confirm_missing: bool) -> dict:
    doc = _load_visible_document(document_id, principal)
    if not _can_review(principal, doc):
        raise HTTPException(status_code=403, detail="업로드한 본인 또는 관리자만 검수할 수 있습니다.")
    row = _version_row(document_id, version_no)
    if row["version_no"] != row["current_version_no"]:
        raise HTTPException(status_code=409, detail="현재 버전만 검수할 수 있습니다.")
    drawing = row["summary_json"]["drawing"]
    if status == "reviewed" and drawing.get("needs_review") and not confirm_missing:
        raise HTTPException(status_code=409, detail={
            "code": "MISSING_FIELDS_CONFIRM_REQUIRED",
            "message": "표제란 필수 항목이 비어 있습니다. 원본을 확인한 뒤 다시 요청하세요.",
            "missing_fields": drawing.get("missing_fields") or [],
        })
    db = get_database_manager()
    review = {"status": status}
    if status == "reviewed":
        now = db.execute_query("SELECT now()")[0][0]
        review.update(reviewer=principal["user_id"], reviewed_at=format_kst_datetime(now),
                      confirmed_missing=bool(drawing.get("needs_review")))
    with db.get_connection():
        db.execute_update(
            "UPDATE tb_document_versions SET summary_json = jsonb_set(summary_json, '{drawing,review}', CAST(? AS jsonb)), "
            "updated_at = now() WHERE document_id = ? AND version_no = ?",
            (json.dumps(review, ensure_ascii=False), document_id, version_no),
        )
        db.execute_update(
            """INSERT INTO tb_document_events (document_id, collection_id, event_type, event_message, actor_id, snapshot_json)
               VALUES (?, (SELECT collection_id FROM tb_documents WHERE document_id = ?), 'update', ?,
                       (SELECT user_id FROM tb_users WHERE user_id = ?), ?)""",
            (document_id, document_id, "도면 검수 완료" if status == "reviewed" else "도면 검수 취소",
             principal["user_id"],
             json.dumps({"field": "drawing_review", "version_no": version_no, "after": status}, ensure_ascii=False)),
        )
    return {"document_id": document_id, "version_no": version_no, "review": _review_view(review)}


@router.post("/documents/{document_id}/versions/{version_no}/drawing-review")
async def review_drawing(
    document_id: str,
    version_no: int,
    body: Optional[dict] = Body(default=None),
    principal: dict = Depends(get_current_principal),
):
    """검수 완료. 필수 항목이 빠진 도면은 ``{"confirm_missing": true}``를 함께 보내야 한다(아니면 409)."""
    confirm = bool((body or {}).get("confirm_missing"))
    return await asyncio.to_thread(_set_review, document_id, version_no, principal, "reviewed", confirm)


@router.delete("/documents/{document_id}/versions/{version_no}/drawing-review")
async def cancel_drawing_review(document_id: str, version_no: int, principal: dict = Depends(get_current_principal)):
    """검수 취소."""
    return await asyncio.to_thread(_set_review, document_id, version_no, principal, "pending", False)

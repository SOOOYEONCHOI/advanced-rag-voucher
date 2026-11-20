"""도면 적재 파이프라인 — 원본 저장 → 변환 → 추출 → 이미지 → 저장 (2026.11.12(sooyeon.choi) 도면 파싱 기능 추가).

기존 적재 파이프라인과 같은 체크포인트·재시도 방식을 쓰되, 임베딩·검색 데이터 저장(Qdrant)·청크 저장(tb_chunks)은 하지 않는다.
문서 행·버전·이미지 리소스·적용 이력은 한 트랜잭션으로 기록한다. 버전 봉인(복원용 벡터 명세)은 하지 않으므로
도면 버전은 이전 버전 적용 대상이 아니다.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Any, Dict, Optional

from app.core.config import get_settings
from app.core.storage_paths import get_file_storage_dir
from app.ingest.drawing.ir import export_md, read_ir, summarize, write_ir
from app.ingest.drawing.runner import convert_step, doc_key_of, extract_step, render_step
from app.repositories.database import get_database_manager
from app.services.ingest_pipeline import (
    INITIAL_VERSION,
    IndexStep,
    IngestContext,
    IngestPipeline,
    ParseStep,
    _is_new_version,
    _record_repo,
    _resource_service,
    _version_of,
)

logger = logging.getLogger(__name__)

DRAWING_ENGINE = "drawing_ingest"
DRAWING_DOC_TYPE = "drawing"
DRAWING_STEPS = ("parse", "drawing_convert", "drawing_extract", "drawing_render", "drawing_store")
_ROLE_FILE = {("drawing", "full"): "full", ("drawing_preview", "full"): "preview"}


def is_drawing_request(request: Dict[str, Any]) -> bool:
    return request.get("document_type") == DRAWING_DOC_TYPE


def _derived_dir(settings, document_id: str, version_no: int) -> Path:
    return get_file_storage_dir(settings) / "drawing" / document_id / f"v{version_no}" / "derived"


def _relative(path: Path) -> str:
    """원본 저장소와 같은 기준(저장 폴더의 두 단계 위, FileStorageManager와 동일)으로 상대 경로를 만든다."""
    root = get_file_storage_dir(get_settings()).resolve().parent.parent
    try:
        return Path(path).resolve().relative_to(root).as_posix()
    except ValueError:
        return Path(path).resolve().as_posix()


class DrawingConvertStep:
    name = "drawing_convert"

    async def run(self, service, context: IngestContext) -> None:
        data, request = context.data, context.request
        if data.get("drawing_source"):
            return
        settings = get_settings()
        derived = _derived_dir(settings, context.document_id, _version_of(request))
        source = await asyncio.to_thread(convert_step, request["file_path"], request["filename"], derived, settings)
        source.update(filename=request["filename"], sha256=data.get("file_sha256"))
        data["drawing_derived_dir"] = str(derived)
        data["drawing_source"] = source


class DrawingExtractStep:
    name = "drawing_extract"

    async def run(self, service, context: IngestContext) -> None:
        data, request = context.data, context.request
        if data.get("drawing_ir_path"):
            return
        settings = get_settings()
        ir_path = Path(data["drawing_derived_dir"]) / "drawing_ir.json"
        source = data["drawing_source"]
        ir = await asyncio.to_thread(extract_step, source["dxf_path"], source, ir_path, settings)
        data["doc_key"] = doc_key_of(ir, request["filename"])
        data["drawing_md_dir"] = await asyncio.to_thread(
            export_md, ir, getattr(settings, "md_save_dir", ""), data["doc_key"], request.get("job_id") or "",
            int(getattr(settings, "drawing_md_keep_last", 5)),
        )
        data["drawing_ir_path"] = str(ir_path)


class DrawingRenderStep:
    name = "drawing_render"

    async def run(self, service, context: IngestContext) -> None:
        data = context.data
        if data.get("drawing_images") is not None:
            return
        settings = get_settings()
        ir_path = Path(data["drawing_ir_path"])
        ir = read_ir(ir_path)
        result = await asyncio.to_thread(render_step, data["drawing_source"]["dxf_path"], ir, settings)
        out_dir = Path(data["drawing_derived_dir"]) / "render"
        shutil.rmtree(out_dir, ignore_errors=True)
        out_dir.mkdir(parents=True, exist_ok=True)
        images = []
        for image in result.images:
            name = _ROLE_FILE.get((image.role, image.region), image.region)
            path = out_dir / f"{name}.png"
            path.write_bytes(image.png)
            images.append({
                "role": image.role, "region": image.region, "path": str(path), "width": image.width,
                "height": image.height, "bbox_norm": image.bbox_norm, "sha256": hashlib.sha256(image.png).hexdigest(),
                "file_size": len(image.png),
            })
        # 렌더 경고·소요 시간을 IR에 더한다(렌더 실패는 저장을 막지 않는다)
        ir["warnings"] = [w for w in ir["warnings"] if not w["code"].startswith(("W_RENDER", "W_FONT"))] + result.warnings
        ir["stats"]["render_ms"] = result.elapsed_ms
        await asyncio.to_thread(write_ir, ir, ir_path)
        data["drawing_images"] = images


def _resource_rows(images: list[dict], document_id: str, version_no: int, parse_job_id: str) -> list[dict[str, Any]]:
    rows = []
    for seq, image in enumerate(images, 1):
        resource_id = f"{document_id}-v{version_no}-d{seq:02d}"
        rows.append({
            "resource_id": resource_id,
            "document_id": document_id,
            "parse_job_id": parse_job_id,
            "resource_type": "image",
            "resource_path": f"documents/{document_id}/resources/{resource_id}/original/{image['sha256']}.png",
            "content_hash": f"sha256:{image['sha256']}",
            "mime_type": "image/png",
            "file_size": image["file_size"],
            "surrounding_text": image["region"],
            "status": "committed",
            "version_no": version_no,
            "role_cd": image["role"],
            "in_print_area": True,
            "overlay_json": {"region": image["region"], "bbox_norm": image.get("bbox_norm"),
                             "width": image["width"], "height": image["height"]},
            "review_status": "auto",
            "_source": image["path"],
        })
    return rows


def _write_resources(rows: list[dict[str, Any]], resource_service) -> None:
    for row in rows:
        destination: Path = resource_service.resolve_relative_path(row["resource_path"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".writing")
        shutil.copyfile(row["_source"], temporary)
        os.replace(temporary, destination)


def _remove_resources(rows: list[dict[str, Any]], resource_service, document_id: str) -> None:
    for row in rows:
        shutil.rmtree(resource_service.resolve_relative_path(f"documents/{document_id}/resources/{row['resource_id']}"),
                      ignore_errors=True)


def same_part_no_documents(db, part_no: Optional[str], document_id: str) -> list[dict[str, Any]]:
    """같은 품번(doc_key)을 쓰는 다른 도면 문서. 자동으로 교체하지 않고 안내에만 쓴다."""
    if not part_no:
        return []
    rows = db.execute_query(
        """SELECT d.document_id, d.product_model, d.original_filename, c.display_name AS collection_display_name
           FROM tb_documents d LEFT JOIN tb_collections c ON c.collection_id = d.collection_id
           WHERE d.doc_key = ? AND d.document_id <> ? AND d.deleted_at IS NULL AND d.doc_type = ?
           ORDER BY d.created_at""",
        (part_no, document_id, DRAWING_DOC_TYPE),
    )
    return [dict(r) for r in rows]


class DrawingStoreStep:
    name = "drawing_store"

    async def run(self, service, context: IngestContext) -> None:
        await asyncio.to_thread(self._store, service, context)

    @staticmethod
    def _store(service, context: IngestContext) -> None:
        request, data = context.request, context.data
        config = data["collection_config"]
        version_no = _version_of(request)
        new_version = _is_new_version(request)
        ir_path = Path(data["drawing_ir_path"])
        ir = read_ir(ir_path)
        summary = summarize(ir)
        meta = ir["metadata"]
        title = " ".join(v for v in (meta.get("part_no"), meta.get("part_name")) if v) or request["filename"]
        file_format = Path(request["filename"]).suffix.lower().lstrip(".") or "dwg"
        resource_service = _resource_service(service)
        rows = _resource_rows(data.get("drawing_images") or [], context.document_id, version_no,
                              f"drawing-{request.get('job_id') or context.document_id}")
        images = {"crops": {}}
        for row in rows:
            if row["role_cd"] == "drawing_crop":
                images["crops"][row["overlay_json"]["region"]] = row["resource_id"]
            else:
                images["full" if row["role_cd"] == "drawing" else "preview"] = row["resource_id"]
        summary_json = {"drawing": {
            **summary,
            "ir_path": _relative(ir_path),
            "md_dir": data.get("drawing_md_dir"),
            "images": images,
            "review": {"status": "pending"},
            "timings": {"convert_ms": (data["drawing_source"].get("converter") or {}).get("elapsed_ms"),
                        "extract_ms": ir["stats"].get("extract_ms"), "render_ms": ir["stats"].get("render_ms")},
        }}
        parse_result = {
            "doc_type": DRAWING_DOC_TYPE, "requested_doc_type": DRAWING_DOC_TYPE, "doc_type_source": "file_extension",
            "total_pages": 1, "chunk_count": 0, "is_law": False, "is_manual": False, "detection_details": None,
        }
        version_fields = dict(
            processing_engine=DRAWING_ENGINE, file_sha256=data.get("file_sha256"), original_filename=request["filename"],
            stored_filename=data["stored_filename"], source_path=data["stored_path"], file_size=data["file_size"],
            file_format=file_format, parser_type=DRAWING_ENGINE, total_pages=1, chunk_count=0,
            md_dir=data.get("drawing_md_dir"), summary_json=summary_json,
        )
        if resource_service and rows:
            _write_resources(rows, resource_service)
        db = getattr(service, "db", None) or get_database_manager()
        record_repo = _record_repo(service)
        try:
            with db.get_connection():
                previous_version_no = None
                if new_version:
                    previous_version_no = record_repo.activate_version(
                        context.document_id, version_no, **version_fields, doc_type=DRAWING_DOC_TYPE,
                        requested_doc_type=DRAWING_DOC_TYPE, doc_type_source="file_extension", title=title,
                    )
                else:
                    IndexStep._store_new_document(service, request, data, context, config, parse_result, title, file_format)
                record_repo.insert_resources([{k: v for k, v in row.items() if not k.startswith("_")} for row in rows])
                if not new_version:
                    record_repo.create_active_version(
                        context.document_id, INITIAL_VERSION, **version_fields,
                        job_id=request.get("job_id"), uploaded_by=request.get("uploaded_by"),
                    )
                db.execute_update(
                    "UPDATE tb_document_versions SET revision_label = ?, warnings_json = ? "
                    "WHERE document_id = ? AND version_no = ?",
                    (meta.get("rev"), json.dumps(ir.get("warnings") or [], ensure_ascii=False),
                     context.document_id, version_no),
                )
                record_repo.record_activation(
                    context.document_id, to_version_no=version_no,
                    operation_type="replace" if new_version else "upload",
                    from_version_no=previous_version_no, actor_id=request.get("uploaded_by"),
                    job_id=request.get("job_id"), initial=not new_version,
                )
        except Exception:
            if resource_service:
                _remove_resources(rows, resource_service, context.document_id)
            raise
        data["activated"] = True
        same = same_part_no_documents(db, meta.get("part_no"), context.document_id) if not new_version else []
        data["result"] = {
            "document_id": context.document_id, "filename": request["filename"], "doc_type": DRAWING_DOC_TYPE,
            "requested_doc_type": DRAWING_DOC_TYPE, "doc_type_source": "file_extension", "detection_details": None,
            "is_law": False, "is_manual": False, "total_pages": 1, "chunk_count": 0,
            "collection_name": request["collection_name"], "status": "success",
            "processing_engine": DRAWING_ENGINE, "version_no": version_no,
            "drawing": {**summary, "same_part_no_documents": same},
        }


class DrawingIngestPipeline(IngestPipeline):
    """기존 파이프라인의 실행·체크포인트·보상 흐름을 그대로 쓰고 단계만 바꾼다."""

    steps = (ParseStep(), DrawingConvertStep(), DrawingExtractStep(), DrawingRenderStep(), DrawingStoreStep())

    async def run(self, service, request: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        started = time.perf_counter()
        try:
            return await super().run(service, request, **kwargs)
        finally:
            logger.info("event=drawing_ingest elapsed_ms=%s filename=%s",
                        int((time.perf_counter() - started) * 1000), request.get("filename"))

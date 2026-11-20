"""적재 기록용 청크 식별자·행 만들기 (2026.10.16 Phase 2). excel·docling 두 경로 공통.

- ``chunk_id`` = ``{document_id}:{version_no}:{source_key}#{part_no}`` (tb_chunks PK, 사람이 읽을 수 있는 키)
- ``point_id`` = uuid5(chunk_id) — Qdrant 포인트 ID. 같은 입력이면 재시도해도 같은 ID(중복 포인트 없음).
  payload의 ``chunk_id``는 기존대로 포인트 ID 문자열이다(평가 코드가 포인트 ID로 비교 — 호환 유지).
- ``source_key``는 버전과 무관한 위치 키(excel: ``09:step:6``, docling: ``chunk_key`` 또는 순번).
"""
from __future__ import annotations

import uuid
from typing import Any, Iterable

# 개정본(Phase 3) 전까지 업로드는 항상 v1
INITIAL_VERSION = 1
_POINT_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "adrag/tb_chunks")


def point_id_for(chunk_id: str) -> str:
    return str(uuid.uuid5(_POINT_NAMESPACE, chunk_id))


def assign_chunk_identity(chunks: list, document_id: str, version_no: int) -> None:
    """청크 메타에 source_key·part_no·chunk_record_id·point_id·version_no를 채운다(멱등)."""
    used: set[tuple[str, int]] = set()
    for index, chunk in enumerate(chunks):
        meta = chunk.metadata
        key = str(meta.get("source_key") or meta.get("chunk_key") or f"c{index:05d}")
        part_no = int(meta.get("part_no") or 0)
        if (key, part_no) in used:  # 원천 키가 겹치면 순번으로 유일하게
            key = f"{key}~i{index}"
        used.add((key, part_no))
        chunk_id = f"{document_id}:{version_no}:{key}#{part_no}"
        meta.update(source_key=key, part_no=part_no, version_no=version_no,
                    chunk_record_id=chunk_id, point_id=point_id_for(chunk_id))


def chunk_rows(chunks: Iterable, document_id: str, version_no: int, collection_id: int) -> list[dict[str, Any]]:
    rows = []
    for chunk in chunks:
        meta = chunk.metadata
        rows.append({
            "chunk_id": meta["chunk_record_id"],
            "document_id": document_id,
            "version_no": version_no,
            "collection_id": collection_id,
            "point_id": meta["point_id"],
            "source_key": meta["source_key"],
            "part_no": meta.get("part_no", 0),
            "point_type": "text",
            "content_type": meta.get("content_type") or meta.get("block_type"),
            "section_type": meta.get("section_type"),
            "sheet_name": meta.get("sheet_name"),
            "source_range": meta.get("source_range"),
            "step_no": meta.get("step_no") if isinstance(meta.get("step_no"), int) else None,
            "chunk_text": chunk.page_content,
            "meta_json": {
                k: meta.get(k) for k in ("processing_engine", "chunk_key", "revision", "page_number",
                                         "header_path", "section_name")
                if meta.get(k) not in (None, "", [])
            },
        })
    return rows


def chunk_resource_links(chunks: Iterable) -> list[tuple[str, str, int]]:
    links = []
    for chunk in chunks:
        for order, resource_id in enumerate(chunk.metadata.get("resource_ids") or []):
            links.append((chunk.metadata["chunk_record_id"], str(resource_id), order))
    return links


def flow_graph_rows(ir: dict[str, Any]) -> list[dict[str, Any]]:
    graphs = []
    for section in ir.get("sections", []):
        graph = section.get("flow_graph")
        if not graph:
            continue
        graphs.append({
            "sheet_name": section.get("name"),
            "nodes": graph.get("nodes") or [],
            "edges": graph.get("edges") or [],
            "unresolved": graph.get("unresolved_connectors") or [],
            "source_hash": graph.get("source_hash"),
            "vlm_status": graph.get("vlm_status"),
            "review_status": "needs_review" if graph.get("review_status") == "needs_review" else "auto",
        })
    return graphs

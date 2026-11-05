"""excel_ingest 청크 → 적재 파이프라인 청크(LCDocument) 변환 (2026.10.16 Phase 1, Phase 2 보강).

- 기존 임베딩·Qdrant 적재 단계를 그대로 쓰도록 docling 스프레드시트 청크와 같은 메타데이터 이름을 쓴다
  (``sheet_name``·``source_range``·``display_markdown``·``chunk_key``·``block_type``, 출처 표시 R4-4).
- 이미지 청크(content_type=image)는 적재하지 않는다(사진 포인트는 넣지 않음, Phase 2 P2-3).
  사진은 배치 행으로 저장되고 텍스트 청크의 ``resource_ids``로 연결된다(P2-8).
- Phase 2(P2-7·P2-9): 버전 무관 키 ``source_key``(예: ``09:step:6``), ``MAX_CHUNK_SIZE`` 초과 시 행 단위 분할
  (머리말 ``[… > …]``·열 안내 줄을 조각마다 반복, ``part_no``).
"""
from __future__ import annotations

from typing import Any, Callable, Iterable, Optional

from app.parsers.models import LCDocument

EXCEL_ENGINE = "excel_ingest"
SKIPPED_CONTENT_TYPES = frozenset({"image"})


def _sheet_index(chunk_id: str) -> int | None:
    parts = chunk_id.split(":")
    try:
        return int(parts[1]) if len(parts) > 1 else None
    except ValueError:
        return None


def _source_range(meta: dict[str, Any]) -> str | None:
    rows = meta.get("rows")
    if isinstance(rows, (list, tuple)) and len(rows) == 2 and all(isinstance(r, int) for r in rows):
        return f"{rows[0]}:{rows[1]}"  # 엑셀 행 범위 표기(예: 5:12)
    return meta.get("shape_range") or None


def source_key_of(chunk_id: str) -> str:
    """excel_ingest 청크 ID ``{doc_key}:{시트}:{종류}:{블록}``에서 문서 키를 뗀 버전 무관 키."""
    _, _, rest = (chunk_id or "").partition(":")
    return rest or chunk_id or "chunk"


def split_text(text: str, max_chars: int) -> list[str]:
    """``max_chars`` 이하 조각으로 나눈다. 첫 줄(머리말)과 ``(열: …)`` 줄은 조각마다 반복한다."""
    if max_chars <= 0 or len(text) <= max_chars:
        return [text]
    lines = text.split("\n")
    header = [lines[0]]
    body = lines[1:]
    if body and body[0].startswith("(열:"):
        header.append(body.pop(0))
    prefix = "\n".join(header)
    room = max(max_chars - len(prefix) - 1, max_chars // 4)
    parts: list[str] = []
    current: list[str] = []
    size = 0
    for line in body:
        while len(line) > room:  # 한 줄이 너무 길면 자른다
            if current:
                parts.append(current)
                current, size = [], 0
            parts.append([line[:room]])
            line = line[room:]
        if current and size + len(line) + 1 > room:
            parts.append(current)
            current, size = [], 0
        current.append(line)
        size += len(line) + 1
    if current:
        parts.append(current)
    return [prefix + "\n" + "\n".join(part) for part in parts] or [text[:max_chars]]


def excel_chunks_to_documents(
    chunks: Iterable[dict[str, Any]],
    *,
    max_chunk_size: int = 0,
    resource_lookup: Optional[Callable[[Optional[str], Optional[list[str]]], list[str]]] = None,
    resource_ids_by_index: Optional[dict[int, list[str]]] = None,
    keep_indexes: Iterable[int] = (),
) -> list[LCDocument]:
    """2026.10.22(sooyeon.choi) 추가 - ``resource_ids_by_index``(청크 순번 → 사진, ``link_excel_images`` 결과)가 있으면
    ``resource_lookup``(Step ``image_ids`` 기준) 대신 쓰고, ``keep_indexes``의 이미지 청크는 적재한다."""
    documents: list[LCDocument] = []
    used_keys: dict[str, int] = {}
    keep = set(keep_indexes)
    for index, chunk in enumerate(chunks):
        content_type = chunk.get("content_type")
        text = (chunk.get("text") or "").strip()
        if (content_type in SKIPPED_CONTENT_TYPES and index not in keep) or not text:
            continue
        meta = chunk.get("meta") or {}
        chunk_id = chunk.get("chunk_id") or ""
        key = source_key_of(chunk_id)
        # excel_ingest가 같은 ID를 두 번 낼 수 있다(예: Step 0) → 버전 안에서 유일하게
        seen = used_keys.get(key, 0)
        used_keys[key] = seen + 1
        if seen:
            key = f"{key}~{seen + 1}"
        if resource_ids_by_index is not None:
            resource_ids = list(resource_ids_by_index.get(index, []))
        else:
            resource_ids = resource_lookup(chunk.get("sheet"), meta.get("image_ids")) if resource_lookup else []
        pieces = split_text(text, max_chunk_size)
        for part_no, piece in enumerate(pieces):
            documents.append(LCDocument(
                page_content=piece,
                metadata={
                    "processing_engine": EXCEL_ENGINE,
                    "chunk_key": chunk_id,
                    "source_key": key,
                    "part_no": part_no,
                    "sheet_name": chunk.get("sheet"),
                    "sheet_index": _sheet_index(chunk_id),
                    "block_type": content_type,
                    "chunk_type": content_type,
                    "content_type": content_type,
                    "source_range": _source_range(meta),
                    "display_markdown": piece,
                    "section_type": meta.get("section_type"),
                    "step_no": meta.get("step_no"),
                    "revision": meta.get("revision"),
                    "resource_ids": resource_ids,
                },
            ))
    return documents

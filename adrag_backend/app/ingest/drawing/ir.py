"""도면 IR(drawing_ir/1.0)·요약·확인용 md (2026.11.12(sooyeon.choi) 도면 파싱 기능 추가).

IR이 도면 처리 결과의 원천이다. 검색에 쓸 메타데이터는 ``metadata``에 고정된 키 이름으로 둔다
(다음 단계에서 검색 데이터·조건 필터에 그대로 쓰므로 이름을 바꾸지 않는다).
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Optional

IR_SCHEMA = "drawing_ir/1.0"
EXTRACTOR_VERSION = "1"

METADATA_KEYS = (
    "doc_type", "part_no", "drawing_no", "part_name", "rev", "rev_major", "rev_iter", "drawing_kind",
    "sheet_size", "scale", "units", "date", "material", "material_group", "part_spec", "after_treatment",
    "drawn", "checked", "approved", "bom_part_nos", "confidential",
)


def build_metadata(ir: dict[str, Any]) -> dict[str, Any]:
    fields = ir["title_block"]["fields"]
    bom = next((t for t in ir["tables"] if t["kind"] == "bom"), None)
    part_nos = [r.get("part_no") for r in (bom["rows"] if bom else []) if r.get("part_no")]
    return {
        "doc_type": "drawing",
        "part_no": fields.get("part_no"),
        "drawing_no": fields.get("part_no"),
        "part_name": fields.get("part_name"),
        "rev": fields.get("revision"),
        "rev_major": fields.get("rev_major"),
        "rev_iter": fields.get("rev_iter"),
        "drawing_kind": "assembly" if part_nos else "part",
        "sheet_size": ir["sheet"].get("size"),
        "scale": fields.get("scale"),
        "units": fields.get("units") or ir["sheet"].get("units"),
        "date": fields.get("date"),
        "material": fields.get("material"),
        "material_group": fields.get("material_group"),
        "part_spec": fields.get("part_spec"),
        "after_treatment": fields.get("after_treatment"),
        "drawn": fields.get("drawn"),
        "checked": fields.get("checked"),
        "approved": fields.get("approved"),
        "bom_part_nos": part_nos,
        "confidential": bool(ir.get("confidential")),
    }


def summarize(ir: dict[str, Any]) -> dict[str, Any]:
    """작업 결과·버전 summary_json·문서 목록에 쓰는 짧은 요약."""
    meta = ir["metadata"]
    warnings = ir.get("warnings") or []
    warn = sum(1 for w in warnings if w.get("level") == "warn")
    missing = next((w.get("missing") for w in warnings if w["code"] == "W_TITLE_MISSING"), None) or []
    tables = {t["kind"]: len(t["rows"]) for t in ir["tables"]}
    return {
        "part_no": meta.get("part_no"),
        "part_name": meta.get("part_name"),
        "rev": meta.get("rev"),
        "sheet_size": meta.get("sheet_size"),
        "scale": meta.get("scale"),
        "drawing_kind": meta.get("drawing_kind"),
        "bom_rows": tables.get("bom", 0),
        "revision_rows": tables.get("revision", 0),
        "note_items": len(ir["notes"].get("items") or []),
        "warn_count": warn,
        "info_count": len(warnings) - warn,
        "needs_review": bool(missing),
        "missing_fields": missing,
        "search_status": "not_indexed",
    }


def write_ir(ir: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.writing")
    tmp.write_text(json.dumps(ir, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def read_ir(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _md_table(columns: list[str], rows: list[dict[str, str]]) -> list[str]:
    def cell(value: Any) -> str:
        return str(value or "").replace("|", "\\|").replace("\n", " ")

    lines = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    lines += ["| " + " | ".join(cell(r.get(c)) for c in columns) + " |" for r in rows]
    return lines


def export_md(ir: dict[str, Any], md_root: str, doc_key: str, job_id: str, keep_last: int = 5) -> Optional[str]:
    """확인용 md를 {md_root}/drawing/{doc_key}/{job_id}/summary.md에 쓰고 최근 keep_last개만 남긴다."""
    if not md_root:
        return None
    safe_key = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in (doc_key or "drawing"))[:80]
    base = Path(md_root) / "drawing" / safe_key
    out_dir = base / (job_id or "manual")
    out_dir.mkdir(parents=True, exist_ok=True)
    fields = ir["title_block"]["fields"]
    lines = [f"# 도면 처리 결과 — {fields.get('part_no') or ir['source']['filename']}", ""]
    lines += ["## 표제란", "", f"- 방식: {ir['title_block']['method']}"]
    lines += [f"- {k}: {v}" for k, v in fields.items()]
    lines += ["", "## 용지", "", f"- {ir['sheet'].get('size')} · 축척 {fields.get('scale') or '-'} · {ir['sheet'].get('units')}"]
    for table in ir["tables"]:
        lines += ["", f"## 표: {table['kind']} ({len(table['rows'])}행, 머리글 {table['header_pos']})", ""]
        lines += _md_table(table["columns"], table["rows"])
    notes = ir["notes"]
    lines += ["", "## 주기", ""] + [f"{i}. {item}" for i, item in enumerate(notes.get("items") or [], 1)]
    if notes.get("general_tolerance"):
        lines += ["", f"- 일반공차: {notes['general_tolerance']}"]
    lines += [f"- 규격 메모: {m}" for m in notes.get("spec_memos") or []]
    lines += ["", f"## 치수 ({len(ir['dimensions'])}개)", ""] + [f"- {d['text']}" for d in ir["dimensions"]]
    lines += ["", "## 기타 글자", ""] + [f"- {t}" for t in ir.get("misc_texts") or []]
    lines += ["", "## 경고·정보", ""] + [
        f"- [{w['level']}] {w['code']} {w['message']}" + (f" ({w['count']})" if w.get("count") is not None else "")
        for w in ir.get("warnings") or []
    ]
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    runs = sorted((p for p in base.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in runs[keep_last:]:
        shutil.rmtree(old, ignore_errors=True)
    return str(out_dir)

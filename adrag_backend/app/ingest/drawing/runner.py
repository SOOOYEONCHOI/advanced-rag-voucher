"""도면 처리 단계 실행 — 변환·추출·이미지 (2026.11.12(sooyeon.choi) 도면 파싱 기능 추가).

적재 파이프라인의 단계(drawing_convert → drawing_extract → drawing_render)가 하나씩 호출한다.
단계 결과 파일(변환 DXF·IR)은 버전 폴더의 derived/에 남겨 재시도 때 앞 단계를 다시 하지 않는다.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Any, Optional

import ezdxf

from .common import warning
from .convert import get_converter
from .detect import detect_drawing
from .extract import extract_dimensions, extract_misc, extract_notes, extract_tables, extract_title, load_config
from .ir import EXTRACTOR_VERSION, IR_SCHEMA, build_metadata, write_ir
from .reader import collect, load_dxf, make_sheet, pick_layout
from .render import RenderResult, render_drawing
from .sanitize import sanitize_dxf


def convert_step(src_path: str, filename: str, derived_dir: Path, settings) -> dict[str, Any]:
    """판별 → (DWG면) 변환 → 보정. 결과 DXF 경로와 변환 정보."""
    fmt = detect_drawing(src_path, filename)
    derived_dir.mkdir(parents=True, exist_ok=True)
    warnings: list[dict] = []
    converter_info: dict[str, Any] = {"name": None}
    if fmt.kind == "dwg":
        result = get_converter(settings).convert(src_path, str(derived_dir / "convert"))
        converted = derived_dir / "converted.dxf"
        shutil.move(result.dxf_path, converted)
        shutil.rmtree(derived_dir / "convert", ignore_errors=True)
        sanitized = derived_dir / "sanitized.dxf"
        fixes = sanitize_dxf(str(converted), str(sanitized))
        if fixes:
            warnings.append(warning("W_SANITIZED", "변환 결과의 잘못된 참조 항목을 자동으로 고쳤습니다.", count=fixes))
        warnings.extend(result.warnings)
        converter_info = {"name": result.tool, "version": result.version, "elapsed_ms": result.elapsed_ms,
                          "sanitize_fixes": fixes, "log_tail": result.log_tail[-5:]}
        dxf_path = sanitized
    else:
        dxf_path = derived_dir / "source.dxf"
        shutil.copyfile(src_path, dxf_path)
    return {
        "format": fmt.kind, "acadver": fmt.acadver, "release": fmt.release,
        "dxf_path": str(dxf_path), "converter": converter_info, "warnings": warnings,
    }


def extract_step(dxf_path: str, source: dict[str, Any], ir_path: Path, settings) -> dict[str, Any]:
    """읽기·정규화·항목 추출 → IR 저장. IR(dict)을 돌려준다."""
    started = time.perf_counter()
    cfg = load_config(getattr(settings, "drawing_template_dir", "") or "")
    warnings: list[dict] = list(source.get("warnings") or [])
    doc, load_warnings = load_dxf(dxf_path)
    warnings += load_warnings
    layout, space = pick_layout(doc)
    sheet = make_sheet(doc, layout, space)
    collected, collect_warnings = collect(doc, layout, sheet)
    warnings += collect_warnings

    title, title_warnings = extract_title(collected.texts, sheet, cfg)
    warnings += title_warnings
    tables, table_warnings = extract_tables(collected, sheet, cfg, skip=set(title.used))
    warnings += table_warnings
    used = set(title.used).union(*(t.used for t in tables)) if tables else set(title.used)
    notes, note_used = extract_notes(collected.texts, sheet, cfg, skip=used)
    used |= note_used
    dimensions, tolerance = extract_dimensions(collected)
    misc, confidential = extract_misc(collected.texts, cfg, skip=used)

    try:
        codepage = doc.header.get("$DWGCODEPAGE")
    except Exception:  # noqa: BLE001
        codepage = None
    ir: dict[str, Any] = {
        "schema": IR_SCHEMA,
        "source": {
            "filename": source.get("filename"), "sha256": source.get("sha256"), "format": source.get("format"),
            "acadver": source.get("acadver") or doc.dxfversion, "release": source.get("release"),
            "codepage": codepage, "converter": source.get("converter") or {"name": None},
        },
        "sheet": {
            "size": sheet.paper, "paper_mm": list(sheet.paper_mm) if sheet.paper_mm else None,
            "scale_factor": sheet.scale_factor, "units": sheet.units, "space": sheet.space,
            "extents": [list(sheet.extmin), list(sheet.extmax)],
        },
        "title_block": {
            "method": title.method, "template": title.template, "label_ratio": title.label_ratio,
            "fields": title.fields, "bbox_norm": title.bbox_norm,
        },
        "tables": [
            {"kind": t.kind, "header_pos": t.header_pos, "columns": t.columns, "header_labels": t.header_labels,
             "rows": t.rows, "bbox_norm": t.bbox_norm, "block": t.block}
            for t in tables
        ],
        "notes": notes,
        "dimensions": dimensions,
        "tolerance_summary": tolerance,
        "misc_texts": misc,
        "confidential": confidential,
        "warnings": warnings,
        "images": [],
        "stats": {
            "entity_count": collected.entity_count, "text_count": len(collected.texts),
            "segment_count": len(collected.segments), "extract_ms": int((time.perf_counter() - started) * 1000),
        },
        "versions": {"ir_schema": IR_SCHEMA, "extractor": EXTRACTOR_VERSION, "ezdxf": ezdxf.__version__,
                     "template": title.template},
    }
    ir["metadata"] = build_metadata(ir)
    write_ir(ir, ir_path)
    return ir


def render_regions(ir: dict[str, Any]) -> dict[str, list[float]]:
    regions: dict[str, list[float]] = {}
    if ir["title_block"].get("bbox_norm"):
        regions["title_block"] = ir["title_block"]["bbox_norm"]
    for table in ir["tables"]:
        regions.setdefault(table["kind"], table["bbox_norm"])
    return regions


def render_step(dxf_path: str, ir: dict[str, Any], settings, *, in_process: bool = False) -> RenderResult:
    lo, hi = ir["sheet"]["extents"]
    return render_drawing(
        dxf_path, lo, hi, render_regions(ir),
        max_px=int(getattr(settings, "drawing_render_max_px", 4000)),
        timeout_sec=int(getattr(settings, "drawing_render_timeout_sec", 90)),
        in_process=in_process,
    )


def doc_key_of(ir: dict[str, Any], filename: str) -> str:
    """doc_key = 표제란 품번. 없으면 파일명(확장자 제외)."""
    part_no: Optional[str] = (ir.get("metadata") or {}).get("part_no")
    return (part_no or Path(filename).stem or "drawing").strip()[:200]

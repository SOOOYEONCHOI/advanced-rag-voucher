"""엑셀 → 공통 IR(dict) + 청크 목록 + 이미지 에셋.

설계 문서 요구사항 매핑:
  B-1 시트 분류, B-2 청킹, B-3 병합/수식, B-4 도형 텍스트, B-5 인쇄영역 밖,
  B-6 관리대장 메타, C-1~C-3 이미지 추출/태깅/연결, D-1 VLM 판정, D-2 흐름도 그래프
"""
from __future__ import annotations

import difflib
import hashlib
import re
import warnings
from dataclasses import dataclass, field

import openpyxl

from .ooxml import CellRange, Picture, ShapeText, Workbook, col_letter
from .sheet import (CIRCLED, NumberedTable, Section, collect_fields, classify, find_numbered_table, labeled_row,
                    load_grid, norm, split_sections)

IR_SCHEMA_VERSION = "0.1"
VLM_RULE_VERSION = "0.1"
NOTE_MIN_CHARS = 40
SMALL_IMAGE_BYTES = 15_000
MAX_ROWS_PER_CHUNK = 25


@dataclass
class ParseResult:
    ir: dict
    chunks: list[dict]
    assets: dict[str, dict] = field(default_factory=dict)   # sha256 -> {ext, data, ...}
    warnings: list[str] = field(default_factory=list)


def parse_workbook(path: str, doc_key: str, model: str | None = None) -> ParseResult:
    warnings.filterwarnings("ignore", module="openpyxl")
    wbx = Workbook(path)
    wb_v = openpyxl.load_workbook(path, data_only=True)
    wb_f = openpyxl.load_workbook(path, data_only=False)
    with open(path, "rb") as f:
        file_sha = hashlib.sha256(f.read()).hexdigest()

    pas = wbx.print_areas()
    res = ParseResult(ir={}, chunks=[])
    sheets_ir = []
    register_rows: list[dict] = []

    for sh in wbx.sheets():
        name = sh["name"]
        g = load_grid(wb_v[name], wb_f[name])
        drw = wbx.sheet_drawing(sh["xml"])
        texty = {k for k, v in drw.all_shape_nodes.items() if v["text"]}
        linked = sum(1 for c in drw.connectors if c.start_id in texty and c.end_id in texty)
        stype, reason = classify(g, linked, name)
        print_area = pas.get(sh["index"])

        def in_pa(r, c, _pa=print_area):
            return True if not _pa else any(p.contains_cell(r, c) for p in _pa)

        s_ir = {
            "index": sh["index"] + 1, "name": name, "state": sh["state"], "section_type": stype,
            "classify_reason": reason, "print_area": [p.a1 for p in print_area] if print_area else None,
            "counts": {"cells": len(g.cells), "merged": len(g.merged), "formulas": len(g.formulas),
                       "shapes_with_text": len(drw.shapes), "pictures": len(drw.pictures),
                       "connectors": len(drw.connectors)},
            "hidden_rows": sorted(g.hidden_rows), "hidden_cols": sorted(g.hidden_cols),
            "header_kv": [], "steps": [], "sections": [], "notes": [], "labels": [], "form_controls": [],
            "placements": [], "out_of_print_area": [], "flow_graph": None,
        }

        # ---------- 번호 표 (SOP Step / 흐름도 공정단계) ----------
        table: NumberedTable | None = None
        if stype == "sop":
            table = find_numbered_table(g, ["작업내용"])
        elif stype == "flowchart":
            table = find_numbered_table(g, ["공정단계"])
        table_rows = set()
        if table:
            for n, r1, r2, _ in table.rows:
                table_rows.update(range(r1, r2 + 1))
            table_rows.add(table.header_row)
            for r in range(1, table.header_row):
                cells = g.row_cells(r)
                if cells:
                    s_ir["header_kv"].append({"row": r, "cells": [(f"{col_letter(c)}{r}", v) for c, v in cells]})
            for n, r1, r2, no_text in table.rows:
                fields = collect_fields(g, table, r1, r2)
                title = (fields.get("작업 내용") or fields.get("공정단계") or "").split("\n")[0]
                sub_rows = [{"row": r, "text": labeled_row(g, r, table.header_map)}
                            for r in range(r1, r2 + 1) if g.row_cells(r)]
                s_ir["steps"].append({"no": n, "rows": [r1, r2], "title": title, "fields": fields,
                                      "sub_rows": sub_rows if len(sub_rows) > 1 else [],
                                      "image_ids": [], "markers": [], "callouts": []})

        # ---------- 번호 표 외 영역 섹션 ----------
        rest_rows = [r for r in g.occupied_rows() if r not in table_rows and
                     not (table and r < table.header_row)]
        for sec in split_sections(g, rest_rows):
            rows = [r for r in range(sec.r1, sec.r2 + 1) if g.row_cells(r)]
            lines = [{"row": r, "text": labeled_row(g, r, sec.header_map if sec.header_row and r > sec.header_row else {})}
                     for r in rows if r != sec.header_row]
            s_ir["sections"].append({"rows": [sec.r1, sec.r2], "title": sec.title,
                                     "header_row": sec.header_row,
                                     "header": " | ".join(dict.fromkeys(sec.header_map.values())) if sec.header_map else None,
                                     "lines": lines})

        # ---------- 인쇄영역 밖 셀 (B-5) ----------
        for (r, c), v in sorted(g.cells.items()):
            if not in_pa(r, c):
                s_ir["out_of_print_area"].append({"cell": f"{col_letter(c)}{r}", "kind": "cell", "text": v})

        # ---------- 도형 텍스트 (B-4) ----------
        notes, labels = _split_shapes(drw.shapes, stype)
        for sp in notes:
            link = _link_note(g, sp)
            item = {"shape_id": sp.shape_id, "range": sp.rng.a1, "text": sp.text,
                    "linked_section": link, "in_print_area": in_pa(sp.rng.r1, sp.rng.c1)}
            s_ir["notes"].append(item)
            if not item["in_print_area"]:
                s_ir["out_of_print_area"].append({"cell": sp.rng.a1, "kind": "shape_note", "text": sp.text[:60]})

        # ---------- 폼 컨트롤 ----------
        for fc in wbx.form_controls(sh["xml"]):
            label = None
            if fc.rng:
                near = [s for s in drw.shapes if s.rng.r1 <= fc.rng.r2 and fc.rng.r1 <= s.rng.r2 and
                        0 <= s.rng.c1 - fc.rng.c1 <= 3]
                label = near[0].text if near else None
            s_ir["form_controls"].append({"name": fc.name, "type": fc.obj_type, "checked": fc.checked,
                                          "range": fc.rng.a1 if fc.rng else None, "label": label,
                                          "is_form_default": True})

        # ---------- 이미지 (C-1~C-3, D-1) ----------
        for pic in drw.pictures:
            pl = _placement(pic, g, stype, table, s_ir, labels, in_pa, res)
            if pl:
                s_ir["placements"].append(pl)
        _fix_detail_views(s_ir)
        used_labels = {lid for pl in s_ir["placements"] for lid in pl.pop("_label_ids", [])}
        for lb in labels:
            if lb.shape_id in used_labels:
                continue
            step = _step_at(s_ir, lb.rng.r1)
            s_ir["labels"].append({"shape_id": lb.shape_id, "range": lb.rng.a1, "text": lb.text,
                                   "attached_to": f"step {step['no']}" if step else None})
            if step:
                _add_marker(step, lb.text)

        # ---------- 흐름도 (D-2) ----------
        if stype == "flowchart":
            s_ir["flow_graph"] = _flow_graph(drw, s_ir)

        if stype == "register" and table is None:
            register_rows = _parse_register(g)
            s_ir["register_rows"] = register_rows

        sheets_ir.append(s_ir)

    # ---------- 관리대장 메타 연계 (B-6) ----------
    _apply_register(sheets_ir, register_rows)

    # ---------- VLM 판정 (D-1) ----------
    for sha, a in res.assets.items():
        a["vlm_status"], a["vlm_reason"] = _vlm_decision(a, sheets_ir)

    res.ir = {
        "ir_schema_version": IR_SCHEMA_VERSION,
        "doc": {"doc_key": doc_key, "title": doc_key, "model": model, "source_type": "xlsx",
                "file_sha256": file_sha, "sheet_count": len(sheets_ir)},
        "sections": sheets_ir,
        "assets": {k: {kk: vv for kk, vv in v.items() if kk != "data"} for k, v in res.assets.items()},
    }
    res.chunks = build_chunks(res.ir)
    return res


# ======================================================================
def _split_shapes(shapes: list[ShapeText], stype: str):
    notes, labels = [], []
    for s in shapes:
        if stype == "flowchart":
            continue  # 흐름도 노드는 flow_graph에서 처리
        (notes if len(s.text) >= NOTE_MIN_CHARS or s.text.count("\n") >= 1 and len(s.text) >= 20 else labels).append(s)
    return notes, labels


def _link_note(g, sp: ShapeText) -> dict | None:
    first = sp.text.split("\n")[0]
    for name in re.findall(r"「([^」]+)」", first):
        key = norm(name)
        if len(key) < 2:
            continue
        cands = [(r, c, v) for (r, c), v in g.cells.items() if key in norm(v) and len(v) <= 80]
        if cands:
            r, c, v = min(cands, key=lambda x: abs(x[0] - sp.rng.r1))
            return {"method": "bracket_name", "cell": f"{col_letter(c)}{r}", "text": v.strip()[:60]}
    above = [(r, c, v) for (r, c), v in g.cells.items() if r <= sp.rng.r1 and len(v) <= 40 and
             re.match(r"^\s*([■▣◈]|\d+\.)", v)]
    if above:
        r, c, v = max(above, key=lambda x: x[0])
        return {"method": "nearest_header", "cell": f"{col_letter(c)}{r}", "text": v.strip()[:60]}
    return None


def _step_at(s_ir, row):
    for st in s_ir["steps"]:
        if st["rows"][0] <= row <= st["rows"][1]:
            return st
    return None


def _add_marker(target: dict, text: str):
    t = text.strip()
    if t in ("Q", "S"):
        if t not in target.setdefault("markers", []):
            target["markers"].append(t)
    elif all(ch in CIRCLED for ch in t.replace(" ", "")):
        for ch in t.replace(" ", ""):
            if ch not in target.setdefault("callouts", []):
                target["callouts"].append(ch)


def _placement(pic: Picture, g, stype, table, s_ir, labels, in_pa, res: ParseResult) -> dict | None:
    if not pic.sha256:
        res.warnings.append(f"[{g.name}] 이미지 원본 없음(외부 링크 등): {pic.name} {pic.external_link}")
        return None
    ext = (pic.media_path or "").rsplit(".", 1)[-1].lower()
    a = res.assets.setdefault(pic.sha256, {"image_id": pic.sha256[:16], "ext": ext, "bytes": len(pic.data),
                                           "data": pic.data, "media_path": pic.media_path, "placements": 0,
                                           "needs_conversion": ext in ("emf", "wmf")})
    a["placements"] += 1

    # 겹치는/같은 그룹 라벨 수집
    overlay, lab_ids = [], []
    for lb in labels:
        inside = pic.rng.r1 <= lb.rng.r1 and lb.rng.r2 <= pic.rng.r2 and pic.rng.c1 <= lb.rng.c1 and lb.rng.c2 <= pic.rng.c2
        if (pic.in_group and lb.anchor_key == pic.anchor_key) or (not pic.in_group and inside):
            overlay.append(lb.text)
            lab_ids.append(lb.shape_id)

    role, link, conf, step, row_item = "figure", "nearest_text", 0.4, None, None
    hdr = table.header_map.get(pic.rng.c1, "") if table else ""
    if stype == "sop" and table and table.header_row < pic.rng.r1 <= table.end_row:
        step = _step_at(s_ir, pic.rng.r1)
        if "사진" in hdr:
            role, link, conf = "step_photo", "row_in_step_range", 0.95
        elif "확대" in hdr or "point" in norm(hdr):
            role, link, conf = "detail_view", "row_in_step_range", 0.6
        else:
            role, link, conf = "step_related", "row_in_step_range", 0.7
    elif stype == "list":
        hm = {}
        for (r, c), v in g.cells.items():
            if "사진" in v and r < pic.rng.r1:
                hm = {"row": r, "col": c}
        if hm and abs(pic.rng.c1 - hm["col"]) <= 1:
            role, link, conf = "part_photo", "row_item", 0.95
            row_item = " · ".join(v for c, v in g.row_cells(pic.rng.r1) if c != hm["col"])
    if role == "figure":
        if pic.rng.r1 <= 6 and len(pic.data) < SMALL_IMAGE_BYTES:
            role, conf = "form_header", 0.9
        elif len(pic.data) < SMALL_IMAGE_BYTES and pic.in_group is False and not overlay:
            role, conf = "decoration", 0.6

    if step:
        if a["image_id"] not in step["image_ids"]:
            step["image_ids"].append(a["image_id"])
        for t in overlay:
            _add_marker(step, t)

    ctx = ""
    if step:
        f = step["fields"]
        ctx = " / ".join(x for x in [step["title"], (f.get("Check Point") or "").replace("\n", " ")[:120]] if x)
    elif row_item:
        ctx = row_item
    else:
        near = [(r, c, v) for (r, c), v in g.cells.items() if pic.rng.r1 - 3 <= r <= pic.rng.r2 and len(v) <= 80]
        near.sort(key=lambda x: (abs(x[0] - pic.rng.r1), abs(x[1] - pic.rng.c1)))
        ctx = " / ".join(v.replace("\n", " ") for _, _, v in near[:3])
        link = "nearest_text" if near else "none"

    callouts = [ch for t in overlay for ch in t if ch in CIRCLED]
    markers = [t.strip() for t in overlay if t.strip() in ("Q", "S")]
    others = [t for t in overlay if t.strip() not in ("Q", "S") and not all(ch in CIRCLED for ch in t.strip())]
    return {
        "image_id": a["image_id"], "sha256": pic.sha256, "section_type": stype, "shape": pic.name, "cell_range": pic.rng.a1,
        "anchor_type": pic.anchor_type, "in_group": pic.in_group, "in_print_area": in_pa(pic.rng.r1, pic.rng.c1),
        "role": role, "column_header": hdr or None,
        "step_no": step["no"] if step else None, "step_title": step["title"] if step else None,
        "row_item": row_item, "callouts": sorted(set(callouts)), "markers": sorted(set(markers)),
        "overlay_texts": others, "context_text": ctx[:200], "link_method": link, "confidence": conf,
        "review_status": "needs_review" if conf < 0.7 and role not in ("decoration", "form_header") else "auto",
        "crop": pic.crop, "_label_ids": lab_ids,
    }


def _fix_detail_views(s_ir):
    """C-3 4단계: 확대도 이미지가 다른 Step의 사진과 같은 파일이면 그 Step으로 보정"""
    photo_step = {p["sha256"]: p["step_no"] for p in s_ir["placements"] if p["role"] == "step_photo"}
    steps = {st["no"]: st for st in s_ir["steps"]}
    for p in s_ir["placements"]:
        if p["role"] != "detail_view":
            continue
        tgt = photo_step.get(p["sha256"])
        if tgt is not None and tgt != p["step_no"]:
            old = steps.get(p["step_no"])
            if old and p["image_id"] in old["image_ids"]:
                old["image_ids"].remove(p["image_id"])
            p["step_no"], p["step_title"] = tgt, steps[tgt]["title"]
            p["link_method"], p["confidence"], p["review_status"] = "same_image_as_step_photo", 0.85, "auto"
            if p["image_id"] not in steps[tgt]["image_ids"]:
                steps[tgt]["image_ids"].append(p["image_id"])


def _flow_graph(drw, s_ir) -> dict:
    nodes = {sid: n for sid, n in drw.all_shape_nodes.items() if n["text"]}
    labels = {sid: n for sid, n in nodes.items() if n["text"].strip().upper() in ("OK", "NG")}
    for sid in labels:
        nodes.pop(sid)
    out_nodes = []
    for sid, n in nodes.items():
        st = _step_at(s_ir, n["rng"].r1)
        out_nodes.append({"id": sid, "text": re.sub(r"\s*\n\s*", " ", n["text"]), "geom": n["geom"],
                          "range": n["rng"].a1, "stage_no": st["no"] if st else None,
                          "stage": st["title"] if st else None})
    edges, unresolved = [], []
    for cx in drw.connectors:
        a, b = cx.start_id, cx.end_id
        if cx.head and cx.head != "none" and not (cx.tail and cx.tail != "none"):
            a, b = b, a     # 화살표가 시작점에 있으면 방향 반전
        if a in nodes and b in nodes:
            edges.append({"from": a, "to": b, "source": "xml", "verified": False})
        else:
            unresolved.append({"connector": cx.shape_id, "from": nodes.get(a, {}).get("text"),
                               "to": nodes.get(b, {}).get("text"), "range": cx.rng.a1})
    connected = {e["from"] for e in edges} | {e["to"] for e in edges}
    return {
        "nodes": out_nodes, "edges": edges, "unresolved_connectors": unresolved,
        "isolated_nodes": [n["id"] for n in out_nodes if n["id"] not in connected],
        "edge_label_shapes": [{"id": k, "text": v["text"], "range": v["rng"].a1} for k, v in labels.items()],
        "source_hash": drw.drawing_hash, "vlm_status": "pending(required)", "review_status": "needs_review",
    }


def _parse_register(g) -> list[dict]:
    hdr = g.find(lambda v: norm(v) == "공정명")
    if not hdr:
        return []
    r0, cname, _ = hdr[0]
    est = [c for (r, c), v in g.cells.items() if r == r0 and norm(v) == "제정일"]
    rev_row = r0 + 1
    rev_cols = sorted((c, v) for (r, c), v in g.cells.items() if r == rev_row and re.fullmatch(r"\d+차", v))
    out = []
    for r in range(r0 + 1, max(r for r, _ in g.cells) + 1):
        name = g.cells.get((r, cname))
        if not name or name in ("1차",):
            continue
        revs = [(lbl, g.cells.get((r, c))) for c, lbl in rev_cols if g.cells.get((r, c))]
        out.append({"process_name": name, "established": g.cells.get((r, est[0])) if est else None,
                    "revision_no": revs[-1][0] if revs else None, "revision_date": revs[-1][1] if revs else None})
    return out


def _apply_register(sheets_ir, rows):
    keys = {norm(s["name"]): s for s in sheets_ir}
    for row in rows:
        k = norm(row["process_name"])
        best = difflib.get_close_matches(k, list(keys), n=1, cutoff=0.72)
        if best:
            keys[best[0]]["revision"] = {**row, "match": best[0] == k and "exact" or "fuzzy"}


def _vlm_decision(asset, sheets_ir) -> tuple[str, str]:
    """D-1 VLM 선택 적용 규칙 (판정만 수행, 실제 VLM 호출은 비동기 큐 담당)"""
    pls = [p for s in sheets_ir for p in s["placements"] if p["image_id"] == asset["image_id"]]
    roles = {p["role"] for p in pls}
    if not pls or roles <= {"decoration", "form_header"}:
        return "skipped", "장식/양식 헤더"
    if any(p["role"] == "figure" and p["section_type"] in ("inspection", "reference", "other") for p in pls):
        return "pending", "성적서·체크시트 내 그림(도면·캡처 추정)"
    if all(p["confidence"] < 0.7 for p in pls):
        return "pending", "텍스트 연결 신뢰도 낮음"
    if all(len(p["context_text"]) < 20 for p in pls):
        return "pending", "주변 텍스트 부족"
    return "skipped", "텍스트 연결 충분"


# ======================================================================
def build_chunks(ir: dict) -> list[dict]:
    doc, model = ir["doc"], ir["doc"].get("model") or ""
    chunks = []

    def add(sheet, kind, block, text, meta=None):
        chunks.append({"chunk_id": f"{doc['doc_key']}:{sheet['index']:02d}:{kind}:{block}",
                       "sheet": sheet["name"], "content_type": kind, "text": text.strip(), "meta": meta or {}})

    for s in ir["sections"]:
        path = f"[{model} > {s['name']}".replace("[ > ", "[")
        rev = s.get("revision")
        rev_txt = f" (개정 {rev['revision_no']} {rev['revision_date']})" if rev and rev.get("revision_no") else ""
        base_meta = {"section_type": s["section_type"], "revision": rev.get("revision_no") if rev else None}
        if s["section_type"] == "register":
            continue
        # 헤더 KV + Step 목록 요약
        if s["steps"]:
            kv = "\n".join(" | ".join(v for _, v in h["cells"]) for h in s["header_kv"])
            step_list = "\n".join(f"{st['no']}. {st['title']}" for st in s["steps"])
            label = "Step" if s["section_type"] == "sop" else "공정단계"
            add(s, "summary", "0", f"{path}{rev_txt} > 개요]\n{kv}\n{label} 목록:\n{step_list}", base_meta)
            for i, st in enumerate(s["steps"]):
                if st.get("sub_rows"):
                    body = "\n".join(f"- {x['text']}" for x in st["sub_rows"])
                else:
                    body = "\n".join(f"{k}: {v.replace(chr(10), ' / ')}" for k, v in st["fields"].items())
                extra = []
                if st.get("markers"):
                    extra.append("표시: " + ", ".join({"Q": "Q(품질)", "S": "S(안전)"}[m] for m in st["markers"]))
                prev_ = s["steps"][i - 1]["title"] if i > 0 else None
                next_ = s["steps"][i + 1]["title"] if i + 1 < len(s["steps"]) else None
                add(s, "step" if s["section_type"] == "sop" else "flow_stage", str(st["no"]),
                    f"{path} > {label} {st['no']}. {st['title']}]\n{body}\n" + "\n".join(extra),
                    {**base_meta, "step_no": st["no"], "prev": prev_, "next": next_, "image_ids": st["image_ids"],
                     "callouts": st.get("callouts", []), "markers": st.get("markers", [])})
        # 일반 섹션
        for si, sec in enumerate(s["sections"]):
            lines = sec["lines"]
            for part in range(0, max(1, len(lines)), MAX_ROWS_PER_CHUNK):
                seg = lines[part:part + MAX_ROWS_PER_CHUNK]
                if not seg:
                    continue
                head = f"{path} > {sec['title'] or '행 ' + str(sec['rows'][0])}]"
                hdr = f"\n(열: {sec['header']})" if sec["header"] else ""
                body = "\n".join(l["text"] for l in seg)
                add(s, "table_section", f"{si}.{part // MAX_ROWS_PER_CHUNK}", f"{head}{hdr}\n{body}",
                    {**base_meta, "rows": [seg[0]["row"], seg[-1]["row"]]})
        # 안내문 도형
        for n in s["notes"]:
            title = n["text"].split("\n")[0][:40]
            add(s, "guide_note", n["shape_id"], f"{path} > 작성 안내: {title}]\n{n['text']}",
                {**base_meta, "shape_range": n["range"], "in_print_area": n["in_print_area"],
                 "linked_section": n["linked_section"]})
        # 폼 컨트롤
        if s["form_controls"]:
            txt = " ".join(("☑" if f["checked"] else "☐") + (f["label"] or f["name"]) for f in s["form_controls"])
            add(s, "form_control", "0", f"{path} > 양식 체크박스]\n{txt}", {**base_meta, "is_form_default": True})
        # 흐름도
        fg = s.get("flow_graph")
        if fg:
            names = {n["id"]: n["text"] for n in fg["nodes"]}
            seq = "\n".join(f"{names[e['from']]} → {names[e['to']]}" for e in fg["edges"])
            add(s, "flow_overview", "0",
                f"{path} > 공정 흐름(XML 확정 연결, 검수 전)]\n{seq}\n※ 미연결 {len(fg['unresolved_connectors'])}건은 VLM 보강 필요",
                {**base_meta, "vlm_status": fg["vlm_status"]})
        # 이미지 청크
        for p in s["placements"]:
            if p["role"] in ("decoration", "form_header"):
                continue
            where = f"Step {p['step_no']} {p['step_title']}" if p["step_no"] else (p["row_item"] or p["cell_range"])
            marks = " ".join(p["callouts"] + p["markers"] + p["overlay_texts"])
            add(s, "image", f"{p['image_id']}@{p['cell_range']}",
                f"{path} > {where}] 이미지({p['role']}) {marks}\n{p['context_text']}",
                {**base_meta, "image_id": p["image_id"], "role": p["role"], "confidence": p["confidence"]})
    return chunks

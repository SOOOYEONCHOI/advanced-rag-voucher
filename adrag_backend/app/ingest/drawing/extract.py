"""도면 항목 추출 — 표제란·표(부품표·개정이력)·주기·치수·기타 글자 (2026.11.12(sooyeon.choi) 도면 파싱 기능 추가).

표제란 순서: ① ATTRIB 태그 → ② 양식 템플릿 영역 안 라벨 인접(값 방향: 아래/오른쪽) → ③ 도면 전체 라벨 인접.
표: 블록별로 문자·선을 모아 표 선으로 행·열 경계를 정하고, 셀 안 여러 줄 문자를 합친 뒤 머리글 별칭으로 열을 맞춘다.
머리글이 맨 위면 부품표처럼 아래로, 맨 아래면 개정이력처럼 위로 데이터 행이 있다.
"""
from __future__ import annotations

import bisect
import re
import statistics
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Optional

import yaml

from .common import warning
from .reader import Collected, Segment, Sheet, TextItem
from .textcodes import label_key

DEFAULT_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


@lru_cache(maxsize=4)
def load_config(template_dir: str = "") -> dict[str, Any]:
    base = Path(template_dir) if template_dir else DEFAULT_TEMPLATE_DIR
    with open(base / "default.yaml", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


# ── 공통 ─────────────────────────────────────────────────────────────

def _alias_index(aliases: dict[str, list[str]]) -> list[tuple[str, str]]:
    pairs = {(label_key(a), key) for key, values in aliases.items() for a in values}
    return sorted(pairs, key=lambda p: -len(p[0]))


def _match(value: str, index: list[tuple[str, str]]) -> Optional[str]:
    key = label_key(value)
    if not key:
        return None
    for alias, field_key in index:
        if key == alias:
            return field_key
    return None


def _median_h(texts: Iterable[TextItem], default: float = 2.5) -> float:
    heights = [t.h for t in texts if t.h > 0]
    return statistics.median(heights) if heights else default


def _cluster(values: list[float], tol: float) -> list[float]:
    out: list[list[float]] = []
    for v in sorted(values):
        if out and v - out[-1][-1] <= tol:
            out[-1].append(v)
        else:
            out.append([v])
    return [sum(group) / len(group) for group in out]


# ── 표제란 ───────────────────────────────────────────────────────────

@dataclass
class TitleResult:
    fields: dict[str, str] = field(default_factory=dict)
    method: str = "none"
    template: Optional[str] = None
    label_ratio: float = 0.0
    bbox_norm: Optional[list[float]] = None
    used: set[int] = field(default_factory=set)      # 사용한 문자 id(기타 글자에서 제외)


def _in_region(t: TextItem, region: list[float]) -> bool:
    return region[0] <= t.nx <= region[2] and region[1] <= t.ny <= region[3]


def _value_candidates(label: TextItem, pool: list[TextItem], direction: str) -> list[tuple[float, TextItem]]:
    h = max(label.h, 0.1)
    found = []
    for t in pool:
        if t is label:
            continue
        if direction in ("below", "auto"):
            gap = label.y0 - t.y1
            overlap = min(label.x1 + 2 * h, t.x1) - max(label.x0 - 2 * h, t.x0)
            if -0.6 * h <= gap <= 4.5 * h and t.y < label.y and overlap > 0:
                found.append((gap + 0.2 * abs(t.x0 - label.x0), t))
        if direction in ("right", "auto"):
            gap = t.x0 - label.x1
            if abs(t.y - label.y) <= 0.7 * max(h, t.h) and -0.5 * h <= gap <= 25 * h:
                found.append((gap + (0.5 * h if direction == "auto" else 0.0), t))
    return found


def _assign(labels: list[tuple[str, TextItem]], pool: list[TextItem], direction: str, label_ids: set[int]):
    """라벨-값 후보를 거리순으로 겹치지 않게 짝짓는다."""
    pairs = []
    values = [t for t in pool if id(t) not in label_ids]
    for field_key, label in labels:
        for score, cand in _value_candidates(label, values, direction):
            pairs.append((score, field_key, label, cand))
    pairs.sort(key=lambda p: p[0])
    taken_fields: set[str] = set()
    taken_values: set[int] = set()
    out: dict[str, TextItem] = {}
    for _, field_key, _, cand in pairs:
        if field_key in taken_fields or id(cand) in taken_values:
            continue
        out[field_key] = cand
        taken_fields.add(field_key)
        taken_values.add(id(cand))
    return out


def _inline_value(text: str, index) -> Optional[tuple[str, str]]:
    """'PART NO: S123'처럼 라벨과 값이 한 문자에 있는 경우."""
    for sep in (":", "："):
        if sep in text:
            head, _, tail = text.partition(sep)
            key = _match(head, index)
            if key and tail.strip():
                return key, tail.strip()
    return None


def extract_title(texts: list[TextItem], sheet: Sheet, cfg: dict[str, Any]) -> tuple[TitleResult, list[dict]]:
    index = _alias_index(cfg["title_fields"])
    result = TitleResult()
    warnings: list[dict] = []

    for t in texts:  # ① ATTRIB 태그
        if t.tag:
            key = _match(t.tag, index)
            if key and key not in result.fields and t.text:
                result.fields[key] = t.text.replace("\n", " ")
                result.used.add(id(t))
    if result.fields:
        result.method = "attrib"

    def label_scan(pool: list[TextItem], direction: str) -> tuple[dict[str, TextItem], list[tuple[str, TextItem]]]:
        labels: list[tuple[str, TextItem]] = []
        for t in pool:
            key = _match(t.text, index)
            if key:
                labels.append((key, t))
            else:
                inline = _inline_value(t.text, index)
                if inline and inline[0] not in result.fields:
                    result.fields[inline[0]] = inline[1]
                    result.used.add(id(t))
        label_ids = {id(t) for _, t in labels}
        return _assign(labels, pool, direction, label_ids), labels

    chosen = None
    for template in cfg.get("templates") or []:  # ② 양식 템플릿
        region = template["title_region"]
        pool = [t for t in texts if _in_region(t, region) and id(t) not in result.used]
        found, labels = label_scan(pool, template.get("value_direction", "below"))
        if len(found) < len(labels):  # 지정 방향에 값이 없는 라벨은 반대 방향도 본다
            extra, _ = label_scan(pool, "auto")
            for k, v in extra.items():
                if k not in found and id(v) not in {id(x) for x in found.values()}:
                    found[k] = v
        ratio = len({k for k, _ in labels}) / max(len(cfg["title_fields"]), 1)
        if chosen is None or ratio > chosen[0]:
            chosen = (ratio, template, found, labels)
    if chosen and chosen[0] >= chosen[1].get("min_label_ratio", 0.5):
        ratio, template, found, labels = chosen
        result.method = f"template:{template['name']}"
        result.template = template["name"]
        result.label_ratio = round(ratio, 3)
        result.bbox_norm = list(template["title_region"])
    else:
        if chosen:
            warnings.append(warning("W_TEMPLATE_MISMATCH", "등록된 표제란 양식과 일치율이 낮아 라벨 주변 방식으로 읽었습니다.",
                                    ratio=round(chosen[0], 3)))
            result.label_ratio = round(chosen[0], 3)
        found, labels = label_scan([t for t in texts if id(t) not in result.used], "auto")  # ③ 전체
        if labels and result.method == "none":
            result.method = "label"
        if labels:
            xs = [t.nx for _, t in labels] + [v.nx for v in found.values()]
            ys = [t.ny for _, t in labels] + [v.ny for v in found.values()]
            result.bbox_norm = [round(min(xs), 4), round(min(ys), 4), round(max(xs), 4), round(max(ys), 4)]

    for key, value in found.items():
        result.fields.setdefault(key, value.text.replace("\n", " "))
        result.used.add(id(value))
    for _, label in labels:
        result.used.add(id(label))

    rev = result.fields.get("revision")
    if rev:
        m = re.fullmatch(r"\s*([A-Za-z]{1,2}|\d{1,3})\s*[.\-]\s*(\d{1,3})\s*", rev)
        result.fields["rev_major"] = m.group(1).upper() if m else rev.strip()
        if m:
            result.fields["rev_iter"] = m.group(2)
    missing = [k for k in cfg.get("required_fields", []) if not result.fields.get(k)]
    if missing:
        names = {"part_no": "품번", "part_name": "품명", "revision": "개정"}
        warnings.append(warning("W_TITLE_MISSING",
                                f"표제란 필수 항목({'·'.join(names.get(k, k) for k in missing)})을 찾지 못했습니다.",
                                missing=missing))
    return result, warnings


# ── 표 ─────────────────────────────────────────────────────────────

@dataclass
class TableResult:
    kind: str
    header_pos: str
    columns: list[str]
    header_labels: list[str]
    rows: list[dict[str, str]]
    block: Optional[str]
    bbox_norm: list[float]
    used: set[int] = field(default_factory=set)


def _grid(segments: list[Segment], h: float) -> tuple[list[float], list[float]]:
    tol = max(h * 0.25, 1e-6)
    xs, ys = [], []
    for s in segments:
        if abs(s.x1 - s.x2) <= tol and abs(s.y1 - s.y2) > tol:
            xs.append((s.x1 + s.x2) / 2)
        elif abs(s.y1 - s.y2) <= tol and abs(s.x1 - s.x2) > tol:
            ys.append((s.y1 + s.y2) / 2)
    return _cluster(xs, h * 0.5), _cluster(ys, h * 0.5)


def _cell_text(items: list[TextItem]) -> str:
    items = sorted(items, key=lambda t: (-round(t.y, 3), t.x))
    return " ".join(t.text.replace("\n", " ") for t in items).strip()


def _rows_by_grid(texts: list[TextItem], xs: list[float], ys: list[float]) -> list[list[list[TextItem]]]:
    ncols, nrows = len(xs) - 1, len(ys) - 1
    grid: list[list[list[TextItem]]] = [[[] for _ in range(ncols)] for _ in range(nrows)]
    for t in texts:
        c = bisect.bisect_right(xs, t.x) - 1
        r = bisect.bisect_right(ys, t.y) - 1
        if 0 <= c < ncols and 0 <= r < nrows:
            grid[r][c].append(t)
    grid.reverse()  # 위 → 아래
    return grid


def _rows_by_text(texts: list[TextItem], h: float) -> list[list[TextItem]]:
    rows: list[list[TextItem]] = []
    for t in sorted(texts, key=lambda t: -t.y):
        if rows and abs(rows[-1][0].y - t.y) <= 0.6 * h:
            rows[-1].append(t)
        else:
            rows.append([t])
    return rows


def parse_table(texts: list[TextItem], segments: list[Segment], kind: str, aliases: dict[str, list[str]],
                required: list[str], sheet: Sheet, block: Optional[str]) -> Optional[TableResult]:
    if len(texts) < 2:
        return None
    index = _alias_index(aliases)
    h = _median_h(texts)
    xs, ys = _grid(segments, h)
    cells_rows: list[list[str]]
    cell_items: list[list[list[TextItem]]]
    if len(xs) >= 3 and len(ys) >= 3:
        cell_items = _rows_by_grid(texts, xs, ys)
        cells_rows = [[_cell_text(c) for c in row] for row in cell_items]
    else:
        text_rows = _rows_by_text(texts, h)
        header_idx = max(range(len(text_rows)), key=lambda i: sum(1 for t in text_rows[i] if _match(t.text, index)))
        header = sorted(text_rows[header_idx], key=lambda t: t.x)
        bounds = [(t.x0, t.x1) for t in header]
        cell_items = []
        for row in text_rows:
            cols: list[list[TextItem]] = [[] for _ in header]
            for t in row:
                c = min(range(len(header)), key=lambda i: 0 if bounds[i][0] - h <= t.x <= bounds[i][1] + h
                        else abs(t.x - (bounds[i][0] + bounds[i][1]) / 2))
                cols[c].append(t)
            cell_items.append(cols)
        cells_rows = [[_cell_text(c) for c in row] for row in cell_items]

    best = None
    for i, row in enumerate(cells_rows):
        mapped = {c: _match(v, index) for c, v in enumerate(row)}
        mapped = {c: k for c, k in mapped.items() if k}
        if len(mapped) >= 2 and (best is None or len(mapped) > len(best[1])):
            best = (i, mapped)
    if best is None:
        return None
    header_idx, colmap = best
    keys = set(colmap.values())
    if not all(k in keys for k in required):
        return None
    nonempty = [i for i, row in enumerate(cells_rows) if any(row)]
    if header_idx == nonempty[0]:
        header_pos, data_idx = "top", [i for i in nonempty if i > header_idx]
    elif header_idx == nonempty[-1]:
        header_pos, data_idx = "bottom", [i for i in nonempty if i < header_idx]
    else:
        header_pos, data_idx = "top", [i for i in nonempty if i > header_idx]
    columns = [colmap[c] for c in sorted(colmap)]
    rows = []
    for i in data_idx:
        record = {colmap[c]: cells_rows[i][c] for c in sorted(colmap) if c < len(cells_rows[i])}
        if not any(record.values()) or _match(" ".join(record.values()), index):
            continue
        rows.append(record)
    xs_all = [t.nx for t in texts]
    ys_all = [t.ny for t in texts]
    used = {id(t) for row in cell_items for cell in row for t in cell}
    return TableResult(
        kind=kind, header_pos=header_pos, columns=columns,
        header_labels=[cells_rows[header_idx][c] for c in sorted(colmap)], rows=rows, block=block,
        bbox_norm=[round(min(xs_all), 4), round(min(ys_all), 4), round(max(xs_all), 4), round(max(ys_all), 4)],
        used=used,
    )


def extract_tables(collected: Collected, sheet: Sheet, cfg: dict[str, Any], skip: set[int]) -> tuple[list[TableResult], list[dict]]:
    table_cfg = cfg["tables"]
    groups: dict[Optional[str], tuple[list[TextItem], list[Segment]]] = {}
    for t in collected.texts:
        if id(t) not in skip:
            groups.setdefault(t.block, ([], []))[0].append(t)
    for s in collected.segments:
        if s.block in groups:
            groups[s.block][1].append(s)
    tables: list[TableResult] = []
    warnings: list[dict] = []
    # 표 블록을 먼저 본다. 같은 종류·같은 머리글 표가 블록에서 이미 나왔으면 모델공간에서 다시 잡힌 표는 버린다
    # (블록 내용이 모델공간에 새어 나온 손상 파일에서 같은 표가 두 번 잡히는 것을 막는다)
    for block, (texts, segs) in sorted(groups.items(), key=lambda item: item[0] is None):
        header_seen, parsed = False, False
        for kind in ("bom", "revision"):
            aliases = table_cfg[kind]
            index = _alias_index(aliases)
            if sum(1 for t in texts if _match(t.text, index)) < 2:
                continue
            header_seen = True
            table = parse_table(texts, segs, kind, aliases, table_cfg["required"][kind], sheet, block)
            if table and block is None and any(
                    t.kind == kind and [label_key(h) for h in t.header_labels] == [label_key(h) for h in table.header_labels]
                    for t in tables):
                parsed = True
                continue
            if table:
                parsed = True
                tables.append(table)
                texts = [t for t in texts if id(t) not in table.used]
        # 머리글 별칭은 맞는데 어떤 표로도 복원하지 못한 표 블록만 경고한다
        if block is not None and header_seen and not parsed and "TABLE" in block.upper():
            warnings.append(warning("W_TABLE_PARSE", "표 머리글은 찾았지만 행·열을 복원하지 못했습니다.", block=block))
    return tables, warnings


# ── 주기·치수·기타 ────────────────────────────────────────────────────

def extract_notes(texts: list[TextItem], sheet: Sheet, cfg: dict[str, Any], skip: set[int]) -> tuple[dict[str, Any], set[int]]:
    ncfg = cfg["notes"]
    heads = {label_key(h) for h in ncfg["headings"]}
    pool = [t for t in texts if id(t) not in skip]
    used: set[int] = set()
    lines: list[str] = []
    for head in pool:
        first, *rest = head.text.split("\n")
        key = label_key(first)
        start = next((hk for hk in heads if key == hk or key.startswith(hk)), None)
        if start is None:
            continue
        used.add(id(head))
        tail =re.sub(r"^\s*(notes?|주\s*기|비고)\s*[:：]?\s*", "", first, flags=re.IGNORECASE)
        if tail and tail != first:
            lines.append(tail)
        lines.extend(rest)
        exclude = [re.compile(p, re.IGNORECASE) for p in cfg["exclude"]["patterns"]]
        below = [
            t for t in pool
            if t is not head and id(t) not in used and t.y < head.y
            and head.x0 - 2 * head.h <= t.x0 <= head.x0 + 0.45 * sheet.width
            and head.y - t.y <= 0.35 * sheet.height
            and not any(p.search(t.text.strip()) for p in exclude)
        ]
        bottom = head.y0
        for t in sorted(below, key=lambda t: (-t.y, t.x)):
            if bottom - t.y1 > 3 * max(head.h, t.h):  # 주기 블록과 떨어진 문자는 다른 내용
                break
            lines.extend(t.text.split("\n"))
            used.add(id(t))
            bottom = min(bottom, t.y0)
        break
    items: list[str] = []
    for line in lines:
        m = re.match(r"^\s*(\d{1,2})\s*[.)]\s*(.*)$", line)
        if m:
            items.append(m.group(2).strip())
        elif items:
            items[-1] = f"{items[-1]} {line.strip()}".strip()
        elif line.strip():
            items.append(line.strip())

    all_text = "\n".join(t.text for t in texts)
    tol = re.search(ncfg["general_tolerance"], all_text, flags=re.IGNORECASE)
    memos: list[str] = []
    memo_re = re.compile(ncfg["spec_memo"])
    for t in texts:
        parts = t.text.split("\n")
        for i, line in enumerate(parts):
            if memo_re.search(line):
                memos.extend(p for p in parts[i:i + 6] if p not in memos)
                used.add(id(t))
                break
    return {
        "items": items,
        "general_tolerance": re.sub(r"\s+", " ", tol.group(1)).strip() if tol else None,
        "spec_memos": memos,
    }, used


_TOL_RE = re.compile(r"(±|\+\s*\d|-\s*\d+(\.\d+)?\s*$|[A-Za-z]\d{1,2}\b)")


def extract_dimensions(collected: Collected) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    dims = [d for d in collected.dimensions if d.get("text")]
    by_block: dict[str, list[TextItem]] = {}
    for t in collected.dim_texts:
        by_block.setdefault(t.block or "", []).append(t)
    for items in by_block.values():
        text = _cell_text(items)
        if text:
            dims.append({"text": text, "measured": None, "reference": bool(re.fullmatch(r"\(.*\)", text))})
    specified = sum(1 for d in dims if _TOL_RE.search(d["text"].replace("Ø", "")))
    return dims, {"specified": specified, "general_tolerance_only": specified == 0}


def extract_misc(texts: list[TextItem], cfg: dict[str, Any], skip: set[int]) -> tuple[list[str], bool]:
    patterns = [re.compile(p, re.IGNORECASE) for p in cfg["exclude"]["patterns"]]
    confidential_re = re.compile(cfg["exclude"]["confidential"], re.IGNORECASE)
    confidential = any(confidential_re.search(t.text.strip()) for t in texts)
    out: list[str] = []
    for t in sorted(texts, key=lambda t: (-t.y, t.x)):
        if id(t) in skip:
            continue
        value = t.text.replace("\n", " ").strip()
        if len(value) < 2 or re.fullmatch(r"[\d.,\s()Øø°±+\-]+", value):
            continue
        if any(p.search(value) for p in patterns):
            continue
        if value not in out:
            out.append(value)
    return out, confidential

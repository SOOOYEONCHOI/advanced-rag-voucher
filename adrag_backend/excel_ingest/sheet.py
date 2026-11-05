"""셀 그리드 처리: 값 정규화, 병합셀, 섹션 분할, 헤더 라벨링, 시트 유형 분류, SOP Step 표 인식."""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from .ooxml import CellRange, col_letter

CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"


def norm(s: str) -> str:
    """매칭용 정규화: 공백·기호 제거, 소문자"""
    return re.sub(r"[\s　■▣◈※·\-_/()（）\[\]「」'\"`.,:]", "", str(s)).lower()


def fmt_value(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, dt.datetime):
        return v.date().isoformat() if v.time() == dt.time(0) else v.isoformat(sep=" ")
    if isinstance(v, dt.date):
        return v.isoformat()
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() else f"{v:g}"
    s = str(v).replace("\r\n", "\n").replace("\t", " ").strip()
    return s or None


@dataclass
class Grid:
    """시트의 비어있지 않은 셀(병합 영역은 좌상단 anchor 1개)"""
    name: str
    cells: dict[tuple[int, int], str] = field(default_factory=dict)
    merged: dict[tuple[int, int], CellRange] = field(default_factory=dict)   # anchor -> 범위
    formulas: dict[tuple[int, int], str] = field(default_factory=dict)
    hidden_rows: set[int] = field(default_factory=set)
    hidden_cols: set[int] = field(default_factory=set)

    def span(self, r: int, c: int) -> CellRange:
        return self.merged.get((r, c), CellRange(r, c, r, c))

    def row_cells(self, r: int) -> list[tuple[int, str]]:
        return sorted((c, v) for (rr, c), v in self.cells.items() if rr == r)

    def occupied_rows(self) -> list[int]:
        rows = set()
        for (r, c) in self.cells:
            sp = self.span(r, c)
            rows.update(range(sp.r1, sp.r2 + 1))
        return sorted(rows)

    def find(self, pred) -> list[tuple[int, int, str]]:
        return sorted((r, c, v) for (r, c), v in self.cells.items() if pred(v))


def load_grid(ws_values, ws_formulas) -> Grid:
    g = Grid(ws_values.title)
    for mr in ws_values.merged_cells.ranges:
        g.merged[(mr.min_row, mr.min_col)] = CellRange(mr.min_row, mr.min_col, mr.max_row, mr.max_col)
    for row in ws_values.iter_rows():
        for c in row:
            v = fmt_value(c.value)
            if v is not None:
                g.cells[(c.row, c.column)] = v
    for row in ws_formulas.iter_rows():
        for c in row:
            if isinstance(c.value, str) and c.value.startswith("="):
                g.formulas[(c.row, c.column)] = c.value
                if (c.row, c.column) not in g.cells:
                    g.cells[(c.row, c.column)] = f"[수식 캐시값 없음] {c.value}"
    g.hidden_rows = {i for i, d in ws_values.row_dimensions.items() if d.hidden}
    for key, d in ws_values.column_dimensions.items():
        if d.hidden:
            from openpyxl.utils import column_index_from_string
            lo = column_index_from_string(key)
            g.hidden_cols.update(range(d.min or lo, (d.max or lo) + 1))
    return g


# ---------------- 섹션 분할 ----------------
@dataclass
class Section:
    r1: int
    r2: int
    title: str | None = None
    header_row: int | None = None
    header_map: dict[int, str] = field(default_factory=dict)  # col -> 헤더 텍스트


def split_sections(g: Grid, rows: list[int] | None = None, gap: int = 2) -> list[Section]:
    rows = rows if rows is not None else g.occupied_rows()
    if not rows:
        return []
    out, start, prev = [], rows[0], rows[0]
    for r in rows[1:]:
        if r - prev > gap:
            out.append(Section(start, prev))
            start = r
        prev = r
    out.append(Section(start, prev))
    for s in out:
        _detect_header(g, s)
    return out


def _is_texty(v: str) -> bool:
    return not re.fullmatch(r"[\d.\s,%/-]+", v) and len(v) <= 40


def _detect_header(g: Grid, s: Section):
    for r in range(s.r1, min(s.r2, s.r1 + 3) + 1):
        cells = g.row_cells(r)
        if len(cells) >= 3 and sum(_is_texty(v) for _, v in cells) >= max(3, int(len(cells) * 0.7)):
            s.header_row = r
            s.header_map = header_map(g, r)
            nxt = r + 1
            # 2단 헤더(상위 병합 + 하위 세부) 보강
            sub = g.row_cells(nxt)
            if nxt <= s.r2 and len(sub) >= 2 and all(_is_texty(v) for _, v in sub) and \
                    any(g.span(r, c).c2 > g.span(r, c).c1 for c, _ in g.row_cells(r)):
                for c, v in sub:
                    sp = g.span(nxt, c)
                    for cc in range(sp.c1, sp.c2 + 1):
                        s.header_map[cc] = f"{s.header_map[cc]} / {v}" if cc in s.header_map else v
                s.header_row = nxt
            break
    first = g.row_cells(s.r1)
    if s.header_row != s.r1 and first:
        s.title = " ".join(v for _, v in first)[:80]


def header_map(g: Grid, r: int) -> dict[int, str]:
    m = {}
    for c, v in g.row_cells(r):
        sp = g.span(r, c)
        for cc in range(sp.c1, sp.c2 + 1):
            m[cc] = v.replace("\n", " ")
    return m


def labeled_row(g: Grid, r: int, hmap: dict[int, str]) -> str:
    parts = []
    for c, v in g.row_cells(r):
        v1 = v.replace("\n", " / ")
        h = hmap.get(c)
        parts.append(f"{h}: {v1}" if h and h != v else v1)
    return " · ".join(parts)


# ---------------- 시트 유형 분류 ----------------
INSPECTION_KWS = ["판정", "합격", "불합격", "규격", "spec", "검사", "검수", "check", "측정", "성적서"]


def classify(g: Grid, n_linked_connectors: int, sheet_name: str) -> tuple[str, str]:
    """B-1 규칙 기반 시트 분류. 반환: (유형, 판별 근거)"""
    texts = [norm(v) for (r, c), v in g.cells.items() if r <= 40 and len(v) <= 30]

    def hits(kws):
        return [k for k in kws if any(k == t or (len(k) > 2 and k in t) for t in texts)]

    sop = hits(["no", "사진", "작업내용", "checkpoint"])
    if len(sop) >= 3:
        return "sop", "헤더 키워드: " + ", ".join(sop)
    if n_linked_connectors >= 8:
        return "flowchart", f"도형 간 연결선 {n_linked_connectors}개"
    reg = hits(["제정일", "개정일", "공정명"])
    if len(reg) >= 3:
        return "register", "헤더 키워드: " + ", ".join(reg)
    if "list" in norm(sheet_name):
        return "list", "시트명에 LIST 포함"
    if "기준" in sheet_name:
        return "reference", "시트명에 기준 포함"
    ins = hits(INSPECTION_KWS) + [k for k in INSPECTION_KWS if k in norm(sheet_name)]
    if ins:
        return "inspection", "키워드: " + ", ".join(dict.fromkeys(ins))
    return "other", "규칙 불일치"


# ---------------- 번호 표(SOP Step / 공정단계) 인식 ----------------
@dataclass
class NumberedTable:
    header_row: int
    header_map: dict[int, str]
    no_col: int
    end_row: int
    rows: list[tuple[int, int, int, str]]    # (no, r_start, r_end, no_text)


def find_numbered_table(g: Grid, must: list[str]) -> NumberedTable | None:
    for r, c, v in g.find(lambda v: norm(v) == "no"):
        hm = header_map(g, r)
        hn = {norm(t) for t in hm.values()}
        if not all(any(m in t for t in hn) for m in must):
            continue
        occ = [x for x in g.occupied_rows() if x > r]
        end = r
        for x in occ:
            if x - end > 2:
                break
            # 표 중간에 새 헤더(두 번째 No)가 나오면 종료
            if x > r + 1 and norm(g.cells.get((x, c), "")) == "no":
                break
            # 표 뒤에 붙은 섹션 제목(넓게 병합된 단일 셀 행, 예: 부적합 LIST)에서 종료
            rc = g.row_cells(x)
            if x > r + 1 and len(rc) == 1 and rc[0][0] != c and \
                    (g.span(x, rc[0][0]).c2 - g.span(x, rc[0][0]).c1) >= 3 and not g.cells.get((x, c)):
                break
            end = x
        nums = []
        for x in range(r + 1, end + 1):
            v = g.cells.get((x, c))
            if v and re.fullmatch(r"\d+", v.strip()):
                nums.append((int(v), x, v))
        rows = []
        for i, (n, x, v) in enumerate(nums):
            nxt = nums[i + 1][1] - 1 if i + 1 < len(nums) else end
            rows.append((n, x, max(x, nxt, g.span(x, c).r2 if (x, c) in g.merged else x), v))
        if rows:
            return NumberedTable(r, hm, c, end, rows)
    return None


def collect_fields(g: Grid, t: NumberedTable, r1: int, r2: int) -> dict[str, str]:
    """번호 행 범위(r1~r2)의 값을 헤더 열 기준으로 모은다."""
    out: dict[str, list[str]] = {}
    for (r, c), v in sorted(g.cells.items()):
        if r1 <= r <= r2 and c != t.no_col:
            h = t.header_map.get(c, col_letter(c))
            out.setdefault(h, []).append(v)
    return {k: "\n".join(vs) for k, vs in out.items()}

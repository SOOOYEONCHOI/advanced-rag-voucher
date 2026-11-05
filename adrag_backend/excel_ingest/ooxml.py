"""xlsx(OOXML) 저수준 파싱: 시트 목록, 인쇄영역, drawing(도형/이미지/연결선), 폼 컨트롤.

openpyxl이 놓치는 요소(그룹 내부 이미지, 도형 텍스트, mc:AlternateContent, 연결선)를
XML에서 직접 읽는다.
"""
from __future__ import annotations

import hashlib
import posixpath
import re
import zipfile
from dataclasses import dataclass, field

from lxml import etree

NS = {
    "xdr": "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
}
R_ID = "{%s}id" % NS["r"]
R_EMBED = "{%s}embed" % NS["r"]
R_LINK = "{%s}link" % NS["r"]

# 기본 셀 크기 추정치 (EMU) — oneCellAnchor의 끝 셀 추정용
EMU_PER_ROW = 190500      # 약 15pt
EMU_PER_COL = 609600      # 약 64px


def col_letter(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def col_index(letters: str) -> int:
    n = 0
    for ch in letters.upper():
        n = n * 26 + (ord(ch) - 64)
    return n


@dataclass
class CellRange:
    r1: int
    c1: int
    r2: int
    c2: int

    @property
    def a1(self) -> str:
        return f"{col_letter(self.c1)}{self.r1}:{col_letter(self.c2)}{self.r2}"

    def overlaps(self, o: "CellRange") -> bool:
        return not (self.r2 < o.r1 or o.r2 < self.r1 or self.c2 < o.c1 or o.c2 < self.c1)

    def contains_cell(self, r: int, c: int) -> bool:
        return self.r1 <= r <= self.r2 and self.c1 <= c <= self.c2


@dataclass
class ShapeText:
    shape_id: str
    name: str
    text: str
    rng: CellRange
    geom: str | None
    anchor_key: int          # 같은 앵커(그룹)에 속한 요소끼리 공유
    in_group: bool


@dataclass
class Picture:
    shape_id: str
    name: str
    alt_text: str
    media_path: str | None
    external_link: str | None
    rng: CellRange
    anchor_type: str
    anchor_key: int
    in_group: bool
    crop: dict | None
    data: bytes | None = None
    sha256: str | None = None


@dataclass
class Connector:
    shape_id: str
    start_id: str | None
    end_id: str | None
    head: str | None
    tail: str | None
    rng: CellRange


@dataclass
class FormControl:
    name: str
    obj_type: str
    checked: bool
    rng: CellRange | None


@dataclass
class SheetDrawing:
    shapes: list[ShapeText] = field(default_factory=list)
    pictures: list[Picture] = field(default_factory=list)
    connectors: list[Connector] = field(default_factory=list)
    all_shape_nodes: dict[str, dict] = field(default_factory=dict)  # 흐름도 노드 후보 (텍스트 없는 도형 포함)
    drawing_hash: str | None = None


class GridGeometry:
    """시트 행 높이·열 너비로 EMU 좌표 → 셀 행/열 변환 (그룹 내부 도형 위치 계산용)"""

    def __init__(self, sheet_root):
        fmt = sheet_root.find("s:sheetFormatPr", NS)
        self.def_ht = float(fmt.get("defaultRowHeight", 15)) if fmt is not None else 15.0
        self.def_w = float(fmt.get("defaultColWidth", 0) or 0) if fmt is not None else 0.0
        if not self.def_w:
            self.def_w = float(fmt.get("baseColWidth", 8)) + 0.71 if fmt is not None and fmt.get("baseColWidth") else 8.43
        self.row_ht = {}
        for r in sheet_root.iter("{%s}row" % NS["s"]):
            if r.get("ht"):
                self.row_ht[int(r.get("r"))] = float(r.get("ht"))
        self.col_w = {}
        for c in sheet_root.iter("{%s}col" % NS["s"]):
            for i in range(int(c.get("min")), int(c.get("max")) + 1):
                if i > 2000:
                    break
                self.col_w[i] = float(c.get("width", self.def_w))

    def emu_to_row(self, emu: float) -> int:
        y, r = 0.0, 1
        while r < 1_048_576:
            h = self.row_ht.get(r, self.def_ht) * 12700
            if y + h > emu:
                return r
            y += h
            r += 1
        return r

    def emu_to_col(self, emu: float) -> int:
        x, c = 0.0, 1
        while c < 16384:
            w = (self.col_w.get(c, self.def_w) * 7 + 5) * 9525
            if x + w > emu:
                return c
            x += w
            c += 1
        return c


def _xfrm(el):
    x = el.find("a:xfrm", NS)
    if x is None:
        return None
    off, ext = x.find("a:off", NS), x.find("a:ext", NS)
    choff, chext = x.find("a:chOff", NS), x.find("a:chExt", NS)
    f = lambda e, a: float(e.get(a)) if e is not None else None
    return {"x": f(off, "x"), "y": f(off, "y"), "cx": f(ext, "cx"), "cy": f(ext, "cy"),
            "chx": f(choff, "x"), "chy": f(choff, "y"), "chcx": f(chext, "cx"), "chcy": f(chext, "cy")}


def _group_positions(grp, tf=None, out=None):
    """그룹 내부 요소의 절대 EMU 사각형 계산. tf: 자식좌표→절대좌표 변환 (sx, sy, dx, dy)"""
    out = {} if out is None else out
    tf = tf or (1.0, 1.0, 0.0, 0.0)
    gx = _xfrm(grp.find("xdr:grpSpPr", NS))
    if gx and gx["chcx"] and gx["chcy"]:
        sx0, sy0, dx0, dy0 = tf
        ax, ay = gx["x"] * sx0 + dx0, gx["y"] * sy0 + dy0
        acx, acy = gx["cx"] * sx0, gx["cy"] * sy0
        sx, sy = acx / gx["chcx"], acy / gx["chcy"]
        tf = (sx, sy, ax - gx["chx"] * sx, ay - gx["chy"] * sy)
    for ch in grp:
        tag = etree.QName(ch).localname
        if tag == "grpSp":
            _group_positions(ch, tf, out)
        elif tag in ("sp", "pic", "cxnSp"):
            pr = ch.find("xdr:spPr", NS)
            x = _xfrm(pr) if pr is not None else None
            nv = ch.find(".//xdr:cNvPr", NS)
            if x and x["x"] is not None and nv is not None:
                sx, sy, dx, dy = tf
                out[nv.get("id")] = (x["x"] * sx + dx, x["y"] * sy + dy, x["cx"] * sx, x["cy"] * sy)
    return out


class Workbook:
    def __init__(self, path: str):
        self.path = path
        self.z = zipfile.ZipFile(path)
        self.names = set(self.z.namelist())
        self._wb = etree.fromstring(self.z.read("xl/workbook.xml"))
        self._wb_rels = self.rels("xl/workbook.xml")

    # ---------- 공통 ----------
    def rels(self, part: str) -> dict[str, tuple[str, str, str]]:
        """rId -> (type, target_path, target_mode)"""
        p = posixpath.join(posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels")
        if p not in self.names:
            return {}
        out = {}
        for e in etree.fromstring(self.z.read(p)):
            typ = e.get("Type", "").rsplit("/", 1)[-1]
            mode = e.get("TargetMode", "Internal")
            tgt = e.get("Target")
            if mode != "External":
                # 2026.10.16(sooyeon.choi) 수정 - 절대 경로 Target("/xl/…", openpyxl 등)은 패키지 루트 기준(Q-P1-1 승인)
                tgt = posixpath.normpath(tgt.lstrip("/") if tgt.startswith("/")
                                         else posixpath.join(posixpath.dirname(part), tgt))
            out[e.get("Id")] = (typ, tgt, mode)
        return out

    def sheets(self) -> list[dict]:
        out = []
        for i, s in enumerate(self._wb.iter("{%s}sheet" % NS["s"])):
            rid = s.get(R_ID)
            out.append({
                "index": i,
                "name": s.get("name"),
                "state": s.get("state", "visible"),
                "xml": self._wb_rels[rid][1],
            })
        return out

    def print_areas(self) -> dict[int, list[CellRange]]:
        """localSheetId -> 인쇄영역 범위 목록"""
        out: dict[int, list[CellRange]] = {}
        for dn in self._wb.iter("{%s}definedName" % NS["s"]):
            if dn.get("name") != "_xlnm.Print_Area" or dn.get("localSheetId") is None:
                continue
            sid = int(dn.get("localSheetId"))
            for part in (dn.text or "").split(","):
                ref = part.split("!")[-1].replace("$", "")
                m = re.match(r"([A-Z]+)(\d+):([A-Z]+)(\d+)", ref)
                if m:
                    out.setdefault(sid, []).append(CellRange(int(m[2]), col_index(m[1]), int(m[4]), col_index(m[3])))
        return out

    # ---------- drawing ----------
    def sheet_drawing(self, sheet_xml: str) -> SheetDrawing:
        res = SheetDrawing()
        rels = self.rels(sheet_xml)
        dparts = [t for (typ, t, _) in rels.values() if typ == "drawing"]
        if not dparts:
            return res
        dpart = dparts[0]
        raw = self.z.read(dpart)
        res.drawing_hash = hashlib.sha256(raw + self.z.read(sheet_xml)).hexdigest()[:16]
        drels = self.rels(dpart)
        root = etree.fromstring(raw)
        geo = GridGeometry(etree.fromstring(self.z.read(sheet_xml)))
        for key, anc in enumerate(_iter_anchors(root)):
            rng0, atype = _anchor_range(anc)
            if rng0 is None:
                continue
            grp = anc.find("xdr:grpSp", NS)
            in_group = grp is not None
            gpos = _group_positions(grp) if in_group else {}

            def pos(el, _g=gpos, _r=rng0):
                """그룹 내부 요소는 실제 위치로 환산, 아니면 앵커 범위"""
                nv_ = el.find(".//xdr:cNvPr", NS)
                p = _g.get(nv_.get("id")) if nv_ is not None else None
                if not p:
                    return _r
                x, y, cx, cy = p
                r1, r2 = geo.emu_to_row(y), geo.emu_to_row(y + max(cy - 1, 0))
                c1, c2 = geo.emu_to_col(x), geo.emu_to_col(x + max(cx - 1, 0))
                # 환산값이 앵커 범위를 크게 벗어나면(좌표계 불일치) 앵커 범위 사용
                if r1 < _r.r1 - 2 or r2 > _r.r2 + 2:
                    return _r
                return CellRange(max(r1, _r.r1), max(c1, _r.c1), min(max(r1, r2), _r.r2), min(max(c1, c2), _r.c2))
            for sp in anc.iter("{%s}sp" % NS["xdr"]):
                nv = sp.find(".//xdr:cNvPr", NS)
                geom = sp.find(".//a:prstGeom", NS)
                text = _shape_text(sp)
                sid = nv.get("id")
                rng = pos(sp)
                res.all_shape_nodes[sid] = {"text": text, "geom": geom.get("prst") if geom is not None else None,
                                            "rng": rng, "name": nv.get("name")}
                if text:
                    res.shapes.append(ShapeText(sid, nv.get("name"), text, rng,
                                                geom.get("prst") if geom is not None else None, key, in_group))
            for pic in anc.iter("{%s}pic" % NS["xdr"]):
                nv = pic.find(".//xdr:cNvPr", NS)
                blip = pic.find(".//a:blip", NS)
                media, ext = None, None
                if blip is not None:
                    if blip.get(R_EMBED):
                        media = drels.get(blip.get(R_EMBED), (None, None, None))[1]
                    if blip.get(R_LINK):
                        ext = drels.get(blip.get(R_LINK), (None, None, None))[1]
                src = pic.find(".//a:srcRect", NS)
                crop = {k: int(v) for k, v in src.attrib.items()} if src is not None and src.attrib else None
                p = Picture(nv.get("id"), nv.get("name"), nv.get("descr") or "", media, ext, pos(pic), atype, key,
                            in_group, crop)
                if media and media in self.names:
                    p.data = self.z.read(media)
                    p.sha256 = hashlib.sha256(p.data).hexdigest()
                res.pictures.append(p)
            for cx in anc.iter("{%s}cxnSp" % NS["xdr"]):
                nv = cx.find(".//xdr:cNvPr", NS)
                st, en = cx.find(".//a:stCxn", NS), cx.find(".//a:endCxn", NS)
                ln = cx.find(".//a:ln", NS)
                head = ln.find("a:headEnd", NS) if ln is not None else None
                tail = ln.find("a:tailEnd", NS) if ln is not None else None
                res.connectors.append(Connector(
                    nv.get("id"), st.get("id") if st is not None else None, en.get("id") if en is not None else None,
                    head.get("type") if head is not None else None, tail.get("type") if tail is not None else None, pos(cx)))
        return res

    def form_controls(self, sheet_xml: str) -> list[FormControl]:
        rels = self.rels(sheet_xml)
        sx = etree.fromstring(self.z.read(sheet_xml))
        out = []
        for c in sx.iter("{%s}control" % NS["s"]):
            typ, tgt, _ = rels.get(c.get(R_ID), (None, None, None))
            if not tgt or tgt not in self.names or "ctrlProp" not in tgt:
                continue
            p = etree.fromstring(self.z.read(tgt))
            rng = None
            anc = c.find(".//s:anchor", NS)
            if anc is not None:
                fr, to = anc.find("s:from", NS), anc.find("s:to", NS)
                if fr is None:
                    fr, to = anc.find("xdr:from", NS), anc.find("xdr:to", NS)
                if fr is not None and to is not None:
                    rng = CellRange(int(fr.findtext("xdr:row", namespaces=NS)) + 1,
                                    int(fr.findtext("xdr:col", namespaces=NS)) + 1,
                                    int(to.findtext("xdr:row", namespaces=NS)) + 1,
                                    int(to.findtext("xdr:col", namespaces=NS)) + 1)
            out.append(FormControl(c.get("name"), p.get("objectType"), p.get("checked") == "Checked", rng))
        return out


def _iter_anchors(root):
    for el in root:
        if etree.QName(el).localname == "AlternateContent":
            ch = el.find("mc:Choice", NS)
            if ch is None:
                ch = el.find("mc:Fallback", NS)
            if ch is not None:
                yield from ch
        else:
            yield el


def _anchor_range(anc):
    tag = etree.QName(anc).localname
    fr, to = anc.find("xdr:from", NS), anc.find("xdr:to", NS)
    if fr is None:
        return None, tag
    r1 = int(fr.findtext("xdr:row", namespaces=NS)) + 1
    c1 = int(fr.findtext("xdr:col", namespaces=NS)) + 1
    if to is not None:
        r2 = int(to.findtext("xdr:row", namespaces=NS)) + 1
        c2 = int(to.findtext("xdr:col", namespaces=NS)) + 1
    else:
        ext = anc.find("xdr:ext", NS)
        cx = int(ext.get("cx", 0)) if ext is not None else 0
        cy = int(ext.get("cy", 0)) if ext is not None else 0
        r2 = r1 + max(0, round(cy / EMU_PER_ROW) - 1)
        c2 = c1 + max(0, round(cx / EMU_PER_COL) - 1)
    return CellRange(r1, c1, max(r1, r2), max(c1, c2)), tag


def _shape_text(sp) -> str:
    paras = []
    for p in sp.iterfind(".//a:p", NS):
        t = "".join((x.text or "") for x in p.iter("{%s}t" % NS["a"])).rstrip()
        if t.strip():
            paras.append(t)
    return "\n".join(paras).strip()

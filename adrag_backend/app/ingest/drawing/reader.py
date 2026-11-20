"""DXF 읽기·좌표 정규화·문자/선 수집 (2026.11.12(sooyeon.choi) 도면 파싱 기능 추가).

- 읽기: ezdxf.readfile → 실패 시 recover → 그래도 실패면 E_DXF_LOAD
- 좌표: 도면 범위($EXTMIN/$EXTMAX, 없으면 계산)를 0~1로 정규화. 모델공간 좌표 = 용지 크기 × 축척이라
  위치 규칙은 모두 정규화 좌표로 쓴다. 범위 비율로 용지 크기(A0~A4)를 추정한다.
- 수집: 블록(INSERT)을 전개해 문자·선을 월드 좌표로 모은다. 표 블록(SW_TABLEANNOTATION_*)·주기 블록 이름을 함께 남기고,
  치수 블록(_D_*·*D*) 문자는 치수로만 쓴다.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Optional

import ezdxf
from ezdxf import bbox as ezbbox
from ezdxf import recover

from .common import DrawingError, warning
from .textcodes import broken_ratio, normalize_text

PAPER_SIZES = {"A0": (1189, 841), "A1": (841, 594), "A2": (594, 420), "A3": (420, 297), "A4": (297, 210)}
_DIM_BLOCK = re.compile(r"^(\*D\d*|_D_.*)$", re.IGNORECASE)
_MAX_DEPTH = 6
_TEXT_TYPES = ("TEXT", "MTEXT", "ATTRIB")


@dataclass
class TextItem:
    text: str
    x: float          # 중심(월드 좌표)
    y: float
    x0: float
    y0: float
    x1: float
    y1: float
    h: float          # 글자 높이
    block: Optional[str] = None   # 최상위 블록 이름(모델공간 직접 문자는 None)
    tag: Optional[str] = None     # ATTRIB 태그
    nx: float = 0.0   # 정규화 좌표(0~1)
    ny: float = 0.0


@dataclass
class Segment:
    x1: float
    y1: float
    x2: float
    y2: float
    block: Optional[str] = None


@dataclass
class Sheet:
    extmin: tuple[float, float]
    extmax: tuple[float, float]
    space: str                    # model | layout 이름
    paper: Optional[str] = None   # A3 등
    paper_mm: Optional[tuple[int, int]] = None
    scale_factor: Optional[float] = None   # 모델 단위 / 용지 mm
    units: str = "mm"

    @property
    def width(self) -> float:
        return max(self.extmax[0] - self.extmin[0], 1e-9)

    @property
    def height(self) -> float:
        return max(self.extmax[1] - self.extmin[1], 1e-9)

    def norm(self, x: float, y: float) -> tuple[float, float]:
        return (x - self.extmin[0]) / self.width, (y - self.extmin[1]) / self.height


@dataclass
class Collected:
    texts: list[TextItem] = field(default_factory=list)
    segments: list[Segment] = field(default_factory=list)
    dim_texts: list[TextItem] = field(default_factory=list)
    dimensions: list[dict[str, Any]] = field(default_factory=list)
    inserts: list[dict[str, Any]] = field(default_factory=list)   # {name, x, y, nx, ny}
    entity_count: int = 0


def load_dxf(path: str):
    """ezdxf 문서와 경고 목록. 읽지 못하면 ``DrawingError(E_DXF_LOAD)``."""
    warnings: list[dict] = []
    try:
        return ezdxf.readfile(path), warnings
    except (IOError, ezdxf.DXFStructureError, ezdxf.DXFError, ValueError, KeyError) as first:
        try:
            doc, auditor = recover.readfile(path)
        except Exception as exc:  # noqa: BLE001 - 어떤 이유든 읽기 실패
            raise DrawingError("E_DXF_LOAD", f"{type(first).__name__}: {first}") from exc
        if auditor.has_errors:
            warnings.append(warning("W_ENCODING", "도면 구조 오류를 복구하며 읽었습니다. 일부 항목이 빠졌을 수 있습니다.",
                                    count=len(auditor.errors)))
        return doc, warnings


_UNITS = {0: "unitless", 1: "inch", 2: "feet", 4: "mm", 5: "cm", 6: "m"}


def pick_layout(doc):
    """엔티티가 있는 공간. 모델공간이 비면 첫 번째 비어 있지 않은 레이아웃."""
    msp = doc.modelspace()
    if len(msp):
        return msp, "model"
    for layout in doc.layouts:
        if layout.name != "Model" and len(layout):
            return layout, layout.name
    raise DrawingError("E_EMPTY_DRAWING")


def _header_extents(doc) -> Optional[tuple[tuple[float, float], tuple[float, float]]]:
    try:
        lo, hi = doc.header["$EXTMIN"], doc.header["$EXTMAX"]
    except KeyError:
        return None
    if not all(math.isfinite(v) for v in (lo[0], lo[1], hi[0], hi[1])):
        return None
    if hi[0] - lo[0] <= 0 or hi[1] - lo[1] <= 0 or abs(hi[0]) > 1e19:
        return None
    return (lo[0], lo[1]), (hi[0], hi[1])


def _robust_extents(layout) -> Optional[tuple[tuple[float, float], tuple[float, float]]]:
    """헤더 범위가 없을 때: 엔티티별 범위를 모으되 중심이 대다수와 멀리 떨어진 엔티티(손상 해칭 등)는 뺀다."""
    boxes = []
    for entity in layout:
        try:
            box = ezbbox.extents([entity], fast=True)
        except Exception:  # noqa: BLE001
            continue
        if box.has_data:
            boxes.append((box.extmin.x, box.extmin.y, box.extmax.x, box.extmax.y))
    if not boxes:
        return None

    def keep_axis(lo_i: int, hi_i: int) -> set[int]:
        centers = [(b[lo_i] + b[hi_i]) / 2 for b in boxes]
        med = sorted(centers)[len(centers) // 2]
        mad = sorted(abs(c - med) for c in centers)[len(centers) // 2]
        spread = max(b[hi_i] for b in boxes) - min(b[lo_i] for b in boxes)
        limit = max(20 * mad, 1e-6 * spread, 1e-9)
        return {i for i, c in enumerate(centers) if abs(c - med) <= limit}

    kept = [boxes[i] for i in keep_axis(0, 2) & keep_axis(1, 3)] or boxes
    return (min(b[0] for b in kept), min(b[1] for b in kept)), (max(b[2] for b in kept), max(b[3] for b in kept))


def make_sheet(doc, layout, space: str) -> Sheet:
    ext = _header_extents(doc) if space == "model" else None
    if ext is None:
        ext = _robust_extents(layout)
        if ext is None:
            raise DrawingError("E_EMPTY_DRAWING")
    sheet = Sheet(extmin=ext[0], extmax=ext[1], space=space)
    try:
        sheet.units = _UNITS.get(int(doc.header.get("$INSUNITS", 4)), "mm")
    except (TypeError, ValueError):
        pass
    sheet.paper, sheet.paper_mm, sheet.scale_factor = estimate_paper(sheet.width, sheet.height)
    return sheet


def estimate_paper(width: float, height: float, tolerance: float = 0.03):
    """가로세로 비율이 용지와 맞는 가장 작은 배율의 A 규격. 맞는 것이 없으면 (None, None, None)."""
    ratio = width / height
    best = None
    for name, (w, h) in PAPER_SIZES.items():
        for pw, ph in ((w, h), (h, w)):
            if abs(ratio - pw / ph) / (pw / ph) <= tolerance:
                factor = width / pw
                score = abs(factor - round(factor)) if factor >= 1 else abs(1 / factor - round(1 / factor))
                if best is None or score < best[0]:
                    best = (score, name, (pw, ph), factor)
    if best is None:
        return None, None, None
    return best[1], best[2], round(best[3], 4)


def _text_value(entity, codepage: str) -> str:
    try:
        raw = entity.plain_text()
    except Exception:  # noqa: BLE001 - 깨진 서식은 원문으로
        raw = entity.dxf.get("text", "")
    return normalize_text(raw, codepage)


def _text_item(entity, codepage: str, block: Optional[str]) -> Optional[TextItem]:
    value = _text_value(entity, codepage)
    if not value:
        return None
    dxftype = entity.dxftype()
    h = float(entity.dxf.get("char_height" if dxftype == "MTEXT" else "height", 2.5) or 2.5)
    try:
        box = ezbbox.extents([entity], fast=True)
    except Exception:  # noqa: BLE001
        box = None
    if box is not None and box.has_data:
        x0, y0, x1, y1 = box.extmin.x, box.extmin.y, box.extmax.x, box.extmax.y
    else:
        ins = entity.dxf.get("insert", (0, 0, 0))
        x0, y0, x1, y1 = ins[0], ins[1] - h, ins[0] + h * len(value) * 0.8, ins[1]
    tag = entity.dxf.get("tag") if dxftype == "ATTRIB" else None
    return TextItem(value, (x0 + x1) / 2, (y0 + y1) / 2, x0, y0, x1, y1, h, block, tag)


def _segments(entity, block: Optional[str]) -> list[Segment]:
    dxftype = entity.dxftype()
    if dxftype == "LINE":
        s, e = entity.dxf.start, entity.dxf.end
        return [Segment(s[0], s[1], e[0], e[1], block)]
    if dxftype in ("LWPOLYLINE", "POLYLINE"):
        try:
            pts = [(p[0], p[1]) for p in (entity.get_points("xy") if dxftype == "LWPOLYLINE" else entity.points())]
        except Exception:  # noqa: BLE001
            return []
        if entity.is_closed and pts:
            pts.append(pts[0])
        return [Segment(a[0], a[1], b[0], b[1], block) for a, b in zip(pts, pts[1:])]
    return []


def collect(doc, layout, sheet: Sheet) -> tuple[Collected, list[dict]]:
    """문자·선·치수를 월드 좌표로 모은다."""
    codepage = "cp949"
    try:
        codepage = doc.encoding or "cp949"
    except AttributeError:
        pass
    out = Collected()

    def visit(entity, block: Optional[str], depth: int, dim_block: bool) -> None:
        out.entity_count += 1
        dxftype = entity.dxftype()
        if dxftype in _TEXT_TYPES:
            item = _text_item(entity, codepage, block)
            if item:
                (out.dim_texts if dim_block else out.texts).append(item)
            return
        if dxftype == "INSERT":
            name = entity.dxf.get("name", "")
            top = block or name
            is_dim = dim_block or bool(_DIM_BLOCK.match(name))
            if block is None:
                ins = entity.dxf.get("insert", (0, 0, 0))
                nx, ny = sheet.norm(ins[0], ins[1])
                out.inserts.append({"name": name, "x": ins[0], "y": ins[1], "nx": nx, "ny": ny})
            for attrib in getattr(entity, "attribs", []):
                visit(attrib, top, depth + 1, is_dim)
            if depth >= _MAX_DEPTH:
                return
            try:
                children = list(entity.virtual_entities())
            except Exception:  # noqa: BLE001 - 손상된 블록은 건너뛴다
                return
            for child in children:
                visit(child, top, depth + 1, is_dim)
            return
        if dxftype == "DIMENSION":
            out.dimensions.append(_dimension(entity, codepage))
            return
        if not dim_block:
            out.segments.extend(_segments(entity, block))

    for entity in layout:
        visit(entity, None, 0, False)

    for item in out.texts + out.dim_texts:
        item.nx, item.ny = sheet.norm(item.x, item.y)
    warnings = []
    ratio = broken_ratio([t.text for t in out.texts])
    if ratio > 0.01:
        warnings.append(warning("W_ENCODING", "깨진 글자가 1%를 넘습니다. 도면 코드페이지를 확인해 주세요.",
                                ratio=round(ratio, 4)))
    return out, warnings


def _fmt_number(value: float) -> str:
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    return text or "0"


def _dimension(entity, codepage: str) -> dict[str, Any]:
    """치수 표시 문자: 블록 안 문자(접두·접미 포함)가 있으면 그것, 없으면 dxf.text의 <>를 측정값으로."""
    try:
        measured = float(entity.get_measurement())
    except Exception:  # noqa: BLE001
        measured = None
    display = None
    try:
        for child in entity.virtual_entities():
            if child.dxftype() in ("MTEXT", "TEXT"):
                display = _text_value(child, codepage)
                break
    except Exception:  # noqa: BLE001
        display = None
    if not display:
        override = normalize_text(entity.dxf.get("text", "") or "", codepage)
        value = _fmt_number(measured) if measured is not None else ""
        display = override.replace("<>", value) if override else value
    display = display.replace("\n", " ").strip()
    return {
        "text": display,
        "measured": round(measured, 4) if measured is not None else None,
        "reference": bool(re.fullmatch(r"\(.*\)", display)),
    }

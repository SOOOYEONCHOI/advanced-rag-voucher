"""도면 이미지 — 전체 렌더·미리보기·영역 크롭 (2026.11.12(sooyeon.choi) 도면 파싱 기능 추가).

- 렌더 범위를 도면 범위로 고정하고, 범위 5% 밖으로 나가는 엔티티와 경계 계산이 실패하는 HATCH는 그리지 않는다
  (변환 과정에서 손상된 해칭 때문에 그림이 점으로 줄어들거나 렌더러가 멈추는 문제).
- 문자 스타일 글꼴을 서버 한글 글꼴로 바꾼다(없으면 한글이 □로 나온다).
- 그림 좌표와 픽셀이 1:1로 맞도록 여백 없이 그리고, 크롭은 정규화 영역을 픽셀로 바꿔 전체 이미지에서 잘라 낸다.
- 렌더는 별도 프로세스에서 제한 시간 안에 실행한다. 실패해도 텍스트 추출 결과는 그대로 저장한다.
"""
from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import yaml

from .common import warning

MARGIN = 0.05
PREVIEW_PX = 1600
_FONT_FILE = Path(__file__).resolve().parent / "templates" / "fonts.yaml"


@dataclass
class RenderedImage:
    role: str                 # drawing | drawing_preview | drawing_crop
    region: str               # full | title_block | bom | revision | notes
    png: bytes
    width: int
    height: int
    bbox_norm: Optional[list[float]] = None


@dataclass
class RenderResult:
    images: list[RenderedImage] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)
    elapsed_ms: int = 0
    skipped: int = 0


@lru_cache(maxsize=1)
def _font_config() -> dict[str, Any]:
    with open(_FONT_FILE, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _server_font(font_manager) -> str:
    cfg = _font_config()
    for name in [cfg.get("default")] + list(cfg.get("fallbacks") or []):
        if name and font_manager.has_font(name):
            return name
    return cfg.get("default") or "DejaVuSans.ttf"


def _apply_fonts(doc) -> int:
    """문자 스타일 글꼴 교체. 바꾼 스타일 수."""
    from ezdxf.fonts import fonts

    cfg = _font_config()
    mapping = {k.lower(): v for k, v in (cfg.get("map") or {}).items()}
    server = _server_font(fonts.font_manager)
    replaced = 0
    for style in doc.styles:
        current = (style.dxf.get("font", "") or "").lower()
        target = mapping.get(current, server)
        if not fonts.font_manager.has_font(target):
            target = server
        if current != target.lower():
            style.dxf.font = target
            replaced += 1
    return replaced


_BACKEND_ROOT = Path(__file__).resolve().parents[3]


def _render_subprocess(dxf_path: str, extmin, extmax, max_px: int, timeout_sec: int) -> dict[str, Any]:
    """렌더를 별도 Python 프로세스(python -m app.ingest.drawing.render)로 실행한다. 시간 초과면 강제 종료."""
    dxf_path = str(Path(dxf_path).resolve())  # 자식 프로세스 작업 폴더와 무관하게 같은 파일을 가리키도록
    with tempfile.TemporaryDirectory(prefix="drawing_render_") as tmp:
        out_png = Path(tmp) / "full.png"
        cmd = [sys.executable, "-m", "app.ingest.drawing.render", dxf_path, str(out_png),
               str(extmin[0]), str(extmin[1]), str(extmax[0]), str(extmax[1]), str(max_px)]
        env = {**os.environ, "PYTHONPATH": str(_BACKEND_ROOT), "MPLBACKEND": "Agg"}
        try:
            done = subprocess.run(cmd, cwd=str(_BACKEND_ROOT), capture_output=True, text=True, errors="replace",
                                  timeout=timeout_sec, env=env)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"{timeout_sec}초 안에 끝나지 않았습니다.") from exc
        if done.returncode != 0 or not out_png.exists():
            raise RuntimeError((done.stderr or done.stdout or "").strip().splitlines()[-1:] or "렌더 실패")
        info = json.loads(done.stdout.strip().splitlines()[-1])
        info["png"] = out_png.read_bytes()
        return info


_UNICODE_ESCAPE = re.compile(r"\\U\+([0-9A-Fa-f]{4})")


def _decode_unicode_escapes(doc) -> None:
    """TEXT·ATTRIB의 \\U+XXXX를 문자로 바꾼다(렌더러는 TEXT에서 이 표기를 풀지 않는다)."""
    for entity in doc.entitydb.values():
        if entity.dxftype() in ("TEXT", "ATTRIB", "ATTDEF") and "\\U+" in (entity.dxf.get("text", "") or ""):
            entity.dxf.text = _UNICODE_ESCAPE.sub(lambda m: chr(int(m.group(1), 16)), entity.dxf.text)


def _render_png(dxf_path: str, extmin, extmax, max_px: int) -> dict[str, Any]:
    import ezdxf
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from ezdxf import bbox as ezbbox
    from ezdxf import path as zpath
    from ezdxf.addons.drawing import Frontend, RenderContext
    from ezdxf.addons.drawing.config import BackgroundPolicy, Configuration
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

    doc = ezdxf.readfile(dxf_path)
    fonts_replaced = _apply_fonts(doc)
    _decode_unicode_escapes(doc)
    msp = doc.modelspace()
    layout = msp if len(msp) else next((lay for lay in doc.layouts if len(lay)), msp)
    x0, y0 = extmin
    x1, y1 = extmax
    w, h = x1 - x0, y1 - y0
    skipped: list[str] = []

    def keep(entity) -> bool:
        try:
            if entity.dxftype() == "HATCH":
                for boundary in entity.paths:
                    zpath.from_hatch_boundary_path(boundary)
            box = ezbbox.extents([entity], fast=True)
            if box.has_data and (
                box.extmin.x < x0 - MARGIN * w or box.extmax.x > x1 + MARGIN * w
                or box.extmin.y < y0 - MARGIN * h or box.extmax.y > y1 + MARGIN * h
            ):
                skipped.append(entity.dxf.handle)
                return False
        except Exception:  # noqa: BLE001 - 경계 계산 실패(손상 knot 등)
            skipped.append(entity.dxf.get("handle", "?"))
            return False
        return True

    scale = max_px / max(w, h)
    width_px, height_px = max(int(round(w * scale)), 1), max(int(round(h * scale)), 1)
    fig = plt.figure(figsize=(width_px / 100, height_px / 100), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1])
    cfg = Configuration(background_policy=BackgroundPolicy.WHITE)
    Frontend(RenderContext(doc), MatplotlibBackend(ax, adjust_figure=False), config=cfg).draw_layout(layout, finalize=True, filter_func=keep)
    ax.set_aspect("auto")
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_axis_off()
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=100, facecolor="white")
    plt.close(fig)
    return {"png": buffer.getvalue(), "skipped": len(skipped), "fonts_replaced": fonts_replaced}


def _scaled(png: bytes, max_px: int) -> tuple[bytes, int, int]:
    from PIL import Image

    with Image.open(io.BytesIO(png)) as img:
        img = img.convert("RGB")
        img.thumbnail((max_px, max_px))
        out = io.BytesIO()
        img.save(out, format="PNG", optimize=True)
        return out.getvalue(), img.width, img.height


def _crop(png: bytes, bbox_norm: list[float], pad: float = 0.01) -> tuple[bytes, int, int]:
    from PIL import Image

    with Image.open(io.BytesIO(png)) as img:
        W, H = img.size
        x0, y0, x1, y1 = bbox_norm
        box = (
            max(int((x0 - pad) * W), 0), max(int((1 - y1 - pad) * H), 0),
            min(int((x1 + pad) * W), W), min(int((1 - y0 + pad) * H), H),
        )
        if box[2] - box[0] < 8 or box[3] - box[1] < 8:
            raise ValueError("크롭 영역이 너무 작습니다.")
        part = img.crop(box).convert("RGB")
        out = io.BytesIO()
        part.save(out, format="PNG", optimize=True)
        return out.getvalue(), part.width, part.height


def render_drawing(dxf_path: str, extmin, extmax, regions: dict[str, list[float]], *,
                   max_px: int = 4000, timeout_sec: int = 90, in_process: bool = False) -> RenderResult:
    """전체 PNG·미리보기·영역 크롭. ``regions``: {region: bbox_norm}. 실패는 경고로만 남긴다."""
    started = time.perf_counter()
    result = RenderResult()
    try:
        if in_process:
            rendered = _render_png(dxf_path, extmin, extmax, max_px)
        else:
            rendered = _render_subprocess(dxf_path, extmin, extmax, max_px, timeout_sec)
    except Exception as exc:  # noqa: BLE001
        result.warnings.append(warning("W_RENDER_FAILED", "도면 이미지를 만들지 못했습니다. 추출 결과는 저장됩니다.",
                                       detail=str(exc)[:300]))
        result.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return result

    png = rendered["png"]
    from PIL import Image

    with Image.open(io.BytesIO(png)) as img:
        width, height = img.size
    result.images.append(RenderedImage("drawing", "full", png, width, height, [0.0, 0.0, 1.0, 1.0]))
    preview, pw, ph = _scaled(png, PREVIEW_PX)
    result.images.append(RenderedImage("drawing_preview", "full", preview, pw, ph, [0.0, 0.0, 1.0, 1.0]))
    for region, bbox_norm in regions.items():
        try:
            crop, cw, ch = _crop(png, bbox_norm)
        except Exception:  # noqa: BLE001 - 영역 하나 실패는 건너뛴다
            continue
        result.images.append(RenderedImage("drawing_crop", region, crop, cw, ch, [round(v, 4) for v in bbox_norm]))
    result.skipped = rendered["skipped"]
    if result.skipped:
        result.warnings.append(warning("W_RENDER_SKIPPED", "도면 범위 밖·경계 오류 엔티티를 그리지 않았습니다. 이미지에서 일부가 빠질 수 있습니다.",
                                       count=result.skipped))
    if rendered["fonts_replaced"]:
        result.warnings.append(warning("W_FONT_FALLBACK", "도면 글꼴을 서버 한글 글꼴로 바꿔 그렸습니다.",
                                       count=rendered["fonts_replaced"]))
    result.elapsed_ms = int((time.perf_counter() - started) * 1000)
    return result


if __name__ == "__main__":  # pragma: no cover - _render_subprocess가 실행
    _dxf, _png, _x0, _y0, _x1, _y1, _max_px = sys.argv[1:8]
    _out = _render_png(_dxf, (float(_x0), float(_y0)), (float(_x1), float(_y1)), int(_max_px))
    Path(_png).write_bytes(_out.pop("png"))
    print(json.dumps(_out))

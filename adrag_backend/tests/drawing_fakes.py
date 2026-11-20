"""합성 도면(DXF) 생성기 — 도면 처리 테스트용 (2026.11.12(sooyeon.choi) 도면 파싱 기능 추가).

실제 사내 도면·추출값은 쓰지 않는다. 샘플 양식의 특징만 재현한다.
- A3 용지 × 축척 1:5(모델 범위 2100×1485), 표제란 값은 라벨 아래 칸
- 부품표는 SW_TABLEANNOTATION_0 블록 안(표 선 있음, 머리글 2줄, 머리글 위)
- 개정이력은 SW_TABLEANNOTATION_1 블록 안(머리글 아래)
- 주기 MTEXT(번호 항목·일반공차 규격), 규격 메모, 치수, 보안 문구, 범위 밖 손상 해칭
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import ezdxf

SCALE = 5
W, H = 420 * SCALE, 297 * SCALE

TITLE = {
    "PART NUMBER": "DW-100200", "REVISION": "B.2", "PART NAME": "ASSY_SAMPLE MODULE",
    "SCALE": "1:5", "DATE": "2026-10-28", "MATERIAL": "SS400", "DRAWN": "설계자A", "CHECKED": "검토자B",
    "APPROVED": "승인자C",
}
BOM_HEADER = [["NO"], ["PART_", "NAMBER"], ["PTC_WM_", "PART_NAME"], ["Q'TY"], ["MATERIAL"]]
BOM_ROWS = [
    ["1", "DW-100201", "FRAME_MAIN", "1", "SS400"],
    ["2", "DW-100231", "SHAFT_DRIVE", "2", "S45C"],
    ["3", "BRG-6205ZZ", "BEARING", "4", "-"],
]
REV_HEADER = ["REV", "DESCRIPTION", "DATE", "DRAWN"]
REV_ROWS = [["B", "커버 볼트 수량 변경", "2026-10-28", "설계자A"], ["A", "최초 작성", "2026-09-02", "설계자A"]]


def _table_block(doc, name: str, header: list, rows: list[list[str]], header_top: bool, col_w: list[float],
                 row_h: float = 8 * SCALE / 2, text_h: float = 2.5 * SCALE / 2):
    block = doc.blocks.new(name)
    nrows = len(rows) + 1
    total_w = sum(col_w)
    for r in range(nrows + 1):
        block.add_line((0, r * row_h), (total_w, r * row_h))
    x = 0.0
    for w in col_w + [0]:
        block.add_line((x, 0), (x, nrows * row_h))
        x += w
    ordered = ([header] + rows) if header_top else (rows + [header])
    for r, row in enumerate(ordered):
        y_top = (nrows - r) * row_h
        x = 0.0
        for c, value in enumerate(row):
            lines = value if isinstance(value, list) else [value]
            for i, line in enumerate(lines):
                y = y_top - (i + 1) * (row_h / (len(lines) + 1)) - text_h / 2
                block.add_text(line, height=text_h, dxfattribs={"insert": (x + 1.5, y)})
            x += col_w[c]
    return block


def make_drawing(path: Path, *, with_title: bool = True, title_overrides: Optional[dict] = None,
                 with_bom: bool = True, corrupt_hatch: bool = True, dxfversion: str = "R2000",
                 header_extents: bool = True) -> Path:
    doc = ezdxf.new(dxfversion, setup=True)
    doc.header["$DWGCODEPAGE"] = "ANSI_949"
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    msp.add_lwpolyline([(10, 10), (W - 10, 10), (W - 10, H - 10), (10, H - 10)], close=True)
    # 형상
    msp.add_lwpolyline([(300, 500), (1100, 500), (1100, 900), (300, 900)], close=True)
    msp.add_circle((450, 700), 80)
    msp.add_circle((950, 700), 80)
    dim = msp.add_linear_dim(base=(300, 450), p1=(300, 500), p2=(1100, 500), dimstyle="EZDXF")
    dim.render()
    # 치수 블록(접두 포함 표시 문자)
    dblock = doc.blocks.new("_D_1")
    dblock.add_text("2-Ø5.5 THRU", height=12)
    msp.add_blockref("_D_1", (450, 820))
    rblock = doc.blocks.new("_D_2")
    rblock.add_text("(12.5)", height=12)
    msp.add_blockref("_D_2", (950, 820))

    th = 2.5 * SCALE
    if with_title:
        values = {**TITLE, **(title_overrides or {})}
        x0, y0 = W * 0.62, 30
        cells = [("PART NUMBER", 0, 2), ("REVISION", 1, 2), ("PART NAME", 0, 1), ("SCALE", 0, 0), ("DATE", 1, 0),
                 ("MATERIAL", 2, 0), ("DRAWN", 2, 2), ("CHECKED", 2, 1), ("APPROVED", 3, 1)]
        cw, ch = 180, 70
        for label, cx, cy in cells:
            bx, by = x0 + cx * cw, y0 + cy * ch
            msp.add_lwpolyline([(bx, by), (bx + cw, by), (bx + cw, by + ch), (bx, by + ch)], close=True)
            msp.add_text(label, height=th * 0.7, dxfattribs={"insert": (bx + 5, by + ch - th - 5)})
            value = values.get(label)
            if value:
                msp.add_mtext(value, dxfattribs={"insert": (bx + 5, by + ch * 0.45), "char_height": th})
    if with_bom:
        _table_block(doc, "SW_TABLEANNOTATION_0", BOM_HEADER, BOM_ROWS, True, [40, 150, 200, 50, 110],
                     row_h=40, text_h=10)
        msp.add_blockref("SW_TABLEANNOTATION_0", (W * 0.62, 330))
    _table_block(doc, "SW_TABLEANNOTATION_1", REV_HEADER, REV_ROWS, False, [40, 300, 120, 100], row_h=35, text_h=10)
    msp.add_blockref("SW_TABLEANNOTATION_1", (W * 0.62, H - 160))
    msp.add_mtext(
        "Notes\\P1. 일반 공차는 KS B ISO 2768-m/K 을 따른다.\\P2. 날카로운 모서리는 C0.5\\P모따기.\\P3. 도장 색상은 회색.",
        dxfattribs={"insert": (60, 330), "char_height": th},
    )
    msp.add_mtext("<샘플 규격 : SP-10, 폭 20mm>\\P재질 : 우레탄", dxfattribs={"insert": (60, H - 60), "char_height": th})
    msp.add_text("Confidential", height=th, dxfattribs={"insert": (W * 0.4, 30)})
    msp.add_text("보통급", height=th, dxfattribs={"insert": (W * 0.4, 60)})
    msp.add_text("조립 후 회전 확인", height=th, dxfattribs={"insert": (300, 1000)})
    if corrupt_hatch:
        hatch = msp.add_hatch(color=1)
        hatch.paths.add_polyline_path([(-200000, 0), (-199000, 0), (-199000, 1000)], is_closed=True)
    if header_extents:  # ezdxf는 저장할 때 모델공간 레이아웃 범위로 $EXTMIN/$EXTMAX를 다시 쓴다
        msp.dxf.extmin = (0, 0, 0)          # (0,0,0)은 거짓으로 보아 헤더를 덮어쓰지 않는다
        msp.dxf.extmax = (W, H, 0)
        doc.header["$EXTMIN"] = (0, 0, 0)
        doc.header["$EXTMAX"] = (W, H, 0)
    doc.saveas(path)  # ezdxf는 한글을 \U+XXXX로 저장한다(추출·렌더 모두 이 표기를 푼다)
    return path


def fake_converter_script(path: Path, *, mode: str = "ok", dxf_source: Optional[Path] = None) -> Path:
    """dwg2dxf 대신 쓰는 가짜 변환기(Python 스크립트). mode: ok | fail | hang."""
    import sys

    body = [
        "import shutil, sys, time",
        "args = sys.argv[1:]",
        "out = args[args.index('-o') + 1]",
        f"mode = {mode!r}",
        "if mode == 'fail':",
        "    sys.stderr.write('ERROR: bad dwg\\n'); sys.exit(2)",
        "if mode == 'hang':",
        "    time.sleep(30)",
        f"shutil.copyfile({str(dxf_source)!r}, out)",
        "sys.stderr.write('Warning: Object handle not found\\n')",
    ]
    script = path.with_suffix(".py")
    script.write_text("\n".join(body), encoding="utf-8")
    if sys.platform.startswith("win"):
        launcher = path.with_suffix(".cmd")
        launcher.write_text(f'@"{sys.executable}" "{script}" %*\n', encoding="utf-8")
    else:
        launcher = path.with_suffix(".sh")
        launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
        launcher.chmod(0o755)
    return launcher


def fake_dwg(path: Path, version: bytes = b"AC1015") -> Path:
    path.write_bytes(version + b"\x00" * 200)
    return path

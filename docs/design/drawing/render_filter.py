"""도면 렌더 — 범위 고정·손상 엔티티 제외·한글 글꼴 대체. 참고용 PoC 코드 (운영 코드 아님).

샘플 조립도에서 확인한 문제(2026-11-04):
1) 변환 과정에서 경계가 손상된 HATCH 34개가 x≈-194,833까지 뻗어 전체 범위가 40배로 커짐
   → 그림이 점 하나로 렌더됨
2) 일부 HATCH 경계의 B-spline knot 값이 잘못돼 ezdxf 렌더러가 예외로 중단
3) 서버에 GOTHIC·MALGUN 글꼴이 없으면 한글이 □로 렌더

처리:
- 렌더 범위를 헤더 $EXTMIN/$EXTMAX로 고정
- 범위 5% 밖으로 나가는 엔티티, 경계 경로 계산이 실패하는 HATCH는 filter_func로 제외(건수 → W_RENDER_SKIPPED)
- 문자 스타일 글꼴을 서버 한글 글꼴로 대체(→ W_FONT_FALLBACK). 운영은 DRAWING_FONT_MAP 설정으로 매핑

결과: 조립도 렌더 24 s(150~520 dpi), 34개 제외 후 정상, 한글 정상. 가공품 2종 1~4 s.
주의: 대체 글꼴은 글자 폭이 달라 MTEXT 줄바꿈 위치가 원본과 조금 다를 수 있음(표 셀 안 줄바꿈).
"""
from __future__ import annotations

import sys
import time

import ezdxf
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from ezdxf import bbox  # noqa: E402
from ezdxf import path as zpath  # noqa: E402
from ezdxf.addons.drawing import Frontend, RenderContext  # noqa: E402
from ezdxf.addons.drawing.config import BackgroundPolicy, Configuration  # noqa: E402
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend  # noqa: E402

KOREAN_FONT = "NotoSansCJK-Regular.ttc"  # 운영: DRAWING_FONT_MAP
MARGIN = 0.05


def render(dxf_path: str, png_path: str, dpi: int = 300) -> dict:
    t0 = time.time()
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()
    fonts_replaced = 0
    for style in doc.styles:
        style.dxf.font = KOREAN_FONT
        fonts_replaced += 1

    (x0, y0, _), (x1, y1, _) = doc.header["$EXTMIN"], doc.header["$EXTMAX"]
    w, h = x1 - x0, y1 - y0
    skipped: list[str] = []

    def keep(entity) -> bool:
        try:
            if entity.dxftype() == "HATCH":
                for boundary in entity.paths:
                    zpath.from_hatch_boundary_path(boundary)
            box = bbox.extents([entity], fast=True)
            if box.has_data and (
                box.extmin.x < x0 - MARGIN * w
                or box.extmax.x > x1 + MARGIN * w
                or box.extmin.y < y0 - MARGIN * h
                or box.extmax.y > y1 + MARGIN * h
            ):
                skipped.append(entity.dxf.handle)
                return False
        except Exception:  # 경계 계산 실패(손상 knot 등)
            skipped.append(entity.dxf.handle)
            return False
        return True

    fig = plt.figure(figsize=(16.54, 11.69))
    ax = fig.add_axes([0, 0, 1, 1])
    cfg = Configuration(background_policy=BackgroundPolicy.WHITE)
    Frontend(RenderContext(doc), MatplotlibBackend(ax), config=cfg).draw_layout(
        msp, finalize=True, filter_func=keep
    )
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_axis_off()
    fig.savefig(png_path, dpi=dpi, bbox_inches="tight", pad_inches=0)
    plt.close(fig)
    return {"png": png_path, "seconds": round(time.time() - t0, 1), "skipped": len(skipped), "fonts_replaced": fonts_replaced}


if __name__ == "__main__":
    print(render(sys.argv[1], sys.argv[2]))

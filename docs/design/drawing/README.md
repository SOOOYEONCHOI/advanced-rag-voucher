# 도면 처리 PoC 참고 코드

2026-11-04 샘플 DWG 3종을 처리하며 확인한 문제와 우회 방법을 담은 **참고용** 코드다. 운영 코드로 그대로 쓰지 말고, `ingest/drawing/`을 구현할 때 규칙만 옮긴다. 샘플 도면·추출값은 들어 있지 않다.

| 파일 | 내용 | 관련 요구사항 |
|---|---|---|
| `sanitize_libredwg_dxf.py` | LibreDWG 출력의 핸들 0 사전 항목 제거 → ezdxf 로드 가능 | FR-05, `W_SANITIZED` |
| `render_filter.py` | 렌더 범위 고정, 손상 HATCH·범위 밖 엔티티 제외, 한글 글꼴 대체 | FR-16, `W_RENDER_SKIPPED`, `W_FONT_FALLBACK` |

검증 환경: LibreDWG 0.13.3(소스 빌드, `./configure --disable-bindings --disable-docs`), ezdxf 1.4(GitHub 소스 설치), matplotlib 3.x, Noto Sans CJK, Python 3.13.

```bash
dwg2dxf -y -o out.dxf input.DWG          # 변환 (별도 프로세스, 타임아웃 필수)
python sanitize_libredwg_dxf.py out.dxf  # → out.sanitized.dxf
python render_filter.py out.sanitized.dxf out.png
```

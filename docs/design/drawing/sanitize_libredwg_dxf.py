"""LibreDWG(dwg2dxf 0.13.3) 출력 DXF 보정 — 참고용 PoC 코드 (운영 코드 아님).

문제: LibreDWG가 만든 DXF의 OBJECTS 사전(DICTIONARY)에 이름이 비어 있고
      핸들 0을 가리키는 항목(그룹코드 3 + 350/360 '0')이 생겨,
      ezdxf.readfile / ezdxf.recover.readfile 모두 "Invalid handle 0"으로 실패한다.
처리: 해당 4줄(코드 3, 이름, 코드 350|360, 값 0)을 제거한다.
결과: 샘플 3종 모두 파일당 4건 제거 후 ezdxf.readfile 성공(2026-11-04 확인).

운영 구현(ingest/drawing/sanitize.py)에서 할 일:
- 그룹코드/값 쌍 단위로 읽기(줄 번호 홀짝 가정 대신 태그 파서 사용 권장)
- 제거 건수를 W_SANITIZED(info)로 반환
- 보정 전 파일 보존, 보정 후 파일은 derived/sanitized.dxf
"""
from __future__ import annotations

import sys
from pathlib import Path


def sanitize(src: Path, dst: Path) -> int:
    text = src.read_text(encoding="utf-8", errors="surrogateescape")
    lines = text.split("\n")
    out: list[str] = []
    removed = 0
    i, n = 0, len(lines)
    while i < n:
        if (
            i + 3 < n
            and lines[i].strip() == "3"
            and lines[i + 2].strip() in ("350", "360")
            and lines[i + 3].strip() == "0"
        ):
            removed += 1
            i += 4
            continue
        out.append(lines[i])
        if i + 1 < n:
            out.append(lines[i + 1])
        i += 2
    dst.write_text("\n".join(out), encoding="utf-8", errors="surrogateescape")
    return removed


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        p = Path(arg)
        count = sanitize(p, p.with_suffix(".sanitized.dxf"))
        print(f"{p.name}: removed {count}")

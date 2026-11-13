"""변환 DXF 보정 (2026.11.12(sooyeon.choi) 도면 파싱 기능 추가).

LibreDWG 출력 DXF의 사전(DICTIONARY)에 이름이 비고 핸들 0을 가리키는 항목(코드 3 + 350/360 '0')이 생겨
ezdxf가 "Invalid handle 0"으로 읽지 못한다. 그 항목을 지운다. 태그(코드·값 두 줄) 단위로 읽어 줄 번호에 기대지 않는다.
"""
from __future__ import annotations

from pathlib import Path


def _read_tags(text: str) -> list[tuple[str, str]]:
    lines = text.splitlines()
    if len(lines) % 2:
        lines.append("")
    return [(lines[i], lines[i + 1]) for i in range(0, len(lines), 2)]


def sanitize_dxf(src: str, dst: str) -> int:
    """보정한 DXF를 ``dst``에 쓰고 지운 항목 수를 돌려준다. 원본(``src``)은 그대로 둔다."""
    raw = Path(src).read_bytes()
    text = raw.decode("utf-8", errors="surrogateescape")
    tags = _read_tags(text)
    out: list[tuple[str, str]] = []
    removed = 0
    i = 0
    while i < len(tags):
        code, value = tags[i]
        if (
            code.strip() == "3"
            and i + 1 < len(tags)
            and tags[i + 1][0].strip() in ("350", "360")
            and tags[i + 1][1].strip() == "0"
        ):
            removed += 1
            i += 2
            continue
        out.append((code, value))
        i += 1
    newline = "\r\n" if b"\r\n" in raw[:4096] else "\n"
    body = newline.join(f"{c}{newline}{v}" for c, v in out) + newline
    Path(dst).write_bytes(body.encode("utf-8", errors="surrogateescape"))
    return removed

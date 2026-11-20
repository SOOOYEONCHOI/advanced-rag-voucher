"""도면 파일 판별 — 확장자 + 파일 서명 (2026.11.12(sooyeon.choi) 도면 파싱 기능 추가).

DWG는 앞 6바이트가 버전 문자열(AC1012~AC1032)이다. DXF는 텍스트(첫 태그 0/SECTION) 또는 바이너리 서명.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .common import DrawingError

DRAWING_EXTENSIONS = frozenset({"dwg", "dxf"})

# R13 ~ R2018. 그 밖(R12 이하·미래 버전)은 변환기 호환을 보장할 수 없어 받지 않는다
DWG_VERSIONS = {
    "AC1012": "R13", "AC1014": "R14", "AC1015": "R2000", "AC1018": "R2004",
    "AC1021": "R2007", "AC1024": "R2010", "AC1027": "R2013", "AC1032": "R2018",
}
_BINARY_DXF = b"AutoCAD Binary DXF\r\n\x1a\x00"


@dataclass(frozen=True)
class DrawingFormat:
    kind: str                 # dwg | dxf_ascii | dxf_binary
    acadver: Optional[str]    # DWG만(AC1015 등)
    release: Optional[str]


def is_drawing_extension(name: str) -> bool:
    return Path(name or "").suffix.lower().lstrip(".") in DRAWING_EXTENSIONS


def detect_drawing(path: str, filename: Optional[str] = None) -> DrawingFormat:
    """서명이 확장자와 맞지 않거나 허용 버전 밖이면 ``DrawingError(E_UNSUPPORTED_FORMAT)``."""
    ext = Path(filename or path).suffix.lower().lstrip(".")
    with open(path, "rb") as handle:
        head = handle.read(512)
    if not head:
        raise DrawingError("E_UNSUPPORTED_FORMAT", "빈 파일")
    if ext == "dwg":
        version = head[:6].decode("ascii", errors="replace")
        if version not in DWG_VERSIONS:
            raise DrawingError("E_UNSUPPORTED_FORMAT", f"DWG 서명 {version!r}")
        return DrawingFormat("dwg", version, DWG_VERSIONS[version])
    if ext == "dxf":
        if head.startswith(_BINARY_DXF):
            return DrawingFormat("dxf_binary", None, None)
        text = head.decode("latin-1").lstrip("﻿").lstrip("\xef\xbb\xbf")
        lines = [line.strip() for line in text.splitlines()[:2]]
        if len(lines) == 2 and lines[0] == "0" and lines[1].upper() in ("SECTION", "EOF"):
            return DrawingFormat("dxf_ascii", None, None)
        # 주석(999)으로 시작하는 DXF
        if lines and lines[0] == "999":
            return DrawingFormat("dxf_ascii", None, None)
        raise DrawingError("E_UNSUPPORTED_FORMAT", "DXF 서명 없음")
    raise DrawingError("E_UNSUPPORTED_FORMAT", f"확장자 .{ext}")

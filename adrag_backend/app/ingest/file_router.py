"""파일 판별 — 업로드 파일을 어느 처리기로 보낼지 정한다 (2026.10.16 Phase 1, F-2-01 / R1-1).

EXCEL_PARSE_MODE
- docling(기본): 모든 파일을 기존 docling 경로로 보낸다(기존 동작 유지, 절대 규칙 6).
- backend      : xlsx·xlsm·xls를 엑셀 전용 처리기(excel_ingest)로 보낸다. 문서 유형·파서 선택은 무시한다(D-16).
                 확장자만 믿지 않고 파일 서명을 확인해 위장 파일·암호 파일을 거부한다.
xltx·xltm(서식 파일)과 그 밖의 형식은 backend 모드에서도 docling으로 보낸다.
"""
from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

ROUTE_DOCLING = "docling"
ROUTE_EXCEL_INGEST = "excel_ingest"

EXCEL_INGEST_EXTENSIONS = frozenset({"xlsx", "xlsm"})
LEGACY_XLS_EXTENSION = "xls"

_OLE2_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_ZIP_SIGNATURE = b"PK\x03\x04"
# 암호화된 OOXML은 OLE2 컨테이너 안에 이 스트림 이름(UTF-16LE)을 가진다
_ENCRYPTED_MARKER = "EncryptedPackage".encode("utf-16-le")
_SCAN_CHUNK = 1024 * 1024


class ExcelFileRejected(ValueError):
    """엑셀 처리기로 받을 수 없는 파일. ``reason``: invalid_format | encrypted."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class ParseRoute:
    handler: str            # ROUTE_DOCLING | ROUTE_EXCEL_INGEST
    extension: str
    needs_conversion: bool = False   # .xls → .xlsx(LibreOffice) 변환 필요


def file_extension(name: str) -> str:
    return Path(name).suffix.lower().lstrip(".")


# 2026.11.12(sooyeon.choi) 도면 파싱 기능 추가 - DRAWING_PARSE_MODE=backend이면 .dwg·.dxf를 도면 처리기로 보낸다
#   (문서 유형·파서 선택은 무시). off이면 기존처럼 지원하지 않는 형식으로 거부된다.
ROUTE_DRAWING_INGEST = "drawing_ingest"
DRAWING_INGEST_EXTENSIONS = frozenset({"dwg", "dxf"})


def is_drawing_ingest_upload(name: str, mode: str) -> bool:
    return mode == "backend" and file_extension(name or "") in DRAWING_INGEST_EXTENSIONS


def is_excel_ingest_extension(name: str) -> bool:
    ext = file_extension(name)
    return ext in EXCEL_INGEST_EXTENSIONS or ext == LEGACY_XLS_EXTENSION


def resolve_parse_route(path: str, mode: str, filename: Optional[str] = None) -> ParseRoute:
    """처리 경로를 정한다. backend 모드 엑셀은 서명이 맞지 않으면 ``ExcelFileRejected``."""
    ext = file_extension(filename or path)
    if mode != "backend" or (ext not in EXCEL_INGEST_EXTENSIONS and ext != LEGACY_XLS_EXTENSION):
        return ParseRoute(ROUTE_DOCLING, ext)

    with open(path, "rb") as handle:
        head = handle.read(8)

    if ext == LEGACY_XLS_EXTENSION:
        if not head.startswith(_OLE2_SIGNATURE):
            raise ExcelFileRejected("invalid_format", "확장자는 .xls이지만 Excel 97-2003 파일이 아닙니다.")
        return ParseRoute(ROUTE_EXCEL_INGEST, ext, needs_conversion=True)

    if head.startswith(_OLE2_SIGNATURE):
        if _contains(path, _ENCRYPTED_MARKER):
            raise ExcelFileRejected("encrypted", "암호가 걸린 엑셀 파일은 등록할 수 없습니다. 암호를 해제한 뒤 올려 주세요.")
        raise ExcelFileRejected("invalid_format", f"확장자는 .{ext}이지만 OOXML(ZIP) 엑셀 파일이 아닙니다.")
    if not head.startswith(_ZIP_SIGNATURE):
        raise ExcelFileRejected("invalid_format", f"확장자는 .{ext}이지만 엑셀 파일이 아닙니다.")
    try:
        with zipfile.ZipFile(path) as archive:
            content_types = archive.read("[Content_Types].xml")
    except (zipfile.BadZipFile, KeyError) as exc:
        raise ExcelFileRejected("invalid_format", "엑셀 파일 구조를 읽을 수 없습니다.") from exc
    if b"spreadsheetml" not in content_types:
        raise ExcelFileRejected("invalid_format", f"확장자는 .{ext}이지만 스프레드시트 문서가 아닙니다.")
    return ParseRoute(ROUTE_EXCEL_INGEST, ext)


def _contains(path: str, marker: bytes) -> bool:
    """큰 파일도 메모리에 다 올리지 않고 marker를 찾는다(청크 경계 겹침 처리)."""
    overlap = len(marker) - 1
    tail = b""
    with open(path, "rb") as handle:
        while chunk := handle.read(_SCAN_CHUNK):
            if marker in tail + chunk:
                return True
            tail = chunk[-overlap:]
    return False

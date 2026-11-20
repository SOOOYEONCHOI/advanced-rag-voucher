"""도면 처리 공통 — 오류·경고 (2026.11.12(sooyeon.choi) 도면 파싱 기능 추가).

오류(E_)는 작업을 실패시키고, 경고(W_)는 결과에 남긴다. 경고 수준
- warn: 결과가 틀렸거나 빠졌을 수 있어 사람이 확인해야 하는 항목
- info: 자동으로 조치해 결과에 문제가 없는 항목
"""
from __future__ import annotations

from typing import Any, Optional

ERROR_MESSAGES = {
    "E_UNSUPPORTED_FORMAT": "도면 파일 형식이 아니거나 지원하지 않는 버전입니다.",
    "E_FILE_TOO_LARGE": "도면 파일이 허용 크기를 넘습니다.",
    "E_CONVERT_FAILED": "DWG를 DXF로 변환하지 못했습니다. 원본을 CAD 프로그램에서 다시 저장(AutoCAD 2000~2018 형식)한 뒤 올려 주세요.",
    "E_CONVERT_TIMEOUT": "DWG 변환 시간이 초과되었습니다.",
    "E_DXF_LOAD": "도면을 읽지 못했습니다.",
    "E_EMPTY_DRAWING": "도면에 내용이 없습니다.",
}

INFO_CODES = frozenset({"W_SANITIZED", "W_FONT_FALLBACK", "W_CONVERTER_WARN"})


class DrawingError(Exception):
    """도면 처리 실패. ``error_code``는 작업 결과에 그대로 남는다(화면이 안내 문구로 바꾼다)."""

    def __init__(self, code: str, detail: Optional[str] = None) -> None:
        message = ERROR_MESSAGES.get(code, code)
        super().__init__(f"{message} ({code}){': ' + detail if detail else ''}")
        self.error_code = code
        self.detail = detail


def warning(code: str, message: str, count: Optional[int] = None, **extra: Any) -> dict[str, Any]:
    item: dict[str, Any] = {"code": code, "level": "info" if code in INFO_CODES else "warn", "message": message}
    if count is not None:
        item["count"] = count
    item.update({k: v for k, v in extra.items() if v is not None})
    return item


def count_levels(warnings: list[dict[str, Any]]) -> tuple[int, int]:
    warn = sum(1 for w in warnings if w.get("level") == "warn")
    return warn, len(warnings) - warn

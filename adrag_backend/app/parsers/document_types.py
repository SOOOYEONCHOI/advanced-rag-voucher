"""문서 유형 값과 파일 확장자 호환성 규칙을 정의한다.

업로드 또는 preview 요청에서 전달된 문서 유형을 정규화하고,
선택한 유형이 파일 형식에 맞는지 공통으로 검증할 때 사용한다.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from .spreadsheet_contract import OOXML_SPREADSHEET_EXTENSIONS


class RequestedDocumentType(str, Enum):
    """사용자가 요청할 수 있는 문서 유형."""

    AUTO = "auto"
    LAW = "law"
    MANUAL = "manual"
    GENERAL = "general"
    SPREADSHEET = "spreadsheet"
    # 2026.11.12(sooyeon.choi) 도면 파싱 기능 추가 - DWG·DXF 전용(도면 처리기)
    DRAWING = "drawing"


class DocumentTypeSource(str, Enum):
    """최종 문서 유형이 결정된 출처."""

    USER_SELECTED = "user_selected"
    AUTO_DETECTED = "auto_detected"
    FILE_EXTENSION = "file_extension"


DOCUMENT_TYPE_VALUES = tuple(item.value for item in RequestedDocumentType)


class DocumentTypeMismatchError(ValueError):
    """선택한 문서 유형으로 파싱 결과를 청킹하지 못했을 때 발생하는 오류."""

    error_code = "DOCUMENT_TYPE_MISMATCH"


def normalize_requested_doc_type(value: str | None) -> str:
    """외부에서 받은 문서 유형을 정규화한다.

    값이 없으면 ``auto``를 사용하고, 앞뒤 공백을 제거한 뒤 소문자로
    변환한다. 허용 목록에 없는 값은 ``ValueError``를 발생시킨다.
    """
    normalized = (value or "auto").strip().lower()
    if normalized not in DOCUMENT_TYPE_VALUES:
        allowed = ", ".join(repr(item) for item in DOCUMENT_TYPE_VALUES)
        raise ValueError(f"document_type은 {allowed} 중 하나여야 합니다.")
    return normalized


def validate_document_type_compatibility(
    extension: str, requested_doc_type: str
) -> None:
    """파일 확장자와 요청 유형의 호환성을 검증한다.

    Excel 계열 파일은 ``auto`` 또는 ``spreadsheet``만 선택할 수 있고,
    Excel이 아닌 파일은 ``spreadsheet`` 유형을 선택할 수 없다.
    호환되지 않는 조합이면 ``ValueError``를 발생시킨다.
    """
    ext = Path(extension or "").suffix.lstrip(".").lower() or extension.lower().lstrip(".")
    requested = normalize_requested_doc_type(requested_doc_type)
    is_spreadsheet = ext in OOXML_SPREADSHEET_EXTENSIONS

    if is_spreadsheet and requested in {"law", "manual", "general"}:
        raise ValueError(
            "XLSX 계열 파일은 문서 유형을 '자동' 또는 '스프레드시트'로 선택해야 합니다."
        )
    if not is_spreadsheet and requested == "spreadsheet":
        raise ValueError(
            "스프레드시트 유형은 XLSX, XLSM, XLTX, XLTM 파일에만 사용할 수 있습니다."
        )
    # 2026.11.12(sooyeon.choi) 도면 파싱 기능 추가 - 도면 유형은 DWG·DXF만, DWG·DXF는 도면 유형만
    is_drawing = ext in ("dwg", "dxf")
    if requested == "drawing" and not is_drawing:
        raise ValueError("도면 유형은 DWG, DXF 파일에만 사용할 수 있습니다.")
    if is_drawing and requested not in ("auto", "drawing"):
        raise ValueError("DWG·DXF 파일은 문서 유형을 '자동' 또는 '도면'으로 선택해야 합니다.")

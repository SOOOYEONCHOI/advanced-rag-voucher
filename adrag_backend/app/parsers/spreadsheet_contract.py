"""Spreadsheet parser/backend shared contract values."""

from typing import Any

from pydantic import BaseModel, ConfigDict

# 2026.08.27(sooyeon.choi) 추가 - Excel 정형 파싱 공통
OOXML_SPREADSHEET_EXTENSIONS = frozenset({"xlsx", "xlsm", "xltx", "xltm"})
SPREADSHEET_SCHEMA_NAME = "StructuredSpreadsheet"
SPREADSHEET_SCHEMA_VERSION = "1.0"
SPREADSHEET_SCHEMA_MAJOR = 1
CANONICAL_BLOCK_TYPES = frozenset({
    "title", "metadata", "paragraph", "record_table", "key_value", "form",
    "matrix", "timeseries", "card_grid", "process_flow", "image_gallery",
    "instruction", "note", "resource_group", "empty", "unknown_table",
})
LEGACY_XLS_UPLOAD_MESSAGE = (
    "레거시 .xls 형식은 지원하지 않습니다. "
    "Excel에서 .xlsx로 저장한 후 다시 업로드해 주세요."
)


class SpreadsheetContractError(ValueError):
    """Spreadsheet IR가 지원 계약을 만족하지 않을 때 발생한다."""


class SpreadsheetIREnvelope(BaseModel):
    """Backend가 우선 검증하는 Spreadsheet IR 최상위 typed model."""

    # 2026.08.27(sooyeon.choi) 추가 - minor 필드 확장을 허용하는 IR envelope model
    model_config = ConfigDict(extra="ignore")

    schema_name: str
    schema_version: str
    pages: list[dict[str, Any]] | None = None
    content: dict[str, Any] | None = None


def validate_spreadsheet_ir(result: dict) -> None:
    """StructuredSpreadsheet 1.x 최상위 계약을 검증한다."""
    # 2026.08.27(sooyeon.choi) 추가 - 알 수 없는 major와 필수 필드 누락 거부
    try:
        envelope = SpreadsheetIREnvelope.model_validate(result)
    except ValueError as exc:
        raise SpreadsheetContractError("spreadsheet IR 필수 필드가 누락되었습니다.") from exc
    schema_name = envelope.schema_name
    schema_version = envelope.schema_version
    if schema_name != SPREADSHEET_SCHEMA_NAME:
        raise SpreadsheetContractError(
            f"지원하지 않는 spreadsheet schema_name: {schema_name!r}"
        )
    if not isinstance(schema_version, str):
        raise SpreadsheetContractError("spreadsheet schema_version이 누락되었습니다.")
    try:
        major = int(schema_version.split(".", 1)[0])
    except (TypeError, ValueError) as exc:
        raise SpreadsheetContractError(
            f"올바르지 않은 spreadsheet schema_version: {schema_version!r}"
        ) from exc
    if major != SPREADSHEET_SCHEMA_MAJOR:
        raise SpreadsheetContractError(
            f"지원하지 않는 spreadsheet schema major version: {schema_version}"
        )
    if envelope.pages is None and "sheets" not in (envelope.content or {}):
        raise SpreadsheetContractError("spreadsheet IR의 sheets/pages가 누락되었습니다.")
    # 2026.08.27(sooyeon.choi) 추가 - block_type 검증과 이전 입력 정규화
    containers = envelope.pages if envelope.pages is not None else (envelope.content or {}).get("sheets", [])
    for container in containers:
        for block in container.get("blocks", []):
            block_type = block.get("block_type", block.get("type"))
            if block_type in {"table", "text"}:
                block["source_block_type"] = block_type
                block_type = "record_table" if block_type == "table" else "paragraph"
                block["block_type"] = block_type
            if block_type not in CANONICAL_BLOCK_TYPES:
                raise SpreadsheetContractError(
                    f"지원하지 않는 spreadsheet block_type: {block_type!r}"
                )

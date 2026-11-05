import os

LOG_PATH = os.getenv("LOG_PATH", "./instance/log")


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def get_log_level() -> str:
    value = os.getenv("LOG_LEVEL", "INFO").strip().upper()
    if value not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ValueError(f"Invalid LOG_LEVEL: {value}")
    return value


LOG_LEVEL = get_log_level()
LOG_RETENTION_DAYS = _positive_int("LOG_RETENTION_DAYS", 30)
LOG_ERROR_RETENTION_DAYS = _positive_int("LOG_ERROR_RETENTION_DAYS", 90)
PARSER_RESOURCE_CLEANUP_INTERVAL_SECONDS = _positive_int(
    "PARSER_RESOURCE_CLEANUP_INTERVAL_SECONDS", 3600
)
PARSER_RESOURCE_TTL_HOURS = _positive_int("PARSER_RESOURCE_TTL_HOURS", 24)

# 2026.08.13(sooyeon.choi) 수정 - Excel 파서 선택 설정 추가
EXCEL_PARSER_OPENPYXL = "openpyxl"
EXCEL_PARSER_DOCLING = "docling"
SUPPORTED_EXCEL_PARSERS = {
    EXCEL_PARSER_OPENPYXL,
    EXCEL_PARSER_DOCLING,
}


def get_excel_parser() -> str:
    parser = os.getenv("EXCEL_PARSER", EXCEL_PARSER_OPENPYXL).strip().lower()
    if parser not in SUPPORTED_EXCEL_PARSERS:
        allowed = ", ".join(sorted(SUPPORTED_EXCEL_PARSERS))
        raise ValueError(f"Invalid EXCEL_PARSER: {parser}. Allowed: {allowed}")
    return parser


EXCEL_PARSER = get_excel_parser()
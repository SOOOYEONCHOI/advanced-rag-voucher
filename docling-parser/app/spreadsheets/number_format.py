"""Excel number_format 기반 표시값 formatter."""

# 2026.08.27(sooyeon.choi) 추가 - REQ-QUALITY-001 표시값 formatter
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any


_EXCEL_EPOCH = datetime(1899, 12, 30)

_MONTH_ABBR = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_MONTH_FULL = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)
_WEEKDAY_ABBR = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_WEEKDAY_FULL = (
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
)

# 지원하지 않는 형식 신호: 지수, 분수, 조건부 구역, 경과시간
_UNSUPPORTED_MARKERS = ("e+", "e-", "?/", "/?", "[h", "[m", "[s")
_GENERAL_FORMATS = {"", "general", "@"}


def format_value(value: Any, number_format: str | None) -> tuple[str, bool]:
    """number_format을 적용한 표시 문자열과 지원 여부를 반환한다.

    반환값의 두 번째 항목이 False면 형식을 해석하지 못해 기본 표기로 대체한 것이며,
    호출부는 `DISPLAY_FORMAT_UNSUPPORTED` warning을 남긴다. 원본 값은 변형하지 않는다.
    """
    if value is None:
        return "", True
    if isinstance(value, bool):
        return ("TRUE" if value else "FALSE"), True

    fmt = (number_format or "General").strip()
    if fmt.lower() in _GENERAL_FORMATS:
        return _general(value), True
    if _has_condition(fmt):
        return _general(value), False

    section = _select_section(fmt, value)
    if section is None:
        return "", True
    if _is_unsupported(section):
        return _general(value), False

    if _is_datetime_format(section):
        moment = _coerce_datetime(value)
        if moment is None:
            return _general(value), True
        return _format_datetime(moment, section)
    if isinstance(value, (int, float, Decimal)):
        negative_section = _section_count(fmt) > 1 and _to_decimal(value) < 0
        return _format_number(_to_decimal(value), section, negative_section)
    return _apply_text_section(str(value), section)


# ── 공통 유틸 ──────────────────────────────────────────────────────────────

def _general(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, time):
        return value.strftime("%H:%M:%S")
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, Decimal):
        return _general(float(value))
    return str(value)


def _to_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _split_sections(fmt: str) -> list[str]:
    """따옴표와 대괄호 안의 세미콜론을 제외하고 형식 구역을 분리한다."""
    sections: list[str] = []
    current: list[str] = []
    in_quote = False
    in_bracket = False
    index = 0
    while index < len(fmt):
        char = fmt[index]
        if char == "\\" and index + 1 < len(fmt):
            current.append(char)
            current.append(fmt[index + 1])
            index += 2
            continue
        if char == '"':
            in_quote = not in_quote
        elif char == "[" and not in_quote:
            in_bracket = True
        elif char == "]" and not in_quote:
            in_bracket = False
        if char == ";" and not in_quote and not in_bracket:
            sections.append("".join(current))
            current = []
        else:
            current.append(char)
        index += 1
    sections.append("".join(current))
    return sections


def _section_count(fmt: str) -> int:
    return len(_split_sections(fmt))


def _select_section(fmt: str, value: Any) -> str | None:
    sections = _split_sections(fmt)
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        number = _to_decimal(value)
        if number == 0 and len(sections) >= 3:
            chosen = sections[2]
        elif number < 0 and len(sections) >= 2:
            chosen = sections[1]
        else:
            chosen = sections[0]
    elif isinstance(value, str):
        chosen = sections[3] if len(sections) >= 4 else sections[0]
    else:
        chosen = sections[0]
    if chosen.strip() == "":
        # 빈 구역은 Excel에서 값을 감춘다.
        return None
    return chosen


def _strip_literals(section: str) -> str:
    """따옴표·대괄호·escape 문자를 제거해 형식 토큰만 남긴다."""
    result: list[str] = []
    index = 0
    while index < len(section):
        char = section[index]
        if char == "\\":
            index += 2
            continue
        if char == '"':
            index += 1
            while index < len(section) and section[index] != '"':
                index += 1
            index += 1
            continue
        if char == "[":
            while index < len(section) and section[index] != "]":
                index += 1
            index += 1
            continue
        result.append(char)
        index += 1
    return "".join(result)


def _has_condition(fmt: str) -> bool:
    lowered = fmt.lower()
    return any(marker in lowered for marker in ("[>", "[<", "[=", "[$$-", "[dbnum"))


def _is_unsupported(section: str) -> bool:
    lowered = section.lower()
    if any(marker in lowered for marker in _UNSUPPORTED_MARKERS):
        return True
    return "?" in _strip_literals(section)


def _is_datetime_format(section: str) -> bool:
    tokens = _strip_literals(section).lower()
    if "general" in tokens:
        return False
    return any(char in tokens for char in "ymdhs")


# ── 날짜·시간 ──────────────────────────────────────────────────────────────

def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    if isinstance(value, time):
        return datetime(1899, 12, 30, value.hour, value.minute, value.second, value.microsecond)
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        return _EXCEL_EPOCH + timedelta(days=float(value))
    return None


def _format_datetime(moment: datetime, section: str) -> tuple[str, bool]:
    tokens = _strip_literals(section).lower()
    use_12_hour = "am/pm" in tokens or "a/p" in tokens
    output: list[str] = []
    index = 0
    length = len(section)
    while index < length:
        char = section[index]
        lower = char.lower()

        if char == "\\" and index + 1 < length:
            output.append(section[index + 1])
            index += 2
            continue
        if char == '"':
            index += 1
            while index < length and section[index] != '"':
                output.append(section[index])
                index += 1
            index += 1
            continue
        if char == "[":
            while index < length and section[index] != "]":
                index += 1
            index += 1
            continue
        if char in "_*" and index + 1 < length:
            index += 2
            continue

        if lower in "ymdhs":
            run = _read_run(section, index, lower)
            index += len(run)
            output.append(_render_datetime_token(moment, lower, len(run), section, index, use_12_hour))
            continue

        remainder = section[index:].upper()
        if remainder.startswith("AM/PM"):
            output.append("AM" if moment.hour < 12 else "PM")
            index += 5
            continue
        if remainder.startswith("A/P"):
            output.append("A" if moment.hour < 12 else "P")
            index += 3
            continue

        output.append(char)
        index += 1
    return "".join(output), True


def _read_run(section: str, index: int, token: str) -> str:
    run = []
    while index < len(section) and section[index].lower() == token:
        run.append(section[index])
        index += 1
    return "".join(run)


def _render_datetime_token(
    moment: datetime,
    token: str,
    width: int,
    section: str,
    next_index: int,
    use_12_hour: bool,
) -> str:
    if token == "y":
        return f"{moment.year % 100:02d}" if width <= 2 else f"{moment.year:04d}"
    if token == "d":
        if width >= 4:
            return _WEEKDAY_FULL[moment.weekday()]
        if width == 3:
            return _WEEKDAY_ABBR[moment.weekday()]
        return f"{moment.day:0{width}d}"
    if token == "h":
        hour = moment.hour
        if use_12_hour:
            hour = hour % 12 or 12
        return f"{hour:0{width}d}"
    if token == "s":
        return f"{moment.second:0{width}d}"
    if token == "m":
        if _is_minute_context(section, next_index):
            return f"{moment.minute:0{width}d}"
        if width >= 5:
            return _MONTH_FULL[moment.month - 1][0]
        if width == 4:
            return _MONTH_FULL[moment.month - 1]
        if width == 3:
            return _MONTH_ABBR[moment.month - 1]
        return f"{moment.month:0{width}d}"
    return ""


def _is_minute_context(section: str, next_index: int) -> bool:
    """m 토큰이 분인지 월인지 앞뒤 시간 토큰으로 판정한다."""
    before = _strip_literals(section[:next_index]).lower().rstrip("m")
    previous_token = next((char for char in reversed(before) if char.isalpha()), "")
    if previous_token == "h":
        return True
    after = _strip_literals(section[next_index:]).lower()
    next_token = next((char for char in after if char.isalpha()), "")
    return next_token == "s"


# ── 숫자 ───────────────────────────────────────────────────────────────────

def _format_number(number: Decimal, section: str, negative_section: bool) -> tuple[str, bool]:
    percent_count = _strip_literals(section).count("%")
    pattern, prefix, suffix = _split_number_pattern(section)
    if not pattern:
        return "".join([prefix, suffix]), True

    scale_commas = 0
    body = pattern
    while body.endswith(","):
        scale_commas += 1
        body = body[:-1]

    value = number
    if negative_section:
        value = -value
    if percent_count:
        value = value * (Decimal(100) ** percent_count)
    if scale_commas:
        value = value / (Decimal(1000) ** scale_commas)

    if "." in body:
        integer_pattern, decimal_pattern = body.split(".", 1)
    else:
        integer_pattern, decimal_pattern = body, ""
    decimals = sum(1 for char in decimal_pattern if char in "0#")
    optional_decimals = sum(1 for char in decimal_pattern if char == "#")
    thousands = "," in integer_pattern
    min_integer_digits = sum(1 for char in integer_pattern if char == "0")

    quantized = value.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)
    negative = quantized < 0
    quantized = abs(quantized)

    digits = f"{quantized:f}"
    if "." in digits:
        integer_text, decimal_text = digits.split(".", 1)
    else:
        integer_text, decimal_text = digits, ""
    if min_integer_digits:
        integer_text = integer_text.rjust(min_integer_digits, "0")
    elif integer_text == "0" and decimals:
        integer_text = ""
    if thousands:
        integer_text = _group_thousands(integer_text)
    if optional_decimals:
        decimal_text = decimal_text.rstrip("0")
    text = integer_text
    if decimal_text:
        text = f"{text}." if text else "0."
        text += decimal_text
    if not text:
        text = "0"
    if negative:
        text = f"-{text}"
    return f"{prefix}{text}{suffix}", True


def _split_number_pattern(section: str) -> tuple[str, str, str]:
    """숫자 자리표시자와 앞뒤 리터럴을 분리한다."""
    pattern: list[str] = []
    prefix: list[str] = []
    suffix: list[str] = []
    index = 0
    length = len(section)
    while index < length:
        char = section[index]
        if char == "\\" and index + 1 < length:
            (suffix if pattern else prefix).append(section[index + 1])
            index += 2
            continue
        if char == '"':
            index += 1
            while index < length and section[index] != '"':
                (suffix if pattern else prefix).append(section[index])
                index += 1
            index += 1
            continue
        if char == "[":
            segment = []
            index += 1
            while index < length and section[index] != "]":
                segment.append(section[index])
                index += 1
            index += 1
            literal = "".join(segment)
            if literal.startswith("$"):
                # [$₩-412] 형태의 통화 구역에서 기호만 사용한다.
                symbol = literal[1:].split("-", 1)[0]
                (suffix if pattern else prefix).append(symbol)
            continue
        if char in "_*" and index + 1 < length:
            index += 2
            continue
        if char in "0#.,":
            pattern.append(char)
            index += 1
            continue
        (suffix if pattern else prefix).append(char)
        index += 1
    return "".join(pattern), "".join(prefix), "".join(suffix)


def _group_thousands(integer_text: str) -> str:
    if not integer_text:
        return integer_text
    return f"{int(integer_text):,}"


def _apply_text_section(text: str, section: str) -> tuple[str, bool]:
    output: list[str] = []
    index = 0
    length = len(section)
    while index < length:
        char = section[index]
        if char == "\\" and index + 1 < length:
            output.append(section[index + 1])
            index += 2
            continue
        if char == '"':
            index += 1
            while index < length and section[index] != '"':
                output.append(section[index])
                index += 1
            index += 1
            continue
        if char == "[":
            while index < length and section[index] != "]":
                index += 1
            index += 1
            continue
        if char in "_*" and index + 1 < length:
            index += 2
            continue
        if char == "@":
            output.append(text)
            index += 1
            continue
        output.append(char)
        index += 1
    return "".join(output), True

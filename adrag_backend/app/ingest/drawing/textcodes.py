"""도면 문자 정규화 (2026.11.12(sooyeon.choi) 도면 파싱 기능 추가).

ezdxf의 plain_text()가 서식 코드(\\P, {\\f…}, %%c 등)를 대부분 풀어 준다. 여기서는 남는 것만 처리한다.
- \\U+XXXX : 유니코드 문자
- \\M+nXXXX: 멀티바이트 문자(n=1 → cp949 등, 도면 코드페이지)
- %%c·%%d·%%p : Ø·°·± (TEXT에서 plain_text를 거치지 않은 값)
"""
from __future__ import annotations

import re

_UNICODE = re.compile(r"\\U\+([0-9A-Fa-f]{4})")
_MBCS = re.compile(r"\\M\+([1-5])([0-9A-Fa-f]{4})")
_PERCENT = {"%%c": "Ø", "%%C": "Ø", "%%d": "°", "%%D": "°", "%%p": "±", "%%P": "±", "%%%": "%"}
_SPACES = re.compile(r"[ \t\u00a0]+")
_MBCS_CODEC = {"1": "cp932", "2": "cp950", "3": "cp949", "4": "cp1361", "5": "gb2312"}


def _mbcs(match: re.Match, codepage: str) -> str:
    codec = _MBCS_CODEC.get(match.group(1), codepage)
    try:
        return bytes.fromhex(match.group(2)).decode(codec)
    except (UnicodeDecodeError, LookupError):
        try:
            return bytes.fromhex(match.group(2)).decode(codepage)
        except (UnicodeDecodeError, LookupError):
            return ""


def normalize_text(value: str, codepage: str = "cp949") -> str:
    """서식 코드를 풀고 줄마다 앞뒤 공백을 정리한다(줄바꿈은 남긴다)."""
    if not value:
        return ""
    text = _UNICODE.sub(lambda m: chr(int(m.group(1), 16)), value)
    text = _MBCS.sub(lambda m: _mbcs(m, codepage), text)
    for code, char in _PERCENT.items():
        text = text.replace(code, char)
    text = text.replace("\\P", "\n").replace("\r\n", "\n")
    lines = [_SPACES.sub(" ", line).strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line)


def label_key(value: str) -> str:
    """라벨 비교용: 대문자, 공백·밑줄·하이픈·마침표·콜론 제거."""
    return re.sub(r"[\s_\-.:：'’`]", "", (value or "").upper())


def broken_ratio(texts: list[str]) -> float:
    """깨진 문자 비율(대체 문자 U+FFFD, 짝 없는 서로게이트)."""
    total = sum(len(t) for t in texts)
    if not total:
        return 0.0
    broken = sum(1 for t in texts for ch in t if ch == "\ufffd" or 0xD800 <= ord(ch) <= 0xDFFF)
    return broken / total

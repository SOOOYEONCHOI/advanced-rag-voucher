from datetime import datetime, timezone
from typing import Optional, Union
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


def now_kst() -> datetime:
    return datetime.now(KST)


def now_kst_iso(timespec: str = "seconds") -> str:
    return now_kst().isoformat(timespec=timespec)


def format_kst_datetime(value: Optional[Union[datetime, str]]) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    value = value.astimezone(KST)
    return value.strftime("%Y-%m-%d %H:%M:%S")

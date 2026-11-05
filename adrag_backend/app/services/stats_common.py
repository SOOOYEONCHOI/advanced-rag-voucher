"""Statistics period and comparison helpers."""

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Iterable, Mapping, Optional
from zoneinfo import ZoneInfo

from app.models.stats_models import StatsPeriodValue


KST = ZoneInfo("Asia/Seoul")


@dataclass(frozen=True)
class StatsPeriodRange:
    """현재·이전 통계 기간."""

    value: StatsPeriodValue
    start: datetime
    end: datetime
    previous_start: datetime
    previous_end: datetime

    def as_response(self) -> dict:
        return {
            "value": self.value,
            "start_at": self.start.isoformat(timespec="seconds"),
            "end_at": self.end.isoformat(timespec="seconds"),
            "timezone": "Asia/Seoul",
        }


# 2026.06.19(sooyeon.choi) 추가 - KST 기준 현재·이전 통계 기간 계산
def resolve_stats_period(
    period: StatsPeriodValue,
    now: Optional[datetime] = None,
) -> StatsPeriodRange:
    current = now or datetime.now(KST)
    if current.tzinfo is None:
        current = current.replace(tzinfo=KST)
    else:
        current = current.astimezone(KST)

    if period == "month":
        start = current.replace(
            day=1,
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        elapsed = current - start
        previous_end = start
        previous_start = previous_end - elapsed
    else:
        days = int(period)
        today_start = datetime.combine(current.date(), time.min, tzinfo=KST)
        start = today_start - timedelta(days=days - 1)
        previous_end = start
        previous_start = previous_end - (current - start)

    return StatsPeriodRange(
        value=period,
        start=start,
        end=current,
        previous_start=previous_start,
        previous_end=previous_end,
    )


# 2026.06.19(sooyeon.choi) 추가 - 이전 값 0을 구분하는 증감률 계산
def percentage_change(current: float, previous: float) -> Optional[float]:
    if previous == 0:
        return None
    return round((current - previous) / previous * 100, 1)


# 2026.06.19(sooyeon.choi) 추가 - 만족도·성공률용 퍼센트포인트 계산
def percentage_point_change(
    current: Optional[float],
    previous: Optional[float],
) -> Optional[float]:
    if current is None or previous is None:
        return None
    return round(current - previous, 1)


# 2026.06.19(sooyeon.choi) 추가 - 선택 기간의 누락 날짜를 0으로 보정
def fill_daily_usage(
    period_range: StatsPeriodRange,
    rows: Iterable[Mapping[str, object]],
) -> list[dict]:
    by_date = {
        str(row["date"]): row
        for row in rows
    }
    items: list[dict] = []
    current_date = period_range.start.date()
    end_date = period_range.end.date()
    while current_date <= end_date:
        date_key = current_date.isoformat()
        row = by_date.get(date_key)
        items.append({
            "date": date_key,
            "query_count": int(row["query_count"]) if row else 0,
            "cost_usd": round(float(row["cost_usd"]), 4) if row else 0.0,
        })
        current_date += timedelta(days=1)
    return items

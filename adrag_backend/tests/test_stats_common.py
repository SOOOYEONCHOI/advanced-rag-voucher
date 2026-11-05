"""Statistics common helper tests."""

from datetime import datetime

from app.services.stats_common import (
    KST,
    fill_daily_usage,
    percentage_change,
    percentage_point_change,
    resolve_stats_period,
)


def test_resolve_rolling_period_uses_exact_calendar_dates():
    now = datetime(2026, 6, 19, 15, 30, tzinfo=KST)

    # 2026.06.19(sooyeon.choi) 추가 - 오늘 포함 7개 달력일과 동일 길이 이전 기간 검증
    period = resolve_stats_period("7", now=now)

    assert period.start.isoformat() == "2026-06-13T00:00:00+09:00"
    assert period.end == now
    assert period.previous_end == period.start
    assert (
        period.previous_end - period.previous_start
        == period.end - period.start
    )


def test_resolve_month_period_uses_elapsed_duration():
    now = datetime(2026, 6, 19, 15, 30, tzinfo=KST)

    # 2026.06.19(sooyeon.choi) 추가 - 이번 달 시작과 동일 경과시간 비교 검증
    period = resolve_stats_period("month", now=now)

    assert period.start.isoformat() == "2026-06-01T00:00:00+09:00"
    assert period.previous_end == period.start
    assert (
        period.previous_end - period.previous_start
        == period.end - period.start
    )


def test_fill_daily_usage_includes_missing_dates():
    period = resolve_stats_period(
        "7",
        now=datetime(2026, 6, 19, 15, 30, tzinfo=KST),
    )

    # 2026.06.19(sooyeon.choi) 추가 - 질의 없는 날짜의 0 보정 검증
    items = fill_daily_usage(
        period,
        [
            {
                "date": "2026-06-14",
                "query_count": 3,
                "cost_usd": 0.12345,
            }
        ],
    )

    assert len(items) == 7
    assert items[0] == {
        "date": "2026-06-13",
        "query_count": 0,
        "cost_usd": 0.0,
    }
    assert items[1] == {
        "date": "2026-06-14",
        "query_count": 3,
        "cost_usd": 0.1235,
    }


def test_change_helpers_distinguish_percent_and_percentage_point():
    # 2026.06.19(sooyeon.choi) 추가 - 건수 증감률과 비율 %p 계산 분리 검증
    assert percentage_change(120, 100) == 20.0
    assert percentage_change(10, 0) is None
    assert percentage_point_change(94.7, 92.6) == 2.1
    assert percentage_point_change(None, 92.6) is None

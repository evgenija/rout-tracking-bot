"""Тести для weekly_report_service.format_weekly_report()."""
from datetime import date
from bot.services.weekly_report_service import format_weekly_report

WEEK_START = date(2026, 4, 20)  # понеділок
WEEK_END   = date(2026, 4, 26)  # неділя

P1_STATS = [
    {"telegram_id": 111, "full_name": "Бодя", "total_km": 150.0,
     "route_count": 3, "waypoint_count": 45, "has_manual": 0},
]

P1_BY_DAY = [
    {"driver_id": 111, "full_name": "Бодя", "day": "2026-04-21",
     "km": 80.0, "route_count": 2, "waypoint_count": 25, "has_manual": 0},
    {"driver_id": 111, "full_name": "Бодя", "day": "2026-04-22",
     "km": 70.0, "route_count": 1, "waypoint_count": 20, "has_manual": 0},
]

P1_ODO = {
    111: {"2026-04-21": 78.0, "2026-04-22": 68.5}
}

P2_WEEKLY = {
    111: {
        "2026-04-21": {"km": 78.0, "cost": 1560.0},
        "2026-04-22": {"km": 68.5, "cost": 1370.0},
    }
}


def test_format_returns_string():
    result = format_weekly_report(P1_STATS, P1_BY_DAY, P1_ODO, P2_WEEKLY, WEEK_START, WEEK_END)
    assert isinstance(result, str)
    assert len(result) > 0


def test_header_contains_dates():
    result = format_weekly_report(P1_STATS, P1_BY_DAY, P1_ODO, P2_WEEKLY, WEEK_START, WEEK_END)
    assert "20.04" in result
    assert "26.04" in result


def test_driver_name_present():
    result = format_weekly_report(P1_STATS, P1_BY_DAY, P1_ODO, P2_WEEKLY, WEEK_START, WEEK_END)
    assert "Бодя" in result


def test_grand_total_section():
    result = format_weekly_report(P1_STATS, P1_BY_DAY, P1_ODO, P2_WEEKLY, WEEK_START, WEEK_END)
    assert "GRAND TOTAL" in result


def test_cost_present():
    result = format_weekly_report(P1_STATS, P1_BY_DAY, P1_ODO, P2_WEEKLY, WEEK_START, WEEK_END)
    assert "грн" in result


def test_grand_total_cost_sums_correctly():
    result = format_weekly_report(P1_STATS, P1_BY_DAY, P1_ODO, P2_WEEKLY, WEEK_START, WEEK_END)
    # 1560 + 1370 = 2930
    assert "2 930" in result


def test_empty_stats_returns_no_data_message():
    result = format_weekly_report([], [], {}, {}, WEEK_START, WEEK_END)
    assert "Немає даних" in result
    assert "GRAND TOTAL" not in result


def test_no_p2_data_shows_pending():
    result = format_weekly_report(P1_STATS, P1_BY_DAY, P1_ODO, {}, WEEK_START, WEEK_END)
    assert "⏳" in result or "немає даних" in result


def test_no_odometer_shows_dash():
    result = format_weekly_report(P1_STATS, P1_BY_DAY, {}, P2_WEEKLY, WEEK_START, WEEK_END)
    assert "—" in result

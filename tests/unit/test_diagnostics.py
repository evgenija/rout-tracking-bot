"""
Тестує функцію diagnose_route() — діагностика розбіжності кілометражу (правило 2.4).
"""
import asyncio, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from unittest.mock import AsyncMock, patch


def _wp(ts_offset_min=0, suspicious=False):
    from datetime import datetime, timezone, timedelta
    base = datetime(2026, 4, 17, 7, 0, tzinfo=timezone.utc)
    ts = (base + timedelta(minutes=ts_offset_min)).isoformat()
    return {"lat": 50.45, "lon": 30.52, "timestamp": ts, "is_suspicious": suspicious}


def run(coro):
    return asyncio.run(coro)


def test_high_suspicious_ratio_gives_reb():
    """Більше 20% підозрілих точок → діагноз 'reb'."""
    from bot.services.diagnostics import diagnose_route
    wps = [_wp(i * 5, suspicious=(i < 3)) for i in range(10)]  # 30% suspicious
    with patch("bot.services.diagnostics.get_route_waypoints", new=AsyncMock(return_value=wps)):
        result = run(diagnose_route(1))
    assert result["diagnosis"] == "reb"


def test_few_points_gives_ios():
    """Менше 10 точок → діагноз 'ios'."""
    from bot.services.diagnostics import diagnose_route
    wps = [_wp(i * 5) for i in range(5)]  # 5 < 10
    with patch("bot.services.diagnostics.get_route_waypoints", new=AsyncMock(return_value=wps)):
        result = run(diagnose_route(1))
    assert result["diagnosis"] == "ios"


def test_ios_with_suspicious_not_reb():
    """iOS (мало точок) + suspicious ≤ 20% → НЕ 'reb' (фікс 03.04)."""
    from bot.services.diagnostics import diagnose_route
    # 5 точок, 1 suspicious = 20% — рівно на межі, НЕ > 20%
    wps = [_wp(i * 5, suspicious=(i == 0)) for i in range(5)]
    with patch("bot.services.diagnostics.get_route_waypoints", new=AsyncMock(return_value=wps)):
        result = run(diagnose_route(1))
    assert result["diagnosis"] != "reb"


def test_auto_close_not_triggers_alert():
    """Авто-закриття (odometer_km=None) → should_alert=False, 2.4 не спрацьовує."""
    from bot.handlers.tracking import _format_odometer_accuracy
    # Сценарій 3: odometer_start є, але odometer_km (фініш) = None
    _, should_alert = _format_odometer_accuracy(100.0, 513015.0, None)
    assert not should_alert
    # Сценарій 4: обидва None
    _, should_alert = _format_odometer_accuracy(100.0, None, None)
    assert not should_alert

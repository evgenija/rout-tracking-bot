import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from unittest.mock import AsyncMock, patch
from bot.services.odometer_service import build_geo_mismatch_line, build_odo_start_alert

_PREV_WP = {"lat": 50.45, "lon": 30.52}
_WP_FAR  = {"lat": 50.42, "lon": 30.56}    # ~4 км
_WP_NEAR = {"lat": 50.45, "lon": 30.524}   # ~0.3 км

_ROUTE_ODO_100  = {"id": 99, "driver_id": 99, "odometer_km": 100.0, "route_date": "2026-05-29"}
_ROUTE_ODO_95   = {"id": 99, "driver_id": 99, "odometer_km": 95.0,  "route_date": "2026-05-29"}
_USER_MOCK      = {"full_name": "Тестовий Водій"}


# ── build_geo_mismatch_line ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cheat_alert_when_diff_zero_and_far():
    """odometer_diff≈0, відстань ~4 км → cheat_alert є + geo_line ⚠️."""
    with (
        patch("bot.services.odometer_service.get_last_route_by_odometer",      AsyncMock(return_value=_ROUTE_ODO_100)),
        patch("bot.services.odometer_service.get_last_finished_route_with_odo", AsyncMock(return_value=_ROUTE_ODO_100)),
        patch("bot.services.odometer_service.get_last_waypoint",                AsyncMock(return_value=_PREV_WP)),
        patch("bot.services.odometer_service.get_route_waypoints",              AsyncMock(return_value=[_WP_FAR])),
        patch("bot.services.odometer_service.get_user",                         AsyncMock(return_value=_USER_MOCK)),
    ):
        geo_line, cheat_alert = await build_geo_mismatch_line(route_id=1, odometer_start=100.0, driver_id=42)

    assert cheat_alert is not None
    assert "🚨" in cheat_alert
    assert "0 км" in cheat_alert
    assert geo_line is not None
    assert "⚠️" in geo_line


@pytest.mark.asyncio
async def test_geo_line_near_waypoints():
    """відстань ~0.3 км → geo_line 'співпадають', cheat_alert=None."""
    with (
        patch("bot.services.odometer_service.get_last_route_by_odometer",      AsyncMock(return_value=_ROUTE_ODO_100)),
        patch("bot.services.odometer_service.get_last_finished_route_with_odo", AsyncMock(return_value=_ROUTE_ODO_100)),
        patch("bot.services.odometer_service.get_last_waypoint",                AsyncMock(return_value=_PREV_WP)),
        patch("bot.services.odometer_service.get_route_waypoints",              AsyncMock(return_value=[_WP_NEAR])),
        patch("bot.services.odometer_service.get_user",                         AsyncMock(return_value=_USER_MOCK)),
    ):
        geo_line, cheat_alert = await build_geo_mismatch_line(route_id=1, odometer_start=100.0, driver_id=42)

    assert geo_line is not None
    assert "співпадають" in geo_line
    assert cheat_alert is None


@pytest.mark.asyncio
async def test_geo_line_far_diff_nonzero():
    """odometer_diff=5, відстань ~4 км → geo_line підтверджує пробіг, cheat_alert=None."""
    with (
        patch("bot.services.odometer_service.get_last_route_by_odometer",      AsyncMock(return_value=_ROUTE_ODO_95)),
        patch("bot.services.odometer_service.get_last_finished_route_with_odo", AsyncMock(return_value=_ROUTE_ODO_95)),
        patch("bot.services.odometer_service.get_last_waypoint",                AsyncMock(return_value=_PREV_WP)),
        patch("bot.services.odometer_service.get_route_waypoints",              AsyncMock(return_value=[_WP_FAR])),
        patch("bot.services.odometer_service.get_user",                         AsyncMock(return_value=_USER_MOCK)),
    ):
        geo_line, cheat_alert = await build_geo_mismatch_line(route_id=1, odometer_start=100.0, driver_id=42)

    assert geo_line is not None
    assert "переміщалась" in geo_line
    assert cheat_alert is None


@pytest.mark.asyncio
async def test_returns_none_tuple_when_no_waypoints():
    """prev_wp=None → (None, None), без виключення."""
    with (
        patch("bot.services.odometer_service.get_last_route_by_odometer",      AsyncMock(return_value=_ROUTE_ODO_100)),
        patch("bot.services.odometer_service.get_last_finished_route_with_odo", AsyncMock(return_value=_ROUTE_ODO_100)),
        patch("bot.services.odometer_service.get_last_waypoint",                AsyncMock(return_value=None)),
        patch("bot.services.odometer_service.get_route_waypoints",              AsyncMock(return_value=[])),
        patch("bot.services.odometer_service.get_user",                         AsyncMock(return_value=_USER_MOCK)),
    ):
        geo_line, cheat_alert = await build_geo_mismatch_line(route_id=1, odometer_start=100.0, driver_id=42)

    assert geo_line is None
    assert cheat_alert is None


@pytest.mark.asyncio
async def test_returns_none_tuple_when_no_prev_route():
    """Немає попереднього маршруту → (None, None)."""
    with (
        patch("bot.services.odometer_service.get_last_route_by_odometer",      AsyncMock(return_value=None)),
        patch("bot.services.odometer_service.get_last_finished_route_with_odo", AsyncMock(return_value=None)),
        patch("bot.services.odometer_service.get_last_waypoint",                AsyncMock(return_value=_PREV_WP)),
        patch("bot.services.odometer_service.get_route_waypoints",              AsyncMock(return_value=[_WP_FAR])),
    ):
        geo_line, cheat_alert = await build_geo_mismatch_line(route_id=1, odometer_start=100.0, driver_id=42)

    assert geo_line is None
    assert cheat_alert is None


# ── build_odo_start_alert ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_same_machine_different_driver():
    """Машина до цього їздила з іншим водієм → рядок про машину в алерті."""
    _machine_route = {"id": 10, "driver_id": 999, "odometer_km": 611766.0}
    _last_route    = {"odometer_km": 611199.0, "route_date": "2026-05-29"}
    _current_user  = {"full_name": "ZAZA"}
    _other_user    = {"full_name": "Уколов Олексій"}

    def _get_user_side(uid):
        return _current_user if uid == 42 else _other_user

    with (
        patch("bot.services.odometer_service.get_last_finished_route_with_odo", AsyncMock(return_value=_last_route)),
        patch("bot.services.odometer_service.get_last_route_by_odometer",       AsyncMock(return_value=_machine_route)),
        patch("bot.services.odometer_service.get_user",                          AsyncMock(side_effect=_get_user_side)),
    ):
        alert = await build_odo_start_alert(driver_id=42, odometer_start=611769.0)

    assert alert is not None
    assert "Уколов Олексій" in alert
    assert "машина" in alert


@pytest.mark.asyncio
async def test_same_driver_no_machine_line():
    """Попередній маршрут по машині — той самий водій → рядок про машину відсутній."""
    _machine_route = {"id": 10, "driver_id": 42, "odometer_km": 100.0}
    _last_route    = {"odometer_km": 95.0, "route_date": "2026-05-29"}
    _user          = {"full_name": "Тест"}

    with (
        patch("bot.services.odometer_service.get_last_finished_route_with_odo", AsyncMock(return_value=_last_route)),
        patch("bot.services.odometer_service.get_last_route_by_odometer",       AsyncMock(return_value=_machine_route)),
        patch("bot.services.odometer_service.get_user",                          AsyncMock(return_value=_user)),
    ):
        alert = await build_odo_start_alert(driver_id=42, odometer_start=100.0)

    assert alert is not None
    assert "машина" not in alert

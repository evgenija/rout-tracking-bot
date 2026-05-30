import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from unittest.mock import AsyncMock, patch
from bot.services.odometer_service import build_geo_mismatch_line

# Координати: Київ і точки на різних відстанях
_PREV_WP   = {"lat": 50.45, "lon": 30.52}   # фініш попереднього маршруту
_WP_FAR    = {"lat": 50.42, "lon": 30.56}   # ~4 км — має тригерити
_WP_NEAR   = {"lat": 50.45, "lon": 30.524}  # ~0.3 км — не тригерить

_LAST_ROUTE_ZERO  = {"id": 99, "odometer_km": 100.0, "route_date": "2026-05-29"}  # diff = 0
_LAST_ROUTE_NONZERO = {"id": 99, "odometer_km": 95.0, "route_date": "2026-05-29"}  # diff = 5


@pytest.mark.asyncio
async def test_triggers_when_diff_zero_and_far():
    """odometer_diff=0, відстань ~4 км → рядок є."""
    with (
        patch("bot.services.odometer_service.get_last_finished_route_with_odo", AsyncMock(return_value=_LAST_ROUTE_ZERO)),
        patch("bot.services.odometer_service.get_last_route_by_odometer", AsyncMock(return_value=None)),
        patch("bot.services.odometer_service.get_last_waypoint", AsyncMock(return_value=_PREV_WP)),
        patch("bot.services.odometer_service.get_route_waypoints", AsyncMock(return_value=[_WP_FAR])),
    ):
        result = await build_geo_mismatch_line(route_id=1, odometer_start=100.0, driver_id=42)

    assert result is not None
    assert "⚠️" in result
    assert "одометр 0 км" in result


@pytest.mark.asyncio
async def test_no_trigger_when_diff_zero_but_near():
    """odometer_diff=0, відстань ~0.3 км → рядок немає."""
    with (
        patch("bot.services.odometer_service.get_last_finished_route_with_odo", AsyncMock(return_value=_LAST_ROUTE_ZERO)),
        patch("bot.services.odometer_service.get_last_route_by_odometer", AsyncMock(return_value=None)),
        patch("bot.services.odometer_service.get_last_waypoint", AsyncMock(return_value=_PREV_WP)),
        patch("bot.services.odometer_service.get_route_waypoints", AsyncMock(return_value=[_WP_NEAR])),
    ):
        result = await build_geo_mismatch_line(route_id=1, odometer_start=100.0, driver_id=42)

    assert result is None


@pytest.mark.asyncio
async def test_no_trigger_when_diff_nonzero():
    """odometer_diff=5, відстань ~4 км → рядок немає (потрібні обидві умови)."""
    with (
        patch("bot.services.odometer_service.get_last_finished_route_with_odo", AsyncMock(return_value=_LAST_ROUTE_NONZERO)),
        patch("bot.services.odometer_service.get_last_route_by_odometer", AsyncMock(return_value=None)),
        patch("bot.services.odometer_service.get_last_waypoint", AsyncMock(return_value=_PREV_WP)),
        patch("bot.services.odometer_service.get_route_waypoints", AsyncMock(return_value=[_WP_FAR])),
    ):
        result = await build_geo_mismatch_line(route_id=1, odometer_start=100.0, driver_id=42)

    assert result is None


@pytest.mark.asyncio
async def test_no_error_when_coordinates_none():
    """prev_wp=None, current_wps=[] → рядок немає, без виключення."""
    with (
        patch("bot.services.odometer_service.get_last_finished_route_with_odo", AsyncMock(return_value=_LAST_ROUTE_ZERO)),
        patch("bot.services.odometer_service.get_last_route_by_odometer", AsyncMock(return_value=None)),
        patch("bot.services.odometer_service.get_last_waypoint", AsyncMock(return_value=None)),
        patch("bot.services.odometer_service.get_route_waypoints", AsyncMock(return_value=[])),
    ):
        result = await build_geo_mismatch_line(route_id=1, odometer_start=100.0, driver_id=42)

    assert result is None

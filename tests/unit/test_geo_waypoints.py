"""
Тести для bot/utils/geo.py — формат waypoints у запиті до Google Directions API.
Регресія 21.04.2026 (commit bee8699): via: префікс прибрано, зупинки = "lat,lon".
"""
import sys, os, asyncio
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from unittest.mock import AsyncMock, MagicMock, patch
from bot.utils.geo import get_road_distance_for_route


def _wps(*coords):
    return [{"lat": lat, "lon": lon} for lat, lon in coords]


def _ok_response(distance_m=50000, polyline="abc123"):
    return {
        "status": "OK",
        "routes": [{
            "legs": [{"distance": {"value": distance_m}}],
            "overview_polyline": {"points": polyline},
        }],
    }


def _make_session_mock(response_data):
    resp = AsyncMock()
    resp.json = AsyncMock(return_value=response_data)
    get_ctx = MagicMock(
        __aenter__=AsyncMock(return_value=resp),
        __aexit__=AsyncMock(return_value=False),
    )
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.get = MagicMock(return_value=get_ctx)
    return MagicMock(return_value=session), session


def _sent_params(session_mock):
    """Повертає dict params переданий у session.get(...)."""
    _, call_kwargs = session_mock.get.call_args
    return call_kwargs.get("params", {})


def test_waypoints_no_via_prefix():
    """Waypoints у запиті до Google НЕ містять 'via:' (regression commit bee8699)."""
    client_cls, session = _make_session_mock(_ok_response())
    wps = _wps((50.4501, 30.5234), (50.3000, 30.7000), (50.3450, 30.9474))

    with patch("bot.config.GOOGLE_MAPS_API_KEY", "fake-key"), \
         patch("bot.utils.geo._route_distance_cache", {}), \
         patch("aiohttp.ClientSession", client_cls):
        asyncio.run(get_road_distance_for_route(wps))

    waypoints_str = _sent_params(session).get("waypoints", "")
    assert "via:" not in waypoints_str, f"waypoints містять 'via:': {waypoints_str!r}"


def test_waypoints_format():
    """Кожна проміжна точка — рядок 'lat,lon' (float через кому, без префіксів)."""
    client_cls, session = _make_session_mock(_ok_response())
    wps = _wps((50.4501, 30.5234), (50.35, 30.65), (50.30, 30.80), (50.3450, 30.9474))

    with patch("bot.config.GOOGLE_MAPS_API_KEY", "fake-key"), \
         patch("bot.utils.geo._route_distance_cache", {}), \
         patch("aiohttp.ClientSession", client_cls):
        asyncio.run(get_road_distance_for_route(wps))

    waypoints_str = _sent_params(session).get("waypoints", "")
    parts = waypoints_str.split("|")
    assert len(parts) == 2, f"Очікувалось 2 проміжних точки, отримано: {parts}"
    for part in parts:
        lat_s, lon_s = part.split(",")
        float(lat_s)
        float(lon_s)


def test_single_waypoint():
    """1 проміжна точка → waypoints містить рівно один запис 'lat,lon' без '|'."""
    client_cls, session = _make_session_mock(_ok_response())
    wps = _wps((50.4501, 30.5234), (50.35, 30.65), (50.3450, 30.9474))

    with patch("bot.config.GOOGLE_MAPS_API_KEY", "fake-key"), \
         patch("bot.utils.geo._route_distance_cache", {}), \
         patch("aiohttp.ClientSession", client_cls):
        asyncio.run(get_road_distance_for_route(wps))

    params = _sent_params(session)
    assert "waypoints" in params
    wp_str = params["waypoints"]
    assert "|" not in wp_str, f"Одна точка не повинна містити '|': {wp_str!r}"
    lat_s, lon_s = wp_str.split(",")
    float(lat_s)
    float(lon_s)


def test_empty_waypoints():
    """2 точки (origin+destination) → параметр 'waypoints' відсутній у запиті."""
    client_cls, session = _make_session_mock(_ok_response())
    wps = _wps((50.4501, 30.5234), (50.3450, 30.9474))

    with patch("bot.config.GOOGLE_MAPS_API_KEY", "fake-key"), \
         patch("bot.utils.geo._route_distance_cache", {}), \
         patch("aiohttp.ClientSession", client_cls):
        asyncio.run(get_road_distance_for_route(wps))

    params = _sent_params(session)
    assert "waypoints" not in params, \
        f"waypoints не мають передаватись для 2 точок, params={params}"

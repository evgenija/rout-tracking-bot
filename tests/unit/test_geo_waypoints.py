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


# ── Chunks (> 25 waypoints) ───────────────────────────────────────────────────

def _make_session_multi(responses):
    """Session mock що повертає послідовно різні відповіді для кількох API викликів."""
    resp = AsyncMock()
    resp.json = AsyncMock(side_effect=responses)
    get_ctx = MagicMock(
        __aenter__=AsyncMock(return_value=resp),
        __aexit__=AsyncMock(return_value=False),
    )
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.get = MagicMock(return_value=get_ctx)
    return MagicMock(return_value=session), session


def test_chunks_boundary_26_points():
    """26 точок (25+1) — мінімальний тригер для chunks: рівно 2 API виклики, km = сума."""
    from bot.utils.geo import _encode_polyline
    poly1 = _encode_polyline([(50.0, 30.0), (50.1, 30.1)])
    poly2 = _encode_polyline([(50.1, 30.1), (50.2, 30.2)])

    wps = [{"lat": 50.0 + i * 0.01, "lon": 30.5} for i in range(26)]
    client_cls, session = _make_session_multi([
        _ok_response(distance_m=50_000, polyline=poly1),  # chunk1: точки 0-24 (25 pts)
        _ok_response(distance_m=20_000, polyline=poly2),  # chunk2: точки 24-25 (2 pts, overlap)
    ])

    with patch("bot.config.GOOGLE_MAPS_API_KEY", "fake-key"), \
         patch("bot.utils.geo._route_distance_cache", {}), \
         patch("bot.utils.geo._polyline_cache", {}), \
         patch("bot.utils.geo._leg_distances_cache", {}), \
         patch("aiohttp.ClientSession", client_cls):
        result = asyncio.run(get_road_distance_for_route(wps))

    assert session.get.call_count == 2, \
        f"26 точок → 2 API виклики, отримано {session.get.call_count}"
    assert result == 70.0, \
        f"km має бути 50+20=70.0, отримано {result}"


def test_chunks_polyline_merged_for_26_points():
    """При > 25 точок polylines з усіх chunks об'єднуються в один повний polyline.

    Overlap-точка (перша точка chunk 2 = остання chunk 1) пропускається при merge,
    щоб маршрут не мав дублікатів координат.
    """
    from bot.utils.geo import get_cached_polyline, _encode_polyline, _decode_polyline

    # Два шматки маршруту з overlap-точкою (50.1, 30.1)
    chunk1_coords = [(50.0, 30.0), (50.05, 30.05), (50.1, 30.1)]
    chunk2_coords = [(50.1, 30.1), (50.15, 30.15), (50.2, 30.2)]
    poly1 = _encode_polyline(chunk1_coords)
    poly2 = _encode_polyline(chunk2_coords)

    wps = [{"lat": 50.0 + i * 0.01, "lon": 30.5} for i in range(26)]
    client_cls, _session = _make_session_multi([
        _ok_response(distance_m=50_000, polyline=poly1),
        _ok_response(distance_m=20_000, polyline=poly2),
    ])
    poly_cache: dict = {}

    with patch("bot.config.GOOGLE_MAPS_API_KEY", "fake-key"), \
         patch("bot.utils.geo._route_distance_cache", {}), \
         patch("bot.utils.geo._polyline_cache", poly_cache), \
         patch("bot.utils.geo._leg_distances_cache", {}), \
         patch("aiohttp.ClientSession", client_cls):
        asyncio.run(get_road_distance_for_route(wps))
        polyline = get_cached_polyline(wps)

    assert polyline is not None, "chunks mode → merged polyline, не None"
    merged_coords = _decode_polyline(polyline)
    # chunk1 (3 pts) + chunk2 (3 pts) - 1 overlap = 5 унікальних точок
    assert len(merged_coords) == 5, \
        f"Merged polyline має 5 координат (без дублікату overlap), отримано {len(merged_coords)}"
    # Перша і остання відповідають початку chunk1 і кінцю chunk2
    assert abs(merged_coords[0][0] - 50.0) < 0.001
    assert abs(merged_coords[-1][0] - 50.2) < 0.001


def test_single_chunk_unchanged_for_25_points():
    """Рівно 25 non-suspicious точок → 1 API виклик і polyline зберігається (regression)."""
    from bot.utils.geo import get_cached_polyline

    wps = [{"lat": 50.0 + i * 0.01, "lon": 30.5} for i in range(25)]
    client_cls, session = _make_session_multi([
        _ok_response(distance_m=40_000, polyline="poly_25pts"),
    ])
    poly_cache: dict = {}

    with patch("bot.config.GOOGLE_MAPS_API_KEY", "fake-key"), \
         patch("bot.utils.geo._route_distance_cache", {}), \
         patch("bot.utils.geo._polyline_cache", poly_cache), \
         patch("bot.utils.geo._leg_distances_cache", {}), \
         patch("aiohttp.ClientSession", client_cls):
        result = asyncio.run(get_road_distance_for_route(wps))
        polyline = get_cached_polyline(wps)

    assert session.get.call_count == 1, \
        f"25 точок → 1 API виклик, отримано {session.get.call_count}"
    assert result == 40.0, f"Очікувалось 40.0 км, отримано {result}"
    assert polyline == "poly_25pts", \
        f"1 chunk → polyline зберігається, отримано {polyline!r}"

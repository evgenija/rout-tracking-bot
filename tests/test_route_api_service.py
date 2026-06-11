"""
Тести для bot/services/route_api_service.py та пов'язаних змін у geo.py.
Не потребують живої БД — використовують мок aiosqlite.

Запуск:
    pytest tests/test_route_api_service.py -v
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from bot.utils.geo import haversine, get_road_distances_per_leg


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_cursor(fetchone=None, fetchall=None):
    cur = MagicMock()
    cur.fetchone = AsyncMock(return_value=fetchone)
    cur.fetchall = AsyncMock(return_value=fetchall or [])
    cur.__aenter__ = AsyncMock(return_value=cur)
    cur.__aexit__ = AsyncMock(return_value=False)
    return cur


def _make_db(*cursors):
    """Повертає мок aiosqlite-з'єднання; кожен виклик db.execute() споживає наступний cursor."""
    db = MagicMock()
    db.execute = MagicMock(side_effect=list(cursors))
    db.__aenter__ = AsyncMock(return_value=db)
    db.__aexit__ = AsyncMock(return_value=False)
    return db


# ── haversine ─────────────────────────────────────────────────────────────────

def test_haversine_kyiv_to_lviv():
    """Київ → Львів по прямій: ~469 км."""
    dist = haversine(50.4501, 30.5234, 49.8397, 24.0297)
    assert 460 < dist < 480, f"Очікувалось ~469 км, отримано {dist:.2f}"


# ── get_route_json ─────────────────────────────────────────────────────────────

def test_get_route_json_returns_none_for_unknown_id():
    """Маршрут не знайдено → None."""
    db = _make_db(_make_cursor(fetchone=None))
    with patch("aiosqlite.connect", return_value=db):
        from bot.services.route_api_service import get_route_json
        result = asyncio.run(get_route_json(99999))
    assert result is None


def test_get_route_json_structure():
    """Маршрут знайдено → dict з усіма обов'язковими ключами."""
    mock_route = {
        "id": 42,
        "driver_id": 100,
        "driver_name": "Іван Тестовий",
        "start_time": "2026-04-23T08:00:00",
        "end_time": "2026-04-23T17:00:00",
        "total_km": 153.5,
        "odometer_start": 15000.0,
        "odometer_km": 15153.5,
        "route_polyline": "abc~encoded~polyline",
    }
    mock_waypoints = [
        {"id": 1, "name": "Старт", "lat": 50.4501, "lon": 30.5234,
         "timestamp": "2026-04-23T08:00:00", "is_suspicious": 0},
        {"id": 2, "name": "Фініш", "lat": 49.8397, "lon": 24.0297,
         "timestamp": "2026-04-23T17:00:00", "is_suspicious": 0},
    ]

    # aiosqlite.Row підтримує доступ за рядковим ключем — dict цього достатньо
    class _Row(dict):
        def __getitem__(self, key):
            return super().__getitem__(key)

    route_row = _Row(mock_route)
    wp_rows = [_Row(w) for w in mock_waypoints]

    db = _make_db(
        _make_cursor(fetchone=route_row),
        _make_cursor(fetchall=wp_rows),
    )
    with patch("aiosqlite.connect", return_value=db):
        with patch("bot.services.route_api_service.get_road_distances_per_leg",
                   new=AsyncMock(return_value=[469.0])):
            from bot.services import route_api_service
            result = asyncio.run(route_api_service.get_route_json(42))

    assert result is not None

    # Обов'язкові ключі верхнього рівня
    for key in ("route_id", "driver_id", "start_time", "end_time",
                "total_km", "odometer_start", "odometer_finish",
                "route_polyline", "waypoints"):
        assert key in result, f"Ключ '{key}' відсутній у відповіді"

    assert result["route_id"] == 42
    assert result["route_polyline"] == "abc~encoded~polyline"
    assert len(result["waypoints"]) == 2

    # Перша точка — немає попередньої → distance/speed = None
    assert result["waypoints"][0]["distance_km"] is None
    assert result["waypoints"][0]["speed_kmh"] is None

    # Друга точка — має відстань і швидкість
    assert result["waypoints"][1]["distance_km"] is not None
    assert result["waypoints"][1]["speed_kmh"] is not None


def test_get_route_json_null_polyline():
    """route_polyline=None (старий маршрут) → повертається без помилок."""
    mock_route = {
        "id": 7, "driver_id": 5, "driver_name": None,
        "start_time": "2026-04-23T08:00:00",
        "end_time": "2026-04-23T12:00:00", "total_km": 80.0,
        "odometer_start": None, "odometer_km": None, "route_polyline": None,
    }

    class _Row(dict):
        pass

    db = _make_db(
        _make_cursor(fetchone=_Row(mock_route)),
        _make_cursor(fetchall=[]),
    )
    with patch("aiosqlite.connect", return_value=db):
        with patch("bot.services.route_api_service.get_road_distances_per_leg",
                   new=AsyncMock(return_value=[])):
            from bot.services import route_api_service
            result = asyncio.run(route_api_service.get_route_json(7))

    assert result is not None
    assert result["route_polyline"] is None
    assert result["waypoints"] == []


# ── get_road_distances_per_leg ────────────────────────────────────────────────

def test_get_road_distances_per_leg_empty():
    """Менше 2 точок → порожній список."""
    result = asyncio.run(get_road_distances_per_leg([]))
    assert result == []
    result1 = asyncio.run(get_road_distances_per_leg([{"lat": 50.0, "lon": 30.0, "is_suspicious": False}]))
    assert result1 == []


def test_get_road_distances_per_leg_fallback_to_haversine():
    """Без API key → haversine fallback; повертає N-1 значень > 0."""
    wps = [
        {"lat": 50.4501, "lon": 30.5234, "is_suspicious": False, "timestamp": "2026-04-23T08:00:00"},
        {"lat": 49.8397, "lon": 24.0297, "is_suspicious": False, "timestamp": "2026-04-23T17:00:00"},
    ]
    with patch("bot.config.GOOGLE_MAPS_API_KEY", ""):
        result = asyncio.run(get_road_distances_per_leg(wps))
    assert len(result) == 1
    assert result[0] > 0


def test_get_road_distances_per_leg_suspicious_count():
    """N waypoints → N-1 значень незалежно від підозрілих точок."""
    wps = [
        {"lat": 50.4501, "lon": 30.5234, "is_suspicious": False},
        {"lat": 99.0,    "lon": 99.0,    "is_suspicious": True},
        {"lat": 49.8397, "lon": 24.0297, "is_suspicious": False},
    ]
    with patch("bot.config.GOOGLE_MAPS_API_KEY", ""):
        result = asyncio.run(get_road_distances_per_leg(wps))
    assert len(result) == 2
    assert all(d > 0 for d in result)


# ── get_cached_polyline ───────────────────────────────────────────────────────

def test_get_cached_polyline_returns_none_before_api_call():
    """Без попереднього API-запиту кеш порожній → None."""
    from bot.utils.geo import get_cached_polyline
    wps = [
        {"lat": 50.4501, "lon": 30.5234},
        {"lat": 49.8397, "lon": 24.0297},
    ]
    with patch("bot.utils.geo._polyline_cache", {}):
        result = get_cached_polyline(wps)
    assert result is None


def test_get_cached_polyline_after_api_call():
    """Після API-запиту get_cached_polyline повертає polyline з кешу."""
    from bot.utils.geo import get_cached_polyline, _route_cache_key
    wps = [
        {"lat": 50.4501, "lon": 30.5234},
        {"lat": 49.8397, "lon": 24.0297},
    ]
    valid = [w for w in wps if not w.get("is_suspicious")]
    key = _route_cache_key(valid)
    fake_polyline = "test_encoded_polyline_string"
    with patch("bot.utils.geo._polyline_cache", {key: fake_polyline}):
        result = get_cached_polyline(wps)
    assert result == fake_polyline


def test_get_cached_polyline_single_point_returns_none():
    """Менше 2 точок → None (не можна побудувати маршрут)."""
    from bot.utils.geo import get_cached_polyline
    assert get_cached_polyline([]) is None
    assert get_cached_polyline([{"lat": 50.0, "lon": 30.0}]) is None

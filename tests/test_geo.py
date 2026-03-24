"""
Тести для bot/utils/geo.py

Запуск:
    pytest tests/test_geo.py -v
"""
import asyncio
import math
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.utils.geo import haversine, calculate_route_distance, is_suspicious, get_road_distance_for_route


# ── haversine ─────────────────────────────────────────────────────────────────

def test_haversine_kyiv_boryspil():
    """Київ центр → Бориспіль: ~32 км пряма лінія (не 39 — то дорожня відстань)."""
    d = haversine(50.4501, 30.5234, 50.3450, 30.9474)
    assert 31.0 < d < 34.0, f"Очікувалось ~32 км, отримано {d:.2f} км"


def test_haversine_london_paris():
    """Лондон → Париж: відома відстань ~341 км по прямій."""
    d = haversine(51.5074, -0.1278, 48.8566, 2.3522)
    assert 338.0 < d < 348.0, f"Очікувалось ~341 км, отримано {d:.2f} км"


def test_haversine_same_point():
    """Та сама точка — відстань нуль."""
    d = haversine(50.4501, 30.5234, 50.4501, 30.5234)
    assert d == 0.0


def test_haversine_symmetry():
    """Відстань A→B == B→A."""
    d1 = haversine(50.4501, 30.5234, 50.3450, 30.9474)
    d2 = haversine(50.3450, 30.9474, 50.4501, 30.5234)
    assert abs(d1 - d2) < 0.001


def test_haversine_returns_km_not_meters():
    """Результат в кілометрах: Київ→Бориспіль має бути ~32, не ~32000."""
    d = haversine(50.4501, 30.5234, 50.3450, 30.9474)
    assert d < 1000, "Схоже результат в метрах, а не км"


# ── calculate_route_distance ──────────────────────────────────────────────────

def test_route_single_segment():
    """Два waypoints: результат == одна відстань haversine."""
    wps = [
        {"lat": 50.4501, "lon": 30.5234},
        {"lat": 50.3450, "lon": 30.9474},
    ]
    expected = haversine(50.4501, 30.5234, 50.3450, 30.9474)
    assert calculate_route_distance(wps) == round(expected, 2)


def test_route_three_points():
    """Три точки: відстань == сума двох сегментів."""
    wps = [
        {"lat": 50.4501, "lon": 30.5234},
        {"lat": 50.3450, "lon": 30.9474},
        {"lat": 50.2000, "lon": 30.7000},
    ]
    expected = (
        haversine(50.4501, 30.5234, 50.3450, 30.9474)
        + haversine(50.3450, 30.9474, 50.2000, 30.7000)
    )
    assert calculate_route_distance(wps) == round(expected, 2)


def test_route_empty():
    """Порожній маршрут → 0."""
    assert calculate_route_distance([]) == 0.0


def test_route_single_point():
    """Один waypoint → 0 (нема сегментів)."""
    assert calculate_route_distance([{"lat": 50.45, "lon": 30.52}]) == 0.0


def test_route_sums_all_pairs():
    """Перевіряємо що розраховуються ВСІ сусідні пари, а не тільки перша/остання.
    Маршрут із зворотним рухом (zigzag): сума сегментів >> пряма від першої до останньої.
    """
    wps = [
        {"lat": 50.45, "lon": 30.52},   # старт
        {"lat": 50.55, "lon": 30.70},   # далеко на північ
        {"lat": 50.40, "lon": 30.50},   # назад на південь
        {"lat": 50.46, "lon": 30.53},   # трохи від старту
    ]
    first_to_last = haversine(50.45, 30.52, 50.46, 30.53)  # ~1.4 km
    full_route = calculate_route_distance(wps)              # >>20 km
    assert full_route > first_to_last * 5, (
        f"Очікувалось набагато більше від {first_to_last:.2f} км, отримано {full_route:.2f} км"
    )


# ── is_suspicious ─────────────────────────────────────────────────────────────

def test_suspicious_teleport():
    """Стрибок > 100 км — підозріло (незалежно від часу)."""
    assert is_suspicious(
        50.4501, 30.5234, "2026-03-24T08:00:00",
        48.0000, 37.0000, "2026-03-24T09:00:00",  # ~700 км — Київ → Донецьк
        max_distance_km=100.0,
    )


def test_suspicious_impossible_speed():
    """50 км за 10 хвилин = 300 км/год → підозріло."""
    assert is_suspicious(
        50.4501, 30.5234, "2026-03-24T08:00:00",
        50.8500, 31.0000, "2026-03-24T08:10:00",  # ~60 км
        max_distance_km=100.0,
        min_time_minutes=2.0,
    )


def test_not_suspicious_normal_delivery():
    """Нормальна доставка: 5 км за 20 хвилин = 15 км/год → не підозріло."""
    assert not is_suspicious(
        50.4501, 30.5234, "2026-03-24T08:00:00",
        50.4800, 30.5600, "2026-03-24T08:20:00",  # ~4 км
        max_distance_km=100.0,
        min_time_minutes=2.0,
    )


def test_not_suspicious_fast_but_possible():
    """30 км за 30 хвилин = 60 км/год → не підозріло."""
    assert not is_suspicious(
        50.4501, 30.5234, "2026-03-24T08:00:00",
        50.7000, 30.7500, "2026-03-24T08:30:00",  # ~34 км
        max_distance_km=100.0,
        min_time_minutes=2.0,
    )


# ── get_road_distance_for_route ───────────────────────────────────────────────

_SAMPLE_WPS = [
    {"lat": 50.4501, "lon": 30.5234},
    {"lat": 50.3450, "lon": 30.9474},
]


def _make_directions_response(meters: int) -> dict:
    return {
        "status": "OK",
        "routes": [{"legs": [{"distance": {"value": meters}}]}],
    }


def _make_mock_session(mock_resp):
    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.get = MagicMock(return_value=MagicMock(
        __aenter__=AsyncMock(return_value=mock_resp),
        __aexit__=AsyncMock(return_value=False),
    ))
    return mock_session


def test_google_api_success():
    """Успішна відповідь API: повертає дорожню відстань у км."""
    mock_resp = AsyncMock()
    mock_resp.json = AsyncMock(return_value=_make_directions_response(39000))
    mock_session = _make_mock_session(mock_resp)

    with patch("bot.config.GOOGLE_MAPS_API_KEY", "fake-key"), \
         patch("bot.utils.geo._route_distance_cache", {}), \
         patch("aiohttp.ClientSession", return_value=mock_session):
        result = asyncio.run(get_road_distance_for_route(_SAMPLE_WPS))

    assert result == 39.0, f"Очікувалось 39.0 км, отримано {result}"


def test_google_api_error_fallback():
    """При помилці API — повертає haversine × 1.4 (з допуском ±0.1 км на округлення)."""
    with patch("bot.config.GOOGLE_MAPS_API_KEY", "fake-key"), \
         patch("bot.utils.geo._route_distance_cache", {}), \
         patch("aiohttp.ClientSession", side_effect=Exception("timeout")):
        result = asyncio.run(get_road_distance_for_route(_SAMPLE_WPS))

    haversine_km = haversine(50.4501, 30.5234, 50.3450, 30.9474)
    expected = haversine_km * 1.4
    assert abs(result - expected) < 0.1, f"Очікувався fallback ~{expected:.2f} км, отримано {result}"


def test_google_api_no_key_fallback():
    """Без API key — повертає haversine × 1.4 без HTTP-запиту (з допуском ±0.1 км)."""
    with patch("bot.config.GOOGLE_MAPS_API_KEY", ""), \
         patch("bot.utils.geo._route_distance_cache", {}):
        result = asyncio.run(get_road_distance_for_route(_SAMPLE_WPS))

    haversine_km = haversine(50.4501, 30.5234, 50.3450, 30.9474)
    expected = haversine_km * 1.4
    assert abs(result - expected) < 0.1, f"Очікувався fallback ~{expected:.2f} км, отримано {result}"


def test_google_api_cache_hit():
    """Другий виклик з тими ж точками не робить HTTP-запит (cache hit)."""
    mock_resp = AsyncMock()
    mock_resp.json = AsyncMock(return_value=_make_directions_response(39000))
    mock_session = _make_mock_session(mock_resp)

    cache = {}
    with patch("bot.config.GOOGLE_MAPS_API_KEY", "fake-key"), \
         patch("bot.utils.geo._route_distance_cache", cache), \
         patch("aiohttp.ClientSession", return_value=mock_session):
        r1 = asyncio.run(get_road_distance_for_route(_SAMPLE_WPS))
        r2 = asyncio.run(get_road_distance_for_route(_SAMPLE_WPS))

    assert r1 == r2 == 39.0
    # Перший виклик зробив запит, другий — взяв з кешу
    assert mock_session.get.call_count == 1, "Очікувався 1 HTTP-запит (кеш), отримано більше"

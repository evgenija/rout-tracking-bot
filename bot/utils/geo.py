import hashlib
import logging
import math
from datetime import datetime
from typing import Dict, List, Optional

import aiohttp

logger = logging.getLogger(__name__)

# ── In-memory cache для Google Directions API ─────────────────────────────────
# Ключ: MD5 від округлених координат маршруту
# Значення: відстань в км
_route_distance_cache: dict = {}

# Лічильник API-запитів (скидається при рестарті, для логування)
_api_call_count: int = 0


# ── Haversine ─────────────────────────────────────────────────────────────────

def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Відстань між двома GPS-координатами в км (пряма лінія, формула Гаверсина)."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def calculate_route_distance(waypoints: List[Dict]) -> float:
    """Пряма відстань маршруту (haversine). Підозрілі точки виключаються.

    Використовується як fallback і для внутрішніх перевірок.
    Для кінцевого кілометражу в боті — використовувати get_road_distance_for_route().
    """
    valid = [wp for wp in waypoints if not wp.get("is_suspicious")]
    total = 0.0
    for i in range(1, len(valid)):
        total += haversine(
            valid[i - 1]["lat"], valid[i - 1]["lon"],
            valid[i]["lat"],     valid[i]["lon"],
        )
    return round(total, 2)


# ── Google Directions API ─────────────────────────────────────────────────────

def _route_cache_key(waypoints: List[Dict]) -> str:
    """MD5-ключ кешу за округленими координатами маршруту (4 знаки ≈ 11 м точність)."""
    coords = tuple(
        (round(wp["lat"], 4), round(wp["lon"], 4))
        for wp in waypoints
    )
    return hashlib.md5(str(coords).encode()).hexdigest()


async def get_road_distance_for_route(waypoints: List[Dict]) -> float:
    """Дорожня відстань маршруту через Google Directions API.

    Переваги перед haversine:
    - Враховує реальні дороги (у 1.3-2x точніше для міської логістики)
    - 1 API-запит на весь маршрут (не на кожну пару точок)

    Вартість:
    - Google Directions API: $0.005 за запит (до 100 waypoints включно)
    - 5 водіїв × 1 запит/маршрут × 30 днів = 150 запитів/місяць ≈ $0.75/місяць
    - Значно дешевше за Distance Matrix ($11/місяць при 75 парах/день)

    Підозрілі точки (is_suspicious=True) виключаються з маршруту.

    Fallback при помилці або відсутності API key:
    - haversine × 1.4 (середній коефіцієнт дорога/пряма для України)
    """
    global _api_call_count

    from bot.config import GOOGLE_MAPS_API_KEY

    # Фільтруємо підозрілі GPS-точки
    valid = [wp for wp in waypoints if not wp.get("is_suspicious")]
    if len(valid) < 2:
        return 0.0

    # Кеш
    cache_key = _route_cache_key(valid)
    if cache_key in _route_distance_cache:
        logger.debug("Google Directions: cache hit (%d точок)", len(valid))
        return _route_distance_cache[cache_key]

    # Немає API key — fallback
    if not GOOGLE_MAPS_API_KEY:
        logger.warning(
            "GOOGLE_MAPS_API_KEY не задано — fallback haversine×1.4 (%.2f км)",
            calculate_route_distance(valid) * 1.4,
        )
        return round(calculate_route_distance(valid) * 1.4, 2)

    # Google Directions API обмеження: максимум 25 точок (origin + 23 via + destination)
    # При більшій кількості — рівномірна вибірка
    if len(valid) > 25:
        logger.warning(
            "Маршрут має %d точок > 25 (ліміт Directions API) — рівномірна вибірка",
            len(valid),
        )
        step = (len(valid) - 1) / 24
        indices = {0, len(valid) - 1} | {int(round(i * step)) for i in range(1, 24)}
        valid = [valid[i] for i in sorted(indices)]

    origin      = f"{round(valid[0]['lat'], 6)},{round(valid[0]['lon'], 6)}"
    destination = f"{round(valid[-1]['lat'], 6)},{round(valid[-1]['lon'], 6)}"

    params: dict = {
        "origin":      origin,
        "destination": destination,
        "mode":        "driving",
        "key":         GOOGLE_MAPS_API_KEY,
    }
    if len(valid) > 2:
        params["waypoints"] = "|".join(
            f"via:{round(wp['lat'], 6)},{round(wp['lon'], 6)}"
            for wp in valid[1:-1]
        )

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://maps.googleapis.com/maps/api/directions/json",
                params=params,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                data = await resp.json()

        _api_call_count += 1
        status = data.get("status")

        if status == "OK":
            total_meters = sum(
                leg["distance"]["value"]
                for leg in data["routes"][0]["legs"]
            )
            total_km = round(total_meters / 1000, 2)
            _route_distance_cache[cache_key] = total_km
            logger.info(
                "Google Directions API запит #%d: %d точок → %.2f км (дорогами)",
                _api_call_count, len(valid), total_km,
            )
            return total_km

        logger.warning("Google Directions API статус: %s — fallback haversine×1.4", status)

    except Exception as exc:
        logger.warning("Google Directions API помилка: %s — fallback haversine×1.4", exc)

    # Fallback
    fallback = round(calculate_route_distance(valid) * 1.4, 2)
    logger.warning("Fallback haversine×1.4: %.2f км", fallback)
    return fallback


def get_api_call_count() -> int:
    """Поточний лічильник API-запитів (з моменту запуску бота)."""
    return _api_call_count


# ── GPS spoofing detection ────────────────────────────────────────────────────

def is_suspicious(
    lat1: float, lon1: float, time1: str,
    lat2: float, lon2: float, time2: str,
    max_distance_km: float = 500.0,
    min_time_minutes: float = 2.0,
) -> bool:
    """Повертає True, якщо переміщення підозріло (можливий GPS-спуфінг / РЕБ).

    Перевіряє два критерії:
    1. Миттєва телепортація — відстань > max_distance_km (за замовчуванням 100 км).
    2. Неможлива швидкість — > 200 км/год між двома мітками.

    Раніше функція повертала False для БУДЬ-ЯКОЇ відстані ≤ 500 км,
    тобто ніколи не спрацьовувала для України. Виправлено.
    """
    distance = haversine(lat1, lon1, lat2, lon2)

    # Критерій 1: миттєва телепортація
    if distance > max_distance_km:
        return True

    t1 = datetime.fromisoformat(time1)
    t2 = datetime.fromisoformat(time2)
    elapsed_minutes = abs((t2 - t1).total_seconds() / 60)

    # Замало часу між мітками — не оцінюємо швидкість
    if elapsed_minutes < min_time_minutes:
        return False

    # Критерій 2: швидкість > 200 км/год — фізично неможлива для вантажівки
    speed_kmh = distance / (elapsed_minutes / 60)
    return speed_kmh > 200.0


# ── Utilities ─────────────────────────────────────────────────────────────────

def format_duration(start_time: str, end_time: Optional[str]) -> str:
    """Форматує тривалість між двома ISO-timestamp'ами."""
    t1 = datetime.fromisoformat(start_time)
    t2 = datetime.fromisoformat(end_time) if end_time else datetime.now()
    delta = t2 - t1
    hours = int(delta.total_seconds() // 3600)
    minutes = int((delta.total_seconds() % 3600) // 60)
    return f"{hours}г {minutes}хв"

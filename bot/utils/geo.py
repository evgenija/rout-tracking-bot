import hashlib
import logging
import math
from datetime import datetime
from typing import Dict, List, Optional

from bot.utils.time_utils import get_kyiv_time, to_kyiv_time

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
    - Google Directions API Advanced: $0.010 за запит (>10 зупинок)
    - 5 водіїв × 1 запит/маршрут × 30 днів = 150 запитів/місяць ≈ $1.50/місяць
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

    # Google Directions API обмеження: максимум 25 проміжних зупинок
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
            f"{round(wp['lat'], 6)},{round(wp['lon'], 6)}"
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
            if total_km > 1000:
                logger.warning(
                    "Google Directions API: підозріло великий результат %.2f км (%d точок) — перевір дані",
                    total_km, len(valid),
                )
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

async def is_suspicious(
    lat1: float, lon1: float, time1: str,
    lat2: float, lon2: float, time2: str,
    max_distance_km: float = 130.0,
    min_time_minutes: float = 2.0,
    *,
    bot=None,
    driver_name: str = "невідомий",
    route_id: int | None = None,
    admin_ids: list | None = None,
    skip_level2: bool = False,
) -> bool:
    """Повертає True, якщо точка підозріла (GPS-спуфінг / РЕБ / поза геозоною).

    Рівень 1 — швидкісні перевірки (існуючі):
      • Телепортація: відстань > max_distance_km (130 км) за < min_time_minutes
      • Неможлива швидкість: > 160 км/год між мітками
      • Комбінована: dist > 35 км І speed > 150 км/год одночасно

    Рівень 2 — абсолютний поріг (пропускається при skip_level2=True — ping-флоу в tracking.py):
      • Відстань > max_distance_km (130 км) за будь-який час

    Рівень 3 — геозони (нові):
      • Перевірка A: точка поза межами України (lat 44.3–52.4, lon 22.1–40.2)
      При спрацюванні геозони — надсилає сповіщення адмінам через bot (якщо передано).
    """
    distance = haversine(lat1, lon1, lat2, lon2)

    t1 = to_kyiv_time(datetime.fromisoformat(time1))
    t2 = to_kyiv_time(datetime.fromisoformat(time2))
    elapsed_minutes = abs((t2 - t1).total_seconds() / 60)

    # ── Рівень 1: швидкісні перевірки ────────────────────────────────────────
    if elapsed_minutes < min_time_minutes:
        # Телепортація: замало часу → перевіряємо тільки відстань
        if distance > max_distance_km:
            return True
    else:
        speed_kmh = distance / (elapsed_minutes / 60)

        # Неможлива швидкість
        if speed_kmh > 160.0:
            return True

        # Комбінована: велика відстань + висока швидкість одночасно
        # (dist > 35 але speed < 150 → нормальна довга пауза між точками)
        if distance > 35.0 and speed_kmh > 150.0:
            return True

    # ── Рівень 2: абсолютний поріг відстані (ping-флоу в tracking.py) ────────
    if not skip_level2 and distance > max_distance_km:
        return True

    # ── Рівень 3: геозони ─────────────────────────────────────────────────────

    async def _notify(text: str) -> None:
        if bot and admin_ids:
            for aid in admin_ids:
                try:
                    await bot.send_message(aid, text)
                except Exception as exc:
                    logger.warning("Не вдалося надіслати сповіщення адміну %d: %s", aid, exc)

    # Перевірка A — поза межами України
    if not (44.3 <= lat2 <= 52.4 and 22.1 <= lon2 <= 40.2):
        await _notify(
            f"⚠️ GPS-аномалія: точка водія {driver_name} поза межами України\n"
            f"lat={lat2}, lon={lon2}\n"
            f"Маршрут #{route_id}"
        )
        return True

    return False


# ── GPS spike detection ───────────────────────────────────────────────────────

# Мінімальний стрибок A→B щоб вважати потенційним спайком
_SPIKE_MIN_JUMP_KM: float = 20.0
# Якщо B→C < A→B * коефіцієнт — C "повернулась", тобто B = spike
_SPIKE_RETURN_RATIO: float = 0.3


def is_spike(
    lat_a: float, lon_a: float,
    lat_b: float, lon_b: float,
    lat_c: float, lon_c: float,
) -> bool:
    """Повертає True якщо точка B є GPS spike між A і C.

    Умова (правило 1.6):
      1. dist(A, B) > _SPIKE_MIN_JUMP_KM (20 км) — стрибок далеко
      2. dist(B, C) < dist(A, B) * _SPIKE_RETURN_RATIO (0.3) — наступна повернулась

    Викликається ретроспективно: коли надходить C, перевіряємо чи B є спайком.
    Якщо наступної точки ще немає — не викликати.
    """
    dist_ab = haversine(lat_a, lon_a, lat_b, lon_b)
    if dist_ab <= _SPIKE_MIN_JUMP_KM:
        return False
    dist_bc = haversine(lat_b, lon_b, lat_c, lon_c)
    return dist_bc < dist_ab * _SPIKE_RETURN_RATIO


# ── Utilities ─────────────────────────────────────────────────────────────────

def format_duration(start_time: str, end_time: Optional[str]) -> str:
    """Форматує тривалість між двома ISO-timestamp'ами."""
    t1 = to_kyiv_time(datetime.fromisoformat(start_time))
    t2 = to_kyiv_time(datetime.fromisoformat(end_time)) if end_time else get_kyiv_time()
    delta = t2 - t1
    hours = int(delta.total_seconds() // 3600)
    minutes = int((delta.total_seconds() % 3600) // 60)
    return f"{hours}г {minutes}хв"

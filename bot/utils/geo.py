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
# Значення: overview_polyline.points (encoded polyline string або None)
_polyline_cache: dict = {}
# Значення: список відстаней по відрізках (leg distances в км)
_leg_distances_cache: dict = {}

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

def _decode_polyline(encoded: str) -> list:
    """Декодує Google Encoded Polyline → список (lat, lon)."""
    result = []
    index = lat = lng = 0
    while index < len(encoded):
        for coord_idx in range(2):
            b, shift, val = 0, 0, 0
            while True:
                b = ord(encoded[index]) - 63
                index += 1
                val |= (b & 0x1f) << shift
                shift += 5
                if b < 0x20:
                    break
            if val & 1:
                val = ~val
            val >>= 1
            if coord_idx == 0:
                lat += val
            else:
                lng += val
        result.append((lat / 1e5, lng / 1e5))
    return result


def _encode_polyline(coords: list) -> str:
    """Кодує список (lat, lon) → Google Encoded Polyline."""
    result = []
    prev_lat = prev_lng = 0
    for lat, lng in coords:
        lat_e5 = round(lat * 1e5)
        lng_e5 = round(lng * 1e5)
        for val in [lat_e5 - prev_lat, lng_e5 - prev_lng]:
            val = ~(val << 1) if val < 0 else val << 1
            while val >= 0x20:
                result.append(chr((0x20 | (val & 0x1f)) + 63))
                val >>= 5
            result.append(chr(val + 63))
        prev_lat, prev_lng = lat_e5, lng_e5
    return "".join(result)


def _merge_polylines(polylines: list) -> Optional[str]:
    """Об'єднує список encoded polylines в один.

    Перша точка кожного наступного chunk = остання попереднього (overlap) — пропускається.
    Повертає None якщо будь-який chunk не має polyline.
    """
    if not polylines or any(pl is None for pl in polylines):
        return None
    if len(polylines) == 1:
        return polylines[0]
    all_coords: list = []
    for i, pl in enumerate(polylines):
        coords = _decode_polyline(pl)
        if i > 0:
            coords = coords[1:]  # перша точка = остання попереднього chunk (overlap)
        all_coords.extend(coords)
    return _encode_polyline(all_coords)


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

    Вартість:
    - Google Directions API Advanced: $0.010 за запит (>10 зупинок)
    - При > 25 точок маршрут ділиться на chunks по 25 з overlap — кілька запитів.

    Підозрілі точки (is_suspicious=True) виключаються з маршруту.

    Fallback при помилці або відсутності API key:
    - haversine × 1.4 (середній коефіцієнт дорога/пряма для України)
    """
    global _api_call_count

    from bot.config import GOOGLE_MAPS_API_KEY

    valid = [wp for wp in waypoints if not wp.get("is_suspicious")]
    if len(valid) < 2:
        return 0.0

    cache_key = _route_cache_key(valid)
    if cache_key in _route_distance_cache:
        logger.debug("Google Directions: cache hit (%d точок)", len(valid))
        return _route_distance_cache[cache_key]

    if not GOOGLE_MAPS_API_KEY:
        fallback = round(calculate_route_distance(valid) * 1.4, 2)
        logger.warning("GOOGLE_MAPS_API_KEY не задано — fallback haversine×1.4 (%.2f км)", fallback)
        return fallback

    # Chunks по 25 точок з overlap (остання точка chunk N = перша chunk N+1).
    # Це гарантує що всі waypoints враховуються — без рівномірної вибірки.
    CHUNK_SIZE = 25
    chunks: list = []
    i = 0
    while i < len(valid):
        end = min(i + CHUNK_SIZE, len(valid))
        chunks.append(valid[i:end])
        if end == len(valid):
            break
        i = end - 1  # overlap: остання точка поточного = перша наступного

    total_km = 0.0
    all_leg_km: list = []
    chunk_polylines: list = []

    try:
        async with aiohttp.ClientSession() as session:
            for chunk_idx, chunk in enumerate(chunks):
                origin      = f"{round(chunk[0]['lat'], 6)},{round(chunk[0]['lon'], 6)}"
                destination = f"{round(chunk[-1]['lat'], 6)},{round(chunk[-1]['lon'], 6)}"
                params: dict = {
                    "origin":      origin,
                    "destination": destination,
                    "mode":        "driving",
                    "key":         GOOGLE_MAPS_API_KEY,
                }
                if len(chunk) > 2:
                    params["waypoints"] = "|".join(
                        f"{round(wp['lat'], 6)},{round(wp['lon'], 6)}"
                        for wp in chunk[1:-1]
                    )

                async with session.get(
                    "https://maps.googleapis.com/maps/api/directions/json",
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    data = await resp.json()

                _api_call_count += 1
                status = data.get("status")

                if status != "OK":
                    logger.warning(
                        "Google Directions API статус: %s (chunk %d/%d) — fallback",
                        status, chunk_idx + 1, len(chunks),
                    )
                    if status in ("REQUEST_DENIED", "OVER_DAILY_LIMIT", "OVER_QUERY_LIMIT"):
                        try:
                            import asyncio as _asyncio
                            from bot.utils.alerts import alert_super_admins
                            _asyncio.create_task(alert_super_admins(
                                f"🚨 Google Directions API: {status}\n"
                                f"Маршрути рахуються по haversine×1.4.\n"
                                f"Перевір білінг: console.cloud.google.com"
                            ))
                        except Exception:
                            pass
                    raise RuntimeError(f"API status {status}")

                route0 = data["routes"][0]
                chunk_km = sum(leg["distance"]["value"] for leg in route0["legs"]) / 1000
                total_km += chunk_km
                all_leg_km.extend(leg["distance"]["value"] / 1000 for leg in route0["legs"])
                chunk_polylines.append(route0.get("overview_polyline", {}).get("points"))

                logger.info(
                    "Google Directions API запит #%d (chunk %d/%d): %d точок → %.2f км",
                    _api_call_count, chunk_idx + 1, len(chunks), len(chunk), chunk_km,
                )

    except Exception as exc:
        logger.warning("Google Directions API помилка: %s — fallback haversine×1.4", exc)
        fallback = round(calculate_route_distance(valid) * 1.4, 2)
        logger.warning("Fallback haversine×1.4: %.2f км", fallback)
        return fallback

    total_km = round(total_km, 2)
    if total_km > 1000:
        logger.warning(
            "Google Directions API: підозріло великий результат %.2f км (%d точок) — перевір дані",
            total_km, len(valid),
        )

    _route_distance_cache[cache_key] = total_km
    _leg_distances_cache[cache_key] = all_leg_km
    _polyline_cache[cache_key] = _merge_polylines(chunk_polylines)

    return total_km


def get_api_call_count() -> int:
    """Поточний лічильник API-запитів (з моменту запуску бота)."""
    return _api_call_count


async def get_road_distances_per_leg(waypoints: List[Dict]) -> List[float]:
    """Дорожня відстань для кожного відрізку (N waypoints → N-1 значень).

    Робить один Google Directions API запит для валідних точок.
    Для пар де одна або обидві точки підозрілі — haversine fallback.
    """
    n = len(waypoints)
    if n < 2:
        return []

    valid = [(i, wp) for i, wp in enumerate(waypoints) if not wp.get("is_suspicious")]

    if len(valid) < 2:
        return [
            haversine(waypoints[i]["lat"], waypoints[i]["lon"],
                      waypoints[i + 1]["lat"], waypoints[i + 1]["lon"])
            for i in range(n - 1)
        ]

    valid_wps = [wp for _, wp in valid]
    cache_key = _route_cache_key(valid_wps)

    if cache_key not in _leg_distances_cache:
        await get_road_distance_for_route(valid_wps)

    road_legs = _leg_distances_cache.get(cache_key)

    valid_indices = [i for i, _ in valid]
    road_map: dict = {}
    if road_legs and len(road_legs) == len(valid) - 1:
        for pos in range(len(valid) - 1):
            road_map[(valid_indices[pos], valid_indices[pos + 1])] = road_legs[pos]

    return [
        road_map.get((i, i + 1),
                     haversine(waypoints[i]["lat"], waypoints[i]["lon"],
                               waypoints[i + 1]["lat"], waypoints[i + 1]["lon"]))
        for i in range(n - 1)
    ]


def get_cached_polyline(waypoints: List[Dict]) -> str | None:
    """Повертає overview_polyline з кешу для waypoints (якщо був API-запит в цьому сеансі).

    Використовує той самий ключ що і get_road_distance_for_route().
    Повертає None якщо запит не відбувся або API повернув помилку (fallback-шлях).
    """
    valid = [wp for wp in waypoints if not wp.get("is_suspicious")]
    if len(valid) < 2:
        return None
    return _polyline_cache.get(_route_cache_key(valid))


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
# Максимальна реальна швидкість на дорозі — вище означає GPS-артефакт
_SPIKE_SPEED_THRESHOLD_KMH: float = 130.0


def is_spike(
    lat_a: float, lon_a: float,
    lat_b: float, lon_b: float,
    lat_c: float, lon_c: float,
    time_a=None,
    time_b=None,
) -> bool:
    """Повертає True якщо точка B є GPS spike між A і C.

    Якщо передані time_a і time_b (datetime): перевіряємо швидкість A→B.
    Швидкість ≤ 130 км/год → B реальна точка → не spike, незалежно від геометрії.
    Швидкість > 130 км/год → застосовується геометрична перевірка dist(B,C).

    Без timestamps: тільки геометрична перевірка (backward compatible).

    Викликається ретроспективно: коли надходить C, перевіряємо чи B є спайком.
    """
    dist_ab = haversine(lat_a, lon_a, lat_b, lon_b)
    if dist_ab <= _SPIKE_MIN_JUMP_KM:
        return False

    if time_a is not None and time_b is not None:
        secs = (time_b - time_a).total_seconds()
        if secs > 0:
            speed_kmh = dist_ab / secs * 3600
            if speed_kmh <= _SPIKE_SPEED_THRESHOLD_KMH:
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

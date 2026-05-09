# bot/services/route_detail_service.py
# Деталізований перегляд маршруту — єдина логіка для /route_detail, /routes, кнопки
# Тільки SELECT запити — нічого не пише в БД

import math
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from bot.models.database import get_route_info, get_route_waypoints, get_routes_in_date_range
from bot.config import MAX_DISTANCE_KM

logger = logging.getLogger(__name__)

# ── Пороги ────────────────────────────────────────────────────────────────────

SPEED_ANOMALY_KMH    = 160.0   # аномальна швидкість — можливий збій GPS
SPEED_SPIKE_KMH      = 500.0   # технічний збій координат
TIME_GAP_MINUTES     = 60.0    # gap що потребує уваги
ROUTE_RESUME_HOURS   = 3.0     # склейка маршруту (год)
ROUTE_RESUME_MINUTES = ROUTE_RESUME_HOURS * 60


# ── Утиліти ───────────────────────────────────────────────────────────────────

def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Відстань між двома точками в км. Тільки для аналізу — не пишеться в БД."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi    = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _parse_ts(ts: str) -> Optional[datetime]:
    """ISO timestamp → timezone-aware datetime або None."""
    if not ts:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def _point_name(wp: dict) -> str:
    """Назва точки з поля name. Координати не виводимо ніколи."""
    name = (wp.get("name") or "").strip()
    return name if name else f"Точка #{wp['id']}"


def _gap_str(gap_min: float) -> str:
    """Форматує хвилини: '2 год 15 хв' або '45 хв'."""
    h, m = int(gap_min // 60), int(gap_min % 60)
    return f"{h} год {m} хв" if h else f"{m} хв"


# ── Класифікація відрізку ─────────────────────────────────────────────────────

def _anomaly_explanation(
    prev: dict,
    curr: dict,
    dist_km: Optional[float],
    gap_min: Optional[float],
    speed_kmh: Optional[float],
) -> Optional[str]:
    """Пояснення мовою власника або None якщо відрізок нормальний."""

    if speed_kmh is not None and speed_kmh > SPEED_SPIKE_KMH:
        km_str  = f"{dist_km:.1f}"   if dist_km   is not None else "?"
        spd_str = f"{speed_kmh:.0f}" if speed_kmh is not None else "?"
        return (
            f"GPS збій на одній точці. Система виключила її з розрахунку і перерахувала "
            f"відрізок через попередню валідну точку: {km_str} км, {spd_str} км/год — "
            f"норма. До оплати не впливає."
        )

    if speed_kmh is not None and speed_kmh > SPEED_ANOMALY_KMH:
        return "Перевищена максимальна швидкість 160 км/год — можливий збій GPS"

    if dist_km is not None and dist_km > MAX_DISTANCE_KM:
        return f"Великий стрибок між точками — {dist_km:.0f} км без геоміток"

    if gap_min is not None and gap_min > TIME_GAP_MINUTES:
        ping_sent     = prev.get("ping_sent_at")
        ping_response = prev.get("ping_response")

        if not ping_sent:
            return (
                f"Водій не ставив геомітку {_gap_str(gap_min)}. Система не може підтвердити "
                f"маршрут на цьому відрізку. GPS дані відсутні — включено як є."
            )
        if ping_response == "stopped":
            return f"Водій підтвердив зупинку — {_gap_str(gap_min)} простою"
        if ping_response == "driving":
            return None  # підтвердив роботу — не аномалія
        # ping_response is None → вже оброблено як unconfirmed_ping вище по пріоритету
        return None

    if curr.get("is_suspicious"):
        spd = f"{speed_kmh:.0f} км/год" if speed_kmh is not None else "—"
        return f"Занадто низька швидкість пересування ({spd}). GPS включено у розрахунок."

    return None


def _classify_segment(prev: dict, curr: dict) -> dict:
    """
    Класифікує відрізок між двома waypoints.
    Пріоритет: unconfirmed_ping > route_resume > anomaly > ok
    """
    dist_km = gap_min = speed_kmh = None

    if all(prev.get(f) is not None and curr.get(f) is not None for f in ("lat", "lon")):
        try:
            dist_km = _haversine(prev["lat"], prev["lon"], curr["lat"], curr["lon"])
        except Exception:
            pass

    t1 = _parse_ts(prev.get("timestamp"))
    t2 = _parse_ts(curr.get("timestamp"))
    if t1 and t2 and t2 >= t1:
        gap_min = (t2 - t1).total_seconds() / 60

    if dist_km is not None and gap_min and gap_min > 0:
        speed_kmh = dist_km / (gap_min / 60)

    base = {
        "name_a":    _point_name(prev),
        "name_b":    _point_name(curr),
        "dist_km":   dist_km,
        "gap_min":   gap_min,
        "speed_kmh": speed_kmh,
    }

    # 1. НЕПІДТВЕРДЖЕНИЙ ПІНГ
    if prev.get("ping_sent_at") and prev.get("ping_response") in (None, "timeout"):
        return {**base, "type": "unconfirmed_ping", "explanation": None}

    # 2. СКЛЕЙКА МАРШРУТУ
    if gap_min is not None and gap_min > ROUTE_RESUME_MINUTES:
        return {**base, "type": "route_resume", "explanation": None}

    # 3. АНОМАЛІЯ
    explanation = _anomaly_explanation(prev, curr, dist_km, gap_min, speed_kmh)
    if explanation:
        return {**base, "type": "anomaly", "explanation": explanation}

    return {**base, "type": "ok", "explanation": None}


# ── Аналіз відрізків ──────────────────────────────────────────────────────────

def analyze_segments(waypoints: list) -> list:
    """Повертає тільки відрізки що потребують уваги (type != ok)."""
    if len(waypoints) < 2:
        return []
    result = []
    for i in range(1, len(waypoints)):
        seg = _classify_segment(waypoints[i - 1], waypoints[i])
        if seg["type"] != "ok":
            result.append(seg)
    return result


# ── Форматування ──────────────────────────────────────────────────────────────

def _format_segment(seg: dict, idx: int) -> str:
    """Форматує один проблемний відрізок."""
    name_a, name_b = seg["name_a"], seg["name_b"]
    dist, gap, speed = seg["dist_km"], seg["gap_min"], seg["speed_kmh"]

    if seg["type"] == "unconfirmed_ping":
        return (
            f"🔇 {name_a} → {name_b}\n"
            f"   ❗ Водій не підтвердив, що працює — геомітка без підтвердження.\n"
            f"      Цей відрізок не враховується в розрахунку оплати."
        )

    if seg["type"] == "route_resume":
        gap_text = _gap_str(gap) if gap is not None else "—"
        return (
            f"🔁 Маршрут продовжено — {name_b}\n"
            f"   ⏱ Перерва: {gap_text}"
        )

    if seg["type"] == "anomaly":
        parts = []
        if dist  is not None: parts.append(f"📏 {dist:.1f} км")
        if gap   is not None: parts.append(f"⏱ {_gap_str(gap)}")
        if speed is not None: parts.append(f"🚀 {speed:.0f} км/год")
        metrics = " | ".join(parts)
        line = f"⚠️ {name_a} → {name_b}"
        if metrics:
            line += f"\n   {metrics}"
        return f"{line}\n   ❗ {seg['explanation']}"

    return ""


def format_route_detail_message(
    route: dict,
    driver_name: str,
    segments: list,
    total_waypoints: int,
) -> str:
    """Повне повідомлення для адміна. Без координат."""
    route_id = route["id"]
    total_km = route.get("total_km") or 0.0
    status   = "активний" if route.get("is_active") else "завершений"

    start_dt = _parse_ts(route.get("start_time") or "")
    date_str = start_dt.strftime("%d.%m.%Y") if start_dt else "—"

    header = (
        f"🔍 Маршрут #{route_id} | {driver_name}\n"
        f"📅 {date_str} | {total_km:.1f} км | {total_waypoints} точок\n"
    )

    # Одометр блок
    odo_start  = route.get("odometer_start")
    odo_finish = route.get("odometer_km")
    if odo_start is not None and odo_finish is not None and odo_finish > odo_start:
        odo_diff = odo_finish - odo_start
        odo_line = f"📊 Одометр: {odo_start:.0f} → {odo_finish:.0f} (+{odo_diff:.0f} км) | GPS: {total_km:.1f} км"
    else:
        odo_line = None

    if not segments:
        result = header + f"\n✅ Маршрут #{route_id} — всі відрізки в нормі"
        if odo_line:
            result += f"\n{odo_line}"
        return result

    total_segments = total_waypoints - 1 if total_waypoints > 1 else 0
    ok_count       = max(0, total_segments - len(segments))

    lines = [
        header,
        f"⚠️ Знайдено {len(segments)} відрізків що потребують уваги:\n",
    ]
    for i, seg in enumerate(segments, 1):
        text = _format_segment(seg, i)
        if text:
            lines.append(f"{i}. {text}")

    if ok_count > 0:
        lines.append(f"\n✅ Решта {ok_count} відрізків — в нормі")
    if odo_line:
        lines.append(odo_line)

    return "\n".join(lines)


# ── Публічне API ──────────────────────────────────────────────────────────────

async def get_route_detail(route_id: int) -> Optional[dict]:
    """
    Головна функція. Повертає dict або None якщо маршрут не знайдено.
    Нічого не пише в БД.
    """
    route_info = await get_route_info(route_id)
    if not route_info:
        return None

    waypoints = await get_route_waypoints(route_id)
    segments  = analyze_segments(waypoints)

    return {
        "route_info":      route_info,
        "driver_name":     route_info.get("full_name") or f"Водій #{route_info['driver_id']}",
        "segments":        segments,
        "total_waypoints": len(waypoints),
    }


async def get_recent_routes(days: int = 7) -> list:
    """
    Маршрути за останні N днів з ім'ям водія, датою, km.
    Використовує існуючу get_routes_in_date_range з database.py.
    """
    today     = datetime.now(timezone.utc).date()
    date_from = (today - timedelta(days=days - 1)).isoformat()
    date_to   = today.isoformat()
    return await get_routes_in_date_range(date_from, date_to)

"""Діагностика причин критичної розбіжності кілометражу (правило 2.4).

Використовується при завершенні маршруту коли похибка трекінг vs одометр > 40%.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TypedDict

from bot.models.database import get_route_waypoints
from bot.utils.geo import haversine

logger = logging.getLogger(__name__)

# ── Пороги діагностики ────────────────────────────────────────────────────────

# РЕБ: частка підозрілих точок (> N% → reb)
_REB_SUSPICIOUS_RATIO = 0.20       # 20%
# РЕБ: швидкість між сусідніми точками (> N км/год → reb)
_REB_SPEED_THRESHOLD_KMH = 150.0
# iOS: мало точок за весь маршрут (< N → ios)
_IOS_MIN_WAYPOINTS = 10
# iOS: великий gap між сусідніми точками (> N хвилин → ios)
_IOS_GAP_MINUTES = 60.0


class DiagnosisResult(TypedDict):
    diagnosis: str          # 'reb' | 'ios' | 'unknown'
    indicators: list        # list[str] — рядки для повідомлення адміну
    recommended_action: str | None  # 'recalculate' | 'odometer' | None


async def diagnose_route(route_id: int) -> DiagnosisResult:
    """Аналізує маршрут і повертає діагноз розбіжності.

    Логіка (пріоритет: reb > ios > unknown):
      'reb'     — % is_suspicious > 20% АБО є точки де швидкість > 150 км/год
      'ios'     — кількість waypoints < 10 АБО є gap між точками > 60 хвилин
      'unknown' — жодна умова не спрацювала
    """
    waypoints = await get_route_waypoints(route_id)
    total = len(waypoints)

    indicators: list[str] = []
    is_reb = False
    is_ios = False

    # ── РЕБ-перевірки ────────────────────────────────────────────────────────

    if total > 0:
        suspicious_count = sum(1 for wp in waypoints if wp.get("is_suspicious"))
        suspicious_ratio = suspicious_count / total
        if suspicious_ratio > _REB_SUSPICIOUS_RATIO:
            is_reb = True
            indicators.append(
                f"• Підозрілих точок: {suspicious_count}/{total} "
                f"({suspicious_ratio * 100:.0f}% > порогу {int(_REB_SUSPICIOUS_RATIO * 100)}%)"
            )

    # Перевірка швидкості між сусідніми точками
    fmt = "%Y-%m-%dT%H:%M:%S.%f"
    fmt_short = "%Y-%m-%dT%H:%M:%S"

    def _parse_ts(ts: str) -> datetime | None:
        for f in (fmt, fmt_short):
            try:
                return datetime.strptime(ts, f)
            except ValueError:
                pass
        try:
            return datetime.fromisoformat(ts)
        except Exception:
            return None

    max_speed_kmh = 0.0
    max_gap_min = 0.0

    for i in range(1, total):
        p1, p2 = waypoints[i - 1], waypoints[i]
        t1 = _parse_ts(p1["timestamp"])
        t2 = _parse_ts(p2["timestamp"])
        if t1 is None or t2 is None:
            continue

        t1 = t1 if t1.tzinfo is not None else t1.replace(tzinfo=timezone.utc)
        t2 = t2 if t2.tzinfo is not None else t2.replace(tzinfo=timezone.utc)
        dt_min = abs((t2 - t1).total_seconds() / 60)
        if dt_min > max_gap_min:
            max_gap_min = dt_min

        if dt_min > 0:
            dist = haversine(p1["lat"], p1["lon"], p2["lat"], p2["lon"])
            speed = dist / (dt_min / 60)
            if speed > max_speed_kmh:
                max_speed_kmh = speed

    if max_speed_kmh > _REB_SPEED_THRESHOLD_KMH:
        is_reb = True
        indicators.append(
            f"• Максимальна швидкість між точками: {max_speed_kmh:.0f} км/год "
            f"(> порогу {int(_REB_SPEED_THRESHOLD_KMH)} км/год)"
        )

    # ── iOS-перевірки (тільки якщо РЕБ не підтверджено) ─────────────────────

    if not is_reb:
        if total < _IOS_MIN_WAYPOINTS:
            is_ios = True
            indicators.append(
                f"• Мало точок GPS: {total} (< порогу {_IOS_MIN_WAYPOINTS})"
            )

        if max_gap_min > _IOS_GAP_MINUTES:
            is_ios = True
            indicators.append(
                f"• Великий gap між точками: {max_gap_min:.0f} хв "
                f"(> порогу {int(_IOS_GAP_MINUTES)} хв)"
            )

    # ── Формування результату ─────────────────────────────────────────────────

    if is_reb:
        diagnosis = "reb"
        recommended_action = "recalculate"
    elif is_ios:
        diagnosis = "ios"
        recommended_action = "odometer"
    else:
        diagnosis = "unknown"
        recommended_action = None

    if not indicators:
        indicators.append("• Автоматичний аналіз не виявив конкретної причини")

    logger.info(
        "diagnose_route #%d: diagnosis=%s, indicators=%d, waypoints=%d",
        route_id, diagnosis, len(indicators), total,
    )

    return DiagnosisResult(
        diagnosis=diagnosis,
        indicators=indicators,
        recommended_action=recommended_action,
    )

"""
Тести для bot/services/diagnostics.py (diagnose_route, правило 2.4)

Запуск:
    pytest tests/test_diagnostics.py -v
"""
import asyncio
from unittest.mock import patch

import pytest

from bot.services.diagnostics import diagnose_route


# ── Хелпери ───────────────────────────────────────────────────────────────────

def _ts(offset_minutes: float = 0) -> str:
    """ISO timestamp: 2026-03-31T08:00 + offset_minutes."""
    from datetime import datetime, timedelta
    base = datetime(2026, 3, 31, 8, 0, 0)
    return (base + timedelta(minutes=offset_minutes)).isoformat()


def _make_wps(
    count: int,
    *,
    suspicious_count: int = 0,
    gap_minutes: float = 5.0,
    speed_jump_kmh: float | None = None,
) -> list[dict]:
    """Генерує список waypoints з параметрами.

    speed_jump_kmh: якщо задано, вставляє один стрибок між точками 1 і 2
    щоб швидкість перевищила поріг (переміщаємо точку 1 далеко).
    """
    # Київ центр: 50.450, 30.523 — рухаємося ~0.001° кожні gap_minutes хвилин
    wps = []
    for i in range(count):
        wps.append({
            "id":           i + 1,
            "lat":          50.450 + i * 0.001,
            "lon":          30.523 + i * 0.001,
            "timestamp":    _ts(i * gap_minutes),
            "is_suspicious": 1 if i < suspicious_count else 0,
        })

    if speed_jump_kmh is not None and count >= 3:
        # Розміщуємо точку [1] дуже далеко щоб швидкість (відстань/час) > speed_jump_kmh
        # Час між [0] і [1] = gap_minutes. Хочемо speed > speed_jump_kmh km/h
        # Потрібна відстань > speed_jump_kmh * gap_minutes / 60 km
        # ~1° ≈ 111 km. Беремо +2° lat (≈222 km) — завжди більше за 150 km/h * 5 min.
        wps[1]["lat"] = wps[0]["lat"] + 2.0
        wps[1]["lon"] = wps[0]["lon"]

    return wps


# ── N1: РЕБ — suspicious_ratio > 20% ─────────────────────────────────────────

def test_reb_suspicious_ratio():
    """4/15 = 26.7% підозрілих → diagnosis='reb', recommended_action='recalculate'."""
    wps = _make_wps(15, suspicious_count=4)

    with patch("bot.services.diagnostics.get_route_waypoints", return_value=wps):
        result = asyncio.run(diagnose_route(1))

    assert result["diagnosis"] == "reb", f"Очікувався 'reb', отримано '{result['diagnosis']}'"
    assert result["recommended_action"] == "recalculate"
    assert any("Підозрілих" in i for i in result["indicators"])


# ── N2: РЕБ — швидкість між точками > 150 км/год ─────────────────────────────

def test_reb_speed():
    """Стрибок ~222 км за 5 хв = ~2664 км/год → diagnosis='reb'."""
    wps = _make_wps(5, gap_minutes=5.0, speed_jump_kmh=200.0)

    with patch("bot.services.diagnostics.get_route_waypoints", return_value=wps):
        result = asyncio.run(diagnose_route(2))

    assert result["diagnosis"] == "reb", f"Очікувався 'reb', отримано '{result['diagnosis']}'"
    assert result["recommended_action"] == "recalculate"
    assert any("швидкість" in i.lower() for i in result["indicators"])


# ── N3: iOS — мало точок (< 10) ───────────────────────────────────────────────

def test_ios_few_waypoints():
    """5 точок < порогу 10 → diagnosis='ios', recommended_action='odometer'."""
    wps = _make_wps(5, gap_minutes=10.0)

    with patch("bot.services.diagnostics.get_route_waypoints", return_value=wps):
        result = asyncio.run(diagnose_route(3))

    assert result["diagnosis"] == "ios", f"Очікувався 'ios', отримано '{result['diagnosis']}'"
    assert result["recommended_action"] == "odometer"
    assert any("точок GPS" in i for i in result["indicators"])


# ── N4: iOS — великий gap між точками > 60 хвилин ────────────────────────────

def test_ios_large_gap():
    """15 точок, але один gap = 90 хвилин → diagnosis='ios'."""
    wps = _make_wps(15, gap_minutes=5.0)
    # Вставляємо великий gap між точками 7 і 8
    from datetime import datetime, timedelta
    t7 = datetime.fromisoformat(wps[7]["timestamp"])
    wps[8]["timestamp"] = (t7 + timedelta(minutes=90)).isoformat()

    with patch("bot.services.diagnostics.get_route_waypoints", return_value=wps):
        result = asyncio.run(diagnose_route(4))

    assert result["diagnosis"] == "ios", f"Очікувався 'ios', отримано '{result['diagnosis']}'"
    assert any("gap" in i.lower() for i in result["indicators"])


# ── N5: unknown — жодна умова не спрацювала ───────────────────────────────────

def test_unknown_diagnosis():
    """15 нормальних точок без підозрілих, без великих стрибків → unknown."""
    wps = _make_wps(15, gap_minutes=10.0)

    with patch("bot.services.diagnostics.get_route_waypoints", return_value=wps):
        result = asyncio.run(diagnose_route(5))

    assert result["diagnosis"] == "unknown"
    assert result["recommended_action"] is None
    assert any("не виявив" in i for i in result["indicators"])


# ── N6: порожній маршрут → unknown ───────────────────────────────────────────

def test_empty_waypoints():
    """0 точок — не крашається. 0 < 10 (IOS_MIN_WAYPOINTS) → ios."""
    with patch("bot.services.diagnostics.get_route_waypoints", return_value=[]):
        result = asyncio.run(diagnose_route(6))

    assert result["diagnosis"] == "ios"
    assert result["recommended_action"] == "odometer"


# ── N7: пріоритет РЕБ над iOS ────────────────────────────────────────────────

def test_reb_takes_priority_over_ios():
    """Якщо і РЕБ і iOS умови — перемагає РЕБ (пріоритет у діагностиці)."""
    # 3 точки (< 10 → iOS), але є підозрілих 2/3 = 67% (> 20% → РЕБ)
    wps = _make_wps(3, suspicious_count=2)

    with patch("bot.services.diagnostics.get_route_waypoints", return_value=wps):
        result = asyncio.run(diagnose_route(7))

    assert result["diagnosis"] == "reb", (
        f"РЕБ мав пріоритет, але отримано '{result['diagnosis']}'"
    )

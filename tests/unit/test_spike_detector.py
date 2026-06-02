"""
Тестує функцію is_spike() — виявлення GPS spike (правило 1.6).
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from datetime import datetime, timezone, timedelta
from bot.utils.geo import is_spike


# ── Геометрична перевірка (без timestamps — backward compatible) ───────────────

def test_spike_detected():
    """A→B великий стрибок (>20 km), B→C мінімальний → B є spike."""
    lat_a, lon_a = 50.45, 30.52
    lat_b, lon_b = 50.72, 30.52   # ~30 km на північ
    lat_c, lon_c = 50.73, 30.52   # ~1 km від B
    assert is_spike(lat_a, lon_a, lat_b, lon_b, lat_c, lon_c)


def test_normal_movement_not_spike():
    """Рівномірний рух по трасі — не spike."""
    lat_a, lon_a = 50.45, 30.52
    lat_b, lon_b = 50.60, 31.50
    lat_c, lon_c = 50.70, 32.30
    assert not is_spike(lat_a, lon_a, lat_b, lon_b, lat_c, lon_c)


def test_short_jump_not_spike():
    """Стрибок < 20 km — не spike навіть якщо B→C менше."""
    lat_a, lon_a = 50.45, 30.52
    lat_b, lon_b = 50.50, 30.60   # ~8 km від A
    lat_c, lon_c = 50.45, 30.53   # повернулась
    assert not is_spike(lat_a, lon_a, lat_b, lon_b, lat_c, lon_c)


# ── Перевірка швидкості (з timestamps) ───────────────────────────────────────

def _make_times(start_hour, start_min, end_hour, end_min):
    """Допоміжна: два datetime в один день."""
    base = datetime(2026, 6, 2, tzinfo=timezone.utc)
    t_a = base.replace(hour=start_hour, minute=start_min)
    t_b = base.replace(hour=end_hour, minute=end_min)
    return t_a, t_b


def test_spike_not_detected_normal_speed_with_timestamps():
    """100 км за 123 хв (49 км/год) — реальна поїздка, не spike.

    Кейс: ZAZA, 'швець'. Геометрично виглядало як spike (dist_bc < 0.3 * dist_ab),
    але водій реально там був — швидкість 49 км/год.
    """
    lat_a, lon_a = 50.39179, 30.35401   # Старт (Вишневе)
    lat_b, lon_b = 50.50396, 31.76741   # швець (~101 км haversine)
    lat_c, lon_c = 50.23916, 31.80025   # косогор (~29 км від швець)
    t_a, t_b = _make_times(7, 6, 9, 9)  # 123 хв → 49 км/год

    # Без timestamps — геометрично це spike
    assert is_spike(lat_a, lon_a, lat_b, lon_b, lat_c, lon_c)
    # З timestamps — швидкість 49 км/год ≤ 130 → не spike
    assert not is_spike(lat_a, lon_a, lat_b, lon_b, lat_c, lon_c, time_a=t_a, time_b=t_b)


def test_spike_detected_unrealistic_speed_with_timestamps():
    """100 км за 2 хв (3000 км/год) — GPS-артефакт → spike."""
    lat_a, lon_a = 50.45, 30.52
    lat_b, lon_b = 50.72, 31.52   # ~80 км
    lat_c, lon_c = 50.73, 31.53   # ~1.4 км від B
    t_a, t_b = _make_times(10, 0, 10, 2)  # 2 хв → ~2400 км/год

    assert is_spike(lat_a, lon_a, lat_b, lon_b, lat_c, lon_c, time_a=t_a, time_b=t_b)


def test_spike_boundary_speed_below_130():
    """120 км/год — нижче порогу → не spike."""
    # ~22 км за 11 хв ≈ 120 км/год < 130
    lat_a, lon_a = 50.45, 30.52
    lat_b, lon_b = 50.645, 30.52  # ~21.7 км від A
    lat_c, lon_c = 50.65, 30.52   # ~0.6 км від B (геометрично spike)
    t_a, t_b = _make_times(10, 0, 10, 11)  # 11 хв → ~118 км/год

    # Без timestamps — геометрично spike
    assert is_spike(lat_a, lon_a, lat_b, lon_b, lat_c, lon_c)
    # Зі timestamps ~118 км/год ≤ 130 → не spike
    assert not is_spike(lat_a, lon_a, lat_b, lon_b, lat_c, lon_c, time_a=t_a, time_b=t_b)


def test_spike_zero_time_falls_back_to_geometry():
    """time_a == time_b (0 секунд) — швидкість ∞ → fallback до геометрії → spike."""
    lat_a, lon_a = 50.45, 30.52
    lat_b, lon_b = 50.72, 30.52
    lat_c, lon_c = 50.73, 30.52
    t = datetime(2026, 6, 2, 10, 0, tzinfo=timezone.utc)

    assert is_spike(lat_a, lon_a, lat_b, lon_b, lat_c, lon_c, time_a=t, time_b=t)

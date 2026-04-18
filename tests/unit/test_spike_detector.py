"""
Тестує функцію is_spike() — виявлення GPS spike (правило 1.6).
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from bot.utils.geo import is_spike


def test_spike_detected():
    """A→B великий стрибок (>20 km), B→C мінімальний (C близько до B) → B є spike.

    GPS стрибнув до B (~30 km від A). Наступна точка C з'явилась майже на B (1 km).
    dist_bc < dist_ab * 0.3 → B помилкова точка, маркується підозрілою.
    """
    lat_a, lon_a = 50.45, 30.52   # A: Київ
    lat_b, lon_b = 50.72, 30.52   # B: ~30 km на північ (GPS стрибок)
    lat_c, lon_c = 50.73, 30.52   # C: ~1 km від B (dist_bc < 0.3 * dist_ab)
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

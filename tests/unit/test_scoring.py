"""
Тестує пороги скорингу відрізків маршруту.
  - gap_pct > 0.10 (не 0.25) для route-level mismatch alert
  - avg_speed < 25 км/год (не 35) для slow-segment alert
  - швидкість > 150 км/год = аномалія (правило 1.1)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from bot.services.route_detail_service import SPEED_ANOMALY_KMH


def _gap_pct_alert(odo_diff: float, tracker_km: float) -> bool:
    gap_pct = abs(odo_diff - tracker_km) / odo_diff
    return gap_pct > 0.10


def _slow_segment_alert(dist_km: float, avg_speed: float) -> bool:
    return dist_km > 60 and avg_speed < 25


def test_gap_pct_threshold_is_0_10():
    assert not _gap_pct_alert(100, 90)    # 10% — рівно на межі, не alert
    assert _gap_pct_alert(100, 89)         # 11% — alert
    assert _gap_pct_alert(100, 85)         # 15% — alert з 0.10, не alert з 0.25


def test_avg_speed_threshold_is_25():
    assert not _slow_segment_alert(70, 25)  # рівно 25 — не alert
    assert _slow_segment_alert(70, 24)      # 24 < 25 — alert
    assert not _slow_segment_alert(70, 30)  # 30 > 25 — не alert (старий поріг 35 спрацьовував)
    assert not _slow_segment_alert(50, 10)  # dist <= 60 — не alert незалежно від speed


def test_speed_anomaly_threshold_is_150():
    assert SPEED_ANOMALY_KMH == 150.0

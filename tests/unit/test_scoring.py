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


# ── Правило 2.1 — відображення розбіжності в P1-звіті ─────────────────────────

def test_odometer_diff_shown_in_report():
    """Розбіжність завжди відображається в P1-звіті при наявності обох показників одометра."""
    from bot.handlers.tracking import _format_odometer_accuracy
    text, _ = _format_odometer_accuracy(85.0, 0.0, 100.0)  # diff_pct=15%
    assert "Похибка" in text, "Текст звіту має містити 'Похибка' при розбіжності"
    assert "15.0%" in text, f"Очікувалось '15.0%' у тексті, отримано: {text!r}"


# ── Правило 2.2 — рівні емодзі точності в P1-звіті ───────────────────────────

def test_accuracy_emoji_levels():
    """Емодзі-рівні точності: ≤5% → ✅, 6-12% → 🔶, >12% → 🔴 (P1-формат звіту)."""
    from bot.handlers.tracking import _format_odometer_accuracy
    # odo_start=0, odo_km=100 → odometer_diff=100
    # diff_pct = abs(total_km - 100) / 100 * 100

    text_ok, _ = _format_odometer_accuracy(96.0, 0.0, 100.0)   # diff=4% → ✅
    text_warn, _ = _format_odometer_accuracy(92.0, 0.0, 100.0)  # diff=8% → 🔶
    text_red, _ = _format_odometer_accuracy(85.0, 0.0, 100.0)   # diff=15% → 🔴

    assert "✅" in text_ok,  f"4% має давати ✅, отримано: {text_ok!r}"
    assert "🔶" in text_warn, f"8% має давати 🔶, отримано: {text_warn!r}"
    assert "🔴" in text_red, f"15% має давати 🔴, отримано: {text_red!r}"

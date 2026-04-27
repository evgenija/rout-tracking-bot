"""
Тести для ping-флоу правил 1.2 і 1.3 (bot/services/ping_service.py).
Правило 1.2: відстань > 130 км → ping водію (не is_suspicious одразу).
Правило 1.3: розрив > 60 хв → ping водію (не is_suspicious одразу).
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from datetime import datetime, timezone, timedelta
from bot.services.ping_service import should_ping, PING_TIMEOUT_MINUTES


def _wp(lat, lon, offset_min=0):
    base = datetime(2026, 4, 25, 8, 0, tzinfo=timezone.utc)
    ts = (base + timedelta(minutes=offset_min)).isoformat()
    return {"lat": lat, "lon": lon, "timestamp": ts}


# ── Правило 1.2: відстань ─────────────────────────────────────────────────────

def test_distance_over_130_triggers_ping():
    """Відстань > 130 км між точками → should_ping = True (правило 1.2)."""
    prev = _wp(50.4501, 30.5234, offset_min=0)    # Київ
    curr = _wp(49.9935, 36.2304, offset_min=5)    # Харків (~410 км), малий gap
    assert should_ping(prev, curr, max_distance_km=130), \
        "Відстань ~410 км має тригерити ping (>130 км)"


def test_distance_under_130_no_ping():
    """Відстань ≤ 130 км і gap ≤ 60 хв → should_ping = False."""
    prev = _wp(50.4501, 30.5234, offset_min=0)    # Київ
    curr = _wp(50.4601, 30.5334, offset_min=10)   # ~1 км від Києва, 10 хв gap
    assert not should_ping(prev, curr, max_distance_km=130), \
        "Близькі точки з малим gap не мають тригерити ping"


# ── Правило 1.3: часовий розрив ───────────────────────────────────────────────

def test_gap_over_60min_triggers_ping():
    """Gap > 60 хв між точками → should_ping = True (правило 1.3)."""
    prev = _wp(50.4501, 30.5234, offset_min=0)
    curr = _wp(50.4601, 30.5334, offset_min=90)   # 90 хв gap, близькі точки
    assert should_ping(prev, curr, max_distance_km=130), \
        "Gap 90 хв має тригерити ping (>60 хв)"


def test_gap_under_60min_no_ping():
    """Gap ≤ 60 хв і відстань ≤ 130 км → should_ping = False."""
    prev = _wp(50.4501, 30.5234, offset_min=0)
    curr = _wp(50.4601, 30.5334, offset_min=59)   # 59 хв, близькі точки
    assert not should_ping(prev, curr, max_distance_km=130), \
        "Gap 59 хв + близькі точки не мають тригерити ping"


# ── Константи і регресії ──────────────────────────────────────────────────────

def test_ping_timeout_constant_is_30():
    """PING_TIMEOUT_MINUTES == 30 (без відповіді 30 хв → is_suspicious=1)."""
    assert PING_TIMEOUT_MINUTES == 30, \
        f"PING_TIMEOUT_MINUTES має бути 30, отримано {PING_TIMEOUT_MINUTES}"


def test_speed_over_150_marks_suspicious_not_ping():
    """Regression: tracking.py перевіряє швидкість > 150 → is_suspicious (не ping)."""
    path = os.path.join(os.path.dirname(__file__), "..", "..", "bot", "handlers", "tracking.py")
    source = open(path, encoding="utf-8").read()
    assert "150" in source and "is_suspicious" in source, \
        "tracking.py має обробляти швидкість >150 через is_suspicious"
    assert "SPEED_ANOMALY_KMH" in source or "150" in source


def test_check_active_route_gaps_uses_is_active():
    """Regression b4ef9f5: scheduler uses 'is_active = 1', not 'status = active'."""
    path = os.path.join(os.path.dirname(__file__), "..", "..", "bot", "utils", "scheduler.py")
    source = open(path, encoding="utf-8").read()
    assert "is_active = 1" in source, \
        "scheduler.py має використовувати is_active=1 (не status)"
    assert "status = 'active'" not in source and "status='active'" not in source, \
        "Знайдено старий баг: status='active' в scheduler.py (commit b4ef9f5)"

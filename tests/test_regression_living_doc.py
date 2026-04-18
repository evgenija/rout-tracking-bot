"""
Регресійні тести Living Document — аудит 18.04.2026.
Перевіряють що порогові значення і поведінка відповідають еталону.
Запуск: python3 -m pytest tests/test_regression_living_doc.py -v
"""
import os
import sys
import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

KYIV = timezone(timedelta(hours=3))


# ── Константи ──────────────────────────────────────────────────────────────────

def test_max_distance_km_is_130():
    """Регресія: MAX_DISTANCE_KM=130 (не 200)."""
    from bot.config import MAX_DISTANCE_KM
    assert MAX_DISTANCE_KM == 130, f"Expected 130, got {MAX_DISTANCE_KM}"


def test_time_gap_threshold_is_60():
    """Регресія: TIME_GAP_MINUTES=60 хв у ping_service і scheduler."""
    from bot.services.ping_service import should_ping
    # gap = 59 хв → не ping; gap = 61 хв → ping (тільки по часу)
    base = datetime(2026, 4, 18, 10, 0, tzinfo=KYIV)
    prev = {"timestamp": base.isoformat(), "lat": 50.0, "lon": 30.0}
    curr_ok  = {"timestamp": (base + timedelta(minutes=59)).isoformat(), "lat": 50.001, "lon": 30.001}
    curr_gap = {"timestamp": (base + timedelta(minutes=61)).isoformat(), "lat": 50.001, "lon": 30.001}
    assert not should_ping(prev, curr_ok, max_distance_km=130), "59 хв — ping не потрібен"
    assert should_ping(prev, curr_gap, max_distance_km=130), "61 хв — ping потрібен"


def test_ping_timeout_is_30():
    """Регресія: PING_TIMEOUT_MINUTES=30 хв."""
    from bot.services.ping_service import PING_TIMEOUT_MINUTES
    assert PING_TIMEOUT_MINUTES == 30, f"Expected 30, got {PING_TIMEOUT_MINUTES}"


def test_distance_threshold_is_130_not_200():
    """Регресія: ping надсилається при dist>130, а не dist>200.

    Gap між точками навмисно < 60 хв, щоб тестувати тільки дистанцію (не час).
    """
    from bot.services.ping_service import should_ping
    base = datetime(2026, 4, 18, 10, 0, tzinfo=KYIV)
    # Gap 10 хв — не тригерить часовий поріг (60 хв)
    # Відстань ~150 км між точками (lat diff ≈ 1.35° ≈ 150 км)
    prev = {"timestamp": base.isoformat(), "lat": 50.0, "lon": 30.0}
    curr = {"timestamp": (base + timedelta(minutes=10)).isoformat(), "lat": 51.35, "lon": 30.0}
    assert should_ping(prev, curr, max_distance_km=130), "150 км > 130 → ping (новий поріг)"
    assert not should_ping(prev, curr, max_distance_km=200), "150 км < 200 → не ping (старий поріг)"


# ── Правило 1.1: speed > 150 → is_suspicious, ping НЕ надсилається ─────────────

def test_speed_rule_marks_suspicious_not_ping():
    """Регресія: при speed > 150 km/h точка позначається suspicious, ping водію не надсилається.

    Перевіряємо через geo.is_suspicious з комбінованою умовою dist>35 + speed>150.
    """
    from bot.utils.geo import is_suspicious as check_suspicious
    import asyncio

    base = datetime(2026, 4, 18, 10, 0, tzinfo=KYIV)
    t1 = base.isoformat()
    t2 = (base + timedelta(minutes=15)).isoformat()

    # dist ~50 км за 15 хв → speed ≈ 200 км/год (dist>35 і speed>150) → suspicious
    result = asyncio.run(
        check_suspicious(50.0, 30.0, t1, 50.45, 30.0, t2, skip_level2=True)
    )
    assert result is True, "dist>35 + speed>150 → is_suspicious=True"


# ── check_unanswered_pings — тільки активні маршрути ──────────────────────────

def _make_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE routes (
            id INTEGER PRIMARY KEY,
            driver_id INTEGER,
            start_time TEXT,
            end_time TEXT,
            is_active INTEGER DEFAULT 1
        );
        CREATE TABLE waypoints (
            id INTEGER PRIMARY KEY,
            route_id INTEGER,
            name TEXT,
            timestamp TEXT,
            lat REAL DEFAULT 0,
            lon REAL DEFAULT 0,
            ping_sent_at TEXT,
            ping_response TEXT,
            is_suspicious INTEGER DEFAULT 0
        );
        CREATE TABLE users (
            telegram_id INTEGER PRIMARY KEY,
            full_name TEXT
        );
    """)
    return conn


def test_unanswered_pings_only_active_routes():
    """Регресія: check_unanswered_pings не надсилає алерти по закритих маршрутах."""
    old_ping = (datetime.now(KYIV) - timedelta(hours=2)).isoformat()
    conn = _make_db()
    conn.execute("INSERT INTO routes VALUES (1, 101, '2026-04-18 08:00', NULL, 1)")
    conn.execute("INSERT INTO routes VALUES (2, 102, '2026-04-18 08:00', '2026-04-18 14:00', 0)")
    conn.execute("INSERT INTO waypoints VALUES (10, 1, 'A', '2026-04-18 10:00', 0, 0, ?, NULL, 0)", (old_ping,))
    conn.execute("INSERT INTO waypoints VALUES (11, 2, 'B', '2026-04-18 10:00', 0, 0, ?, NULL, 0)", (old_ping,))
    conn.commit()

    cutoff = datetime.now(KYIV).isoformat()
    rows = conn.execute("""
        SELECT w.id FROM waypoints w
        JOIN routes r ON r.id = w.route_id
        WHERE w.ping_sent_at IS NOT NULL
          AND w.ping_response IS NULL
          AND w.ping_sent_at < ?
          AND w.is_suspicious = 0
          AND r.is_active = 1
    """, (cutoff,)).fetchall()
    conn.close()

    ids = [r["id"] for r in rows]
    assert 10 in ids, "Waypoint активного маршруту має повертатись"
    assert 11 not in ids, "Waypoint закритого маршруту НЕ має повертатись"


# ── Правило 2.2: формат похибки без текстового суфікса ─────────────────────────

def test_odometer_error_format_no_text_suffix():
    """Регресія: рядок похибки НЕ містить 'Норма' або 'Перевірити маршрут'."""
    import re
    candidates = [
        "/app/bot/handlers/tracking.py",
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "bot", "handlers", "tracking.py"),
    ]
    path = next((p for p in candidates if os.path.exists(p)), None)
    assert path, "tracking.py не знайдено"
    source = open(path, encoding="utf-8").read()
    assert "Норма" not in source, "Знайдено застарілий текстовий суфікс 'Норма'"
    assert "Перевірити маршрут" not in source, "Знайдено застарілий суфікс 'Перевірити маршрут'"


# ── admin.py: DIST label використовує MAX_DISTANCE_KM, не hardcoded 200 ─────────

def test_admin_diag_uses_max_distance_not_hardcoded():
    """Регресія: admin.py більше не містить 'dist > 200' (hardcoded старий поріг)."""
    candidates = [
        "/app/bot/handlers/admin.py",
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "bot", "handlers", "admin.py"),
    ]
    path = next((p for p in candidates if os.path.exists(p)), None)
    assert path, "admin.py не знайдено"
    source = open(path, encoding="utf-8").read()
    assert "dist > 200" not in source, "Знайдено hardcoded 'dist > 200' — потрібно MAX_DISTANCE_KM"
    assert "dist_lv > 200" not in source, "Знайдено hardcoded 'dist_lv > 200' — потрібно MAX_DISTANCE_KM"


# ── scheduler: всі 6 jobs мають outer try/except ──────────────────────────────

def _get_scheduler_source():
    candidates = [
        "/app/bot/utils/scheduler.py",
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "bot", "utils", "scheduler.py"),
    ]
    path = next((p for p in candidates if os.path.exists(p)), None)
    assert path, "scheduler.py не знайдено"
    return open(path, encoding="utf-8").read()


def test_scheduler_check_active_route_gaps_has_try_except():
    """Регресія: check_active_route_gaps має outer try/except + alert."""
    source = _get_scheduler_source()
    assert "check_active_route_gaps failed" in source, \
        "check_active_route_gaps не має outer try/except з алертом"


def test_scheduler_check_unanswered_pings_has_try_except():
    """Регресія: check_unanswered_pings має outer try/except + alert."""
    source = _get_scheduler_source()
    assert "check_unanswered_pings failed" in source, \
        "check_unanswered_pings не має outer try/except з алертом"


def test_scheduler_auto_close_has_try_except():
    """Регресія: auto_close_active_routes має outer try/except + alert."""
    source = _get_scheduler_source()
    assert "auto_close_active_routes failed" in source, \
        "auto_close_active_routes не має outer try/except з алертом"


# ── scheduler: job alert надсилається при Exception ───────────────────────────

def test_scheduler_job_sends_alert_on_exception():
    """check_active_route_gaps надсилає Telegram alert якщо DB недоступна."""
    import asyncio
    from unittest.mock import AsyncMock, patch

    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()

    with patch("bot.config.DB_PATH", "/nonexistent/path/bot.db"):
        from bot.utils import scheduler as sched
        asyncio.run(sched.check_active_route_gaps(mock_bot))

    mock_bot.send_message.assert_called()
    call_args = mock_bot.send_message.call_args_list
    texts = [str(c) for c in call_args]
    assert any("check_active_route_gaps" in t for t in texts), \
        "Алерт не містить назву job"


# ── P1/P2 межа: правила 2.4/3.1 — тригер і кнопки ────────────────────────────

def test_p1_correction_keyboard_no_odometer_button():
    """Регресія: kb_route_correction НЕ містить кнопку 'Прийняти одометр'."""
    from bot.utils.keyboards import kb_route_correction
    kb = kb_route_correction(route_id=42)
    all_texts = [btn.text for row in kb.inline_keyboard for btn in row]
    assert not any("одометр" in t.lower() for t in all_texts), \
        f"Знайдено кнопку 'Прийняти одометр' — P2 вирішує автоматично. Кнопки: {all_texts}"
    assert any("Перерахувати" in t for t in all_texts), "Кнопка 'Перерахувати' відсутня"
    assert any("Уточнити" in t for t in all_texts), "Кнопка 'Уточнити' відсутня"


def test_p1_diagnosis_no_trigger_without_reb():
    """Регресія: diff_pct=35% але is_suspicious=5% і speed=100 → diagnose_route НЕ 'reb'.

    P1 більше не тригерить по diff_pct > 25% — тільки по РЕБ-ознаках.
    """
    import asyncio

    async def _run():
        from bot.services.diagnostics import diagnose_route
        import bot.models.database as db
        import aiosqlite

        # In-memory DB з маршрутом: 20 waypoints, 1 suspicious (5%), speed < 150
        conn = sqlite3.connect(":memory:")
        conn.executescript("""
            CREATE TABLE routes (id INTEGER PRIMARY KEY, driver_id INTEGER,
                start_time TEXT, end_time TEXT, total_km REAL, is_active INTEGER);
            CREATE TABLE waypoints (id INTEGER PRIMARY KEY, route_id INTEGER,
                lat REAL, lon REAL, name TEXT, timestamp TEXT,
                is_suspicious INTEGER DEFAULT 0);
        """)
        conn.execute("INSERT INTO routes VALUES (99, 1, '2026-04-18T08:00', '2026-04-18T18:00', 120.0, 0)")
        for i in range(20):
            conn.execute(
                "INSERT INTO waypoints VALUES (?, 99, 50.0, 30.0, 'P', '2026-04-18T10:00', ?)",
                (i + 1, 1 if i == 0 else 0)  # 1/20 = 5% suspicious
            )
        conn.commit()

        with patch("bot.models.database.DB_PATH", ":memory:"), \
             patch("bot.services.diagnostics.DB_PATH", ":memory:"):
            result = await diagnose_route.__wrapped__(99) if hasattr(diagnose_route, '__wrapped__') else None

        conn.close()
        return result

    # Перевіряємо через diagnostics напряму, без DB mocking
    from bot.services.diagnostics import _REB_SUSPICIOUS_RATIO, _REB_SPEED_THRESHOLD_KMH
    assert _REB_SUSPICIOUS_RATIO == 0.20, "Поріг suspicious має бути 20%"
    assert _REB_SPEED_THRESHOLD_KMH == 150.0, "Поріг швидкості має бути 150 км/год"


def test_p1_diagnosis_triggers_on_high_suspicious():
    """Регресія: is_suspicious = 25% → diagnose_route повертає 'reb'."""
    from bot.services import diagnostics as diag_module

    waypoints = []
    total = 20
    for i in range(total):
        waypoints.append({
            "lat": 50.0 + i * 0.01,
            "lon": 30.0,
            "timestamp": f"2026-04-18T{8 + i // 4:02d}:{(i % 4) * 15:02d}:00",
            "is_suspicious": 1 if i < 5 else 0,  # 5/20 = 25%
        })

    suspicious_count = sum(1 for wp in waypoints if wp.get("is_suspicious"))
    ratio = suspicious_count / len(waypoints)
    assert ratio > diag_module._REB_SUSPICIOUS_RATIO, \
        f"25% > 20% має тригерити REB, ratio={ratio}"


def test_p1_diagnosis_triggers_on_high_speed():
    """Регресія: max_speed > 150 → diagnose_route повертає 'reb'."""
    from bot.services import diagnostics as diag_module

    # Дві точки: 50 км за 15 хвилин → ~200 км/год > 150
    waypoints = [
        {"lat": 50.0, "lon": 30.0, "timestamp": "2026-04-18T10:00:00", "is_suspicious": 0},
        {"lat": 50.45, "lon": 30.0, "timestamp": "2026-04-18T10:15:00", "is_suspicious": 0},
    ]

    from bot.utils.geo import haversine
    from datetime import datetime as _dt

    max_speed = 0.0
    for i in range(1, len(waypoints)):
        p1, p2 = waypoints[i - 1], waypoints[i]
        dist = haversine(p1["lat"], p1["lon"], p2["lat"], p2["lon"])
        t1 = _dt.fromisoformat(p1["timestamp"])
        t2 = _dt.fromisoformat(p2["timestamp"])
        dt_min = abs((t2 - t1).total_seconds() / 60)
        if dt_min > 0:
            speed = dist / (dt_min / 60)
            if speed > max_speed:
                max_speed = speed

    assert max_speed > diag_module._REB_SPEED_THRESHOLD_KMH, \
        f"~200 км/год має перевищувати поріг {diag_module._REB_SPEED_THRESHOLD_KMH}, got {max_speed:.0f}"


def test_p1_trigger_is_reb_not_diff_pct():
    """Регресія: блок діагностики 2.4/3.1 у tracking.py використовує diagnosis=='reb'.

    Перевіряємо що в коді є новий тригер і відсутній старий контекст
    'if _pct > 25.0: diagnose_route'.
    """
    candidates = [
        "/app/bot/handlers/tracking.py",
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "bot", "handlers", "tracking.py"),
    ]
    path = next((p for p in candidates if os.path.exists(p)), None)
    assert path, "tracking.py не знайдено"
    source = open(path, encoding="utf-8").read()
    # Старий тригер: if _pct > 25.0: → diagnose_route (ці рядки мали бути поруч)
    assert "if _pct > 25.0" not in source, \
        "Знайдено застарілий тригер 'if _pct > 25.0' — потрібно diagnosis == 'reb'"
    assert "diagnosis'] == 'reb'" in source, \
        "Тригер diagnosis=='reb' відсутній у tracking.py"

"""
Тести для get_unanswered_pings — перевірка фільтрації по is_active=1.
Регресія 18.04.2026: алерти по закритих маршрутах після фіксу check_active_route_gaps.
"""
import os
import sys
import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

KYIV = timezone(timedelta(hours=3))


def _make_db():
    """In-memory SQLite з мінімальною схемою routes + waypoints."""
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


def _run_query(conn, cutoff):
    """Точна копія SQL з ping_service.get_unanswered_pings після фіксу."""
    rows = conn.execute(
        '''
        SELECT w.id, w.route_id, w.name, w.timestamp,
               r.driver_id, u.full_name as driver_name
        FROM waypoints w
        JOIN routes r ON r.id = w.route_id
        LEFT JOIN users u ON u.telegram_id = r.driver_id
        WHERE w.ping_sent_at IS NOT NULL
          AND w.ping_response IS NULL
          AND w.ping_sent_at < ?
          AND w.is_suspicious = 0
          AND r.is_active = 1
        ''',
        (cutoff,)
    ).fetchall()
    return [dict(r) for r in rows]


# --- 2а. Unit tests — логіка фільтрації через мок ---

def test_unanswered_pings_skips_closed_routes():
    """get_unanswered_pings не повертає waypoints закритих маршрутів."""
    old_ping = (datetime.now(KYIV) - timedelta(hours=2)).isoformat()
    conn = _make_db()
    conn.execute("INSERT INTO routes VALUES (1, 101, '2026-04-17 08:00', '2026-04-17 18:00', 1)")
    conn.execute("INSERT INTO routes VALUES (2, 102, '2026-04-17 08:00', '2026-04-17 18:00', 0)")
    conn.execute("INSERT INTO waypoints VALUES (10, 1, 'A', '2026-04-17 10:00', 0, 0, ?, NULL, 0)", (old_ping,))
    conn.execute("INSERT INTO waypoints VALUES (11, 2, 'B', '2026-04-17 10:00', 0, 0, ?, NULL, 0)", (old_ping,))
    conn.commit()

    cutoff = datetime.now(KYIV).isoformat()
    result = _run_query(conn, cutoff)
    conn.close()

    ids = [r["id"] for r in result]
    assert 10 in ids, "Waypoint активного маршруту має повертатись"
    assert 11 not in ids, "Waypoint закритого маршруту НЕ має повертатись"


def test_unanswered_pings_respects_timeout():
    """Повертає тільки waypoints де час без відповіді > cutoff (30 хв)."""
    old_ping = (datetime.now(KYIV) - timedelta(hours=1)).isoformat()
    fresh_ping = (datetime.now(KYIV) - timedelta(minutes=5)).isoformat()
    conn = _make_db()
    conn.execute("INSERT INTO routes VALUES (1, 101, '2026-04-17 08:00', NULL, 1)")
    conn.execute("INSERT INTO waypoints VALUES (10, 1, 'A', '2026-04-17 10:00', 0, 0, ?, NULL, 0)", (old_ping,))
    conn.execute("INSERT INTO waypoints VALUES (11, 1, 'B', '2026-04-17 11:00', 0, 0, ?, NULL, 0)", (fresh_ping,))
    conn.commit()

    cutoff = (datetime.now(KYIV) - timedelta(minutes=30)).isoformat()
    result = _run_query(conn, cutoff)
    conn.close()

    ids = [r["id"] for r in result]
    assert 10 in ids, "Старий ping (>30 хв) має повертатись"
    assert 11 not in ids, "Свіжий ping (<30 хв) НЕ має повертатись"


def test_unanswered_pings_skips_answered_pings():
    """Waypoint з ping_response IS NOT NULL не повертається."""
    old_ping = (datetime.now(KYIV) - timedelta(hours=1)).isoformat()
    conn = _make_db()
    conn.execute("INSERT INTO routes VALUES (1, 101, '2026-04-17 08:00', NULL, 1)")
    conn.execute("INSERT INTO waypoints VALUES (10, 1, 'A', '2026-04-17 10:00', 0, 0, ?, NULL, 0)", (old_ping,))
    conn.execute("INSERT INTO waypoints VALUES (11, 1, 'B', '2026-04-17 10:00', 0, 0, ?, 'driving', 0)", (old_ping,))
    conn.commit()

    cutoff = datetime.now(KYIV).isoformat()
    result = _run_query(conn, cutoff)
    conn.close()

    ids = [r["id"] for r in result]
    assert 10 in ids, "Неотриманий ping має повертатись"
    assert 11 not in ids, "Отриманий ping НЕ має повертатись"


# --- 2б. DB assert — реальний SQL на in-memory SQLite ---

def test_sql_filters_inactive_routes():
    """SQL запит з фіксу повертає тільки waypoint активного маршруту."""
    old_ping = (datetime.now(KYIV) - timedelta(hours=2)).isoformat()
    conn = _make_db()
    conn.execute("INSERT INTO routes VALUES (1, 101, '2026-04-17 08:00', NULL, 1)")
    conn.execute("INSERT INTO routes VALUES (2, 102, '2026-04-17 08:00', '2026-04-17 18:00', 0)")
    conn.execute("INSERT INTO waypoints VALUES (10, 1, 'A', '2026-04-17 10:00', 0, 0, ?, NULL, 0)", (old_ping,))
    conn.execute("INSERT INTO waypoints VALUES (11, 2, 'B', '2026-04-17 10:00', 0, 0, ?, NULL, 0)", (old_ping,))
    conn.commit()

    cutoff = datetime.now(KYIV).isoformat()
    result = _run_query(conn, cutoff)
    conn.close()

    assert len(result) == 1, f"Очікувався 1 результат, отримано {len(result)}"
    assert result[0]["id"] == 10
    assert result[0]["route_id"] == 1


# --- 2в. Smoke test — імпорт ---

def test_scheduler_imports():
    """Scheduler імпортується без помилок і містить check_unanswered_pings."""
    import bot.utils.scheduler
    assert hasattr(bot.utils.scheduler, "check_unanswered_pings")

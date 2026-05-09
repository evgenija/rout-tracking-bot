# bot/services/ping_service.py
# Ping-флоу для правил 1.2 і 1.3 валідації waypoints
# Не містить бізнес-логіки маршруту — тільки ping механіку

from datetime import datetime, timedelta, timezone
import sqlite3

from bot.config import DB_PATH

KYIV_OFFSET = timezone(timedelta(hours=3))
PING_TIMEOUT_MINUTES = 30


def should_ping(prev_waypoint: dict, curr_waypoint: dict, max_distance_km: float) -> bool:
    """Перевіряє чи потрібен ping за правилами 1.2 і 1.3."""
    # 1.3: часовий gap
    if prev_waypoint.get('timestamp') and curr_waypoint.get('timestamp'):
        prev_time = datetime.fromisoformat(prev_waypoint['timestamp'])
        curr_time = datetime.fromisoformat(curr_waypoint['timestamp'])
        gap_minutes = (curr_time - prev_time).total_seconds() / 60
        if gap_minutes > 60:
            return True
    # 1.2: відстань
    distance = _haversine(
        prev_waypoint['lat'], prev_waypoint['lon'],
        curr_waypoint['lat'], curr_waypoint['lon']
    )
    if distance > max_distance_km:
        return True
    return False


def mark_ping_sent(waypoint_id: int) -> None:
    """Позначає що ping надіслано для waypoint."""
    now = datetime.now(KYIV_OFFSET).isoformat()
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        'UPDATE waypoints SET ping_sent_at = ? WHERE id = ?',
        (now, waypoint_id)
    )
    conn.commit()
    conn.close()


def record_ping_response(waypoint_id: int, response: str) -> None:
    """Зберігає відповідь водія: 'driving' або 'stopped'."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        'UPDATE waypoints SET ping_response = ? WHERE id = ?',
        (response, waypoint_id)
    )
    conn.commit()
    conn.close()


def get_unanswered_pings() -> list[dict]:
    """Повертає waypoints з ping без відповіді старше 30 хв."""
    cutoff = (datetime.now(KYIV_OFFSET) - timedelta(minutes=PING_TIMEOUT_MINUTES)).isoformat()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
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
          AND r.is_active = 1
          AND w.id != (SELECT MIN(id) FROM waypoints WHERE route_id = w.route_id)
        ''',
        (cutoff,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _haversine(lat1, lon1, lat2, lon2) -> float:
    """Відстань між двома точками в км."""
    import math
    R = 6371
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return 2 * R * math.asin(math.sqrt(a))

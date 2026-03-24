import aiosqlite
from datetime import datetime
from typing import Optional, List, Dict
from bot.config import DB_PATH


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                username    TEXT,
                full_name   TEXT,
                role        TEXT    DEFAULT 'driver',
                is_approved INTEGER DEFAULT 0,
                created_at  TEXT    DEFAULT (datetime('now'))
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS routes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                driver_id   INTEGER,
                start_time  TEXT,
                end_time    TEXT,
                total_km    REAL    DEFAULT 0,
                is_active   INTEGER DEFAULT 1,
                FOREIGN KEY (driver_id) REFERENCES users(telegram_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS waypoints (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                route_id     INTEGER,
                lat          REAL,
                lon          REAL,
                name         TEXT,
                timestamp    TEXT,
                is_suspicious INTEGER DEFAULT 0,
                FOREIGN KEY (route_id) REFERENCES routes(id)
            )
        """)
        await db.commit()


# ── Users ─────────────────────────────────────────────────────────────────────

async def get_user(telegram_id: int) -> Optional[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def create_user(telegram_id: int, username: str, full_name: str, role: str = "driver"):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (telegram_id, username, full_name, role) VALUES (?, ?, ?, ?)",
            (telegram_id, username, full_name, role),
        )
        await db.commit()


async def approve_user(telegram_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET is_approved = 1 WHERE telegram_id = ?", (telegram_id,)
        )
        await db.commit()


async def delete_user(telegram_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM users WHERE telegram_id = ?", (telegram_id,))
        await db.commit()


async def get_all_users() -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users ORDER BY is_approved DESC, created_at ASC"
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def search_drivers_by_query(query: str) -> List[Dict]:
    """Пошук авторизованих водіїв за точним ID або частиною імені."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        # Спробувати як числовий ID
        try:
            user_id = int(query)
            async with db.execute(
                "SELECT * FROM users WHERE telegram_id = ? AND is_approved = 1", (user_id,)
            ) as cur:
                rows = await cur.fetchall()
                if rows:
                    return [dict(r) for r in rows]
        except ValueError:
            pass
        # Пошук за частиною імені (без урахування регістру)
        async with db.execute(
            "SELECT * FROM users WHERE is_approved = 1 AND LOWER(full_name) LIKE LOWER(?)",
            (f"%{query}%",),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def get_all_approved_drivers() -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users WHERE is_approved = 1"
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


# ── Routes ────────────────────────────────────────────────────────────────────

async def start_route(driver_id: int, start_time: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO routes (driver_id, start_time) VALUES (?, ?)",
            (driver_id, start_time),
        )
        await db.commit()
        return cur.lastrowid


async def get_active_route(driver_id: int) -> Optional[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM routes WHERE driver_id = ? AND is_active = 1 ORDER BY id DESC LIMIT 1",
            (driver_id,),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def end_route(route_id: int, end_time: str, total_km: float):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE routes SET end_time = ?, total_km = ?, is_active = 0 WHERE id = ?",
            (end_time, total_km, route_id),
        )
        await db.commit()


# ── Waypoints ─────────────────────────────────────────────────────────────────

async def add_waypoint(
    route_id: int, lat: float, lon: float, name: str,
    timestamp: str, is_suspicious: bool = False,
):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO waypoints (route_id, lat, lon, name, timestamp, is_suspicious) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (route_id, lat, lon, name, timestamp, int(is_suspicious)),
        )
        await db.commit()


async def get_route_waypoints(route_id: int) -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM waypoints WHERE route_id = ? ORDER BY timestamp", (route_id,)
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def get_last_waypoint(route_id: int) -> Optional[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM waypoints WHERE route_id = ? ORDER BY timestamp DESC LIMIT 1",
            (route_id,),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


# ── Reports ───────────────────────────────────────────────────────────────────

async def get_daily_stats(date_str: str) -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT u.full_name,
                   u.telegram_id,
                   COALESCE(SUM(r.total_km), 0)                          AS total_km,
                   MIN(r.start_time)                                      AS first_start,
                   MAX(COALESCE(r.end_time, datetime('now')))             AS last_end
            FROM routes r
            JOIN users u ON r.driver_id = u.telegram_id
            WHERE DATE(r.start_time) = ?
            GROUP BY r.driver_id
            """,
            (date_str,),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def flag_suspicious_waypoints_retroactive(
    max_distance_km: float = 100.0,
    max_speed_kmh: float = 200.0,
) -> Dict:
    """Ретроактивно помічає аномальні геомітки в існуючих маршрутах.

    Перевіряє кожну пару сусідніх геоміток:
    - відстань > max_distance_km → телепортація
    - швидкість > max_speed_kmh → фізично неможливо

    Повертає словник зі статистикою: {flagged: N, routes_affected: N}.
    """
    from bot.utils.geo import haversine
    from datetime import datetime as _dt

    flagged = 0
    routes_affected = set()

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT id FROM routes") as cur:
            route_ids = [r["id"] for r in await cur.fetchall()]

        for route_id in route_ids:
            async with db.execute(
                "SELECT * FROM waypoints WHERE route_id = ? ORDER BY timestamp",
                (route_id,),
            ) as cur:
                wps = [dict(r) for r in await cur.fetchall()]

            for i in range(1, len(wps)):
                prev, curr = wps[i - 1], wps[i]
                if curr["is_suspicious"]:
                    continue  # вже помічено

                distance = haversine(prev["lat"], prev["lon"], curr["lat"], curr["lon"])
                suspicious = False

                if distance > max_distance_km:
                    suspicious = True
                else:
                    try:
                        t1 = _dt.fromisoformat(prev["timestamp"])
                        t2 = _dt.fromisoformat(curr["timestamp"])
                        elapsed_min = abs((t2 - t1).total_seconds() / 60)
                        if elapsed_min >= 2.0:
                            speed = distance / (elapsed_min / 60)
                            if speed > max_speed_kmh:
                                suspicious = True
                    except Exception:
                        pass

                if suspicious:
                    await db.execute(
                        "UPDATE waypoints SET is_suspicious = 1 WHERE id = ?",
                        (curr["id"],),
                    )
                    flagged += 1
                    routes_affected.add(route_id)

        await db.commit()

    return {"flagged": flagged, "routes_affected": len(routes_affected)}


async def recalculate_all_route_distances() -> Dict:
    """Перераховує total_km для всіх завершених маршрутів без підозрілих точок.

    Повертає словник: {recalculated: N, anomalies_fixed: N}.
    """
    from bot.utils.geo import calculate_route_distance

    recalculated = 0
    anomalies_fixed = 0

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id, total_km FROM routes WHERE is_active = 0"
        ) as cur:
            routes = [dict(r) for r in await cur.fetchall()]

        for route in routes:
            waypoints = await get_route_waypoints(route["id"])
            new_km = calculate_route_distance(waypoints)
            old_km = route["total_km"] or 0.0

            if abs(new_km - old_km) > 0.01:
                await db.execute(
                    "UPDATE routes SET total_km = ? WHERE id = ?",
                    (new_km, route["id"]),
                )
                if old_km > 500:
                    anomalies_fixed += 1
                recalculated += 1

        await db.commit()

    return {"recalculated": recalculated, "anomalies_fixed": anomalies_fixed}


async def get_all_routes_with_stats() -> List[Dict]:
    """Повертає всі маршрути з кількістю геоміток для діагностики."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT r.id, r.driver_id, u.full_name,
                   r.total_km, r.is_active, r.start_time,
                   COUNT(w.id) AS waypoint_count,
                   SUM(w.is_suspicious) AS suspicious_count
            FROM routes r
            LEFT JOIN users u ON r.driver_id = u.telegram_id
            LEFT JOIN waypoints w ON w.route_id = r.id
            GROUP BY r.id
            ORDER BY r.start_time DESC
            """
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def get_weekly_stats(start_date: str, end_date: str) -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT u.full_name,
                   u.telegram_id,
                   COALESCE(SUM(r.total_km), 0) AS total_km,
                   COUNT(r.id)                  AS route_count
            FROM routes r
            JOIN users u ON r.driver_id = u.telegram_id
            WHERE DATE(r.start_time) BETWEEN ? AND ?
            GROUP BY r.driver_id
            ORDER BY total_km DESC
            """,
            (start_date, end_date),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

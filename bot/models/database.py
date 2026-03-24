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

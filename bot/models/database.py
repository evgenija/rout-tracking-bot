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
        # Міграція: is_manual може не існувати в старих БД
        try:
            await db.execute(
                "ALTER TABLE routes ADD COLUMN is_manual INTEGER DEFAULT 0"
            )
        except Exception:
            pass  # колонка вже існує
        # Міграція: odometer_km — показник одометра водія при завершенні маршруту
        try:
            await db.execute(
                "ALTER TABLE routes ADD COLUMN odometer_km REAL DEFAULT NULL"
            )
        except Exception:
            pass  # колонка вже існує
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


async def save_odometer(route_id: int, odometer_km: float):
    """Зберігає показник одометра для завершеного маршруту."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE routes SET odometer_km = ? WHERE id = ?",
            (odometer_km, route_id),
        )
        await db.commit()


async def get_todays_route(driver_id: int) -> Optional[Dict]:
    """Повертає активний маршрут або останній завершений за сьогодні.

    Використовується для збереження waypoints незалежно від того,
    чи водій вже натиснув Фініш і ще не натиснув новий Старт.
    Активний маршрут (is_active=1) має пріоритет над завершеним.
    """
    today = datetime.now().date().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT * FROM routes
            WHERE driver_id = ? AND DATE(start_time) = ?
            ORDER BY is_active DESC, id DESC LIMIT 1
            """,
            (driver_id, today),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def get_todays_finished_route(driver_id: int) -> Optional[Dict]:
    """Повертає останній завершений маршрут водія за сьогодні (is_active=0)."""
    today = datetime.now().date().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM routes WHERE driver_id = ? AND is_active = 0 AND DATE(start_time) = ?"
            " ORDER BY id DESC LIMIT 1",
            (driver_id, today),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def get_all_active_routes_today() -> List[Dict]:
    """Всі активні маршрути за сьогодні з даними водія."""
    today = datetime.now().date().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT r.id, r.driver_id, r.start_time,
                   u.full_name, u.telegram_id
            FROM routes r
            JOIN users u ON r.driver_id = u.telegram_id
            WHERE r.is_active = 1 AND DATE(r.start_time) = ?
            """,
            (today,),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def reactivate_route(route_id: int):
    """Повертає завершений маршрут в активний стан (is_active=1, end_time=NULL, total_km=0, odometer_km=NULL)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE routes SET is_active = 1, end_time = NULL, total_km = 0, odometer_km = NULL WHERE id = ?",
            (route_id,),
        )
        await db.commit()


async def get_route_info(route_id: int) -> Optional[Dict]:
    """Базова інформація про маршрут з ім'ям водія (для діагностики)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT r.id, r.driver_id, u.full_name,
                   r.total_km, r.is_active, r.start_time, r.end_time,
                   COALESCE(r.is_manual, 0) AS is_manual
            FROM routes r
            JOIN users u ON r.driver_id = u.telegram_id
            WHERE r.id = ?
            """,
            (route_id,),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def set_manual_km(route_id: int, km: float) -> bool:
    """Встановлює кілометраж вручну і позначає маршрут як is_manual=1.
    Повертає True якщо маршрут знайдено і оновлено, False якщо не знайдено."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "UPDATE routes SET total_km = ?, is_manual = 1 WHERE id = ?",
            (km, route_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def clear_manual_km(route_id: int) -> bool:
    """Знімає позначку ручного вводу (is_manual=0) для маршруту.
    Повертає True якщо маршрут знайдено і оновлено, False якщо не знайдено."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "UPDATE routes SET is_manual = 0 WHERE id = ?",
            (route_id,),
        )
        await db.commit()
        return cur.rowcount > 0


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


async def get_last_valid_waypoint(route_id: int) -> Optional[Dict]:
    """Остання незапідозрена точка маршруту (is_suspicious=0)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM waypoints WHERE route_id = ? AND is_suspicious = 0 ORDER BY timestamp DESC LIMIT 1",
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
                   COALESCE(SUM(r.total_km), 0)        AS total_km,
                   SUM(r.odometer_km)                  AS total_odometer_km,
                   MIN(r.start_time)                   AS first_start,
                   MAX(COALESCE(r.end_time, datetime('now'))) AS last_end,
                   COALESCE(wc.wcount, 0)              AS waypoint_count
            FROM routes r
            JOIN users u ON r.driver_id = u.telegram_id
            LEFT JOIN (
                SELECT r2.driver_id,
                       COUNT(w.id) AS wcount
                FROM routes r2
                JOIN waypoints w ON w.route_id = r2.id
                WHERE DATE(r2.start_time) = ?
                GROUP BY r2.driver_id
            ) wc ON wc.driver_id = r.driver_id
            WHERE DATE(r.start_time) = ?
            GROUP BY r.driver_id
            """,
            (date_str, date_str),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def flag_suspicious_waypoints_retroactive() -> Dict:
    """Ретроактивно перераховує is_suspicious для всіх геоміток.

    Використовує поточний алгоритм з config (cascade-free):
    - час < MIN_TIME_MINUTES → перевірка відстані > MAX_DISTANCE_KM
    - час >= MIN_TIME_MINUTES → тільки швидкість > 160 км/год
    Також знімає прапор з точок що більше не є підозрілими.

    Повертає: {flagged: N, cleared: N, routes_affected: N}.
    """
    from bot.utils.geo import haversine
    from bot.config import MAX_DISTANCE_KM, MIN_TIME_MINUTES
    from datetime import datetime as _dt

    flagged = 0
    cleared = 0
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

            # Cascade-free: обробляємо всі точки, last_valid — серед вже оброблених
            new_flags = []
            for i, wp in enumerate(wps):
                if i == 0:
                    new_flags.append(0)
                    continue
                last_valid = next(
                    (wps[j] for j in range(i - 1, -1, -1) if new_flags[j] == 0),
                    None,
                )
                ref = last_valid if last_valid is not None else wps[i - 1]
                distance = haversine(ref["lat"], ref["lon"], wp["lat"], wp["lon"])
                suspicious = False
                try:
                    t1 = _dt.fromisoformat(ref["timestamp"])
                    t2 = _dt.fromisoformat(wp["timestamp"])
                    elapsed_min = abs((t2 - t1).total_seconds() / 60)
                    if elapsed_min < MIN_TIME_MINUTES:
                        suspicious = distance > MAX_DISTANCE_KM
                    else:
                        speed = distance / (elapsed_min / 60)
                        suspicious = speed > 160.0
                except Exception:
                    pass
                new_flags.append(1 if suspicious else 0)

            for wp, new_flag in zip(wps, new_flags):
                if wp["is_suspicious"] != new_flag:
                    await db.execute(
                        "UPDATE waypoints SET is_suspicious = ? WHERE id = ?",
                        (new_flag, wp["id"]),
                    )
                    if new_flag == 1:
                        flagged += 1
                    else:
                        cleared += 1
                    routes_affected.add(route_id)

        await db.commit()

    return {"flagged": flagged, "cleared": cleared, "routes_affected": len(routes_affected)}


async def recalculate_all_route_distances(date_str: Optional[str] = None) -> Dict:
    """Перераховує total_km для завершених маршрутів через Google Directions API.

    Args:
        date_str: Якщо задано (ISO date, напр. "2024-03-15") — тільки маршрути за цей день.
                  Інакше — всі завершені маршрути.

    Повертає словник: {recalculated: N, anomalies_fixed: N}.
    """
    from bot.utils.geo import get_road_distance_for_route

    recalculated = 0
    anomalies_fixed = 0

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if date_str:
            query = "SELECT id, total_km FROM routes WHERE is_active = 0 AND DATE(start_time) = ?"
            params = (date_str,)
        else:
            query = "SELECT id, total_km FROM routes WHERE is_active = 0"
            params = ()
        async with db.execute(query, params) as cur:
            routes = [dict(r) for r in await cur.fetchall()]

        for route in routes:
            waypoints = await get_route_waypoints(route["id"])
            new_km = await get_road_distance_for_route(waypoints)
            if new_km > 1000:
                from bot.utils.geo import calculate_route_distance
                new_km = round(calculate_route_distance(waypoints) * 1.4, 2)
                logger.warning(
                    "Маршрут %s: аномальний km > 1000, скинуто до haversine×1.4 = %.2f км",
                    route["id"], new_km,
                )
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


async def get_weekly_stats_by_day(start_date: str, end_date: str) -> List[Dict]:
    """Per-driver per-day breakdown for diagnostic logging."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT u.full_name,
                   rday.driver_id,
                   rday.day,
                   rday.route_count,
                   rday.km,
                   rday.has_manual,
                   COALESCE(wday.wcount, 0) AS waypoint_count
            FROM (
                SELECT driver_id,
                       DATE(start_time) AS day,
                       COUNT(id)        AS route_count,
                       COALESCE(SUM(total_km), 0)        AS km,
                       MAX(COALESCE(is_manual, 0))        AS has_manual
                FROM routes
                WHERE DATE(start_time) BETWEEN ? AND ?
                GROUP BY driver_id, DATE(start_time)
            ) rday
            JOIN users u ON rday.driver_id = u.telegram_id
            LEFT JOIN (
                SELECT r2.driver_id,
                       DATE(r2.start_time) AS day,
                       COUNT(w.id)         AS wcount
                FROM routes r2
                JOIN waypoints w ON w.route_id = r2.id
                WHERE DATE(r2.start_time) BETWEEN ? AND ?
                GROUP BY r2.driver_id, DATE(r2.start_time)
            ) wday ON wday.driver_id = rday.driver_id AND wday.day = rday.day
            ORDER BY u.full_name, rday.day
            """,
            (start_date, end_date, start_date, end_date),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def fix_suspicious_for_route(route_id: int) -> Dict:
    """Перераховує is_suspicious для кожної точки маршруту з поточним алгоритмом.

    Алгоритм cascade-free: для кожної точки шукає останню валідну (is_suspicious=0)
    серед вже оброблених точок. Оновлює is_suspicious в БД, потім перераховує total_km.

    Повертає: {fixed: N, total: N, old_km: float, new_km: float}
    """
    from bot.utils.geo import is_suspicious as check_suspicious, get_road_distance_for_route
    from bot.config import MAX_DISTANCE_KM, MIN_TIME_MINUTES

    waypoints = await get_route_waypoints(route_id)
    if not waypoints:
        return {"fixed": 0, "total": 0, "old_km": 0.0, "new_km": 0.0}

    # Перераховуємо is_suspicious в пам'яті (cascade-free)
    new_flags = []
    for i, wp in enumerate(waypoints):
        if i == 0:
            new_flags.append(0)
            continue
        # Останній валідний серед вже оброблених
        last_valid = next(
            (waypoints[j] for j in range(i - 1, -1, -1) if new_flags[j] == 0),
            None,
        )
        ref = last_valid if last_valid is not None else waypoints[i - 1]
        flag = check_suspicious(
            ref["lat"], ref["lon"], ref["timestamp"],
            wp["lat"], wp["lon"], wp["timestamp"],
            MAX_DISTANCE_KM, MIN_TIME_MINUTES,
        )
        new_flags.append(1 if flag else 0)

    # Записуємо оновлені прапори в БД
    fixed = 0
    async with aiosqlite.connect(DB_PATH) as db:
        for wp, new_flag in zip(waypoints, new_flags):
            if wp["is_suspicious"] != new_flag:
                await db.execute(
                    "UPDATE waypoints SET is_suspicious = ? WHERE id = ?",
                    (new_flag, wp["id"]),
                )
                fixed += 1
        await db.commit()

    # Перераховуємо total_km з оновленими прапорами
    updated_waypoints = await get_route_waypoints(route_id)
    new_km = await get_road_distance_for_route(updated_waypoints)

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT total_km FROM routes WHERE id = ?", (route_id,)
        ) as cur:
            row = await cur.fetchone()
            old_km = dict(row)["total_km"] if row else 0.0
        await db.execute(
            "UPDATE routes SET total_km = ? WHERE id = ?", (new_km, route_id)
        )
        await db.commit()

    return {"fixed": fixed, "total": len(waypoints), "old_km": old_km, "new_km": new_km}


async def get_weekly_stats(start_date: str, end_date: str) -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT u.full_name,
                   u.telegram_id,
                   COALESCE(SUM(r.total_km), 0)      AS total_km,
                   COUNT(r.id)                       AS route_count,
                   COALESCE(wc.wcount, 0)            AS waypoint_count,
                   MAX(COALESCE(r.is_manual, 0))     AS has_manual
            FROM routes r
            JOIN users u ON r.driver_id = u.telegram_id
            LEFT JOIN (
                SELECT r2.driver_id,
                       COUNT(w.id) AS wcount
                FROM routes r2
                JOIN waypoints w ON w.route_id = r2.id
                WHERE DATE(r2.start_time) BETWEEN ? AND ?
                GROUP BY r2.driver_id
            ) wc ON wc.driver_id = r.driver_id
            WHERE DATE(r.start_time) BETWEEN ? AND ?
            GROUP BY r.driver_id
            ORDER BY total_km DESC
            """,
            (start_date, end_date, start_date, end_date),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

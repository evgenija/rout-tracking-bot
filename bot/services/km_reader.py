"""
km_reader.py — читає km з P1 таблиць для P2 розрахунків.
ТІЛЬКИ SELECT. Жодних змін в P1 даних.

P1 використовує SQLite (aiosqlite) і на Railway, і локально.
P2 PostgreSQL pool — тільки для P2 таблиць (coefficients, monthly_data).
Таблиця 'users' (не 'drivers') — driver_id посилається на users.telegram_id.
Колонка driver_type додається міграцією add_driver_type.sql до таблиці users.
"""
import aiosqlite
from dataclasses import dataclass
from datetime import date

from bot.config import DB_PATH


@dataclass
class DailyKm:
    date: date
    logistics_km: float
    own_km: float


async def get_daily_km(pool, target_date: date) -> DailyKm:
    """
    Читає сумарні km за день з P1 таблиці routes.
    Розділяє за driver_type: 'logistics' | 'own'.
    Використовує total_km. P1 таблиці не змінювати.

    pool — не використовується (P1 SQLite), зарезервовано для сумісності API.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT
                COALESCE(u.driver_type, 'own')  AS driver_type,
                SUM(COALESCE(r.total_km, 0))     AS total_km
            FROM routes r
            LEFT JOIN users u ON r.driver_id = u.telegram_id
            WHERE DATE(r.start_time) = ?
              AND r.is_active = 0
            GROUP BY COALESCE(u.driver_type, 'own')
            """,
            (target_date.isoformat(),),
        ) as cur:
            rows = await cur.fetchall()

    logistics_km = 0.0
    own_km = 0.0
    for row in rows:
        if row["driver_type"] == "logistics":
            logistics_km = float(row["total_km"])
        else:
            own_km = float(row["total_km"])

    return DailyKm(date=target_date, logistics_km=logistics_km, own_km=own_km)

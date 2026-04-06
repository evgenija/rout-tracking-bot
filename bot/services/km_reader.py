"""
km_reader.py — читає km з P1 таблиць для P2 розрахунків.
ТІЛЬКИ SELECT. Жодних змін в P1 даних.

P1 на Railway використовує PostgreSQL (asyncpg).
Той самий pool що і решта P2 сервісів.
Таблиця 'users' (не 'drivers') — driver_id посилається на users.telegram_id.
Колонка driver_type додається міграцією add_driver_type.sql до таблиці users.
"""
from dataclasses import dataclass
from datetime import date


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
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                COALESCE(u.driver_type, 'own')       AS driver_type,
                SUM(COALESCE(r.total_km, 0))          AS total_km
            FROM routes r
            LEFT JOIN users u ON r.driver_id = u.telegram_id
            WHERE (r.start_time AT TIME ZONE 'Europe/Kyiv')::date = $1
              AND r.is_active = false
            GROUP BY COALESCE(u.driver_type, 'own')
            """,
            target_date,
        )

    logistics_km = 0.0
    own_km = 0.0
    for row in rows:
        if row["driver_type"] == "logistics":
            logistics_km = float(row["total_km"])
        else:
            own_km = float(row["total_km"])

    return DailyKm(date=target_date, logistics_km=logistics_km, own_km=own_km)

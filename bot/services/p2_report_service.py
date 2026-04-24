"""
p2_report_service.py — читає агреговані дані з P2 daily_input для денного звіту.
Не залежить від P1 SQLite, aiogram або telegram.
"""
import logging

logger = logging.getLogger(__name__)


async def get_p2_daily_by_date(pg_pool, date_str: str) -> dict:
    """
    Повертає {driver_id: {km, cost, driver_type}} з P2 daily_input за дату.
    Якщо pg_pool=None або запит впав — повертає {}.
    """
    if pg_pool is None:
        return {}
    try:
        async with pg_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT driver_id,
                       SUM(km)             AS total_km,
                       SUM(logistics_cost) AS total_cost,
                       MAX(driver_type)    AS driver_type
                FROM daily_input
                WHERE date = $1
                GROUP BY driver_id
                """,
                date_str,
            )
        return {
            row["driver_id"]: {
                "km":          row["total_km"],
                "cost":        row["total_cost"],
                "driver_type": row["driver_type"],
            }
            for row in rows
        }
    except Exception as e:
        logger.warning("P2 daily_input read failed for %s: %s", date_str, e)
        return {}


async def get_p2_weekly_by_range(pg_pool, start_date: str, end_date: str) -> dict:
    """
    Повертає {driver_id: {day_str: {km, cost}}} з daily_input за діапазон дат.
    Якщо pg_pool=None або запит впав — повертає {}.
    """
    if pg_pool is None:
        return {}
    try:
        async with pg_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT driver_id,
                       date::text        AS day,
                       SUM(km)           AS total_km,
                       SUM(logistics_cost) AS total_cost
                FROM daily_input
                WHERE date BETWEEN $1 AND $2
                GROUP BY driver_id, date
                ORDER BY driver_id, date
                """,
                start_date, end_date,
            )
        result: dict = {}
        for row in rows:
            result.setdefault(row["driver_id"], {})[row["day"]] = {
                "km":   row["total_km"],
                "cost": row["total_cost"],
            }
        return result
    except Exception as e:
        logger.warning("P2 weekly read failed (%s–%s): %s", start_date, end_date, e)
        return {}


def format_payment_line(p2_entry: dict | None) -> str:
    """
    Рядок оплати для денного звіту.
    p2_entry — один запис з get_p2_daily_by_date або None.
    """
    if not p2_entry:
        return "⏳ Оплата не розрахована"
    cost = p2_entry.get("cost") or 0.0
    km   = p2_entry.get("km")  or 0.0
    dtype = p2_entry.get("driver_type", "")
    type_label = "логістика" if dtype == "logistics" else "власний водій"
    return f"💰 Оплата: {cost:,.0f} грн | {km:.1f} км final ({type_label})".replace(",", " ")

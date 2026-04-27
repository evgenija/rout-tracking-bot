"""
finance_service.py — операції з P2 period_input та агрегація для P&L звітів.
Читає daily_input (доставка) і period_input (виручка).
P1 SQLite — тільки SELECT для перевірки маршрутів.
"""
import logging
from datetime import date, timedelta
from typing import Optional

import aiosqlite

from bot.config import DB_PATH
from bot.services.calculator import (
    calculate_daily_op_profit,
    calculate_weekly_net_profit,
    calculate_monthly_net_profit,
    DailyOpResult,
    WeeklyResult,
    MonthlyResult,
)

logger = logging.getLogger(__name__)


async def get_open_routes_for_date(target_date: date) -> list[dict]:
    """Повертає незакриті маршрути з P1 SQLite за дату (is_active=1)."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT r.id, u.full_name
                FROM routes r
                LEFT JOIN users u ON r.driver_id = u.telegram_id
                WHERE DATE(r.start_time) = ? AND r.is_active = 1
                """,
                (target_date.isoformat(),),
            ) as cur:
                rows = await cur.fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning("get_open_routes_for_date failed: %s", e)
        return []


async def get_delivery_totals_for_date(pg_pool, target_date: date) -> tuple[float, float]:
    """
    Повертає (logistics_total, own_total) з daily_input за дату.
    Якщо немає записів — (0.0, 0.0).
    """
    if pg_pool is None:
        return 0.0, 0.0
    try:
        async with pg_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT driver_type, SUM(logistics_cost) AS total_cost
                FROM daily_input
                WHERE date = $1
                GROUP BY driver_type
                """,
                target_date,
            )
        logistics = 0.0
        own = 0.0
        for row in rows:
            if row["driver_type"] == "logistics":
                logistics = float(row["total_cost"] or 0)
            else:
                own = float(row["total_cost"] or 0)
        return logistics, own
    except Exception as e:
        logger.warning("get_delivery_totals_for_date failed for %s: %s", target_date, e)
        return 0.0, 0.0


async def get_revenue_for_date(pg_pool, target_date: date) -> Optional[dict]:
    """
    Повертає {revenue, sales_km} з period_input де date_from <= target_date <= date_to.
    None якщо немає запису.
    """
    if pg_pool is None:
        return None
    try:
        async with pg_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT revenue, sales_km
                FROM period_input
                WHERE date_from <= $1 AND date_to >= $1
                ORDER BY created_at DESC
                LIMIT 1
                """,
                target_date,
            )
        if row is None:
            return None
        return {"revenue": int(row["revenue"]), "sales_km": int(row["sales_km"])}
    except Exception as e:
        logger.warning("get_revenue_for_date failed for %s: %s", target_date, e)
        return None


async def save_period_input(
    pg_pool,
    date_from: date,
    date_to: date,
    revenue: int,
    sales_km: int,
) -> bool:
    """
    Зберігає запис у period_input.
    Повертає True при успіху, False якщо є overlap або інша помилка.
    """
    if pg_pool is None:
        return False
    try:
        async with pg_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO period_input (date_from, date_to, revenue, sales_km)
                VALUES ($1, $2, $3, $4)
                """,
                date_from, date_to, revenue, sales_km,
            )
        return True
    except Exception as e:
        logger.warning("save_period_input failed (%s–%s): %s", date_from, date_to, e)
        return False


async def get_daily_op_result(
    pg_pool,
    target_date: date,
    coefficients: dict,
) -> Optional[DailyOpResult]:
    """
    Повертає DailyOpResult за дату або None якщо виручка ще не введена.
    """
    rev_data = await get_revenue_for_date(pg_pool, target_date)
    if rev_data is None:
        return None

    logistics, own = await get_delivery_totals_for_date(pg_pool, target_date)

    return calculate_daily_op_profit(
        revenue=rev_data["revenue"],
        sales_km=rev_data["sales_km"],
        delivery_logistics=logistics,
        delivery_own=own,
        report_date=target_date,
        coefficients=coefficients,
    )


async def get_missing_revenue_days(
    pg_pool,
    start_date: date,
    end_date: date,
) -> list[date]:
    """
    Повертає список дат без виручки в period_input за діапазон.
    Враховує тільки дати де є записи в daily_input (були маршрути).
    """
    if pg_pool is None:
        return []
    try:
        async with pg_pool.acquire() as conn:
            # Дати з маршрутами (доставка є)
            delivery_rows = await conn.fetch(
                "SELECT DISTINCT date FROM daily_input WHERE date BETWEEN $1 AND $2 ORDER BY date",
                start_date, end_date,
            )
            # Дати з введеною виручкою
            revenue_rows = await conn.fetch(
                """
                SELECT generate_series(date_from, date_to, '1 day'::interval)::date AS d
                FROM period_input
                WHERE date_from <= $2 AND date_to >= $1
                """,
                start_date, end_date,
            )

        delivery_dates = {row["date"] for row in delivery_rows}
        revenue_dates  = {row["d"] for row in revenue_rows}
        return sorted(delivery_dates - revenue_dates)
    except Exception as e:
        logger.warning("get_missing_revenue_days failed: %s", e)
        return []


async def get_working_days_in_month(pg_pool, year: int, month: int) -> int:
    """Кількість унікальних дат з маршрутами в daily_input за місяць."""
    if pg_pool is None:
        return 22  # fallback
    try:
        first_day = date(year, month, 1)
        if month == 12:
            last_day = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            last_day = date(year, month + 1, 1) - timedelta(days=1)
        async with pg_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COUNT(DISTINCT date) AS cnt FROM daily_input WHERE date BETWEEN $1 AND $2",
                first_day, last_day,
            )
        return int(row["cnt"]) if row and row["cnt"] else 1
    except Exception as e:
        logger.warning("get_working_days_in_month failed: %s", e)
        return 22


async def build_weekly_result(
    pg_pool,
    week_start: date,
    week_end: date,
    coefficients: dict,
) -> WeeklyResult:
    """Будує WeeklyResult для тижня. is_partial=True якщо є дні без виручки."""
    missing = await get_missing_revenue_days(pg_pool, week_start, week_end)
    working_days = await get_working_days_in_month(pg_pool, week_start.year, week_start.month)

    daily_results = []
    d = week_start
    while d <= week_end:
        result = await get_daily_op_result(pg_pool, d, coefficients)
        if result is not None:
            daily_results.append(result)
        d += timedelta(days=1)

    if not daily_results:
        # Повністю порожній тиждень
        from bot.services.calculator import WeeklyResult as WR
        return WR(
            week_start=week_start, week_end=week_end,
            revenue=0, op_profit=0, shared_week=0, taxes_week=0,
            net_profit=0, breakeven_day=0, revenue_vs_median_pct=None,
            is_partial=True, missing_days=missing,
        )

    result = calculate_weekly_net_profit(
        week_start=week_start,
        week_end=week_end,
        daily_results=daily_results,
        working_days_in_month=working_days,
        coefficients=coefficients,
    )
    result.is_partial = len(missing) > 0
    result.missing_days = missing
    return result


async def build_monthly_result(
    pg_pool,
    year: int,
    month: int,
    coefficients: dict,
) -> MonthlyResult:
    """Будує MonthlyResult для місяця."""
    first_day = date(year, month, 1)
    if month == 12:
        last_day = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        last_day = date(year, month + 1, 1) - timedelta(days=1)

    missing = await get_missing_revenue_days(pg_pool, first_day, last_day)
    working_days = await get_working_days_in_month(pg_pool, year, month)

    daily_results = []
    d = first_day
    while d <= last_day:
        result = await get_daily_op_result(pg_pool, d, coefficients)
        if result is not None:
            daily_results.append(result)
        d += timedelta(days=1)

    return calculate_monthly_net_profit(
        year=year,
        month=month,
        daily_results=daily_results,
        working_days=working_days,
        coefficients=coefficients,
        missing_days_count=len(missing),
    )

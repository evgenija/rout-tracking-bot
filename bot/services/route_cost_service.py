"""
route_cost_service.py — розрахунок вартості маршруту після завершення в P1.
Викликається з tracking.py після фінішу маршруту.
Зберігає в P2 PostgreSQL. Повідомляє супер-адміна.
"""
import logging
from datetime import date

from bot.services.calculator import _calc_logistics_cost, select_final_km
from bot.config import ADMIN_IDS
from bot.utils.time_utils import get_kyiv_time
from config_p2 import SUPER_ADMIN_IDS

logger = logging.getLogger(__name__)

LOGISTICS_DRIVER_IDS = {935741313, 1713367110, 570793350, 486855930, 432931183}  # Бодя, ZAZA, Уколов, Жека, Sheva


def get_driver_type(telegram_id: int) -> str:
    return "logistics" if telegram_id in LOGISTICS_DRIVER_IDS else "own"


async def on_route_finished(
    route_id: int,
    driver_id: int,
    driver_type: str,
    tracking_km: float,
    odometer_km: float | None,
    driver_name: str,
    coefficients: dict,
    pg_pool,
    bot,
) -> None:
    """
    Викликається після кожного завершення маршруту в P1.
    driver_type: 'logistics' або 'own'
    tracking_km: GPS total_km з P1 routes
    odometer_km: delta одометра (odometer_finish - odometer_start), або None якщо відсутній
    pg_pool: існуючий asyncpg pool (не створювати новий)
    """
    _coeff = coefficients
    if driver_type == "logistics":
        _coeff = dict(coefficients)
        _coeff["odometer_over_tracking_threshold"] = _coeff.get(
            "logistics_odometer_over_tracking_threshold", 0.095
        )
    final_km, reason = select_final_km(tracking_km, odometer_km, _coeff)

    if reason == 'odometer_missing':
        alert_text = (
            f"⚠️ Маршрут #{route_id} | {driver_name}\n"
            f"Одометр відсутній. Розрахунок за трекінгом GPS: {tracking_km:.1f} км"
        )
        for admin_id in list(set(ADMIN_IDS + SUPER_ADMIN_IDS)):
            try:
                await bot.send_message(admin_id, alert_text)
            except Exception:
                pass
    else:
        logger.info("final_km reason: %s, route_id: %s", reason, route_id)

    # Розрахунок вартості
    if driver_type == "logistics":
        cost = _calc_logistics_cost(final_km, coefficients)
    else:
        cost = final_km * coefficients["own_driver_cost_per_km"]

    # Зберегти в P2 PostgreSQL — ідемпотентно: continuation route оновлює існуючий рядок
    try:
        async with pg_pool.acquire() as conn:
            existing = await conn.fetchrow(
                "SELECT id, km FROM daily_input WHERE route_id = $1", route_id
            )
            if existing:
                total_km = existing["km"] + final_km
                if driver_type == "logistics":
                    total_cost = _calc_logistics_cost(total_km, coefficients)
                else:
                    total_cost = total_km * coefficients["own_driver_cost_per_km"]
                await conn.execute(
                    "UPDATE daily_input SET km = $1, logistics_cost = $2 WHERE route_id = $3",
                    total_km, total_cost, route_id,
                )
                logger.info(
                    "P2 daily_input route_id %d: continuation km %.2f+%.2f=%.2f, cost %.2f→%.2f",
                    route_id, existing["km"], final_km, total_km, cost, total_cost,
                )
                final_km, cost = total_km, total_cost
            else:
                await conn.execute(
                    """
                    INSERT INTO daily_input
                        (date, route_id, driver_id, driver_type, km, logistics_cost)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    get_kyiv_time().date(), route_id, driver_id, driver_type, final_km, cost,
                )
    except Exception as e:
        logger.warning("P2 daily_input save failed: %s", e)

    # Повідомлення супер-адміну
    def fmt(v):
        return f"{v:,.0f}".replace(",", " ")

    cost_label = "логістики" if driver_type == "logistics" else "власного водія"
    text = (
        f"🚛 Маршрут #{route_id} завершено\n"
        f"👤 Водій ID: {driver_id} | Тип: {driver_type}\n"
        f"📏 km: {final_km:.1f}\n"
        f"💰 Вартість {cost_label}: {fmt(cost)} грн"
    )
    for admin_id in SUPER_ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text)
        except Exception:
            pass

    # Якщо це останній відкритий маршрут за сьогодні і виручка вже введена —
    # надіслати скоригований денний Op.Profit з повними витратами
    try:
        from bot.services.finance_service import get_open_routes_for_date, get_daily_op_result
        from bot.services.report_service import format_daily_op_report
        route_date = get_kyiv_time().date()
        open_routes = await get_open_routes_for_date(route_date)
        if not open_routes:
            result = await get_daily_op_result(pg_pool, route_date, coefficients)
            if result is not None:
                corrected_text = (
                    f"🔄 Всі маршрути закрито — перерахунок за {route_date.strftime('%d.%m.%Y')}\n\n"
                    + format_daily_op_report(result)
                )
                for admin_id in SUPER_ADMIN_IDS:
                    try:
                        await bot.send_message(admin_id, corrected_text)
                    except Exception:
                        pass
    except Exception as _e:
        logger.warning("Corrected daily report after route close failed: %s", _e)

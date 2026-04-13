"""
route_cost_service.py — розрахунок вартості маршруту після завершення в P1.
Викликається з tracking.py після фінішу маршруту.
Зберігає в P2 PostgreSQL. Повідомляє супер-адміна.
"""
import logging
from datetime import date

from bot.services.calculator import _calc_logistics_cost
from config_p2 import SUPER_ADMIN_IDS

logger = logging.getLogger(__name__)

LOGISTICS_DRIVER_IDS = {935741313, 1713367110, 570793350}  # Бодя, ZAZA, Уколов


def get_driver_type(telegram_id: int) -> str:
    return "logistics" if telegram_id in LOGISTICS_DRIVER_IDS else "own"


async def on_route_finished(
    route_id: int,
    driver_id: int,
    driver_type: str,
    km: float,
    coefficients: dict,
    pg_pool,
    bot,
) -> None:
    """
    Викликається після кожного завершення маршруту в P1.
    driver_type: 'logistics' або 'own' (дефолт 'own' якщо не визначено)
    km: total_km або odometer_km з P1 routes таблиці
    pg_pool: існуючий asyncpg pool (не створювати новий)
    """
    # Розрахунок вартості
    if driver_type == "logistics":
        cost = _calc_logistics_cost(km, coefficients)
    else:
        cost = km * coefficients["own_driver_cost_per_km"]

    # Зберегти в P2 PostgreSQL
    try:
        async with pg_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO daily_input
                    (date, route_id, driver_id, driver_type, km, logistics_cost)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                date.today(), route_id, driver_id, driver_type, km, cost,
            )
    except Exception as e:
        logger.warning("P2 daily_input save failed: %s", e)
        return

    # Повідомлення супер-адміну
    def fmt(v):
        return f"{v:,.0f}".replace(",", " ")

    cost_label = "логістики" if driver_type == "logistics" else "власного водія"
    text = (
        f"🚛 Маршрут #{route_id} завершено\n"
        f"👤 Водій ID: {driver_id} | Тип: {driver_type}\n"
        f"📏 km: {km:.1f}\n"
        f"💰 Вартість {cost_label}: {fmt(cost)} грн"
    )
    for admin_id in SUPER_ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text)
        except Exception:
            pass

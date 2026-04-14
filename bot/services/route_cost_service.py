"""
route_cost_service.py — розрахунок вартості маршруту після завершення в P1.
Викликається з tracking.py після фінішу маршруту.
Зберігає в P2 PostgreSQL. Повідомляє супер-адміна.
"""
import logging
from datetime import date

from bot.services.calculator import _calc_logistics_cost, select_final_km
from bot.config import ADMIN_IDS
from config_p2 import SUPER_ADMIN_IDS

logger = logging.getLogger(__name__)

LOGISTICS_DRIVER_IDS = {935741313, 1713367110, 570793350}  # Бодя, ZAZA, Уколов


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
    final_km, reason = select_final_km(tracking_km, odometer_km, coefficients)

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

    # Зберегти в P2 PostgreSQL
    try:
        async with pg_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO daily_input
                    (date, route_id, driver_id, driver_type, km, logistics_cost)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                date.today(), route_id, driver_id, driver_type, final_km, cost,
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
        f"📏 km: {final_km:.1f}\n"
        f"💰 Вартість {cost_label}: {fmt(cost)} грн"
    )
    for admin_id in SUPER_ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text)
        except Exception:
            pass

import logging
from typing import Optional

from bot.models.database import (
    get_last_finished_route_with_odo,
    get_last_route_by_odometer,
    get_last_waypoint,
    get_route_waypoints,
    get_user,
)
from bot.utils.geo import haversine

logger = logging.getLogger(__name__)

ODO_MAX_DIFF_KM = 800.0


def validate_finish_odometer(odo_start: float, odo_finish: float) -> Optional[str]:
    """Повертає текст помилки або None якщо дані валідні."""
    diff = odo_finish - odo_start
    if diff <= 0:
        return (
            f"⚠️ Помилка: показник фінішу ({odo_finish:.0f}) менший або рівний показнику старту ({odo_start:.0f}).\n"
            "Перевір дані лічильника та введи ще раз:"
        )
    if diff > ODO_MAX_DIFF_KM:
        return (
            f"⚠️ Незвичні дані: пробіг за маршрут {diff:.0f} км перевищує {ODO_MAX_DIFF_KM:.0f} км.\n"
            "Перевір дані лічильника та введи ще раз:"
        )
    return None


async def build_odo_start_alert(driver_id: int, odometer_start: float) -> Optional[str]:
    """Порівнює старт сьогодні з фінішем останнього маршруту. Повертає текст алерту або None."""
    last_route = await get_last_finished_route_with_odo(driver_id)
    if not last_route or not last_route.get("odometer_km"):
        return None

    prev_odo = last_route["odometer_km"]
    route_date = last_route.get("route_date", "?")
    diff = odometer_start - prev_odo

    _user = await get_user(driver_id)
    driver_name = _user["full_name"] if _user else "Водій"

    diff_emoji = "⚠️" if diff < 0 else "✅"
    diff_text = (
        f"сьогодні МЕНШЕ на {abs(diff):.0f} км — можлива помилка або зміна авто"
        if diff < 0
        else f"+{diff:.0f} км"
    )
    return (
        f"📊 Одометр {driver_name}:\n"
        f"Останній маршрут ({route_date}): фінішував {prev_odo:.0f} → сьогодні старт {odometer_start:.0f} км\n"
        f"{diff_emoji} {diff_text}"
    )


async def build_geo_mismatch_line(route_id: int, odometer_start: float, driver_id: int) -> Optional[str]:
    """Додатковий рядок до алерту: odometer_diff=0 І геомітки розходяться > 2 км.

    Порівнює останню геомітку попереднього маршруту (за машиною через одометр,
    fallback — за водієм) з першою геоміткою поточного маршруту.
    Повертає рядок для дописування або None якщо умова не виконана / дані недоступні.
    Помилки перехоплюються — алерт надсилається без нового рядка.
    """
    try:
        last_route = await get_last_finished_route_with_odo(driver_id)
        if not last_route or not last_route.get("odometer_km"):
            return None

        if odometer_start - last_route["odometer_km"] != 0:
            return None

        # Шукаємо попередній маршрут по одометру (будь-який водій = та сама машина)
        machine_route = await get_last_route_by_odometer(odometer_start)
        prev_route_id = machine_route["id"] if machine_route else last_route["id"]

        prev_wp = await get_last_waypoint(prev_route_id)
        if not prev_wp:
            return None

        current_wps = await get_route_waypoints(route_id)
        if not current_wps:
            return None

        dist = haversine(prev_wp["lat"], prev_wp["lon"], current_wps[0]["lat"], current_wps[0]["lon"])
        if dist > 2.0:
            return f"\n\n⚠️ Геомітки різні (~{dist:.0f} км), а одометр 0 км — варто перевірити"

        return None
    except Exception as exc:
        logger.warning("Geo mismatch check failed: %s", exc)
        return None

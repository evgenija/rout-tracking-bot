import logging
from typing import Optional

from bot.models.database import get_last_finished_route_with_odo, get_user

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

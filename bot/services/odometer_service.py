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
    """Порівнює старт сьогодні з фінішем останнього маршруту водія. Повертає текст алерту або None."""
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
    alert = (
        f"📊 Одометр {driver_name}:\n"
        f"Останній маршрут ({route_date}): фінішував {prev_odo:.0f} → сьогодні старт {odometer_start:.0f} км\n"
        f"{diff_emoji} {diff_text}"
    )

    # Перевірка по машині: чи їздив інший водій на цій машині нещодавно
    machine_route = await get_last_route_by_odometer(odometer_start)
    if machine_route and machine_route["driver_id"] != driver_id:
        other_user = await get_user(machine_route["driver_id"])
        other_name = other_user["full_name"] if other_user else f"ID {machine_route['driver_id']}"
        alert += (
            f"\n🚗 Можлива та сама машина: {other_name} їздив на ній нещодавно"
            f" (одометр ~{machine_route['odometer_km']:.0f} км)"
        )

    return alert


async def build_geo_mismatch_line(
    route_id: int, odometer_start: float, driver_id: int
) -> tuple[Optional[str], Optional[str]]:
    """Перевірка геоміток між попереднім фінішем і поточним стартом.

    Завжди виконується при старті маршруту. Шукає попередній маршрут спочатку
    по машині (get_last_route_by_odometer), потім fallback по водію.

    Повертає (geo_line, cheat_alert):
      geo_line    — рядок для додавання в одометровий алерт адмінам/супер-адмінам
      cheat_alert — окреме повідомлення тільки для супер-адмінів (підозра на чітерство)

    Кейси:
      відстань < 2 км               → geo_line "співпадають", cheat_alert=None
      відстань ≥ 2 км + diff ≈ 0    → geo_line ⚠️ + cheat_alert 🚨 (головний кейс)
      відстань ≥ 2 км + diff ≠ 0    → geo_line "підтверджують пробіг", cheat_alert=None
    """
    try:
        # Попередній маршрут: по машині → fallback по водію
        machine_route = await get_last_route_by_odometer(odometer_start)
        last_route = await get_last_finished_route_with_odo(driver_id)

        if machine_route:
            prev_route_id = machine_route["id"]
            prev_odo_km = machine_route["odometer_km"]
        elif last_route and last_route.get("odometer_km"):
            prev_route_id = last_route["id"]
            prev_odo_km = last_route["odometer_km"]
        else:
            return None, None

        prev_wp = await get_last_waypoint(prev_route_id)
        if not prev_wp:
            return None, None

        current_wps = await get_route_waypoints(route_id)
        if not current_wps:
            return None, None

        dist = haversine(prev_wp["lat"], prev_wp["lon"], current_wps[0]["lat"], current_wps[0]["lon"])
        odometer_diff = odometer_start - prev_odo_km

        if dist < 2.0:
            dist_m = int(dist * 1000)
            return f"\n📍 Геомітки фінішу та старту співпадають (~{dist_m} м)", None

        # dist >= 2.0
        if abs(odometer_diff) < 1.0:
            _user = await get_user(driver_id)
            driver_name = _user["full_name"] if _user else f"ID {driver_id}"
            geo_line = f"\n\n⚠️ Геомітки різні (~{dist:.0f} км), а одометр 0 км — варто перевірити"
            cheat_alert = (
                f"🚨 Підозра на приховані кілометри\n"
                f"👤 {driver_name}\n"
                f"📍 Геомітки фінішу та старту розходяться на ~{dist:.0f} км\n"
                f"🔢 Одометр: різниця 0 км — машина нібито не рухалась\n"
                f"⚠️ Можливо водій їздив після маршруту за особистими потребами"
            )
            return geo_line, cheat_alert

        # dist >= 2.0, diff != 0 — одометр підтверджує пробіг між маршрутами
        return f"\n📍 Геомітки підтверджують: між маршрутами машина переміщалась (~{dist:.0f} км)", None

    except Exception as exc:
        logger.warning("Geo mismatch check failed: %s", exc)
        return None, None

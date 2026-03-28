import logging
from datetime import datetime

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from bot.utils.keyboards import kb_driver_idle, kb_driver_active, kb_admin_driver_idle, kb_admin_driver_active

from bot.config import ADMIN_IDS, SUPER_ADMIN_IDS, GROUP_CHAT_ID, MAX_DISTANCE_KM, MIN_TIME_MINUTES
from bot.models.database import (
    add_waypoint,
    end_route,
    get_active_route,
    get_last_waypoint,
    get_last_valid_waypoint,
    get_route_waypoints,
    get_todays_finished_route,
    get_todays_route,
    get_user,
    reactivate_route,
    save_odometer,
    start_route,
)
from bot.utils.geo import get_road_distance_for_route
from bot.utils.geo import is_suspicious as check_suspicious

logger = logging.getLogger(__name__)
router = Router()


class WaypointState(StatesGroup):
    waiting_for_name = State()
    waiting_for_start_location = State()


class OdometerState(StatesGroup):
    waiting_for_odometer = State()


# ── Auth helper ───────────────────────────────────────────────────────────────

async def _approved(user_id: int) -> bool:
    if user_id in ADMIN_IDS or user_id in SUPER_ADMIN_IDS:
        return True
    user = await get_user(user_id)
    return bool(user and user["is_approved"])


# ── Кнопки Reply Keyboard (дублюють команди) ─────────────────────────────────

@router.message(F.text == "🚀 Почати маршрут")
async def btn_start_route(message: Message, state: FSMContext):
    await cmd_start_route(message, state)

@router.message(F.text == "🏁 Завершити маршрут")
async def btn_end_route(message: Message, state: FSMContext):
    await cmd_end_route(message, state)


# ── /start_route ──────────────────────────────────────────────────────────────

@router.message(Command("start_route"))
async def cmd_start_route(message: Message, state: FSMContext):
    user_id = message.from_user.id

    if not await _approved(user_id):
        await message.answer("❌ Ви не авторизовані. Надішліть /start.")
        return

    if await get_active_route(user_id):
        await message.answer("⚠️ Активний маршрут вже є. Завершіть його: /end_route")
        return

    user = await get_user(user_id)
    is_adm = user_id in ADMIN_IDS or user_id in SUPER_ADMIN_IDS
    todays_route = await get_todays_finished_route(user_id)

    if todays_route:
        # Продовжуємо завершений маршрут за сьогодні
        await reactivate_route(todays_route["id"])
        route_id = todays_route["id"]
        time_finish = (
            datetime.fromisoformat(todays_route["end_time"]).strftime("%H:%M")
            if todays_route.get("end_time")
            else "невідомо"
        )
        time_restart = datetime.now().strftime("%H:%M")
        label = f"▶️ Маршрут #{route_id} продовжено!"
        group_label = (
            f"🔄 Маршрут {user['full_name']} поновлено після перерви\n"
            f"⏸ Перерва з {time_finish} до {time_restart}\n"
            f"⚠️ Геомітки за цей період не збережені"
        )
    else:
        # Новий маршрут
        now = datetime.now().isoformat()
        route_id = await start_route(user_id, now)
        label = f"🚀 Маршрут #{route_id} розпочато!"
        group_label = f"🚀 Водій {user['full_name']} розпочав маршрут #{route_id}"

    try:
        await message.bot.send_message(
            GROUP_CHAT_ID,
            f"{group_label}\n⏰ {datetime.now().strftime('%H:%M %d.%m.%Y')}",
        )
    except Exception as e:
        logger.warning("Не вдалося надіслати старт в груповий чат: %s", e)

    await state.update_data(start_route_id=route_id, start_is_adm=is_adm)
    await state.set_state(WaypointState.waiting_for_start_location)
    await message.answer(
        f"{label}\n"
        f"⏰ {datetime.now().strftime('%H:%M %d.%m.%Y')}\n\n"
        "📍 Надішли своє місцезнаходження для фіксації старту маршруту.",
        reply_markup=kb_admin_driver_active() if is_adm else kb_driver_active(),
    )


# ── /end_route ────────────────────────────────────────────────────────────────

@router.message(Command("end_route"))
async def cmd_end_route(message: Message, state: FSMContext):
    user_id = message.from_user.id

    if not await _approved(user_id):
        await message.answer("❌ Ви не авторизовані.")
        return

    active = await get_active_route(user_id)
    if not active:
        await message.answer("❌ Немає активного маршруту.")
        return

    waypoints = await get_route_waypoints(active["id"])
    total_km = await get_road_distance_for_route(waypoints)
    if total_km > 1000:
        from bot.utils.geo import calculate_route_distance
        suspicious_count = sum(1 for wp in waypoints if wp.get("is_suspicious"))
        logger.warning(
            "Маршрут #%s: аномальний km=%.2f (підозрілих %d/%d) — fallback haversine×1.4",
            active["id"], total_km, suspicious_count, len(waypoints),
        )
        total_km = round(calculate_route_distance(waypoints) * 1.4, 2)
        for admin_id in ADMIN_IDS:
            try:
                await message.bot.send_message(
                    admin_id,
                    f"⚠️ Маршрут #{active['id']}: аномальний кілометраж скинуто.\n"
                    f"Збережено: {total_km:.1f} км (haversine×1.4)\n"
                    f"Підозрілих точок: {suspicious_count}/{len(waypoints)}",
                )
            except Exception:
                pass

    now = datetime.now().isoformat()
    await end_route(active["id"], now, total_km)

    start_dt = datetime.fromisoformat(active["start_time"])
    delta = datetime.now() - start_dt
    hours, rem = divmod(int(delta.total_seconds()), 3600)
    minutes = rem // 60

    user = await get_user(user_id)
    is_adm = user_id in ADMIN_IDS or user_id in SUPER_ADMIN_IDS

    await state.update_data(
        odometer_route_id=active["id"],
        odometer_total_km=total_km,
        odometer_user_name=user["full_name"],
        odometer_waypoint_count=len(waypoints),
        odometer_duration=f"{hours}г {minutes}хв",
        odometer_time=datetime.now().strftime('%H:%M %d.%m.%Y'),
        odometer_is_adm=is_adm,
    )
    await state.set_state(OdometerState.waiting_for_odometer)

    await message.answer(
        f"🏁 Маршрут #{active['id']} завершено!\n\n"
        f"📟 Скільки показує одометр?\n"
        f"Введіть ціле число км (наприклад: 15420)\n"
        f"або /пропустити якщо одометру немає",
        reply_markup=kb_admin_driver_idle() if is_adm else kb_driver_idle(),
    )


# ── Одометр після Фінішу ──────────────────────────────────────────────────────

@router.message(OdometerState.waiting_for_odometer)
async def handle_odometer_input(message: Message, state: FSMContext):
    data = await state.get_data()
    await state.clear()

    route_id    = data["odometer_route_id"]
    total_km    = data["odometer_total_km"]
    user_name   = data["odometer_user_name"]
    wp_count    = data["odometer_waypoint_count"]
    duration    = data["odometer_duration"]
    time_str    = data["odometer_time"]
    is_adm      = data["odometer_is_adm"]

    odometer_km = None
    text = (message.text or "").strip()

    if text and text != "/пропустити":
        try:
            val = int(text)
            if val > 0:
                odometer_km = float(val)
                await save_odometer(route_id, odometer_km)
        except ValueError:
            pass

    # Будуємо summary
    summary = (
        f"🏁 Маршрут #{route_id} завершено!\n\n"
        f"👤 {user_name}\n"
        f"📍 Точок: {wp_count}\n"
        f"🛣 Відстань: {total_km:.2f} км (програма)\n"
    )
    diff = None
    if odometer_km is not None:
        diff = abs(total_km - odometer_km) / odometer_km * 100 if odometer_km > 0 else 0.0
        summary += f"📟 Одометр: {odometer_km:.0f} км\n"
        summary += f"📊 Розбіжність: {diff:.1f}%\n"
    summary += f"⏱ Тривалість: {duration}\n"
    summary += f"⏰ {time_str}"

    await message.answer(summary)

    # Повідомлення адмінам (з алертом при розбіжності > 30%)
    admin_msg = summary
    if diff is not None and diff > 30:
        admin_msg += (
            f"\n\n⚠️ Велика розбіжність: {user_name} "
            f"програма {total_km:.1f} км / одометр {odometer_km:.0f} км ({diff:.1f}%)"
        )

    for admin_id in ADMIN_IDS:
        try:
            await message.bot.send_message(admin_id, admin_msg)
        except Exception as e:
            logger.warning("Не вдалося надіслати фініш адміну %s: %s", admin_id, e)

    try:
        await message.bot.send_message(GROUP_CHAT_ID, summary)
    except Exception as e:
        logger.warning("Не вдалося надіслати фініш в груповий чат: %s", e)


# ── Геолокація ────────────────────────────────────────────────────────────────

# Геомітка старту маршруту (обробляється до загального handle_location!)
@router.message(F.location, WaypointState.waiting_for_start_location)
async def handle_start_location(message: Message, state: FSMContext):
    data = await state.get_data()
    route_id = data.get("start_route_id")
    is_adm   = data.get("start_is_adm", False)
    await state.clear()

    if not route_id:
        return

    lat = message.location.latitude
    lon = message.location.longitude
    now = datetime.now().isoformat()
    await add_waypoint(route_id, lat, lon, "Старт", now, False)

    user = await get_user(message.from_user.id)
    await message.answer(
        "✅ Старт зафіксовано! Удачної дороги!",
        reply_markup=kb_admin_driver_active() if is_adm else kb_driver_active(),
    )
    try:
        await message.bot.send_location(GROUP_CHAT_ID, latitude=lat, longitude=lon)
        await message.bot.send_message(GROUP_CHAT_ID, f"📍 {user['full_name']} — Старт")
    except Exception as e:
        logger.warning("Не вдалося надіслати старт-геомітку в груповий чат: %s", e)


@router.message(F.location)
async def handle_location(message: Message, state: FSMContext):
    user_id = message.from_user.id

    if not await _approved(user_id):
        return

    route = await get_todays_route(user_id)
    if not route:
        await message.answer("❌ Спочатку почніть маршрут: /start_route")
        return

    await state.update_data(
        pending_lat=message.location.latitude,
        pending_lon=message.location.longitude,
        pending_route_id=route["id"],
    )
    await state.set_state(WaypointState.waiting_for_name)
    await message.answer("📍 Геолокацію отримано. Введіть назву точки:")


@router.message(WaypointState.waiting_for_name)
async def handle_waypoint_name(message: Message, state: FSMContext):
    user_id = message.from_user.id
    point_name = message.text.strip()

    data = await state.get_data()
    lat = data.get("pending_lat")
    lon = data.get("pending_lon")
    route_id = data.get("pending_route_id")
    await state.clear()

    if lat is None or lon is None or route_id is None:
        await message.answer("❌ Помилка: геолокація не знайдена. Надішліть знову.")
        return

    now = datetime.now().isoformat()

    # РЕБ-спуфінг перевірка — порівнюємо з останньою валідною точкою
    last_wp = await get_last_valid_waypoint(route_id)
    if last_wp is None:
        last_wp = await get_last_waypoint(route_id)  # fallback: всі попередні підозрілі
    suspicious = False
    if last_wp:
        suspicious = check_suspicious(
            last_wp["lat"], last_wp["lon"], last_wp["timestamp"],
            lat, lon, now,
            MAX_DISTANCE_KM, MIN_TIME_MINUTES,
        )

    await add_waypoint(route_id, lat, lon, point_name, now, suspicious)

    user = await get_user(user_id)
    flag = "⚠️" if suspicious else "📍"

    # Коротке підтвердження водію без деталей
    is_adm = user_id in ADMIN_IDS or user_id in SUPER_ADMIN_IDS
    await message.answer(
        f"{flag} Точку збережено" + (" — підозріла!" if suspicious else ""),
        reply_markup=kb_admin_driver_active() if is_adm else kb_driver_active(),
    )

    # Карта + підпис з деталями — тільки в груповий чат
    caption = f"{flag} {user['full_name']} — {point_name}"
    if suspicious:
        caption += "\n⚠️ ПІДОЗРІЛА ГЕОМІТКА — можливий GPS-спуфінг!"

    try:
        await message.bot.send_location(GROUP_CHAT_ID, latitude=lat, longitude=lon)
        await message.bot.send_message(GROUP_CHAT_ID, caption)
    except Exception as e:
        logger.warning("Не вдалося надіслати в груповий чат %s: %s", GROUP_CHAT_ID, e)

    # Сповістити адмінів про підозрілу мітку
    if suspicious:
        alert = (
            f"🚨 ПІДОЗРІЛА ГЕОМІТКА!\n"
            f"👤 {user['full_name']} (ID: {user_id})\n"
            f"📍 {point_name}\n"
            f"📌 {lat:.5f}, {lon:.5f}\n"
            f"Маршрут #{route_id}"
        )
        for admin_id in ADMIN_IDS:
            try:
                await message.bot.send_message(admin_id, alert)
            except Exception as e:
                logger.warning("Не вдалося сповістити адміна %s: %s", admin_id, e)

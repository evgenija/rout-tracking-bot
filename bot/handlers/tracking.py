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
    save_odometer_start,
    start_route,
)
from bot.utils.geo import get_road_distance_for_route
from bot.utils.geo import is_suspicious as check_suspicious

logger = logging.getLogger(__name__)
router = Router()


class WaypointState(StatesGroup):
    waiting_for_name = State()
    waiting_for_start_location = State()
    waiting_for_start_odometer = State()


class OdometerState(StatesGroup):
    waiting_for_finish_location = State()
    waiting_for_finish_odometer = State()


# ── Auth helper ───────────────────────────────────────────────────────────────

async def _approved(user_id: int) -> bool:
    if user_id in ADMIN_IDS or user_id in SUPER_ADMIN_IDS:
        return True
    user = await get_user(user_id)
    return bool(user and user["is_approved"])


def _is_silent_driver(user_id: int) -> bool:
    """Адміни, що їздять як водії, не надсилають повідомлення в груповий чат."""
    return user_id in ADMIN_IDS or user_id in SUPER_ADMIN_IDS


def _format_odometer_accuracy(
    total_km: float,
    odometer_start,
    odometer_km,
) -> tuple:
    """Повертає (текст_секції, потрібен_алерт).

    Обробляє 5 сценаріїв наявності/відсутності одометрових даних.
    Алерт = True тільки в сценарії 1 (обидва введено, diff > 0) при похибці > 30%.
    """
    has_start  = odometer_start is not None
    has_finish = odometer_km is not None

    if has_start and has_finish:
        odometer_diff = odometer_km - odometer_start
        if odometer_diff <= 0:
            # Сценарій 5 — помилка вводу
            text = (
                f"📌 Одометр: {odometer_start:.0f} → {odometer_km:.0f} км\n"
                f"   ⚠️ Помилка вводу — показник фінішу менший за старт"
            )
            return text, False

        # Сценарій 1 — обидва введено, diff > 0
        diff_pct = abs(total_km - odometer_diff) / odometer_diff * 100
        if diff_pct <= 10:
            label = "✅ Норма"
        elif diff_pct <= 25:
            label = "⚠️ Місто/Waze (очікувано)"
        elif diff_pct <= 40:
            label = "🔶 Перевірити маршрут"
        else:
            label = "🔴 Критична розбіжність"
        text = (
            f"📌 Одометр: {odometer_start:.0f} → {odometer_km:.0f} км\n"
            f"   Пробіг за одометром: {odometer_diff:.1f} км\n"
            f"   Трекінг: {total_km:.2f} км\n"
            f"   Похибка: {diff_pct:.1f}%  {label}"
        )
        return text, diff_pct > 30

    if not has_start and has_finish:
        # Сценарій 2
        text = (
            f"📌 Одометр при старті не введено\n"
            f"   Одометр фінішу: {odometer_km:.0f} км\n"
            f"   ⚠️ Порівняння недоступне — водій не ввів одометр на старті"
        )
        return text, False

    if has_start and not has_finish:
        # Сценарій 3
        text = (
            f"📌 Одометр старту: {odometer_start:.0f} км\n"
            f"   Одометр при фінішу не введено\n"
            f"   ⚠️ Порівняння недоступне — водій не ввів одометр на фінішу"
        )
        return text, False

    # Сценарій 4 — жодного
    return "📌 Одометр не введено ні на старті ні на фінішу\n   ⚠️ Порівняння недоступне", False


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
        now_dt = datetime.now()
        finish_dt = (
            datetime.fromisoformat(todays_route["end_time"])
            if todays_route.get("end_time")
            else now_dt
        )
        time_finish = finish_dt.strftime("%H:%M")
        time_restart = now_dt.strftime("%H:%M")
        date_str = now_dt.strftime("%d.%m.%Y")
        duration_min = max(0, int((now_dt - finish_dt).total_seconds() / 60))
        label = f"▶️ Маршрут #{route_id} продовжено!"
        group_label = (
            f"🔄 Маршрут {user['full_name']} поновлено після перерви\n"
            f"⏸ Перерва з {time_finish} до {time_restart}\n"
            f"⏱ Тривалість перерви: {duration_min} хв\n"
            f"🕐 {time_restart} {date_str}"
        )
        group_time_suffix = ""  # час вже в group_label
    else:
        # Новий маршрут
        now = datetime.now().isoformat()
        route_id = await start_route(user_id, now)
        label = f"🚀 Маршрут #{route_id} розпочато!"
        group_label = f"🚀 Водій {user['full_name']} розпочав маршрут #{route_id}"
        group_time_suffix = f"\n⏰ {datetime.now().strftime('%H:%M %d.%m.%Y')}"

    if not _is_silent_driver(user_id):
        try:
            await message.bot.send_message(
                GROUP_CHAT_ID,
                f"{group_label}{group_time_suffix}",
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

    user = await get_user(user_id)
    is_adm = user_id in ADMIN_IDS or user_id in SUPER_ADMIN_IDS

    await state.update_data(
        finish_route_id=active["id"],
        finish_start_time=active["start_time"],
        finish_is_adm=is_adm,
        finish_user_name=user["full_name"],
        finish_odometer_start=active.get("odometer_start"),
    )
    await state.set_state(OdometerState.waiting_for_finish_location)
    await message.answer(
        "🏁 Завершення маршруту\n\n"
        "📍 Надішли своє місцезнаходження для фіксації фінішу.",
        reply_markup=kb_admin_driver_active() if is_adm else kb_driver_active(),
    )


# ── Геомітка та одометр Фінішу ────────────────────────────────────────────────

@router.message(F.location, OdometerState.waiting_for_finish_location)
async def handle_finish_location(message: Message, state: FSMContext):
    data = await state.get_data()
    route_id   = data.get("finish_route_id")
    is_adm     = data.get("finish_is_adm", False)
    user_name  = data.get("finish_user_name", "")
    start_time = data.get("finish_start_time")

    if not route_id:
        await state.clear()
        return

    lat = message.location.latitude
    lon = message.location.longitude
    now = datetime.now().isoformat()
    await add_waypoint(route_id, lat, lon, "Фініш", now, False)

    # Розрахунок кілометражу (включно з точкою Фінішу)
    waypoints = await get_route_waypoints(route_id)
    total_km = await get_road_distance_for_route(waypoints)
    if total_km > 1000:
        from bot.utils.geo import calculate_route_distance
        suspicious_count = sum(1 for wp in waypoints if wp.get("is_suspicious"))
        logger.warning(
            "Маршрут #%s: аномальний km=%.2f (підозрілих %d/%d) — fallback haversine×1.4",
            route_id, total_km, suspicious_count, len(waypoints),
        )
        total_km = round(calculate_route_distance(waypoints) * 1.4, 2)
        for admin_id in ADMIN_IDS:
            try:
                await message.bot.send_message(
                    admin_id,
                    f"⚠️ Маршрут #{route_id}: аномальний кілометраж скинуто.\n"
                    f"Збережено: {total_km:.1f} км (haversine×1.4)\n"
                    f"Підозрілих точок: {suspicious_count}/{len(waypoints)}",
                )
            except Exception:
                pass

    if not _is_silent_driver(message.from_user.id):
        try:
            await message.bot.send_location(GROUP_CHAT_ID, latitude=lat, longitude=lon)
            await message.bot.send_message(GROUP_CHAT_ID, f"🏁 {user_name} — Фініш")
        except Exception as e:
            logger.warning("Не вдалося надіслати фініш-геомітку в груповий чат: %s", e)

    start_dt = datetime.fromisoformat(start_time) if start_time else datetime.now()
    delta = datetime.now() - start_dt
    hours, rem = divmod(int(delta.total_seconds()), 3600)
    minutes = rem // 60

    await state.update_data(
        finish_total_km=total_km,
        finish_waypoint_count=len(waypoints),
        finish_duration=f"{hours}г {minutes}хв",
        finish_time=datetime.now().strftime('%H:%M %d.%m.%Y'),
        finish_end_time=now,
    )
    await state.set_state(OdometerState.waiting_for_finish_odometer)
    await message.answer(
        "✅ Фініш зафіксовано!\n\n"
        "🚗 Введіть поточний показник одометра (ціле число, км):\n"
        "Наприклад: 15800",
        reply_markup=kb_admin_driver_active() if is_adm else kb_driver_active(),
    )


@router.message(OdometerState.waiting_for_finish_odometer)
async def handle_finish_odometer(message: Message, state: FSMContext):
    data = await state.get_data()

    route_id      = data["finish_route_id"]
    total_km      = data["finish_total_km"]
    user_name     = data["finish_user_name"]
    wp_count      = data["finish_waypoint_count"]
    duration      = data["finish_duration"]
    time_str      = data["finish_time"]
    end_time      = data.get("finish_end_time", datetime.now().isoformat())
    is_adm        = data["finish_is_adm"]
    odometer_start = data.get("finish_odometer_start")

    text = (message.text or "").strip().replace(",", ".")
    odometer_km = None
    try:
        val = float(text)
        if val > 0:
            odometer_km = val
    except ValueError:
        pass

    if odometer_km is None:
        await message.answer(
            "⚠️ Одометр обов'язковий для завершення маршруту.\n"
            "Введіть поточний показник одометра (ціле число, км):\n"
            "Наприклад: 15800"
        )
        return  # стан залишається waiting_for_finish_odometer

    await state.clear()
    await end_route(route_id, end_time, total_km)
    await save_odometer(route_id, odometer_km)

    odo_section, should_alert = _format_odometer_accuracy(total_km, odometer_start, odometer_km)

    summary = (
        f"🏁 Маршрут #{route_id} завершено!\n\n"
        f"👤 {user_name}\n"
        f"📍 Точок: {wp_count}\n"
        f"⏱ Тривалість: {duration}\n"
        f"⏰ {time_str}\n\n"
        f"{odo_section}"
    )

    await message.answer(summary, reply_markup=kb_admin_driver_idle() if is_adm else kb_driver_idle())

    admin_msg = summary
    if should_alert:
        admin_msg += f"\n\n⚠️ Велика розбіжність по маршруту {user_name} — перевір!"

    for admin_id in ADMIN_IDS:
        try:
            await message.bot.send_message(admin_id, admin_msg)
        except Exception as e:
            logger.warning("Не вдалося надіслати фініш адміну %s: %s", admin_id, e)

    if not _is_silent_driver(message.from_user.id):
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

    if not route_id:
        await state.clear()
        return

    lat = message.location.latitude
    lon = message.location.longitude
    now = datetime.now().isoformat()
    await add_waypoint(route_id, lat, lon, "Старт", now, False)

    user = await get_user(message.from_user.id)
    if not _is_silent_driver(message.from_user.id):
        try:
            await message.bot.send_location(GROUP_CHAT_ID, latitude=lat, longitude=lon)
            await message.bot.send_message(GROUP_CHAT_ID, f"📍 {user['full_name']} — Старт")
        except Exception as e:
            logger.warning("Не вдалося надіслати старт-геомітку в груповий чат: %s", e)

    # Переходимо до запиту одометра (зберігаємо route_id і is_adm)
    await state.update_data(start_route_id=route_id, start_is_adm=is_adm)
    await state.set_state(WaypointState.waiting_for_start_odometer)
    await message.answer(
        "✅ Старт зафіксовано!\n\n"
        "🚗 Введіть поточний показник одометра (ціле число, км):\n"
        "Наприклад: 15420",
        reply_markup=kb_admin_driver_active() if is_adm else kb_driver_active(),
    )


@router.message(WaypointState.waiting_for_start_odometer)
async def handle_start_odometer_input(message: Message, state: FSMContext):
    data = await state.get_data()
    route_id = data.get("start_route_id")
    is_adm   = data.get("start_is_adm", False)

    if not route_id:
        await state.clear()
        return

    text = (message.text or "").strip().replace(",", ".")
    odometer_start = None
    try:
        val = float(text)
        if val > 0:
            odometer_start = val
    except ValueError:
        pass

    if odometer_start is None:
        await message.answer(
            "⚠️ Одометр обов'язковий для старту маршруту.\n"
            "Введіть поточний показник одометра (ціле число, км):\n"
            "Наприклад: 15420"
        )
        return  # стан залишається waiting_for_start_odometer

    await state.clear()
    await save_odometer_start(route_id, odometer_start)
    await message.answer(
        f"🚗 Одометр {odometer_start:.0f} км зафіксовано. Удачної дороги!",
        reply_markup=kb_admin_driver_active() if is_adm else kb_driver_active(),
    )


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

    user = await get_user(user_id)

    # РЕБ-спуфінг перевірка — порівнюємо з останньою валідною точкою
    last_wp = await get_last_valid_waypoint(route_id)
    if last_wp is None:
        last_wp = await get_last_waypoint(route_id)  # fallback: всі попередні підозрілі
    suspicious = False
    if last_wp:
        suspicious = await check_suspicious(
            last_wp["lat"], last_wp["lon"], last_wp["timestamp"],
            lat, lon, now,
            MAX_DISTANCE_KM, MIN_TIME_MINUTES,
            bot=message.bot,
            driver_name=user["full_name"],
            route_id=route_id,
            admin_ids=list(set(ADMIN_IDS + SUPER_ADMIN_IDS)),
        )

    await add_waypoint(route_id, lat, lon, point_name, now, suspicious)
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

    if not _is_silent_driver(user_id):
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

import logging
from datetime import datetime

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from bot.utils.keyboards import kb_driver_idle, kb_driver_active

from bot.config import ADMIN_IDS, GROUP_CHAT_ID, MAX_DISTANCE_KM, MIN_TIME_MINUTES
from bot.models.database import (
    add_waypoint,
    end_route,
    get_active_route,
    get_last_waypoint,
    get_route_waypoints,
    get_user,
    start_route,
)
from bot.utils.geo import calculate_route_distance
from bot.utils.geo import is_suspicious as check_suspicious

logger = logging.getLogger(__name__)
router = Router()


class WaypointState(StatesGroup):
    waiting_for_name = State()


# ── Auth helper ───────────────────────────────────────────────────────────────

async def _approved(user_id: int) -> bool:
    user = await get_user(user_id)
    return bool(user and user["is_approved"])


# ── Кнопки Reply Keyboard (дублюють команди) ─────────────────────────────────

@router.message(F.text == "🚀 Почати маршрут")
async def btn_start_route(message: Message):
    await cmd_start_route(message)

@router.message(F.text == "🏁 Завершити маршрут")
async def btn_end_route(message: Message):
    await cmd_end_route(message)


# ── /start_route ──────────────────────────────────────────────────────────────

@router.message(Command("start_route"))
async def cmd_start_route(message: Message):
    user_id = message.from_user.id

    if not await _approved(user_id):
        await message.answer("❌ Ви не авторизовані. Надішліть /start.")
        return

    if await get_active_route(user_id):
        await message.answer("⚠️ Активний маршрут вже є. Завершіть його: /end_route")
        return

    now = datetime.now().isoformat()
    route_id = await start_route(user_id, now)
    user = await get_user(user_id)

    await message.answer(
        f"🚀 Маршрут #{route_id} розпочато!\n"
        f"⏰ {datetime.now().strftime('%H:%M %d.%m.%Y')}\n\n"
        "Натисніть кнопку щоб надіслати геолокацію.",
        reply_markup=kb_driver_active(),
    )

    # Повідомити груповий чат про старт
    try:
        await message.bot.send_message(
            GROUP_CHAT_ID,
            f"🚀 Водій {user['full_name']} розпочав маршрут #{route_id}\n"
            f"⏰ {datetime.now().strftime('%H:%M %d.%m.%Y')}",
        )
    except Exception as e:
        logger.warning("Не вдалося надіслати старт в груповий чат: %s", e)


# ── /end_route ────────────────────────────────────────────────────────────────

@router.message(Command("end_route"))
async def cmd_end_route(message: Message):
    user_id = message.from_user.id

    if not await _approved(user_id):
        await message.answer("❌ Ви не авторизовані.")
        return

    active = await get_active_route(user_id)
    if not active:
        await message.answer("❌ Немає активного маршруту.")
        return

    waypoints = await get_route_waypoints(active["id"])
    total_km = calculate_route_distance(waypoints)
    now = datetime.now().isoformat()
    await end_route(active["id"], now, total_km)

    start_dt = datetime.fromisoformat(active["start_time"])
    delta = datetime.now() - start_dt
    hours, rem = divmod(int(delta.total_seconds()), 3600)
    minutes = rem // 60

    user = await get_user(user_id)
    summary = (
        f"🏁 Маршрут #{active['id']} завершено!\n\n"
        f"👤 {user['full_name']}\n"
        f"📍 Точок: {len(waypoints)}\n"
        f"🛣 Відстань: {total_km:.2f} км\n"
        f"⏱ Тривалість: {hours}г {minutes}хв\n"
        f"⏰ {datetime.now().strftime('%H:%M %d.%m.%Y')}"
    )

    await message.answer(summary, reply_markup=kb_driver_idle())

    # Сповістити адмінів про завершення маршруту
    for admin_id in ADMIN_IDS:
        try:
            await message.bot.send_message(admin_id, summary)
        except Exception as e:
            logger.warning("Не вдалося надіслати фініш адміну %s: %s", admin_id, e)


# ── Геолокація ────────────────────────────────────────────────────────────────

@router.message(F.location)
async def handle_location(message: Message, state: FSMContext):
    user_id = message.from_user.id

    if not await _approved(user_id):
        return

    if not await get_active_route(user_id):
        await message.answer("❌ Спочатку почніть маршрут: /start_route")
        return

    await state.update_data(
        pending_lat=message.location.latitude,
        pending_lon=message.location.longitude,
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
    await state.clear()

    if lat is None or lon is None:
        await message.answer("❌ Помилка: геолокація не знайдена. Надішліть знову.")
        return

    active = await get_active_route(user_id)
    if not active:
        await message.answer("❌ Немає активного маршруту.")
        return

    now = datetime.now().isoformat()

    # РЕБ-спуфінг перевірка
    last_wp = await get_last_waypoint(active["id"])
    suspicious = False
    if last_wp:
        suspicious = check_suspicious(
            last_wp["lat"], last_wp["lon"], last_wp["timestamp"],
            lat, lon, now,
            MAX_DISTANCE_KM, MIN_TIME_MINUTES,
        )

    await add_waypoint(active["id"], lat, lon, point_name, now, suspicious)

    user = await get_user(user_id)
    flag = "⚠️" if suspicious else "📍"

    await message.answer(
        f"{flag} {point_name}\n"
        f"📌 {lat:.5f}, {lon:.5f}\n"
        f"⏰ {datetime.now().strftime('%H:%M')}",
        reply_markup=kb_driver_active(),
    )

    # Дублювати в груповий чат
    group_text = (
        f"{flag} Водій: {user['full_name']}\n"
        f"📍 {point_name}\n"
        f"📌 {lat:.5f}, {lon:.5f}\n"
        f"⏰ {datetime.now().strftime('%H:%M %d.%m.%Y')}"
    )
    if suspicious:
        group_text += "\n\n⚠️ ПІДОЗРІЛА ГЕОМІТКА — можливий GPS-спуфінг!"

    try:
        await message.bot.send_message(GROUP_CHAT_ID, group_text)
    except Exception as e:
        logger.warning("Не вдалося надіслати в груповий чат %s: %s", GROUP_CHAT_ID, e)

    # Сповістити адмінів про підозрілу мітку
    if suspicious:
        alert = (
            f"🚨 ПІДОЗРІЛА ГЕОМІТКА!\n"
            f"👤 {user['full_name']} (ID: {user_id})\n"
            f"📍 {point_name}\n"
            f"📌 {lat:.5f}, {lon:.5f}\n"
            f"Маршрут #{active['id']}"
        )
        for admin_id in ADMIN_IDS:
            try:
                await message.bot.send_message(admin_id, alert)
            except Exception as e:
                logger.warning("Не вдалося сповістити адміна %s: %s", admin_id, e)

import logging
from datetime import datetime

from aiogram import Router, F
from bot.utils.time_utils import get_kyiv_time, to_kyiv_time
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

from bot.utils.keyboards import kb_driver_idle, kb_driver_active, kb_admin_driver_idle, kb_admin_driver_active

from bot.config import ADMIN_IDS, SUPER_ADMIN_IDS, GROUP_CHAT_ID, MAX_DISTANCE_KM, MIN_TIME_MINUTES, VIEWER_BASE_URL
from bot.models.database import (
    add_waypoint,
    end_route,
    get_active_route,
    get_last_n_waypoints,
    get_last_waypoint,
    get_last_valid_waypoint,
    get_route_waypoints,
    get_route_waypoints_from_last_start,
    get_todays_finished_route,
    get_todays_route,
    get_user,
    mark_waypoint_suspicious,
    reactivate_route,
    save_odometer,
    save_odometer_start,
    start_route,
)
from bot.services.diagnostics import diagnose_route
from bot.services.odometer_service import validate_finish_odometer, build_odo_start_alert, build_geo_mismatch_line
from bot.services.route_comment_service import get_route_comment
from bot.utils.geo import get_road_distance_for_route, get_cached_polyline
from bot.utils.geo import is_spike
from bot.utils.geo import is_suspicious as check_suspicious
from bot.utils.keyboards import kb_route_correction

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
    round_pct: bool = False,
) -> tuple:
    """Повертає (текст_секції, потрібен_алерт).

    Обробляє 5 сценаріїв наявності/відсутності одометрових даних.
    Алерт = True тільки в сценарії 1 (обидва введено, diff > 0) при похибці > 25%.
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
        if diff_pct <= 5:
            label = "✅"
        elif diff_pct <= 12:
            label = "🔶"
        else:
            label = "🔴"
        pct_str = f"{int(round(diff_pct))}%" if round_pct else f"{diff_pct:.1f}%"
        text = (
            f"📌 Одометр: {odometer_start:.0f} → {odometer_km:.0f} км\n"
            f"   Пробіг за одометром: {odometer_diff:.1f} км\n"
            f"   Трекінг: {total_km:.2f} км\n"
            f"   Похибка: {pct_str}  {label}"
        )
        return text, diff_pct > 25

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
        route_id = todays_route["id"]
        now_dt = get_kyiv_time()
        finish_dt = (
            to_kyiv_time(datetime.fromisoformat(todays_route["end_time"]))
            if todays_route.get("end_time")
            else now_dt
        )
        time_finish = finish_dt.strftime("%H:%M")
        _confirm_kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text=f"▶️ Продовжити маршрут #{route_id}",
                callback_data=f"continue_route:{route_id}",
            )
        ]])
        await message.answer(
            f"🔄 Сьогодні вже є маршрут #{route_id}, завершений о {time_finish}.\n"
            f"Натисни кнопку щоб продовжити його.",
            reply_markup=_confirm_kb,
        )
        return
    else:
        # Новий маршрут
        now = get_kyiv_time().isoformat()
        route_id = await start_route(user_id, now)
        label = f"🚀 Маршрут #{route_id} розпочато!"
        group_label = f"🚀 Водій {user['full_name']} розпочав маршрут #{route_id}"
        group_time_suffix = f"\n⏰ {get_kyiv_time().strftime('%H:%M %d.%m.%Y')}"

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
        f"⏰ {get_kyiv_time().strftime('%H:%M %d.%m.%Y')}\n\n"
        "📍 Надішли своє місцезнаходження для фіксації старту маршруту.",
        reply_markup=kb_admin_driver_active() if is_adm else kb_driver_active(),
    )


# ── Callback: підтвердження продовження маршруту ─────────────────────────────

@router.callback_query(F.data.startswith("continue_route:"))
async def callback_continue_route(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id

    if not await _approved(user_id):
        await callback.answer("❌ Ви не авторизовані.", show_alert=True)
        return

    if await get_active_route(user_id):
        await callback.answer("⚠️ Маршрут вже активний.", show_alert=True)
        return

    try:
        route_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        await callback.answer("❌ Невірні дані.", show_alert=True)
        return

    todays_route = await get_todays_finished_route(user_id)
    if not todays_route or todays_route["id"] != route_id:
        await callback.answer("❌ Маршрут не знайдено або вже активний.", show_alert=True)
        return

    user = await get_user(user_id)
    is_adm = user_id in ADMIN_IDS or user_id in SUPER_ADMIN_IDS

    await reactivate_route(route_id)

    now_dt = get_kyiv_time()
    finish_dt = (
        to_kyiv_time(datetime.fromisoformat(todays_route["end_time"]))
        if todays_route.get("end_time")
        else now_dt
    )
    time_finish = finish_dt.strftime("%H:%M")
    time_restart = now_dt.strftime("%H:%M")
    date_str = now_dt.strftime("%d.%m.%Y")
    duration_min = max(0, int((now_dt - finish_dt).total_seconds() / 60))

    group_label = (
        f"🔄 Маршрут {user['full_name']} поновлено після перерви\n"
        f"⏸ Перерва з {time_finish} до {time_restart}\n"
        f"⏱ Тривалість перерви: {duration_min} хв\n"
        f"🕐 {time_restart} {date_str}"
    )
    if not _is_silent_driver(user_id):
        try:
            await callback.bot.send_message(GROUP_CHAT_ID, group_label)
        except Exception as e:
            logger.warning("Не вдалося надіслати продовження в груповий чат: %s", e)

    await state.update_data(start_route_id=route_id, start_is_adm=is_adm)
    await state.set_state(WaypointState.waiting_for_start_location)

    await callback.message.edit_text(
        f"▶️ Маршрут #{route_id} продовжено!\n"
        f"⏰ {now_dt.strftime('%H:%M %d.%m.%Y')}\n\n"
        "📍 Надішли своє місцезнаходження для фіксації старту маршруту.",
    )
    await callback.message.answer(
        "📍 Надішли своє місцезнаходження:",
        reply_markup=kb_admin_driver_active() if is_adm else kb_driver_active(),
    )
    await callback.answer()


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
    now = get_kyiv_time().isoformat()
    await add_waypoint(route_id, lat, lon, "Фініш", now, False)

    # Розрахунок кілометражу (включно з точкою Фінішу)
    waypoints = await get_route_waypoints_from_last_start(route_id)
    valid = [wp for wp in waypoints if not wp.get("is_suspicious")]
    total_km = await get_road_distance_for_route(waypoints)
    if total_km > 1000:
        from bot.utils.geo import calculate_route_distance
        suspicious_count = sum(1 for wp in waypoints if wp.get("is_suspicious"))
        logger.warning(
            "Маршрут #%s: аномальний km=%.2f (підозрілих %d/%d) — fallback haversine×1.4",
            route_id, total_km, suspicious_count, len(waypoints),
        )
        total_km = round(calculate_route_distance(valid if valid else waypoints) * 1.4, 2)
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

    start_dt = datetime.fromisoformat(start_time) if start_time else get_kyiv_time()
    delta = get_kyiv_time() - to_kyiv_time(start_dt)
    hours, rem = divmod(int(delta.total_seconds()), 3600)
    minutes = rem // 60

    _now_kyiv = get_kyiv_time()
    _start_hm = to_kyiv_time(start_dt).strftime('%H:%M') if start_time else _now_kyiv.strftime('%H:%M')
    # Фікс 3: перерахунок з урахуванням suspicious точок перед збереженням у FSM
    waypoints_fresh = await get_route_waypoints_from_last_start(route_id)
    valid_fresh = [wp for wp in waypoints_fresh if not wp.get("is_suspicious")]
    if len(valid_fresh) >= 2:
        total_km = await get_road_distance_for_route(valid_fresh)
    _cached_polyline = get_cached_polyline(valid_fresh if len(valid_fresh) >= 2 else waypoints_fresh)
    await state.update_data(
        finish_total_km=total_km,
        finish_waypoint_count=len(waypoints),
        finish_duration=f"{hours}г {minutes}хв",
        finish_start_hm=_start_hm,
        finish_hm=_now_kyiv.strftime('%H:%M'),
        finish_date=_now_kyiv.strftime('%d.%m.%Y'),
        finish_end_time=now,
        finish_polyline=_cached_polyline,
    )
    await state.set_state(OdometerState.waiting_for_finish_odometer)
    await message.answer(
        "✅ Фініш зафіксовано!\n\n"
        "🚗 Введіть поточний показник одометра (ціле число, км):\n"
        "Наприклад: 15800",
        reply_markup=kb_admin_driver_active() if is_adm else kb_driver_active(),
    )


@router.message(OdometerState.waiting_for_finish_odometer)
async def handle_finish_odometer(message: Message, state: FSMContext, pg_pool=None):
    data = await state.get_data()

    route_id      = data["finish_route_id"]
    total_km      = data["finish_total_km"]
    user_name     = data["finish_user_name"]
    wp_count      = data["finish_waypoint_count"]
    duration      = data["finish_duration"]
    start_hm      = data["finish_start_hm"]
    finish_hm     = data["finish_hm"]
    finish_date   = data["finish_date"]
    end_time      = data.get("finish_end_time", get_kyiv_time().isoformat())
    is_adm        = data["finish_is_adm"]
    odometer_start = data.get("finish_odometer_start")
    polyline_str  = data.get("finish_polyline")

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

    if odometer_start is not None:
        error_msg = validate_finish_odometer(odometer_start, odometer_km)
        if error_msg:
            await message.answer(error_msg)
            return

    await state.clear()

    # Правила 2.4/3.1 — РЕБ/spoofing діагностика при ручному закритті
    # Тригер: is_suspicious > 20% АБО max_speed > 150 → diagnose_route повертає 'reb'
    # Рішення по одометру приймає P2 автоматично — кнопка "Прийняти одометр" в P1 відсутня
    _diag = await diagnose_route(route_id)
    if _diag['diagnosis'] == 'reb':
        _diag_text = (
            f"🔴 РЕБ/споофінг виявлено — маршрут #{route_id}\n"
            f"👤 {user_name} | {get_kyiv_time().strftime('%d.%m.%Y')}\n\n"
            f"📊 Трекінг: {total_km:.2f} км\n\n"
            f"🔍 Діагноз: РЕБ-спуфінг (ймовірний)\n"
            + "\n".join(_diag["indicators"])
            + "\n\nЩо робити:"
        )
        _kb = kb_route_correction(route_id)
        for _admin_id in list(set(ADMIN_IDS + SUPER_ADMIN_IDS)):
            try:
                await message.bot.send_message(_admin_id, _diag_text, reply_markup=_kb)
            except Exception as exc:
                logger.warning("Не вдалося надіслати діагностику адміну %d: %s", _admin_id, exc)

    await end_route(route_id, end_time, total_km)
    try:
        if polyline_str:
            from bot.models.database import update_route_polyline
            await update_route_polyline(route_id, polyline_str)
    except Exception as _e:
        logger.warning("polyline save failed for route %d: %s", route_id, _e)
    await save_odometer(route_id, odometer_km)

    # P2 hook — розрахунок вартості логістики
    # Не змінює логіку P1. Якщо P2 впаде — P1 продовжує працювати.
    try:
        from bot.services.route_cost_service import on_route_finished, get_driver_type
        from bot.services.coefficients_service import CoefficientsService

        _driver_type = get_driver_type(message.from_user.id)
        _tracking_km = float(total_km) if total_km else 0.0
        _odo_delta = None
        if odometer_km and odometer_start and odometer_km > odometer_start:
            _odo_delta = float(odometer_km - odometer_start)

        if pg_pool:
            _coeffs_svc = CoefficientsService(pg_pool)
            _coefficients = await _coeffs_svc.get()
            await on_route_finished(
                route_id=route_id,
                driver_id=message.from_user.id,
                driver_type=_driver_type,
                tracking_km=_tracking_km,
                odometer_km=_odo_delta,
                driver_name=user_name,
                coefficients=_coefficients,
                pg_pool=pg_pool,
                bot=message.bot,
            )
    except Exception as _e:
        logger.warning("P2 route cost hook failed: %s", _e)

    odo_section_driver, should_alert = _format_odometer_accuracy(
        total_km, odometer_start, odometer_km, round_pct=True
    )
    odo_section_admin, _ = _format_odometer_accuracy(total_km, odometer_start, odometer_km)

    _odo_diff = None
    if odometer_km is not None and odometer_start is not None and odometer_km > odometer_start:
        _odo_diff = odometer_km - odometer_start
    _comment = get_route_comment(user_name, _odo_diff, total_km)

    _base = (
        f"🏁 Маршрут #{route_id} завершено!\n\n"
        f"👤 {user_name}\n"
        f"📍 Точок: {wp_count}\n"
        f"⏱ Тривалість: {duration}\n"
        f"🕐 {start_hm} → {finish_hm}  {finish_date}\n\n"
    )
    summary = _base + odo_section_driver        # водій + загальний чат
    admin_summary = _base + odo_section_admin   # адміни

    if _comment:
        summary += f"\n\n{_comment}"
        admin_summary += f"\n\n{_comment}"

    await message.answer(summary, reply_markup=kb_admin_driver_idle() if is_adm else kb_driver_idle())

    admin_msg = admin_summary
    if should_alert:
        admin_msg += f"\n\n⚠️ Велика розбіжність по маршруту {user_name} — перевір!"

    _kb_row = [InlineKeyboardButton(text="🔍 Деталі маршруту", callback_data=f"route_detail:{route_id}")]
    if VIEWER_BASE_URL:
        _kb_row.append(InlineKeyboardButton(text="🗺 Карта", url=f"{VIEWER_BASE_URL}/route/{route_id}"))
    _detail_kb = InlineKeyboardMarkup(inline_keyboard=[_kb_row])
    for admin_id in ADMIN_IDS:
        try:
            kb = _detail_kb if admin_id in SUPER_ADMIN_IDS else None
            await message.bot.send_message(admin_id, admin_msg, reply_markup=kb)
        except Exception as e:
            logger.warning("Не вдалося надіслати фініш адміну %s: %s", admin_id, e)

    for super_id in SUPER_ADMIN_IDS:
        if super_id not in ADMIN_IDS:
            try:
                await message.bot.send_message(super_id, admin_msg, reply_markup=_detail_kb)
            except Exception as e:
                logger.warning("Не вдалося надіслати фініш супер-адміну %s: %s", super_id, e)

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
    now = get_kyiv_time().isoformat()
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

    try:
        alert = await build_odo_start_alert(message.from_user.id, odometer_start)
        geo_line, cheat_alert = await build_geo_mismatch_line(route_id, odometer_start, message.from_user.id)
        if alert and geo_line:
            alert += geo_line
        if alert:
            for _aid in list(set(ADMIN_IDS + SUPER_ADMIN_IDS)):
                if _aid != message.from_user.id:
                    try:
                        await message.bot.send_message(_aid, alert)
                    except Exception:
                        pass
        if cheat_alert:
            for _sid in SUPER_ADMIN_IDS:
                if _sid != message.from_user.id:
                    try:
                        await message.bot.send_message(_sid, cheat_alert)
                    except Exception:
                        pass
    except Exception as _e:
        logger.warning("Odo start comparison failed: %s", _e)

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

    now = get_kyiv_time().isoformat()

    user = await get_user(user_id)

    # РЕБ-спуфінг перевірка — порівнюємо з останньою валідною точкою
    last_wp = await get_last_valid_waypoint(route_id)
    if last_wp is None:
        last_wp = await get_last_waypoint(route_id)  # fallback: всі попередні підозрілі
    suspicious = False
    if last_wp:
        # Правило 1.1 + геозони (без Level 2 — його обробляє ping-флоу нижче)
        suspicious = await check_suspicious(
            last_wp["lat"], last_wp["lon"], last_wp["timestamp"],
            lat, lon, now,
            MAX_DISTANCE_KM, MIN_TIME_MINUTES,
            bot=message.bot,
            driver_name=user["full_name"],
            route_id=route_id,
            admin_ids=list(set(ADMIN_IDS + SUPER_ADMIN_IDS)),
            skip_level2=True,
        )

    await add_waypoint(route_id, lat, lon, point_name, now, suspicious)

    # GPS spike (правило 1.6): ретроспективно перевіряємо попередню точку B
    # Логіка: щойно збережена точка = C; якщо dist(A,B)>20 і dist(B,C)<dist(A,B)*0.3 → B spike
    last3 = await get_last_n_waypoints(route_id, 3)
    if len(last3) == 3:
        wp_a, wp_b, wp_c = last3
        if not wp_b["is_suspicious"] and is_spike(
            wp_a["lat"], wp_a["lon"],
            wp_b["lat"], wp_b["lon"],
            wp_c["lat"], wp_c["lon"],
        ):
            await mark_waypoint_suspicious(wp_b["id"])
            logger.info("GPS spike: waypoint id=%d (route=%d) позначено як suspicious", wp_b["id"], route_id)

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

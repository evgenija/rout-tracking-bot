import logging
from datetime import datetime, timedelta

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery

from bot.config import ADMIN_IDS, SUPER_ADMIN_IDS, COMPANY_NAME
from bot.models.database import (
    delete_user,
    get_all_users,
    get_all_routes_with_stats,
    get_daily_stats,
    get_weekly_stats,
    get_weekly_stats_by_day,
    flag_suspicious_waypoints_retroactive,
    recalculate_all_route_distances,
    search_drivers_by_query,
)
from bot.utils.geo import format_duration
from bot.utils.keyboards import kb_admin_main, kb_admin_driver_idle, kb_drivers_menu, kb_reports_menu

logger = logging.getLogger(__name__)
router = Router()


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS or user_id in SUPER_ADMIN_IDS


# ── FSM ───────────────────────────────────────────────────────────────────────

class RemoveDriverState(StatesGroup):
    waiting_for_query   = State()
    waiting_for_confirm = State()


# ── Reply keyboard: головне меню ──────────────────────────────────────────────

@router.message(F.text == "🚗 Режим водія")
async def btn_driver_mode(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer("🚗 Режим водія. Можна починати маршрут.", reply_markup=kb_admin_driver_idle())


@router.message(F.text == "◀️ Повернутися до адмін меню")
async def btn_back_to_admin(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer("Адмін меню:", reply_markup=kb_admin_main())


@router.message(F.text == "📊 Звіти")
async def btn_reports(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer("📊 Оберіть звіт:", reply_markup=kb_reports_menu())


@router.message(F.text == "🚗 Водії")
async def btn_drivers(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer("🚗 Управління водіями:", reply_markup=kb_drivers_menu())


@router.message(F.text == "💰 Фін модель")
async def btn_finance(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer("💰 Фінансова модель — в розробці.")


# ── Inline callbacks: звіти ───────────────────────────────────────────────────

@router.callback_query(F.data == "rpt:daily")
async def cb_daily(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Недостатньо прав.", show_alert=True)
        return
    await callback.answer()

    today = datetime.now().date().isoformat()
    stats = await get_daily_stats(today)

    if not stats:
        await callback.message.answer(f"📊 Щоденний звіт за {today}\n\nНемає активних маршрутів.")
        return

    lines = [f"📊 Щоденний звіт за {today}\n"]
    for s in stats:
        duration = format_duration(s["first_start"], s["last_end"])
        lines.append(
            f"👤 {s['full_name']}\n"
            f"   🛣 {s['total_km']:.1f} км | {s['waypoint_count']} точок\n"
            f"   ⏱ {duration}"
        )
    await callback.message.answer("\n\n".join(lines))


@router.callback_query(F.data == "rpt:weekly")
async def cb_weekly(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Недостатньо прав.", show_alert=True)
        return
    await callback.answer()

    today      = datetime.now().date()
    week_start = (today - timedelta(days=today.weekday())).isoformat()
    week_end   = today.isoformat()
    stats      = await get_weekly_stats(week_start, week_end)

    # Diagnostic: per-driver per-day breakdown
    day_breakdown = await get_weekly_stats_by_day(week_start, week_end)
    by_driver: dict[str, list] = {}
    for row in day_breakdown:
        by_driver.setdefault(row["full_name"], []).append(row)
    for drv, days in by_driver.items():
        total_km  = sum(d["km"] for d in days)
        total_pts = sum(d["waypoint_count"] for d in days)
        day_parts = ", ".join(
            f"{d['day']}={d['km']:.1f}km/{d['waypoint_count']}pts({d['route_count']}routes)"
            for d in days
        )
        logger.info("[weekly] %s: %s | total=%.1fkm/%dpts", drv, day_parts, total_km, total_pts)

    if not stats:
        await callback.message.answer(f"📊 Тижневий звіт ({week_start} — {week_end})\n\nНемає даних.")
        return

    lines = [f"📊 Тижневий звіт ({week_start} — {week_end})\n"]
    grand_total = 0.0
    for s in stats:
        km = s["total_km"] or 0.0
        wp = s["waypoint_count"] or 0
        lines.append(
            f"👤 {s['full_name']}\n"
            f"🛣 {km:.1f} км | {wp} точок"
        )
        grand_total += km
    lines.append(f"─────────────────\n🏁 Grand Total: {grand_total:.1f} км")
    await callback.message.answer("\n\n".join(lines))


# ── Inline callbacks: водії ───────────────────────────────────────────────────

@router.callback_query(F.data == "drv:list")
async def cb_drivers_list(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Недостатньо прав.", show_alert=True)
        return
    await callback.answer()

    users    = await get_all_users()
    approved = [u for u in users if u["is_approved"]]

    if not approved:
        await callback.message.answer("👥 Немає авторизованих водіїв.")
        return

    lines = ["✅ Авторизовані водії:\n"]
    for u in approved:
        tag = f" @{u['username']}" if u["username"] else ""
        lines.append(f"  • {u['full_name']}{tag} — {u['telegram_id']}")
    await callback.message.answer("\n".join(lines))


@router.callback_query(F.data == "drv:pending")
async def cb_drivers_pending(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Недостатньо прав.", show_alert=True)
        return
    await callback.answer()

    users   = await get_all_users()
    pending = [u for u in users if not u["is_approved"]]

    if not pending:
        await callback.message.answer("✅ Немає запитів на авторизацію.")
        return

    lines = ["⏳ Очікують авторизації:\n"]
    for u in pending:
        tag = f" @{u['username']}" if u["username"] else ""
        lines.append(f"  • {u['full_name']}{tag} — {u['telegram_id']}")
    await callback.message.answer("\n".join(lines))


@router.callback_query(F.data == "drv:remove")
async def cb_drivers_remove(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Недостатньо прав.", show_alert=True)
        return
    await callback.answer()

    users    = await get_all_users()
    approved = [u for u in users if u["is_approved"]]

    if not approved:
        await callback.message.answer("Немає активних водіїв.")
        return

    lines = ["Активні водії:\n"]
    for u in approved:
        lines.append(f"  {u['full_name']} — {u['telegram_id']}")
    lines.append("\nВведіть ID або частину імені водія:\n(/cancel — скасувати)")

    await callback.message.answer("\n".join(lines))
    await state.set_state(RemoveDriverState.waiting_for_query)


# ── FSM: видалення водія ──────────────────────────────────────────────────────

@router.message(RemoveDriverState.waiting_for_query)
async def handle_remove_query(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return

    query   = message.text.strip()
    matches = await search_drivers_by_query(query)

    if not matches:
        await message.answer("❌ Водія не знайдено. Спробуйте ще раз або /cancel.")
        return

    if len(matches) == 1:
        user = matches[0]
        await state.update_data(target_id=user["telegram_id"], target_name=user["full_name"])
        await state.set_state(RemoveDriverState.waiting_for_confirm)
        await message.answer(
            f"Видалити {user['full_name']} (ID: {user['telegram_id']})?\n\n"
            "Введіть ТАК для підтвердження або /cancel."
        )
    else:
        lines = ["Знайдено кількох — уточніть запит або введіть точний ID:\n"]
        for u in matches:
            lines.append(f"  {u['full_name']} — {u['telegram_id']}")
        await message.answer("\n".join(lines))


@router.message(RemoveDriverState.waiting_for_confirm)
async def handle_remove_confirm(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return

    if message.text.strip().upper() != "ТАК":
        await state.clear()
        await message.answer("❌ Скасовано.", reply_markup=kb_admin_main())
        return

    data        = await state.get_data()
    target_id   = data["target_id"]
    target_name = data["target_name"]
    await state.clear()

    await delete_user(target_id)
    await message.answer(
        f"✅ {target_name} (ID: {target_id}) видалено.",
        reply_markup=kb_admin_main(),
    )

    try:
        await message.bot.send_message(target_id, f"❌ Вас видалено з системи {COMPANY_NAME}.")
    except Exception:
        pass


@router.message(Command("fix_anomalies"))
async def cmd_fix_anomalies(message: Message):
    """Ретроактивно фіксує аномальні GPS-точки і перераховує кілометраж."""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Недостатньо прав.")
        return

    await message.answer("🔍 Сканую геомітки на аномалії...")

    flag_result = await flag_suspicious_waypoints_retroactive()
    recalc_result = await recalculate_all_route_distances()

    # Повний звіт по маршрутах
    routes = await get_all_routes_with_stats()
    lines = [
        f"✅ Діагностика завершена\n",
        f"🚨 Помічено підозрілих геоміток: {flag_result['flagged']}",
        f"🛣 Маршрутів з аномаліями: {flag_result['routes_affected']}",
        f"🔄 Перераховано маршрутів: {recalc_result['recalculated']}",
        f"🏁 Виправлено аномальних км: {recalc_result['anomalies_fixed']}\n",
        "📋 Всі маршрути:",
    ]
    for r in routes:
        status = "⚠️" if (r["suspicious_count"] or 0) > 0 else "✅"
        name = r["full_name"] or f"ID:{r['driver_id']}"
        lines.append(
            f"{status} {name} | {r['total_km']:.1f} км | "
            f"{r['waypoint_count']} точок ({r['suspicious_count'] or 0} підозр.) | "
            f"{(r['start_time'] or '')[:10]}"
        )

    await message.answer("\n".join(lines))


@router.message(Command("recalculate_today"))
async def cmd_recalculate_today(message: Message):
    """Перераховує кілометраж сьогоднішніх маршрутів через Google Directions API."""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Недостатньо прав.")
        return

    today = datetime.now().date().isoformat()
    await message.answer(f"🔄 Перераховую маршрути за {today} через Google API...")

    result = await recalculate_all_route_distances(today)

    from bot.utils.geo import get_api_call_count
    lines = [
        f"✅ Перерахунок завершено за {today}",
        f"🔄 Оновлено маршрутів: {result['recalculated']}",
        f"🚨 Виправлено аномальних: {result['anomalies_fixed']}",
        f"📡 Всього API-запитів: {get_api_call_count()}",
    ]
    await message.answer("\n".join(lines))


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    current = await state.get_state()
    if current and "RemoveDriverState" in current:
        await state.clear()
        await message.answer("❌ Скасовано.", reply_markup=kb_admin_main())

# bot/handlers/route_detail_handler.py
# Три точки входу до route_detail_service:
#   2а. Callback кнопки [🔍 Деталі маршруту] — тільки super-admin
#   2б. Команда /route_detail [id]            — будь-який адмін
#   2в. Команда /routes                       — тільки super-admin

import logging

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)

from bot.config import ADMIN_IDS, SUPER_ADMIN_IDS
from bot.services.route_detail_service import (
    get_route_detail,
    get_recent_routes,
    format_route_detail_message,
)

logger = logging.getLogger(__name__)
route_detail_router = Router()


def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS or user_id in SUPER_ADMIN_IDS


def _is_super_admin(user_id: int) -> bool:
    return user_id in SUPER_ADMIN_IDS


# ── 2а. Callback — кнопка [🔍 Деталі маршруту] ───────────────────────────────

@route_detail_router.callback_query(F.data.startswith("route_detail:"))
async def handle_route_detail_callback(callback: CallbackQuery):
    if not _is_super_admin(callback.from_user.id):
        await callback.answer("Доступ тільки для супер-адміна.", show_alert=True)
        return

    try:
        route_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        await callback.answer("Невірний формат.", show_alert=True)
        return

    await callback.answer()

    detail = await get_route_detail(route_id)
    if detail is None:
        await callback.message.answer(f"Маршрут #{route_id} не знайдено.")
        return

    text = format_route_detail_message(
        route           = detail["route_info"],
        driver_name     = detail["driver_name"],
        segments        = detail["segments"],
        total_waypoints = detail["total_waypoints"],
    )
    await callback.message.answer(text, parse_mode="HTML")


# ── 2б. /route_detail [id] — резервний варіант ───────────────────────────────

@route_detail_router.message(Command("route_detail"))
async def cmd_route_detail(message: Message):
    # Доступ: будь-який адмін.
    # Щоб обмежити тільки super-admin — замінити _is_admin на _is_super_admin
    if not _is_admin(message.from_user.id):
        return

    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2 or not args[1].strip().isdigit():
        await message.answer(
            "Використання: /route_detail [route_id]\n"
            "Приклад: /route_detail 42\n\n"
            "Список маршрутів за 7 днів: /routes"
        )
        return

    route_id = int(args[1].strip())
    detail   = await get_route_detail(route_id)

    if detail is None:
        await message.answer(f"Маршрут #{route_id} не знайдено.")
        return

    text = format_route_detail_message(
        route           = detail["route_info"],
        driver_name     = detail["driver_name"],
        segments        = detail["segments"],
        total_waypoints = detail["total_waypoints"],
    )
    await message.answer(text, parse_mode="HTML")


# ── 2в. /routes — список за 7 днів з кнопками ────────────────────────────────

@route_detail_router.message(Command("routes"))
async def cmd_routes(message: Message):
    # Доступ: тільки super-admin
    if not _is_super_admin(message.from_user.id):
        return

    routes = await get_recent_routes(days=7)

    if not routes:
        await message.answer("📋 Маршрутів за останні 7 днів не знайдено.")
        return

    await message.answer("📋 Маршрути за 7 днів\n")

    for r in routes:
        name     = r.get("full_name") or f"Водій #{r['driver_id']}"
        date     = (r.get("date") or "")[:10]
        km       = r.get("total_km") or 0.0
        route_id = r["id"]

        text = f"{name} · {date} · {km:.1f} км"
        kb   = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🔍", callback_data=f"route_detail:{route_id}")
        ]])
        await message.answer(text, reply_markup=kb)

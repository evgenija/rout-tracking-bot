# bot/handlers/ping_handler.py
# UI для ping-флоу. Логіка — тільки в ping_service.

from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from bot.services.ping_service import record_ping_response

ping_router = Router()


def build_ping_keyboard(waypoint_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="✅ Так, їду",
            callback_data=f"ping_driving:{waypoint_id}"
        ),
        InlineKeyboardButton(
            text="📍 Зупинився",
            callback_data=f"ping_stopped:{waypoint_id}"
        )
    ]])


@ping_router.callback_query(F.data.startswith("ping_driving:"))
async def handle_ping_driving(callback: CallbackQuery):
    waypoint_id = int(callback.data.split(":")[1])
    record_ping_response(waypoint_id, 'driving')
    await callback.message.edit_text("✅ Дякуємо, продовжуйте маршрут")
    await callback.answer()


@ping_router.callback_query(F.data.startswith("ping_stopped:"))
async def handle_ping_stopped(callback: CallbackQuery):
    waypoint_id = int(callback.data.split(":")[1])
    record_ping_response(waypoint_id, 'stopped')
    await callback.message.edit_text("📍 Зрозуміло. Не забудьте поставити геомітку при відновленні маршруту.")
    await callback.answer()

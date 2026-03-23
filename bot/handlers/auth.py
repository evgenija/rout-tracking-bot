import logging
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from bot.config import ADMIN_IDS, SUPER_ADMIN_IDS, COMPANY_NAME, WELCOME_MESSAGE
from bot.models.database import get_user, create_user, approve_user, delete_user

logger = logging.getLogger(__name__)
router = Router()


# ── Helpers ───────────────────────────────────────────────────────────────────

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS or user_id in SUPER_ADMIN_IDS


def is_super_admin(user_id: int) -> bool:
    return user_id in SUPER_ADMIN_IDS


def _approval_kb(driver_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Підтвердити", callback_data=f"approve:{driver_id}"),
        InlineKeyboardButton(text="❌ Відхилити",  callback_data=f"reject:{driver_id}"),
    ]])


async def _notify_admins(bot: Bot, text: str, driver_id: int):
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, reply_markup=_approval_kb(driver_id))
        except Exception as e:
            logger.warning("Не вдалося сповістити адміна %s: %s", admin_id, e)


# ── /start ────────────────────────────────────────────────────────────────────

@router.message(Command("start"))
async def cmd_start(message: Message):
    user_id   = message.from_user.id
    username  = message.from_user.username or ""
    full_name = message.from_user.full_name or f"User_{user_id}"

    logger.info("/start від user_id=%s username=%s is_admin=%s", user_id, username, is_admin(user_id))

    # Визначаємо роль
    if is_super_admin(user_id):
        role = "driver,admin,super_admin"
    elif is_admin(user_id):
        role = "driver,admin"
    else:
        role = "driver"

    existing = await get_user(user_id)
    logger.info("existing user: %s", existing)

    # Вже авторизований
    if existing and existing["is_approved"]:
        cmds = "/start_route — почати маршрут\n/end_route — завершити маршрут"
        if is_admin(user_id):
            cmds += "\n/report — звіт за сьогодні\n/weekly — тижневий звіт\n/remove — видалити водія"
        if is_super_admin(user_id):
            cmds += "\n/finance — фінансова модель"
        await message.answer(f"👋 З поверненням, {full_name}!\n\n{cmds}")
        return

    if not existing:
        await create_user(user_id, username, full_name, role)

    # Адміни авторизуються автоматично
    if is_admin(user_id):
        await approve_user(user_id)
        logger.info("Sending admin welcome to user_id=%s", user_id)
        await message.answer(
            WELCOME_MESSAGE.format(company=COMPANY_NAME) + "\n\n"
            f"👋 {full_name}, ви авторизовані як адмін.\n\n"
            "/report — звіт за сьогодні\n"
            "/weekly — тижневий звіт\n"
            "/remove [telegram_id] — видалити водія"
        )
        return

    # Звичайний водій — очікує підтвердження
    await message.answer(
        f"👋 Вітаємо!\n"
        f"Ваш запит на доступ до {COMPANY_NAME} надіслано адміністратору.\n"
        f"Очікуйте підтвердження."
    )
    await _notify_admins(
        message.bot,
        f"🔔 Новий запит на авторизацію:\n"
        f"👤 {full_name}\n"
        f"🆔 {user_id}\n"
        f"@{username}",
        user_id,
    )


# ── Callbacks ─────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("approve:"))
async def cb_approve(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Недостатньо прав.", show_alert=True)
        return

    driver_id = int(callback.data.split(":")[1])
    await approve_user(driver_id)
    await callback.message.edit_text(callback.message.text + "\n\n✅ Авторизовано")
    await callback.answer("Водія авторизовано.")

    try:
        await callback.bot.send_message(
            driver_id,
            f"✅ Доступ підтверджено! Ви авторизовані в {COMPANY_NAME}.\n\n"
            "/start_route — почати маршрут\n/end_route — завершити маршрут",
        )
    except Exception as e:
        logger.warning("Не вдалося сповістити водія %s: %s", driver_id, e)


@router.callback_query(F.data.startswith("reject:"))
async def cb_reject(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Недостатньо прав.", show_alert=True)
        return

    driver_id = int(callback.data.split(":")[1])
    await delete_user(driver_id)
    await callback.message.edit_text(callback.message.text + "\n\n❌ Відхилено")
    await callback.answer("Запит відхилено.")

    try:
        await callback.bot.send_message(driver_id, f"❌ Ваш запит на доступ до {COMPANY_NAME} відхилено.")
    except Exception:
        pass


# ── /remove ───────────────────────────────────────────────────────────────────

@router.message(Command("remove"))
async def cmd_remove(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Недостатньо прав.")
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Використання: /remove [telegram_id]")
        return

    try:
        target_id = int(parts[1].strip())
    except ValueError:
        await message.answer("❌ Невірний формат ID.")
        return

    user = await get_user(target_id)
    if not user:
        await message.answer("❌ Користувача не знайдено.")
        return

    await delete_user(target_id)
    await message.answer(f"✅ {user['full_name']} (ID: {target_id}) видалено.")

    try:
        await message.bot.send_message(target_id, f"❌ Вас видалено з системи {COMPANY_NAME}.")
    except Exception:
        pass


# ── /finance (super-admin заглушка) ──────────────────────────────────────────

@router.message(Command("finance"))
async def cmd_finance(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Доступ лише для супер-адмінів.")
        return
    await message.answer("💰 Фінансова модель — в розробці.")

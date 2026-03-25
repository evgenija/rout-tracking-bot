from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)


# ── Driver keyboards ──────────────────────────────────────────────────────────

def kb_driver_idle() -> ReplyKeyboardMarkup:
    """Клавіатура водія без активного маршруту."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🚀 Почати маршрут")]],
        resize_keyboard=True,
    )


def kb_driver_active() -> ReplyKeyboardMarkup:
    """Клавіатура водія під час активного маршруту."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📍 Надіслати геолокацію", request_location=True)],
            [KeyboardButton(text="🏁 Завершити маршрут")],
        ],
        resize_keyboard=True,
    )


# ── Admin keyboards ───────────────────────────────────────────────────────────

def kb_admin_main() -> ReplyKeyboardMarkup:
    """Головне меню адміна."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Звіти"), KeyboardButton(text="🚗 Водії")],
            [KeyboardButton(text="💰 Фін модель")],
            [KeyboardButton(text="🚗 Режим водія")],
        ],
        resize_keyboard=True,
    )


def kb_admin_driver_idle() -> ReplyKeyboardMarkup:
    """Адмін у режимі водія — без активного маршруту."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🚀 Почати маршрут")],
            [KeyboardButton(text="◀️ Повернутися до адмін меню")],
        ],
        resize_keyboard=True,
    )


def kb_admin_driver_active() -> ReplyKeyboardMarkup:
    """Адмін у режимі водія — активний маршрут."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📍 Надіслати геолокацію", request_location=True)],
            [KeyboardButton(text="🏁 Завершити маршрут")],
            [KeyboardButton(text="◀️ Повернутися до адмін меню")],
        ],
        resize_keyboard=True,
    )


def kb_reports_menu() -> InlineKeyboardMarkup:
    """Підменю звітів."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Денний звіт",   callback_data="rpt:daily")],
        [InlineKeyboardButton(text="📆 Тижневий звіт", callback_data="rpt:weekly")],
    ])


def kb_drivers_menu() -> InlineKeyboardMarkup:
    """Підменю водіїв."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Список водіїв",          callback_data="drv:list")],
        [InlineKeyboardButton(text="⏳ Запити на авторизацію",  callback_data="drv:pending")],
        [InlineKeyboardButton(text="❌ Видалити водія",          callback_data="drv:remove")],
    ])


def kb_remove() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()

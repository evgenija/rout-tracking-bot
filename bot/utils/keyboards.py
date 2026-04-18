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


def kb_route_correction(route_id: int) -> InlineKeyboardMarkup:
    """Кнопки дій адміна при РЕБ/spoofing діагностиці (правила 2.4/3.1).

    Тільки "Перерахувати" і "Уточнити" — рішення по одометру приймає P2 автоматично.
    Callback prefix: corr:{action}:{route_id}
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="🔄 Перерахувати без підозрілих",
            callback_data=f"corr:recalc:{route_id}",
        )],
        [InlineKeyboardButton(
            text="❓ Уточнити у водія",
            callback_data=f"corr:clarify:{route_id}",
        )],
    ])


def kb_remove() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()


def kb_remind_ios_drivers(drivers: list) -> InlineKeyboardMarkup:
    """Список водіїв для /remind_ios — по 3 у рядку + кнопка скасування."""
    buttons: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for i, d in enumerate(drivers):
        row.append(InlineKeyboardButton(
            text=f"👤 {d['full_name']}",
            callback_data=f"ios:{d['telegram_id']}",
        ))
        if len(row) == 3 or i == len(drivers) - 1:
            buttons.append(row)
            row = []
    buttons.append([InlineKeyboardButton(text="❌ Скасувати", callback_data="ios:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def kb_ios_location_settings() -> None:
    """App-prefs:// URL не підтримується Telegram Bot API — кнопка не додається."""
    return None

from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
)


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


def kb_remove() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()

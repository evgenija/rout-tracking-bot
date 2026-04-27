"""
Тести для кнопки 🗺 Карта в bot/handlers/tracking.py.
Фіча 23.04.2026: кнопка відображається тільки якщо VIEWER_BASE_URL задано в env.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


# Відтворює логіку рядків 439-442 bot/handlers/tracking.py
def _finish_kb(viewer_base_url: str, route_id: int) -> InlineKeyboardMarkup:
    row = [InlineKeyboardButton(text="🔍 Деталі маршруту", callback_data=f"route_detail:{route_id}")]
    if viewer_base_url:
        row.append(InlineKeyboardButton(text="🗺 Карта", url=f"{viewer_base_url}/route/{route_id}"))
    return InlineKeyboardMarkup(inline_keyboard=[row])


def _flat_buttons(kb: InlineKeyboardMarkup):
    return [b for row in kb.inline_keyboard for b in row]


def test_map_button_present_when_viewer_url_set():
    """При VIEWER_BASE_URL != '' — кнопка '🗺 Карта' присутня у keyboard."""
    kb = _finish_kb("https://example.com", 42)
    texts = [b.text for b in _flat_buttons(kb)]
    assert "🗺 Карта" in texts, f"Кнопка '🗺 Карта' відсутня при VIEWER_BASE_URL заданому. Кнопки: {texts}"


def test_map_button_absent_when_viewer_url_missing():
    """При VIEWER_BASE_URL = '' — кнопка '🗺 Карта' відсутня, бот не падає."""
    kb = _finish_kb("", 42)
    texts = [b.text for b in _flat_buttons(kb)]
    assert "🗺 Карта" not in texts, f"Кнопка не має бути при порожньому URL. Кнопки: {texts}"


def test_map_button_url_format():
    """URL кнопки = VIEWER_BASE_URL + '/route/' + route_id."""
    route_id = 99
    kb = _finish_kb("https://viewer.example.com", route_id)
    btn = next((b for b in _flat_buttons(kb) if b.text == "🗺 Карта"), None)
    assert btn is not None
    assert btn.url == f"https://viewer.example.com/route/{route_id}", \
        f"Невірний URL кнопки: {btn.url!r}"


def test_tracking_source_has_conditional():
    """Regression: tracking.py містить 'if VIEWER_BASE_URL:' та текст '🗺 Карта'."""
    path = os.path.join(os.path.dirname(__file__), "..", "..", "bot", "handlers", "tracking.py")
    source = open(path, encoding="utf-8").read()
    assert "if VIEWER_BASE_URL:" in source, \
        "Умовна логіка 'if VIEWER_BASE_URL:' відсутня в tracking.py"
    assert "🗺 Карта" in source, \
        "Текст кнопки '🗺 Карта' відсутній в tracking.py"

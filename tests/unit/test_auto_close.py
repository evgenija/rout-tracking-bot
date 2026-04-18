"""
Регресійні тести для auto_close_active_routes.
"""
import os, sys, re
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


def _find_file(*rel_parts):
    candidates = [
        os.path.join("/app", *rel_parts),
        os.path.join(os.path.dirname(__file__), "..", "..", *rel_parts),
    ]
    return next((p for p in candidates if os.path.exists(p)), None)


def test_admin_message_no_false_odometer():
    """auto_close не надсилає хибне 'Одометр не зафіксовано' (regression)."""
    path = _find_file("bot", "utils", "scheduler.py")
    assert path, "scheduler.py не знайдено"
    source = open(path, encoding="utf-8").read()
    assert "Одометр не зафіксовано" not in source, (
        "Баг повернувся: auto_close надсилає хибне повідомлення про одометр"
    )


def test_get_all_active_routes_today_should_include_odometer_start():
    """get_all_active_routes_today() має включати odometer_start у SELECT.

    ВІДОМА ПРОБЛЕМА: зараз не включає — авто-закриття не може перевірити odometer_start.
    Цей тест провалиться поки не буде виправлено database.py.
    """
    path = _find_file("bot", "models", "database.py")
    assert path, "database.py не знайдено"
    source = open(path, encoding="utf-8").read()
    fn_match = re.search(
        r"async def get_all_active_routes_today.*?(?=\nasync def |\Z)",
        source, re.DOTALL,
    )
    assert fn_match, "Функцію get_all_active_routes_today не знайдено"
    fn_body = fn_match.group(0)
    assert "odometer_start" in fn_body, (
        "get_all_active_routes_today не включає odometer_start у SELECT — "
        "потрібно оновити database.py і auto_close_active_routes"
    )

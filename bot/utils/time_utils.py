from datetime import datetime, timezone, timedelta

# Київ = UTC+3 постійно (Україна скасувала переведення годинників з 2022 р.)
KYIV_TZ = timezone(timedelta(hours=3))


def get_kyiv_time() -> datetime:
    """Повертає поточний час у часовому поясі UTC+3 (Kyiv)."""
    return datetime.now(KYIV_TZ)


def to_kyiv_time(dt: datetime) -> datetime:
    """Конвертує datetime з БД у Kyiv time (UTC+3).

    Обробляє обидва формати:
    - naive datetime (старі UTC-записи в БД) — трактується як UTC, +3 год
    - aware datetime (нові записи з offset) — конвертується до UTC+3
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(KYIV_TZ)

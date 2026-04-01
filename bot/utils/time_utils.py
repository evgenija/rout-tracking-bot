from datetime import datetime
import pytz

KYIV_TZ = pytz.timezone("Europe/Kyiv")


def get_kyiv_time() -> datetime:
    """Повертає поточний час у часовому поясі Europe/Kyiv."""
    return datetime.now(KYIV_TZ)


def to_kyiv_time(dt: datetime) -> datetime:
    """Конвертує UTC datetime з БД у Kyiv time."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = pytz.utc.localize(dt)
    return dt.astimezone(KYIV_TZ)

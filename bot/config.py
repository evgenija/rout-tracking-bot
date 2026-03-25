import os
from typing import List
from dotenv import load_dotenv

load_dotenv()

# ── White-label налаштування ──────────────────────────────────────────────────
BOT_NAME = "Route Tracker Bot"
COMPANY_NAME = "АБВ хімія"
WELCOME_MESSAGE = "Ласкаво просимо до системи трекінгу маршрутів {company}!"

# ── Середовище ────────────────────────────────────────────────────────────────
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
ADMIN_IDS: List[int] = [
    int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()
]
SUPER_ADMIN_IDS: List[int] = [
    int(x.strip()) for x in os.getenv("SUPER_ADMIN_IDS", "").split(",") if x.strip()
]
GROUP_CHAT_ID: int = int(os.getenv("GROUP_CHAT_ID", "0"))
DATABASE_URL: str = os.getenv("DATABASE_URL", "bot.db")

# Вираховуємо шлях до SQLite-файлу
_data_dir = os.getenv("DATA_DIR", "")
if _data_dir and os.path.isdir(_data_dir):
    DB_PATH = os.path.join(_data_dir, "bot.db")
elif DATABASE_URL.startswith("sqlite"):
    DB_PATH = DATABASE_URL.replace("sqlite+aiosqlite:///", "").replace("sqlite:///", "")
else:
    DB_PATH = "bot.db"

# ── Google Maps Platform ──────────────────────────────────────────────────────
GOOGLE_MAPS_API_KEY: str = os.getenv("GOOGLE_MAPS_API_KEY", "")

# ── Захист від РЕБ-спуфінгу ───────────────────────────────────────────────────
MAX_DISTANCE_KM: float = 200.0    # макс відстань між двома мітками (понад — телепортація)
MIN_TIME_MINUTES: float = 2.0     # мін час між мітками для оцінки швидкості

# ── Планувальник звітів ───────────────────────────────────────────────────────
DAILY_REPORT_HOUR: int = 20
DAILY_REPORT_MINUTE: int = 0
WEEKLY_REPORT_WEEKDAY: str = "sun"   # APScheduler: sun=неділя

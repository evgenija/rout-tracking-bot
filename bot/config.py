import os
from typing import List
from dotenv import load_dotenv

load_dotenv()

# ── White-label налаштування ──────────────────────────────────────────────────
BOT_NAME = "Route Tracker Bot"
COMPANY_NAME = "Logistics Co."
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
if DATABASE_URL.startswith("sqlite"):
    DB_PATH = DATABASE_URL.replace("sqlite+aiosqlite:///", "").replace("sqlite:///", "")
else:
    DB_PATH = "bot.db"

# ── Захист від РЕБ-спуфінгу ───────────────────────────────────────────────────
MAX_DISTANCE_KM: float = 500.0    # макс відстань між двома мітками
MIN_TIME_MINUTES: float = 10.0    # мін час між мітками

# ── Планувальник звітів ───────────────────────────────────────────────────────
DAILY_REPORT_HOUR: int = 20
DAILY_REPORT_MINUTE: int = 0
WEEKLY_REPORT_WEEKDAY: str = "sun"   # APScheduler: sun=неділя

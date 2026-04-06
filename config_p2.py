"""
config_p2.py — конфіг модуля P2 Finance Bot.
Окремий від config.py P1. P1 не чіпати.
P2 використовує окрему PostgreSQL через PG_DATABASE_URL.
"""
import os
from dotenv import load_dotenv

load_dotenv()

SUPER_ADMIN_IDS = [314776654, 568294118]
PG_DATABASE_URL: str = os.getenv("PG_DATABASE_URL", "")

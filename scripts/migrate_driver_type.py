"""
Task 0 — Migrate driver_type in P1 SQLite.
Adds driver_type column to users table and sets correct values.
Run on the server: python3 scripts/migrate_driver_type.py
"""
import asyncio
import aiosqlite
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bot.config import DB_PATH


async def migrate():
    print(f"DB_PATH: {DB_PATH}")
    async with aiosqlite.connect(DB_PATH) as db:
        # Add column if not exists
        try:
            await db.execute("ALTER TABLE users ADD COLUMN driver_type TEXT DEFAULT 'own'")
            await db.commit()
            print("Column driver_type added")
        except Exception as e:
            print(f"Column already exists (OK): {e}")

        # Set logistics for known drivers (Bodya, ZAZA, Ukolov)
        logistics_ids = [935741313, 1713367110, 570793350]

        await db.execute(
            f"UPDATE users SET driver_type = 'logistics' WHERE telegram_id IN ({','.join('?' * len(logistics_ids))})",
            logistics_ids,
        )
        await db.commit()

        # Show all drivers
        cursor = await db.execute("SELECT id, name, telegram_id, driver_type FROM users")
        rows = await cursor.fetchall()
        print("\nAll drivers:")
        for r in rows:
            print(r)
        print("\nMigration OK")


asyncio.run(migrate())

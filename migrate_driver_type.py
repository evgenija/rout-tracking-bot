import asyncio
import aiosqlite
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from bot.config import DB_PATH


async def migrate():
    async with aiosqlite.connect(DB_PATH) as db:
        # Додати колонку якщо немає
        try:
            await db.execute("ALTER TABLE users ADD COLUMN driver_type TEXT DEFAULT 'own'")
            print("Column added")
        except Exception as e:
            print(f"Column already exists: {e}")

        # Встановити logistics для відомих водіїв
        logistics_ids = [935741313, 1713367110, 570793350]  # Бодя, ZAZA, Уколов

        await db.execute(
            f"UPDATE users SET driver_type = 'logistics' WHERE telegram_id IN ({','.join('?' * len(logistics_ids))})",
            logistics_ids,
        )
        await db.commit()

        # Показати всіх водіїв
        cursor = await db.execute("SELECT telegram_id, full_name, driver_type FROM users")
        rows = await cursor.fetchall()
        print("\nВсі водії:")
        for r in rows:
            print(r)
        print("Migration OK")


asyncio.run(migrate())

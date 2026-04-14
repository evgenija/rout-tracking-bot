import asyncio
import logging

import asyncpg
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from aiogram.types import BotCommand, BotCommandScopeChat
from bot.config import BOT_NAME, BOT_TOKEN, ADMIN_IDS, SUPER_ADMIN_IDS
from config_p2 import PG_DATABASE_URL
from bot.services.db_init_p2 import create_p2_tables
from bot.handlers import admin, auth, reports, tracking, ping_handler, debug_handler, route_detail_handler
from bot.models.database import (
    init_db,
    flag_suspicious_waypoints_retroactive,
    recalculate_all_route_distances,
)
from bot.utils.scheduler import setup_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN не задано. Перевірте .env файл.")

    logger.info("Запуск %s...", BOT_NAME)

    await init_db()
    logger.info("БД ініціалізовано.")

    flag_result = await flag_suspicious_waypoints_retroactive()
    logger.info("Ретроактивна перевірка GPS: %s", flag_result)

    recalc_result = await recalculate_all_route_distances()
    logger.info("Перерахунок маршрутів: %s", recalc_result)

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    if PG_DATABASE_URL:
        pg_pool = await asyncpg.create_pool(PG_DATABASE_URL)
        await create_p2_tables(pg_pool)
        dp["pg_pool"] = pg_pool
        logger.info("P2 PostgreSQL pool ініціалізовано.")
    else:
        logger.warning("PG_DATABASE_URL не задано — P2 функції вимкнено.")

    dp.include_router(auth.router)
    dp.include_router(admin.router)
    dp.include_router(tracking.router)
    dp.include_router(reports.router)
    dp.include_router(ping_handler.ping_router)
    dp.include_router(debug_handler.debug_router)
    dp.include_router(route_detail_handler.route_detail_router)

    setup_scheduler(bot)

    admin_commands = [
        BotCommand(command="remind_ios", description="Нагадування водію про геолокацію iOS"),
    ]
    for admin_id in set(ADMIN_IDS + SUPER_ADMIN_IDS):
        try:
            await bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=admin_id))
        except Exception:
            pass

    logger.info("Бот запущено. Починаю polling...")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())

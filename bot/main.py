import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config import BOT_NAME, BOT_TOKEN
from bot.handlers import admin, auth, reports, tracking
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

    dp.include_router(auth.router)
    dp.include_router(admin.router)
    dp.include_router(tracking.router)
    dp.include_router(reports.router)

    setup_scheduler(bot)

    logger.info("Бот запущено. Починаю polling...")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())

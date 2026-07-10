import logging
import os

import aiohttp

logger = logging.getLogger(__name__)


async def alert_super_admins(text: str) -> None:
    """Надсилає алерт супер-адмінам напряму через Telegram API (без bot-instance)."""
    token = os.environ.get("BOT_TOKEN", "")
    if not token:
        logger.warning("alert_super_admins: BOT_TOKEN не задано")
        return

    raw_ids = os.environ.get("SUPER_ADMIN_IDS", "")
    admin_ids = [int(x.strip()) for x in raw_ids.split(",") if x.strip()]
    if not admin_ids:
        logger.warning("alert_super_admins: SUPER_ADMIN_IDS не задано")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    timeout = aiohttp.ClientTimeout(total=5)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for chat_id in admin_ids:
            try:
                await session.post(url, json={"chat_id": chat_id, "text": text})
            except Exception as exc:
                logger.warning("alert_super_admins → %d: %s", chat_id, exc)

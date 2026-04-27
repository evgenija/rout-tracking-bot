"""
fuel_price_updater.py — щотижневий авто-апдейт цін на пальне.
Спроба: scrape globalpetrolprices.com/Ukraine → оновити DB → refresh кеш → notify.
Fallback: нагадування адміну оновити вручну командою /set_fuel <a95> <lpg>.
"""
import logging
import re

import aiohttp

logger = logging.getLogger(__name__)

_A95_URL = "https://www.globalpetrolprices.com/Ukraine/gasoline_prices/"
_LPG_URL = "https://www.globalpetrolprices.com/Ukraine/lpg_prices/"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; RouteBot/1.0)"}


async def _scrape_price(url: str) -> float | None:
    """Спроба зчитати поточну ціну з globalpetrolprices.com. Повертає UAH/л або None."""
    try:
        async with aiohttp.ClientSession(headers=_HEADERS) as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=12)) as resp:
                if resp.status != 200:
                    logger.warning("fuel scrape: HTTP %s for %s", resp.status, url)
                    return None
                html = await resp.text()

        for pattern in (
            r'<td[^>]+class="[^"]*price[^"]*"[^>]*>\s*([\d.]+)\s*</td>',
            r'"price":\s*"([\d.]+)"',
            r'<span[^>]+id="[^"]*price[^"]*"[^>]*>\s*([\d.]+)',
        ):
            m = re.search(pattern, html)
            if m:
                price = float(m.group(1))
                if 10 < price < 300:  # sanity: розумний діапазон UAH/л
                    return price
    except Exception as e:
        logger.warning("fuel scrape failed %s: %s", url, e)
    return None


async def update_fuel_prices(pg_pool, coeff_service, bot, super_admin_ids: list) -> None:
    """
    Щотижневий job (понеділок 08:00 Київ).
    Успіх → оновлює fuel_price_a95/lpg в DB + refresh кеш + сповіщення ✅.
    Невдача → нагадування адміну з /set_fuel.
    """
    a95 = await _scrape_price(_A95_URL)
    lpg = await _scrape_price(_LPG_URL)

    if a95 and lpg:
        async with pg_pool.acquire() as conn:
            await conn.execute(
                "UPDATE coefficients SET value=$1, updated_at=NOW() WHERE key='fuel_price_a95'", a95
            )
            await conn.execute(
                "UPDATE coefficients SET value=$1, updated_at=NOW() WHERE key='fuel_price_lpg'", lpg
            )
        await coeff_service.refresh()
        coeffs = await coeff_service.get()
        new_cost = coeffs.get("sales_cost_per_km", 0)
        text = (
            f"⛽ Ціни на пальне оновлено автоматично\n"
            f"А-95: {a95:.2f} грн/л\n"
            f"LPG: {lpg:.2f} грн/л\n"
            f"→ sales_cost_per_km = {new_cost:.2f} грн/км"
        )
        logger.info("Fuel prices auto-updated: A95=%.2f LPG=%.2f cost/km=%.4f", a95, lpg, new_cost)
    else:
        coeffs = await coeff_service.get()
        cur_a95 = coeffs.get("fuel_price_a95", "?")
        cur_lpg = coeffs.get("fuel_price_lpg", "?")
        cur_cost = coeffs.get("sales_cost_per_km", 0)
        text = (
            f"⚠️ Авто-оновлення цін на пальне не вдалося.\n"
            f"Поточні значення в системі:\n"
            f"  А-95: {cur_a95} грн/л\n"
            f"  LPG: {cur_lpg} грн/л\n"
            f"  sales_cost_per_km: {cur_cost:.2f} грн/км\n\n"
            f"Перевір актуальні ціни та оновіть:\n"
            f"/set_fuel <а95> <lpg>\n"
            f"Приклад: /set_fuel 74.50 50.20"
        )
        logger.warning("Fuel price auto-update failed, manual update required")

    for admin_id in super_admin_ids:
        try:
            await bot.send_message(admin_id, text)
        except Exception as e:
            logger.warning("fuel notify failed admin %s: %s", admin_id, e)

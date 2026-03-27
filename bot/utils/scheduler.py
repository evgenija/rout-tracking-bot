import logging
from datetime import datetime, timedelta

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from bot.config import (
    ADMIN_IDS,
    DAILY_REPORT_HOUR,
    DAILY_REPORT_MINUTE,
    WEEKLY_REPORT_WEEKDAY,
)
from bot.models.database import (
    get_daily_stats,
    get_weekly_stats,
    get_all_active_routes_today,
    get_route_waypoints,
    end_route,
)
from bot.utils.geo import format_duration

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler(timezone="Europe/Kyiv")


async def send_daily_report(bot: Bot):
    today = datetime.now().date().isoformat()
    stats = await get_daily_stats(today)

    if not stats:
        text = f"📊 Щоденний звіт за {today}\n\nНемає активних маршрутів."
    else:
        lines = [f"📊 Щоденний звіт за {today}\n"]
        for s in stats:
            duration = format_duration(s["first_start"], s["last_end"])
            lines.append(
                f"👤 {s['full_name']}\n"
                f"   🛣 {s['total_km']:.1f} км\n"
                f"   ⏱ {duration}"
            )
        text = "\n\n".join(lines)

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text)
        except Exception as e:
            logger.warning("Не вдалося надіслати звіт адміну %s: %s", admin_id, e)


async def send_weekly_report(bot: Bot):
    today = datetime.now().date()
    # Тиждень: з попереднього понеділка по сьогодні
    week_start = (today - timedelta(days=today.weekday() + 1)).isoformat()
    week_end = today.isoformat()

    stats = await get_weekly_stats(week_start, week_end)

    if not stats:
        text = f"📊 Тижневий звіт ({week_start} — {week_end})\n\nНемає даних."
    else:
        lines = [f"📊 Тижневий звіт ({week_start} — {week_end})\n"]
        grand_total = 0.0
        for s in stats:
            km = s["total_km"] or 0.0
            lines.append(f"👤 {s['full_name']}: {km:.1f} км ({s['route_count']} маршрутів)")
            grand_total += km
        lines.append(f"\n🏁 Grand Total: {grand_total:.1f} км")
        text = "\n".join(lines)

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text)
        except Exception as e:
            logger.warning("Не вдалося надіслати тижневий звіт адміну %s: %s", admin_id, e)


async def send_driver_reminder(bot: Bot):
    active_routes = await get_all_active_routes_today()
    for route in active_routes:
        try:
            await bot.send_message(
                route["telegram_id"],
                "⚠️ Твій маршрут досі активний!\n"
                "Якщо ти завершив роботу — натисни Фініш.\n"
                "Якщо не натиснеш до кінця дня — маршрут закриється автоматично.",
            )
        except Exception as e:
            logger.warning("Не вдалося надіслати нагадування водію %s: %s", route["telegram_id"], e)


async def auto_close_active_routes(bot: Bot):
    from bot.utils.geo import get_road_distance_for_route
    active_routes = await get_all_active_routes_today()
    for route in active_routes:
        route_id = route["id"]
        try:
            waypoints = await get_route_waypoints(route_id)
            # finished_at = timestamp останньої геомітки, або зараз якщо точок немає
            if waypoints:
                finished_at = waypoints[-1]["timestamp"]
            else:
                finished_at = datetime.now().isoformat()

            total_km = await get_road_distance_for_route(waypoints)
            await end_route(route_id, finished_at, total_km)

            # Повідомлення водію
            try:
                await bot.send_message(
                    route["telegram_id"],
                    f"🔒 Маршрут автоматично закрито о 23:59. Пробіг: {total_km:.1f} км",
                )
            except Exception as e:
                logger.warning("Не вдалося надіслати авто-закриття водію %s: %s", route["telegram_id"], e)

            # Повідомлення адмінам
            for admin_id in ADMIN_IDS:
                try:
                    await bot.send_message(
                        admin_id,
                        f"⚠️ Маршрут #{route_id} ({route['full_name']}) закрито автоматично "
                        f"(водій не натиснув Фініш). Пробіг: {total_km:.1f} км",
                    )
                except Exception as e:
                    logger.warning("Не вдалося надіслати авто-закриття адміну %s: %s", admin_id, e)

        except Exception as e:
            logger.error("Помилка авто-закриття маршруту #%s: %s", route_id, e)


def setup_scheduler(bot: Bot):
    scheduler.add_job(
        send_daily_report,
        CronTrigger(hour=DAILY_REPORT_HOUR, minute=DAILY_REPORT_MINUTE),
        args=[bot],
        id="daily_report",
        replace_existing=True,
    )
    scheduler.add_job(
        send_weekly_report,
        CronTrigger(day_of_week=WEEKLY_REPORT_WEEKDAY, hour=DAILY_REPORT_HOUR, minute=DAILY_REPORT_MINUTE),
        args=[bot],
        id="weekly_report",
        replace_existing=True,
    )
    scheduler.add_job(
        send_driver_reminder,
        CronTrigger(hour=20, minute=30),
        args=[bot],
        id="driver_reminder",
        replace_existing=True,
    )
    scheduler.add_job(
        auto_close_active_routes,
        CronTrigger(hour=23, minute=59),
        args=[bot],
        id="auto_close_routes",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started (daily=%s:%s, weekly=%s)", DAILY_REPORT_HOUR, DAILY_REPORT_MINUTE, WEEKLY_REPORT_WEEKDAY)

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
from bot.models.database import get_daily_stats, get_weekly_stats
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
    scheduler.start()
    logger.info("Scheduler started (daily=%s:%s, weekly=%s)", DAILY_REPORT_HOUR, DAILY_REPORT_MINUTE, WEEKLY_REPORT_WEEKDAY)

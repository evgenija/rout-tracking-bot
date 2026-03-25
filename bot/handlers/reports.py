from datetime import datetime, timedelta

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.config import ADMIN_IDS, SUPER_ADMIN_IDS
from bot.models.database import get_daily_stats, get_weekly_stats, get_weekly_stats_by_day, get_all_users
from bot.utils.geo import format_duration

logger = logging.getLogger(__name__)
router = Router()


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS or user_id in SUPER_ADMIN_IDS


@router.message(Command("drivers"))
async def cmd_drivers(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Недостатньо прав.")
        return

    users = await get_all_users()
    if not users:
        await message.answer("👥 Список порожній.")
        return

    approved = [u for u in users if u["is_approved"]]
    pending  = [u for u in users if not u["is_approved"]]

    lines = ["👥 Список водіїв\n"]

    if approved:
        lines.append("✅ Авторизовані:")
        for u in approved:
            tag = f" @{u['username']}" if u["username"] else ""
            lines.append(f"  • {u['full_name']}{tag} (ID: {u['telegram_id']})")

    if pending:
        lines.append("\n⏳ Очікують авторизації:")
        for u in pending:
            tag = f" @{u['username']}" if u["username"] else ""
            lines.append(f"  • {u['full_name']}{tag} (ID: {u['telegram_id']})")

    await message.answer("\n".join(lines))


@router.message(Command("report"))
async def cmd_report(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Недостатньо прав.")
        return

    today = datetime.now().date().isoformat()
    stats = await get_daily_stats(today)

    if not stats:
        await message.answer(f"📊 Щоденний звіт за {today}\n\nНемає активних маршрутів.")
        return

    lines = [f"📊 Щоденний звіт за {today}\n"]
    for s in stats:
        duration = format_duration(s["first_start"], s["last_end"])
        lines.append(
            f"👤 {s['full_name']}\n"
            f"   🛣 {s['total_km']:.1f} км | {s['waypoint_count']} точок\n"
            f"   ⏱ {duration}"
        )
    await message.answer("\n\n".join(lines))


@router.message(Command("weekly"))
async def cmd_weekly(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Недостатньо прав.")
        return

    today           = datetime.now().date()
    week_start_date = today - timedelta(days=today.weekday())
    week_start      = week_start_date.isoformat()
    week_end        = today.isoformat()
    stats           = await get_weekly_stats(week_start, week_end)

    # Per-driver per-day breakdown (diagnostic + display)
    day_breakdown = await get_weekly_stats_by_day(week_start, week_end)
    by_driver_day: dict[int, dict[str, float]] = {}
    by_driver_log: dict[str, list] = {}
    for row in day_breakdown:
        by_driver_day.setdefault(row["driver_id"], {})[row["day"]] = row["km"]
        by_driver_log.setdefault(row["full_name"], []).append(row)
    for drv, days in by_driver_log.items():
        day_parts = ", ".join(
            f"{d['day']}={d['km']:.1f}km/{d['waypoint_count']}pts({d['route_count']}routes)"
            for d in days
        )
        logger.info("[weekly] %s: %s | total=%.1fkm/%dpts",
                    drv, day_parts,
                    sum(d["km"] for d in days),
                    sum(d["waypoint_count"] for d in days))

    if not stats:
        await message.answer(f"📊 Тижневий звіт ({week_start} — {week_end})\n\nНемає даних.")
        return

    UA_DAYS   = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд"]
    week_days = [week_start_date + timedelta(days=i) for i in range(7)]

    header = f"📊 Тижневий звіт ({week_start} — {week_end})"
    driver_blocks   = []
    grand_total_km  = 0.0
    grand_total_pts = 0

    for s in stats:
        km          = s["total_km"] or 0.0
        wp          = s["waypoint_count"] or 0
        driver_days = by_driver_day.get(s["telegram_id"], {})

        rows = [f"👤 {s['full_name']}"]
        for d in week_days:
            day_km    = driver_days.get(d.isoformat(), 0.0)
            day_label = f"{UA_DAYS[d.weekday()]} {d.strftime('%d.%m')}"
            rows.append(f"📅 {day_label} — {day_km:.1f} км")
        rows.append(f"🛣 Тотал: {km:.1f} км | {wp} точок")
        driver_blocks.append("\n".join(rows))
        grand_total_km  += km
        grand_total_pts += wp

    body  = "\n\n─────────────────\n\n".join(driver_blocks)
    grand = f"━━━━━━━━━━━━━━━━━\n📊 GRAND TOTAL: {grand_total_km:.1f} км | {grand_total_pts} точок"
    await message.answer(f"{header}\n\n{body}\n\n{grand}")

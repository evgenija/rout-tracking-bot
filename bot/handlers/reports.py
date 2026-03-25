from datetime import datetime, timedelta

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.config import ADMIN_IDS, SUPER_ADMIN_IDS
from bot.models.database import get_daily_stats, get_weekly_stats, get_all_users
from bot.utils.geo import format_duration

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

    today = datetime.now().date()
    week_start = (today - timedelta(days=today.weekday() + 1)).isoformat()
    week_end = today.isoformat()
    stats = await get_weekly_stats(week_start, week_end)

    if not stats:
        await message.answer(f"📊 Тижневий звіт ({week_start} — {week_end})\n\nНемає даних.")
        return

    lines = [f"📊 Тижневий звіт ({week_start} — {week_end})\n"]
    grand_total = 0.0
    for s in stats:
        km = s["total_km"] or 0.0
        wp = s["waypoint_count"] or 0
        lines.append(
            f"👤 {s['full_name']}\n"
            f"   🛣 {km:.1f} км | {wp} точок"
        )
        grand_total += km
    lines.append(f"\n🏁 Grand Total: {grand_total:.1f} км")
    await message.answer("\n\n".join(lines))

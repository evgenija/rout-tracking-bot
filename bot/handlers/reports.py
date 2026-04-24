from datetime import datetime, timedelta

import logging

from bot.utils.time_utils import get_kyiv_time

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.config import ADMIN_IDS, SUPER_ADMIN_IDS
from bot.models.database import get_daily_stats, get_weekly_stats, get_weekly_stats_by_day, get_weekly_odo_by_day, get_all_users
from bot.utils.geo import format_duration
from bot.services.p2_report_service import get_p2_daily_by_date, format_payment_line, get_p2_weekly_by_range
from bot.services.weekly_report_service import format_weekly_report

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


def _odo_accuracy_block(total_km: float, odo_start, odo_finish) -> str:
    if odo_start is None or odo_finish is None:
        return "📍 Одометр: не введено"
    odo_diff = odo_finish - odo_start
    if odo_diff <= 0:
        return f"📍 Одометр: {odo_start:.0f} → {odo_finish:.0f} км\n   ⚠️ Помилка вводу"
    diff_pct = abs(total_km - odo_diff) / odo_diff * 100
    if diff_pct <= 5:
        label = "✅"
    elif diff_pct <= 12:
        label = "🔶"
    else:
        label = "🔴"
    return (
        f"📍 Одометр: {odo_start:.0f} → {odo_finish:.0f} км\n"
        f"   Пробіг за одометром: {odo_diff:.1f} км\n"
        f"   Трекінг: {total_km:.1f} км\n"
        f"   Похибка: {diff_pct:.1f}%  {label}"
    )


@router.message(Command("report"))
async def cmd_report(message: Message, pg_pool=None):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Недостатньо прав.")
        return

    today = get_kyiv_time().date().isoformat()
    stats = await get_daily_stats(today)
    p2    = await get_p2_daily_by_date(pg_pool, today)

    if not stats:
        await message.answer(f"📊 Щоденний звіт за {today}\n\nНемає активних маршрутів.")
        return

    lines = [f"📊 Щоденний звіт за {today}\n"]
    for s in stats:
        duration    = format_duration(s["first_start"], s["last_end"])
        p2_entry    = p2.get(s["telegram_id"])
        km_display  = p2_entry["km"] if p2_entry else s["total_km"]
        odo_block    = _odo_accuracy_block(s["total_km"], s.get("odo_start"), s.get("odo_finish"))
        payment_line = format_payment_line(p2_entry)
        lines.append(
            f"👤 {s['full_name']}\n"
            f"🛣 {km_display:.1f} км | {s['waypoint_count']} точок\n"
            f"⏱ {duration}\n"
            f"{odo_block}\n"
            f"{payment_line}"
        )
    await message.answer("\n\n".join(lines))


@router.message(Command("weekly"))
async def cmd_weekly(message: Message, pg_pool=None):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Недостатньо прав.")
        return

    today      = get_kyiv_time().date()
    week_start = today - timedelta(days=today.weekday())
    week_end   = today

    p1_stats  = await get_weekly_stats(week_start.isoformat(), week_end.isoformat())
    p1_by_day = await get_weekly_stats_by_day(week_start.isoformat(), week_end.isoformat())
    p1_odo    = await get_weekly_odo_by_day(week_start.isoformat(), week_end.isoformat())
    p2_weekly = await get_p2_weekly_by_range(pg_pool, week_start.isoformat(), week_end.isoformat())

    text = format_weekly_report(p1_stats, p1_by_day, p1_odo, p2_weekly, week_start, week_end)
    await message.answer(text)

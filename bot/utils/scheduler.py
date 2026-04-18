import logging
from datetime import datetime, timedelta

from bot.utils.time_utils import get_kyiv_time

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from bot.config import (
    ADMIN_IDS,
    SUPER_ADMIN_IDS,
    DAILY_REPORT_HOUR,
    DAILY_REPORT_MINUTE,
    GROUP_CHAT_ID,
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


async def send_daily_report(bot: Bot):
    today = get_kyiv_time().date().isoformat()
    stats = await get_daily_stats(today)

    if not stats:
        text = f"📊 Щоденний звіт за {today}\n\nНемає активних маршрутів."
    else:
        lines = [f"📊 Щоденний звіт за {today}\n"]
        for s in stats:
            duration = format_duration(s["first_start"], s["last_end"])
            total_km = s["total_km"]
            wcount   = s.get("waypoint_count", 0)
            base = (
                f"👤 {s['full_name']}\n"
                f"🛣 {total_km:.1f} км | {wcount} точок\n"
                f"⏱ {duration}"
            )
            odo_block = _odo_accuracy_block(total_km, s.get("odo_start"), s.get("odo_finish"))
            lines.append(f"{base}\n{odo_block}")
        text = "\n\n".join(lines)

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text)
        except Exception as e:
            logger.warning("Не вдалося надіслати звіт адміну %s: %s", admin_id, e)


async def send_weekly_report(bot: Bot):
    today = get_kyiv_time().date()
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
                finished_at = get_kyiv_time().isoformat()

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
                        f"(водій не натиснув Фініш). Пробіг: {total_km:.1f} км\n"
                        + (
                            f"📌 Одометр старту: {route['odometer_start']:.0f} км — фініш не введено"
                            if route.get("odometer_start") is not None
                            else "📌 Одометр не вводився — порівняння недоступне"
                        ),
                    )
                except Exception as e:
                    logger.warning("Не вдалося надіслати авто-закриття адміну %s: %s", admin_id, e)

            # Повідомлення в загальний чат (тихий режим для адмінів-водіїв)
            if route["telegram_id"] not in ADMIN_IDS and route["telegram_id"] not in SUPER_ADMIN_IDS:
                try:
                    await bot.send_message(
                        GROUP_CHAT_ID,
                        f"⚠️ Маршрут {route['full_name']} закрито автоматично о 23:59\n"
                        f"(водій не натиснув Фініш)\n"
                        f"🛣 Пробіг за день: {total_km:.1f} км",
                    )
                except Exception as e:
                    logger.warning("Не вдалося надіслати авто-закриття в груповий чат: %s", e)

        except Exception as e:
            logger.error("Помилка авто-закриття маршруту #%s: %s", route_id, e)


async def check_unanswered_pings(bot: Bot) -> None:
    """Scheduler job: позначає як suspicious waypoints без відповіді на ping > 30 хв."""
    from datetime import timezone, timedelta
    import sqlite3 as _sqlite3
    from bot.services import ping_service
    from bot.config import DB_PATH, ADMIN_IDS, SUPER_ADMIN_IDS
    _KYIV = timezone(timedelta(hours=3))
    unanswered = ping_service.get_unanswered_pings()
    for wp in unanswered:
        conn = _sqlite3.connect(DB_PATH)
        conn.execute("UPDATE waypoints SET is_suspicious = 1 WHERE id = ?", (wp["id"],))
        conn.commit()
        conn.close()
        driver_name = wp["driver_name"] or "Водій"
        try:
            wp_time = datetime.fromisoformat(wp["timestamp"])
            if wp_time.tzinfo is None:
                wp_time = wp_time.replace(tzinfo=_KYIV)
            gap_minutes = int((datetime.now(_KYIV) - wp_time).total_seconds() / 60)
        except Exception:
            gap_minutes = 0
        alert_text = (
            f"⚠️ {driver_name} не відповів на перевірку\n"
            f"Без геомітки {gap_minutes} хв — "
            f"наступні точки позначатимуться як підозрілі"
        )
        for admin_id in list(set(ADMIN_IDS + SUPER_ADMIN_IDS)):
            try:
                await bot.send_message(chat_id=admin_id, text=alert_text)
            except Exception as exc:
                logger.warning("Алерт адміну %d не надіслано: %s", admin_id, exc)


async def check_active_route_gaps(bot: Bot) -> None:
    """Scheduler job: ping driver if last waypoint > 60 min ago and no ping sent yet."""
    import sqlite3 as _sqlite3
    from datetime import timezone, timedelta
    from bot.services import ping_service
    from bot.config import DB_PATH, MAX_DISTANCE_KM
    from bot.handlers.ping_handler import build_ping_keyboard

    _KYIV = timezone(timedelta(hours=3))
    now = datetime.now(_KYIV)
    gap_cutoff = (now - timedelta(minutes=60)).isoformat()

    conn = _sqlite3.connect(DB_PATH)
    conn.row_factory = _sqlite3.Row
    active_routes = conn.execute(
        "SELECT id, driver_id FROM routes WHERE is_active = 1"
    ).fetchall()

    to_ping = []
    for route in active_routes:
        route_id = route["id"]
        wps = conn.execute(
            """SELECT w.id, w.timestamp, w.lat, w.lon, w.ping_sent_at,
                      u.full_name as driver_name
               FROM waypoints w
               JOIN routes r ON r.id = w.route_id
               LEFT JOIN users u ON u.telegram_id = r.driver_id
               WHERE w.route_id = ?
               ORDER BY w.timestamp DESC LIMIT 2""",
            (route_id,)
        ).fetchall()

        if not wps:
            continue
        last_wp = dict(wps[0])
        if last_wp["ping_sent_at"] is not None:
            continue

        should_ping = False
        # Rule 1.3: gap > 60 хв — водій мовчить без нових геоміток
        if last_wp["timestamp"] < gap_cutoff:
            should_ping = True
        # Rule 1.2: стрибок > MAX_DISTANCE_KM від попередньої точки
        if not should_ping and len(wps) >= 2:
            prev_wp = dict(wps[1])
            if ping_service._haversine(
                prev_wp["lat"], prev_wp["lon"],
                last_wp["lat"], last_wp["lon"],
            ) > MAX_DISTANCE_KM:
                should_ping = True

        if should_ping:
            to_ping.append({
                "route_id": route_id,
                "driver_id": route["driver_id"],
                "wp_id": last_wp["id"],
                "driver_name": last_wp["driver_name"] or "Водій",
            })

    conn.close()

    for item in to_ping:
        try:
            await bot.send_message(
                chat_id=item["driver_id"],
                text=f"🚗 {item['driver_name']}, ви ще працюєте по маршруту?",
                reply_markup=build_ping_keyboard(item["wp_id"]),
            )
            ping_service.mark_ping_sent(item["wp_id"])
            logger.info(
                "Scheduler ping sent: route=%d wp=%d driver=%d",
                item["route_id"], item["wp_id"], item["driver_id"],
            )
        except Exception as exc:
            logger.warning("Scheduler ping failed: route=%d err=%s", item["route_id"], exc)


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
    scheduler.add_job(
        check_unanswered_pings,
        CronTrigger(minute="*/5"),
        args=[bot],
        id="check_unanswered_pings",
        replace_existing=True,
    )
    scheduler.add_job(
        check_active_route_gaps,
        CronTrigger(minute="*/5"),
        args=[bot],
        id="check_active_route_gaps",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started (daily=%s:%s, weekly=%s)", DAILY_REPORT_HOUR, DAILY_REPORT_MINUTE, WEEKLY_REPORT_WEEKDAY)

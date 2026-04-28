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
    WEEKLY_REPORT_HOUR,
)
from bot.models.database import (
    get_daily_stats,
    get_weekly_stats,
    get_weekly_stats_by_day,
    get_weekly_odo_by_day,
    get_all_active_routes_today,
    get_route_waypoints,
    end_route,
)
from bot.utils.geo import format_duration
from bot.services.p2_report_service import get_p2_daily_by_date, format_payment_line, get_p2_weekly_by_range
from bot.services.weekly_report_service import format_weekly_report

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler(timezone="Europe/Kyiv")

# Shared instance — ініціалізується в setup_scheduler, використовується у всіх jobs
_shared_coeff_service = None


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


async def send_daily_report(bot: Bot, pg_pool=None):
    try:
        today = get_kyiv_time().date().isoformat()
        stats = await get_daily_stats(today)
        p2    = await get_p2_daily_by_date(pg_pool, today)

        if not stats:
            text = f"📊 Щоденний звіт за {today}\n\nНемає активних маршрутів."
        else:
            lines = [f"📊 Щоденний звіт за {today}\n"]
            for s in stats:
                duration  = format_duration(s["first_start"], s["last_end"])
                total_km  = s["total_km"]
                wcount    = s.get("waypoint_count", 0)
                p2_entry  = p2.get(s["telegram_id"])
                km_display = p2_entry["km"] if p2_entry else total_km
                base = (
                    f"👤 {s['full_name']}\n"
                    f"🛣 {km_display:.1f} км | {wcount} точок\n"
                    f"⏱ {duration}"
                )
                odo_block     = _odo_accuracy_block(total_km, s.get("odo_start"), s.get("odo_finish"))
                payment_line  = format_payment_line(p2_entry)
                lines.append(f"{base}\n{odo_block}\n{payment_line}")
            text = "\n\n".join(lines)

        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(admin_id, text)
            except Exception as e:
                logger.warning("Не вдалося надіслати звіт адміну %s: %s", admin_id, e)
    except Exception as e:
        logger.error("Scheduler job send_daily_report failed: %s", e)
        for admin_id in list(set(ADMIN_IDS + SUPER_ADMIN_IDS)):
            try:
                await bot.send_message(admin_id, f"⚠️ Scheduler job впав:\nsend_daily_report\n{e}")
            except Exception:
                pass


async def send_weekly_report(bot: Bot, pg_pool=None):
    try:
        today      = get_kyiv_time().date()
        week_start = today - timedelta(days=today.weekday() + 1)  # пн минулого тижня
        week_end   = today

        p1_stats  = await get_weekly_stats(week_start.isoformat(), week_end.isoformat())
        p1_by_day = await get_weekly_stats_by_day(week_start.isoformat(), week_end.isoformat())
        p1_odo    = await get_weekly_odo_by_day(week_start.isoformat(), week_end.isoformat())
        p2_weekly = await get_p2_weekly_by_range(pg_pool, week_start.isoformat(), week_end.isoformat())

        text = format_weekly_report(p1_stats, p1_by_day, p1_odo, p2_weekly, week_start, week_end)

        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(admin_id, text)
            except Exception as e:
                logger.warning("Не вдалося надіслати тижневий звіт адміну %s: %s", admin_id, e)
    except Exception as e:
        logger.error("Scheduler job send_weekly_report failed: %s", e)
        for admin_id in list(set(ADMIN_IDS + SUPER_ADMIN_IDS)):
            try:
                await bot.send_message(admin_id, f"⚠️ Scheduler job впав:\nsend_weekly_report\n{e}")
            except Exception:
                pass


async def send_driver_reminder(bot: Bot):
    try:
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
    except Exception as e:
        logger.error("Scheduler job send_driver_reminder failed: %s", e)
        for admin_id in list(set(ADMIN_IDS + SUPER_ADMIN_IDS)):
            try:
                await bot.send_message(admin_id, f"⚠️ Scheduler job впав:\nsend_driver_reminder\n{e}")
            except Exception:
                pass


async def auto_close_active_routes(bot: Bot, pg_pool=None):
    try:
        await _auto_close_active_routes_inner(bot, pg_pool)
    except Exception as e:
        logger.error("Scheduler job auto_close_active_routes failed: %s", e)
        for admin_id in list(set(ADMIN_IDS + SUPER_ADMIN_IDS)):
            try:
                await bot.send_message(admin_id, f"⚠️ Scheduler job впав:\nauto_close_active_routes\n{e}")
            except Exception:
                pass


async def _auto_close_active_routes_inner(bot: Bot, pg_pool=None):
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
            try:
                from bot.utils.geo import get_cached_polyline
                from bot.models.database import update_route_polyline
                _polyline = get_cached_polyline(waypoints)
                if _polyline:
                    await update_route_polyline(route_id, _polyline)
            except Exception as _e:
                logger.warning("polyline save failed for route %d: %s", route_id, _e)

            # P2 hook — без одометра фінішу (авто-закриття)
            if pg_pool:
                try:
                    from bot.services.route_cost_service import on_route_finished, get_driver_type
                    from bot.services.coefficients_service import CoefficientsService
                    _driver_type = get_driver_type(route["telegram_id"])
                    svc = _shared_coeff_service or CoefficientsService(pg_pool)
                    _coefficients = await svc.get()
                    await on_route_finished(
                        route_id=route_id,
                        driver_id=route["telegram_id"],
                        driver_type=_driver_type,
                        tracking_km=float(total_km) if total_km else 0.0,
                        odometer_km=None,
                        driver_name=route["full_name"],
                        coefficients=_coefficients,
                        pg_pool=pg_pool,
                        bot=bot,
                    )
                except Exception as _e:
                    logger.warning("P2 route cost hook failed (auto-close) route #%d: %s", route_id, _e)

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
    try:
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
    except Exception as e:
        logger.error("Scheduler job check_unanswered_pings failed: %s", e)
        for admin_id in list(set(ADMIN_IDS + SUPER_ADMIN_IDS)):
            try:
                await bot.send_message(admin_id, f"⚠️ Scheduler job впав:\ncheck_unanswered_pings\n{e}")
            except Exception:
                pass


async def check_active_route_gaps(bot: Bot) -> None:
    """Scheduler job: ping driver if last waypoint > 60 min ago and no ping sent yet."""
    try:
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
    except Exception as e:
        logger.error("Scheduler job check_active_route_gaps failed: %s", e)
        for admin_id in list(set(ADMIN_IDS + SUPER_ADMIN_IDS)):
            try:
                await bot.send_message(admin_id, f"⚠️ Scheduler job впав:\ncheck_active_route_gaps\n{e}")
            except Exception:
                pass


async def update_fuel_prices_job(bot: Bot, pg_pool=None):
    """Щотижневий job: авто-оновлення цін на пальне."""
    if not pg_pool:
        return
    try:
        from bot.services.fuel_price_updater import update_fuel_prices
        from config_p2 import SUPER_ADMIN_IDS
        svc = _shared_coeff_service
        if svc is None:
            from bot.services.coefficients_service import CoefficientsService
            svc = CoefficientsService(pg_pool)
        await update_fuel_prices(pg_pool, svc, bot, SUPER_ADMIN_IDS)
    except Exception as e:
        logger.error("Scheduler job update_fuel_prices failed: %s", e)
        for admin_id in list(set(ADMIN_IDS + SUPER_ADMIN_IDS)):
            try:
                await bot.send_message(admin_id, f"⚠️ Scheduler job впав:\nupdate_fuel_prices\n{e}")
            except Exception:
                pass


async def check_weekly_missing_revenue(bot: Bot, pg_pool=None):
    """Сб 18:00 — перевірка пропущеної виручки за тиждень."""
    if not pg_pool:
        return
    try:
        from datetime import date
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        from bot.services.finance_service import get_missing_revenue_days
        today = get_kyiv_time().date()
        week_start = today - timedelta(days=today.weekday())  # поточний пн
        missing = await get_missing_revenue_days(pg_pool, week_start, today)
        if not missing:
            return
        days_str = ", ".join(d.strftime("%d.%m") for d in missing)
        text = (
            f"📋 Є пропуски у виручці за {week_start.strftime('%d.%m')}–{today.strftime('%d.%m.%Y')}:\n"
            f"Дні без даних: {days_str}"
        )
        # Групуємо суміжні дні у блоки, щоб уникнути overlap при збереженні
        blocks, start, prev = [], missing[0], missing[0]
        for d in missing[1:]:
            if (d - prev).days == 1:
                prev = d
            else:
                blocks.append((start, prev))
                start = prev = d
        blocks.append((start, prev))

        buttons = [
            [InlineKeyboardButton(
                text=f"📥 Ввести за {bf.strftime('%d.%m')}–{bt.strftime('%d.%m')} одразу",
                callback_data=f"batch_revenue:{bf.isoformat()}:{bt.isoformat()}",
            )]
            for bf, bt in blocks if bf != bt  # однодення блоки — без кнопки
        ]
        kb = InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None
        for admin_id in SUPER_ADMIN_IDS:
            try:
                await bot.send_message(admin_id, text, reply_markup=kb)
            except Exception as e:
                logger.warning("check_weekly_missing: notify failed %s: %s", admin_id, e)
    except Exception as e:
        logger.error("Scheduler job check_weekly_missing_revenue failed: %s", e)
        for admin_id in list(set(ADMIN_IDS + SUPER_ADMIN_IDS)):
            try:
                await bot.send_message(admin_id, f"⚠️ Scheduler job впав:\ncheck_weekly_missing_revenue\n{e}")
            except Exception:
                pass


async def send_weekly_revenue_reminder(bot: Bot):
    """Пн 09:00 — нагадування ввести виручку."""
    try:
        today = get_kyiv_time().date()
        prev_week_end = today - timedelta(days=1)  # нд
        prev_week_start = prev_week_end - timedelta(days=6)  # пн
        text = (
            f"📊 Новий тиждень!\n"
            f"Чи введена виручка за {prev_week_start.strftime('%d.%m')}–{prev_week_end.strftime('%d.%m')}?\n"
            f"Натисни 💰 Фін модель щоб перевірити або ввести."
        )
        for admin_id in SUPER_ADMIN_IDS:
            try:
                await bot.send_message(admin_id, text)
            except Exception as e:
                logger.warning("weekly_reminder: notify failed %s: %s", admin_id, e)
    except Exception as e:
        logger.error("Scheduler job send_weekly_revenue_reminder failed: %s", e)
        for admin_id in list(set(ADMIN_IDS + SUPER_ADMIN_IDS)):
            try:
                await bot.send_message(admin_id, f"⚠️ Scheduler job впав:\nsend_weekly_revenue_reminder\n{e}")
            except Exception:
                pass


async def send_weekly_finance_report(bot: Bot, pg_pool=None):
    """Пн 20:00 — тижневий фін звіт (частковий якщо є пропуски)."""
    if not pg_pool:
        return
    try:
        from datetime import date
        from bot.services.finance_service import build_weekly_result
        from bot.services.report_service_finance import format_weekly_report_finance
        today = get_kyiv_time().date()
        prev_week_end = today - timedelta(days=1)
        prev_week_start = prev_week_end - timedelta(days=6)
        svc = _shared_coeff_service
        if svc is None:
            from bot.services.coefficients_service import CoefficientsService
            svc = CoefficientsService(pg_pool)
        coefficients = await svc.get()
        result = await build_weekly_result(pg_pool, prev_week_start, prev_week_end, coefficients)
        text = format_weekly_report_finance(result)
        for admin_id in SUPER_ADMIN_IDS:
            try:
                await bot.send_message(admin_id, text)
            except Exception as e:
                logger.warning("weekly_finance_report: notify failed %s: %s", admin_id, e)
    except Exception as e:
        logger.error("Scheduler job send_weekly_finance_report failed: %s", e)
        for admin_id in list(set(ADMIN_IDS + SUPER_ADMIN_IDS)):
            try:
                await bot.send_message(admin_id, f"⚠️ Scheduler job впав:\nsend_weekly_finance_report\n{e}")
            except Exception:
                pass


async def send_monthly_finance_report(bot: Bot, pg_pool=None):
    """1-го числа 08:00 — місячний фін звіт."""
    if not pg_pool:
        return
    try:
        from datetime import date
        from bot.services.finance_service import build_monthly_result
        from bot.services.report_service_finance import format_monthly_report_finance
        today = get_kyiv_time().date()
        # звіт за попередній місяць
        if today.month == 1:
            year, month = today.year - 1, 12
        else:
            year, month = today.year, today.month - 1
        svc = _shared_coeff_service
        if svc is None:
            from bot.services.coefficients_service import CoefficientsService
            svc = CoefficientsService(pg_pool)
        coefficients = await svc.get()
        result = await build_monthly_result(pg_pool, year, month, coefficients)
        text = format_monthly_report_finance(result, month)
        for admin_id in SUPER_ADMIN_IDS:
            try:
                await bot.send_message(admin_id, text)
            except Exception as e:
                logger.warning("monthly_finance_report: notify failed %s: %s", admin_id, e)
    except Exception as e:
        logger.error("Scheduler job send_monthly_finance_report failed: %s", e)
        for admin_id in list(set(ADMIN_IDS + SUPER_ADMIN_IDS)):
            try:
                await bot.send_message(admin_id, f"⚠️ Scheduler job впав:\nsend_monthly_finance_report\n{e}")
            except Exception:
                pass


def setup_scheduler(bot: Bot, pg_pool=None, coeff_service=None):
    global _shared_coeff_service
    if coeff_service:
        _shared_coeff_service = coeff_service
    elif pg_pool:
        from bot.services.coefficients_service import CoefficientsService
        _shared_coeff_service = CoefficientsService(pg_pool)

    scheduler.add_job(
        send_daily_report,
        CronTrigger(hour=DAILY_REPORT_HOUR, minute=DAILY_REPORT_MINUTE),
        args=[bot, pg_pool],
        id="daily_report",
        replace_existing=True,
    )
    scheduler.add_job(
        send_weekly_report,
        CronTrigger(day_of_week=WEEKLY_REPORT_WEEKDAY, hour=WEEKLY_REPORT_HOUR, minute=0),
        args=[bot, pg_pool],
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
        args=[bot, pg_pool],
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
    scheduler.add_job(
        update_fuel_prices_job,
        CronTrigger(day_of_week="mon", hour=8, minute=0),
        args=[bot, pg_pool],
        id="update_fuel_prices",
        replace_existing=True,
    )
    # P&L Finance jobs
    scheduler.add_job(
        check_weekly_missing_revenue,
        CronTrigger(day_of_week="sat", hour=18, minute=0),
        args=[bot, pg_pool],
        id="check_weekly_missing_revenue",
        replace_existing=True,
    )
    scheduler.add_job(
        send_weekly_revenue_reminder,
        CronTrigger(day_of_week="mon", hour=9, minute=0),
        args=[bot],
        id="weekly_revenue_reminder",
        replace_existing=True,
    )
    scheduler.add_job(
        send_weekly_finance_report,
        CronTrigger(day_of_week="mon", hour=20, minute=0),
        args=[bot, pg_pool],
        id="weekly_finance_report",
        replace_existing=True,
    )
    scheduler.add_job(
        send_monthly_finance_report,
        CronTrigger(day=1, hour=8, minute=0),
        args=[bot, pg_pool],
        id="monthly_finance_report",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started (daily=%s:%s, weekly=%s)", DAILY_REPORT_HOUR, DAILY_REPORT_MINUTE, WEEKLY_REPORT_WEEKDAY)

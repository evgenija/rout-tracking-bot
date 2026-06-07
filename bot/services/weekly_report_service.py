"""
weekly_report_service.py — форматування тижневого звіту.
Чиста функція: не залежить від БД, aiogram або Telegram.
Отримує готові дані з P1 і P2, повертає рядок.
"""
from datetime import date, timedelta


def format_weekly_report(
    p1_stats: list,
    p1_by_day: list,
    p1_odo: dict,
    p2_weekly: dict,
    week_start: date,
    week_end: date,
) -> str:
    """
    p1_stats    — результат get_weekly_stats() (total per driver)
    p1_by_day   — результат get_weekly_stats_by_day() (per driver per day)
    p1_odo      — результат get_weekly_odo_by_day() ({driver_id: {day: odo_km}})
    p2_weekly   — результат get_p2_weekly_by_range() ({driver_id: {day: {km, cost}}})
    """
    if not p1_stats:
        return (
            f"📅 Тижневий звіт: {week_start.strftime('%d.%m')} – "
            f"{week_end.strftime('%d.%m.%Y')}\n\nНемає даних за цей тиждень."
        )

    header = (
        f"📅 Тижневий звіт: {week_start.strftime('%d.%m')} – "
        f"{week_end.strftime('%d.%m.%Y')}"
    )

    # Побудуємо per-day dict: {driver_id: {day_str: {tracking_km, ...}}}
    by_driver_day: dict = {}
    for row in p1_by_day:
        by_driver_day.setdefault(row["driver_id"], {})[row["day"]] = row

    week_days = [week_start + timedelta(days=i) for i in range(7)]

    driver_blocks = []
    grand_tracking = 0.0
    grand_odo      = 0.0
    grand_cost     = 0.0
    grand_has_cost = False
    has_asterisk   = False

    for s in p1_stats:
        driver_id   = s["telegram_id"]
        driver_days = by_driver_day.get(driver_id, {})
        driver_odo  = p1_odo.get(driver_id, {})
        driver_p2   = p2_weekly.get(driver_id, {})

        lines = [f"👤 {s['full_name']}", "━━━━━━━━━━━━━━━━━━"]

        day_tracking = 0.0
        day_odo_sum  = 0.0
        day_cost_sum = 0.0
        has_odo      = False
        has_cost     = False

        for d in week_days:
            day_str  = d.isoformat()
            p1_day   = driver_days.get(day_str)
            if not p1_day:
                continue

            tracking = p1_day.get("km") or 0.0
            odo      = driver_odo.get(day_str)
            p2_day   = driver_p2.get(day_str)

            day_tracking += tracking
            if odo is not None:
                day_odo_sum += odo
                has_odo = True
            if p2_day:
                day_cost_sum += (p2_day.get("cost") or 0.0)
                has_cost = True

            label = d.strftime("%d.%m")
            if p2_day:
                km_col = f"{p2_day['km']:.1f}"
            else:
                km_col = f"{tracking:.1f}*"
                has_asterisk = True
            odo_col = f"{odo:.1f}" if odo is not None else "—"
            cost_col = f"{p2_day['cost']:,.0f} грн".replace(",", " ") if p2_day else "—"
            lines.append(f"{label} | odo {odo_col} | gps {tracking:.1f} | final {km_col} | {cost_col}")

        lines.append("─────────────────────")
        total_final  = sum(
            (driver_p2.get(d.isoformat(), {}).get("km") or 0.0) for d in week_days
        ) or day_tracking
        odo_total_str  = f"{day_odo_sum:.1f} км (одометр)" if has_odo else "одометр відсутній"
        cost_total_str = f"{day_cost_sum:,.0f} грн".replace(",", " ") if has_cost else "⏳ немає даних"
        lines.append(
            f"Тотал: {total_final:.1f} км (final) | {odo_total_str} | {cost_total_str}"
        )

        driver_blocks.append("\n".join(lines))

        grand_tracking += day_tracking
        grand_odo      += day_odo_sum
        grand_cost     += day_cost_sum
        if has_cost:
            grand_has_cost = True

    grand_cost_str = f"{grand_cost:,.0f} грн".replace(",", " ") if grand_has_cost else "⏳ немає даних"
    grand_odo_str  = f"{grand_odo:.1f} км" if grand_odo > 0 else "—"
    grand_block = (
        "━━━━━━━━━━━━━━━━━━\n"
        "📊 GRAND TOTAL\n"
        f"Трекінг: {grand_tracking:.1f} км\n"
        f"Одометр: {grand_odo_str}\n"
        f"Оплата: {grand_cost_str}"
    )

    note = (
        "\n* — final_km = GPS (одометр відсутній або P2 не відповів)"
        if has_asterisk else ""
    )

    return "\n\n".join([header] + driver_blocks + [grand_block]) + note

"""
report_service_finance.py — форматує WeeklyResult і MonthlyResult для Telegram.
Не залежить від БД або aiogram.
"""
from calendar import month_name as _month_name
from bot.services.calculator import WeeklyResult, MonthlyResult

_MONTHS_UA = [
    "", "Січень", "Лютий", "Березень", "Квітень", "Травень", "Червень",
    "Липень", "Серпень", "Вересень", "Жовтень", "Листопад", "Грудень",
]


def _fmt(value: float) -> str:
    return f"{value:,.0f}".replace(",", " ") + " грн"


def _pct(value: float) -> str:
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.0f}%"


def format_weekly_report_finance(result: WeeklyResult) -> str:
    start_str = result.week_start.strftime("%d.%m")
    end_str   = result.week_end.strftime("%d.%m.%Y")

    lines = [f"📊 Тижневий звіт {start_str}–{end_str}"]

    if result.is_partial and result.missing_days:
        missing_str = ", ".join(d.strftime("%d.%m") for d in result.missing_days)
        lines.append(f"⚠️ Неповний: відсутні дані за {missing_str}")

    lines += [
        "",
        f"💰 Виручка тижня:          {_fmt(result.revenue)}",
        f"🚛 Доставка:              -{_fmt(result.delivery_total)}  │  одометр: -{_fmt(result.delivery_total_odo)}",
        f"📦 Операційний прибуток:   {_fmt(result.op_profit)}  │  одометр: {_fmt(result.op_profit_odo)}",
        "",
        "📉 Фіксовані витрати тижня:",
        f"   Загальні витрати:       {_fmt(result.shared_week)}",
        f"   Податки:                {_fmt(result.taxes_week)}",
        "─" * 38,
        f"{'✅' if result.net_profit >= 0 else '🔴'} Чистий прибуток:         {_fmt(result.net_profit)}  │  одометр: {_fmt(result.net_profit_odo)}",
    ]

    if result.breakeven_day > 0:
        lines += [
            "",
            f"📍 Беззбитковість:",
            f"   На день потрібно:    {_fmt(result.breakeven_day)}",
        ]
        if result.days_in_week > 0:
            daily_avg = result.revenue / result.days_in_week
            ratio = daily_avg / result.breakeven_day
            symbol = "✅" if ratio >= 1 else "⚠️"
            lines.append(
                f"   Середня за тиждень:  {_fmt(daily_avg)} (×{ratio:.1f} від мінімуму {symbol})"
            )
            if result.working_days_in_month > 0 and result.monthly_fixed > 0:
                op_daily_avg = result.op_profit / result.days_in_week
                projected_net = op_daily_avg * result.working_days_in_month - result.monthly_fixed
                month_name = _MONTHS_UA[result.week_start.month]
                if projected_net >= 0:
                    lines.append(f"📈 Прогноз на {month_name}: ~{_fmt(projected_net)} чистого прибутку")
                else:
                    lines.append(f"📈 Прогноз на {month_name}: {_fmt(projected_net)} (збиток якщо темп збережеться)")

    if result.revenue_vs_median_pct is not None:
        lines.append(f"📈 vs медіана 2025:         {_pct(result.revenue_vs_median_pct)}")

    return "\n".join(lines)


def format_monthly_report_finance(result: MonthlyResult, month: int) -> str:
    month_name = _MONTHS_UA[month] if 1 <= month <= 12 else str(month)

    lines = [f"📊 Місячний звіт — {month_name} {result.year}"]

    if result.is_partial:
        lines.append(f"⚠️ Частковий: {result.missing_days_count} дні(в) без виручки")

    lines += [
        "",
        f"💰 Виручка:                {_fmt(result.revenue)}",
        f"📦 Собівартість (70%):    -{_fmt(result.cogs)}",
        f"🚚 Доставка:              -{_fmt(result.delivery_total)}  │  одометр: -{_fmt(result.delivery_total_odo)}",
        f"👔 Sales км:              -{_fmt(result.sales_km_cost)}",
        f"💼 Зарплата sales:        -{_fmt(result.sales_salary)}",
        "─" * 38,
        f"📊 Операційний прибуток:   {_fmt(result.op_profit)}  │  одометр: {_fmt(result.op_profit_odo)}",
        "",
        "📉 Фіксовані витрати:",
        f"   Загальні:              -{_fmt(result.shared)}",
        f"   Податки:               -{_fmt(result.taxes)}",
        "─" * 38,
        f"{'✅' if result.net_profit >= 0 else '🔴'} Чистий прибуток:         {_fmt(result.net_profit)}  │  одометр: {_fmt(result.net_profit_odo)}",
    ]

    if result.breakeven_day > 0:
        lines.append(f"\n📍 Беззбитковість/день:    {_fmt(result.breakeven_day)}")

    if result.revenue_vs_median_pct is not None:
        lines.append(f"📈 vs медіана 2025:         {_pct(result.revenue_vs_median_pct)}")

    return "\n".join(lines)

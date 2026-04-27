"""
report_service.py — форматує результати calculator.py для Telegram.
Не залежить від БД або aiogram.
"""
from datetime import date

from bot.services.calculator import BusinessResult, DailyOpResult


def format_daily_report(result: BusinessResult, report_date: date, sales_km: float) -> str:
    """Форматує денний звіт для супер-адміна (business_mode результат)."""
    def fmt(value: float) -> str:
        return f"{value:,.0f}".replace(",", " ") + " грн"

    def fmt_km(value: float) -> str:
        return f"{value:.1f} км"

    lines = [
        f"📊 Звіт за {report_date.strftime('%d.%m.%Y')}",
        "",
        f"💰 Revenue:          {fmt(result.revenue)}",
        f"📦 COGS:            -{fmt(result.cogs)}",
        "",
        f"🚛 Доставка:",
        f"   логістика:       -{fmt(result.delivery.logistics_cost)} ({fmt_km(result.delivery.logistics_km)})",
        f"   власний водій:   -{fmt(result.delivery.own_cost)} ({fmt_km(result.delivery.own_km)})",
        "",
        f"👔 Sales км:         -{fmt(result.sales_km_cost)} ({fmt_km(sales_km)})",
        f"💼 Зарплата sales:   -{fmt(result.sales_salary)}",
        "",
        f"🏢 Загальні:         -{fmt(result.shared)}",
        f"💸 Податки:          -{fmt(result.taxes)}",
        "",
        "─" * 32,
        f"{'✅' if result.net_profit >= 0 else '🔴'} Net Profit:    {fmt(result.net_profit)}",
        "",
        f"📉 Беззбитковість:   {fmt(result.breakeven_revenue)}",
    ]
    return "\n".join(lines)


def format_daily_op_report(result: DailyOpResult) -> str:
    """Форматує денний операційний звіт для власника (без Shared і Taxes)."""
    def fmt(value: float) -> str:
        return f"{value:,.0f}".replace(",", " ") + " грн"

    date_str = result.date.strftime("%d.%m.%Y")
    lines = [
        f"📊 Операційний результат за {date_str}",
        "",
        f"💰 Виручка:              {fmt(result.revenue)}",
        f"📦 Собівартість (70%):  -{fmt(result.cogs)}",
        f"🚚 Доставка:            -{fmt(result.delivery_total)}",
        f"   └ Логістика:         -{fmt(result.delivery_logistics)}",
        f"   └ Власний водій:     -{fmt(result.delivery_own)}",
        f"👔 Sales км:            -{fmt(result.sales_km_cost)}",
        f"💼 Зарплата sales:      -{fmt(result.sales_salary)}",
        "─" * 36,
        f"{'✅' if result.op_profit >= 0 else '🔴'} Операційний прибуток:  {fmt(result.op_profit)}",
    ]

    if result.sales_km_missing:
        lines.append("")
        lines.append("⚠️ Sales км = 0. Перевір та введи /set_sales_km якщо потрібно.")

    return "\n".join(lines)

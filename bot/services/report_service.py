"""
report_service.py — форматує результати calculator.py для Telegram.
Не залежить від БД або aiogram.
"""
from datetime import date

from bot.services.calculator import BusinessResult


def format_daily_report(result: BusinessResult, report_date: date, sales_km: float) -> str:
    """
    Форматує денний звіт для супер-адміна.
    Повертає готовий текст для Telegram.
    """
    def fmt(value: float) -> str:
        """Форматує число: 26524.5 → '26 525 грн'"""
        return f"{value:,.0f}".replace(",", " ") + " грн"

    def fmt_km(value: float) -> str:
        return f"{value:.1f} км"

    sales_note = " ⚠️ (salary > km cost)" if result.sales < 0 else ""

    lines = [
        f"📊 Звіт за {report_date.strftime('%d.%m.%Y')}",
        "",
        f"💰 Revenue:       {fmt(result.revenue)}",
        f"📦 COGS:         -{fmt(result.cogs)}",
        "",
        f"🚛 Delivery:",
        f"   logistics:    -{fmt(result.delivery.logistics_cost)} ({fmt_km(result.delivery.logistics_km)})",
        f"   власний водій: -{fmt(result.delivery.own_cost)} ({fmt_km(result.delivery.own_km)})",
        "",
        f"🧑 Sales:         {fmt(result.sales)}{sales_note}",
        f"   km вручну:    {fmt_km(sales_km)}",
        "",
        f"🏢 Shared:        -{fmt(result.shared)}",
        f"💸 Taxes:         -{fmt(result.taxes)}",
        "",
        "─" * 30,
        f"{'✅' if result.net_profit >= 0 else '🔴'} Net Profit:    {fmt(result.net_profit)}",
        "",
        f"📉 Break-even:    {fmt(result.breakeven_revenue)}",
    ]
    return "\n".join(lines)

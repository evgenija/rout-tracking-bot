"""
calculator.py — чиста бізнес-логіка P2 Finance Bot.
Не залежить від БД, Telegram або зовнішніх сервісів.
Всі коефіцієнти передаються ззовні як dict. Хардкод заборонено.

Три типи учасників:
- logistics: зовнішня компанія, тариф місто/область залежно від km
- own: власний водій (Трохімчук), фіксована ставка, без амортизації
- sales: sales managers, km вручну, амортизація вже в sales_cost_per_km

Ключі coefficients dict:
  margin_pct, monthly_shared, monthly_taxes, sales_salary_pct,
  logistics_city_rate, logistics_regional_rate,
  logistics_city_fixed_fee, logistics_city_threshold_km,
  own_driver_cost_per_km,
  sales_cost_per_km,
  effective_tax_rate, revenue_median_2025
"""
from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class DeliveryBreakdown:
    logistics_km: float
    logistics_cost: float
    own_km: float
    own_cost: float
    total: float


@dataclass
class BusinessResult:
    revenue: float
    cogs: float
    delivery: DeliveryBreakdown
    sales_km_cost: float   # sales_km × sales_cost_per_km, завжди ≥ 0
    sales_salary: float    # revenue × sales_salary_pct, завжди ≥ 0
    shared: float
    taxes: float
    net_profit: float
    breakeven_revenue: float


@dataclass
class RouteResult:
    revenue: float
    cogs: float
    delivery_cost: float
    sales_km_cost: float   # завжди ≥ 0
    sales_salary: float    # завжди ≥ 0
    operating_result: float


@dataclass
class DailyOpResult:
    date: date
    revenue: int
    cogs: float
    delivery_logistics: float
    delivery_own: float
    delivery_total: float
    sales_km_cost: float    # завжди ≥ 0
    sales_salary: float     # завжди ≥ 0
    op_profit: float
    sales_km: int
    sales_km_missing: bool  # True якщо sales_km=0 при revenue>0
    delivery_logistics_odo: float = 0.0
    delivery_own_odo: float = 0.0
    delivery_total_odo: float = 0.0
    op_profit_odo: float = 0.0


@dataclass
class WeeklyResult:
    week_start: date
    week_end: date
    revenue: float
    op_profit: float
    shared_week: float
    taxes_week: float
    net_profit: float
    breakeven_day: float
    revenue_vs_median_pct: Optional[float]  # None якщо немає медіани
    is_partial: bool
    missing_days: list
    days_in_week: int = 0
    working_days_in_month: int = 0
    monthly_fixed: float = 0.0
    delivery_total: float = 0.0
    delivery_total_odo: float = 0.0
    op_profit_odo: float = 0.0
    net_profit_odo: float = 0.0


@dataclass
class MonthlyResult:
    year: int
    month: int
    revenue: float
    cogs: float
    delivery_total: float
    sales_km_cost: float
    sales_salary: float
    op_profit: float
    shared: float
    taxes: float
    net_profit: float
    breakeven_day: float
    working_days: int
    revenue_vs_median_pct: Optional[float]
    is_partial: bool
    missing_days_count: int
    delivery_total_odo: float = 0.0
    op_profit_odo: float = 0.0
    net_profit_odo: float = 0.0


def _calc_logistics_cost(km: float, coefficients: dict) -> float:
    """Розрахунок вартості логістичної компанії за km."""
    threshold = coefficients["logistics_city_threshold_km"]
    if km <= threshold:
        return km * coefficients["logistics_city_rate"] + coefficients["logistics_city_fixed_fee"]
    return km * coefficients["logistics_regional_rate"]


def calc_delivery_cost_by_odo(odo_km: float, driver_type: str, coefficients: dict) -> float:
    """Вартість доставки за одометром. Та сама тарифна логіка що й final_km."""
    if driver_type == "logistics":
        return _calc_logistics_cost(odo_km, coefficients)
    return odo_km * coefficients["own_driver_cost_per_km"]


def business_mode(
    revenue: float,
    logistics_km: float,
    own_km: float,
    sales_km: float,
    days_in_month: int,
    coefficients: dict
) -> BusinessResult:
    """
    Business mode: розрахунок за один день.
    Sales розділений на два компоненти, обидва ≥ 0.
    Shared і Taxes діляться на кількість днів місяця.
    """
    margin_pct       = coefficients["margin_pct"]
    monthly_shared   = coefficients["monthly_shared"]
    monthly_taxes    = coefficients["monthly_taxes"]
    sales_salary_pct = coefficients["sales_salary_pct"]

    cogs = revenue * (1 - margin_pct)

    logistics_cost = _calc_logistics_cost(logistics_km, coefficients)
    own_cost = own_km * coefficients["own_driver_cost_per_km"]
    delivery = DeliveryBreakdown(
        logistics_km=logistics_km,
        logistics_cost=logistics_cost,
        own_km=own_km,
        own_cost=own_cost,
        total=logistics_cost + own_cost
    )

    sales_km_cost = sales_km * coefficients["sales_cost_per_km"]
    sales_salary  = revenue * sales_salary_pct
    shared = monthly_shared / days_in_month
    taxes  = monthly_taxes / days_in_month
    net_profit = revenue - cogs - delivery.total - sales_km_cost - sales_salary - shared - taxes
    breakeven_revenue = (monthly_shared + monthly_taxes) / margin_pct / days_in_month

    return BusinessResult(
        revenue=revenue, cogs=cogs, delivery=delivery,
        sales_km_cost=sales_km_cost, sales_salary=sales_salary,
        shared=shared, taxes=taxes,
        net_profit=net_profit, breakeven_revenue=breakeven_revenue
    )


def route_mode(
    route_revenue: float,
    route_km: float,
    driver_type: str,
    route_sales_km: float,
    coefficients: dict
) -> RouteResult:
    """
    Route mode: операційний результат одного маршруту.
    driver_type: 'logistics' або 'own'
    Sales розділений на два компоненти, обидва ≥ 0.
    Без Shared і Taxes.
    """
    margin_pct       = coefficients["margin_pct"]
    sales_salary_pct = coefficients["sales_salary_pct"]

    cogs = route_revenue * (1 - margin_pct)

    if driver_type == "logistics":
        delivery_cost = _calc_logistics_cost(route_km, coefficients)
    elif driver_type == "own":
        delivery_cost = route_km * coefficients["own_driver_cost_per_km"]
    else:
        raise ValueError(f"Невідомий driver_type: {driver_type}. Очікується 'logistics' або 'own'.")

    sales_km_cost = route_sales_km * coefficients["sales_cost_per_km"]
    sales_salary  = route_revenue * sales_salary_pct
    operating_result = route_revenue - cogs - delivery_cost - sales_km_cost - sales_salary

    return RouteResult(
        revenue=route_revenue, cogs=cogs,
        delivery_cost=delivery_cost,
        sales_km_cost=sales_km_cost, sales_salary=sales_salary,
        operating_result=operating_result
    )


def select_final_km(
    tracking_km: float,
    odometer_km: float | None,
    coefficients: dict
) -> tuple[float, str]:
    """
    Вибір final_km для розрахунку вартості маршруту.
    Пороги читаються з coefficients, не хардкодяться.
    Повертає (km, reason).
    """
    over_tracking = coefficients.get('odometer_over_tracking_threshold', 0.05)
    over_odometer = coefficients.get('tracking_over_odometer_threshold', 0.03)

    if odometer_km is None:
        return tracking_km, 'odometer_missing'
    if tracking_km == 0:
        return odometer_km, 'tracking_zero'

    diff_pct = (odometer_km - tracking_km) / tracking_km

    if abs(diff_pct) <= over_tracking:
        return odometer_km, 'within_tolerance'
    if diff_pct > over_tracking:
        return tracking_km, 'odometer_inflated'
    if diff_pct <= -over_odometer:
        return odometer_km, 'gps_noise'

    return odometer_km, 'within_tolerance'


def historical_mode(
    revenue: float,
    logistics_km: float,
    own_km: float,
    sales_km: float,
    coefficients: dict
) -> BusinessResult:
    """
    Historical mode: розрахунок за повний місяць.
    Shared і Taxes — повні суми (не ділити на дні).
    """
    margin_pct       = coefficients["margin_pct"]
    monthly_shared   = coefficients["monthly_shared"]
    monthly_taxes    = coefficients["monthly_taxes"]
    sales_salary_pct = coefficients["sales_salary_pct"]

    cogs = revenue * (1 - margin_pct)

    logistics_cost = _calc_logistics_cost(logistics_km, coefficients)
    own_cost = own_km * coefficients["own_driver_cost_per_km"]
    delivery = DeliveryBreakdown(
        logistics_km=logistics_km,
        logistics_cost=logistics_cost,
        own_km=own_km,
        own_cost=own_cost,
        total=logistics_cost + own_cost
    )

    sales_km_cost = sales_km * coefficients["sales_cost_per_km"]
    sales_salary  = revenue * sales_salary_pct
    net_profit = revenue - cogs - delivery.total - sales_km_cost - sales_salary - monthly_shared - monthly_taxes
    breakeven_revenue = (monthly_shared + monthly_taxes) / margin_pct

    return BusinessResult(
        revenue=revenue, cogs=cogs, delivery=delivery,
        sales_km_cost=sales_km_cost, sales_salary=sales_salary,
        shared=monthly_shared, taxes=monthly_taxes,
        net_profit=net_profit, breakeven_revenue=breakeven_revenue
    )


def calculate_daily_op_profit(
    revenue: int,
    sales_km: int,
    delivery_logistics: float,
    delivery_own: float,
    report_date: date,
    coefficients: dict,
) -> DailyOpResult:
    """
    Операційний прибуток за день (без Shared і Taxes).
    delivery_logistics / delivery_own — агреговані суми з daily_input за дату.
    """
    margin_pct       = coefficients["margin_pct"]
    sales_salary_pct = coefficients["sales_salary_pct"]

    cogs          = revenue * (1 - margin_pct)
    delivery_total = delivery_logistics + delivery_own
    sales_km_cost = sales_km * coefficients["sales_cost_per_km"]
    sales_salary  = revenue * sales_salary_pct
    op_profit     = revenue - cogs - delivery_total - sales_km_cost - sales_salary

    return DailyOpResult(
        date=report_date,
        revenue=revenue,
        cogs=cogs,
        delivery_logistics=delivery_logistics,
        delivery_own=delivery_own,
        delivery_total=delivery_total,
        sales_km_cost=sales_km_cost,
        sales_salary=sales_salary,
        op_profit=op_profit,
        sales_km=sales_km,
        sales_km_missing=(sales_km == 0),
    )


def calculate_weekly_net_profit(
    week_start: date,
    week_end: date,
    daily_results: list,   # список DailyOpResult за тиждень
    working_days_in_month: int,
    coefficients: dict,
) -> WeeklyResult:
    """
    Тижневий Net Profit = Σ Op.Profit − Shared_week − Taxes_week.
    Shared_week пропорційний до кількості робочих днів тижня у місяці.
    Taxes_week = Revenue_week × effective_tax_rate.
    """
    monthly_shared    = coefficients["monthly_shared"]
    effective_tax_rate = coefficients.get("effective_tax_rate", 0.0)
    revenue_median    = coefficients.get("revenue_median_2025", 0.0)

    days_in_week       = len(daily_results)
    revenue_week       = sum(r.revenue for r in daily_results)
    op_profit_sum      = sum(r.op_profit for r in daily_results)
    delivery_total     = sum(r.delivery_total for r in daily_results)
    delivery_total_odo = sum(r.delivery_total_odo for r in daily_results)
    op_profit_odo_sum  = sum(r.op_profit_odo for r in daily_results)

    shared_week    = monthly_shared * (days_in_week / working_days_in_month) if working_days_in_month > 0 else 0.0
    taxes_week     = revenue_week * effective_tax_rate
    net_profit     = op_profit_sum - shared_week - taxes_week
    net_profit_odo = op_profit_odo_sum - shared_week - taxes_week

    breakeven_day = (
        (coefficients["monthly_shared"] + coefficients["monthly_taxes"])
        / coefficients["margin_pct"] / working_days_in_month
        if working_days_in_month > 0 else 0.0
    )

    weekly_median = revenue_median / 4.33
    revenue_vs_median = (
        (revenue_week / weekly_median - 1) * 100
        if weekly_median > 0 else None
    )

    monthly_fixed = coefficients["monthly_shared"] + coefficients["monthly_taxes"]

    return WeeklyResult(
        week_start=week_start,
        week_end=week_end,
        revenue=revenue_week,
        op_profit=op_profit_sum,
        shared_week=shared_week,
        taxes_week=taxes_week,
        net_profit=net_profit,
        breakeven_day=breakeven_day,
        revenue_vs_median_pct=revenue_vs_median,
        is_partial=False,
        missing_days=[],
        days_in_week=days_in_week,
        working_days_in_month=working_days_in_month,
        monthly_fixed=monthly_fixed,
        delivery_total=delivery_total,
        delivery_total_odo=delivery_total_odo,
        op_profit_odo=op_profit_odo_sum,
        net_profit_odo=net_profit_odo,
    )


def calculate_monthly_net_profit(
    year: int,
    month: int,
    daily_results: list,   # список DailyOpResult за місяць
    working_days: int,
    coefficients: dict,
    missing_days_count: int = 0,
) -> MonthlyResult:
    """
    Місячний Net Profit = Σ Op.Profit − monthly_shared − monthly_taxes.
    """
    margin_pct       = coefficients["margin_pct"]
    monthly_shared   = coefficients["monthly_shared"]
    monthly_taxes    = coefficients["monthly_taxes"]
    revenue_median   = coefficients.get("revenue_median_2025", 0.0)

    revenue            = sum(r.revenue for r in daily_results)
    cogs               = sum(r.cogs for r in daily_results)
    delivery_total     = sum(r.delivery_total for r in daily_results)
    delivery_total_odo = sum(r.delivery_total_odo for r in daily_results)
    sales_km_cost      = sum(r.sales_km_cost for r in daily_results)
    sales_salary       = sum(r.sales_salary for r in daily_results)
    op_profit          = sum(r.op_profit for r in daily_results)
    op_profit_odo      = sum(r.op_profit_odo for r in daily_results)
    net_profit         = op_profit - monthly_shared - monthly_taxes
    net_profit_odo     = op_profit_odo - monthly_shared - monthly_taxes

    breakeven_day = (
        (monthly_shared + monthly_taxes) / margin_pct / working_days
        if working_days > 0 else 0.0
    )
    revenue_vs_median = (
        (revenue / revenue_median - 1) * 100
        if revenue_median > 0 else None
    )

    return MonthlyResult(
        year=year, month=month,
        revenue=revenue, cogs=cogs,
        delivery_total=delivery_total,
        sales_km_cost=sales_km_cost,
        sales_salary=sales_salary,
        op_profit=op_profit,
        shared=monthly_shared, taxes=monthly_taxes,
        net_profit=net_profit,
        breakeven_day=breakeven_day,
        working_days=working_days,
        revenue_vs_median_pct=revenue_vs_median,
        is_partial=(missing_days_count > 0),
        missing_days_count=missing_days_count,
        delivery_total_odo=delivery_total_odo,
        op_profit_odo=op_profit_odo,
        net_profit_odo=net_profit_odo,
    )

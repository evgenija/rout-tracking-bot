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
  sales_cost_per_km
"""
from dataclasses import dataclass, field


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
    sales: float
    shared: float
    taxes: float
    net_profit: float
    breakeven_revenue: float


@dataclass
class RouteResult:
    revenue: float
    cogs: float
    delivery_cost: float
    sales: float
    operating_result: float


def _calc_logistics_cost(km: float, coefficients: dict) -> float:
    """Розрахунок вартості логістичної компанії за km."""
    threshold = coefficients["logistics_city_threshold_km"]
    if km <= threshold:
        return km * coefficients["logistics_city_rate"] + coefficients["logistics_city_fixed_fee"]
    return km * coefficients["logistics_regional_rate"]


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
    В один день можуть бути одночасно logistics_km + own_km + sales_km.
    Shared і Taxes діляться на кількість днів місяця.
    """
    margin_pct = coefficients["margin_pct"]
    monthly_shared = coefficients["monthly_shared"]
    monthly_taxes = coefficients["monthly_taxes"]
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

    sales = (sales_km * coefficients["sales_cost_per_km"]) - (revenue * sales_salary_pct)
    shared = monthly_shared / days_in_month
    taxes = monthly_taxes / days_in_month
    net_profit = revenue - cogs - delivery.total - sales - shared - taxes
    breakeven_revenue = (monthly_shared + monthly_taxes) / margin_pct / days_in_month

    return BusinessResult(
        revenue=revenue, cogs=cogs, delivery=delivery,
        sales=sales, shared=shared, taxes=taxes,
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
    route_sales_km: km sales managers за цей маршрут, вводиться вручну.
    Без Shared і Taxes.
    """
    margin_pct = coefficients["margin_pct"]
    sales_salary_pct = coefficients["sales_salary_pct"]

    cogs = route_revenue * (1 - margin_pct)

    if driver_type == "logistics":
        delivery_cost = _calc_logistics_cost(route_km, coefficients)
    elif driver_type == "own":
        delivery_cost = route_km * coefficients["own_driver_cost_per_km"]
    else:
        raise ValueError(f"Невідомий driver_type: {driver_type}. Очікується 'logistics' або 'own'.")

    sales = (route_sales_km * coefficients["sales_cost_per_km"]) - (route_revenue * sales_salary_pct)
    operating_result = route_revenue - cogs - delivery_cost - sales

    return RouteResult(
        revenue=route_revenue, cogs=cogs,
        delivery_cost=delivery_cost, sales=sales,
        operating_result=operating_result
    )


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
    margin_pct = coefficients["margin_pct"]
    monthly_shared = coefficients["monthly_shared"]
    monthly_taxes = coefficients["monthly_taxes"]
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

    sales = (sales_km * coefficients["sales_cost_per_km"]) - (revenue * sales_salary_pct)
    net_profit = revenue - cogs - delivery.total - sales - monthly_shared - monthly_taxes
    breakeven_revenue = (monthly_shared + monthly_taxes) / margin_pct

    return BusinessResult(
        revenue=revenue, cogs=cogs, delivery=delivery,
        sales=sales, shared=monthly_shared, taxes=monthly_taxes,
        net_profit=net_profit, breakeven_revenue=breakeven_revenue
    )

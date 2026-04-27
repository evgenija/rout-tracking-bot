"""
test_calculator.py — smoke + regression тести для calculator.py.
Перевіряє фінансову логіку з реальними коефіцієнтами з БД.
Усі очікувані значення розраховані вручну і задокументовані.
"""
import pytest
from bot.services.calculator import business_mode, route_mode, select_final_km, _calc_logistics_cost

# Реальні коефіцієнти (відповідають поточному стану БД + обрахований sales_cost_per_km)
REAL_COEFFICIENTS = {
    "margin_pct": 0.3,
    "monthly_shared": 292555.0,
    "monthly_taxes": 14549.0,
    "sales_salary_pct": 0.035,
    "logistics_city_rate": 12.2,
    "logistics_regional_rate": 20.0,
    "logistics_city_fixed_fee": 3000.0,
    "logistics_city_threshold_km": 386.0,
    "own_driver_cost_per_km": 18.5,
    "sales_cost_per_km": 5.7944,  # (7/100*72.71 + 10/100*48.99)/2 + 0.80
    "odometer_over_tracking_threshold": 0.05,
    "tracking_over_odometer_threshold": 0.03,
}


# ── _calc_logistics_cost ──────────────────────────────────────────────────────

def test_logistics_city_rate():
    # 200 км ≤ 386 (поріг) → міський тариф: 200*12.2 + 3000 = 5440
    cost = _calc_logistics_cost(200.0, REAL_COEFFICIENTS)
    assert abs(cost - 5440.0) < 0.01


def test_logistics_regional_rate():
    # 400 км > 386 → обласний тариф: 400*20.0 = 8000
    cost = _calc_logistics_cost(400.0, REAL_COEFFICIENTS)
    assert abs(cost - 8000.0) < 0.01


def test_logistics_city_boundary_exact():
    # Рівно 386 км → місто: 386*12.2 + 3000 = 7709.2
    cost = _calc_logistics_cost(386.0, REAL_COEFFICIENTS)
    assert abs(cost - 7709.2) < 0.01


def test_logistics_regional_boundary_over():
    # 387 км > 386 → область: 387*20.0 = 7740
    cost = _calc_logistics_cost(387.0, REAL_COEFFICIENTS)
    assert abs(cost - 7740.0) < 0.01


# ── business_mode ─────────────────────────────────────────────────────────────

def test_business_mode_smoke():
    """
    revenue=100000, logistics_km=200, own_km=50, sales_km=100, days=30
    COGS = 70000
    logistics_cost = 5440, own_cost = 925, delivery = 6365
    sales = 100*5.7944 - 100000*0.035 = 579.44 - 3500 = -2920.56
    shared = 292555/30 = 9751.83, taxes = 14549/30 = 484.97
    net_profit = 100000 - 70000 - 6365 + 2920.56 - 9751.83 - 484.97 ≈ 16318.76
    breakeven = (292555+14549)/0.3/30 = 34122.67
    """
    result = business_mode(
        revenue=100000.0,
        logistics_km=200.0,
        own_km=50.0,
        sales_km=100.0,
        days_in_month=30,
        coefficients=REAL_COEFFICIENTS,
    )
    assert abs(result.cogs - 70000.0) < 0.01
    assert abs(result.delivery.logistics_cost - 5440.0) < 0.01
    assert abs(result.delivery.own_cost - 925.0) < 0.01
    assert abs(result.delivery.total - 6365.0) < 0.01
    assert abs(result.sales - (-2920.56)) < 0.01
    assert abs(result.net_profit - 16318.76) < 1.0
    assert abs(result.breakeven_revenue - 34122.67) < 1.0


def test_business_mode_sales_can_be_negative():
    # Sales може бути від'ємним (ставка salary_pct > km-компенсація) — це нормально
    result = business_mode(
        revenue=500000.0,
        logistics_km=10.0,
        own_km=0.0,
        sales_km=5.0,
        days_in_month=30,
        coefficients=REAL_COEFFICIENTS,
    )
    assert result.sales < 0  # 5*5.7944 - 500000*0.035 явно < 0


def test_business_mode_regional_logistics():
    # logistics_km=400 (> 386) → обласний тариф 20/км
    result = business_mode(
        revenue=100000.0,
        logistics_km=400.0,
        own_km=0.0,
        sales_km=0.0,
        days_in_month=31,
        coefficients=REAL_COEFFICIENTS,
    )
    assert abs(result.delivery.logistics_cost - 8000.0) < 0.01


# ── route_mode ────────────────────────────────────────────────────────────────

def test_route_mode_logistics_city():
    """
    route_revenue=50000, route_km=100, logistics city, sales_km=50
    COGS = 35000
    delivery = 100*12.2+3000 = 4220
    sales = 50*5.7944 - 50000*0.035 = 289.72 - 1750 = -1460.28
    operating = 50000 - 35000 - 4220 + 1460.28 = 12240.28
    """
    result = route_mode(
        route_revenue=50000.0,
        route_km=100.0,
        driver_type="logistics",
        route_sales_km=50.0,
        coefficients=REAL_COEFFICIENTS,
    )
    assert abs(result.cogs - 35000.0) < 0.01
    assert abs(result.delivery_cost - 4220.0) < 0.01
    assert abs(result.operating_result - 12240.28) < 1.0


def test_route_mode_own_driver():
    # own: 80 km * 18.5 = 1480
    result = route_mode(
        route_revenue=30000.0,
        route_km=80.0,
        driver_type="own",
        route_sales_km=0.0,
        coefficients=REAL_COEFFICIENTS,
    )
    assert abs(result.delivery_cost - 1480.0) < 0.01


def test_route_mode_unknown_driver_raises():
    with pytest.raises(ValueError, match="Невідомий driver_type"):
        route_mode(100000, 100, "unknown", 0, REAL_COEFFICIENTS)


# ── select_final_km ───────────────────────────────────────────────────────────

def test_select_final_km_within_tolerance():
    km, reason = select_final_km(100.0, 103.0, REAL_COEFFICIENTS)
    assert reason == "within_tolerance"
    assert km == 103.0


def test_select_final_km_odometer_inflated():
    # odometer >> tracking > 5% → рахуємо за tracking
    km, reason = select_final_km(100.0, 110.0, REAL_COEFFICIENTS)
    assert reason == "odometer_inflated"
    assert km == 100.0


def test_select_final_km_no_odometer():
    km, reason = select_final_km(100.0, None, REAL_COEFFICIENTS)
    assert reason == "odometer_missing"
    assert km == 100.0

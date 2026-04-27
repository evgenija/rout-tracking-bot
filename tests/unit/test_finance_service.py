"""
test_finance_service.py — unit тести для finance_service.py та calculator нових функцій.
Використовує AsyncMock замість реального PostgreSQL.
"""
import pytest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

from bot.services.calculator import (
    calculate_daily_op_profit,
    calculate_weekly_net_profit,
    calculate_monthly_net_profit,
    DailyOpResult,
)

COEFFS = {
    "margin_pct": 0.3,
    "monthly_shared": 292555.0,
    "monthly_taxes": 14549.0,
    "sales_salary_pct": 0.035,
    "logistics_city_rate": 12.2,
    "logistics_regional_rate": 20.0,
    "logistics_city_fixed_fee": 3000.0,
    "logistics_city_threshold_km": 386.0,
    "own_driver_cost_per_km": 18.5,
    "sales_cost_per_km": 5.7944,
    "effective_tax_rate": 0.00216,
    "revenue_median_2025": 6737667.0,
}


# ── calculate_daily_op_profit ─────────────────────────────────────────────────

def test_daily_op_profit_formula():
    """
    revenue=1_000_000, sales_km=600, logistics=20_000, own=5_000
    cogs = 700_000
    sales_km_cost = 600*5.7944 = 3476.64
    sales_salary  = 1_000_000*0.035 = 35_000
    op_profit = 1_000_000 - 700_000 - 25_000 - 3476.64 - 35_000 = 236_523.36
    """
    r = calculate_daily_op_profit(
        revenue=1_000_000,
        sales_km=600,
        delivery_logistics=20_000.0,
        delivery_own=5_000.0,
        report_date=date(2026, 4, 21),
        coefficients=COEFFS,
    )
    assert abs(r.cogs - 700_000) < 0.01
    assert abs(r.sales_km_cost - 3476.64) < 0.1
    assert abs(r.sales_salary - 35_000) < 0.01
    assert abs(r.op_profit - 236_523.36) < 1.0
    assert r.sales_km_missing is False


def test_daily_op_profit_no_delivery():
    r = calculate_daily_op_profit(
        revenue=500_000, sales_km=0,
        delivery_logistics=0.0, delivery_own=0.0,
        report_date=date(2026, 4, 22), coefficients=COEFFS,
    )
    assert r.delivery_total == 0.0
    assert r.sales_km_missing is True
    # op_profit = 500k - 350k - 0 - 0 - 17500 = 132500
    assert abs(r.op_profit - 132_500) < 1.0


def test_daily_op_profit_sales_components_always_nonnegative():
    r = calculate_daily_op_profit(
        revenue=10_000_000, sales_km=1,
        delivery_logistics=0.0, delivery_own=0.0,
        report_date=date(2026, 4, 23), coefficients=COEFFS,
    )
    assert r.sales_km_cost >= 0
    assert r.sales_salary >= 0


# ── calculate_weekly_net_profit ───────────────────────────────────────────────

def _make_daily(revenue: int, sales_km: int = 0) -> DailyOpResult:
    return calculate_daily_op_profit(
        revenue=revenue, sales_km=sales_km,
        delivery_logistics=10_000.0, delivery_own=2_000.0,
        report_date=date(2026, 4, 21), coefficients=COEFFS,
    )


def test_weekly_net_profit_formula():
    """
    3 дні × 850k виручка = 2_550_000
    op_profit_day ≈ (850k - 595k - 12k - 0 - 29750) = 213250 × 3 = 639750
    shared_week = 292555 * (3/22) = 39893.86
    taxes_week  = 2_550_000 * 0.00216 = 5508
    net = 639750 - 39893.86 - 5508 ≈ 594348
    """
    days = [_make_daily(850_000) for _ in range(3)]
    result = calculate_weekly_net_profit(
        week_start=date(2026, 4, 21),
        week_end=date(2026, 4, 26),
        daily_results=days,
        working_days_in_month=22,
        coefficients=COEFFS,
    )
    assert result.revenue == 3 * 850_000
    assert abs(result.shared_week - 292555 * 3 / 22) < 1.0
    assert abs(result.taxes_week - 3 * 850_000 * 0.00216) < 1.0
    assert result.net_profit < result.op_profit
    assert result.revenue_vs_median_pct is not None


def test_weekly_no_data_returns_zero_net():
    result = calculate_weekly_net_profit(
        week_start=date(2026, 4, 21),
        week_end=date(2026, 4, 26),
        daily_results=[],
        working_days_in_month=22,
        coefficients=COEFFS,
    )
    assert result.revenue == 0
    assert result.net_profit == 0 - result.shared_week - result.taxes_week


# ── calculate_monthly_net_profit ──────────────────────────────────────────────

def test_monthly_net_profit_formula():
    days = [_make_daily(850_000) for _ in range(22)]
    result = calculate_monthly_net_profit(
        year=2026, month=4,
        daily_results=days,
        working_days=22,
        coefficients=COEFFS,
        missing_days_count=0,
    )
    assert result.is_partial is False
    assert abs(result.shared - 292555.0) < 0.01
    assert abs(result.taxes - 14549.0) < 0.01
    assert result.net_profit == result.op_profit - 292555.0 - 14549.0


def test_monthly_partial_flag():
    days = [_make_daily(850_000) for _ in range(15)]
    result = calculate_monthly_net_profit(
        year=2026, month=4, daily_results=days,
        working_days=22, coefficients=COEFFS, missing_days_count=7,
    )
    assert result.is_partial is True
    assert result.missing_days_count == 7


def test_monthly_revenue_vs_median():
    days = [_make_daily(6_737_667) for _ in range(1)]
    result = calculate_monthly_net_profit(
        year=2026, month=4, daily_results=days,
        working_days=22, coefficients=COEFFS,
    )
    # revenue = медіана → ~0%
    assert result.revenue_vs_median_pct is not None
    assert abs(result.revenue_vs_median_pct) < 0.01


# ── finance_service helpers ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_delivery_totals_no_pool():
    from bot.services.finance_service import get_delivery_totals_for_date
    logistics, own = await get_delivery_totals_for_date(None, date(2026, 4, 27))
    assert logistics == 0.0
    assert own == 0.0


@pytest.mark.asyncio
async def test_get_revenue_for_date_no_pool():
    from bot.services.finance_service import get_revenue_for_date
    result = await get_revenue_for_date(None, date(2026, 4, 27))
    assert result is None


@pytest.mark.asyncio
async def test_save_period_input_no_pool():
    from bot.services.finance_service import save_period_input
    ok = await save_period_input(None, date(2026, 4, 1), date(2026, 4, 1), 850000, 550)
    assert ok is False


@pytest.mark.asyncio
async def test_get_delivery_totals_from_mock_pool():
    from bot.services.finance_service import get_delivery_totals_for_date

    mock_conn = AsyncMock()
    mock_conn.fetch.return_value = [
        {"driver_type": "logistics", "total_cost": 15000.0},
        {"driver_type": "own",       "total_cost": 3000.0},
    ]
    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__  = AsyncMock(return_value=False)

    logistics, own = await get_delivery_totals_for_date(mock_pool, date(2026, 4, 27))
    assert logistics == 15000.0
    assert own == 3000.0


@pytest.mark.asyncio
async def test_get_revenue_for_date_from_mock_pool():
    from bot.services.finance_service import get_revenue_for_date

    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = {"revenue": 850000, "sales_km": 550}
    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__  = AsyncMock(return_value=False)

    result = await get_revenue_for_date(mock_pool, date(2026, 4, 27))
    assert result == {"revenue": 850000, "sales_km": 550}


@pytest.mark.asyncio
async def test_get_revenue_for_date_not_found():
    from bot.services.finance_service import get_revenue_for_date

    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = None
    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__  = AsyncMock(return_value=False)

    result = await get_revenue_for_date(mock_pool, date(2026, 4, 27))
    assert result is None

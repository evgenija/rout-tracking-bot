"""
Regression тест: подвійний фініш маршруту (баг 30.04.2026).
Перевіряє що другий виклик on_route_finished для того ж route_id
оновлює існуючий рядок (UPDATE), а не додає новий (INSERT).
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.services.calculator import _calc_logistics_cost


COEFFICIENTS = {
    "logistics_city_rate": 12.2,
    "logistics_regional_rate": 20.0,
    "logistics_city_fixed_fee": 3000.0,
    "logistics_city_threshold_km": 386.0,
    "own_driver_cost_per_km": 18.5,
    "odometer_over_tracking_threshold": 0.05,
    "tracking_over_odometer_threshold": 0.03,
}


def test_fixed_fee_charged_twice_without_guard():
    """Без захисту: fixed_fee нараховується двічі при двох окремих INSERT."""
    km1, km2 = 97.85, 17.69
    cost_separate = _calc_logistics_cost(km1, COEFFICIENTS) + _calc_logistics_cost(km2, COEFFICIENTS)
    cost_merged = _calc_logistics_cost(km1 + km2, COEFFICIENTS)
    assert abs(cost_separate - 7409.59) < 0.1
    assert abs(cost_merged - 4409.59) < 0.1
    # Різниця = рівно одна зайва фіксована надбавка
    assert abs(cost_separate - cost_merged - 3000.0) < 0.1


@pytest.mark.asyncio
async def test_on_route_finished_continuation_updates_not_inserts():
    """Другий on_route_finished для того ж route_id → UPDATE, не INSERT."""
    from bot.services.route_cost_service import on_route_finished

    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = {"id": 77, "km": 97.85}

    mock_acquire = MagicMock()
    mock_acquire.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_acquire.__aexit__ = AsyncMock(return_value=None)

    mock_pool = MagicMock()
    mock_pool.acquire.return_value = mock_acquire
    mock_bot = AsyncMock()

    await on_route_finished(
        route_id=125,
        driver_id=486855930,
        driver_type="logistics",
        tracking_km=17.69,
        odometer_km=None,
        driver_name="Жека",
        coefficients=COEFFICIENTS,
        pg_pool=mock_pool,
        bot=mock_bot,
    )

    mock_conn.execute.assert_called_once()
    call_sql = mock_conn.execute.call_args[0][0]
    assert "UPDATE daily_input" in call_sql, f"Очікувався UPDATE, отримано: {call_sql}"

    total_km = mock_conn.execute.call_args[0][1]
    total_cost = mock_conn.execute.call_args[0][2]
    assert abs(total_km - 115.54) < 0.01, f"Очікувалось 115.54 км, отримано {total_km}"
    assert abs(total_cost - 4409.59) < 0.1, f"Очікувалось 4409.59 грн, отримано {total_cost}"


@pytest.mark.asyncio
async def test_on_route_finished_first_call_inserts():
    """Перший on_route_finished для нового route_id → INSERT."""
    from bot.services.route_cost_service import on_route_finished

    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = None  # запис не існує

    mock_acquire = MagicMock()
    mock_acquire.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_acquire.__aexit__ = AsyncMock(return_value=None)

    mock_pool = MagicMock()
    mock_pool.acquire.return_value = mock_acquire
    mock_bot = AsyncMock()

    await on_route_finished(
        route_id=999,
        driver_id=486855930,
        driver_type="logistics",
        tracking_km=97.85,
        odometer_km=None,
        driver_name="Жека",
        coefficients=COEFFICIENTS,
        pg_pool=mock_pool,
        bot=mock_bot,
    )

    mock_conn.execute.assert_called_once()
    call_sql = mock_conn.execute.call_args[0][0]
    assert "INSERT INTO daily_input" in call_sql, f"Очікувався INSERT, отримано: {call_sql}"

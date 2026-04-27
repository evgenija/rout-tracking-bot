"""
test_coefficients_service.py — перевіряє динамічне обрахування sales_cost_per_km.
sales_cost_per_km не зберігається в БД — обраховується в CoefficientsService._load().
"""
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.services.coefficients_service import CoefficientsService


def _make_pool(db_rows: dict) -> MagicMock:
    """Мок pg_pool що повертає задані рядки з coefficients."""
    mock_conn = AsyncMock()
    mock_conn.fetch.return_value = [{"key": k, "value": v} for k, v in db_rows.items()]
    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return mock_pool


@pytest.mark.asyncio
async def test_sales_cost_per_km_computed_from_components():
    """
    З реальних цін:
      a95_cost = 7.0/100 * 72.71 = 5.0897
      lpg_cost = 10.0/100 * 48.99 = 4.899
      avg = (5.0897 + 4.899) / 2 = 4.9944
      + amort 0.80 → sales_cost_per_km = 5.7944
    """
    pool = _make_pool({
        "fuel_price_a95": 72.71,
        "fuel_price_lpg": 48.99,
        "fuel_consumption_a95": 7.0,
        "fuel_consumption_lpg": 10.0,
        "sales_amortization_per_km": 0.80,
    })
    svc = CoefficientsService(pool)
    coeffs = await svc.get()
    assert abs(coeffs["sales_cost_per_km"] - 5.7944) < 0.001


@pytest.mark.asyncio
async def test_sales_cost_per_km_higher_prices_give_higher_cost():
    """Вищі ціни → вищий sales_cost_per_km.
    new: (7/100*80.00 + 10/100*55.00)/2 + 0.80 = (5.60+5.50)/2 + 0.80 = 6.35
    """
    pool_old = _make_pool({
        "fuel_price_a95": 72.71, "fuel_price_lpg": 48.99,
        "fuel_consumption_a95": 7.0, "fuel_consumption_lpg": 10.0,
        "sales_amortization_per_km": 0.80,
    })
    pool_new = _make_pool({
        "fuel_price_a95": 80.00, "fuel_price_lpg": 55.00,
        "fuel_consumption_a95": 7.0, "fuel_consumption_lpg": 10.0,
        "sales_amortization_per_km": 0.80,
    })
    old_cost = (await CoefficientsService(pool_old).get())["sales_cost_per_km"]
    new_cost = (await CoefficientsService(pool_new).get())["sales_cost_per_km"]

    assert new_cost > old_cost
    assert abs(new_cost - 6.35) < 0.01


@pytest.mark.asyncio
async def test_sales_cost_uses_fallback_defaults():
    """Якщо компоненти відсутні в БД — fallback до захардкоджених дефолтів."""
    pool = _make_pool({})  # порожня БД
    svc = CoefficientsService(pool)
    coeffs = await svc.get()
    expected = (7.0 / 100 * 72.71 + 10.0 / 100 * 48.99) / 2 + 0.80
    assert abs(coeffs["sales_cost_per_km"] - expected) < 0.001


@pytest.mark.asyncio
async def test_sales_cost_per_km_not_stored_in_db():
    """sales_cost_per_km відсутній у сирих даних БД — тільки в обрахованому кеші."""
    pool = _make_pool({"fuel_price_a95": 72.71, "fuel_price_lpg": 48.99})
    svc = CoefficientsService(pool)
    await svc.get()
    # Перевіряємо що в сирих рядках БД цього ключа немає
    conn = await pool.acquire().__aenter__()
    raw_rows = conn.fetch.return_value
    raw_keys = [r["key"] for r in raw_rows]
    assert "sales_cost_per_km" not in raw_keys


@pytest.mark.asyncio
async def test_cache_not_reloaded_within_ttl():
    """get() не звертається до БД якщо кеш ще актуальний (не expired)."""
    fetch_count = 0
    original_load = CoefficientsService._load

    async def counted_load(self):
        nonlocal fetch_count
        fetch_count += 1
        await original_load(self)

    pool = _make_pool({"margin_pct": 0.3})
    svc = CoefficientsService(pool)

    with patch.object(CoefficientsService, "_load", counted_load):
        await svc.get()
        await svc.get()  # другий виклик — кеш актуальний → DB не викликається

    assert fetch_count == 1


@pytest.mark.asyncio
async def test_refresh_forces_reload():
    """refresh() скидає кеш і завантажує з БД."""
    fetch_count = 0
    original_load = CoefficientsService._load

    async def counted_load(self):
        nonlocal fetch_count
        fetch_count += 1
        await original_load(self)

    pool = _make_pool({"margin_pct": 0.3})
    svc = CoefficientsService(pool)

    with patch.object(CoefficientsService, "_load", counted_load):
        await svc.get()
        await svc.refresh()

    assert fetch_count == 2

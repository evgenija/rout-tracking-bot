"""
Тести для p2_report_service.py.
Smoke: get_p2_daily_by_date з pg_pool=None → {}
Fallback: порожній daily_input → format_payment_line(None) → ⏳
Regression: формат payment_line стабільний
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.services.p2_report_service import get_p2_daily_by_date, format_payment_line


# ── get_p2_daily_by_date ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_no_pg_pool_returns_empty():
    result = await get_p2_daily_by_date(None, "2026-04-24")
    assert result == {}


@pytest.mark.asyncio
async def test_returns_dict_keyed_by_driver_id():
    mock_pool = MagicMock()
    mock_conn = AsyncMock()
    mock_conn.fetch.return_value = [
        {"driver_id": 111, "total_km": 85.5, "total_cost": 1710.0, "driver_type": "logistics"},
        {"driver_id": 222, "total_km": 42.0, "total_cost": 777.0, "driver_type": "own"},
    ]
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__  = AsyncMock(return_value=False)

    result = await get_p2_daily_by_date(mock_pool, "2026-04-24")

    assert 111 in result
    assert 222 in result
    assert result[111]["km"]   == 85.5
    assert result[111]["cost"] == 1710.0
    assert result[222]["driver_type"] == "own"


@pytest.mark.asyncio
async def test_empty_daily_input_returns_empty_dict():
    mock_pool = MagicMock()
    mock_conn = AsyncMock()
    mock_conn.fetch.return_value = []
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__  = AsyncMock(return_value=False)

    result = await get_p2_daily_by_date(mock_pool, "2026-04-24")
    assert result == {}


@pytest.mark.asyncio
async def test_pg_error_returns_empty():
    mock_pool = MagicMock()
    mock_conn = AsyncMock()
    mock_conn.fetch.side_effect = Exception("connection refused")
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__  = AsyncMock(return_value=False)

    result = await get_p2_daily_by_date(mock_pool, "2026-04-24")
    assert result == {}


# ── format_payment_line ───────────────────────────────────────────────────────

def test_no_p2_entry_shows_pending():
    line = format_payment_line(None)
    assert line == "⏳ Оплата не розрахована"


def test_logistics_entry_format():
    entry = {"km": 85.5, "cost": 1710.0, "driver_type": "logistics"}
    line = format_payment_line(entry)
    assert "💰" in line
    assert "логістика" in line
    assert "1 710" in line or "1710" in line
    assert "85.5" in line


def test_own_driver_entry_format():
    entry = {"km": 42.0, "cost": 777.0, "driver_type": "own"}
    line = format_payment_line(entry)
    assert "власний водій" in line
    assert "777" in line


def test_zero_cost_still_shows_line():
    entry = {"km": 10.0, "cost": 0.0, "driver_type": "own"}
    line = format_payment_line(entry)
    assert "💰" in line
    assert line != "⏳ Оплата не розрахована"

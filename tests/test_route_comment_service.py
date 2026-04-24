from unittest.mock import patch

import pytest

from bot.services.route_comment_service import (
    get_route_comment,
    _POOL_NORM,
    _POOL_CHECK,
    _POOL_CRITICAL,
    _POOL_GOOD,
    _POOL_WOW,
)

NAME = "Іван"


@pytest.mark.parametrize("tracking,odometer,expected_pool", [
    (100.0, 100.0, _POOL_NORM),    # norm — однакові
    (100.0, 105.0, _POOL_NORM),    # norm — межа 5%
    (100.0, 110.0, _POOL_CHECK),   # check — 10%
    (100.0, 114.0, _POOL_CHECK),   # check — межа 14%
    (100.0, 120.0, _POOL_CRITICAL),# critical — 20%
    (100.0,  92.0, _POOL_GOOD),    # good — трекінг > одометр 8%
    (100.0,  82.0, _POOL_WOW),     # wow — трекінг > одометр 18%
])
def test_category(tracking, odometer, expected_pool):
    with patch("bot.services.route_comment_service.random.choice",
               side_effect=lambda pool: pool[0]) as mock_choice:
        result = get_route_comment(NAME, odometer, tracking)
        called_pool = mock_choice.call_args[0][0]
        assert called_pool is expected_pool
        assert isinstance(result, str)
        assert NAME in result
        assert result != ""


def test_tracking_zero():
    assert get_route_comment(NAME, 100.0, 0.0) == ""


def test_odometer_none():
    assert get_route_comment(NAME, None, 100.0) == ""


def test_tracking_none():
    assert get_route_comment(NAME, 100.0, None) == ""


def test_result_is_random():
    """Перевіряємо що random.choice справді викликається (не хардкод)."""
    results = {get_route_comment(NAME, 100.0, 100.0) for _ in range(50)}
    assert len(results) > 1

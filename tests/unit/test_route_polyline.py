"""
Тести для збереження route_polyline в SQLite та кешу polyline у geo.py.
Фічі 23.04.2026: збереження overview_polyline з Google API після фінішу маршруту.
"""
import sys, os, asyncio, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from unittest.mock import AsyncMock, MagicMock, patch
import aiosqlite


def _ok_response(polyline="encoded_polyline_abc123"):
    return {
        "status": "OK",
        "routes": [{
            "legs": [{"distance": {"value": 39000}}],
            "overview_polyline": {"points": polyline},
        }],
    }


def _make_session_mock(response_data):
    resp = AsyncMock()
    resp.json = AsyncMock(return_value=response_data)
    get_ctx = MagicMock(
        __aenter__=AsyncMock(return_value=resp),
        __aexit__=AsyncMock(return_value=False),
    )
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.get = MagicMock(return_value=get_ctx)
    return MagicMock(return_value=session)


def test_polyline_saved_on_route_finish():
    """update_route_polyline зберігає polyline в БД (temp SQLite, повна перевірка запису)."""
    from bot.models.database import init_db, update_route_polyline

    async def _run():
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            tmp = f.name
        try:
            with patch("bot.models.database.DB_PATH", tmp):
                await init_db()
                async with aiosqlite.connect(tmp) as db:
                    await db.execute(
                        "INSERT INTO routes (driver_id, start_time, is_active) VALUES (1, '2026-04-24T10:00:00', 0)"
                    )
                    await db.commit()
                    cursor = await db.execute("SELECT last_insert_rowid()")
                    row = await cursor.fetchone()
                    route_id = row[0]
                await update_route_polyline(route_id, "encoded_polyline_abc123")
                async with aiosqlite.connect(tmp) as db:
                    cursor = await db.execute(
                        "SELECT route_polyline FROM routes WHERE id = ?", (route_id,)
                    )
                    result = await cursor.fetchone()
            return result[0] if result else None
        finally:
            os.unlink(tmp)

    polyline = asyncio.run(_run())
    assert polyline == "encoded_polyline_abc123", \
        f"Очікувався polyline 'encoded_polyline_abc123', отримано {polyline!r}"


def test_polyline_none_on_api_error():
    """При помилці Google API — get_cached_polyline повертає None, функція не кидає виняток."""
    from bot.utils.geo import get_road_distance_for_route, get_cached_polyline

    wps = [{"lat": 50.4501, "lon": 30.5234}, {"lat": 50.3450, "lon": 30.9474}]
    fresh_cache: dict = {}
    with patch("bot.config.GOOGLE_MAPS_API_KEY", "fake-key"), \
         patch("bot.utils.geo._route_distance_cache", {}), \
         patch("bot.utils.geo._polyline_cache", fresh_cache), \
         patch("aiohttp.ClientSession", side_effect=Exception("network error")):
        result = asyncio.run(get_road_distance_for_route(wps))
        polyline = get_cached_polyline(wps)

    assert isinstance(result, float), "Fallback має повернути float (haversine×1.4)"
    assert polyline is None, f"При помилці API polyline має бути None, отримано {polyline!r}"


def test_polyline_column_exists():
    """Після init_db() таблиця routes містить колонку route_polyline (PRAGMA table_info)."""
    async def _run():
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            tmp = f.name
        try:
            with patch("bot.models.database.DB_PATH", tmp):
                from bot.models.database import init_db
                await init_db()
            async with aiosqlite.connect(tmp) as db:
                cursor = await db.execute("PRAGMA table_info(routes)")
                rows = await cursor.fetchall()
            return [row[1] for row in rows]
        finally:
            os.unlink(tmp)

    columns = asyncio.run(_run())
    assert "route_polyline" in columns, \
        f"Колонка route_polyline відсутня в таблиці routes. Колонки: {columns}"

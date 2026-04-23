import aiosqlite
from datetime import datetime

from bot.config import DB_PATH
from bot.utils.geo import haversine


async def get_route_json(route_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id, driver_id, start_time, end_time, total_km, "
            "odometer_start, odometer_km, route_polyline FROM routes WHERE id = ?",
            (route_id,),
        ) as cur:
            route = await cur.fetchone()

        if not route:
            return None

        async with db.execute(
            "SELECT id, name, lat, lon, timestamp, is_suspicious "
            "FROM waypoints WHERE route_id = ? ORDER BY timestamp",
            (route_id,),
        ) as cur:
            rows = await cur.fetchall()

    waypoints = []
    for i, w in enumerate(rows):
        wp = {
            "id": w["id"],
            "name": w["name"],
            "lat": w["lat"],
            "lon": w["lon"],
            "timestamp": w["timestamp"],
            "is_suspicious": bool(w["is_suspicious"]),
            "distance_km": None,
            "speed_kmh": None,
        }
        if i > 0:
            prev = rows[i - 1]
            dist = haversine(prev["lat"], prev["lon"], w["lat"], w["lon"])
            try:
                t1 = datetime.fromisoformat(prev["timestamp"])
                t2 = datetime.fromisoformat(w["timestamp"])
                dt_h = (t2 - t1).total_seconds() / 3600
                wp["distance_km"] = round(dist, 2)
                if dt_h > 0:
                    wp["speed_kmh"] = round(dist / dt_h, 1)
            except Exception:
                pass
        waypoints.append(wp)

    return {
        "route_id": route["id"],
        "driver_id": route["driver_id"],
        "start_time": route["start_time"],
        "end_time": route["end_time"],
        "total_km": route["total_km"],
        "odometer_start": route["odometer_start"],
        "odometer_finish": route["odometer_km"],
        "route_polyline": route["route_polyline"],
        "waypoints": waypoints,
    }

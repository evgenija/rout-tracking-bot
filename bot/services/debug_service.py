from typing import Optional

from bot.models.database import get_route_info, get_route_waypoints


async def get_route_debug_info(route_id: int) -> Optional[dict]:
    """Returns diagnostic data for a route. Read-only."""
    route = await get_route_info(route_id)
    if not route:
        return None
    waypoints = await get_route_waypoints(route_id)
    return {"route": route, "waypoints": waypoints}

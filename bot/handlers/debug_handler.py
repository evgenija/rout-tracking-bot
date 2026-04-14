from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.config import SUPER_ADMIN_IDS
from bot.services.debug_service import get_route_debug_info

debug_router = Router()


@debug_router.message(Command("debug_route"))
async def handle_debug_route(message: Message):
    if message.from_user.id not in SUPER_ADMIN_IDS:
        return  # silently ignore non-super-admins

    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip().isdigit():
        await message.answer("Використання: /debug_route [route_id]")
        return

    route_id = int(args[1].strip())
    data = await get_route_debug_info(route_id)
    if not data:
        await message.answer(f"❌ Route #{route_id} not found")
        return

    route = data["route"]
    waypoints = data["waypoints"]

    status = "active" if route["is_active"] else "finished"
    total_km = route.get("total_km") or 0
    odometer_start = route.get("odometer_start") or 0
    odometer_km = route.get("odometer_km") or 0
    odo_diff = odometer_km - odometer_start

    if odo_diff > 0:
        gap_pct_str = f"{abs(odo_diff - total_km) / odo_diff * 100:.1f}%"
    else:
        gap_pct_str = "n/a"

    lines = [
        f"🔧 Route #{route['id']}",
        f"Driver: {route['full_name']} | Status: {status}",
        f"total_km: {total_km:.1f} | odometer_km: {odo_diff:.1f} | gap_pct: {gap_pct_str}",
        f"Created: {route.get('start_time', '—')}",
        "",
        f"Waypoints ({len(waypoints)}):",
    ]

    for wp in waypoints[:20]:
        ts = wp.get("timestamp", "")
        time_str = ts[11:16] if len(ts) >= 16 else ts  # HH:MM
        name = wp.get("name", "")
        lat = wp.get("lat", 0)
        lon = wp.get("lon", 0)
        flag = " ⚠️" if wp.get("is_suspicious") else ""
        lines.append(f"{time_str} {name} ({lat:.3f}, {lon:.3f}){flag}")

    if len(waypoints) > 20:
        lines.append(f"... і ще {len(waypoints) - 20} точок")

    await message.answer("\n".join(lines))

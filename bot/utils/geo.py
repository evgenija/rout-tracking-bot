import math
from datetime import datetime
from typing import List, Dict, Optional


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Відстань між двома GPS-координатами в км (формула Гаверсина)."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def calculate_route_distance(waypoints: List[Dict]) -> float:
    """Загальна відстань маршруту за списком геоміток.

    Підозрілі точки (is_suspicious=True) виключаються з розрахунку,
    щоб аномальні GPS-координати (РЕБ-спуфінг) не спотворювали кілометраж.
    """
    valid = [wp for wp in waypoints if not wp.get("is_suspicious")]
    total = 0.0
    for i in range(1, len(valid)):
        total += haversine(
            valid[i - 1]["lat"], valid[i - 1]["lon"],
            valid[i]["lat"],     valid[i]["lon"],
        )
    return round(total, 2)


def is_suspicious(
    lat1: float, lon1: float, time1: str,
    lat2: float, lon2: float, time2: str,
    max_distance_km: float = 500.0,
    min_time_minutes: float = 2.0,
) -> bool:
    """Повертає True, якщо переміщення підозріло (можливий GPS-спуфінг / РЕБ).

    Перевіряє два критерії:
    1. Миттєва телепортація — відстань > max_distance_km (за замовчуванням 100 км).
    2. Неможлива швидкість — > 200 км/год між двома мітками.

    Раніше функція повертала False для БУДЬ-ЯКОЇ відстані ≤ 500 км,
    тобто ніколи не спрацьовувала для України. Виправлено.
    """
    distance = haversine(lat1, lon1, lat2, lon2)

    # Критерій 1: миттєва телепортація
    if distance > max_distance_km:
        return True

    t1 = datetime.fromisoformat(time1)
    t2 = datetime.fromisoformat(time2)
    elapsed_minutes = abs((t2 - t1).total_seconds() / 60)

    # Замало часу між мітками — не оцінюємо швидкість
    if elapsed_minutes < min_time_minutes:
        return False

    # Критерій 2: швидкість > 200 км/год — фізично неможлива для вантажівки
    speed_kmh = distance / (elapsed_minutes / 60)
    return speed_kmh > 200.0


def format_duration(start_time: str, end_time: Optional[str]) -> str:
    """Форматує тривалість між двома ISO-timestamp'ами."""
    t1 = datetime.fromisoformat(start_time)
    t2 = datetime.fromisoformat(end_time) if end_time else datetime.now()
    delta = t2 - t1
    hours = int(delta.total_seconds() // 3600)
    minutes = int((delta.total_seconds() % 3600) // 60)
    return f"{hours}г {minutes}хв"

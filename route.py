from math import radians, sin, cos, sqrt, atan2


def haversine_km(lat1, lon1, lat2, lon2):
    earth_radius_km = 6371.0

    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)

    a = (
        sin(dlat / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    )
    c = 2 * atan2(sqrt(a), sqrt(1 - a))

    return earth_radius_km * c


def calculate_total_distance_km(points):
    if len(points) < 2:
        return 0.0

    total_km = 0.0

    for i in range(len(points) - 1):
        p1 = points[i]
        p2 = points[i + 1]

        segment_km = haversine_km(
            p1["latitude"],
            p1["longitude"],
            p2["latitude"],
            p2["longitude"],
        )
        total_km += segment_km

    return round(total_km, 1)
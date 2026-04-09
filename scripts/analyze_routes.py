"""
analyze_routes.py — P1 Route Alert Validation Script
Reads SQLite DB (read-only), calculates segment & route metrics,
saves results to scripts/output/*.csv and prints terminal report.

Run locally:  python scripts/analyze_routes.py
Run Railway:  railway run python scripts/analyze_routes.py
"""

import csv
import math
import os
import sqlite3
import subprocess
import sys
from datetime import datetime

# ── Optional: requests for Google Directions API ──────────────────────────────
try:
    import requests as _requests
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False


# ─────────────────────────────────────────────────────────────────────────────
# 1. FIND SQLITE FILE
# ─────────────────────────────────────────────────────────────────────────────

def find_db() -> str:
    """Find the SQLite file that contains the 'routes' table."""
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # Collect candidate .db / .sqlite files
    candidates = []
    for dirpath, _dirs, files in os.walk(repo_root):
        for fname in files:
            if fname.endswith(".db") or fname.endswith(".sqlite"):
                candidates.append(os.path.join(dirpath, fname))

    # Also try env-based path from bot/config.py logic
    data_dir = os.getenv("DATA_DIR", "")
    if data_dir and os.path.isdir(data_dir):
        env_path = os.path.join(data_dir, "bot.db")
        if os.path.isfile(env_path) and env_path not in candidates:
            candidates.insert(0, env_path)

    database_url = os.getenv("DATABASE_URL", "")
    if database_url:
        for prefix in ("sqlite+aiosqlite:///", "sqlite:///"):
            if database_url.startswith(prefix):
                url_path = database_url[len(prefix):]
                if not os.path.isabs(url_path):
                    url_path = os.path.join(repo_root, url_path)
                if os.path.isfile(url_path) and url_path not in candidates:
                    candidates.insert(0, url_path)

    for path in candidates:
        try:
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='routes'")
            if cur.fetchone():
                conn.close()
                return path
            conn.close()
        except Exception:
            continue

    raise FileNotFoundError(
        f"Could not find a SQLite file with a 'routes' table. Searched: {candidates}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 2. HAVERSINE
# ─────────────────────────────────────────────────────────────────────────────

def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ─────────────────────────────────────────────────────────────────────────────
# 3. GOOGLE DIRECTIONS API (per segment)
# ─────────────────────────────────────────────────────────────────────────────

_GOOGLE_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")
_google_ok = 0
_google_fallback = 0


def get_google_km(lat1: float, lon1: float, lat2: float, lon2: float):
    """Return road distance in km for a segment via Google Directions API.

    Returns (km: float, source: str).
    source = 'google' | 'haversine_fallback'
    """
    global _google_ok, _google_fallback

    hav = haversine(lat1, lon1, lat2, lon2)

    if not _GOOGLE_API_KEY or not _HAS_REQUESTS:
        _google_fallback += 1
        return None, "haversine_fallback"

    try:
        resp = _requests.get(
            "https://maps.googleapis.com/maps/api/directions/json",
            params={
                "origin": f"{lat1},{lon1}",
                "destination": f"{lat2},{lon2}",
                "mode": "driving",
                "key": _GOOGLE_API_KEY,
            },
            timeout=8,
        )
        data = resp.json()
        status = data.get("status", "")
        if status == "OK":
            meters = sum(
                leg["distance"]["value"] for leg in data["routes"][0]["legs"]
            )
            _google_ok += 1
            return round(meters / 1000, 3), "google"
        # REQUEST_DENIED, ZERO_RESULTS, etc.
        _google_fallback += 1
        return None, "haversine_fallback"
    except Exception:
        _google_fallback += 1
        return None, "haversine_fallback"


# ─────────────────────────────────────────────────────────────────────────────
# 4. MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    # ── Find DB ──────────────────────────────────────────────────────────────
    print("🔍 Searching for SQLite database...")
    db_path = find_db()
    print(f"✅ Found: {db_path}")

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    # ── STEP 1: Fetch routes (last 14 days, finished) ────────────────────────
    # Actual schema: is_active=0 means finished; date from start_time
    routes_rows = conn.execute("""
        SELECT id,
               driver_id,
               DATE(start_time)  AS date,
               total_km,
               odometer_start,
               odometer_km       AS odometer_finish,
               start_time        AS started_at,
               end_time          AS finished_at
        FROM routes
        WHERE is_active = 0
          AND DATE(start_time) >= DATE('now', '-14 days')
        ORDER BY start_time
    """).fetchall()

    routes = [dict(r) for r in routes_rows]
    route_count = len(routes)

    if route_count < 5:
        print(
            f"\n⚠️  Знайдено лише {route_count} маршрут(и) за останні 14 днів. "
            "Недостатньо даних (потрібно ≥ 5). Зупиняємось."
        )
        conn.close()
        sys.exit(1)

    print(f"📦 Routes found: {route_count}")

    # ── Output paths ─────────────────────────────────────────────────────────
    script_dir = os.path.dirname(os.path.abspath(__file__))
    out_dir = os.path.join(script_dir, "output")
    os.makedirs(out_dir, exist_ok=True)
    seg_csv_path   = os.path.join(out_dir, "segments_validation.csv")
    route_csv_path = os.path.join(out_dir, "route_validation.csv")

    # ── STEP 2-6: Build segment rows ─────────────────────────────────────────
    # Actual waypoint columns: id, route_id, lat, lon, name, timestamp, is_suspicious
    seg_cols = [
        "route_id", "segment_id", "point_from", "point_to",
        "timestamp_from", "timestamp_to", "time_gap_minutes",
        "haversine_km", "google_km", "distance_source", "distance_used_km",
        "avg_speed_kmh", "google_to_haversine_ratio",
        "alert_slow_segment", "score", "score_label",
        "manual_label", "comments",
    ]

    seg_rows = []
    skipped_routes = []  # routes with < 2 waypoints

    for route in routes:
        rid = route["id"]
        wps = conn.execute("""
            SELECT id, lat, lon, name, timestamp
            FROM waypoints
            WHERE route_id = ?
              AND is_suspicious = 0
            ORDER BY timestamp
        """, (rid,)).fetchall()
        wps = [dict(w) for w in wps]

        if len(wps) < 2:
            skipped_routes.append(rid)
            continue

        for i in range(len(wps) - 1):
            wp_a = wps[i]
            wp_b = wps[i + 1]

            # time_gap_minutes
            try:
                t_a = datetime.fromisoformat(wp_a["timestamp"])
                t_b = datetime.fromisoformat(wp_b["timestamp"])
                time_gap = abs((t_b - t_a).total_seconds() / 60)
            except Exception:
                continue  # skip malformed timestamps

            if time_gap == 0:
                continue  # avoid division by zero

            hav_km = round(haversine(wp_a["lat"], wp_a["lon"], wp_b["lat"], wp_b["lon"]), 3)

            # Google Directions per segment
            google_km, distance_source = get_google_km(
                wp_a["lat"], wp_a["lon"], wp_b["lat"], wp_b["lon"]
            )

            # distance_used_km
            if google_km is not None:
                dist_used = google_km
            else:
                dist_used = hav_km

            avg_speed = round(dist_used / (time_gap / 60), 2) if time_gap > 0 else None

            # google_to_haversine_ratio
            if google_km is not None and hav_km > 0:
                g2h = round(google_km / hav_km, 3)
            else:
                g2h = ""

            # STEP 4 — baseline alert
            alert = (dist_used > 60 and avg_speed is not None and avg_speed < 25)

            # STEP 5 — scoring
            score = 0
            if dist_used > 60:
                score += 1
            if avg_speed is not None and avg_speed < 25:
                score += 2
            if time_gap > 120:
                score += 1

            if score <= 1:
                score_label = "OK"
            elif score <= 3:
                score_label = "WARNING"
            else:
                score_label = "SUSPICIOUS"

            seg_rows.append({
                "route_id":                rid,
                "segment_id":              f"{rid}_{i+1}",
                "point_from":              wp_a.get("name") or f"({wp_a['lat']},{wp_a['lon']})",
                "point_to":                wp_b.get("name") or f"({wp_b['lat']},{wp_b['lon']})",
                "timestamp_from":          wp_a["timestamp"],
                "timestamp_to":            wp_b["timestamp"],
                "time_gap_minutes":        round(time_gap, 2),
                "haversine_km":            hav_km,
                "google_km":               google_km if google_km is not None else "",
                "distance_source":         distance_source,
                "distance_used_km":        round(dist_used, 3),
                "avg_speed_kmh":           avg_speed if avg_speed is not None else "",
                "google_to_haversine_ratio": g2h,
                "alert_slow_segment":      "TRUE" if alert else "FALSE",
                "score":                   score,
                "score_label":             score_label,
                "manual_label":            "",
                "comments":                "",
            })

    # ── Write segments CSV ────────────────────────────────────────────────────
    with open(seg_csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=seg_cols)
        w.writeheader()
        w.writerows(seg_rows)

    # ── STEP 11: Route-level validation ──────────────────────────────────────
    # odometer_km (diff) = odometer_finish - odometer_start (actual col: odometer_km - odometer_start)
    route_cols = [
        "route_id", "odometer_km", "tracker_total_km",
        "gap_pct", "alert_route_mismatch",
        "manual_label", "comments",
    ]

    route_rows = []
    for route in routes:
        odo_start  = route.get("odometer_start")
        odo_finish = route.get("odometer_finish")
        tracker_km = route.get("total_km")

        if odo_start is None or odo_finish is None:
            continue  # no odometer data

        odo_diff = round(odo_finish - odo_start, 2)
        if odo_diff <= 0:
            continue  # invalid odometer values

        gap_pct = round(abs(odo_diff - (tracker_km or 0)) / odo_diff, 4)
        alert_mismatch = gap_pct > 0.10

        route_rows.append({
            "route_id":            route["id"],
            "odometer_km":         odo_diff,
            "tracker_total_km":    round(tracker_km or 0, 2),
            "gap_pct":             gap_pct,
            "alert_route_mismatch": "TRUE" if alert_mismatch else "FALSE",
            "manual_label":        "",
            "comments":            "",
        })

    with open(route_csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=route_cols)
        w.writeheader()
        w.writerows(route_rows)

    conn.close()

    # ── STEP 7: Terminal report ───────────────────────────────────────────────
    total_segments = len(seg_rows)
    alert_segs     = sum(1 for r in seg_rows if r["alert_slow_segment"] == "TRUE")
    alert_routes   = sum(1 for r in route_rows if r["alert_route_mismatch"] == "TRUE")
    pct_seg        = round(alert_segs / total_segments * 100, 1) if total_segments else 0
    pct_route      = round(alert_routes / len(route_rows) * 100, 1) if route_rows else 0

    ok_cnt      = sum(1 for r in seg_rows if r["score_label"] == "OK")
    warn_cnt    = sum(1 for r in seg_rows if r["score_label"] == "WARNING")
    susp_cnt    = sum(1 for r in seg_rows if r["score_label"] == "SUSPICIOUS")

    from_date = min((r["date"] for r in routes), default="—")
    to_date   = max((r["date"] for r in routes), default="—")

    print(f"""
✅ ЗВІТ АНАЛІЗУ МАРШРУТІВ P1
📅 Період: {from_date} — {to_date}
📊 Маршрутів оброблено: {route_count}
⚠️  Маршрутів пропущено (< 2 waypoints): {len(skipped_routes)} — {skipped_routes or 'немає'}
📍 Сегментів всього: {total_segments}
🚨 alert_slow_segment = TRUE: {alert_segs} ({pct_seg}%)
🔴 alert_route_mismatch = TRUE: {alert_routes} ({pct_route}%)
📈 Score розподіл: OK={ok_cnt} / WARNING={warn_cnt} / SUSPICIOUS={susp_cnt}
🌐 Google Roads API: успіх={_google_ok} / fallback={_google_fallback}
📁 Файли збережено:
   - {seg_csv_path}
   - {route_csv_path}

📋 ЩО РОБИТИ ДАЛІ (інструкція для оркестратора):
1. Завантажити обидва CSV файли з Railway або локально
2. Відкрити Google Sheet: https://docs.google.com/spreadsheets/d/1sE76nVlx6iOUUXXztFweZmfCoq9s4pkfvjWaj1iSj9g
3. Імпортувати кожен CSV як окрему вкладку: Файл → Імпортувати → Завантажити → обрати файл → «Вставити як новий аркуш»
4. У колонці manual_label для кожного рядка поставити: OK або SUSPICIOUS
   Орієнтир — SUSPICIOUS якщо: alert=TRUE або score≥3 або логіка руху виглядає дивно
5. Після заповнення manual_label — повернутись до оркестратора для аналізу TP/FP/FN

🎯 ОЧІКУВАНИЙ ЕФЕКТ:
Після заповнення manual_label стане зрозуміло:
- Чи baseline rule (distance>60 AND speed<35) ловить реальні підозрілі кейси
- Чи scoring model дає кращий баланс ніж просте правило
- Які пороги (60км, 35км/год, 120хв) потрібно скоригувати
Результат → фіксація фінальних порогів → реалізація в services/validation.py
""")


if __name__ == "__main__":
    main()

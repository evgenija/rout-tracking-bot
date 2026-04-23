#!/usr/bin/env python3
"""
tests/db_assert.py
Запуск: python3 tests/db_assert.py  (локально або через railway ssh --native)
Виводить: OK/MISSING для кожної колонки та таблиці
Exit code: 0 якщо всі OK, 1 якщо є MISSING
"""
import os
import sqlite3
import sys

DB_PATH = os.environ.get("DB_PATH", "/data/bot.db")
if not os.path.exists(DB_PATH):
    DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "bot.db")

results = []

def check(label, ok, detail=""):
    status = "OK" if ok else "MISSING"
    line = f"[{status}] {label}"
    if detail:
        line += f" — {detail}"
    print(line)
    results.append(ok)


try:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
except Exception as e:
    print(f"[FATAL] Не вдалося підключитись до БД: {e}")
    sys.exit(1)

# Очікувані таблиці
EXPECTED_TABLES = ["routes", "waypoints"]

cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
existing_tables = {row[0] for row in cur.fetchall()}

for table in EXPECTED_TABLES:
    check(f"таблиця '{table}'", table in existing_tables)

# Критичні колонки routes
ROUTES_COLUMNS = ["id", "driver_id", "start_time", "end_time",
                  "total_km", "is_active", "odometer_start", "odometer_km",
                  "route_polyline"]

if "routes" in existing_tables:
    cur.execute("PRAGMA table_info(routes)")
    routes_cols = {row[1] for row in cur.fetchall()}
    for col in ROUTES_COLUMNS:
        check(f"routes.{col}", col in routes_cols)
    # Немає колонки status — відомий патерн регресії
    check("routes НЕ має колонки 'status' (захист від регресії)",
          "status" not in routes_cols,
          "знайдено 'status' — небезпечна регресія!" if "status" in routes_cols else "")

# Критичні колонки waypoints
WAYPOINTS_COLUMNS = ["id", "route_id", "lat", "lon", "name", "timestamp", "is_suspicious"]

if "waypoints" in existing_tables:
    cur.execute("PRAGMA table_info(waypoints)")
    waypoints_cols = {row[1] for row in cur.fetchall()}
    for col in WAYPOINTS_COLUMNS:
        check(f"waypoints.{col}", col in waypoints_cols)

conn.close()

# Summary
ok_count = sum(results)
total = len(results)
print(f"\n{ok_count}/{total} перевірок пройшло")
sys.exit(0 if all(results) else 1)

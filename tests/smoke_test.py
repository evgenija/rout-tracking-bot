#!/usr/bin/env python3
"""
tests/smoke_test.py
Запуск: python3 tests/smoke_test.py  (локально або через railway ssh --native)
Виводить: PASS/FAIL для кожного тесту
Exit code: 0 якщо всі PASS, 1 якщо є FAIL
"""
import os
import sqlite3
import sys

DB_PATH = os.environ.get("DB_PATH", "/data/bot.db")
if not os.path.exists(DB_PATH):
    DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "bot.db")

results = []

def check(name, passed, detail=""):
    status = "PASS" if passed else "FAIL"
    line = f"[{status}] {name}"
    if detail:
        line += f" — {detail}"
    print(line)
    results.append(passed)


# Test 1: БД доступна і таблиця routes існує
try:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='routes'")
    found = cur.fetchone() is not None
    check("БД доступна і таблиця routes існує", found, DB_PATH if not found else "")
except Exception as e:
    check("БД доступна і таблиця routes існує", False, str(e))
    conn = None

# Test 2: Поле odometer_start існує у схемі
if conn:
    try:
        cur.execute("PRAGMA table_info(routes)")
        columns = [row[1] for row in cur.fetchall()]
        has_col = "odometer_start" in columns
        check("Поле odometer_start існує у схемі routes", has_col,
              f"знайдені колонки: {columns}" if not has_col else "")
    except Exception as e:
        check("Поле odometer_start існує у схемі routes", False, str(e))

# Test 3: Активні маршрути мають is_active=1, немає колонки status
if conn:
    try:
        cur.execute("PRAGMA table_info(routes)")
        columns = [row[1] for row in cur.fetchall()]
        has_status = "status" in columns
        cur.execute("SELECT COUNT(*) FROM routes WHERE is_active = 1")
        active_count = cur.fetchone()[0]
        check("Активні маршрути мають is_active (не status)",
              not has_status,
              "знайдено колонку status — небезпечна регресія!" if has_status
              else f"активних маршрутів: {active_count}")
    except Exception as e:
        check("Активні маршрути мають is_active (не status)", False, str(e))

# Test 4: Regression — auto_close не містить хибне повідомлення про одометр
try:
    candidates = [
        "/app/bot/utils/scheduler.py",
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "bot", "utils", "scheduler.py"),
    ]
    scheduler_path = next((p for p in candidates if os.path.exists(p)), None)
    if not scheduler_path:
        raise FileNotFoundError(f"scheduler.py не знайдено, перевірено: {candidates}")
    with open(scheduler_path, encoding="utf-8") as f:
        source = f.read()
    bad_string = "Одометр не зафіксовано"
    has_bad = bad_string in source
    check("auto_close не містить хибне 'Одометр не зафіксовано'",
          not has_bad,
          "знайдено рядок — баг повернувся!" if has_bad else "")
except Exception as e:
    check("auto_close не містить хибне 'Одометр не зафіксовано'", False, str(e))

if conn:
    conn.close()

# Summary
passed = sum(results)
total = len(results)
print(f"\n{passed}/{total} тестів пройшло")
sys.exit(0 if all(results) else 1)

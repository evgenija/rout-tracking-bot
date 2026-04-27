"""
recalculate_april_km.py — перерахунок daily_input.km за квітень 2026.

За замовчуванням — DRY RUN (тільки показує що зміниться, жодного UPDATE).
Для реального UPDATE запустити з прапором --execute.

Логіка:
  1. Читає всі записи daily_input за квітень з P2 PostgreSQL
  2. Для кожного запису — читає відповідний маршрут з P1 SQLite
     (tracking_km = routes.total_km, odometer_diff = odometer_km - odometer_start)
  3. Перераховує final_km через select_final_km() з поточними коефіцієнтами
  4. Якщо результат відрізняється від поточного daily_input.km > 0.5 км →
     DRY RUN: виводить рядок; EXECUTE: оновлює daily_input.km і logistics_cost

Запуск:
  python3 scripts/recalculate_april_km.py           # dry run
  python3 scripts/recalculate_april_km.py --execute # реальний UPDATE (тільки після апруву)
"""
import asyncio
import sqlite3
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncpg
from dotenv import load_dotenv
load_dotenv()
PG_DATABASE_URL = os.getenv("DATABASE_PUBLIC_URL") or os.getenv("PG_DATABASE_URL", "")
from bot.config import DB_PATH
from bot.services.calculator import select_final_km, _calc_logistics_cost

DRY_RUN = "--execute" not in sys.argv
MONTH   = "2026-04"
MIN_DIFF = 0.5  # км — мінімальна різниця щоб вважати запис "застарілим"


def get_p1_route(route_id: int) -> dict | None:
    """Читає маршрут з P1 SQLite: total_km, odometer_start, odometer_km."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT total_km, odometer_start, odometer_km FROM routes WHERE id = ?",
        (route_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


async def main():
    print(f"{'='*60}")
    print(f"  {'DRY RUN' if DRY_RUN else '!!! EXECUTE — РЕАЛЬНИЙ UPDATE !!!'}")
    print(f"  Місяць: {MONTH}")
    print(f"{'='*60}\n")

    pg = await asyncpg.connect(PG_DATABASE_URL)

    # Завантажити коефіцієнти
    coeff_rows = await pg.fetch("SELECT key, value FROM coefficients")
    coefficients = {r["key"]: r["value"] for r in coeff_rows}
    if not coefficients:
        print("❌ Коефіцієнти порожні — перервано.")
        await pg.close()
        return

    print(f"✅ Коефіцієнти завантажено: {len(coefficients)} ключів")
    thresh_ot = coefficients.get("odometer_over_tracking_threshold", 0.05)
    thresh_to = coefficients.get("tracking_over_odometer_threshold", 0.03)
    print(f"   odometer_over_tracking_threshold = {thresh_ot}")
    print(f"   tracking_over_odometer_threshold = {thresh_to}\n")

    # Завантажити всі записи daily_input за квітень
    rows = await pg.fetch(
        """
        SELECT id, date, route_id, driver_id, driver_type, km, logistics_cost
        FROM daily_input
        WHERE TO_CHAR(date, 'YYYY-MM') = $1
        ORDER BY date, driver_id
        """,
        MONTH,
    )
    print(f"Записів у daily_input за {MONTH}: {len(rows)}\n")

    to_update = []
    skipped_no_route = []

    for r in rows:
        route = get_p1_route(r["route_id"]) if r["route_id"] else None
        if not route:
            skipped_no_route.append(r["id"])
            continue

        tracking_km = route["total_km"] or 0.0
        odo_start   = route["odometer_start"]
        odo_finish  = route["odometer_km"]
        odo_diff    = None
        if odo_start is not None and odo_finish is not None and odo_finish > odo_start:
            odo_diff = odo_finish - odo_start

        new_km, reason = select_final_km(tracking_km, odo_diff, coefficients)

        # Нова вартість
        if r["driver_type"] == "logistics":
            new_cost = _calc_logistics_cost(new_km, coefficients)
        else:
            new_cost = new_km * coefficients.get("own_driver_cost_per_km", 0.0)

        old_km   = r["km"] or 0.0
        old_cost = r["logistics_cost"] or 0.0

        if abs(new_km - old_km) > MIN_DIFF:
            to_update.append({
                "id":        r["id"],
                "date":      r["date"],
                "driver_id": r["driver_id"],
                "route_id":  r["route_id"],
                "old_km":    old_km,
                "new_km":    new_km,
                "old_cost":  old_cost,
                "new_cost":  new_cost,
                "reason":    reason,
            })

    # --- Звіт ---
    print(f"{'─'*60}")
    print(f"Записів без маршруту в P1: {len(skipped_no_route)}")
    if skipped_no_route:
        print(f"  IDs: {skipped_no_route}")
    print(f"Записів де km зміниться (> {MIN_DIFF} км): {len(to_update)}")
    print(f"{'─'*60}\n")

    if to_update:
        print(f"{'id':>5} | {'date':>12} | {'driver_id':>12} | {'route':>6} | "
              f"{'old_km':>8} | {'new_km':>8} | {'diff':>7} | "
              f"{'old_cost':>10} | {'new_cost':>10} | reason")
        print("─" * 110)
        for u in to_update:
            diff = u["new_km"] - u["old_km"]
            print(
                f"{u['id']:>5} | {str(u['date']):>12} | {u['driver_id']:>12} | "
                f"{u['route_id']:>6} | {u['old_km']:>8.1f} | {u['new_km']:>8.1f} | "
                f"{diff:>+7.1f} | {u['old_cost']:>10.0f} | {u['new_cost']:>10.0f} | {u['reason']}"
            )
        print()

    if DRY_RUN:
        print("✋ DRY RUN завершено. Жодного UPDATE не виконано.")
        print("   Щоб застосувати: python3 scripts/recalculate_april_km.py --execute")
    else:
        if not to_update:
            print("Нічого оновлювати.")
        else:
            print(f"⚡ Виконую UPDATE {len(to_update)} записів...")
            for u in to_update:
                await pg.execute(
                    "UPDATE daily_input SET km = $1, logistics_cost = $2 WHERE id = $3",
                    u["new_km"], u["new_cost"], u["id"],
                )
            print(f"✅ Оновлено: {len(to_update)} записів.")

            # Верифікація
            verify = await pg.fetch(
                """
                SELECT id, km, logistics_cost
                FROM daily_input
                WHERE id = ANY($1)
                ORDER BY id
                """,
                [u["id"] for u in to_update],
            )
            print(f"\nВерифікація ({len(verify)} рядків):")
            for v in verify:
                matched = next(u for u in to_update if u["id"] == v["id"])
                status = "✅" if abs(v["km"] - matched["new_km"]) < 0.01 else "❌"
                print(f"  {status} id={v['id']} km={v['km']:.1f} cost={v['logistics_cost']:.0f}")

    await pg.close()


if __name__ == "__main__":
    asyncio.run(main())

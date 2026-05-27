"""
Одноразовий backfill: дорахунок вартості маршрутів за 14–27.05.2026.
Причина: відсутність коефіцієнтів у P2 DB після reset (logistics_city_rate та ін.)
призводила до мовчазного падіння _calc_logistics_cost → не INSERT у daily_input.

Запускати ПІСЛЯ деплою (коефіцієнти вже засіяні в БД).
Виклик: railway ssh + base64 (see CLAUDE.md — Доступ до БД).
"""
import asyncio
import os
import sys
from datetime import date as date_cls

import aiosqlite
import asyncpg

sys.path.insert(0, '/app')
from bot.services.calculator import _calc_logistics_cost, select_final_km

LOGISTICS_DRIVER_IDS = {935741313, 1713367110, 570793350, 486855930}
BACKFILL_FROM = date_cls(2026, 5, 14)
BACKFILL_TO   = date_cls(2026, 5, 27)


def _driver_type(driver_id: int) -> str:
    return "logistics" if driver_id in LOGISTICS_DRIVER_IDS else "own"


async def main():
    data_dir = os.environ.get('DATA_DIR', '')
    db_path = os.path.join(data_dir, 'bot.db') if data_dir else 'bot.db'
    pg_url = os.environ['PG_DATABASE_URL']

    pg = await asyncpg.connect(pg_url)

    # Коефіцієнти з P2
    coeff_rows = await pg.fetch('SELECT key, value FROM coefficients')
    coefficients = {r['key']: float(r['value']) for r in coeff_rows}
    print(f"Coefficients loaded: {len(coefficients)} keys")

    # Перевіряємо що критичні коефіцієнти є
    required = ['logistics_city_threshold_km', 'logistics_city_rate', 'logistics_city_fixed_fee',
                'logistics_regional_rate', 'own_driver_cost_per_km']
    missing_keys = [k for k in required if k not in coefficients]
    if missing_keys:
        print(f"ERROR: missing coefficients: {missing_keys}")
        print("Запустіть скрипт після деплою щоб коефіцієнти засіялись.")
        await pg.close()
        return

    # Вже існуючі route_id в daily_input
    existing_rows = await pg.fetch(
        'SELECT DISTINCT route_id FROM daily_input WHERE route_id IS NOT NULL'
    )
    existing_ids = {r['route_id'] for r in existing_rows}
    print(f"Existing route_ids in daily_input: {len(existing_ids)}")

    # Завершені маршрути з P1 за діапазон дат
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            """
            SELECT id, driver_id, total_km, odometer_start, odometer_km,
                   DATE(start_time) AS route_date
            FROM routes
            WHERE is_active = 0
              AND DATE(start_time) BETWEEN ? AND ?
            ORDER BY id
            """,
            (BACKFILL_FROM.isoformat(), BACKFILL_TO.isoformat()),
        ) as cur:
            all_routes = await cur.fetchall()

    print(f"P1 finished routes {BACKFILL_FROM}–{BACKFILL_TO}: {len(all_routes)}")

    to_backfill = [r for r in all_routes if r[0] not in existing_ids]
    print(f"Missing from daily_input: {len(to_backfill)}")

    if not to_backfill:
        print("Нічого бекфілити — всі маршрути вже є в daily_input.")
        await pg.close()
        return

    inserted = 0
    skipped = 0
    for route_id, driver_id, total_km, odo_start, odo_km_abs, route_date_str in to_backfill:
        tracking_km = float(total_km or 0)

        if driver_id is None:
            print(f"  SKIP route_id={route_id} — driver_id відсутній")
            skipped += 1
            continue

        if tracking_km == 0 and odo_km_abs is None:
            print(f"  SKIP route_id={route_id} — km=0 і одометр відсутній")
            skipped += 1
            continue

        driver_type = _driver_type(driver_id)

        # Дельта одометра
        odo_delta = None
        if odo_start is not None and odo_km_abs is not None:
            diff = float(odo_km_abs) - float(odo_start)
            if diff > 0:
                odo_delta = diff

        # Для логістики — окремий поріг одометра
        coeff = dict(coefficients)
        if driver_type == "logistics":
            coeff["odometer_over_tracking_threshold"] = coeff.get(
                "logistics_odometer_over_tracking_threshold", 0.095
            )

        final_km, reason = select_final_km(tracking_km, odo_delta, coeff)

        if driver_type == "logistics":
            cost = _calc_logistics_cost(final_km, coefficients)
        else:
            cost = final_km * coefficients["own_driver_cost_per_km"]

        route_date = date_cls.fromisoformat(route_date_str)

        await pg.execute(
            """
            INSERT INTO daily_input (date, route_id, driver_id, driver_type, km, logistics_cost)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            route_date, route_id, driver_id, driver_type, final_km, cost,
        )

        print(
            f"  INSERT route_id={route_id} | {driver_type} | {route_date} "
            f"| km={final_km:.1f} ({reason}) | cost={cost:,.0f} грн"
        )
        inserted += 1

    print(f"\nГотово: вставлено {inserted}, пропущено {skipped}")
    await pg.close()


asyncio.run(main())

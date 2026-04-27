"""
db_init_p2.py — ініціалізація таблиць P2 Finance Bot.
P1 таблиці не чіпати.
"""


async def create_p2_tables(pool):
    async with pool.acquire() as conn:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS btree_gist;")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS coefficients (
                id SERIAL PRIMARY KEY,
                key VARCHAR(100) UNIQUE NOT NULL,
                value FLOAT NOT NULL,
                description TEXT,
                updated_at TIMESTAMP DEFAULT NOW(),
                updated_by BIGINT
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS monthly_data (
                id SERIAL PRIMARY KEY,
                month DATE NOT NULL,
                revenue FLOAT,
                logistics_km FLOAT,
                own_km FLOAT,
                sales_km FLOAT,
                shared FLOAT,
                taxes FLOAT,
                net_profit FLOAT,
                created_at TIMESTAMP DEFAULT NOW()
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_input (
                id SERIAL PRIMARY KEY,
                date DATE NOT NULL,
                route_id INTEGER,
                driver_id INTEGER,
                driver_type VARCHAR(20) DEFAULT 'own',
                km FLOAT,
                logistics_cost FLOAT,
                created_at TIMESTAMP DEFAULT NOW()
            );
        """)
        # Seed: вартість власного водія. Оновлює тільки якщо значення NULL.
        await conn.execute("""
            INSERT INTO coefficients (key, value, description)
            VALUES ('own_driver_cost_per_km', 18.50, 'Вартість власного водія (грн/км)')
            ON CONFLICT (key) DO UPDATE
                SET value = EXCLUDED.value, description = EXCLUDED.description
                WHERE coefficients.value IS NULL
        """)
        await conn.execute("""
            INSERT INTO coefficients (key, value, description)
            VALUES ('odometer_over_tracking_threshold', 0.05, 'Поріг: одометр > трекінг. Перевищення → рахуємо за трекінгом')
            ON CONFLICT (key) DO NOTHING
        """)
        await conn.execute("""
            INSERT INTO coefficients (key, value, description)
            VALUES ('tracking_over_odometer_threshold', 0.03, 'Поріг: трекінг > одометр. Перевищення → рахуємо за одометром')
            ON CONFLICT (key) DO NOTHING
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS period_input (
                id         SERIAL PRIMARY KEY,
                date_from  DATE        NOT NULL,
                date_to    DATE        NOT NULL,
                revenue    BIGINT      NOT NULL,
                sales_km   INTEGER     NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                CONSTRAINT period_input_no_overlap
                    EXCLUDE USING gist (daterange(date_from, date_to, '[]') WITH &&)
            );
        """)
        # Фінансові коефіцієнти — ON CONFLICT DO NOTHING: не перезаписувати актуальні значення
        for key, value, desc in [
            ("monthly_shared",           292555.0, "Загальні витрати/міс (медіана 2025, грн)"),
            ("monthly_taxes",             14549.0, "Податки/міс (медіана 2025, грн)"),
            ("sales_salary_pct",           0.035,  "Частка виручки на зарплату sales managers"),
            ("fuel_price_a95",             72.71,  "Ціна А-95 грн/л (авто або /set_fuel)"),
            ("fuel_price_lpg",             48.99,  "Ціна LPG грн/л (авто або /set_fuel)"),
            ("fuel_consumption_a95",        7.0,   "Витрата А-95 л/100км (sales managers)"),
            ("fuel_consumption_lpg",       10.0,   "Витрата LPG л/100км (sales managers)"),
            ("sales_amortization_per_km",   0.80,  "Амортизація авто sales managers грн/км"),
            ("effective_tax_rate",          0.00216, "Ефективна ставка податку: taxes_median/revenue_median_2025"),
            ("revenue_median_2025",      6737667.0, "Медіана місячного revenue 2025 (грн). Для порівняння у звітах."),
        ]:
            await conn.execute(
                "INSERT INTO coefficients (key, value, description) VALUES ($1, $2, $3) "
                "ON CONFLICT (key) DO NOTHING",
                key, value, desc
            )

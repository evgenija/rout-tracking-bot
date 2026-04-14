"""
db_init_p2.py — ініціалізація таблиць P2 Finance Bot.
P1 таблиці не чіпати.
"""


async def create_p2_tables(pool):
    async with pool.acquire() as conn:
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

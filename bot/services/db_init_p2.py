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

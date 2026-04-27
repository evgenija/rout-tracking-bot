"""
coefficients_service.py — читає і кешує коефіцієнти з P2 таблиці coefficients.
Кеш TTL: 1 година. Ручний скид через refresh().
sales_cost_per_km не зберігається в БД — обраховується динамічно з компонент пального.
"""
import time
from typing import Optional


class CoefficientsService:
    def __init__(self, pool):
        self.pool = pool
        self._cache: Optional[dict] = None
        self._cached_at: float = 0
        self._ttl: int = 3600  # 1 година

    async def get(self) -> dict:
        """Повертає dict коефіцієнтів. Використовує кеш якщо не протух."""
        if self._cache is None or (time.time() - self._cached_at) > self._ttl:
            await self._load()
        return self._cache

    async def _load(self):
        """Завантажує коефіцієнти з БД і обраховує похідні."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT key, value FROM coefficients")
        cache = {row["key"]: row["value"] for row in rows}

        # sales_cost_per_km = середнє (витрата_A95/100*ціна_A95, витрата_LPG/100*ціна_LPG) + амортизація
        a95_cost = cache.get("fuel_consumption_a95", 7.0) / 100 * cache.get("fuel_price_a95", 72.71)
        lpg_cost = cache.get("fuel_consumption_lpg", 10.0) / 100 * cache.get("fuel_price_lpg", 48.99)
        amort = cache.get("sales_amortization_per_km", 0.80)
        cache["sales_cost_per_km"] = round((a95_cost + lpg_cost) / 2 + amort, 4)

        self._cache = cache
        self._cached_at = time.time()

    async def refresh(self):
        """Примусово скидає кеш і перезавантажує з БД."""
        self._cache = None
        await self._load()

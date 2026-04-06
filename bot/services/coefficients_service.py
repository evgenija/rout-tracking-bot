"""
coefficients_service.py — читає і кешує коефіцієнти з P2 таблиці coefficients.
Кеш TTL: 1 година. Ручний скид через refresh().
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
        """Завантажує коефіцієнти з БД."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT key, value FROM coefficients")
        self._cache = {row["key"]: row["value"] for row in rows}
        self._cached_at = time.time()

    async def refresh(self):
        """Примусово скидає кеш і перезавантажує з БД."""
        self._cache = None
        await self._load()

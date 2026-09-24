"""
core/idempotency.py — Takroriy Harakatlar va Dublikatlarni Oldini Olish Qatlami (Phase 38)

Qoidalar:
- Bir xil ID/kalitga ega rejalashtirilgan ishlar, email yuborishlar, avtonom vazifalar
  va Telegram xabarlarining takroriy bajarilishini (Duplicate execution) bartaraf etadi.
- TTL (Time-To-Live) asosida keshlanadi.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)


class IdempotencyManager:
    """Dublikat amallarni aniqlovchi va to'xtatuvchi in-memory kesh."""

    def __init__(self, default_ttl: float = 300.0) -> None:
        self.default_ttl = float(default_ttl)
        # key -> expiration_timestamp (float)
        self._keys: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def check_and_set(self, key: str, ttl_seconds: Optional[float] = None, ttl: Optional[float] = None) -> bool:
        """
        Amalni ro'yxatga oladi.

        Returns:
            True — Agar birinchi marta bajarilayotgan bo'lsa (amalga ruxsat).
            False — Agar dublikat bo'lsa (amal allaqachon bajarilmoqda yoki yaqinda bajarilgan).
        """
        if ttl is not None:
            ttl_seconds = float(ttl)
        elif ttl_seconds is None:
            ttl_seconds = self.default_ttl
        now = time.time()
        async with self._lock:
            self._cleanup(now)

            exp = self._keys.get(key)
            if exp is not None and exp > now:
                logger.info("Idempotent deduplication: kalit '%s' takrorlandi, bajarish rad etildi", key)
                return False

            self._keys[key] = now + ttl_seconds
            return True

    async def is_duplicate(self, key: str) -> bool:
        """Kalit faol keshda mavjudligini tekshiradi."""
        now = time.time()
        async with self._lock:
            exp = self._keys.get(key)
            return exp is not None and exp > now

    async def release(self, key: str) -> None:
        """Amal muvaffaqiyatsiz tugaganda kalitni muddatidan oldin bo'shatish."""
        async with self._lock:
            self._keys.pop(key, None)

    def _cleanup(self, now: float) -> None:
        """Eskirgan kalitlarni tozalaydi."""
        expired = [k for k, exp in self._keys.items() if exp <= now]
        for k in expired:
            del self._keys[k]

    def clear(self) -> None:
        """Barcha kalitlarni tozalash (testlar uchun)."""
        self._keys.clear()


# Global Singleton
idempotency_manager = IdempotencyManager()

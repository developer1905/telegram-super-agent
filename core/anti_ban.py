"""
core/anti_ban.py — Telegram Anti-Ban & Rate-Limiting "Qo'riqchisi"

Userbot orqali xabar yuborishda Telegram tomonidan SpamBlock yoki FloodWait
chekloviga tushib qolmaslik uchun xabarlar orasiga 3-7 soniyalik dinamik
random kechikishlar (jitter) va xavfsizlik nazoratini joriy etadi.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any, Optional

from config import ANTI_BAN_MIN_DELAY, ANTI_BAN_MAX_DELAY

logger = logging.getLogger(__name__)


class AntiBanGuard:
    """
    Userbot xavfsizligi va xabarlar oqimini tartibga soluvchi boshqaruvchi.
    """

    def __init__(
        self,
        min_delay: float = ANTI_BAN_MIN_DELAY,
        max_delay: float = ANTI_BAN_MAX_DELAY,
    ) -> None:
        self.min_delay = min_delay
        self.max_delay = max_delay
        self._last_send_time: float = 0.0
        self._lock = asyncio.Lock()
        self.total_safe_sends: int = 0

    async def wait_jitter(self, custom_min: Optional[float] = None, custom_max: Optional[float] = None) -> float:
        """3-7 soniya oralig'ida kutilmagan (random) kechikish qo'llash."""
        low = custom_min if custom_min is not None else self.min_delay
        high = custom_max if custom_max is not None else self.max_delay
        delay = random.uniform(low, high)
        logger.debug("AntiBan: %.2f soniya xavfsizlik kechikishi...", delay)
        await asyncio.sleep(delay)
        return delay

    async def safe_send_message(
        self,
        client: Any,
        entity: Any,
        message: str,
        **kwargs: Any,
    ) -> Any:
        """
        Telethon client orqali xabarni xavfsiz oraliq (3-7s) bilan yuborish.
        Ketma-ket yuborilgan xabarlar orasida avtomatik oraliq saqlanadi.
        """
        async with self._lock:
            now = time.time()
            elapsed = now - self._last_send_time
            needed_delay = random.uniform(self.min_delay, self.max_delay)

            if elapsed < needed_delay and self._last_send_time > 0:
                wait_time = needed_delay - elapsed
                logger.info("AntiBan: SpamBlock himoyasi uchun %.2f soniya kutilmoqda...", wait_time)
                await asyncio.sleep(wait_time)

            try:
                # Xabarni yuborish
                result = await client.send_message(entity, message, **kwargs)
                self._last_send_time = time.time()
                self.total_safe_sends += 1
                return result
            except Exception as exc:
                # FloodWaitError ni aniqlash (telethon kutubxonasidan)
                exc_str = str(exc)
                if "FloodWait" in type(exc).__name__ or "flood" in exc_str.lower():
                    logger.warning("AntiBan FloodWait aniqlandi: %s", exc)
                raise exc


# Global Anti-Ban singleton instansiyasi
anti_ban = AntiBanGuard()

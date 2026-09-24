"""
security/rate_limiter.py — Rate Limiting va So'rovlar Oqimini Nazorat Qilish (Phase 37)

Qoidalar:
- Foydalanuvchi, IP yoki amaliyot kaliti bo'yicha siljuvchi oyna (Sliding Window) algoritmi.
- API so'rovlari, Telegram buyruqlari, qimmat AI amallari va media yuklash uchun alohida limitlar.
- Limit oshib ketganda 429 Too Many Requests va Retry-After sarlavhasi qaytariladi.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional, Tuple
from aiohttp import web

logger = logging.getLogger(__name__)


@dataclass
class RateLimitConfig:
    max_requests: int
    window_seconds: float


class SlidingWindowRateLimiter:
    """Xotirada ishlaydigan siljuvchi oyna rate limiteri."""

    def __init__(self) -> None:
        # key -> list of timestamps (float)
        self._requests: dict[str, list[float]] = defaultdict(list)
        # Standart cheklovlar: (max_requests, window_seconds)
        self.DEFAULT_LIMITS: dict[str, tuple[int, float]] = {
            "api_general": (60, 60.0),       # 60 req/min
            "api_auth": (15, 60.0),          # 15 req/min
            "telegram_msg": (25, 30.0),      # 25 msg / 30 sec
            "ai_expensive": (8, 60.0),       # 8 queries / min (Midjourney, Code sandbox)
            "media_download": (10, 60.0),    # 10 downloads / min
            "email_send": (5, 60.0),         # 5 emails / min
        }

    async def is_allowed(self, key: str, config: RateLimitConfig) -> tuple[bool, dict]:
        """Asinxron tekshiruv va batafsil metadata qaytaruvchi metod."""
        allowed, retry_after = self.check_limit(
            key,
            custom_max=config.max_requests,
            custom_window=config.window_seconds,
        )
        full_key = f"api_general:{key}"
        curr_count = len(self._requests.get(full_key, []))
        meta = {
            "remaining": max(0, config.max_requests - curr_count),
            "retry_after": retry_after,
        }
        return allowed, meta

    def check_limit(
        self,
        key: str,
        category: str = "api_general",
        custom_max: Optional[int] = None,
        custom_window: Optional[float] = None,
    ) -> Tuple[bool, float]:
        """
        So'rov belgilangan limitdan oshmaganligini tekshiradi.

        Returns:
            (allowed: bool, retry_after_seconds: float)
        """
        now = time.time()
        max_req, window = self.DEFAULT_LIMITS.get(category, (60, 60.0))
        if custom_max is not None:
            max_req = custom_max
        if custom_window is not None:
            window = custom_window

        full_key = f"{category}:{key}"
        timestamps = self._requests[full_key]

        # Eskirgan timestamp larni tozalaymiz
        cutoff = now - window
        valid_timestamps = [t for t in timestamps if t > cutoff]
        self._requests[full_key] = valid_timestamps

        if len(valid_timestamps) >= max_req:
            # Eng eski so'rov oynadan chiqib ketish vaqti
            oldest = valid_timestamps[0]
            retry_after = max(0.1, round(window - (now - oldest), 1))
            logger.warning(
                "Rate limit exceeded for %s (%d/%d in %.1fs). Retry after %.1fs",
                full_key, len(valid_timestamps), max_req, window, retry_after,
            )
            return False, retry_after

        # Yangi so'rovni qo'shamiz
        valid_timestamps.append(now)
        return True, 0.0

    def reset(self, key: Optional[str] = None) -> None:
        """Keshni tozalash (testlar uchun)."""
        if key:
            for k in list(self._requests.keys()):
                if key in k:
                    del self._requests[k]
        else:
            self._requests.clear()


# Global Singleton
rate_limiter = SlidingWindowRateLimiter()


@web.middleware
async def rate_limit_middleware(request: web.Request, handler) -> web.Response:
    """aiohttp /api/* so'rovlari uchun rate limit tekshiruvi."""
    path = request.path
    if not path.startswith("/api/"):
        return await handler(request)

    # Identifikator: client IP yoki Telegram user_id
    user_id = request.headers.get("X-Telegram-User-Id") or request.remote or "unknown_client"
    category = "api_general"
    if "expensive" in path or "midjourney" in path or "code" in path:
        category = "ai_expensive"

    allowed, retry_after = rate_limiter.check_limit(user_id, category=category)
    if not allowed:
        return web.json_response(
            {
                "error": "Juda ko'p so'rov yuborildi. Iltimos, birozdan so'ng qayta urinib ko'ring.",
                "code": "RATE_LIMITED",
                "retry_after": retry_after,
            },
            status=429,
            headers={
                "Retry-After": str(int(retry_after) + 1),
                "Content-Type": "application/json",
            },
        )

    return await handler(request)

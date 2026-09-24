"""
tests/test_rate_limit_and_idempotency.py — Rate Limiting va Idempotency Testlari
"""

import asyncio
import time
import pytest
from aiohttp import web
from unittest.mock import AsyncMock

from security.rate_limiter import SlidingWindowRateLimiter, RateLimitConfig, rate_limit_middleware
from core.idempotency import IdempotencyManager, idempotency_manager


def test_sliding_window_rate_limiter_allows_under_limit():
    async def _test():
        limiter = SlidingWindowRateLimiter()
        config = RateLimitConfig(max_requests=5, window_seconds=10)
        
        for _ in range(5):
            allowed, meta = await limiter.is_allowed("test_client", config)
            assert allowed is True
            assert meta["remaining"] >= 0

    asyncio.run(_test())


def test_sliding_window_rate_limiter_blocks_over_limit():
    async def _test():
        limiter = SlidingWindowRateLimiter()
        config = RateLimitConfig(max_requests=3, window_seconds=10)
        
        for _ in range(3):
            allowed, _ = await limiter.is_allowed("test_client_burst", config)
            assert allowed is True
            
        blocked, meta = await limiter.is_allowed("test_client_burst", config)
        assert blocked is False
        assert meta["remaining"] == 0
        assert meta["retry_after"] > 0

    asyncio.run(_test())


def test_rate_limit_middleware():
    async def _test():
        req = AsyncMock(spec=web.Request)
        req.path = "/api/test"
        req.headers = {"X-Forwarded-For": "10.0.0.1"}
        req.remote = "10.0.0.1"

        handler = AsyncMock(return_value=web.Response(text="ok", status=200))
        resp = await rate_limit_middleware(req, handler)
        assert resp.status == 200

    asyncio.run(_test())


def test_idempotency_manager_check_and_set():
    async def _test():
        mgr = IdempotencyManager()
        
        # First time setting key
        first = await mgr.check_and_set("action:123", ttl=2)
        assert first is True
        assert await mgr.is_duplicate("action:123") is True

        # Immediate duplicate request should be blocked
        second = await mgr.check_and_set("action:123", ttl=2)
        assert second is False

        # Manual release
        await mgr.release("action:123")
        assert await mgr.is_duplicate("action:123") is False
        
        # After release, can set again
        third = await mgr.check_and_set("action:123", ttl=2)
        assert third is True

    asyncio.run(_test())


def test_idempotency_manager_ttl_expiry():
    async def _test():
        mgr = IdempotencyManager()
        
        assert await mgr.check_and_set("short_key", ttl=1) is True
        await asyncio.sleep(1.1)
        # Expired, so check_and_set should allow again
        assert await mgr.check_and_set("short_key", ttl=1) is True

    asyncio.run(_test())

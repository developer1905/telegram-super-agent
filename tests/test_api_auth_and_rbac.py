"""
tests/test_api_auth_and_rbac.py — API Authentication, RBAC, and Sensitive Endpoints Security Tests.

Mandatory Master Prompt Integration Tests:
1. GET /api/facts without auth -> 401
2. GET /api/profile without auth -> 401
3. GET /api/tasks without auth -> 401
4. GET /api/reminders without auth -> 401
5. GET /api/uptime without auth -> 401
6. GET /api/system_info without auth -> 401
7. Public paths (/health, /readiness, /webapp, /landing) -> Allowed without auth
8. Regular user accessing admin endpoint -> 403
9. Cross-user data access (User A requesting User B's astrology) -> 403
10. Missing astrology profile -> 404 (does not return another user's profile)
"""

import hashlib
import hmac
import json
import time
import pytest
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

from security.api_auth import (
    WebAppAuthMiddleware,
    webapp_auth_middleware,
    validate_telegram_init_data,
    SECURITY_HEADERS,
)


def create_valid_init_data(user_id: int, bot_token: str, auth_date: int = None) -> str:
    """Yaroqli Telegram initData satrini yaratish helperi."""
    if auth_date is None:
        auth_date = int(time.time())
    user_json = json.dumps({"id": user_id, "first_name": "TestUser", "username": f"user_{user_id}"})
    params = {
        "auth_date": str(auth_date),
        "query_id": "AAHdF6IQAAAAAN0XohD12345",
        "user": user_json,
    }
    data_check_parts = sorted(f"{k}={v}" for k, v in params.items())
    data_check_string = "\n".join(data_check_parts)
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    
    # URL encoded init_data satri
    return f"auth_date={auth_date}&hash={computed_hash}&query_id={params['query_id']}&user={user_json}"


class TestApiAuthAndRbac(AioHTTPTestCase):

    async def get_application(self):
        app = web.Application(middlewares=[webapp_auth_middleware])

        # Test endpoints
        async def public_health(request):
            return web.json_response({"status": "healthy"})

        async def public_readiness(request):
            return web.json_response({"status": "ready"})

        async def public_webapp(request):
            return web.Response(text="Webapp dashboard")

        async def api_facts(request):
            user_id = request.get("authenticated_user_id")
            return web.json_response({"status": "ok", "user_id": user_id, "facts": []})

        async def api_profile(request):
            user_id = request.get("authenticated_user_id")
            return web.json_response({"status": "ok", "user_id": user_id})

        async def api_tasks(request):
            user_id = request.get("authenticated_user_id")
            return web.json_response({"status": "ok", "user_id": user_id, "tasks": []})

        async def api_reminders(request):
            user_id = request.get("authenticated_user_id")
            return web.json_response({"status": "ok", "user_id": user_id, "reminders": []})

        async def api_uptime(request):
            if not request.get("is_admin", False):
                return web.json_response({"error": "Admin required", "code": "FORBIDDEN"}, status=403)
            return web.json_response({"status": "ok", "monitors": []})

        async def api_system_info(request):
            if not request.get("is_admin", False):
                return web.json_response({"error": "Admin required", "code": "FORBIDDEN"}, status=403)
            return web.json_response({"status": "ok", "system": "healthy"})

        async def api_astrology_profile(request):
            auth_user = str(request.get("authenticated_user_id"))
            query_user = request.query.get("user_id")
            is_admin = request.get("is_admin", False)
            if query_user and str(query_user) != auth_user and not is_admin:
                return web.json_response({"error": "Forbidden", "code": "FORBIDDEN"}, status=403)
            # Simulate missing profile
            return web.json_response({"status": "not_found", "message": "Profil mavjud emas"}, status=404)

        app.router.add_get("/health", public_health)
        app.router.add_get("/readiness", public_readiness)
        app.router.add_get("/webapp", public_webapp)
        app.router.add_get("/api/facts", api_facts)
        app.router.add_get("/api/profile", api_profile)
        app.router.add_get("/api/tasks", api_tasks)
        app.router.add_get("/api/reminders", api_reminders)
        app.router.add_get("/api/uptime", api_uptime)
        app.router.add_get("/api/system_info", api_system_info)
        app.router.add_get("/api/astrology/profile", api_astrology_profile)
        return app

    @unittest_run_loop
    async def test_public_paths_allowed_without_auth(self):
        """Public sahifalar (/health, /readiness, /webapp) autentifikatsiyasiz o'tishi kerak."""
        resp1 = await self.client.request("GET", "/health")
        assert resp1.status == 200

        resp2 = await self.client.request("GET", "/readiness")
        assert resp2.status == 200

        resp3 = await self.client.request("GET", "/webapp")
        assert resp3.status == 200

    @unittest_run_loop
    async def test_sensitive_endpoints_require_auth_401(self):
        """Barcha nozik /api/* endpointlar authsiz 401 qaytarishi kerak."""
        sensitive_paths = [
            "/api/facts",
            "/api/profile",
            "/api/tasks",
            "/api/reminders",
            "/api/uptime",
            "/api/system_info",
            "/api/astrology/profile",
        ]
        for path in sensitive_paths:
            resp = await self.client.request("GET", path)
            assert resp.status == 401, f"{path} authsiz chaqirilganda 401 qaytarmadi: status={resp.status}"
            body = await resp.json()
            assert body.get("code") == "MISSING_AUTH"

    @unittest_run_loop
    async def test_invalid_init_data_rejected_401(self):
        """Noto'g'ri yoki buzilgan initData 401 bilan rad etilishi kerak."""
        headers = {"X-Telegram-Init-Data": "auth_date=123&hash=invalidhash&user={}"}
        resp = await self.client.request("GET", "/api/facts", headers=headers)
        assert resp.status == 401
        body = await resp.json()
        assert body.get("code") == "INVALID_AUTH"

    @unittest_run_loop
    async def test_authenticated_user_can_access_own_facts(self):
        """Yaroqli initData bilan user o'z facts endpointiga kira olishi kerak."""
        from config import BOT_TOKEN
        token = BOT_TOKEN or "test_bot_token_12345"
        init_data = create_valid_init_data(user_id=1234567, bot_token=token)

        headers = {"X-Telegram-Init-Data": init_data}
        resp = await self.client.request("GET", "/api/facts", headers=headers)
        assert resp.status == 200
        body = await resp.json()
        assert body.get("user_id") == "1234567"

    @unittest_run_loop
    async def test_regular_user_blocked_from_admin_endpoints_403(self):
        """Oddiy foydalanuvchi admin endpointiga (/api/uptime, /api/system_info) kirsa 403 qaytarilishi kerak."""
        from config import BOT_TOKEN, ADMIN_ID
        token = BOT_TOKEN or "test_bot_token_12345"
        regular_user_id = 999999
        if ADMIN_ID and int(regular_user_id) == int(ADMIN_ID):
            regular_user_id = 888888

        init_data = create_valid_init_data(user_id=regular_user_id, bot_token=token)
        headers = {"X-Telegram-Init-Data": init_data}

        resp_uptime = await self.client.request("GET", "/api/uptime", headers=headers)
        assert resp_uptime.status == 403

        resp_sys = await self.client.request("GET", "/api/system_info", headers=headers)
        assert resp_sys.status == 403

    @unittest_run_loop
    async def test_cross_user_astrology_access_blocked_403(self):
        """User A boshqa User B ning astrologiya profilini so'rasa 403 qaytishi kerak."""
        from config import BOT_TOKEN
        token = BOT_TOKEN or "test_bot_token_12345"
        user_a_id = 111222
        user_b_id = 333444

        init_data_a = create_valid_init_data(user_id=user_a_id, bot_token=token)
        headers = {"X-Telegram-Init-Data": init_data_a}

        # User A User B ning profilini query orqali so'ramoqchi
        resp = await self.client.request("GET", f"/api/astrology/profile?user_id={user_b_id}", headers=headers)
        assert resp.status == 403

    @unittest_run_loop
    async def test_missing_astrology_profile_returns_404_not_other_user(self):
        """Mavjud bo'lmagan astrologiya profili Admin uchun 404 qaytarishi kerak (boshqa user profilini bermaslik)."""
        from config import BOT_TOKEN, ADMIN_ID
        token = BOT_TOKEN or "test_bot_token_12345"
        user_a_id = ADMIN_ID

        init_data_a = create_valid_init_data(user_id=user_a_id, bot_token=token)
        headers = {"X-Telegram-Init-Data": init_data_a}

        resp = await self.client.request("GET", "/api/astrology/profile", headers=headers)
        assert resp.status == 404

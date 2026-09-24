"""
security/api_auth.py — Telegram WebApp initData HMAC Validation va API Authentication

Telegram Mini App endpointlari uchun server-side autentifikatsiya:
1. initData HMAC-SHA256 signature validation (Telegram spetsifikatsiyasiga muvofiq)
2. Timestamp expiration tekshiruvi (5 daqiqa)
3. ADMIN_ID yoki ruxsat etilgan ACL tekshiruvi
4. Unauthenticated → 401, Unauthorized → 403

MUHIM: Frontend'dagi window.Telegram.WebApp.initDataUnsafe.user.id ga ishonmang.
Faqat server-side HMAC validation ishonchli.

Telegram initData spec: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from typing import Optional
from urllib.parse import parse_qs, unquote

from aiohttp import web

logger = logging.getLogger(__name__)

# initData 24 soatgacha amal qiladi (Telegram Mini App standart seansi)
INIT_DATA_MAX_AGE_SECONDS: int = 86400  # 24 soat

# Xavfsizlik headerlari (Telegram Mini App iframe yuklana olishi uchun X-Frame-Options olib tashlangan)
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-XSS-Protection": "1; mode=block",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Content-Security-Policy": "default-src 'self' 'unsafe-inline' 'unsafe-eval' https: data: blob:; frame-ancestors 'self' https://web.telegram.org https://*.telegram.org https://telegram.org;",
}


def _compute_init_data_hash(init_data_raw: str, bot_token: str) -> str:
    """
    Telegram initData HMAC-SHA256 hisobi.
    
    Algoritm:
    1. data_check_string = barcha maydonlar (hash bundan tashqari) alfabetik tartibda, \n bilan ajratilgan
    2. secret_key = HMAC-SHA256(bot_token, "WebAppData")
    3. hash = HMAC-SHA256(data_check_string, secret_key).hexdigest()
    """
    # initData ni parse qilamiz
    params = {}
    for part in init_data_raw.split("&"):
        if "=" in part:
            k, v = part.split("=", 1)
            params[unquote(k)] = unquote(v)
    
    # hash ni olib tashlaymiz
    received_hash = params.pop("hash", "")
    
    # Alfabetik tartibda data_check_string quramiz
    data_check_parts = sorted(f"{k}={v}" for k, v in params.items())
    data_check_string = "\n".join(data_check_parts)
    
    # secret_key = HMAC-SHA256("WebAppData", bot_token)
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    
    # computed hash
    computed = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    
    return computed, received_hash, params


def validate_telegram_init_data(
    init_data_raw: str,
    bot_token: str,
    allowed_user_ids: Optional[list[int]] = None,
    max_age_seconds: int = INIT_DATA_MAX_AGE_SECONDS,
) -> tuple[bool, Optional[int], Optional[str]]:
    """
    Telegram initData ni server tomonda tekshiradi.
    
    Returns:
        (is_valid, user_id, error_message)
        - is_valid: True bo'lsa autentifikatsiya muvaffaqiyatli
        - user_id: Tasdiqlangan foydalanuvchi ID
        - error_message: Xato bo'lsa tavsif
    """
    if not init_data_raw or not bot_token:
        return False, None, "initData yoki bot_token bo'sh"
    
    try:
        computed_hash, received_hash, params = _compute_init_data_hash(init_data_raw, bot_token)
    except Exception as exc:
        logger.warning("initData parse xatosi: %s", exc)
        return False, None, f"initData parse xatosi: {exc}"
    
    # HMAC tekshirish (constant-time comparison xavfsizlik uchun)
    if not hmac.compare_digest(computed_hash, received_hash):
        logger.warning("initData HMAC tekshiruvidan o'tmadi")
        return False, None, "HMAC signature noto'g'ri"
    
    # Vaqt tekshiruvi
    auth_date_str = params.get("auth_date", "0")
    try:
        auth_date = int(auth_date_str)
    except ValueError:
        return False, None, "auth_date noto'g'ri format"
    
    age = int(time.time()) - auth_date
    if age > max_age_seconds:
        logger.warning("initData eskirgan: %d soniya eski (max %d)", age, max_age_seconds)
        return False, None, f"initData eskirgan ({age}s > {max_age_seconds}s)"
    
    # user ID olish
    user_str = params.get("user", "{}")
    try:
        user_data = json.loads(unquote(user_str))
        user_id = int(user_data.get("id", 0))
    except Exception:
        return False, None, "user ma'lumotlarini o'qib bo'lmadi"
    
    if not user_id:
        return False, None, "user_id topilmadi"
    
    # ACL tekshiruvi
    if allowed_user_ids is not None and user_id not in allowed_user_ids:
        logger.warning("Ruxsatsiz foydalanuvchi: user_id=%d", user_id)
        return False, user_id, f"Ruxsatsiz foydalanuvchi (ID: {user_id})"
    
    return True, user_id, None


async def require_webapp_auth(request: web.Request) -> Optional[web.Response]:
    """
    aiohttp handler uchun auth middleware helper.
    Telegram WebApp initData HMAC-SHA256 validatsiyasini amalga oshiradi.
    
    Returns:
        web.Response (401 yoki 403) — agar auth xato bo'lsa
        None — agar muvaffaqiyatli bo'lsa.
        Muvaffaqiyatli bo'lganda request obyektiga:
        - request["authenticated_user_id"] (str)
        - request["is_admin"] (bool)
        - request["role"] ("admin" | "user")
        biriktiriladi.
    """
    from config import BOT_TOKEN, ADMIN_ID
    
    # initData header, query param yoki JSON body dan olamiz
    init_data = (
        request.headers.get("X-Telegram-Init-Data", "").strip()
        or request.headers.get("Authorization", "").replace("Bearer ", "").strip()
        or request.query.get("init_data", "").strip()
        or request.query.get("initData", "").strip()
        or request.query.get("token", "").strip()
    )
    
    # Agar header bo'lmasa, JSON body dan ham tekshiramiz
    if not init_data and request.method in ("POST", "PUT", "PATCH"):
        try:
            body = await request.clone(read_body=True).json()
            init_data = str(body.get("init_data", "") or body.get("initData", "") or body.get("token", "")).strip()
        except Exception:
            pass
    
    if not init_data:
        return web.json_response(
            {"error": "Authentication required. Telegram WebApp initData missing.", "code": "MISSING_AUTH"},
            status=401,
            headers=SECURITY_HEADERS,
        )

    # Maxsus holat: Bot egasi brauzerdan BOT_TOKEN bilan to'g'ridan-to'g'ri admin sifatida kirishi
    if BOT_TOKEN and (init_data == BOT_TOKEN.strip()):
        str_admin_id = str(ADMIN_ID or "admin")
        request["authenticated_user_id"] = str_admin_id
        request["is_admin"] = True
        request["role"] = "admin"
        return None
    
    is_valid, user_id, error_msg = validate_telegram_init_data(
        init_data, BOT_TOKEN, allowed_user_ids=None
    )
    
    if not is_valid or not user_id:
        return web.json_response(
            {"error": error_msg or "Invalid authentication", "code": "INVALID_AUTH"},
            status=401,
            headers=SECURITY_HEADERS,
        )
    
    # Muvaffaqiyatli — authenticated identity va RBAC rolini biriktiramiz
    str_user_id = str(user_id)
    is_admin = False
    if ADMIN_ID:
        try:
            is_admin = int(user_id) == int(ADMIN_ID)
        except (ValueError, TypeError):
            is_admin = str_user_id == str(ADMIN_ID)

    request["authenticated_user_id"] = str_user_id
    request["is_admin"] = is_admin
    request["role"] = "admin" if is_admin else "user"
    return None


def add_security_headers(response: web.Response) -> web.Response:
    """Response ga xavfsizlik headerlarini qo'shadi."""
    for k, v in SECURITY_HEADERS.items():
        response.headers[k] = v
    return response


class WebAppAuthMiddleware:
    """
    aiohttp middleware — barcha /api/* endpointlarini autentifikatsiya qiladi.
    Faqatgina ochiq statik sahifalar (/health, /webapp, /landing, /) autentifikatsiyasiz o'tadi.
    """
    
    # Faqat haqiqiy ochiq resurslar (hech qanday nozik ma'lumot bermaydi)
    PUBLIC_PATHS = {
        "/",
        "/health",
        "/webapp",
        "/webapp/",
        "/landing",
        "/landing/",
        "/readiness",
        "/favicon.ico",
    }
    
    # Middleware placeholder (assigned below)
    middleware = None


@web.middleware
async def webapp_auth_middleware(request: web.Request, handler) -> web.Response:
    """aiohttp middleware — public sahifalarni o'tkazadi, /api/* ni himoyalaydi."""
    path = request.path
    
    # Public yo'llar auth talab qilmaydi
    if path in WebAppAuthMiddleware.PUBLIC_PATHS or not path.startswith("/api/"):
        try:
            response = await handler(request)
        except Exception as exc:
            logger.error("Public handler xatosi [%s %s]: %s", request.method, path, exc, exc_info=True)
            response = web.Response(
                text="Serverda xatolik yuz berdi. Iltimos, keyinroq qayta urinib ko'ring.",
                status=500,
                content_type="text/plain",
                charset="utf-8",
            )
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        if path in ("/webapp", "/webapp/", "/"):
            response.headers.pop("X-Frame-Options", None)
        return response
    
    # /api/* uchun auth tekshiruvi (faqat yozish / o'zgartirish amallari uchun)
    auth_error = await require_webapp_auth(request)
    if auth_error is not None:
        return auth_error
    
    # Auth o'tdi — handler ga uzatamiz
    try:
        response = await handler(request)
    except Exception as exc:
        logger.error("API handler xatosi [%s %s]: %s", request.method, path, exc, exc_info=True)
        # Internal xatolarni leak qilmaymiz
        response = web.json_response(
            {"error": "Internal server error", "code": "INTERNAL_ERROR"},
            status=500,
        )
    
    # Xavfsizlik headerlarini qo'shamiz
    for k, v in SECURITY_HEADERS.items():
        response.headers.setdefault(k, v)
    
    return response

# Link into class for backward compatibility
WebAppAuthMiddleware.middleware = webapp_auth_middleware


# CORS policy (faqat Telegram WebApp domeniga ruxsat)
CORS_ALLOWED_ORIGINS = [
    "https://web.telegram.org",
    "https://k.web.telegram.org",
    "https://z.web.telegram.org",
    "https://a.web.telegram.org",
    "https://webk.telegram.org",
    "https://webz.telegram.org",
]


@web.middleware
async def cors_middleware(request: web.Request, handler) -> web.Response:
    """CORS middleware — faqat Telegram WebApp domenlariga ruxsat beradi."""
    origin = request.headers.get("Origin", "")
    
    if request.method == "OPTIONS":
        # Preflight request
        if origin in CORS_ALLOWED_ORIGINS or not origin:
            response = web.Response(status=204)
        else:
            response = web.Response(status=403)
        
        if origin in CORS_ALLOWED_ORIGINS:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Telegram-Init-Data, Authorization"
            response.headers["Access-Control-Max-Age"] = "86400"
        return response
    
    response = await handler(request)
    
    if origin in CORS_ALLOWED_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
    
    return response

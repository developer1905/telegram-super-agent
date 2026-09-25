"""
main.py — Asosiy Kirish Nuqtasi

Barcha tarkibiy qismlarni birlashtiradi:
1. Konfiguratsiyani tekshiradi
2. AIManager yaratadi
3. Telethon Userbot ni ishga tushiradi
4. aiogram Dispatcher + Routerlarni sozlaydi
5. APScheduler kunlik hisobotni ro'yxatdan o'tkazadi
6. Health Check HTTP Server (Render + UptimeRobot uchun)
7. Bot polling ni ishga tushiradi
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
import uuid
from datetime import datetime
from typing import Optional

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import BOT_TOKEN, ADMIN_ID, validate_config, WEBAPP_URL, get_clean_webapp_url, LOG_CHANNEL_ID
from core.ai_manager import AIManager
from core.database import db
from core.inbox_triage import init_inbox_triage
from core.mistral_agent_bot import get_second_bot, second_bot_router, setup_architect_bot
from core.userbot import create_userbot_client
import core.userbot as userbot_module
from services.scheduler import setup_scheduler
from security.api_auth import WebAppAuthMiddleware, cors_middleware
from security.rate_limiter import rate_limit_middleware

# Handlerlar
from handlers import menu_handler, message_handler, file_handler, photo_handler, email_handler, voice_handler, group_handler

# ─── Logging Sozlash ─────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# Bot ishga tushgan vaqti (uptime uchun)
START_TIME = datetime.now()

# Fon vazifalarini xavfsiz boshqarish va tozalash (Background Task Tracker)
from core import task_tracker
_BACKGROUND_TASKS = task_tracker._BACKGROUND_TASKS
track_background_task = task_tracker.track_background_task
cancel_all_background_tasks = task_tracker.cancel_all_background_tasks


# ─── Web Server & Telegram Mini App ───────────────────────────

async def health_handler(request: web.Request) -> web.Response:
    """
    UptimeRobot va Render health check uchun endpoint.
    GET /health → 200 OK + JSON holat
    """
    uptime_seconds = (datetime.now() - START_TIME).total_seconds()
    hours = int(uptime_seconds // 3600)
    minutes = int((uptime_seconds % 3600) // 60)

    return web.json_response({
        "status": "ok",
        "bot": "Super-Agent 2.0",
        "uptime": f"{hours}h {minutes}m",
        "userbot": "connected" if userbot_module.userbot else "disconnected",
        "timestamp": datetime.now().isoformat(),
    })


async def readiness_handler(request: web.Request) -> web.Response:
    """
    Readiness probe — kerakli dependencylar holatini tekshiradi.
    GET /readiness → 200 agar barcha kerakli komponentlar tayyor, 503 aks holda.
    """
    checks = {}
    is_ready = True

    # Database check
    try:
        await db.get_stats_summary()
        checks["database"] = "ok"
    except Exception as db_err:
        checks["database"] = f"error"
        is_ready = False
        logger.error("Readiness: DB xato: %s", db_err)

    # Bot token check
    if BOT_TOKEN:
        checks["bot_token"] = "configured"
    else:
        checks["bot_token"] = "missing"
        is_ready = False

    # Scheduler check
    checks["userbot"] = "connected" if userbot_module.userbot and userbot_module.userbot.is_connected() else "disconnected"

    return web.json_response(
        {"status": "ready" if is_ready else "not_ready", "checks": checks},
        status=200 if is_ready else 503,
    )


async def root_handler(request: web.Request) -> web.Response:
    """Asosiy sahifa — Render deployment tekshiruvi uchun."""
    return web.Response(
        text=(
            "<html><body style='font-family:sans-serif;padding:2em;background:#090d16;color:#f8fafc'>"
            "<h1>🤖 Telegram Super-Agent 2.0</h1>"
            "<p>Enterprise AI Agent ishlayapti ✅</p>"
            f"<p>Uptime: {(datetime.now() - START_TIME).total_seconds():.0f}s</p>"
            "<p><a style='color:#38bdf8' href='/webapp'>📱 Telegram Mini App</a> | "
            "<a style='color:#38bdf8' href='/health'>/health</a></p>"
            "</body></html>"
        ),
        content_type="text/html",
    )


async def webapp_page_handler(request: web.Request) -> web.Response:
    """Telegram Mini App (Web App) HTML interfeysi."""
    try:
        candidate_paths = [
            os.path.join(os.path.dirname(__file__), "webapp", "index.html"),
            os.path.join(os.getcwd(), "webapp", "index.html"),
            os.path.join(os.path.expanduser("~"), "superagent", "webapp", "index.html"),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "webapp", "index.html"),
        ]
        webapp_file = None
        for p in candidate_paths:
            if os.path.exists(p):
                webapp_file = p
                break

        if webapp_file:
            with open(webapp_file, "r", encoding="utf-8", errors="replace") as f:
                html = f.read()
            return web.Response(
                text=html,
                content_type="text/html",
                charset="utf-8",
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                },
            )
        logger.warning("webapp_page_handler: index.html quyidagi joylardan topilmadi: %s", candidate_paths)
        return web.Response(text="Web App index.html topilmadi", status=404, content_type="text/plain", charset="utf-8")
    except Exception as exc:
        logger.error("webapp_page_handler xatosi: %s", exc, exc_info=True)
        return web.Response(
            text="Web App sahifasini yuklashda xatolik yuz berdi. Iltimos, keyinroq qayta urinib ko'ring.",
            status=500,
            content_type="text/plain",
            charset="utf-8",
        )


async def landing_page_handler(request: web.Request) -> web.Response:
    """B2B Sotuv Landing Page HTML interfeysi."""
    try:
        candidate_paths = [
            os.path.join(os.path.dirname(__file__), "landing", "index.html"),
            os.path.join(os.getcwd(), "landing", "index.html"),
            os.path.join(os.path.expanduser("~"), "superagent", "landing", "index.html"),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "landing", "index.html"),
        ]
        landing_file = None
        for p in candidate_paths:
            if os.path.exists(p):
                landing_file = p
                break

        if landing_file:
            with open(landing_file, "r", encoding="utf-8", errors="replace") as f:
                html = f.read()
            return web.Response(
                text=html,
                content_type="text/html",
                charset="utf-8",
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                },
            )
        return web.Response(text="Landing page index.html topilmadi", status=404, content_type="text/plain", charset="utf-8")
    except Exception as exc:
        logger.error("landing_page_handler xatosi: %s", exc, exc_info=True)
        return web.Response(
            text="Landing sahifasini yuklashda xatolik yuz berdi.",
            status=500,
            content_type="text/plain",
            charset="utf-8",
        )



async def api_stats_handler(request: web.Request) -> web.Response:
    """Mini App uchun jonli statistika va joriy model/rol holati."""
    ai_manager: AIManager = request.app["ai_manager"]
    stats = await db.get_stats_summary()
    stats["current_provider"] = ai_manager.current_provider
    stats["current_or_model"] = ai_manager.current_or_model
    stats["current_role"] = ai_manager.current_role
    stats["is_admin"] = bool(request.get("is_admin", False))
    stats["user_id"] = str(request.get("authenticated_user_id", ""))
    stats["role"] = str(request.get("role", "user"))
    return web.json_response(stats)


def check_admin(request: web.Request) -> Optional[web.Response]:
    """Admin rolini tekshirish. Agar admin bo'lmasa 403 Forbidden qaytaradi."""
    if not request.get("is_admin", False):
        return web.json_response(
            {"error": "Ushbu amalni bajarish uchun Administrator huquqi talab qilinadi.", "code": "FORBIDDEN"},
            status=403,
            headers={"Content-Type": "application/json"}
        )
    return None


async def api_admin_users_handler(request: web.Request) -> web.Response:
    """Admin Panel: barcha ro'yxatdan o'tgan foydalanuvchilar ro'yxati (Faqat Administrator uchun)."""
    admin_err = check_admin(request)
    if admin_err:
        return admin_err
    users = await db.get_all_users()
    return web.json_response({"status": "ok", "users": users, "total": len(users)})


async def api_admin_block_user_handler(request: web.Request) -> web.Response:
    """Admin Panel: foydalanuvchini bloklash yoki blokdan chiqarish (Faqat Administrator uchun)."""
    admin_err = check_admin(request)
    if admin_err:
        return admin_err

    data = await request.json()
    user_id = str(data.get("user_id", "")).strip()
    is_blocked = bool(data.get("is_blocked", False))
    reason = str(data.get("reason", "")).strip()

    if not user_id:
        return web.json_response({"status": "error", "message": "user_id kiritilmadi"}, status=400)

    from config import ADMIN_ID
    if str(ADMIN_ID) and user_id == str(ADMIN_ID):
        return web.json_response({"status": "error", "message": "Tizim administratorini bloklash mumkin emas!"}, status=400)

    success = await db.set_user_blocked_status(user_id, is_blocked=is_blocked, reason=reason)
    return web.json_response({
        "status": "ok" if success else "error",
        "user_id": user_id,
        "is_blocked": is_blocked,
        "reason": reason,
    })


async def api_admin_overview_handler(request: web.Request) -> web.Response:
    """Admin Panel: umumiy foydalanuvchilar va xavfsizlik statistikasi (Faqat Administrator uchun)."""
    admin_err = check_admin(request)
    if admin_err:
        return admin_err

    users = await db.get_all_users()
    total_users = len(users)
    blocked_count = sum(1 for u in users if u.get("is_blocked"))
    active_count = total_users - blocked_count
    total_messages = sum(u.get("message_count", 0) for u in users)

    return web.json_response({
        "status": "ok",
        "total_users": total_users,
        "blocked_count": blocked_count,
        "active_count": active_count,
        "total_messages": total_messages,
    })


async def api_switch_model_handler(request: web.Request) -> web.Response:
    """Mini App orqali AI modelni almashtirish (Faqat Administrator uchun)."""
    admin_err = check_admin(request)
    if admin_err:
        return admin_err

    ai_manager: AIManager = request.app["ai_manager"]
    data = await request.json()
    model = data.get("model", "gemini")

    if model == "gemini":
        ai_manager.switch_provider("gemini")
    elif model in ("nvidia", "nemotron"):
        ai_manager.switch_provider("nvidia")
    elif model in ("mistral", "codestral"):
        ai_manager.switch_provider("mistral")
    elif model == "omniroute":
        ai_manager.switch_provider("omniroute")
    else:
        ai_manager.switch_openrouter_model(model)

    return web.json_response({"status": "ok", "provider": ai_manager.current_provider, "model": ai_manager.current_or_model})


async def api_switch_role_handler(request: web.Request) -> web.Response:
    """Mini App orqali tizim rolini almashtirish (Faqat Administrator uchun)."""
    admin_err = check_admin(request)
    if admin_err:
        return admin_err

    ai_manager: AIManager = request.app["ai_manager"]
    data = await request.json()
    role = data.get("role", "universal")
    ai_manager.switch_role(role)
    return web.json_response({"status": "ok", "role": ai_manager.current_role})


async def api_add_fact_handler(request: web.Request) -> web.Response:
    """Mini App orqali doimiy xotiraga yangi fakt qo'shish."""
    data = await request.json()
    key = data.get("key", "").strip()
    content = data.get("content", "").strip()
    category = data.get("category", "webapp").strip()
    user_id = str(request.get("authenticated_user_id") or "admin")
    if not key or not content:
        return web.json_response({"status": "error", "message": "Kalit yoki matn bo'sh"}, status=400)

    success = await db.save_fact(key, content, category=category, user_id=user_id)
    return web.json_response({"status": "ok" if success else "error"})


async def api_facts_handler(request: web.Request) -> web.Response:
    """Mini App: doimiy xotiradagi faktlar ro'yxati (Foydalanuvchi faqat o'zinikini ko'radi)."""
    user_id = request.get("authenticated_user_id")
    is_admin = request.get("is_admin", False)
    facts = await db.get_all_facts(user_id=None if is_admin else user_id)
    return web.json_response({"facts": facts})


async def api_delete_fact_handler(request: web.Request) -> web.Response:
    """Mini App: faktni o'chirish."""
    data = await request.json()
    key = data.get("key", "").strip()
    user_id = request.get("authenticated_user_id")
    is_admin = request.get("is_admin", False)
    if not key:
        return web.json_response({"status": "error", "message": "Kalit ko'rsatilmadi"}, status=400)
    success = await db.delete_fact(key, user_id=None if is_admin else user_id)
    return web.json_response({"status": "ok" if success else "error"})


async def api_reminders_handler(request: web.Request) -> web.Response:
    """Mini App: faol eslatmalar ro'yxati."""
    user_id = request.get("authenticated_user_id")
    is_admin = request.get("is_admin", False)
    reminders = await db.get_active_reminders(user_id=None if is_admin else user_id)
    return web.json_response({"reminders": reminders})


async def api_add_reminder_handler(request: web.Request) -> web.Response:
    """Mini App: yangi eslatma qo'shish."""
    data = await request.json()
    text = data.get("text", "").strip()
    remind_at = data.get("remind_at", "").strip()
    user_id = str(request.get("authenticated_user_id") or ADMIN_ID or "admin")
    if not text or not remind_at:
        return web.json_response({"status": "error", "message": "Matn yoki vaqt to'ldirilmadi"}, status=400)

    rem_id = await db.add_reminder(user_id, text, remind_at, user_id=user_id)
    return web.json_response({"status": "ok", "id": rem_id})


async def api_delete_reminder_handler(request: web.Request) -> web.Response:
    """Mini App: eslatmani bekor qilish."""
    data = await request.json()
    rem_id = data.get("id")
    user_id = request.get("authenticated_user_id")
    is_admin = request.get("is_admin", False)
    if not rem_id:
        return web.json_response({"status": "error", "message": "ID ko'rsatilmadi"}, status=400)
    success = await db.delete_reminder(int(rem_id), user_id=None if is_admin else user_id)
    return web.json_response({"status": "ok" if success else "error"})


async def api_scheduled_posts_handler(request: web.Request) -> web.Response:
    """Mini App: kutilayotgan kanal postlari (Faqat Administrator uchun)."""
    admin_err = check_admin(request)
    if admin_err:
        return admin_err
    posts = await db.get_all_pending_posts()
    return web.json_response({"posts": posts})


async def api_ai_playground_handler(request: web.Request) -> web.Response:
    """Mini App: AI sinov (Playground) — to'g'ridan-to'g'ri so'rov yuborish."""
    ai_manager: AIManager = request.app["ai_manager"]
    data = await request.json()
    prompt = data.get("prompt", "").strip()
    if not prompt:
        return web.json_response({"status": "error", "message": "Prompt matni bo'sh"}, status=400)
    try:
        response = await ai_manager.generate(prompt)
        return web.json_response({
            "status": "ok",
            "response": response,
            "provider": ai_manager.current_provider,
            "model": ai_manager.current_or_model,
            "role": ai_manager.current_role,
        })
    except Exception as exc:
        logger.error("api_ai_playground xatosi: %s", exc)
        return web.json_response({"status": "error", "message": "AI so'rovida xatolik yuz berdi"}, status=500)


async def api_system_info_handler(request: web.Request) -> web.Response:
    """Mini App: tizim holati, uptime, userbot, ma'lumotlar bazasi (Faqat Administrator uchun)."""
    admin_err = check_admin(request)
    if admin_err:
        return admin_err

    ai_manager: AIManager = request.app["ai_manager"]
    uptime_seconds = (datetime.now() - START_TIME).total_seconds()
    userbot_client = userbot_module.get_client() if hasattr(userbot_module, "get_client") else userbot_module.userbot
    userbot_connected = bool(userbot_client and userbot_client.is_connected())

    try:
        import zoneinfo
        tashkent_now = datetime.now(zoneinfo.ZoneInfo("Asia/Tashkent")).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        tashkent_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    hours = int(uptime_seconds // 3600)
    minutes = int((uptime_seconds % 3600) // 60)

    active_collabs = 0
    try:
        from core.bot_collab import ACTIVE_COLLABS, ACTIVE_CHIT_CHATS
        active_collabs = len(ACTIVE_COLLABS) + len(ACTIVE_CHIT_CHATS)
    except Exception:
        pass

    return web.json_response({
        "status": "ok",
        "uptime_human": f"{hours} soat, {minutes} daqiqa",
        "tashkent_time": tashkent_now,
        "userbot_connected": userbot_connected,
        "database_type": "Supabase + SQLite (Hybrid)" if db.use_supabase else "SQLite Local DB",
        "provider": ai_manager.current_provider,
        "model": ai_manager.current_or_model,
        "role": ai_manager.current_role,
        "active_collabs": active_collabs,
    })


async def api_managed_chats_handler(request: web.Request) -> web.Response:
    """Mini App: boshqarilayotgan barcha guruhlar va kanallar (Faqat Administrator uchun)."""
    admin_err = check_admin(request)
    if admin_err:
        return admin_err
    chats = await db.get_managed_chats()
    if not chats and LOG_CHANNEL_ID:
        try:
            bot: Optional[Bot] = request.app.get("bot")
            if bot:
                ch = await bot.get_chat(LOG_CHANNEL_ID)
                await db.register_managed_chat(
                    chat_id=LOG_CHANNEL_ID,
                    title=ch.title or "Asosiy Kanal",
                    username=ch.username or "",
                    chat_type="channel",
                    is_admin=True,
                )
                chats = await db.get_managed_chats()
        except Exception as exc:
            logger.debug("api_managed_chats auto-sync ogohlantirish: %s", exc)
    return web.json_response({"chats": chats})


async def api_chat_agent_handler(request: web.Request) -> web.Response:
    """Mini App: To'liq AI Agent chat muloqoti (xuddi botdagi kabi)."""
    ai_manager: AIManager = request.app["ai_manager"]
    bot: Optional[Bot] = request.app.get("bot")
    data = await request.json()
    user_text = data.get("message", "").strip()
    if not user_text:
        return web.json_response({"status": "error", "message": "Xabar bo'sh"}, status=400)

    # 1. Eslatma buyruqlari ("21:30 da eslat: ...", "15 daqiqadan keyin eslat: ...")
    if any(w in user_text.lower() for w in ["eslat", "remind", "eslatma", "eslatgin", "eslatib"]):
        try:
            from core.reminder_manager import parse_reminder_smart
            rem_res = await parse_reminder_smart(user_text, ai_manager)
            if rem_res:
                rem_time, rem_task = rem_res
                rem_id = await db.add_reminder(ADMIN_ID, rem_task, rem_time)
                return web.json_response({
                    "status": "ok",
                    "type": "reminder",
                    "response": (
                        f"⏰ **Eslatma muvaffaqiyatli saqlandi!**\n\n"
                        f"📝 **Vazifa:** {rem_task}\n"
                        f"🕒 **Eslatish vaqti:** `{rem_time}` (Toshkent vaqti)\n\n"
                        f"ID: `#{rem_id}` — Belgilangan vaqtda signal beriladi."
                    )
                })
        except Exception as exc:
            logger.warning("api_chat_agent reminder xato: %s", exc)

    # 2. Kanalga post buyrug'i ("post: ...", "kanalga yoz: ...")
    from handlers.message_handler import parse_post_command
    post_cmd = parse_post_command(user_text)
    if post_cmd and bot:
        target, post_text = post_cmd
        try:
            from core.userbot import post_to_channel_or_chat
            res = await post_to_channel_or_chat(bot, target, post_text)
            return web.json_response({
                "status": "ok",
                "type": "post",
                "response": res
            })
        except Exception as exc:
            logger.warning("api_chat_agent post xato: %s", exc)

    # 2.1 Midjourney v6 Rasm Chizish
    mj_match = re.match(r"^(?:/imagine|/midjourney|chiz|rasm\s+chiz|rasm\s+yarat|chizib\s+ber|draw)[:\s]+(.+)$", user_text, re.IGNORECASE | re.DOTALL)
    if mj_match:
        raw_prompt = mj_match.group(1).strip()
        try:
            from core.midjourney_agent import draw_midjourney_image
            import base64
            img_bytes, enhanced, ar, seed, *_ = await draw_midjourney_image(raw_prompt, ai_manager)
            if img_bytes:
                b64_img = base64.b64encode(img_bytes).decode("utf-8")
                return web.json_response({
                    "status": "ok",
                    "type": "image",
                    "image_base64": f"data:image/jpeg;base64,{b64_img}",
                    "response": f"🎨 **Midjourney v6 Badiiy Asari:**\n\n📝 **Prompt:** _{enhanced}_\n📐 O'lcham: `{ar}` | 🎲 Seed: `{seed}`"
                })
        except Exception as exc:
            logger.warning("api_chat_agent midjourney xato: %s", exc)

    # 2.2 Nous Hermes 3 Avtonom Agent
    hermes_match = re.match(r"^(?:/hermes|hermes)[:\s]+(.+)$", user_text, re.IGNORECASE | re.DOTALL)
    if hermes_match:
        task_prompt = hermes_match.group(1).strip()
        try:
            from core.hermes_agent import run_hermes_agent
            hermes_res = await run_hermes_agent(task_prompt, ai_manager)
            return web.json_response({
                "status": "ok",
                "type": "hermes",
                "response": hermes_res
            })
        except Exception as exc:
            logger.warning("api_chat_agent hermes xato: %s", exc)

    # 3. Fakt saqlash ("eslab qol: ...", "/remember ...")
    remember_match = re.match(r"^(?:/remember|eslab\s+qol|fakt\s+saqla)[:\s]+(.+)$", user_text, re.IGNORECASE)
    if remember_match:
        content_to_save = remember_match.group(1).strip()
        if ":" in content_to_save:
            f_key, f_val = content_to_save.split(":", 1)
        else:
            f_key = f"fact_{str(uuid.uuid4())[:6]}"
            f_val = content_to_save
        await db.save_fact(f_key.strip().lower(), f_val.strip(), category="chat_agent")
        return web.json_response({
            "status": "ok",
            "type": "memory",
            "response": f"🧠 **Doimiy xotiraga saqlandi!**\n\n• **Kalit:** `{f_key.strip().lower()}`\n• **Mazmun:** {f_val.strip()}\n\nAgent endi ushbu faktni barcha suhbatlarda inobatga oladi."
        })

    # 4. Internetdan jonli qidiruv ("qidir: ...", "google: ...")
    if re.match(r"^(?:qidir|internetdan\s+qidir|google)[:\s]+", user_text, re.IGNORECASE):
        search_q = re.sub(r"^(?:qidir|internetdan\s+qidir|google)[:\s]+", "", user_text, flags=re.IGNORECASE).strip()
        if search_q:
            try:
                from core.search_agent import answer_with_web_search
                ans = await answer_with_web_search(search_q, ai_manager)
                return web.json_response({
                    "status": "ok",
                    "type": "web_search",
                    "response": ans
                })
            except Exception as exc:
                logger.warning("api_chat_agent search xato: %s", exc)

    # 5. Oddiy so'rov → AI bilan to'liq muloqot
    try:
        response = await ai_manager.generate(user_text)
        return web.json_response({
            "status": "ok",
            "type": "chat",
            "response": response,
            "provider": ai_manager.current_provider,
            "model": ai_manager.current_or_model,
            "role": ai_manager.current_role
        })
    except Exception as exc:
        logger.error("api_chat_agent xatosi: %s", exc)
        return web.json_response({"status": "error", "message": "AI agent so'rovida xatolik"}, status=500)




async def api_tasks_get_handler(request: web.Request) -> web.Response:
    """Mini App: Notion / Todo vazifalar ro'yxati (Foydalanuvchi faqat o'z vazifalarini ko'radi)."""
    try:
        user_id = request.get("authenticated_user_id")
        is_admin = request.get("is_admin", False)
        tasks = await db.get_tasks(user_id=None if is_admin else user_id)
        return web.json_response({"status": "ok", "tasks": tasks})
    except Exception as exc:
        logger.error("api_tasks_get xatosi: %s", exc, exc_info=True)
        return web.json_response({"status": "error", "message": "Vazifalar ro'yxatini yuklashda xatolik yuz berdi"}, status=500)


async def api_tasks_add_handler(request: web.Request) -> web.Response:
    """Mini App: Yangi vazifa qo'shish."""
    try:
        data = await request.json()
        title = data.get("title", "").strip()
        due_date = data.get("due_date", "")
        user_id = str(request.get("authenticated_user_id") or "admin")
        if not title:
            return web.json_response({"status": "error", "message": "Vazifa nomi bo'sh"}, status=400)
        task_id = await db.add_task(user_id, title, due_date=due_date)
        return web.json_response({"status": "ok", "task_id": task_id})
    except Exception as exc:
        logger.error("api_tasks_add xatosi: %s", exc, exc_info=True)
        return web.json_response({"status": "error", "message": "Vazifa qo'shishda xatolik yuz berdi"}, status=500)


async def api_tasks_toggle_handler(request: web.Request) -> web.Response:
    """Mini App: Vazifani bajarilgan deb belgilash yoki o'chirish."""
    try:
        data = await request.json()
        task_id = int(data.get("task_id", 0))
        action = data.get("action", "complete")
        user_id = request.get("authenticated_user_id")
        is_admin = request.get("is_admin", False)
        if action == "complete":
            await db.complete_task(task_id, user_id=None if is_admin else user_id)
        elif action == "delete":
            await db.delete_task(task_id, user_id=None if is_admin else user_id)
        return web.json_response({"status": "ok"})
    except Exception as exc:
        logger.error("api_tasks_toggle xatosi: %s", exc, exc_info=True)
        return web.json_response({"status": "error", "message": "Vazifa holatini yangilashda xatolik yuz berdi"}, status=500)


async def api_uptime_get_handler(request: web.Request) -> web.Response:
    """Mini App: Uptime monitor saytlar ro'yxati (Faqat Administrator uchun)."""
    admin_err = check_admin(request)
    if admin_err:
        return admin_err
    try:
        monitors = await db.get_uptime_monitors()
        return web.json_response({"status": "ok", "monitors": monitors})
    except Exception as exc:
        logger.error("api_uptime_get xatosi: %s", exc, exc_info=True)
        return web.json_response({"status": "error", "message": "Monitoring ro'yxatini yuklashda xatolik yuz berdi"}, status=500)


async def api_uptime_add_handler(request: web.Request) -> web.Response:
    """Mini App: Uptime monitorga yangi sayt qo'shish (Faqat Administrator uchun)."""
    admin_err = check_admin(request)
    if admin_err:
        return admin_err
    try:
        data = await request.json()
        url = data.get("url", "").strip()
        name = data.get("name", "").strip() or url
        if not url:
            return web.json_response({"status": "error", "message": "URL kiritilmadi"}, status=400)
        from core.uptime_agent import check_url_health
        status_code, latency = await check_url_health(url)
        mon_id = await db.add_uptime_monitor(ADMIN_ID, url, name)
        await db.update_uptime_status(mon_id, status_code, latency)
        return web.json_response({
            "status": "ok",
            "id": mon_id,
            "url": url,
            "name": name,
            "last_status": status_code,
            "latency_ms": latency
        })
    except Exception as exc:
        logger.error("api_uptime_add xatosi: %s", exc, exc_info=True)
        return web.json_response({"status": "error", "message": "Monitoring qo'shishda xatolik yuz berdi"}, status=500)


async def api_uptime_delete_handler(request: web.Request) -> web.Response:
    """Mini App: Uptime monitorni o'chirish (Faqat Administrator uchun)."""
    admin_err = check_admin(request)
    if admin_err:
        return admin_err
    try:
        data = await request.json()
        mon_id = int(data.get("id", 0))
        await db.delete_uptime_monitor(mon_id)
        return web.json_response({"status": "ok"})
    except Exception as exc:
        logger.error("api_uptime_del xatosi: %s", exc, exc_info=True)
        return web.json_response({"status": "error", "message": "Monitoringni o'chirishda xatolik yuz berdi"}, status=500)


async def api_clean_server_handler(request: web.Request) -> web.Response:
    """Mini App: Serverni xavfsiz tozalash va disk holati (Faqat Administrator uchun)."""
    admin_err = check_admin(request)
    if admin_err:
        return admin_err
    try:
        from core.cleaner_agent import safe_clean_server_storage, get_system_storage_info
        res = await safe_clean_server_storage()
        storage = get_system_storage_info()
        return web.json_response({"status": "ok", "cleaned": res, "storage": storage})
    except Exception as exc:
        logger.error("api_clean_server xatosi: %s", exc, exc_info=True)
        return web.json_response({"status": "error", "message": "Serverni tozalashda xatolik yuz berdi"}, status=500)


async def api_profile_handler(request: web.Request) -> web.Response:
    """Mini App: Mem0 shaxsiy profil faktlari (Foydalanuvchi faqat o'z profilini ko'radi)."""
    try:
        user_id = request.get("authenticated_user_id")
        is_admin = request.get("is_admin", False)
        facts = await db.get_all_facts(user_id=None if is_admin else user_id)
        profile_facts = [
            f for f in facts
            if f.get("category") == "mem0_profile" or f.get("key", "").startswith("profile_")
        ]
        return web.json_response({
            "status": "ok",
            "profile_facts": profile_facts,
            "total_facts": len(facts)
        })
    except Exception as exc:
        logger.error("api_profile xatosi: %s", exc, exc_info=True)
        return web.json_response({"status": "error", "message": "Profil ma'lumotlarini olishda xatolik yuz berdi"}, status=500)


async def api_generate_image_handler(request: web.Request) -> web.Response:
    """Mini App: Midjourney v6 AI Rasm yaratish."""
    ai_manager: AIManager = request.app["ai_manager"]
    try:
        data = await request.json()
        prompt = data.get("prompt", "").strip()
        aspect_ratio = data.get("aspect_ratio", "1:1")
        style = data.get("style", "photo")
        model = data.get("model", "flux")
        if not prompt:
            return web.json_response({"status": "error", "message": "Prompt kiritilmadi"}, status=400)
        from core.midjourney_agent import draw_midjourney_image
        import base64
        full_prompt = prompt if "--style" in prompt else f"{prompt} --style {style}"
        img_bytes, enhanced, ar, seed, used_model, *_ = await draw_midjourney_image(
            full_prompt, ai_manager, aspect_ratio=aspect_ratio, model=model
        )
        if img_bytes:
            b64_img = base64.b64encode(img_bytes).decode("utf-8")
            return web.json_response({
                "status": "ok",
                "image_base64": f"data:image/jpeg;base64,{b64_img}",
                "enhanced_prompt": enhanced,
                "aspect_ratio": ar,
                "seed": seed,
                "model": used_model,
            })
        return web.json_response({"status": "error", "message": "Rasm yaratishda xatolik"}, status=500)
    except Exception as exc:
        logger.error("api_generate_image xatosi: %s", exc, exc_info=True)
        return web.json_response({"status": "error", "message": "Rasm yaratish jarayonida xatolik yuz berdi"}, status=500)


async def api_download_video_handler(request: web.Request) -> web.Response:
    """Mini App: Ijtimoiy tarmoqlardan video yuklab olish."""
    try:
        data = await request.json()
        url = data.get("url", "").strip()
        if not url:
            return web.json_response({"status": "error", "message": "URL kiritilmadi"}, status=400)
        from core.media_downloader import download_social_video
        info = await download_social_video(url)
        if info:
            filename = info.get("filename") or os.path.basename(info.get("file_path"))
            return web.json_response({
                "status": "ok",
                "title": info.get("title"),
                "platform": info.get("platform"),
                "size_mb": info.get("size_mb"),
                "filename": filename,
                "download_url": f"/api/video/stream/{filename}",
                "message": f"✅ {info.get('platform')} videosi muvaffaqiyatli tayyorlandi!"
            })
        return web.json_response({"status": "error", "message": "Video yuklab bo'lmadi yoki hajm 50MB dan katta"}, status=400)
    except Exception as exc:
        logger.error("api_download_video xatosi: %s", exc, exc_info=True)
        return web.json_response({"status": "error", "message": "Video yuklab olishda xatolik yuz berdi"}, status=500)


async def api_video_stream_handler(request: web.Request) -> web.StreamResponse:
    """Yuklangan videoni Web App ga oqim ko'rinishida uzatish."""
    filename = request.match_info.get("filename", "")
    filename = os.path.basename(filename)
    if not filename.endswith(".mp4"):
        return web.Response(text="Fayl formati noto'g'ri", status=400)

    file_path = os.path.join(os.path.dirname(__file__), "data", "temp", filename)
    if not os.path.exists(file_path):
        return web.Response(text="Video fayl topilmadi yoki o'chirilgan", status=404)

    response = web.FileResponse(file_path)
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.headers["Content-Type"] = "video/mp4"
    return response


async def api_video_audio_handler(request: web.Request) -> web.StreamResponse:
    """Yuklangan videodan MP3 audio ajratib Web App ga uzatish."""
    filename = request.match_info.get("filename", "")
    filename = os.path.basename(filename)
    base_name = os.path.splitext(filename)[0]
    mp3_filename = f"{base_name}.mp3"
    mp3_path = os.path.join(os.path.dirname(__file__), "data", "temp", mp3_filename)

    if not os.path.exists(mp3_path):
        video_path = os.path.join(os.path.dirname(__file__), "data", "temp", f"{base_name}.mp4")
        if not os.path.exists(video_path):
            return web.Response(text="Video fayl topilmadi", status=404)
        from core.media_downloader import extract_audio_from_video
        ok = await extract_audio_from_video(video_path, mp3_path)
        if not ok or not os.path.exists(mp3_path):
            return web.Response(text="Audio ajratib bo'lmadi", status=500)

    response = web.FileResponse(mp3_path)
    response.headers["Content-Disposition"] = f'attachment; filename="{mp3_filename}"'
    response.headers["Content-Type"] = "audio/mpeg"
    return response


async def api_agent_research_handler(request: web.Request) -> web.Response:
    """Mini App: Deep Research Agent API."""
    try:
        ai_manager: AIManager = request.app["ai_manager"]
        data = await request.json()
        topic = data.get("topic", "").strip()
        if not topic:
            return web.json_response({"status": "error", "message": "Tadqiqot mavzusi kiritilmadi"}, status=400)
        from core.expert_agents import DeepResearchAgent
        agent = DeepResearchAgent(ai_manager)
        report = await agent.conduct_research(topic)
        return web.json_response({"status": "ok", "report": report})
    except Exception as exc:
        logger.error("api_agent_research xatosi: %s", exc, exc_info=True)
        return web.json_response({"status": "error", "message": "Tadqiqot o'tkazishda xatolik yuz berdi"}, status=500)


async def api_agent_code_review_handler(request: web.Request) -> web.Response:
    """Mini App: Code Reviewer & Bug Fixer API."""
    try:
        ai_manager: AIManager = request.app["ai_manager"]
        data = await request.json()
        code_text = data.get("code", "").strip()
        language = data.get("language")
        if not code_text:
            return web.json_response({"status": "error", "message": "Kod matni kiritilmadi"}, status=400)
        from core.expert_agents import CodeReviewerAgent
        agent = CodeReviewerAgent(ai_manager)
        report = await agent.review_code(code_text, language=language)
        return web.json_response({"status": "ok", "report": report})
    except Exception as exc:
        logger.error("api_agent_code_review xatosi: %s", exc, exc_info=True)
        return web.json_response({"status": "error", "message": "Kodni tahlil qilishda xatolik yuz berdi"}, status=500)


async def api_agent_inspect_doc_handler(request: web.Request) -> web.Response:
    """Mini App: Smart Contract & Document Analyzer API."""
    try:
        ai_manager: AIManager = request.app["ai_manager"]
        data = await request.json()
        doc_text = data.get("doc_text", "").strip()
        if not doc_text:
            return web.json_response({"status": "error", "message": "Hujjat matni kiritilmadi"}, status=400)
        from core.expert_agents import DocumentContractAgent
        agent = DocumentContractAgent(ai_manager)
        report = await agent.analyze_document(doc_text)
        return web.json_response({"status": "ok", "report": report})
    except Exception as exc:
        logger.error("api_agent_inspect_doc xatosi: %s", exc, exc_info=True)
        return web.json_response({"status": "error", "message": "Hujjatni tahlil qilishda xatolik yuz berdi"}, status=500)


async def api_agent_smm_creator_handler(request: web.Request) -> web.Response:
    """Mini App: Viral SMM & Content Strategy API."""
    try:
        ai_manager: AIManager = request.app["ai_manager"]
        data = await request.json()
        topic = data.get("topic", "").strip()
        platform = data.get("platform", "Telegram")
        if not topic:
            return web.json_response({"status": "error", "message": "Mavzu kiritilmadi"}, status=400)
        from core.expert_agents import ViralSMMAgent
        agent = ViralSMMAgent(ai_manager)
        report = await agent.generate_content(topic, platform=platform)
        return web.json_response({"status": "ok", "report": report})
    except Exception as exc:
        logger.error("api_agent_smm_creator xatosi: %s", exc, exc_info=True)
        return web.json_response({"status": "error", "message": "SMM kontent yaratish jarayonida xatolik yuz berdi"}, status=500)


async def api_tts_voice_handler(request: web.Request) -> web.Response:
    """Mini App: Matnni ovozga aylantirish (TTS)."""
    try:
        data = await request.json()
        text = data.get("text", "").strip()
        voice = data.get("voice")
        if not text:
            return web.json_response({"status": "error", "message": "Matn kiritilmadi"}, status=400)
        from core.tts_agent import generate_speech_audio
        import base64
        audio_bytes = await generate_speech_audio(text, voice=voice)
        if audio_bytes:
            b64 = base64.b64encode(audio_bytes).decode("utf-8")
            return web.json_response({
                "status": "ok",
                "audio_base64": f"data:audio/mp3;base64,{b64}"
            })
        return web.json_response({"status": "error", "message": "Ovoz sintezida xatolik"}, status=500)
    except Exception as exc:
        logger.error("api_tts_voice xatosi: %s", exc, exc_info=True)
        return web.json_response({"status": "error", "message": "Ovoz sintez qilish jarayonida xatolik yuz berdi"}, status=500)


async def api_astrology_calculate_handler(request: web.Request) -> web.Response:
    """Mini App: Natal Karta hisoblash va saqlash API."""
    try:
        data = await request.json()
        birth_date = data.get("birth_date", "").strip()
        birth_time = data.get("birth_time", "12:00").strip()
        city = data.get("city", "Toshkent").strip()
        user_id = str(request.get("authenticated_user_id") or data.get("user_id", "default_user"))

        if not birth_date:
            return web.json_response({"status": "error", "message": "Tug'ilgan sana kiritilmadi"}, status=400)

        from core.astrology_agent import calculate_full_natal_chart, calculate_transits, calculate_solar_return_summary
        chart = calculate_full_natal_chart(birth_date, birth_time, city)
        transits = calculate_transits(chart.get("planets", {}))
        solar = calculate_solar_return_summary(chart.get("planets", {}).get("Quyosh", {}).get("longitude", 0.0), 2026)

        await db.save_astrology_profile(
            user_id=user_id,
            birth_date=birth_date,
            birth_time=birth_time,
            city=city,
            chart_data=chart,
        )

        return web.json_response({
            "status": "ok",
            "chart": chart,
            "transits": transits,
            "solar": solar,
        })
    except Exception as exc:
        logger.error("api_astrology_calculate xatosi: %s", exc, exc_info=True)
        return web.json_response({"status": "error", "message": "Natal kartani hisoblashda xatolik yuz berdi"}, status=500)


async def api_astrology_profile_handler(request: web.Request) -> web.Response:
    """Mini App: Mavjud Astrologiya profilini olish."""
    try:
        auth_user_id = str(request.get("authenticated_user_id") or "")
        requested_user_id = request.query.get("user_id")
        is_admin = request.get("is_admin", False)

        if requested_user_id and str(requested_user_id) != auth_user_id and not is_admin:
            return web.json_response(
                {"status": "forbidden", "message": "Boshqa foydalanuvchining astrologiya profiliga kirish taqiqlangan.", "code": "FORBIDDEN"},
                status=403
            )

        target_user_id = str(requested_user_id if (requested_user_id and is_admin) else auth_user_id)
        profile = await db.get_astrology_profile(target_user_id)
        if profile and profile.get("chart"):
            from core.astrology_agent import calculate_transits, calculate_solar_return_summary
            chart = profile["chart"]
            transits = calculate_transits(chart.get("planets", {}))
            solar = calculate_solar_return_summary(chart.get("planets", {}).get("Quyosh", {}).get("longitude", 0.0), 2026)
            return web.json_response({
                "status": "ok",
                "profile": {
                    "birth_date": profile.get("birth_date"),
                    "birth_time": profile.get("birth_time"),
                    "city": profile.get("city"),
                    "chart": chart,
                    "transits": transits,
                    "solar": solar,
                }
            })
        return web.json_response({"status": "not_found", "message": "Astrologiya profili mavjud emas", "code": "NOT_FOUND"}, status=404)
    except Exception as exc:
        logger.error("api_astrology_profile xatosi: %s", exc, exc_info=True)
        return web.json_response({"status": "error", "message": "Astrologiya profilini yuklashda xatolik yuz berdi"}, status=500)


async def api_astrology_interpret_handler(request: web.Request) -> web.Response:
    """Mini App: 20 yillik tajribali munajjim-olim (Grandmaster) darajasida voqeaviy prognoz generatsiya qilish."""
    try:
        ai_manager: AIManager = request.app["ai_manager"]
        data = await request.json()
        question = data.get("question", "").strip()
        auth_user_id = str(request.get("authenticated_user_id") or "")
        requested_user_id = data.get("user_id")
        is_admin = request.get("is_admin", False)

        if requested_user_id and str(requested_user_id) != auth_user_id and not is_admin:
            return web.json_response(
                {"status": "forbidden", "message": "Boshqa foydalanuvchi nomidan tahlil olish taqiqlangan.", "code": "FORBIDDEN"},
                status=403
            )

        target_user_id = str(requested_user_id if (requested_user_id and is_admin) else auth_user_id)
        selected_model = data.get("model", "")

        profile = await db.get_astrology_profile(target_user_id)
        if not profile or not profile.get("chart"):
            return web.json_response({"status": "error", "message": "Avval natal kartangizni hisoblang"}, status=400)

        custom_lots = profile.get("custom_lots", [])
        from core.astrology_agent import build_grandmaster_astrology_prompt
        prompt = build_grandmaster_astrology_prompt(profile, custom_lots, question=question, target_year=2026)
        prompt += "\n\n[QAT'IY TALAB: BARCHA TAHLIL VA XULOSALARINGIZNI FAQAT O'ZBEK TILIDA (LOTIN ALIFBOSIDA) YOZING! INGLIZ YOKI RUS TILIDA SO'Z ISHLATMANG!]"

        # Modelni dinamik almashtirish (Hermes 3, Gemini va hk)
        prev_provider = ai_manager.current_provider
        prev_model = ai_manager.current_or_model

        if "hermes" in selected_model.lower():
            ai_manager.switch_openrouter_model("hermes")
        elif "gemini" in selected_model.lower():
            ai_manager.switch_provider("gemini")

        try:
            report = await ai_manager.generate(prompt, save_history=False, chat_id=f"astro_{target_user_id}")
            from core.astrology_agent import ensure_uzbek_astrology_report
            report = await ensure_uzbek_astrology_report(report, ai_manager)
        finally:
            ai_manager.current_provider = prev_provider
            ai_manager.current_or_model = prev_model

        return web.json_response({
            "status": "ok",
            "report": report,
            "response": report,
            "lots_count": len(custom_lots),
        })
    except Exception as exc:
        logger.error("api_astrology_interpret xatosi: %s", exc, exc_info=True)
        return web.json_response({"status": "error", "message": "Astrologik tahlilda xatolik yuz berdi"}, status=500)


async def api_astrology_lots_handler(request: web.Request) -> web.Response:
    """Mini App: 513 tagacha bo'lgan Arab Lotlarini qabul qilish va profilga saqlash."""
    try:
        data = await request.json()
        auth_user_id = str(request.get("authenticated_user_id") or "")
        requested_user_id = data.get("user_id")
        is_admin = request.get("is_admin", False)

        if requested_user_id and str(requested_user_id) != auth_user_id and not is_admin:
            return web.json_response(
                {"status": "forbidden", "message": "Boshqa foydalanuvchiga lot saqlash taqiqlangan.", "code": "FORBIDDEN"},
                status=403
            )

        target_user_id = str(requested_user_id if (requested_user_id and is_admin) else auth_user_id)
        raw_lots = data.get("lots_data", "")

        from core.astrology_agent import parse_custom_arabic_lots
        parsed = parse_custom_arabic_lots(raw_lots)
        if not parsed:
            return web.json_response({"status": "error", "message": "Lotlar ma'lumotlarini o'qib bo'lmadi"}, status=400)

        await db.save_custom_lots(target_user_id, parsed)
        return web.json_response({
            "status": "ok",
            "count": len(parsed),
            "lots": parsed,
            "message": f"Muvaffaqiyatli! {len(parsed)} ta Arab Loti xotiraga saqlandi va AI tahliliga ulandi."
        })
    except Exception as exc:
        logger.error("api_astrology_lots xatosi: %s", exc, exc_info=True)
        return web.json_response({"status": "error", "message": "Arab lotlarini saqlashda xatolik yuz berdi"}, status=500)


async def start_web_server(ai_manager: AIManager, bot: Optional[Bot] = None) -> web.AppRunner:
    """aiohttp web server va Mini App endpointlarini ishga tushiradi."""
    # Middleware zanjiri: cors -> rate_limit -> auth -> handler
    app = web.Application(middlewares=[
        cors_middleware,
        rate_limit_middleware,
        WebAppAuthMiddleware.middleware,
    ])
    app["ai_manager"] = ai_manager
    if bot:
        app["bot"] = bot

    # Public (auth talab qilinmaydigan) sahifalar
    app.router.add_get("/", webapp_page_handler)
    app.router.add_get("/webapp", webapp_page_handler)
    app.router.add_get("/webapp/", webapp_page_handler)
    app.router.add_get("/landing", landing_page_handler)
    app.router.add_get("/landing/", landing_page_handler)
    app.router.add_get("/health", health_handler)
    app.router.add_get("/readiness", readiness_handler)
    app.router.add_get("/api/stats", api_stats_handler)
    app.router.add_post("/api/switch_model", api_switch_model_handler)
    app.router.add_post("/api/switch_role", api_switch_role_handler)
    app.router.add_get("/api/facts", api_facts_handler)
    app.router.add_post("/api/add_fact", api_add_fact_handler)
    app.router.add_post("/api/delete_fact", api_delete_fact_handler)
    app.router.add_get("/api/reminders", api_reminders_handler)
    app.router.add_post("/api/add_reminder", api_add_reminder_handler)
    app.router.add_post("/api/delete_reminder", api_delete_reminder_handler)
    app.router.add_get("/api/scheduled_posts", api_scheduled_posts_handler)
    app.router.add_post("/api/ai_playground", api_ai_playground_handler)
    app.router.add_get("/api/system_info", api_system_info_handler)
    app.router.add_get("/api/managed_chats", api_managed_chats_handler)
    app.router.add_post("/api/chat_agent", api_chat_agent_handler)

    # Yangi Super-Agent Vositalari
    app.router.add_get("/api/tasks", api_tasks_get_handler)
    app.router.add_post("/api/tasks/add", api_tasks_add_handler)
    app.router.add_post("/api/tasks/toggle", api_tasks_toggle_handler)
    app.router.add_get("/api/uptime", api_uptime_get_handler)
    app.router.add_post("/api/uptime/add", api_uptime_add_handler)
    app.router.add_post("/api/uptime/delete", api_uptime_delete_handler)
    app.router.add_post("/api/clean_server", api_clean_server_handler)
    app.router.add_get("/api/profile", api_profile_handler)
    app.router.add_post("/api/generate_image", api_generate_image_handler)
    app.router.add_post("/api/download_video", api_download_video_handler)
    app.router.add_get("/api/video/stream/{filename}", api_video_stream_handler)
    app.router.add_get("/api/video/audio/{filename}", api_video_audio_handler)
    app.router.add_post("/api/tts_voice", api_tts_voice_handler)
    app.router.add_post("/api/agent/research", api_agent_research_handler)
    app.router.add_post("/api/agent/code_review", api_agent_code_review_handler)
    app.router.add_post("/api/agent/inspect_doc", api_agent_inspect_doc_handler)
    app.router.add_post("/api/agent/smm_creator", api_agent_smm_creator_handler)

    # Astrologiya & Natal Karta API
    app.router.add_post("/api/astrology/calculate", api_astrology_calculate_handler)
    app.router.add_get("/api/astrology/profile", api_astrology_profile_handler)
    app.router.add_post("/api/astrology/interpret", api_astrology_interpret_handler)
    app.router.add_post("/api/astrology/lots", api_astrology_lots_handler)

    # Administrator Paneli & Foydalanuvchilar Boshqaruvi
    app.router.add_get("/api/admin/users", api_admin_users_handler)
    app.router.add_post("/api/admin/block_user", api_admin_block_user_handler)
    app.router.add_get("/api/admin/overview", api_admin_overview_handler)

    port = int(os.getenv("PORT", "8080"))
    runner = web.AppRunner(app)
    await runner.setup()

    candidate_ports = [port]
    if port != 8080 and 8080 not in candidate_ports:
        candidate_ports.append(8080)
    for alt in (8081, 8888, 5000):
        if alt not in candidate_ports:
            candidate_ports.append(alt)

    server_started = False
    for p in candidate_ports:
        try:
            site = web.TCPSite(
                runner,
                host="0.0.0.0",
                port=p,
                reuse_address=True,
                reuse_port=True if hasattr(os, "SO_REUSEPORT") else False,
            )
            await site.start()
            logger.info("✅ Web App Server faol: http://0.0.0.0:%d/webapp", p)
            server_started = True
            break
        except Exception as port_err:
            logger.warning("Port %d band yoki xatolik yuz berdi: %s. Boshqa port sinab ko'rilmoqda...", p, port_err)

    if not server_started:
        logger.error("⚠️ Hech qaysi portda Web App server ulanmadi. Bot serverlarsiz faoliyatini davom ettiradi.")

    return runner


# ─── Asosiy Asinxron Funksiya ─────────────────────────────────

async def main() -> None:
    web_runner: Optional[web.AppRunner] = None
    scheduler = None

    # 1. Konfiguratsiyani tekshirish
    missing = validate_config()
    if missing:
        logger.critical("❌ Yetishmayotgan muhit o'zgaruvchilari: %s", missing)
        logger.critical("💡 .env.example faylini .env ga nusxalab to'ldiring!")
        sys.exit(1)

    logger.info("✅ Konfiguratsiya tekshirildi")

    # 2. AIManager yaratish
    ai_manager = AIManager()
    logger.info("✅ AI Manager tayyor")

    # 2.5. Crash Recovery: steyl avtonom vazifalarni qayta tiklash
    from core.autonomy_manager import autonomy_manager
    try:
        recovered = await autonomy_manager.recover_stale_tasks_on_startup()
        if recovered:
            logger.info("✅ Qayta tiklangan steyl avtonom vazifalar: %d ta", recovered)
    except Exception as rec_err:
        logger.warning("recover_stale_tasks_on_startup xatosi: %s", rec_err)

    # 3. aiogram Bot va Dispatcher sozlash
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
    )
    dp = Dispatcher()

    # 4. Web App va Health Server ni ishga tushirish (xatolikka chidamli)
    try:
        web_runner = await start_web_server(ai_manager, bot=bot)
    except Exception as ws_err:
        logger.warning("⚠️ Web App server ishga tushirishda xatolik: %s (Bot ishlashda davom etadi)", ws_err)

    # 5. Telethon Userbot ni ishga tushirish
    userbot_client = create_userbot_client()
    try:
        await userbot_client.connect()
        if not await userbot_client.is_user_authorized():
            logger.warning(
                "⚠️ Userbot avtorizatsiyasiz. "
                "USERBOT_SESSION ni to'g'ri qo'ying."
            )
        else:
            userbot_module.userbot = userbot_client
            me = await userbot_client.get_me()
            logger.info(
                "✅ Userbot ulandi: @%s (ID: %s)",
                me.username or "username_yo'q",
                me.id,
            )

            # Telegram suhbatini avtomatik o'qib bazaga qayta saqlash (Orqa fonda)
            async def _auto_sync_telegram_history():
                try:
                    await asyncio.sleep(3)
                    bot_me = await bot.get_me()
                    if bot_me.username:
                        res = await userbot_module.sync_chat_history_from_telegram(
                            target_username_or_id=bot_me.username,
                            ai_manager=ai_manager,
                            limit=60,
                        )
                        logger.info("Telegram xotira sinxronizatsiyasi: %s", res.get("message"))
                except Exception as sync_err:
                    logger.debug("Avtomatik Telegram xotira sinxronlash: %s", sync_err)

            track_background_task(_auto_sync_telegram_history(), name="auto_sync_telegram_history")
    except Exception as exc:
        logger.error("⚠️ Userbot ulanmadi: %s", exc)

    # Telegram Mini App Menu Button (pastki chap menyu tugmasi)
    target_webapp_url = get_clean_webapp_url()
    if target_webapp_url:
        try:
            from aiogram.types import MenuButtonWebApp, WebAppInfo
            await bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(
                    text="📱 Mini App",
                    web_app=WebAppInfo(url=target_webapp_url),
                )
            )
            logger.info("✅ Telegram Menu Button (Mini App) sozlandi: %s", target_webapp_url)
        except Exception as exc:
            logger.warning("Menu Button sozlashda xato: %s", exc)

    # 5.5. Doimiy RAG xotirani (Supabase -> SQLite) va kanalni (LOG_CHANNEL_ID) yangilash
    async def _init_rag_and_channel_sync():
        try:
            facts = await db.get_all_facts()
            logger.info("✅ RAG doimiy xotira yuklandi va keshlandi: %d ta fakt", len(facts))
        except Exception as r_err:
            logger.warning("RAG xotira sinxronlash ogohlantirish: %s", r_err)

        if LOG_CHANNEL_ID:
            try:
                ch = await bot.get_chat(LOG_CHANNEL_ID)
                ch_title = ch.title or f"Asosiy Kanal ({LOG_CHANNEL_ID})"
                ch_username = ch.username or ""
                await db.add_or_update_managed_chat(
                    chat_id=LOG_CHANNEL_ID,
                    title=ch_title,
                    chat_type="channel",
                    username=ch_username,
                )
                logger.info("✅ Boshqariladigan kanal (LOG_CHANNEL_ID) yangilandi: '%s' (@%s)", ch_title, ch_username)
            except Exception as ch_err:
                logger.debug("LOG_CHANNEL_ID bot orqali tekshirish ogohlantirish: %s", ch_err)

    track_background_task(_init_rag_and_channel_sync(), name="init_rag_and_channel_sync")

    # AIManager ni data sifatida uzatish
    dp["ai_manager"] = ai_manager
    dp["ai"] = ai_manager

    # Routerlarni ulash (tartib: menu, email, file, photo, voice, group, message)
    dp.include_router(menu_handler.router)
    dp.include_router(email_handler.router)
    dp.include_router(file_handler.router)
    dp.include_router(photo_handler.router)
    dp.include_router(voice_handler.router)    # Voice-to-Task
    dp.include_router(group_handler.router)    # Guruhlar, kanallar va my_chat_member

    dp.include_router(message_handler.router)  # Oxirida (catch-all)

    logger.info("✅ Barcha handlerlar ulandi (Guruhlar va Kanallar avtopiloti qo'shildi)")

    # 2-Botni (Mistral Arxitektor @architect7_bot) mustaqil fonda ishga tushirish
    from core.mistral_agent_bot import set_main_bot_instance
    set_main_bot_instance(bot)

    second_bot = get_second_bot()
    second_bot_task: Optional[asyncio.Task] = None
    if second_bot:
        async def _run_second_bot_isolated():
            try:
                dp_second = Dispatcher()
                dp_second.include_router(second_bot_router)
                await second_bot.delete_webhook(drop_pending_updates=False)
                sec_me = await second_bot.get_me()
                logger.info("🚀 2-Bot (@%s - %s) mustaqil dispatcher bilan ishga tushdi!", sec_me.username, sec_me.first_name)
                await setup_architect_bot(second_bot)
                await dp_second.start_polling(
                    second_bot,
                    handle_signals=False,
                    allowed_updates=[
                        "message",
                        "edited_message",
                        "channel_post",
                        "edited_channel_post",
                        "callback_query",
                    ],
                )
            except Exception as sec_err:
                logger.error("2-Bot polling xatosi: %s", sec_err, exc_info=True)

        second_bot_task = track_background_task(_run_second_bot_isolated(), name="second_bot_isolated")

    # 6. Smart Inbox Triage kuzatuvchisini faollashtirish
    if userbot_module.userbot and userbot_module.userbot.is_connected():
        await init_inbox_triage(userbot_module.userbot, bot, ai_manager)

    # 7. APScheduler kunlik hisobot va SMM avtopilot
    scheduler = setup_scheduler(bot, ai_manager)
    scheduler.start()
    logger.info("✅ Scheduler ishga tushdi (21:00 da hisobot, SMM avtopilot faol)")

    # 7.5. Avtonom Jonli Muloqotlarni Tiklash (Avto-suhbat faol bo'lgan chatlar uchun)
    async def _resume_auto_chat_conversations():
        try:
            await asyncio.sleep(6.0)
            all_facts = await db.get_all_facts()
            for f in all_facts:
                if f.get("category") == "auto_chat" and f.get("content") == "1":
                    k = f.get("key", "")
                    if k.startswith("auto_chat_"):
                        try:
                            c_id = int(k.replace("auto_chat_", ""))
                            from core.bot_skills import start_continuous_living_conversation, autonomous_dialogue_engine
                            if not autonomous_dialogue_engine.is_running(c_id):
                                task = track_background_task(
                                    start_continuous_living_conversation(
                                        chat_id=c_id,
                                        bot_white=bot,
                                        bot_black=second_bot,
                                        origin_bot=bot
                                    ),
                                    name=f"living_dialogue_{c_id}"
                                )
                                autonomous_dialogue_engine.active_tasks[c_id] = task
                                logger.info("☕ Avto-suhbat avtomatik qayta tiklandi: chat_id=%s", c_id)
                        except Exception as e_res:
                            logger.warning("Avto-suhbat tiklash xatosi (%s): %s", k, e_res)
        except Exception as e_all:
            logger.warning("_resume_auto_chat_conversations xatosi: %s", e_all)

    track_background_task(_resume_auto_chat_conversations(), name="resume_auto_chat")

    # 8. Adminga ishga tushdi xabari
    from core.safe_send import safe_send_message
    try:
        await safe_send_message(
            bot=bot,
            chat_id=ADMIN_ID,
            text=(
                "🚀 *Super-Agent ishga tushdi!*\n\n"
                "✅ AI Manager: tayyor\n"
                f"✅ Userbot: {'ulandi' if userbot_module.userbot else '⚠️ ulanmagan'}\n"
                "✅ Scheduler: 21:00 da hisobot\n"
                "✅ Health Server: /health endpoint faol\n"
                "✅ Guruh va Kanallar avtopiloti: faol\n"
                f"✅ 2-Bot (@architect7_bot): {'faol' if second_bot else 'sozlanmagan'}\n\n"
                "Menyuni ochish uchun /start ni bosing."
            ),
            parse_mode="Markdown",
        )
    except Exception as exc:
        logger.warning("Adminga xabar yuborilmadi: %s", exc)

    # 9. Asosiy bot polling boshlash (Webhook to'qnashuvining oldini olish)
    try:
        await bot.delete_webhook(drop_pending_updates=False)
    except Exception as exc:
        logger.warning("delete_webhook xatosi: %s", exc)

    logger.info("🤖 Bot polling boshlandi (Doimiy 24/7 uzluksiz rejim)...")
    retry_delay = 3.0
    try:
        while True:
            try:
                await dp.start_polling(
                    bot,
                    allowed_updates=[
                        "message",
                        "edited_message",
                        "channel_post",
                        "edited_channel_post",
                        "my_chat_member",
                        "chat_member",
                        "callback_query",
                    ],
                )
                # Agar polling to'g'ri yakunlansa (masalan, stop chaqirilsa)
                break
            except asyncio.CancelledError:
                logger.info("🛑 Polling bekor qilindi (To'xtatish buyrug'i).")
                break
            except Exception as poll_err:
                err_text = str(poll_err)
                if "Conflict" in err_text or "terminated by other getUpdates" in err_text:
                    logger.critical(
                        "❌ TELEGRAM TO'QNASHUV (ConflictError): Serverda boshqa bot nusxasi ishlab turibdi! "
                        "10 soniyadan so'ng qayta ulanishga harakat qilinadi..."
                    )
                    await asyncio.sleep(10.0)
                else:
                    logger.warning(
                        "⚠️ Tarmoq xatosi yoki aloqa uzilishi: %s. %.1f soniyadan so'ng avtomatik qayta ulanmoqda...",
                        poll_err,
                        retry_delay,
                    )
                    await asyncio.sleep(retry_delay)
                    retry_delay = min(retry_delay * 1.4, 20.0)
    finally:
        # [Shutdown 1/11] Scheduler to'xtatish
        if scheduler:
            try:
                scheduler.shutdown(wait=False)
                logger.info("[Shutdown 1/11] Scheduler to'xtatildi")
            except Exception as sch_err:
                logger.debug("Scheduler to'xtatishda xatolik: %s", sch_err)

        # [Shutdown 2/11] Yangi avtonom vazifalarni qabul qilishni to'xtatish
        try:
            from core.autonomy_manager import autonomy_manager
            await autonomy_manager.set_global_enabled(False)
            logger.info("[Shutdown 2/11] AutonomyManager global to'xtatildi")
        except Exception as aut_err:
            logger.debug("Autonomy global disable xatosi: %s", aut_err)

        # [Shutdown 3/11] Faol avtonom vazifalarni bekor qilish
        try:
            cancelled_tasks = await autonomy_manager.cancel_all_tasks(reason="System shutdown")
            logger.info("[Shutdown 3/11] Faol avtonom vazifalar bekor qilindi (%d ta)", len(cancelled_tasks))
        except Exception as aut_can_err:
            logger.debug("Autonomy cancel all xatosi: %s", aut_can_err)

        # [Shutdown 4/11] Qolgan barcha fon vazifalarini to'xtatish (Tracked Background Tasks)
        try:
            await cancel_all_background_tasks(timeout=5.0)
            logger.info("[Shutdown 4/11] Fon vazifalari to'xtatildi")
        except Exception as wait_err:
            logger.debug("Fon vazifalarini to'xtatishda kutish xatosi: %s", wait_err)

        # [Shutdown 5/11] Web Runner cleanup
        if web_runner:
            try:
                await web_runner.cleanup()
                logger.info("[Shutdown 5/11] Web Runner tozalandi")
            except Exception as wr_err:
                logger.debug("Web runner tozalashda xatolik: %s", wr_err)

        # [Shutdown 6/11] Telegram asosiy bot sessiyasini yopish
        try:
            await bot.session.close()
            logger.info("[Shutdown 6/11] Telegram asosiy bot sessiyasi yopildi")
        except Exception as bot_err:
            logger.debug("Bot sessiyasini yopishda xatolik: %s", bot_err)

        # [Shutdown 7/11] 2-Bot sessiyasi va taskini yopish
        if second_bot_task and not second_bot_task.done():
            second_bot_task.cancel()
        if second_bot:
            try:
                await second_bot.session.close()
                logger.info("[Shutdown 7/11] 2-Bot sessiyasi yopildi")
            except Exception as s_err:
                logger.debug("2-Bot sessiyasini yopishda xatolik: %s", s_err)

        # [Shutdown 8/11] Userbot ulanishini uzish
        if userbot_module.userbot and userbot_module.userbot.is_connected():
            try:
                await userbot_module.userbot.disconnect()
                logger.info("[Shutdown 8/11] Userbot uzildi")
            except Exception as ub_err:
                logger.debug("Userbot uzishda xatolik: %s", ub_err)

        # [Shutdown 9/11] Ma'lumotlar bazasi resurslarini yopish
        try:
            db.close()
            logger.info("[Shutdown 9/11] Ma'lumotlar bazasi ulanishi yopildi")
        except Exception as db_err:
            logger.debug("DB close xatosi: %s", db_err)

        # [Shutdown 10/11] Logging resurslarini flush qilish
        try:
            logging.shutdown()
        except Exception:
            pass

        # [Shutdown 11/11] Yakuniy xavfsiz to'xtatish xabari
        print("👋 [Shutdown 11/11] Bot to'liq va xavfsiz to'xtatildi. Barcha resurslar tozalandi.")


# ─── Kirish Nuqtasi ───────────────────────────────────────────

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Foydalanuvchi tomonidan to'xtatildi (Ctrl+C)")
    except Exception as exc:
        logger.critical("💥 Kritik xato: %s", exc, exc_info=True)
        sys.exit(1)

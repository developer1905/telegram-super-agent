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

from config import BOT_TOKEN, ADMIN_ID, validate_config, WEBAPP_URL, get_clean_webapp_url
from core.ai_manager import AIManager
from core.database import db
from core.inbox_triage import init_inbox_triage
from core.userbot import create_userbot_client
import core.userbot as userbot_module
from services.scheduler import setup_scheduler

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
        "bot": "Super-Agent 2.0 Enterprise",
        "uptime": f"{hours}h {minutes}m",
        "userbot": "connected" if userbot_module.userbot else "disconnected",
        "timestamp": datetime.now().isoformat(),
    })


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
    webapp_file = os.path.join(os.path.dirname(__file__), "webapp", "index.html")
    if os.path.exists(webapp_file):
        with open(webapp_file, "r", encoding="utf-8") as f:
            html = f.read()
        return web.Response(
            text=html,
            content_type="text/html",
            headers={
                "Access-Control-Allow-Origin": "*",
                "Cache-Control": "no-cache, no-store, must-revalidate",
            },
        )
    return web.Response(text="Web App index.html topilmadi", status=404)


async def landing_page_handler(request: web.Request) -> web.Response:
    """B2B Sotuv Landing Page HTML interfeysi."""
    landing_file = os.path.join(os.path.dirname(__file__), "landing", "index.html")
    if os.path.exists(landing_file):
        with open(landing_file, "r", encoding="utf-8") as f:
            html = f.read()
        return web.Response(
            text=html,
            content_type="text/html",
            headers={
                "Access-Control-Allow-Origin": "*",
                "Cache-Control": "no-cache, no-store, must-revalidate",
            },
        )
    return web.Response(text="Landing page index.html topilmadi", status=404)



async def api_stats_handler(request: web.Request) -> web.Response:
    """Mini App uchun jonli statistika va joriy model/rol holati."""
    ai_manager: AIManager = request.app["ai_manager"]
    stats = await db.get_stats_summary()
    stats["current_provider"] = ai_manager.current_provider
    stats["current_or_model"] = ai_manager.current_or_model
    stats["current_role"] = ai_manager.current_role
    return web.json_response(stats)


async def api_switch_model_handler(request: web.Request) -> web.Response:
    """Mini App orqali AI modelni almashtirish."""
    ai_manager: AIManager = request.app["ai_manager"]
    data = await request.json()
    model = data.get("model", "gemini")

    if model == "gemini":
        ai_manager.switch_provider("gemini")
    elif model == "omniroute":
        ai_manager.switch_provider("omniroute")
    else:
        ai_manager.switch_openrouter_model(model)

    return web.json_response({"status": "ok", "provider": ai_manager.current_provider, "model": ai_manager.current_or_model})


async def api_switch_role_handler(request: web.Request) -> web.Response:
    """Mini App orqali tizim rolini almashtirish."""
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
    if not key or not content:
        return web.json_response({"status": "error", "message": "Kalit yoki matn bo'sh"}, status=400)

    success = await db.save_fact(key, content, category=category)
    return web.json_response({"status": "ok" if success else "error"})


async def api_facts_handler(request: web.Request) -> web.Response:
    """Mini App: doimiy xotiradagi barcha faktlar ro'yxati."""
    facts = await db.get_all_facts()
    return web.json_response({"facts": facts})


async def api_delete_fact_handler(request: web.Request) -> web.Response:
    """Mini App: faktni o'chirish."""
    data = await request.json()
    key = data.get("key", "").strip()
    if not key:
        return web.json_response({"status": "error", "message": "Kalit ko'rsatilmadi"}, status=400)
    success = await db.delete_fact(key)
    return web.json_response({"status": "ok" if success else "error"})


async def api_reminders_handler(request: web.Request) -> web.Response:
    """Mini App: barcha faol eslatmalar ro'yxati."""
    reminders = await db.get_active_reminders()
    return web.json_response({"reminders": reminders})


async def api_add_reminder_handler(request: web.Request) -> web.Response:
    """Mini App: yangi eslatma qo'shish."""
    data = await request.json()
    text = data.get("text", "").strip()
    remind_at = data.get("remind_at", "").strip()
    if not text or not remind_at:
        return web.json_response({"status": "error", "message": "Matn yoki vaqt to'ldirilmadi"}, status=400)

    rem_id = await db.add_reminder(ADMIN_ID, text, remind_at)
    return web.json_response({"status": "ok", "id": rem_id})


async def api_delete_reminder_handler(request: web.Request) -> web.Response:
    """Mini App: eslatmani bekor qilish."""
    data = await request.json()
    rem_id = data.get("id")
    if not rem_id:
        return web.json_response({"status": "error", "message": "ID ko'rsatilmadi"}, status=400)
    success = await db.delete_reminder(int(rem_id))
    return web.json_response({"status": "ok" if success else "error"})


async def api_scheduled_posts_handler(request: web.Request) -> web.Response:
    """Mini App: kutilayotgan kanal postlari."""
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
        return web.json_response({"status": "error", "message": str(exc)}, status=500)


async def api_system_info_handler(request: web.Request) -> web.Response:
    """Mini App: tizim holati, uptime, userbot, ma'lumotlar bazasi."""
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

    return web.json_response({
        "uptime_human": f"{hours} soat, {minutes} daqiqa",
        "tashkent_time": tashkent_now,
        "userbot_connected": userbot_connected,
        "database_type": "Supabase + SQLite (Hybrid)" if db.use_supabase else "SQLite Local DB",
        "provider": ai_manager.current_provider,
        "model": ai_manager.current_or_model,
        "role": ai_manager.current_role,
    })


async def api_managed_chats_handler(request: web.Request) -> web.Response:
    """Mini App: boshqarilayotgan barcha guruhlar va kanallar."""
    chats = await db.get_managed_chats()
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
            img_bytes, enhanced, ar, seed = await draw_midjourney_image(raw_prompt, ai_manager)
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
        return web.json_response({"status": "error", "message": str(exc)}, status=500)


async def start_web_server(ai_manager: AIManager, bot: Optional[Bot] = None) -> web.AppRunner:
    """aiohttp web server va Mini App endpointlarini ishga tushiradi."""
    app = web.Application()
    app["ai_manager"] = ai_manager
    if bot:
        app["bot"] = bot

    # Ham root ("/"), ham "/webapp" Mini Appni ochadi (404 va adashishlarning oldini oladi)
    app.router.add_get("/", webapp_page_handler)
    app.router.add_get("/webapp", webapp_page_handler)
    app.router.add_get("/webapp/", webapp_page_handler)
    app.router.add_get("/landing", landing_page_handler)
    app.router.add_get("/landing/", landing_page_handler)
    app.router.add_get("/health", health_handler)
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

    port = int(os.getenv("PORT", "8080"))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=port)
    await site.start()
    logger.info("✅ Web App Server faol: http://0.0.0.0:%d/webapp", port)
    return runner


# ─── Asosiy Asinxron Funksiya ─────────────────────────────────

async def main() -> None:
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

    # 3. aiogram Bot va Dispatcher sozlash
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
    )
    dp = Dispatcher()

    # 4. Web App va Health Server ni ishga tushirish
    web_runner = await start_web_server(ai_manager, bot=bot)

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

            asyncio.create_task(_auto_sync_telegram_history())
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

    # AIManager ni data sifatida uzatish
    dp["ai_manager"] = ai_manager

    # Routerlarni ulash (tartib: menu, email, file, photo, voice, group, message)
    dp.include_router(menu_handler.router)
    dp.include_router(email_handler.router)
    dp.include_router(file_handler.router)
    dp.include_router(photo_handler.router)
    dp.include_router(voice_handler.router)    # Voice-to-Task
    dp.include_router(group_handler.router)    # Guruhlar, kanallar va my_chat_member
    dp.include_router(message_handler.router)  # Oxirida (catch-all)

    logger.info("✅ Barcha handlerlar ulandi (Guruhlar va Kanallar avtopiloti qo'shildi)")

    # 6. Smart Inbox Triage kuzatuvchisini faollashtirish
    if userbot_module.userbot and userbot_module.userbot.is_connected():
        await init_inbox_triage(userbot_module.userbot, bot, ai_manager)

    # 7. APScheduler kunlik hisobot va SMM avtopilot
    scheduler = setup_scheduler(bot, ai_manager)
    scheduler.start()
    logger.info("✅ Scheduler ishga tushdi (21:00 da hisobot, SMM avtopilot faol)")

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
                "✅ Guruh va Kanallar avtopiloti: faol\n\n"
                "Menyuni ochish uchun /start ni bosing."
            ),
            parse_mode="Markdown",
        )
    except Exception as exc:
        logger.warning("Adminga xabar yuborilmadi: %s", exc)

    # 9. Polling boshlash (Webhook to'qnashuvining oldini olish)
    try:
        await bot.delete_webhook(drop_pending_updates=False)
    except Exception as exc:
        logger.warning("delete_webhook xatosi: %s", exc)

    logger.info("🤖 Bot polling boshlandi...")
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
    finally:
        # To'xtatishda resurslarni tozalash
        scheduler.shutdown(wait=False)
        if userbot_module.userbot and userbot_module.userbot.is_connected():
            await userbot_module.userbot.disconnect()
        await web_runner.cleanup()
        await bot.session.close()
        logger.info("👋 Bot to'xtatildi. Resurslar tozalandi.")


# ─── Kirish Nuqtasi ───────────────────────────────────────────

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Foydalanuvchi tomonidan to'xtatildi (Ctrl+C)")
    except Exception as exc:
        logger.critical("💥 Kritik xato: %s", exc, exc_info=True)
        sys.exit(1)

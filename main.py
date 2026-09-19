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
from core.mistral_agent_bot import get_second_bot, second_bot_router
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
        return web.json_response({"status": "error", "message": str(exc)}, status=500)




async def api_tasks_get_handler(request: web.Request) -> web.Response:
    """Mini App: Notion / Todo vazifalar ro'yxati."""
    try:
        tasks = await db.get_tasks(ADMIN_ID)
        return web.json_response({"status": "ok", "tasks": tasks})
    except Exception as exc:
        logger.error("api_tasks_get xatosi: %s", exc)
        return web.json_response({"status": "error", "message": str(exc)}, status=500)


async def api_tasks_add_handler(request: web.Request) -> web.Response:
    """Mini App: Yangi vazifa qo'shish."""
    try:
        data = await request.json()
        title = data.get("title", "").strip()
        due_date = data.get("due_date", "")
        if not title:
            return web.json_response({"status": "error", "message": "Vazifa nomi bo'sh"}, status=400)
        task_id = await db.add_task(ADMIN_ID, title, due_date=due_date)
        return web.json_response({"status": "ok", "task_id": task_id})
    except Exception as exc:
        logger.error("api_tasks_add xatosi: %s", exc)
        return web.json_response({"status": "error", "message": str(exc)}, status=500)


async def api_tasks_toggle_handler(request: web.Request) -> web.Response:
    """Mini App: Vazifani bajarilgan deb belgilash yoki o'chirish."""
    try:
        data = await request.json()
        task_id = int(data.get("task_id", 0))
        action = data.get("action", "complete")
        if action == "complete":
            await db.complete_task(task_id)
        elif action == "delete":
            await db.delete_task(task_id)
        return web.json_response({"status": "ok"})
    except Exception as exc:
        logger.error("api_tasks_toggle xatosi: %s", exc)
        return web.json_response({"status": "error", "message": str(exc)}, status=500)


async def api_uptime_get_handler(request: web.Request) -> web.Response:
    """Mini App: Uptime monitor saytlar ro'yxati."""
    try:
        monitors = await db.get_uptime_monitors(ADMIN_ID)
        return web.json_response({"status": "ok", "monitors": monitors})
    except Exception as exc:
        logger.error("api_uptime_get xatosi: %s", exc)
        return web.json_response({"status": "error", "message": str(exc)}, status=500)


async def api_uptime_add_handler(request: web.Request) -> web.Response:
    """Mini App: Uptime monitorga yangi sayt qo'shish."""
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
        logger.error("api_uptime_add xatosi: %s", exc)
        return web.json_response({"status": "error", "message": str(exc)}, status=500)


async def api_uptime_delete_handler(request: web.Request) -> web.Response:
    """Mini App: Uptime monitorni o'chirish."""
    try:
        data = await request.json()
        mon_id = int(data.get("id", 0))
        await db.delete_uptime_monitor(mon_id)
        return web.json_response({"status": "ok"})
    except Exception as exc:
        logger.error("api_uptime_del xatosi: %s", exc)
        return web.json_response({"status": "error", "message": str(exc)}, status=500)


async def api_clean_server_handler(request: web.Request) -> web.Response:
    """Mini App: Serverni xavfsiz tozalash va disk holati."""
    try:
        from core.cleaner_agent import safe_clean_server_storage, get_system_storage_info
        res = await safe_clean_server_storage()
        storage = get_system_storage_info()
        return web.json_response({"status": "ok", "cleaned": res, "storage": storage})
    except Exception as exc:
        logger.error("api_clean_server xatosi: %s", exc)
        return web.json_response({"status": "error", "message": str(exc)}, status=500)


async def api_profile_handler(request: web.Request) -> web.Response:
    """Mini App: Mem0 shaxsiy profil faktlari."""
    try:
        facts = await db.get_all_facts()
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
        logger.error("api_profile xatosi: %s", exc)
        return web.json_response({"status": "error", "message": str(exc)}, status=500)


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
        logger.error("api_generate_image xatosi: %s", exc)
        return web.json_response({"status": "error", "message": str(exc)}, status=500)


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
        logger.error("api_download_video xatosi: %s", exc)
        return web.json_response({"status": "error", "message": str(exc)}, status=500)


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
        logger.error("api_agent_research xatosi: %s", exc)
        return web.json_response({"status": "error", "message": str(exc)}, status=500)


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
        logger.error("api_agent_code_review xatosi: %s", exc)
        return web.json_response({"status": "error", "message": str(exc)}, status=500)


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
        logger.error("api_agent_inspect_doc xatosi: %s", exc)
        return web.json_response({"status": "error", "message": str(exc)}, status=500)


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
        logger.error("api_agent_smm_creator xatosi: %s", exc)
        return web.json_response({"status": "error", "message": str(exc)}, status=500)


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
        logger.error("api_tts_voice xatosi: %s", exc)
        return web.json_response({"status": "error", "message": str(exc)}, status=500)


async def api_astrology_calculate_handler(request: web.Request) -> web.Response:
    """Mini App: Natal Karta hisoblash va saqlash API."""
    try:
        data = await request.json()
        birth_date = data.get("birth_date", "").strip()
        birth_time = data.get("birth_time", "12:00").strip()
        city = data.get("city", "Toshkent").strip()
        user_id = str(data.get("user_id", "default_user"))

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
        logger.error("api_astrology_calculate xatosi: %s", exc)
        return web.json_response({"status": "error", "message": str(exc)}, status=500)


async def api_astrology_profile_handler(request: web.Request) -> web.Response:
    """Mini App: Mavjud Astrologiya profilini olish."""
    try:
        user_id = request.query.get("user_id", "default_user")
        profile = await db.get_astrology_profile(user_id)
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
        return web.json_response({"status": "not_found", "message": "Profil mavjud emas"})
    except Exception as exc:
        logger.error("api_astrology_profile xatosi: %s", exc)
        return web.json_response({"status": "error", "message": str(exc)}, status=500)


async def api_astrology_interpret_handler(request: web.Request) -> web.Response:
    """Mini App: 20 yillik tajribali munajjim-olim (Grandmaster) darajasida voqeaviy prognoz generatsiya qilish."""
    try:
        ai_manager: AIManager = request.app["ai_manager"]
        data = await request.json()
        question = data.get("question", "").strip()
        user_id = str(data.get("user_id", "default_user"))
        selected_model = data.get("model", "")

        profile = await db.get_astrology_profile(user_id)
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
            report = await ai_manager.generate(prompt, save_history=False, chat_id=f"astro_{user_id}")
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
        logger.error("api_astrology_interpret xatosi: %s", exc)
        return web.json_response({"status": "error", "message": str(exc)}, status=500)


async def api_astrology_lots_handler(request: web.Request) -> web.Response:
    """Mini App: 513 tagacha bo'lgan Arab Lotlarini qabul qilish va profilga saqlash."""
    try:
        data = await request.json()
        user_id = str(data.get("user_id", "default_user"))
        raw_lots = data.get("lots_data", "")

        from core.astrology_agent import parse_custom_arabic_lots
        parsed = parse_custom_arabic_lots(raw_lots)
        if not parsed:
            return web.json_response({"status": "error", "message": "Lotlar ma'lumotlarini o'qib bo'lmadi"}, status=400)

        await db.save_custom_lots(user_id, parsed)
        return web.json_response({
            "status": "ok",
            "count": len(parsed),
            "lots": parsed,
            "message": f"Muvaffaqiyatli! {len(parsed)} ta Arab Loti xotiraga saqlandi va AI tahliliga ulandi."
        })
    except Exception as exc:
        logger.error("api_astrology_lots xatosi: %s", exc)
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

    # 2-Bot (Mistral Arxitektor Agent Bot @architect7_bot)
    second_bot = get_second_bot()
    if second_bot:
        dp.include_router(second_bot_router)
        logger.info("✅ 2-Bot: Mistral Arxitektor Agent Bot (@architect7_bot) routeri ulandi")

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
    bots_to_poll = [bot]
    if second_bot:
        try:
            await second_bot.delete_webhook(drop_pending_updates=False)
            bots_to_poll.append(second_bot)
            logger.info("✅ 2-Bot (@architect7_bot) polling ro'yxatiga qo'shildi")
        except Exception as e:
            logger.warning("2-Bot delete_webhook xatosi: %s", e)

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
                    *bots_to_poll,
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
        # To'xtatishda barcha resurslarni xavfsiz tozalash
        if scheduler:
            try:
                scheduler.shutdown(wait=False)
            except Exception as sch_err:
                logger.debug("Scheduler to'xtatishda xatolik: %s", sch_err)
        if userbot_module.userbot and userbot_module.userbot.is_connected():
            try:
                await userbot_module.userbot.disconnect()
            except Exception as ub_err:
                logger.debug("Userbot uzishda xatolik: %s", ub_err)
        if web_runner:
            try:
                await web_runner.cleanup()
            except Exception as wr_err:
                logger.debug("Web runner tozalashda xatolik: %s", wr_err)
        try:
            await bot.session.close()
        except Exception as bot_err:
            logger.debug("Bot sessiyasini yopishda xatolik: %s", bot_err)
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

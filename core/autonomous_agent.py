"""
core/autonomous_agent.py — Avtonom Vazifalarni Bajaruvchi Agent (Autonomous Task Executor)

4 ta Ilg'or Skill:
1. 📢 Kanalga avtonom post chiqarish (Mavzudan AI matn + ixtiyoriy FLUX.1 rasm generatsiyasi)
2. 👥 Guruhga avtonom xabar / anons yuborish (Guruh nomi yoki @username bo'yicha)
3. 🤖 Boshqa bot bilan muloqot (Inter-Bot Communication via Telethon Userbot)
4. ⏰ Rejalashtirilgan va muntazam postlar (Autonomous Scheduler integratsiyasi)
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Optional, TYPE_CHECKING

from aiogram import Bot
from aiogram.types import Message, BufferedInputFile, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import ADMIN_ID, LOG_CHANNEL_ID
from core.database import db
from core.userbot import (
    post_to_channel_or_chat,
    post_to_group_or_channel_smart,
    interact_with_bot_and_wait_reply,
    userbot as telethon_userbot,
)
from core.safe_send import safe_send_message, safe_message_answer, safe_edit_text
from services.scheduler import LogCollector

if TYPE_CHECKING:
    from core.ai_manager import AIManager

logger = logging.getLogger(__name__)

try:
    import zoneinfo
    TASHKENT_TZ = zoneinfo.ZoneInfo("Asia/Tashkent")
except Exception:
    TASHKENT_TZ = None


def get_current_tashkent_time() -> datetime:
    """Toshkent joriy vaqti."""
    if TASHKENT_TZ:
        return datetime.now(TASHKENT_TZ)
    return datetime.now()


# ─── 1. BUYRUQ VA INTENTLARNI ANIQLASH (INTENT DETECTOR) ───────

async def detect_autonomous_intent(text: str, ai_manager: "AIManager") -> Optional[dict]:
    """
    Foydalanuvchi matnidan 4 ta avtonom skilldan birini aniqlaydi:
    - 'channel_post'
    - 'group_announce'
    - 'bot_interact'
    - 'schedule_post'
    """
    clean_text = text.strip()
    lower_text = clean_text.lower()

    # 1. Boshqa bot bilan muloqot (Inter-Bot Communication)
    # Masalan: "@vkmusic_bot ga /start deb yoz", "@midjourney_bot ga /imagine cat", "botga: @bot ..."
    bot_match = re.search(r"(@[a-zA-Z0-9_]+bot)\s*(?:ga\s+)?(?:deb\s+)?(?:yoz|yubor|so'ra|qidir|ayt|ishlat|buyruq\s+ber)?[:\s]*(.+)", clean_text, re.IGNORECASE | re.DOTALL)
    if not bot_match and lower_text.startswith(("botga:", "bot:", "interact:", "/bot")):
        parts = clean_text.split(maxsplit=2)
        if len(parts) >= 3 and "bot" in parts[1].lower():
            return {
                "intent": "bot_interact",
                "target": parts[1].strip(),
                "prompt": parts[2].strip(),
            }

    if bot_match:
        target_bot = bot_match.group(1).strip()
        command = bot_match.group(2).strip()
        # Tozalash: agar oxirida "deb yoz" bo'lsa
        command = re.sub(r"\s+deb\s+(?:yoz|yubor|so'ra)$", "", command, flags=re.IGNORECASE).strip()
        if command:
            return {
                "intent": "bot_interact",
                "target": target_bot,
                "prompt": command,
            }

    # 2. Rejalashtirilgan post (Autonomous Scheduler)
    # Masalan: "ertaga soat 10:00 da kanalga post chiqar", "21:30 da @kanalim ga post rejalashtir"
    has_time_word = bool(re.search(r"(?:soat\s*)?\b\d{1,2}:\d{2}\b|ertaga|indin|har\s+kuni|\d+\s*(?:daqiqa|minut|soat)dan\s*keyin", lower_text))
    has_post_word = any(w in lower_text for w in ["post", "kanalga", "guruhga", "e'lon", "anons"])
    is_schedule_intent = has_time_word and has_post_word and any(w in lower_text for w in ["rejalashtir", "chiqar", "tashla", "joyla", "yoz", "e'lon qil"])

    if is_schedule_intent or lower_text.startswith(("/schedule_post", "rejalashtirilgan post:")):
        return await _parse_schedule_task_ai(clean_text, ai_manager)

    # 3. Kanalga avtonom post chiqarish
    # Masalan: "@kanal ga AI haqida post chiqar", "kanalimga motivatsiya haqida post joyla va rasm ham chiz"
    is_channel_post = (
        ("kanalga" in lower_text or "kanalimga" in lower_text or "kanal" in lower_text)
        and any(w in lower_text for w in ["post", "maqola", "chiqar", "tayyorla", "joyla", "e'lon"])
    ) or lower_text.startswith(("/autopost", "post chiqar:", "kanalga post:"))

    if is_channel_post:
        return await _parse_channel_task_ai(clean_text, ai_manager)

    # 4. Guruhga avtonom xabar / anons yuborish
    # Masalan: "@dasturchilar guruhiga meetup haqida anons ber", "IT Guruh ga yangi video haqida xabar yubor"
    is_group_announce = (
        ("guruhga" in lower_text or "guruhimga" in lower_text or "chatga" in lower_text)
        and any(w in lower_text for w in ["anons", "xabar", "e'lon", "yubor", "yoz", "chiqar"])
    ) or lower_text.startswith(("/group_post", "guruhga anons:", "guruhga xabar:"))

    if is_group_announce:
        return await _parse_group_task_ai(clean_text, ai_manager)

    return None


# ─── AI Yordamida Aniq Parametrlarni Ajratish ─────────────────

async def _parse_channel_task_ai(text: str, ai_manager: "AIManager") -> dict:
    """Kanalga post parametrlari: target, topic, with_image."""
    # Tezkor tekshiruv: @username bormi?
    target_match = re.search(r"(@[a-zA-Z0-9_]+|-100\d+)", text)
    target = target_match.group(1) if target_match else ""
    with_image = any(w in text.lower() for w in ["rasm", "rasmli", "photo", "image", "chiz", "illustratsiya", "banner"])

    prompt = (
        f"Foydalanuvchi Telegram kanaliga post chiqarishni buyurdi:\n\"{text}\"\n\n"
        f"Vazifa: JSON formatida ajratib ber:\n"
        f"1. 'target': kanal username yoki ID (agar aniq aytilmagan bo'lsa bo'sh qoldir: '')\n"
        f"2. 'topic': post mavzusi yoki tayyor matni\n"
        f"3. 'with_image': rasm chizish kerakmi (true yoki false)\n\n"
        f"Format: {{\"target\": \"@kanal yoki ''\", \"topic\": \"mavzu\", \"with_image\": true}}\n"
        f"Faqat sof JSON qaytar."
    )
    try:
        res = await ai_manager.generate(prompt, save_history=False)
        json_match = re.search(r"\{.*\}", res, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group(0))
            return {
                "intent": "channel_post",
                "target": data.get("target") or target,
                "topic": data.get("topic") or text,
                "with_image": data.get("with_image", with_image),
            }
    except Exception as exc:
        logger.debug("parse_channel_task_ai xatosi: %s", exc)

    return {
        "intent": "channel_post",
        "target": target,
        "topic": text,
        "with_image": with_image,
    }


async def _parse_group_task_ai(text: str, ai_manager: "AIManager") -> dict:
    """Guruh anonsi parametrlari: target, message/topic."""
    target_match = re.search(r"(@[a-zA-Z0-9_]+|-100\d+)", text)
    target = target_match.group(1) if target_match else ""

    prompt = (
        f"Foydalanuvchi Telegram guruhiga xabar/anons yuborishni buyurdi:\n\"{text}\"\n\n"
        f"Vazifa: JSON formatida ajratib ber:\n"
        f"1. 'target': guruh nomi yoki @username yoki ID (masalan: 'Dasturchilar' yoki '@dasturchilar')\n"
        f"2. 'topic': yuborilishi kerak bo'lgan xabar yoki anons mavzusi\n\n"
        f"Format: {{\"target\": \"guruh nomi yoki username\", \"topic\": \"anons matni yoki mavzusi\"}}\n"
        f"Faqat sof JSON qaytar."
    )
    try:
        res = await ai_manager.generate(prompt, save_history=False)
        json_match = re.search(r"\{.*\}", res, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group(0))
            return {
                "intent": "group_announce",
                "target": data.get("target") or target,
                "topic": data.get("topic") or text,
            }
    except Exception as exc:
        logger.debug("parse_group_task_ai xatosi: %s", exc)

    return {
        "intent": "group_announce",
        "target": target,
        "topic": text,
    }


async def _parse_schedule_task_ai(text: str, ai_manager: "AIManager") -> dict:
    """Rejalashtirilgan post parametrlari: target, time, topic."""
    now = get_current_tashkent_time()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")

    target_match = re.search(r"(@[a-zA-Z0-9_]+|-100\d+)", text)
    target = target_match.group(1) if target_match else ""

    prompt = (
        f"Hozirgi sana va vaqt (Toshkent): {now_str}.\n"
        f"Foydalanuvchi rejalashtirilgan post buyrug'ini berdi:\n\"{text}\"\n\n"
        f"Vazifa: JSON formatida ajratib ber:\n"
        f"1. 'target': kanal/guruh manzili (@username, ID yoki bo'sh '')\n"
        f"2. 'time': e'lon qilinish vaqti (YYYY-MM-DD HH:MM:00 formatida)\n"
        f"3. 'topic': post mavzusi yoki to'liq matni\n\n"
        f"Format: {{\"target\": \"@kanal\", \"time\": \"YYYY-MM-DD HH:MM:00\", \"topic\": \"mavzu\"}}\n"
        f"Faqat sof JSON qaytar."
    )
    try:
        res = await ai_manager.generate(prompt, save_history=False)
        json_match = re.search(r"\{.*\}", res, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group(0))
            return {
                "intent": "schedule_post",
                "target": data.get("target") or target,
                "scheduled_time": data.get("time"),
                "topic": data.get("topic") or text,
            }
    except Exception as exc:
        logger.debug("parse_schedule_task_ai xatosi: %s", exc)

    return {
        "intent": "schedule_post",
        "target": target,
        "scheduled_time": None,
        "topic": text,
    }


# ─── 2. AVTONOM IJRO ETUVCHILAR (EXECUTORS) ───────────────────

# ── Skill 1: Kanalga Avtonom Post Chiqarish ──
async def execute_channel_post(
    message: Message,
    target: str,
    topic: str,
    with_image: bool,
    ai_manager: "AIManager",
) -> None:
    """Kanalga avtonom post tayyorlab chiqaradi (matn + rasm)."""
    bot: Bot = message.bot
    status_msg = await message.answer("✍️ **AI orqali kanal uchun professional post tayyorlanmoqda...**", parse_mode="Markdown")

    # Kanal manzilini aniqlash
    final_target = target.strip()
    if not final_target:
        primary = await db.get_primary_channel()
        if primary:
            final_target = primary["chat_id"]
        elif LOG_CHANNEL_ID:
            final_target = str(LOG_CHANNEL_ID)
        else:
            await status_msg.edit_text(
                "❌ **Qaysi kanalga post chiqarish ko'rsatilmadi.**\n"
                "💡 Masalan: `@kanalim ga AI yangiliklari haqida post chiqar`",
                parse_mode="Markdown",
            )
            return

    # Post matnini AI orqali professional yaratish
    post_prompt = (
        f"Sen professional SMM mutaxassisi va Telegram kanallar muharririsan.\n"
        f"Mavzu: {topic}\n\n"
        f"Talablar:\n"
        f"1. O'quvchini darhol jalb qiluvchi sarlavha (emojilar bilan).\n"
        f"2. Qiziqarli, o'qilishi oson va foydali asosiy qism.\n"
        f"3. Xulosa yoki o'quvchilarga savol (Call To Action).\n"
        f"4. Tegishli hashtaglar (#ai #yangiliklar ...).\n"
        f"5. O'zbek tilida, professional va chiroyli Telegram Markdown formatida yoz.\n"
        f"Faqat post matnini ber, ortiqcha izohsiz."
    )
    post_text = await ai_manager.generate(post_prompt, save_history=False)

    image_bytes = None
    if with_image:
        await status_msg.edit_text("🎨 **FLUX.1 orqali post uchun mualliflik rasmi chizilmoqda...**", parse_mode="Markdown")
        try:
            from core.midjourney_agent import generate_free_midjourney_image
            image_bytes = await generate_free_midjourney_image(prompt=topic, aspect_ratio="16:9")
        except Exception as img_exc:
            logger.warning("Rasm chizishda xatolik: %s", img_exc)

    await status_msg.edit_text(f"📡 `{final_target}` kanaliga post e'lon qilinmoqda...", parse_mode="Markdown")

    published = False
    send_error = ""

    # Agar rasm bo'lsa, avval rasm bilan chiqarishga urinish
    if image_bytes and bot:
        try:
            caption = post_text[:1020]
            photo_file = BufferedInputFile(image_bytes, filename="post.jpg")
            await bot.send_photo(chat_id=final_target, photo=photo_file, caption=caption, parse_mode="Markdown")
            published = True
        except Exception as exc:
            logger.warning("Bot orqali rasm yuborishda xato: %s. Telethon orqali urinilmoqda...", exc)
            if telethon_userbot and telethon_userbot.is_connected():
                try:
                    await telethon_userbot.send_file(final_target, image_bytes, caption=post_text[:1020])
                    published = True
                except Exception as tb_exc:
                    send_error = str(tb_exc)

    # Agar rasm bo'lmasa yoki rasm yuborish o'xshamasa — matnli post
    if not published:
        res = await post_to_channel_or_chat(bot, final_target, post_text)
        if res.startswith("✅"):
            published = True
        else:
            send_error = res

    if published:
        img_status = "Ha (FLUX.1)" if image_bytes else "Yo'q (Matnli)"
        report_text = (
            f"🎉 **Kanalga Avtonom Post Muvaffaqiyatli E'lon Qilindi!**\n\n"
            f"🎯 **Kanal:** `{final_target}`\n"
            f"🖼 **Rasm:** {img_status}\n\n"
            f"📝 **Chiqarilgan Post Ko'rinishi:**\n"
            f"{'─' * 30}\n"
            f"{post_text[:600]}...\n"
            f"{'─' * 30}\n"
            f"✅ Barcha vazifalar to'liq bajarildi."
        )
        await status_msg.edit_text(report_text, parse_mode="Markdown")
        LogCollector().add(action_type="post", description=f"Autonomous post to {final_target}", model_used="autonomous_agent")
    else:
        await status_msg.edit_text(
            f"⚠️ **Kanalga post chiqarishda xatolik yuz berdi:**\n\n"
            f"`{send_error}`\n\n"
            f"💡 **Tavsiya:** Bot kanalingizda **Admin** ekanligiga va xabar yozish ruxsatiga ega ekaniga ishonch hosil qiling.",
            parse_mode="Markdown",
        )


# ── Skill 2: Guruhga Avtonom Anons / Xabar Yuborish ──
async def execute_group_announce(
    message: Message,
    target: str,
    topic: str,
    ai_manager: "AIManager",
) -> None:
    """Guruhga avtonom chiroyli anons yoki xabar chiqaradi."""
    status_msg = await message.answer("👥 **Guruh uchun rasmiy anons matni tayyorlanmoqda...**", parse_mode="Markdown")

    final_target = target.strip()
    if not final_target:
        await status_msg.edit_text(
            "❌ **Qaysi guruhga yuborish ko'rsatilmadi.**\n"
            "💡 Masalan: `@dasturchilar guruhiga yangi loyiha haqida anons ber`",
            parse_mode="Markdown",
        )
        return

    # Anons matnini AI orqali tayyorlash
    announce_prompt = (
        f"Guruh a'zolari uchun qisqa, diqqatni tortuvchi va samimiy Telegram anons/xabar yoz.\n"
        f"Mavzu yoki mazmun: {topic}\n\n"
        f"Talablar:\n"
        f"- Emojilar bilan boyitilgan\n"
        f"- Guruh auditoriyasiga mos va tushunarli\n"
        f"- O'zbek tilida, qisqa va lo'nda\n"
        f"Faqat e'lon matnini chiqar."
    )
    announce_text = await ai_manager.generate(announce_prompt, save_history=False)

    await status_msg.edit_text(f"📡 `{final_target}` guruhiga anons yetkazilmoqda...", parse_mode="Markdown")

    # Smart Sender orqali guruhga yetkazish (Telethon yoki aiogram)
    result = await post_to_group_or_channel_smart(final_target, announce_text)

    if result.startswith("✅"):
        await status_msg.edit_text(
            f"📣 **Guruhga Anons Muvaffaqiyatli Yetkazildi!**\n\n"
            f"👥 **Guruh:** `{final_target}`\n\n"
            f"📝 **Anons Matni:**\n"
            f"{'─' * 30}\n"
            f"{announce_text}\n"
            f"{'─' * 30}",
            parse_mode="Markdown",
        )
        LogCollector().add(action_type="group_send", description=f"Anons to {final_target}", model_used="autonomous_agent")
    else:
        await status_msg.edit_text(
            f"⚠️ **Guruhga yuborishda muammo yuz berdi:**\n\n{result}",
            parse_mode="Markdown",
        )


# ── Skill 3: Boshqa Bot Bilan Muloqot (Inter-Bot Communication) ──
async def execute_bot_interact(
    message: Message,
    bot_target: str,
    prompt: str,
) -> None:
    """Telethon Userbot orqali boshqa botga xabar yuborib, uning javobini oladi."""
    clean_bot = bot_target.strip().lstrip("@")
    status_msg = await message.answer(
        f"📡 **`@{clean_bot}` botiga so'rov yuborilmoqda...**\n"
        f"💬 Buyruq: `{prompt}`\n\n"
        f"⏳ *Botning javobi kutilmoqda (Telethon Userbot orqali)...*",
        parse_mode="Markdown",
    )

    success, reply_summary, reply_id = await interact_with_bot_and_wait_reply(
        bot_target=f"@{clean_bot}",
        prompt_or_command=prompt,
        timeout_sec=20,
        forward_to_chat_id=message.chat.id,
    )

    if success:
        report = (
            f"🤖 **Inter-Bot Muloqoti Yakunlandi!**\n\n"
            f"🎯 **Bot:** `@{clean_bot}`\n"
            f"💬 **Yuborilgan so'rov:** `{prompt}`\n\n"
            f"{reply_summary}"
        )
        await status_msg.edit_text(report[:4000], parse_mode="Markdown")
        LogCollector().add(action_type="userbot", description=f"Inter-bot @{clean_bot}: {prompt[:30]}", model_used="telethon_interbot")
    else:
        await status_msg.edit_text(
            f"⚠️ **Inter-Bot Natijasi:**\n\n{reply_summary}",
            parse_mode="Markdown",
        )


# ── Skill 4: Rejalashtirilgan Post (Autonomous Scheduler) ──
async def execute_schedule_post(
    message: Message,
    target: str,
    scheduled_time: Optional[str],
    topic: str,
    ai_manager: "AIManager",
) -> None:
    """Belgilangan vaqtga postni avtonom rejalashtiradi."""
    status_msg = await message.answer("⏰ **Post matni tayyorlanib, rejalashtiruv tizimiga kiritilmoqda...**", parse_mode="Markdown")

    final_target = target.strip()
    if not final_target:
        primary = await db.get_primary_channel()
        if primary:
            final_target = primary["chat_id"]
        elif LOG_CHANNEL_ID:
            final_target = str(LOG_CHANNEL_ID)
        else:
            final_target = "default"

    # Vaqtni aniqlash
    if not scheduled_time:
        # Default: 1 soatdan keyin
        t_time = get_current_tashkent_time() + timedelta(hours=1)
        scheduled_time = t_time.strftime("%Y-%m-%d %H:%M:00")

    # Post matnini AI orqali tayyorlash
    post_prompt = (
        f"Telegram kanali uchun chiroyli, emojilarga boy va qiziqarli post yoz.\n"
        f"Mavzu: {topic}\n"
        f"O'zbek tilida, Telegram Markdown formatida bo'lsin. Faqat post matnini ber."
    )
    post_text = await ai_manager.generate(post_prompt, save_history=False)

    post_id = await db.add_scheduled_post(
        chat_id=final_target,
        text=post_text,
        scheduled_time=scheduled_time,
    )

    if post_id > 0:
        await status_msg.edit_text(
            f"⏰ **Post Muvaffaqiyatli Rejalashtirildi!**\n\n"
            f"📌 **Manzil:** `{final_target}`\n"
            f"🕒 **E'lon qilinish vaqti:** `{scheduled_time}` (Toshkent vaqti)\n"
            f"🆔 **Post ID:** `#{post_id}`\n\n"
            f"📝 **Tayyorlangan Post:**\n"
            f"{'─' * 30}\n"
            f"{post_text[:500]}...\n"
            f"{'─' * 30}\n\n"
            f"🤖 *Vaqti kelishi bilan avtonom tarzda kanalga chiqariladi!*",
            parse_mode="Markdown",
        )
        LogCollector().add(action_type="schedule_post", description=f"Post #{post_id} at {scheduled_time}", model_used="autonomous_scheduler")
    else:
        await status_msg.edit_text("❌ Postni rejalashtirishda ma'lumotlar bazasida xatolik yuz berdi.", parse_mode="Markdown")


# ─── 3. ASOSIY ENTRYPOINT (TRY_EXECUTE_AUTONOMOUS_TASK) ───────

async def try_execute_autonomous_task(
    message: Message,
    user_text: str,
    ai_manager: "AIManager",
) -> bool:
    """
    Xabar kelganda uni 4 ta avtonom topshiriqdan biriga mos kelishini tekshiradi.
    Agar mos kelsa, avtonom bajarib True qaytaradi. Mos kelmasa False.
    """
    # Maxsus holatlarni chetlab o'tish (URL video yuklash, media fayllar, oddiy salomlar)
    if re.match(r"^https?://", user_text) or len(user_text.strip()) < 4:
        return False

    intent_data = await detect_autonomous_intent(user_text, ai_manager)
    if not intent_data:
        return False

    intent = intent_data.get("intent")
    logger.info("Avtonom Intent aniqlandi: %s | Ma'lumot: %s", intent, intent_data)

    if intent == "bot_interact":
        await execute_bot_interact(
            message=message,
            bot_target=intent_data.get("target", ""),
            prompt=intent_data.get("prompt", ""),
        )
        return True

    elif intent == "channel_post":
        await execute_channel_post(
            message=message,
            target=intent_data.get("target", ""),
            topic=intent_data.get("topic", user_text),
            with_image=intent_data.get("with_image", False),
            ai_manager=ai_manager,
        )
        return True

    elif intent == "group_announce":
        await execute_group_announce(
            message=message,
            target=intent_data.get("target", ""),
            topic=intent_data.get("topic", user_text),
            ai_manager=ai_manager,
        )
        return True

    elif intent == "schedule_post":
        await execute_schedule_post(
            message=message,
            target=intent_data.get("target", ""),
            scheduled_time=intent_data.get("scheduled_time"),
            topic=intent_data.get("topic", user_text),
            ai_manager=ai_manager,
        )
        return True

    return False

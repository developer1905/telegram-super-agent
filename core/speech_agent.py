"""
core/speech_agent.py — Ovozli Xabarlarni Eshitish (STT) va Ovozli Muloqot Agenti

Imkoniyatlar:
1. Telegram ovozli xabarlarini (.ogg/.opus) tinglab, 100% aniq matnga aylantirish (Speech-to-Text).
2. O'zbek, Rus va Ingliz tillaridagi nutqni bexato tushunish.
3. Foydalanuvchining ovozli xabaridagi niyatni (intent) aniqlash:
   - Vazifalar ("Notionga vazifa qo'sh: ...")
   - Eslatmalar ("21:00 da eslat ...")
   - Real Madrid o'yinlari va sport yangiliklari ("Real Madrid bugun o'ynaydimi?")
   - Midjourney rasm chizish ("Rasm chiz: ...")
   - Internetdan qidirish ("Qidir: ...")
   - Erkin AI suhbat
4. Javobni tabiiy ovoz bilan (Microsoft Edge Neural TTS: Madina / Sardor) ovozli xabar ko'rinishida qaytarish.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import re
from typing import Optional, Dict, Any, TYPE_CHECKING

from aiogram import Bot
from aiogram.enums import ChatAction
from aiogram.types import Message, BufferedInputFile

from config import ADMIN_ID, ENABLE_VOICE_REPLIES, DEFAULT_VOICE
from core.database import db

if TYPE_CHECKING:
    from core.ai_manager import AIManager

logger = logging.getLogger(__name__)


async def transcribe_audio_bytes(
    audio_bytes: bytes,
    mime_type: str = "audio/ogg",
    ai_manager: Optional["AIManager"] = None,
) -> str:
    """
    Audio baytlarini matnga (Transkripsiyaga) aylantiradi.
    Gemini 2.5/3.1 Flash audio imkoniyatidan foydalanadi.
    """
    if not audio_bytes:
        return ""

    if ai_manager and hasattr(ai_manager, "_gemini_client") and ai_manager._gemini_client:
        from google.genai import types as genai_types
        from config import GEMINI_MODEL, GEMINI_FALLBACK_MODELS

        instruction = (
            "You are an expert audio transcriber. Listen carefully to this audio recording "
            "and output the EXACT speech as text in the original language (Uzbek, Russian, or English). "
            "Do NOT add preamble, markdown commentary, or explanations. Return ONLY the transcribed text."
        )

        models = [GEMINI_MODEL] + list(GEMINI_FALLBACK_MODELS)
        for m in models:
            try:
                part = genai_types.Part.from_bytes(data=audio_bytes, mime_type=mime_type)
                resp = await asyncio.to_thread(
                    ai_manager._gemini_client.models.generate_content,
                    model=m,
                    contents=[part, instruction],
                )
                if resp and resp.text:
                    cleaned = resp.text.strip().strip('"\'`')
                    if cleaned:
                        return cleaned
            except Exception as exc:
                logger.debug("Gemini STT urinishi (%s) xatosi: %s", m, exc)
                continue

    return ""


async def process_voice_agent_message(
    message: Message,
    bot: Bot,
    ai_manager: "AIManager",
) -> None:
    """
    Ovozli xabarni qabul qilib, uni to'liq mustaqil agent darajasida bajaradi.
    """
    from core.safe_send import safe_edit_text, safe_send_message
    from core.tts_agent import generate_speech_audio

    # Chat action
    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.RECORD_VOICE)

    status_msg = await message.reply("🎧 Ovozli xabaringiz tinglanmoqda va tahlil qilinmoqda...")

    try:
        file_id = message.voice.file_id if message.voice else message.audio.file_id
        mime_type = message.voice.mime_type if message.voice else (message.audio.mime_type or "audio/ogg")

        # 1. Telegramdan yuklab olish
        file_io = io.BytesIO()
        await bot.download(file_id, destination=file_io)
        audio_bytes = file_io.getvalue()

        if not audio_bytes:
            await safe_edit_text(status_msg, "❌ Ovozli faylni yuklab olishda xatolik yuz berdi.", parse_mode=None)
            return

        # 2. Audio Transkripsiyasi
        transcription = await transcribe_audio_bytes(audio_bytes, mime_type=mime_type, ai_manager=ai_manager)

        # 3. Agar to'g'ridan-to'g'ri multimodal javob olsak
        if not transcription:
            # Multimodal fallback
            instruction = (
                "Foydalanuvchining ovozli xabarini diqqat bilan eshitib, unga Super-Agent sifatida to'liq, "
                "ravon va professional tarzda o'zbek tilida javob bering. "
                "Birinchi qatorda eshitilgan matnni: '🎙 Transkripsiya: <matn>' shaklida keltiring."
            )
            ai_ans = await ai_manager.generate_with_audio(audio_bytes, mime_type, custom_instruction=instruction)
            await safe_edit_text(status_msg, ai_ans, parse_mode="Markdown")

            # Ovozli javob
            if ENABLE_VOICE_REPLIES:
                voice_bytes = await generate_speech_audio(ai_ans[:800])
                if voice_bytes:
                    v_file = BufferedInputFile(file=voice_bytes, filename="reply.mp3")
                    await message.reply_voice(voice=v_file, caption="🎙 **Ovozli AI Javobi**")
            return

        # 4. Foydalanuvchi aytgan aniq matn bor! Uni log qilish va ko'rsatish
        await safe_edit_text(
            status_msg,
            f"🎙 **Siz aytdingiz:**\n_{transcription}_\n\n⏳ Agent vazifani bajarmoqda...",
            parse_mode="Markdown"
        )

        user_text = transcription.strip()

        # 4.1 Notion / Todo Vazifa buyrug'i
        from core.todo_notion_agent import parse_and_create_todo_from_text
        if any(w in user_text.lower() for w in ["vazifa", "todo", "reja", "qiladigan ish", "rejam"]):
            todo_res = await parse_and_create_todo_from_text(user_text, ai_manager, user_id=ADMIN_ID)
            if todo_res:
                await safe_edit_text(status_msg, todo_res, parse_mode="Markdown")
                v_bytes = await generate_speech_audio("Vazifangiz rejalashtirildi va saqlandi!")
                if v_bytes:
                    await message.reply_voice(voice=BufferedInputFile(file=v_bytes, filename="todo.mp3"))
                return

        # 4.2 Eslatma buyrug'i
        if any(w in user_text.lower() for w in ["eslat", "remind", "eslatma", "eslatgin"]):
            from core.reminder_manager import parse_reminder_smart
            rem_res = await parse_reminder_smart(user_text, ai_manager)
            if rem_res:
                rem_time, rem_task = rem_res
                rem_id = await db.add_reminder(ADMIN_ID, rem_task, rem_time)
                rem_ans = (
                    f"⏰ **Ovozli buyruq bo'yicha eslatma saqlandi!**\n\n"
                    f"📝 **Vazifa:** {rem_task}\n"
                    f"🕒 **Vaqt:** `{rem_time}` (Toshkent)\n"
                    f"ID: `#{rem_id}`"
                )
                await safe_edit_text(status_msg, rem_ans, parse_mode="Markdown")
                v_bytes = await generate_speech_audio(f"Eslatma {rem_time} ga belgilandi.")
                if v_bytes:
                    await message.reply_voice(voice=BufferedInputFile(file=v_bytes, filename="rem.mp3"))
                return


        # 4.4 Midjourney rasm chizish
        if any(w in user_text.lower() for w in ["rasm chiz", "chizib ber", "chiz", "imagine"]):
            raw_prompt = re.sub(r"^(?:rasm\s+chiz|chizib\s+ber|chiz|imagine)[:\s]+", "", user_text, flags=re.IGNORECASE).strip()
            from core.midjourney_agent import draw_midjourney_image
            await safe_edit_text(status_msg, f"🎨 **Midjourney v6 rasm chizmoqda:**\n_{raw_prompt}_", parse_mode="Markdown")
            img_bytes, enhanced, ar, seed = await draw_midjourney_image(raw_prompt, ai_manager)
            if img_bytes:
                photo_file = BufferedInputFile(file=img_bytes, filename="art.jpg")
                caption = f"🎨 **Midjourney v6:**\n📝 _{enhanced}_\n📐 O'lcham: `{ar}` | 🎲 Seed: `{seed}`"
                await message.reply_photo(photo=photo_file, caption=caption, parse_mode="Markdown")
                await status_msg.delete()
                return

        # 4.5 Qidiruv yoki Erkin AI Suhbat
        if any(w in user_text.lower() for w in ["qidir", "internetdan qidir", "google"]):
            from core.search_agent import answer_with_web_search
            q = re.sub(r"^(?:qidir|internetdan\s+qidir|google)[:\s]+", "", user_text, flags=re.IGNORECASE).strip()
            ans = await answer_with_web_search(q, ai_manager)
        else:
            ans = await ai_manager.generate(user_text)

        full_reply = (
            f"🎙 **Eshitildi:** _{transcription}_\n\n"
            f"💡 **AI Javobi:**\n{ans}"
        )
        await safe_edit_text(status_msg, full_reply, parse_mode="Markdown")

        # Tabiiy ovozda javob qaytarish
        if ENABLE_VOICE_REPLIES:
            speech_chunk = ans
            if len(speech_chunk) > 600:
                speech_chunk = speech_chunk[:600].rsplit(".", 1)[0] + "."
            v_bytes = await generate_speech_audio(speech_chunk)
            if v_bytes:
                await message.reply_voice(
                    voice=BufferedInputFile(file=v_bytes, filename="reply.mp3"),
                    caption="🎙 **Ovozli Javob**"
                )

    except Exception as exc:
        logger.error("process_voice_agent_message xatosi: %s", exc)
        await safe_edit_text(status_msg, f"❌ Ovozli xabarni qayta ishlashda xatolik: {exc}", parse_mode=None)

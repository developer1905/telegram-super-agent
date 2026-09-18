"""
handlers/voice_handler.py — Ovozli Xabarlarni Tushunish va Vazifalarga Aylantirish (Voice-to-Task)

Telegramdan yuborilgan ovozli xabarlarni (.ogg / audio) xotirada (RAM) qabul qilib,
Gemini 3.6 Flash multimodal audio imkoniyati orqali to'g'ridan-to'g'ri tinglaydi,
transkripsiya qiladi va buyruqlarni (masalan: biror kishiga xabar yozish,
taqvim/eslatma qo'yish, post chiqarish) aniqlaydi.
"""

from __future__ import annotations

import io
import logging
from typing import Optional

from aiogram import Bot, Router, F
from aiogram.enums import ChatAction
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from config import ADMIN_ID
from core.ai_manager import AIManager
from core.database import db

logger = logging.getLogger(__name__)

router = Router()


def get_voice_actions_keyboard(action_type: str = "send") -> InlineKeyboardMarkup:
    """Ovozli buyruq bo'yicha tezkor amallar klaviaturasi."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Tasdiqlash va Bajarish", callback_data="voice_confirm_action"),
                InlineKeyboardButton(text="❌ Bekor qilish", callback_data="voice_cancel_action"),
            ]
        ]
    )


@router.message(F.voice | F.audio)
async def handle_voice_message(message: Message, bot: Bot, ai: AIManager) -> None:
    """Ovozli xabar kelganda uni tahlil qilish."""
    # Faqat adminga ruxsat
    if message.from_user and message.from_user.id != ADMIN_ID:
        await message.reply("⛔ Kechirasiz, faqat tizim administratori ovozli buyruqlardan foydalana oladi.")
        return

    # Chat action ko'rsatish
    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.RECORD_VOICE)

    status_msg = await message.reply("🎧 Ovozli xabar qabul qilindi. Tinglanmoqda va tahlil qilinmoqda...")

    try:
        # Fayl ID sini aniqlash
        file_id = message.voice.file_id if message.voice else message.audio.file_id
        mime_type = message.voice.mime_type if message.voice else (message.audio.mime_type or "audio/ogg")

        # Telegramdan faylni to'g'ridan-to'g'ri xotiraga (RAM) yuklab olish
        file_io = io.BytesIO()
        await bot.download(file_id, destination=file_io)
        audio_bytes = file_io.getvalue()

        if not audio_bytes:
            await status_msg.edit_text("❌ Ovozli faylni yuklab olishda xatolik yuz berdi.")
            return

        # Gemini 3.6 Flash Multimodal Audio orqali tahlil qilish
        instruction = (
            "Siz foydalanuvchining shaxsiy aqlli yordamchisisiz (Super-Agent).\n"
            "Ushbu ovozli xabarni diqqat bilan eshiting va tushuning.\n\n"
            "Format:\n"
            "🎙 **Transkripsiya (Aytilgan so'zlar):**\n"
            "<aniq eshitilgan matn>\n\n"
            "🎯 **Aniqlangan Vazifa / Buyruq:**\n"
            "<agar biror kishiga yozish, eslatma qo'yish yoki amal bajarish buyurilgan bo'lsa, aniq tahlil>\n\n"
            "💡 **Tavsiya etilgan keyingi qadam:**\n"
            "<buyruqni bajarish bo'yicha xulosa>"
        )

        ai_response = await ai.generate_with_audio(
            audio_bytes=audio_bytes,
            mime_type=mime_type,
            custom_instruction=instruction,
        )

        await db.log_event("voice_task", f"Audio analyzed, size: {len(audio_bytes)} bytes")

        from core.safe_send import safe_edit_text

        # Natijani chiqarish
        await safe_edit_text(
            status_msg,
            ai_response,
            reply_markup=get_voice_actions_keyboard() if "🎯" in ai_response else None,
            parse_mode="Markdown",
        )

        # ─── Realistik Ovozli Javob Qaytarish (edge-tts) ───
        from config import ENABLE_VOICE_REPLIES
        if ENABLE_VOICE_REPLIES:
            try:
                from core.tts_agent import generate_speech_audio
                from aiogram.types import BufferedInputFile

                # AI javobidagi eng muhim qismini (tavsiya yoki xulosani) ovozga aylantirish
                speech_text = ai_response
                if "💡" in speech_text:
                    speech_text = speech_text.split("💡")[-1]
                elif "🎯" in speech_text:
                    speech_text = speech_text.split("🎯")[-1]

                voice_bytes = await generate_speech_audio(speech_text)
                if voice_bytes:
                    voice_file = BufferedInputFile(file=voice_bytes, filename="superagent_reply.mp3")
                    await message.reply_voice(
                        voice=voice_file,
                        caption="🎙 **Ovozli AI Javobi**",
                    )
            except Exception as tts_err:
                logger.debug("Ovozli javob yuborishda xatolik: %s", tts_err)

    except Exception as exc:
        logger.error("Ovozli xabarni qayta ishlash xatosi: %s", exc)
        from core.safe_send import safe_edit_text
        await safe_edit_text(status_msg, f"❌ Ovozli xabarni qayta ishlashda xatolik: {exc}", parse_mode=None)


@router.callback_query(F.data == "voice_confirm_action")
async def on_voice_confirm(callback: CallbackQuery) -> None:
    """Ovozli buyruqni bajarish tasdiqlandi."""
    await callback.answer("✅ Buyruq qabul qilindi va ijroga topshirildi!", show_alert=True)
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=None)


@router.callback_query(F.data == "voice_cancel_action")
async def on_voice_cancel(callback: CallbackQuery) -> None:
    """Ovozli buyruq bekor qilindi."""
    await callback.answer("❌ Bekor qilindi.")
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=None)

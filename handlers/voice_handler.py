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
    """Ovozli xabar kelganda uni Speech-to-Text va Ovozli Agent orqali to'liq bajarish."""
    if message.from_user and message.from_user.id != ADMIN_ID:
        await message.reply("⛔ Kechirasiz, faqat tizim administratori ovozli buyruqlardan foydalana oladi.")
        return

    from core.speech_agent import process_voice_agent_message
    await process_voice_agent_message(message=message, bot=bot, ai_manager=ai)


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

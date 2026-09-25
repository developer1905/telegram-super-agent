"""
handlers/photo_handler.py — Rasm Qabul Qilish va Tahrirlash

Foydalanuvchi yuborgan rasmni:
1. Caption yo'q → Gemini multimodal tahlil
2. Caption buyruq → Pillow orqali tahrirlash (grayscale, blur, resize...)
3. Tahrirlangan rasmni yangi fayl sifatida qaytarish
"""

from __future__ import annotations

import io
import logging

from aiogram import Router, F, Bot
from aiogram.types import Message, BufferedInputFile

from config import ADMIN_ID
from core.database import db
from core.ai_manager import AIManager
from core.image_editor import (
    apply_edit,
    parse_edit_command,
    FILTER_COMMANDS,
)
from services.scheduler import LogCollector

logger = logging.getLogger(__name__)
router = Router(name="photo")


# ─── Rasm Handler ─────────────────────────────────────────────

@router.message(F.photo)
async def handle_photo(message: Message, bot: Bot, ai_manager: AIManager) -> None:
    """
    Rasm qabul qiladi.
    Caption asosida tahrirlash yoki multimodal tahlil bajaradi.
    """
    user_id = message.from_user.id if message.from_user else 0
    if await db.is_user_blocked(user_id):
        await message.answer("❌ Sizning hisobingiz administrator tomonidan bloklangan.")
        return
    caption = (message.caption or "").strip()
    photo = message.photo[-1]  # Eng yuqori sifatli versiya

    # Rasmni RAMga yuklash
    wait_msg = await message.answer("⏳ Rasm yuklanmoqda...")
    try:
        file_obj = await bot.get_file(photo.file_id)
        file_buf = io.BytesIO()
        await bot.download_file(file_obj.file_path, destination=file_buf)
        image_bytes = file_buf.getvalue()
        image_mime = "image/jpeg"
    except Exception as exc:
        await wait_msg.edit_text(f"❌ Rasm yuklanmadi: {exc}")
        logger.error("Rasm yuklanmadi: %s", exc, exc_info=True)
        return

    # ─── Caption bo'sh → AI tahlil ───
    if not caption:
        await wait_msg.edit_text("🔍 Rasm tahlil qilinmoqda (Gemini Vision)...")
        await message.bot.send_chat_action(message.chat.id, "typing")

        # Gemini ga majburan yuborish (multimodal)
        original_provider = ai_manager.current_provider
        original_or_model = ai_manager.current_or_model
        if ai_manager.current_provider != "gemini":
            ai_manager.current_provider = "gemini"

        analysis = await ai_manager.generate(
            user_message=(
                "Bu rasmni batafsil tahlil qil:\n"
                "1. Rasmda nima ko'rinmoqda?\n"
                "2. Ranglar, kompozitsiya va uslub haqida ayt\n"
                "3. Qanday maqsadda ishlatilgan bo'lishi mumkin?\n"
                "4. Yaxshilash bo'yicha tavsiyalar"
            ),
            image_bytes=image_bytes,
            image_mime=image_mime,
        )

        # Provayderini qaytarish
        ai_manager.current_provider = original_provider
        ai_manager.current_or_model = original_or_model

        await wait_msg.edit_text(
            f"🖼 **Rasm Tahlili (Gemini Vision):**\n{'─'*30}\n\n{analysis}",
            parse_mode="Markdown",
        )

        LogCollector().add(
            action_type="photo",
            description="AI multimodal rasm tahlili",
            model_used="gemini-vision",
        )
        return

    # ─── Caption buyruq → Tahrirlash ───
    cmd, params = parse_edit_command(caption)

    if cmd is None:
        # Noma'lum caption — AI tahlil bilan bajarish
        await wait_msg.edit_text("🤔 Rasm haqida savolingizga javob berilmoqda...")
        await message.bot.send_chat_action(message.chat.id, "typing")

        original_provider = ai_manager.current_provider
        if ai_manager.current_provider != "gemini":
            ai_manager.current_provider = "gemini"

        analysis = await ai_manager.generate(
            user_message=caption,
            image_bytes=image_bytes,
            image_mime=image_mime,
        )

        ai_manager.current_provider = original_provider

        await wait_msg.edit_text(analysis, parse_mode="Markdown")

        LogCollector().add(
            action_type="photo",
            description=f"Rasm+savol: {caption[:40]}",
            model_used="gemini-vision",
        )
        return

    # Tahrirlash buyrug'i aniqlandi
    await wait_msg.edit_text(f"🎨 `{cmd}` qo'llanilmoqda...", parse_mode="Markdown")

    edited_bytes, description = apply_edit(image_bytes, cmd, params)

    if edited_bytes is None:
        # Xato
        await wait_msg.edit_text(description, parse_mode="Markdown")
        return

    # Tahrirlangan rasmni yuborish
    await wait_msg.delete()

    input_file = BufferedInputFile(
        file=edited_bytes,
        filename=f"edited_{cmd}.jpg",
    )
    await message.answer_photo(
        photo=input_file,
        caption=f"✅ {description}\n📐 Asl: `{photo.width}×{photo.height}`",
        parse_mode="Markdown",
    )

    LogCollector().add(
        action_type="photo",
        description=f"Rasm tahrirlash: {cmd} {params}",
        model_used="pillow",
    )


# ─── Barcha Tahrirlash Buyruqlari Ro'yxati ───────────────────

@router.message(ADMIN_FILTER, F.text.lower() == "rasmlar")
async def show_image_commands(message: Message) -> None:
    """Rasm tahrirlash buyruqlari ro'yxatini ko'rsatadi."""
    text = (
        "🖼 **Rasm Tahrirlash Buyruqlari**\n\n"
        "Rasm yuboring va caption sifatida yozing:\n\n"
        "`grayscale` — Kulrang rang\n"
        "`blur` — Blur (흐릿lashtirish)\n"
        "`sharpen` — Tiklash\n"
        "`brightness [0.5-3.0]` — Yorqinlik (masalan: `brightness 1.8`)\n"
        "`contrast [0.5-3.0]` — Kontrast (masalan: `contrast 2.0`)\n"
        "`watermark [matn]` — Suv belgisi (masalan: `watermark © Mening Kanalim`)\n"
        "`resize [kenglik] [balandlik]` — O'lcham (masalan: `resize 1280 720`)\n"
        "`crop [x] [y] [kenglik] [balandlik]` — Kesish\n\n"
        "Caption yo'q bo'lsa → **AI multimodal tahlil**\n"
        "Boshqa savol yozsangiz → **AI rasm haqida javob beradi**"
    )
    await message.answer(text, parse_mode="Markdown")

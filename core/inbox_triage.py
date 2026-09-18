"""
core/inbox_triage.py — Aqlli Kiruvchi Xabarlar Saralash va Avto-Javob Qoralamalari (Smart Inbox Triage)

Userbot orqali kiruvchi shaxsiy xabarlarni orqa fonda kuzatadi.
Spam va reklamalarni e'tiborsiz qoldirib, muhim xabarlarni (mijoz, sherik, biznes, pul)
saralab, adminga darhol bildirishnoma beradi va tayyor qoralama (draft) javob tayyorlaydi.
Admin [Yuborish] tugmasini bossa, Userbot orqali xavfsiz (Anti-Ban bilan) javob beradi.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, Optional

from telethon import events
from telethon.tl.types import User

from config import ADMIN_ID
from core.anti_ban import anti_ban
from core.database import db

logger = logging.getLogger(__name__)

# Saqlanib turgan qoralamalar ombori: draft_id -> dict
PENDING_DRAFTS: dict[str, dict] = {}
# Spam va takrorlanishdan himoya: user_id -> last_timestamp
_USER_COOLDOWNS: dict[int, float] = {}


def get_pending_draft(draft_id: str) -> Optional[dict]:
    """Qoralama ma'lumotlarini olish."""
    return PENDING_DRAFTS.get(draft_id)


def remove_pending_draft(draft_id: str) -> None:
    """Qoralamani o'chirish."""
    PENDING_DRAFTS.pop(draft_id, None)


async def send_draft_reply(userbot_client: Any, draft_id: str) -> tuple[bool, str]:
    """Tasdiqlangan qoralamani Userbot orqali xavfsiz jo'natish."""
    draft = PENDING_DRAFTS.get(draft_id)
    if not draft:
        return False, "Qoralama muddati o'tgan yoki topilmadi."

    peer_id = draft["peer_id"]
    reply_text = draft["reply_text"]
    sender_name = draft.get("sender_name", "Foydalanuvchi")

    try:
        # Anti-Ban xavfsizlik oraliq vaqti bilan yuborish
        await anti_ban.safe_send_message(userbot_client, peer_id, reply_text)
        await db.log_event("userbot_send", f"Draft reply sent to {sender_name} (ID: {peer_id})")
        PENDING_DRAFTS.pop(draft_id, None)
        return True, f"✅ Javob **{sender_name}** ga muvaffaqiyatli yuborildi!"
    except Exception as exc:
        logger.error("send_draft_reply xatosi: %s", exc)
        return False, f"❌ Xabar yuborishda xatolik: {exc}"


async def init_inbox_triage(userbot_client: Any, bot_instance: Any, ai_manager: Any) -> None:
    """Telethon Userbot ga kiruvchi shaxsiy xabarlarni kuzatish eventini ulash."""
    if not userbot_client:
        logger.warning("InboxTriage: Userbot ulanmagan, saralash ishga tushmadi.")
        return

    @userbot_client.on(events.NewMessage(incoming=True))
    async def on_new_private_message(event: Any) -> None:
        try:
            # Faqat shaxsiy (private) suhbatlar
            if not event.is_private or event.out:
                return

            sender_id = event.sender_id
            # Admin o'ziga o'zi yozsa yoki bot bo'lsa e'tibor bermaymiz
            if sender_id == ADMIN_ID:
                return

            sender = await event.get_sender()
            if isinstance(sender, User) and getattr(sender, "bot", False):
                return

            # Cooldown tekshiruvi: bitta odam ketma-ket yozsa har soniyada bezovta qilmaslik (60 soniya)
            now = time.time()
            last_time = _USER_COOLDOWNS.get(sender_id, 0.0)
            if now - last_time < 45.0:
                return
            _USER_COOLDOWNS[sender_id] = now

            msg_text = (event.raw_text or "").strip()
            if not msg_text or len(msg_text) < 3:
                return

            sender_title = getattr(sender, "first_name", "") or ""
            if getattr(sender, "last_name", None):
                sender_title += f" {sender.last_name}"
            username_str = f"@{sender.username}" if getattr(sender, "username", None) else f"ID: {sender_id}"
            if not sender_title:
                sender_title = username_str

            # AI orqali muhimlikni tekshirish
            triage_prompt = (
                f"Siz aqlli kotibsiz. Foydalanuvchining shaxsiy Telegramiga yangi xabar keldi.\n"
                f"Kimdan: {sender_title} ({username_str})\n"
                f"Xabar: \"{msg_text}\"\n\n"
                f"Vazifa:\n"
                f"1. Agar bu reklama, spam, havola yoki keraksiz spam bo'lsa: 'SPAM' so'zini qaytaring.\n"
                f"2. Agar oddiy salom-alik bo'lsa va zudlik bilan javob talab qilmasa: 'LOW' deb qaytaring.\n"
                f"3. Agar bu muhim xabar bo'lsa (biznes, mijoz, buyurtma, hamkorlik, pul, qarz, shartnoma, muhim savol):\n"
                f"Quyidagi formatda qaytaring:\n"
                f"STATUS: HIGH\n"
                f"SUMMARY: <xabarning 1 qatorlik o'zbekcha qisqa mazmuni>\n"
                f"DRAFT: <foydalanuvchi nomidan qaytarilishi mumkin bo'lgan o'ta xushmuomala, professional va ixcham o'zbekcha qoralama javob>"
            )

            triage_res = await ai_manager.generate(triage_prompt, save_history=False)

            if "STATUS: HIGH" in triage_res or "HIGH" in triage_res:
                # Qisqa mazmun va draftni ajratib olish
                summary = "Muhim shaxsiy xabar"
                draft_text = "Assalomu alaykum! Xabaringizni oldim, tez orada batafsil javob qaytaraman."

                for line in triage_res.splitlines():
                    if line.startswith("SUMMARY:"):
                        summary = line.replace("SUMMARY:", "").strip()
                    elif line.startswith("DRAFT:"):
                        draft_text = line.replace("DRAFT:", "").strip()

                draft_id = str(uuid.uuid4())[:8]
                PENDING_DRAFTS[draft_id] = {
                    "peer_id": sender_id,
                    "reply_text": draft_text,
                    "sender_name": sender_title,
                }

                # Adminga Telegram bot orqali bildirishnoma va tugmalar yuborish
                from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

                keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(text="🚀 Yuborish (Userbot)", callback_data=f"send_draft:{draft_id}"),
                            InlineKeyboardButton(text="❌ E'tiborsiz qoldirish", callback_data=f"dismiss_draft:{draft_id}"),
                        ]
                    ]
                )

                notify_text = (
                    f"📬 **Muhim Kiruvchi Xabar (Smart Inbox Triage)**\n\n"
                    f"👤 **Kimdan:** {sender_title} ({username_str})\n"
                    f"💬 **Xabar:**\n_{msg_text}_\n\n"
                    f"📝 **Qisqacha mazmun:**\n{summary}\n\n"
                    f"✍️ **Tavsiya etilgan javob (Draft):**\n`{draft_text}`"
                )

                await bot_instance.send_message(
                    chat_id=ADMIN_ID,
                    text=notify_text,
                    reply_markup=keyboard,
                    parse_mode="Markdown",
                )
                await db.log_event("inbox_triage", f"High priority from {sender_title}")

        except Exception as exc:
            logger.error("on_new_private_message xatosi: %s", exc)

    logger.info("InboxTriage: Smart Inbox Triage kuzatuvchisi faollashtirildi.")

"""
handlers/group_handler.py — Guruhlar va Kanallarda Avtomatik Salomlashish va AI Yordamchi

Imkoniyatlar:
1. my_chat_member / new_chat_members orqali kanal yoki guruhga qo'shilganda avtomatik salomlashish (bulletproof safe_send).
2. Kanallarni va guruhlarni avtomatik bazaga (managed_chats) ro'yxatga olish.
3. Guruhda admin yozsa yoki buyruq bersa zudlik bilan javob berish.
4. Guruh a'zolari botga savol bersa (bot ..., @mention, reply, yoki savol belgisi ?) aqlli AI javob qaytarish.
5. Kanallarda post chiqarilganda yoki savol berilganda (savol?, bot..., #xulosa, /ai) kanalga avtomatik AI tahlil va javob yo'llash.
6. Adminga yangi guruh/kanal qo'shilganida to'liq hisobot berish.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from aiogram import Router, F
from aiogram.types import (
    Message,
    ChatMemberUpdated,
)

from config import ADMIN_ID
from core.ai_manager import AIManager
from core.database import db
from core.reminder_manager import parse_reminder_smart
from core.safe_send import safe_send_message, safe_message_reply, safe_message_answer
from services.scheduler import LogCollector

logger = logging.getLogger(__name__)
router = Router(name="group")


# ─── 1. KANAL YOKI GURUHGA QO'SHILGANDA AVTOMATIK SALOMLASHISH ───

@router.my_chat_member()
async def on_my_chat_member_updated(event: ChatMemberUpdated) -> None:
    """
    Bot kanal yoki guruhga qo'shilganda, admin qilinganda yoki chiqarilganda ishlaydi.
    """
    old_status = event.old_chat_member.status
    new_status = event.new_chat_member.status
    chat = event.chat

    logger.info(
        "ChatMemberUpdated: chat_id=%s, title='%s', type=%s, %s -> %s",
        chat.id,
        chat.title,
        chat.type,
        old_status,
        new_status,
    )

    # 1. KANALGA QO'SHILGANDA
    if chat.type == "channel":
        if new_status == "administrator":
            # Bazaga saqlash
            await db.add_or_update_managed_chat(
                chat_id=chat.id,
                title=chat.title or "Nomsiz Kanal",
                chat_type="channel",
                username=chat.username or "",
            )

            # Kanalga avtomatik salomlashish posti
            welcome_post = (
                "🎉 **Assalomu alaykum!**\n\n"
                "Ushbu kanalga **Super-Agent AI** tizimi muvaffaqiyatli ulandi! 🤖✨\n\n"
                "📌 **Imkoniyatlar:**\n"
                "• Kanalga berilgan savollarga avtomatik AI tahlil va javoblar\n"
                "• Postlarni avtomatik rejalashtirish va chiqarish\n"
                "• Gemini AI yordamida tezislar, xulosalar va hashtaglar tayyorlash\n\n"
                "Kanalda botga murojaat qilish uchun postda `bot [savol]` yoki `/ai [savol]` deb yozishingiz mumkin."
            )
            try:
                await safe_send_message(
                    bot=event.bot,
                    chat_id=chat.id,
                    text=welcome_post,
                    parse_mode="Markdown",
                )
                logger.info("✅ '%s' kanaliga salomlashish posti chiqarildi", chat.title)
            except Exception as exc:
                logger.warning("Kanalga salomlashish posti yuborilmadi (%s): %s", chat.id, exc)

            # Adminga xabarnoma
            try:
                admin_notice = (
                    f"📢 **Bot yangi kanalga Admin bo'lib ulandi!**\n\n"
                    f"📌 Kanal: **{chat.title}**\n"
                    f"🆔 ID: `{chat.id}`\n"
                    f"🔗 Username: @{chat.username or 'yo‘q'}\n\n"
                    f"✅ Kanalga salomlashish posti chiqarildi va bazaga saqlandi!"
                )
                await safe_send_message(
                    bot=event.bot,
                    chat_id=ADMIN_ID,
                    text=admin_notice,
                    parse_mode="Markdown",
                )
            except Exception as exc:
                logger.warning("Adminga kanal xabari yuborilmadi: %s", exc)

        elif new_status in ("kicked", "left"):
            await db.remove_managed_chat(chat.id)
            try:
                await safe_send_message(
                    bot=event.bot,
                    chat_id=ADMIN_ID,
                    text=f"⚠️ **Diqqat:** Bot `{chat.title}` kanalidan chiqarildi.",
                    parse_mode="Markdown",
                )
            except Exception:
                pass
        return

    # 2. GURUH YOKI SUPERGURUHGA QO'SHILGANDA
    if chat.type in ("group", "supergroup"):
        if new_status in ("member", "administrator"):
            # Bazaga saqlash
            await db.add_or_update_managed_chat(
                chat_id=chat.id,
                title=chat.title or "Nomsiz Guruh",
                chat_type="group",
                username=chat.username or "",
            )

            bot_user = await event.bot.get_me()
            bot_username = bot_user.username or "bot"

            # Guruhga avtomatik salomlashish xabari
            welcome_group = (
                f"👋 **Assalomu alaykum, aziz \"{chat.title}\" a'zolari!**\n\n"
                f"Men **Super-Agent AI** — aqlli guruh yordamchisiman! 🤖✨\n\n"
                f"💡 **Menga murojaat qilish oson:**\n"
                f"1. `bot [savolingiz]` yoki `@{bot_username} [savol]` deb yozing\n"
                f"2. Mening xabarimga **Reply** (javob) qiling\n"
                f"3. Biror xabarni tushunmasangiz, unga reply qilib `bot tushuntir` deng\n\n"
                f"Barcha savollaringizga mamnuniyat bilan javob beraman! 🚀"
            )
            try:
                await safe_send_message(
                    bot=event.bot,
                    chat_id=chat.id,
                    text=welcome_group,
                    parse_mode="Markdown",
                )
                logger.info("✅ '%s' guruhiga salomlashish xabari yuborildi", chat.title)
            except Exception as exc:
                logger.warning("Guruhga salomlashish xabari yuborilmadi (%s): %s", chat.id, exc)

            # Adminga xabarnoma
            try:
                admin_notice = (
                    f"👥 **Bot yangi guruhga ulandi!**\n\n"
                    f"📌 Guruh: **{chat.title}**\n"
                    f"🆔 ID: `{chat.id}`\n"
                    f"🔗 Username: @{chat.username or 'yo‘q'}\n"
                    f"👑 Status: {new_status}\n\n"
                    f"Guruh a'zolari botga savol bersa yoki siz buyruq bersangiz, zudlik bilan javob beradi."
                )
                await safe_send_message(
                    bot=event.bot,
                    chat_id=ADMIN_ID,
                    text=admin_notice,
                    parse_mode="Markdown",
                )
            except Exception as exc:
                logger.warning("Adminga guruh xabari yuborilmadi: %s", exc)

        elif new_status in ("kicked", "left"):
            await db.remove_managed_chat(chat.id)
            try:
                await safe_send_message(
                    bot=event.bot,
                    chat_id=ADMIN_ID,
                    text=f"⚠️ **Diqqat:** Bot `{chat.title}` guruhidan chiqarildi.",
                    parse_mode="Markdown",
                )
            except Exception:
                pass


# ─── 2. NEW_CHAT_MEMBERS (Foydalanuvchi botni guruhga qo'shganda) ─

@router.message(F.chat.type.in_({"group", "supergroup"}), F.new_chat_members)
async def on_new_chat_members(message: Message) -> None:
    """Foydalanuvchi botni guruhga qo'shganda salomlashish."""
    bot_user = await message.bot.get_me()
    for member in message.new_chat_members:
        if member.id == bot_user.id:
            await db.add_or_update_managed_chat(
                chat_id=message.chat.id,
                title=message.chat.title or "Guruh",
                chat_type="group",
                username=message.chat.username or "",
            )
            welcome_group = (
                f"👋 **Assalomu alaykum, aziz \"{message.chat.title}\" a'zolari!**\n\n"
                f"Men **Super-Agent AI** — aqlli guruh yordamchisiman! 🤖✨\n\n"
                f"💡 **Menga murojaat qilish uchun:**\n"
                f"• Xabaringiz boshida `bot [savolingiz]` deb yozing yoki `@{bot_user.username}` deb belgilang!\n"
                f"• Yoki mening xabarimga **Reply** qiling.\n\n"
                f"Savol va topshiriqlaringizni bajonidil bajaraman!"
            )
            try:
                await safe_message_answer(message, welcome_group, parse_mode="Markdown")
            except Exception as exc:
                logger.warning("Guruh new_chat_members xatosi: %s", exc)
            break


# ─── 3. GURUHDA BUYRUQ VA SAVOLLARGA JAVOB BERISH ────────────

@router.message(F.chat.type.in_({"group", "supergroup"}), F.text)
async def handle_group_message(message: Message, ai_manager: AIManager) -> None:
    """
    Guruhdagi barcha xabarlarni aqlli tahlil qilish:
    1. Admin yozsa: Har qanday savol yoki buyruqqa darhol javob beradi.
    2. Har qanday a'zo uchun:
       - Botga reply qilinganda
       - @mention qilinganda
       - Xabarda 'bot', 'ai', 'agent' so'zlari bilan boshlansa yoki murojaat bo'lsa
       - Biror xabarga reply qilib 'bot javob ber', 'tushuntir', 'tarjima qil' deyilsa
       - Savol berilganda (? belgisi bilan va botga tegishli bo'lsa)
    """
    raw_text = (message.text or "").strip()
    if not raw_text:
        return

    is_admin = (message.from_user and message.from_user.id == ADMIN_ID)
    bot_user = await message.bot.get_me()
    bot_username = (bot_user.username or "").lower()
    bot_mention = f"@{bot_username}" if bot_username else ""

    text_lower = raw_text.lower()

    # 1. Reply tekshiruvi: botning xabariga reply qilinganmi?
    is_reply_to_bot = (
        message.reply_to_message is not None
        and message.reply_to_message.from_user is not None
        and message.reply_to_message.from_user.id == bot_user.id
    )

    # 2. Mention tekshiruvi: @bot_username yozilganmi?
    is_bot_mentioned = bool(bot_mention and bot_mention in text_lower)

    # 3. Bot prefikslari (bot, botjon, ai, /ai, /bot, /ask, superagent, agent, ey bot, salom bot)
    prefix_pattern = r"^(?:bot|botjon|ai|/ai|/bot|/ask|agent|superagent|ey bot|salom bot|qani bot)[\s,:!-]+"
    starts_with_bot = bool(re.search(prefix_pattern, text_lower))

    # 4. Matn ichida botga murojaat bor-yo'qligi
    contains_bot_call = bool(re.search(r"\b(?:bot|botjon|superagent)\b", text_lower))

    # 5. Boshqa odamning xabariga reply qilib botdan yordam so'rash
    is_reply_to_other = message.reply_to_message is not None and not is_reply_to_bot
    is_asking_on_reply = is_reply_to_other and (
        contains_bot_call
        or any(w in text_lower for w in ["tushuntir", "javob ber", "tarjima qil", "bunga nima", "fikring", "tahlil"])
    )

    # 6. Admin uchun kengaytirilgan ruxsat
    is_admin_direct = is_admin and (
        raw_text.startswith("/")
        or starts_with_bot
        or contains_bot_call
        or raw_text.endswith("?")
        or any(w in text_lower for w in ["eslat", "remind", "post", "tahlil", "statistika", "xabar"])
    )

    # Bot javob berishi kerakmi?
    should_reply = (
        is_reply_to_bot
        or is_bot_mentioned
        or starts_with_bot
        or is_asking_on_reply
        or (contains_bot_call and raw_text.endswith("?"))
        or is_admin_direct
    )

    if not should_reply:
        return

    # Prefikslarni tozalash (AI ga toza so'rov yuborish uchun)
    clean_query = raw_text
    if starts_with_bot:
        clean_query = re.sub(prefix_pattern, "", clean_query, flags=re.IGNORECASE).strip()
    if bot_mention:
        clean_query = re.sub(re.escape(bot_mention), "", clean_query, flags=re.IGNORECASE).strip()
    clean_query = clean_query.strip()

    # Reply qilingan xabar bo'lsa, uning matnini kontekst sifatida qo'shamiz
    replied_context = ""
    if message.reply_to_message:
        replied_text = message.reply_to_message.text or message.reply_to_message.caption or ""
        sender_name = message.reply_to_message.from_user.full_name if message.reply_to_message.from_user else "A'zo"
        if replied_text:
            replied_context = f"[Mavzu xabari ({sender_name}): '{replied_text[:500]}']\n"

    # Agar xabar faqat "bot" bo'lib boshqa matn bo'lmasa
    if not clean_query and not replied_context:
        user_name = message.from_user.first_name if message.from_user else "do'stim"
        await safe_message_reply(
            message,
            f"Assalomu alaykum, {user_name}! Savolingiz yoki topshirig'ingizni yozing, bajonidil yordam beraman! Masalan: `bot O'zbekistonning diqqatga sazovor joylari haqida aytib ber`",
            parse_mode="Markdown",
        )
        return

    # ── ADMIN XOS BUYRUQLARI ──
    if is_admin:
        # 1. Eslatma o'rnatish
        if any(w in clean_query.lower() for w in ["eslat", "remind", "eslatma"]):
            rem_res = await parse_reminder_smart(clean_query, ai_manager)
            if rem_res:
                rem_time, rem_task = rem_res
                await db.add_reminder(message.chat.id, rem_task, rem_time)
                await safe_message_reply(
                    message,
                    f"⏰ **Eslatma qabul qilindi, hurmatli Admin!**\n\n"
                    f"📝 Vazifa: {rem_task}\n"
                    f"🕒 Vaqt: `{rem_time}`\n"
                    f"Vaqti kelganda ushbu guruhga signal yuboraman.",
                    parse_mode="Markdown",
                )
                return

        # 2. /status
        if clean_query.lower() in ("/status", "holat", "status"):
            status_text = ai_manager.status()
            await safe_message_reply(message, f"📊 **Bot Holati:**\n{status_text}", parse_mode="Markdown")
            return

        # 3. /clear
        if clean_query.lower() in ("/clear", "tozala"):
            res = ai_manager.clear_history()
            await safe_message_reply(message, res, parse_mode="Markdown")
            return

    # ── AI JAVOBI YARATISH ──
    try:
        await message.bot.send_chat_action(message.chat.id, "typing")
    except Exception:
        pass

    user_full = message.from_user.full_name if message.from_user else "Foydalanuvchi"
    group_title = message.chat.title or "Guruh"

    full_prompt = (
        f"Guruh: '{group_title}'. Foydalanuvchi: {user_full}.\n"
        f"{replied_context}"
        f"Savol / Murojaat: {clean_query or 'Ushbu mavzuni tushuntirib ber.'}\n\n"
        f"Talab: Guruh a'zosiga do'stona, aniq, foydali va chiroyli formatda o'zbek tilida javob ber."
    )

    try:
        response = await ai_manager.generate(full_prompt, save_history=False)
        await safe_message_reply(message, response, parse_mode="Markdown")
        LogCollector().add(
            action_type="group_ai",
            description=f"Guruh ({group_title}): {clean_query[:35]}",
            model_used="gemini_assistant",
        )
    except Exception as exc:
        logger.error("Guruhda AI javobida xatolik: %s", exc)
        await safe_message_reply(
            message,
            "⚠️ Kechirasiz, so'rovingizga javob tayyorlashda xatolik yuz berdi. Iltimos, qayta urinib ko'ring.",
            parse_mode=None,
        )


# ─── 4. KANALDA POSTLAR VA SAVOLLARGA JAVOB BERISH (CHANNEL_POST) ─

@router.channel_post(F.text)
async def handle_channel_post(message: Message, ai_manager: AIManager) -> None:
    """
    Kanalga yangi post chiqarilganda yoki savol berilganda ishlaydi.
    1. Kanalni doimiy bazaga (managed_chats) avtomatik kiritadi.
    2. Agar postda savol berilsa (oxirida '?' bo'lsa), yoki 'bot', '/ai', '@bot', 'savol:' bo'lsa:
       Bot kanalga darhol aqlli javob yoki sharh xabarini chiqaradi.
    3. Agar postda #ai_xulosa, #bot_tahlil yoki 'xulosa:' bo'lsa:
       Postning qisqacha xulosasi va hashtaglarini kanalga sharh qilib chiqaradi.
    """
    raw_text = (message.text or "").strip()
    if not raw_text:
        return

    logger.info("ChannelPost received in '%s': %s", message.chat.title, raw_text[:45])

    # 1. Kanalni bazada yangilab qo'yamiz
    await db.add_or_update_managed_chat(
        chat_id=message.chat.id,
        title=message.chat.title or "Kanal",
        chat_type="channel",
        username=message.chat.username or "",
    )

    bot_user = await message.bot.get_me()
    bot_username = (bot_user.username or "").lower()
    bot_mention = f"@{bot_username}" if bot_username else ""
    text_lower = raw_text.lower()

    # Triggerlarni tekshiramiz
    has_bot_call = bool(
        bot_mention in text_lower
        or re.search(r"^(?:bot|/ai|/bot|/ask|ai:)[\s,:!-]+", text_lower)
        or "#ai" in text_lower
        or "#bot" in text_lower
    )
    is_question = raw_text.endswith("?") or text_lower.startswith("savol:")
    is_summary_request = "#ai_xulosa" in text_lower or text_lower.startswith("xulosa:") or text_lower.startswith("tahlil:")

    # Agar post botga qaratilgan bo'lsa yoki savol bo'lsa yoki xulosa so'ralsa
    if has_bot_call or is_question or is_summary_request:
        try:
            await message.bot.send_chat_action(message.chat.id, "typing")
        except Exception:
            pass

        # Matnni tozalash
        clean_text = raw_text
        if bot_mention:
            clean_text = re.sub(re.escape(bot_mention), "", clean_text, flags=re.IGNORECASE).strip()
        clean_text = re.sub(r"^(?:bot|/ai|/bot|/ask|ai:|#ai_xulosa|#bot_tahlil|xulosa:|tahlil:|savol:)[\s,:!-]+", "", clean_text, flags=re.IGNORECASE).strip()

        if is_summary_request:
            prompt = (
                f"Kanal posti: '{clean_text or raw_text}'.\n\n"
                f"Ushbu post uchun qisqacha 3 ta asosiy xulosa va 4 ta eng sara hashtag tuzib ber (o'zbek tilida)."
            )
        else:
            prompt = (
                f"Telegram kanalida post / savol berildi: '{clean_text or raw_text}'.\n\n"
                f"Ushbu kanal obunachilari uchun professional, aniq, qiziqarli va chiroyli formatda javob / izoh tayyorlab ber (o'zbek tilida)."
            )

        try:
            ai_reply = await ai_manager.generate(prompt, save_history=False)
            header = "💡 **AI Xulosasi:**\n\n" if is_summary_request else "🤖 **Super-Agent Javobi:**\n\n"
            
            # Kanalga javob xabarini yo'llash (reply qilib)
            await safe_message_reply(
                message=message,
                text=f"{header}{ai_reply}",
                parse_mode="Markdown",
            )
            LogCollector().add(
                action_type="channel_ai",
                description=f"Kanal ({message.chat.title}): {raw_text[:35]}",
                model_used="gemini_assistant",
            )
            logger.info("✅ Kanalga AI javobi muvaffaqiyatli yuborildi: %s", message.chat.title)
        except Exception as exc:
            logger.error("Kanal postida AI javob tayyorlash xatosi: %s", exc)

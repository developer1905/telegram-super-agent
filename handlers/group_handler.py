"""
handlers/group_handler.py — Guruhlar va Kanallarda To'liq Avtopilot va AI Yordamchi

Imkoniyatlar:
1. my_chat_member / new_chat_members orqali kanal yoki guruhga qo'shilganda avtomatik salomlashish.
2. Kanallarni va guruhlarni bazaga (managed_chats) avtomatik ro'yxatga olish.
3. Rasm chizish (Midjourney/FLUX.1): Guruhda yoki kanalda /draw, /imagine, 'bot rasm chiz:' buyrug'i berilsa fotorealistik rasm generatsiya qilish.
4. Video yuklash: Guruhda Instagram, TikTok, YouTube havolalari yuborilganda videoni to'g'ridan-to'g'ri yuklab guruhga jo'natish.
5. Expert AI Agentlar:
   - 🔬 Deep Research: /research, /tadqiqot
   - 💻 Code Reviewer: /code, /audit, /kod
   - 📄 Document & Contract Analyzer: /doc, /shartnoma
   - 🎯 Viral SMM Creator: /smm, /post
6. Multimodal Vision & Hujjat tahlili: Guruhda rasm yoki fayl yuborib botdan so'ralsa darhol tahlil qilish.
7. Guruh Moderatsiyasi (Adminlar uchun):
   - /mute [minut], /unmute, /ban, /unban, /pin, /unpin, /rules, /setrules, /warn
8. Kanallar bilan ishlash (Channel Autopilot):
   - Postlarda savol bo'lsa yoki #xulosa, #tahlil, #fakt bo'lsa professional sharh berish
   - /post_channel orqali kanalga post chiqarish
"""

from __future__ import annotations

import asyncio
import datetime
import html
import io
import logging
import os
import re
import uuid
from typing import Optional

from aiogram import Router, F, Bot
from aiogram.types import (
    Message,
    ChatMemberUpdated,
    BufferedInputFile,
    ChatPermissions,
)

from config import ADMIN_ID
from core.ai_manager import AIManager
from core.database import db
from core.expert_agents import (
    DeepResearchAgent,
    CodeReviewerAgent,
    DocumentContractAgent,
    ViralSMMAgent,
)
from core.media_downloader import extract_media_url, download_social_video
from core.midjourney_agent import draw_midjourney_image, MJ_TASKS, build_mj_keyboard, AVAILABLE_MODELS
from core.reminder_manager import parse_reminder_smart
from core.safe_send import safe_send_message, safe_message_reply, safe_message_answer
from services.scheduler import LogCollector

logger = logging.getLogger(__name__)
router = Router(name="group")

# Guruh qoidalari uchun xotira kesh
_GROUP_RULES: dict[int, str] = {}
# Foydalanuvchilar ogohlantirishlari (user_id -> count)
_USER_WARNS: dict[str, int] = {}


async def _is_user_group_admin(message: Message) -> bool:
    """Foydalanuvchi ushbu guruhda admin yoki tizim administratori ekanligini tekshiradi."""
    if not message.from_user:
        return False
    if message.from_user.id == ADMIN_ID:
        return True
    try:
        member = await message.chat.get_member(message.from_user.id)
        return member.status in ("creator", "administrator")
    except Exception:
        return False


# ─── 1. KANAL YOKI GURUHGA QO'SHILGANDA SALOMLASHISH ─────────

@router.my_chat_member()
async def on_my_chat_member_updated(event: ChatMemberUpdated) -> None:
    """Bot kanal yoki guruhga qo'shilganda yoki chiqarilganda ishlaydi."""
    old_status = event.old_chat_member.status
    new_status = event.new_chat_member.status
    chat = event.chat

    logger.info("ChatMemberUpdated: chat_id=%s, title='%s', type=%s, %s -> %s",
                chat.id, chat.title, chat.type, old_status, new_status)

    # 1. KANALGA QO'SHILGANDA
    if chat.type == "channel":
        if new_status == "administrator":
            await db.add_or_update_managed_chat(
                chat_id=chat.id,
                title=chat.title or "Nomsiz Kanal",
                chat_type="channel",
                username=chat.username or "",
            )
            welcome_post = (
                "🎉 **Assalomu alaykum!**\n\n"
                "Ushbu kanalga **Super-Agent AI** tizimi muvaffaqiyatli ulandi! 🤖✨\n\n"
                "📌 **Imkoniyatlar:**\n"
                "• Kanal postlariga avtomatik AI tahlil, tezislar va xulosalar (#xulosa, #savol, #fakt)\n"
                "• Savollarga aqlli va professional javoblar\n"
                "• Rasm chizish va kontent yaratish imkoniyati"
            )
            try:
                await safe_send_message(bot=event.bot, chat_id=chat.id, text=welcome_post, parse_mode="Markdown")
            except Exception as exc:
                logger.warning("Kanalga salomlashish posti yuborilmadi: %s", exc)
        elif new_status in ("kicked", "left"):
            await db.remove_managed_chat(chat.id)
        return

    # 2. GURUHGA QO'SHILGANDA
    if chat.type in ("group", "supergroup"):
        if new_status in ("member", "administrator"):
            await db.add_or_update_managed_chat(
                chat_id=chat.id,
                title=chat.title or "Nomsiz Guruh",
                chat_type="group",
                username=chat.username or "",
            )
            bot_user = await event.bot.get_me()
            welcome_group = (
                f"👋 **Assalomu alaykum, \"{chat.title}\" a'zolari!**\n\n"
                f"Men **Super-Agent AI** — universal guruh yordamchisiman! 🤖✨\n\n"
                f"🚀 **Men guruhda nimalar qila olaman?**\n"
                f"• 🎨 **Rasm chizish:** `/draw [prompt]` yoki `bot rasm chiz: [so'rov]`\n"
                f"• 🎬 **Video yuklash:** Instagram/TikTok/YouTube ssilkasini yuboring\n"
                f"• 🔬 **Deep Research:** `/research [mavzu]`\n"
                f"• 💻 **Kodni tekshirish:** `/code [kod]`\n"
                f"• 📄 **Shartnoma tahlili:** `/doc [matn]`\n"
                f"• 🎯 **SMM Post:** `/smm [mavzu]`\n"
                f"• 🛡️ **Guruh moderatsiyasi:** `/mute`, `/ban`, `/pin`, `/rules` (adminlar uchun)\n"
                f"• 💬 Menga savol berish uchun `bot [savol]` deng yoki xabarimga **Reply** qiling!"
            )
            try:
                await safe_send_message(bot=event.bot, chat_id=chat.id, text=welcome_group, parse_mode="Markdown")
            except Exception as exc:
                logger.warning("Guruhga salomlashish xabari yuborilmadi: %s", exc)
        elif new_status in ("kicked", "left"):
            await db.remove_managed_chat(chat.id)


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
                f"👋 **Assalomu alaykum!** Men **Super-Agent AI**man.\n\n"
                f"Menga topshiriq berish uchun xabaringizda `bot ...` deb yozing yoki buyruqlardan foydalaning (`/draw`, `/research`, `/code`, `/smm`)."
            )
            await safe_message_answer(message, welcome_group, parse_mode="Markdown")
            break


# ─── 2. GURUHDA MATN VA TOPSHIRIQLARNI BAJARISH ──────────────

@router.message(F.chat.type.in_({"group", "supergroup"}), F.text)
async def handle_group_message(message: Message, ai_manager: AIManager, bot: Bot) -> None:
    """
    Guruhdagi har qanday topshiriq va buyruqlarni aqlli tarzda bajarish.
    """
    raw_text = (message.text or "").strip()
    if not raw_text:
        return

    text_lower = raw_text.lower()
    bot_user = await bot.get_me()
    bot_username = (bot_user.username or "").lower()
    bot_mention = f"@{bot_username}" if bot_username else ""

    # Botga murojaat tekshiruvi
    is_reply_to_bot = (
        message.reply_to_message is not None
        and message.reply_to_message.from_user is not None
        and message.reply_to_message.from_user.id == bot_user.id
    )
    is_bot_mentioned = bool(bot_mention and bot_mention in text_lower)
    starts_with_bot = bool(re.match(r"^(?:bot|botjon|ai|/ai|agent|superagent|qani bot|ey bot)[\s,:!-]+", text_lower))
    starts_with_slash = raw_text.startswith("/")
    has_media_link = bool(extract_media_url(raw_text))

    # Triggerlar
    should_process = (
        is_reply_to_bot
        or is_bot_mentioned
        or starts_with_bot
        or starts_with_slash
        or has_media_link
        or (message.reply_to_message and any(w in text_lower for w in ["bot", "tekshir", "tushuntir", "tarjima qil"]))
    )

    # Guruhdagi xabarlarni doimiy xotirada saqlab borish (AI suhbat kontekstini to'liq eslab qolishi uchun)
    user_full = message.from_user.full_name if message.from_user else "A'zo"
    user_id_str = str(message.from_user.id) if message.from_user else ""
    chat_id_str = str(message.chat.id)
    chat_type_str = message.chat.type

    if not raw_text.startswith("/"):
        try:
            asyncio.create_task(
                db.add_chat_message(
                    role="user",
                    content=raw_text,
                    chat_id=chat_id_str,
                    user_id=user_id_str,
                    sender_name=user_full,
                    chat_type=chat_type_str,
                )
            )
            c_hist = ai_manager.chat_histories.setdefault(chat_id_str, [])
            c_hist.append({
                "role": "user",
                "content": raw_text,
                "sender_name": user_full,
                "chat_id": chat_id_str,
            })
            if len(c_hist) > 40:
                ai_manager.chat_histories[chat_id_str] = c_hist[-40:]
        except Exception:
            pass

    if not should_process:
        return

    # Prefikslardan tozalangan matn
    clean_text = raw_text
    if starts_with_bot:
        clean_text = re.sub(r"^(?:bot|botjon|ai|/ai|agent|superagent|qani bot|ey bot)[\s,:!-]+", "", clean_text, flags=re.IGNORECASE).strip()
    if bot_mention:
        clean_text = re.sub(re.escape(bot_mention), "", clean_text, flags=re.IGNORECASE).strip()
    clean_text = clean_text.strip()
    clean_lower = clean_text.lower()

    # ── A. GURUH MODERATSIYASI (Adminlar uchun) ──
    is_admin = await _is_user_group_admin(message)

    # 1. /mute yoki /sukut (faqat replyga)
    if is_admin and (clean_lower.startswith("/mute") or clean_lower.startswith("/sukut") or clean_lower.startswith("bot mute")):
        if not message.reply_to_message or not message.reply_to_message.from_user:
            await safe_message_reply(message, "⚠️ Mute qilish uchun biror a'zoning xabariga reply qiling: `/mute 10` (daqiqa).", parse_mode="Markdown")
            return
        target_user = message.reply_to_message.from_user
        minutes = 10
        m = re.search(r"\d+", clean_text)
        if m:
            minutes = int(m.group(0))
        until_date = datetime.datetime.now() + datetime.timedelta(minutes=minutes)
        try:
            await bot.restrict_chat_member(
                chat_id=message.chat.id,
                user_id=target_user.id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until_date,
            )
            await safe_message_reply(message, f"🔇 **{target_user.full_name}** {minutes} daqiqaga guruhda yozishdan cheklandi.", parse_mode="Markdown")
        except Exception as exc:
            await safe_message_reply(message, f"❌ Mute qilishda xatolik: {exc}", parse_mode=None)
        return

    # 2. /unmute
    if is_admin and (clean_lower.startswith("/unmute") or clean_lower.startswith("bot unmute")):
        if not message.reply_to_message or not message.reply_to_message.from_user:
            await safe_message_reply(message, "⚠️ Unmute qilish uchun a'zoning xabariga reply qiling.", parse_mode=None)
            return
        target_user = message.reply_to_message.from_user
        try:
            await bot.restrict_chat_member(
                chat_id=message.chat.id,
                user_id=target_user.id,
                permissions=ChatPermissions(
                    can_send_messages=True,
                    can_send_audios=True,
                    can_send_documents=True,
                    can_send_photos=True,
                    can_send_videos=True,
                    can_send_other_messages=True,
                    can_add_web_page_previews=True,
                ),
            )
            await safe_message_reply(message, f"🔊 **{target_user.full_name}** uchun cheklov bekor qilindi.", parse_mode="Markdown")
        except Exception as exc:
            await safe_message_reply(message, f"❌ Unmute xatosi: {exc}", parse_mode=None)
        return

    # 3. /ban yoki /hayda
    if is_admin and (clean_lower.startswith("/ban") or clean_lower.startswith("/hayda") or clean_lower.startswith("bot ban")):
        if not message.reply_to_message or not message.reply_to_message.from_user:
            await safe_message_reply(message, "⚠️ Bandan o'tkazish uchun a'zoning xabariga reply qiling.", parse_mode=None)
            return
        target_user = message.reply_to_message.from_user
        try:
            await bot.ban_chat_member(chat_id=message.chat.id, user_id=target_user.id)
            await safe_message_reply(message, f"⛔ **{target_user.full_name}** guruhdan chiqarildi va bloklandi.", parse_mode="Markdown")
        except Exception as exc:
            await safe_message_reply(message, f"❌ Ban xatosi: {exc}", parse_mode=None)
        return

    # 4. /unban
    if is_admin and (clean_lower.startswith("/unban") or clean_lower.startswith("bot unban")):
        user_id_to_unban = None
        if message.reply_to_message and message.reply_to_message.from_user:
            user_id_to_unban = message.reply_to_message.from_user.id
        else:
            m = re.search(r"\d{6,}", clean_text)
            if m:
                user_id_to_unban = int(m.group(0))
        if user_id_to_unban:
            try:
                await bot.unban_chat_member(chat_id=message.chat.id, user_id=user_id_to_unban)
                await safe_message_reply(message, f"✅ Foydalanuvchi ({user_id_to_unban}) bandan chiqarildi.", parse_mode=None)
            except Exception as exc:
                await safe_message_reply(message, f"❌ Unban xatosi: {exc}", parse_mode=None)
        return

    # 5. /pin va /unpin
    if is_admin and (clean_lower.startswith("/pin") or clean_lower.startswith("/qada")):
        if message.reply_to_message:
            try:
                await bot.pin_chat_message(chat_id=message.chat.id, message_id=message.reply_to_message.message_id)
                await safe_message_reply(message, "📌 Xabar muvaffaqiyatli qadaldi!", parse_mode=None)
            except Exception as exc:
                await safe_message_reply(message, f"❌ Xabarni qadashda xatolik: {exc}", parse_mode=None)
        return

    if is_admin and (clean_lower.startswith("/unpin")):
        try:
            await bot.unpin_chat_message(chat_id=message.chat.id)
            await safe_message_reply(message, "📌 Qadalgan xabar yechildi.", parse_mode=None)
        except Exception as exc:
            await safe_message_reply(message, f"❌ Unpin xatosi: {exc}", parse_mode=None)
        return

    # 6. /rules va /setrules
    if clean_lower.startswith("/rules") or clean_lower == "qoidalar" or clean_lower == "guruh qoidalari":
        rules = _GROUP_RULES.get(message.chat.id, "📜 **Guruh Qoidalari:**\n1. O'zaro hurmat saqlansin.\n2. Reklama va spam taqiqlanadi.\n3. Haqoratli so'zlar ishlatilmasin.")
        await safe_message_reply(message, rules, parse_mode="Markdown")
        return

    if is_admin and clean_lower.startswith("/setrules"):
        new_rules = clean_text[9:].strip()
        if new_rules:
            _GROUP_RULES[message.chat.id] = f"📜 **Guruh Qoidalari:**\n\n{new_rules}"
            await safe_message_reply(message, "✅ Guruh qoidalari muvaffaqiyatli saqlandi!", parse_mode=None)
        return

    # 7. /warn (ogohlantirish)
    if is_admin and (clean_lower.startswith("/warn") or clean_lower.startswith("ogohlantir")):
        if message.reply_to_message and message.reply_to_message.from_user:
            t_user = message.reply_to_message.from_user
            u_key = f"{message.chat.id}:{t_user.id}"
            count = _USER_WARNS.get(u_key, 0) + 1
            _USER_WARNS[u_key] = count
            if count >= 3:
                _USER_WARNS[u_key] = 0
                until_date = datetime.datetime.now() + datetime.timedelta(hours=24)
                await bot.restrict_chat_member(chat_id=message.chat.id, user_id=t_user.id, permissions=ChatPermissions(can_send_messages=False), until_date=until_date)
                await safe_message_reply(message, f"⚠️ **{t_user.full_name}** 3 marta ogohlantirildi va 24 soatga mute qilindi!", parse_mode="Markdown")
            else:
                await safe_message_reply(message, f"⚠️ **{t_user.full_name}** ogohlantirildi! ({count}/3 ta)", parse_mode="Markdown")
            return

    # ── B. RASM CHIZISH (FLUX.1 / Midjourney) ──
    img_match = re.match(r"^(?:/draw|/imagine|/midjourney|/flux|/art|rasm\s+chiz|rasm|chiz|chizib\s+ber)[:\s]*(.*)$", clean_text, re.IGNORECASE | re.DOTALL)
    if img_match:
        prompt_query = img_match.group(1).strip()
        if not prompt_query and message.reply_to_message:
            prompt_query = message.reply_to_message.text or message.reply_to_message.caption or ""
        if prompt_query:
            wait_m = await message.reply("🎨 <b>Super-Agent Studio rasm chizmoqda...</b> Bir necha soniya kuting...", parse_mode="HTML")
            try:
                await bot.send_chat_action(message.chat.id, "upload_photo")
                img_bytes, enhanced_p, ar, seed, used_model, *_ = await draw_midjourney_image(
                    raw_prompt=prompt_query,
                    ai_manager=ai_manager,
                    enhance=True,
                )
                if img_bytes:
                    task_id = uuid.uuid4().hex[:8]
                    MJ_TASKS[task_id] = {
                        "prompt": prompt_query,
                        "enhanced": enhanced_p,
                        "ar": ar,
                        "seed": seed,
                        "model": used_model,
                        "style": "photo",
                    }
                    reply_markup = build_mj_keyboard(task_id, current_model=used_model, current_ar=ar, current_style="photo")
                    photo_file = BufferedInputFile(file=img_bytes, filename=f"flux_{task_id}.jpg")
                    model_title = AVAILABLE_MODELS.get(used_model, used_model).split("(")[0].strip()
                    caption = (
                        f"🎨 <b>Super-Agent Studio: {html.escape(model_title)}</b>\n\n"
                        f"📝 <i>{html.escape(prompt_query)}</i>\n"
                        f"📐 O'lcham: <code>{ar}</code> | 🎲 Seed: <code>{seed}</code>\n"
                        f"🤖 <b>Super-Agent</b>"
                    )
                    await wait_m.delete()
                    await message.reply_photo(photo=photo_file, caption=caption, reply_markup=reply_markup, parse_mode="HTML")
                    return
                else:
                    await wait_m.edit_text("❌ Rasm chizishda xatolik yuz berdi. Iltimos, qayta urinib ko'ring.")
            except Exception as exc:
                logger.error("Guruhda rasm chizish xatosi: %s", exc)
                await wait_m.edit_text(f"❌ Rasm generatsiyasida xatolik: {exc}")
            return

    # ── C. VIDEO YUKLASH (Instagram, TikTok, YouTube, X, Pinterest) ──
    media_url = extract_media_url(raw_text)
    if media_url:
        wait_m = await message.reply("⏳ <b>Video yuklanmoqda...</b> Iltimos, kuting...", parse_mode="HTML")
        try:
            from core.media_downloader import get_or_create_mp3
            await bot.send_chat_action(message.chat.id, "upload_video")
            info = await download_social_video(media_url)
            if info and info.get("file_path") and os.path.exists(info["file_path"]):
                f_path = info["file_path"]
                p_safe = html.escape(info.get("platform", "Video"))
                t_safe = html.escape(info.get("title", "")[:80])
                m_info = ""
                if info.get("music_title"):
                    m_info = f"\n🎵 <b>Musiqa:</b> {html.escape(info['music_title'][:60])}"

                caption = (
                    f"🎬 <b>{p_safe} yuklandi!</b>\n"
                    f"📝 <b>Nomi:</b> {t_safe}"
                    f"{m_info}\n\n"
                    f"🤖 <b>Super-Agent</b>"
                )
                from aiogram.types import FSInputFile
                v_file = FSInputFile(f_path)
                try:
                    await message.reply_video(video=v_file, caption=caption, parse_mode="HTML")
                except Exception:
                    await message.reply_document(document=v_file, caption=caption, parse_mode="HTML")

                # Agar so'rovda mp3 yoki musiqa bo'lsa
                if any(w in raw_text.lower() for w in ["mp3", "musiqa", "audio", "qo'shiq"]):
                    mp3_info = await get_or_create_mp3(info)
                    if mp3_info and os.path.exists(mp3_info["audio_path"]):
                        a_file = FSInputFile(mp3_info["audio_path"])
                        await message.reply_audio(
                            audio=a_file,
                            title=mp3_info.get("title", "Audio")[:80],
                            performer=mp3_info.get("artist", "Super-Agent")[:80],
                            caption=f"🎵 <b>{html.escape(mp3_info.get('title', 'Musiqa')[:80])}</b>",
                            parse_mode="HTML",
                        )

                await wait_m.delete()
                return
            else:
                await wait_m.edit_text("⚠️ Ushbu videoni yuklab bo'lmadi yoki havola yopiq hisobga tegishli.")
                return
        except Exception as exc:
            logger.error("Guruhda video yuklash xatosi: %s", exc)
            await wait_m.edit_text("⚠️ Video yuklashda xatolik yuz berdi.")
            return

    # ── D. 🔬 DEEP RESEARCH AGENT ──
    if clean_lower.startswith("/research") or clean_lower.startswith("/tadqiqot") or clean_lower.startswith("tadqiqot:"):
        query = re.sub(r"^(?:/research|/tadqiqot|tadqiqot:)[\s:]*", "", clean_text, flags=re.IGNORECASE).strip()
        if not query and message.reply_to_message:
            query = message.reply_to_message.text or message.reply_to_message.caption or ""
        if query:
            wait_m = await message.reply(f"🔬 **'{query[:40]}' mavzusi bo'yicha Deep Research boshlandi...**\nInternet faktlari qidirilmoqda...")
            try:
                report = await DeepResearchAgent.conduct_research(query, ai_manager)
                await wait_m.delete()
                for chunk in [report[i:i+4000] for i in range(0, len(report), 4000)]:
                    await message.reply(chunk, parse_mode="Markdown")
                return
            except Exception as exc:
                await wait_m.edit_text(f"❌ Tadqiqotda xatolik: {exc}")
                return

    # ── E. 💻 CODE REVIEWER AGENT ──
    if clean_lower.startswith("/code") or clean_lower.startswith("/audit") or clean_lower.startswith("/kod") or clean_lower.startswith("kod:"):
        code_body = re.sub(r"^(?:/code|/audit|/kod|kod:)[\s:]*", "", clean_text, flags=re.IGNORECASE).strip()
        if not code_body and message.reply_to_message:
            code_body = message.reply_to_message.text or ""
        if code_body:
            wait_m = await message.reply("💻 **Kod auditi o'tkazilmoqda...** Xatolar va xavfsizlik tekshirilmoqda...")
            try:
                audit_res = await CodeReviewerAgent.review_code(code_body, ai_manager)
                await wait_m.delete()
                for chunk in [audit_res[i:i+4000] for i in range(0, len(audit_res), 4000)]:
                    await message.reply(chunk, parse_mode="Markdown")
                return
            except Exception as exc:
                await wait_m.edit_text(f"❌ Kod auditida xatolik: {exc}")
                return

    # ── F. 📄 DOCUMENT & CONTRACT ANALYZER ──
    if clean_lower.startswith("/doc") or clean_lower.startswith("/shartnoma") or clean_lower.startswith("shartnoma:"):
        doc_text = re.sub(r"^(?:/doc|/shartnoma|shartnoma:)[\s:]*", "", clean_text, flags=re.IGNORECASE).strip()
        if not doc_text and message.reply_to_message:
            doc_text = message.reply_to_message.text or message.reply_to_message.caption or ""
        if doc_text:
            wait_m = await message.reply("📄 **Hujjat va shartnoma xatarlari tahlil qilinmoqda...**")
            try:
                analysis = await DocumentContractAgent.analyze_contract(doc_text, ai_manager)
                await wait_m.delete()
                for chunk in [analysis[i:i+4000] for i in range(0, len(analysis), 4000)]:
                    await message.reply(chunk, parse_mode="Markdown")
                return
            except Exception as exc:
                await wait_m.edit_text(f"❌ Shartnoma tahlilida xatolik: {exc}")
                return

    # ── G. 🎯 VIRAL SMM AGENT ──
    if clean_lower.startswith("/smm") or clean_lower.startswith("/post") or clean_lower.startswith("smm:") or clean_lower.startswith("post:"):
        topic = re.sub(r"^(?:/smm|/post|smm:|post:)[\s:]*", "", clean_text, flags=re.IGNORECASE).strip()
        if not topic and message.reply_to_message:
            topic = message.reply_to_message.text or ""
        if topic:
            wait_m = await message.reply("🎯 **Viral SMM post yaratilmoqda...** Ilgaklar va hashtaglar tanlanmoqda...")
            try:
                smm_post = await ViralSMMAgent.generate_campaign(topic, "Telegram", ai_manager)
                await wait_m.delete()
                for chunk in [smm_post[i:i+4000] for i in range(0, len(smm_post), 4000)]:
                    await message.reply(chunk, parse_mode="Markdown")
                return
            except Exception as exc:
                await wait_m.edit_text(f"❌ SMM yaratishda xatolik: {exc}")
                return

    # ── H. UMUMIY AQLLI AI JAVOBI ──
    replied_context = ""
    if message.reply_to_message:
        r_text = message.reply_to_message.text or message.reply_to_message.caption or ""
        sender_n = message.reply_to_message.from_user.full_name if message.reply_to_message.from_user else "A'zo"
        if r_text:
            replied_context = f"[Mavzu xabari ({sender_n}): '{r_text[:600]}']\n"

    try:
        await bot.send_chat_action(message.chat.id, "typing")
    except Exception:
        pass

    group_title = message.chat.title or "Guruh"
    user_full = message.from_user.full_name if message.from_user else "Foydalanuvchi"

    user_query = f"{replied_context}{clean_text or 'Ushbu mavzuni tushuntirib ber.'}"

    try:
        reply = await ai_manager.generate(
            user_message=user_query,
            save_history=True,
            chat_id=str(message.chat.id),
            user_id=str(message.from_user.id) if message.from_user else "",
            sender_name=user_full,
            chat_type=message.chat.type,
        )
        await safe_message_reply(message, reply, parse_mode="Markdown")
        LogCollector().add(
            action_type="group_ai",
            description=f"Guruh ({group_title}): {clean_text[:35]}",
            model_used="gemini_assistant",
        )
    except Exception as exc:
        logger.error("Guruhda AI javob xatosi: %s", exc)
        await safe_message_reply(message, "⚠️ Savolingizga javob tayyorlashda xatolik yuz berdi. Iltimos, qayta so'rang.", parse_mode=None)


# ─── 3. GURUHDA RASM (MULTIMODAL VISION) BILAN ISHLASH ────────

@router.message(F.chat.type.in_({"group", "supergroup"}), F.photo)
async def handle_group_photo(message: Message, ai_manager: AIManager, bot: Bot) -> None:
    """Guruhda rasm yuborilganda yoki rasmga bot orqali savol berilganda."""
    caption = (message.caption or "").strip()
    bot_user = await bot.get_me()
    bot_mention = f"@{bot_user.username}".lower() if bot_user.username else ""

    # Tekshiruv: rasm tagida bot chaqirilganmi?
    has_bot_call = bool(
        "bot" in caption.lower()
        or (bot_mention and bot_mention in caption.lower())
        or caption.startswith("/")
    )

    if not has_bot_call:
        return

    wait_m = await message.reply("🔍 **Rasm tahlil qilinmoqda (Gemini Vision)...**")
    try:
        photo = message.photo[-1]
        file_obj = await bot.get_file(photo.file_id)
        buf = io.BytesIO()
        await bot.download_file(file_obj.file_path, destination=buf)
        img_bytes = buf.getvalue()

        clean_caption = re.sub(r"\b(?:bot|botjon)\b", "", caption, flags=re.IGNORECASE).strip()
        user_prompt = clean_caption or "Ushbu rasmni batafsil tahlil qiling va unda nimalar aks etganini tushuntiring."

        analysis = await ai_manager.generate_with_image(
            prompt=user_prompt,
            image_bytes=img_bytes,
            mime_type="image/jpeg",
            save_history=True,
            chat_id=str(message.chat.id),
            user_id=str(message.from_user.id) if message.from_user else "",
            sender_name=message.from_user.full_name if message.from_user else "A'zo",
            chat_type=message.chat.type,
        )
        await wait_m.delete()
        await message.reply(analysis, parse_mode="Markdown")
    except Exception as exc:
        logger.error("Guruhda rasm tahlili xatosi: %s", exc)
        await wait_m.edit_text(f"❌ Rasmni tahlil qilishda xatolik: {exc}")


# ─── 4. GURUHDA HUJJAT BILAN ISHLASH ──────────────────────────

@router.message(F.chat.type.in_({"group", "supergroup"}), F.document)
async def handle_group_document(message: Message, ai_manager: AIManager, bot: Bot) -> None:
    """Guruhda shartnoma yoki hujjat (.pdf, .docx, .txt) yuborilganda audit qilish."""
    caption = (message.caption or "").strip().lower()
    doc = message.document
    if not doc:
        return

    # Agar captionda bot yoki shartnoma / tekshir bo'lsa
    if not any(k in caption for k in ["bot", "tekshir", "shartnoma", "doc", "audit", "tahlil"]):
        return

    file_name = doc.file_name or "hujjat"
    wait_m = await message.reply(f"📄 **'{file_name}' hujjati tahlil qilinmoqda...**")
    try:
        file_obj = await bot.get_file(doc.file_id)
        buf = io.BytesIO()
        await bot.download_file(file_obj.file_path, destination=buf)
        content_bytes = buf.getvalue()

        # Matn ajratib olish
        extracted_text = ""
        if file_name.endswith(".txt") or file_name.endswith(".md"):
            extracted_text = content_bytes.decode("utf-8", errors="ignore")
        elif file_name.endswith(".pdf"):
            try:
                import pypdf
                pdf_reader = pypdf.PdfReader(io.BytesIO(content_bytes))
                pages_text = [p.extract_text() or "" for p in pdf_reader.pages[:15]]
                extracted_text = "\n".join(pages_text)
            except Exception:
                extracted_text = content_bytes[:4000].decode("utf-8", errors="ignore")
        elif file_name.endswith(".docx"):
            try:
                import docx
                doc_obj = docx.Document(io.BytesIO(content_bytes))
                extracted_text = "\n".join([p.text for p in doc_obj.paragraphs])
            except Exception:
                extracted_text = content_bytes[:4000].decode("utf-8", errors="ignore")
        else:
            extracted_text = content_bytes[:4000].decode("utf-8", errors="ignore")

        if not extracted_text.strip():
            await wait_m.edit_text("⚠️ Hujjatdan matn ajratib bo'lmadi.")
            return

        analysis = await DocumentContractAgent.analyze_contract(extracted_text[:12000], ai_manager)
        await wait_m.delete()
        for chunk in [analysis[i:i+4000] for i in range(0, len(analysis), 4000)]:
            await message.reply(chunk, parse_mode="Markdown")
    except Exception as exc:
        logger.error("Guruhda hujjat tahlili xatosi: %s", exc)
        await wait_m.edit_text(f"❌ Hujjat tahlilida xatolik: {exc}")


# ─── 5. KANALDA POSTLARGA AVTOMATIK JAVOB (CHANNEL AUTOPILOT) ─

@router.channel_post(F.text)
async def handle_channel_post(message: Message, ai_manager: AIManager, bot: Bot) -> None:
    """
    Kanalga yangi post chiqarilganda avtomatik tahlil va javob yuborish.
    """
    raw_text = (message.text or "").strip()
    if not raw_text:
        return

    # Kanalni bazada yangilash
    await db.add_or_update_managed_chat(
        chat_id=message.chat.id,
        title=message.chat.title or "Kanal",
        chat_type="channel",
        username=message.chat.username or "",
    )

    bot_user = await bot.get_me()
    bot_mention = f"@{bot_user.username}".lower() if bot_user.username else ""
    text_lower = raw_text.lower()

    # Triggerlar
    has_bot_call = bool(
        bot_mention in text_lower
        or re.search(r"^(?:bot|/ai|/bot|/ask|ai:)[\s,:!-]+", text_lower)
        or "#ai" in text_lower
        or "#bot" in text_lower
    )
    is_question = raw_text.endswith("?") or text_lower.startswith("savol:")
    is_summary = "#xulosa" in text_lower or text_lower.startswith("xulosa:") or "#tahlil" in text_lower
    is_fact_check = "#fakt" in text_lower or text_lower.startswith("fakt:")
    is_image_request = bool(re.search(r"(?:#rasm|#draw|/draw|/imagine|/flux|rasm\s+chiz|chizib\s+ber)", text_lower))

    if not (has_bot_call or is_question or is_summary or is_fact_check or is_image_request):
        return

    clean_text = re.sub(r"^(?:bot|/ai|/bot|/ask|ai:|#ai|#bot|#xulosa|#tahlil|#fakt|#rasm|#draw|/draw|/imagine|/flux|rasm\s+chiz:|chiz:|xulosa:|fakt:|savol:)[\s,:!-]+", "", raw_text, flags=re.IGNORECASE).strip()

    # Agar kanalda rasm so'ralgan bo'lsa
    if is_image_request:
        p_query = clean_text or raw_text
        try:
            await bot.send_chat_action(message.chat.id, "upload_photo")
            img_bytes, enhanced_p, ar, seed, *_ = await draw_midjourney_image(raw_prompt=p_query, ai_manager=ai_manager, enhance=True)
            if img_bytes:
                photo_file = BufferedInputFile(file=img_bytes, filename=f"channel_flux_{uuid.uuid4().hex[:6]}.jpg")
                caption = (
                    f"🎨 <b>FLUX.1 Badiiy Asari:</b>\n\n"
                    f"📝 <i>{html.escape(p_query)}</i>\n\n"
                    f"🤖 <b>Super-Agent Studio</b>"
                )
                await message.reply_photo(photo=photo_file, caption=caption, parse_mode="HTML")
                return
        except Exception as img_err:
            logger.error("Kanalda rasm chizish xatosi: %s", img_err)
            return

    try:
        await bot.send_chat_action(message.chat.id, "typing")
    except Exception:
        pass

    if is_summary:
        prompt = f"Kanal posti: '{clean_text or raw_text}'.\n\nUshbu post bo'yicha 3 ta eng muhim tezis-xulosa va 4 ta ommabop hashtag tuzib ber (o'zbek tilida)."
        header = "💡 **AI Xulosasi va Tezislar:**\n\n"
    elif is_fact_check:
        prompt = f"Kanal posti: '{clean_text or raw_text}'.\n\nUshbu faktni tahlil qiling va obunachilar uchun qisqa izoh bering (o'zbek tilida)."
        header = "🔍 **AI Fakt Tahlili:**\n\n"
    else:
        prompt = f"Telegram kanalida savol/post berildi: '{clean_text or raw_text}'.\n\nObunachilar uchun professional, aniq va qiziqarli sharh yozib ber (o'zbek tilida)."
        header = "🤖 **Super-Agent Tahlili:**\n\n"

    try:
        channel_title = message.chat.title or "Kanal"
        chat_id_str = str(message.chat.id)
        ai_reply = await ai_manager.generate(
            prompt,
            save_history=True,
            chat_id=chat_id_str,
            sender_name=channel_title,
            chat_type="channel",
        )
        await safe_message_reply(message=message, text=f"{header}{ai_reply}", parse_mode="Markdown")
        LogCollector().add(
            action_type="channel_ai",
            description=f"Kanal ({message.chat.title}): {raw_text[:35]}",
            model_used="gemini_assistant",
        )
    except Exception as exc:
        logger.error("Kanal postida AI javob xatosi: %s", exc)

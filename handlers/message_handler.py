"""
handlers/message_handler.py — Matnli Xabarlar Handler (Kengaytirilgan Smart Userbot)

Imkoniyatlar:
1. Oddiy matn → AI orqali tezkor va erkin javob (Gemini + OpenRouter Fallback)
2. Nom bo'yicha shaxsiy xabar yuborish (Username bo'lmagan tanishlarga ham: "Ali ga salom deb yoz")
3. Guruh va kanallarga post/xabar chiqarish ("post: IT Guruh Salom hammaga")
4. Guruh yoki kanalni AI bilan tahlil qilish ("guruhni tekshir: IT Guruh")
5. Shaxsiy Telegram akkauntini to'liq AI tahlili ("telegram tekshir", "kim yozdi")
6. Xavfsizlik: begonalarni rad etish, bir nechta odam topilsa tanlov tugmasi
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Optional

from aiogram import Router, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    BufferedInputFile,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import ADMIN_ID, GEMINI_MODEL
from core.ai_manager import AIManager
from core.database import db
from core.safe_send import safe_send_message, safe_message_answer, safe_edit_text
from core.inbox_triage import send_draft_reply, remove_pending_draft
from core.web_scraper import analyze_url_and_generate_post
from core.userbot import (
    send_message_smart,
    post_to_group_or_channel_smart,
    post_to_channel_or_chat,
    summarize_target_chat,
    summarize_telegram_activity,
    get_dialogs,
)
from core.search_agent import search_image_url, answer_with_web_search, download_image_bytes
from core.reminder_manager import parse_reminder_smart
from core.midjourney_agent import draw_midjourney_image, generate_free_midjourney_image
from core.hermes_agent import run_hermes_agent
from services.scheduler import LogCollector
from handlers.email_handler import handle_email_text_command

logger = logging.getLogger(__name__)
router = Router(name="message")

ADMIN_FILTER = F.from_user.id == ADMIN_ID
NOT_ADMIN_FILTER = F.from_user.id != ADMIN_ID

# Kutilayotgan postlar, tanlovlar va Midjourney vazifalari xotirasi
_pending_posts: dict[int, tuple[str, str]] = {}
_pending_smart_sends: dict[str, str] = {}  # draft_id -> message_text
_mj_tasks: dict[str, dict] = {}  # task_id -> {"prompt": str, "enhanced": str, "ar": str, "seed": int}


# ─── Boshqalar uchun Rad Etish ────────────────────────────────

@router.message(F.chat.type == "private", NOT_ADMIN_FILTER)
async def reject_unauthorized(message: Message) -> None:
    logger.warning(
        "Ruxsatsiz kirish urinishi: user_id=%s, username=%s",
        message.from_user.id,
        message.from_user.username,
    )
    text = (
        f"⛔ **Xavfsizlik Cheklovi:**\n"
        f"Bu bot faqat uning egasi uchun shaxsiy rejimda ishlaydi.\n\n"
        f"👤 Sizning Telegram ID: `{message.from_user.id}`\n\n"
        f"💡 Agar bu siz bo'lsangiz, botga to'liq egalik qilish uchun `.env` faylingizda:\n"
        f"`ADMIN_ID={message.from_user.id}` deb yozing va botni qayta yoqing!"
    )
    await message.answer(text, parse_mode="Markdown")


# ─── Moslashuvchan Qidiruv va Buyruq Patternlari ──────────────

# 1. Boshqalarga xabar yuborish (Ism yoki Username bo'yicha)
_SEND_PATTERNS = [
    re.compile(r"^(?:yoz|yubor)\s+([@\w\d_\s\.\+\-]+?)\s*[:,-]\s*(.+)$", re.IGNORECASE | re.DOTALL),
    re.compile(r"^([@\w\d_\s\.\+\-]+?)\s*ga\s*(?:yoz|yubor)\s*[:,-]?\s*(.+)$", re.IGNORECASE | re.DOTALL),
    re.compile(r"^([@\w\d_\s\.\+\-]+?)\s*ga\s+(.+?)\s+deb\s+(?:yoz|yubor)$", re.IGNORECASE | re.DOTALL),
]

# 2. Guruh yoki kanalni AI bilan tahlil qilish
_CHAT_SUMMARY_PATTERN = re.compile(
    r"^(?:guruhni\s+tekshir|kanalni\s+tekshir|guruh\s+xulosasi|chat\s+tahlil)[:\s]+([@\w\d_\s\.\-]+)$",
    re.IGNORECASE,
)


def _match_send_command(text: str) -> Optional[tuple[str, str]]:
    for pattern in _SEND_PATTERNS:
        m = pattern.match(text)
        if m:
            return m.group(1).strip(), m.group(2).strip()
    return None


def parse_post_command(text: str) -> Optional[tuple[str, str]]:
    """
    Kanalga post chiqarish buyrug'ini tahlil qiladi.
    Formatlar:
    1. /post [matn]  yoki  /post @kanal [matn]
    2. post: [matn]  yoki  post: @kanal [matn]
    3. kanalga yoz: [matn]  yoki  kanalga yoz @kanal: [matn]
    4. kanalimga yoz: [matn]
    5. kanalga: [matn]
    6. guruhga yoz: [nomi] [matn]
    """
    from config import LOG_CHANNEL_ID
    t = (text or "").strip()

    # 1. /post buyrug'i
    if t.lower().startswith("/post"):
        rest = t[5:].strip()
        if not rest:
            return None
        parts = rest.split(maxsplit=1)
        if parts[0].startswith("@") or parts[0].startswith("-100") or (parts[0].lstrip("-").isdigit() and len(parts[0]) > 8):
            target = parts[0]
            post_text = parts[1] if len(parts) > 1 else ""
        else:
            target = str(LOG_CHANNEL_ID) if LOG_CHANNEL_ID else "default"
            post_text = rest
        return target, post_text

    # 2. Prefikslar
    prefix_pattern = r"^(?:post|kanalga\s+yoz|kanalimga\s+yoz|kanalga|kanalimga|guruhga\s+yoz)[:\s]+"
    m = re.match(prefix_pattern, t, re.IGNORECASE)
    if not m:
        return None

    rest = t[m.end():].strip()
    if not rest:
        return None

    # Birinchi so'z target bo'lishi mumkinmi?
    parts = rest.split(maxsplit=1)
    first_token = parts[0].rstrip(":,")
    if first_token.startswith("@") or first_token.startswith("-100") or (first_token.lstrip("-").isdigit() and len(first_token) > 8):
        target = first_token
        post_text = parts[1].strip() if len(parts) > 1 else ""
    elif len(parts) > 1 and parts[1].strip():
        if "guruh" in t[:m.end()].lower():
            target = first_token
            post_text = parts[1].strip()
        elif LOG_CHANNEL_ID:
            target = str(LOG_CHANNEL_ID)
            post_text = rest
        else:
            target = first_token
            post_text = parts[1].strip()
    else:
        target = str(LOG_CHANNEL_ID) if LOG_CHANNEL_ID else "default"
        post_text = rest

    if not post_text:
        return None

    return target, post_text


# ─── Guruh / Kanal Postini Tasdiqlash ────────────────────────

@router.message(ADMIN_FILTER, lambda msg: parse_post_command(msg.text or "") is not None)
async def handle_post_to_channel_or_group(message: Message) -> None:
    res = parse_post_command(message.text or "")
    if not res:
        return

    target, post_text = res

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="✅ E'lon qilish",
            callback_data=f"confirm_post:{message.message_id}",
        ),
        InlineKeyboardButton(
            text="❌ Bekor qilish",
            callback_data=f"cancel_post:{message.message_id}",
        ),
    )

    preview = (
        f"📢 **Guruh/Kanalga Post Tasdig'i**\n"
        f"{'─' * 30}\n"
        f"🎯 Manzil: `{target}`\n\n"
        f"{post_text}\n"
        f"{'─' * 30}\n"
        f"E'lon qilinsinmi?"
    )

    confirm_msg = await message.answer(preview, reply_markup=builder.as_markup(), parse_mode="Markdown")
    _pending_posts[confirm_msg.message_id] = (target, post_text)


@router.callback_query(ADMIN_FILTER, F.data.startswith("confirm_post:"))
async def cb_confirm_post(cb: CallbackQuery) -> None:
    await cb.answer()
    msg_id = cb.message.message_id
    if msg_id not in _pending_posts:
        await cb.answer("⚠️ Post ma'lumoti eskirgan", show_alert=True)
        return

    target, post_text = _pending_posts.pop(msg_id)
    await cb.message.edit_text(f"📡 `{target}` ga post e'lon qilinmoqda...", parse_mode="Markdown")

    result = await post_to_channel_or_chat(cb.bot, target, post_text)
    await cb.message.edit_text(result, parse_mode="Markdown")

    LogCollector().add(
        action_type="post",
        description=f"{target} ga post: {post_text[:40]}",
        model_used="bot_channel",
    )


@router.callback_query(ADMIN_FILTER, F.data.startswith("cancel_post:"))
async def cb_cancel_post(cb: CallbackQuery) -> None:
    msg_id = cb.message.message_id
    _pending_posts.pop(msg_id, None)
    await cb.message.edit_text("❌ Post bekor qilindi.")
    await cb.answer("Bekor qilindi")


# ─── Nomzodlar Tanlanganda Xabar Yuborish ────────────────────

@router.callback_query(ADMIN_FILTER, F.data.startswith("smart_send:"))
async def cb_smart_send_choice(cb: CallbackQuery) -> None:
    parts = cb.data.split(":")
    if len(parts) < 3:
        return
    entity_id = int(parts[1])
    draft_id = parts[2]

    message_text = _pending_smart_sends.pop(draft_id, None)
    if not message_text:
        await cb.answer("⚠️ Xabar matni topilmadi (qaytadan yozing)", show_alert=True)
        return

    await cb.answer("📤 Xabar yuborilmoqda...")
    await cb.message.edit_text(f"📡 `{entity_id}` ga xabar yuborilmoqda...", parse_mode="Markdown")

    success, result_text, _ = await send_message_smart(str(entity_id), message_text)
    await cb.message.edit_text(result_text, parse_mode="Markdown")


# ─── Inbox Triage Draft Javoblarni Yuborish ───────────────────

@router.callback_query(ADMIN_FILTER, F.data.startswith("send_draft:"))
async def cb_send_inbox_draft(cb: CallbackQuery) -> None:
    draft_id = cb.data.replace("send_draft:", "")
    from core.userbot import userbot
    client = userbot.get_client()
    if not client or not client.is_connected():
        await cb.answer("❌ Userbot ulanmagan!", show_alert=True)
        return

    await cb.answer("📤 Userbot orqali yuborilmoqda...")
    await cb.message.edit_text("📡 Javob yuborilmoqda...")
    ok, res_text = await send_draft_reply(client, draft_id)
    await cb.message.edit_text(res_text, parse_mode="Markdown")


@router.callback_query(ADMIN_FILTER, F.data.startswith("dismiss_draft:"))
async def cb_dismiss_inbox_draft(cb: CallbackQuery) -> None:
    draft_id = cb.data.replace("dismiss_draft:", "")
    remove_pending_draft(draft_id)
    await cb.message.edit_text("❌ Qoralama xabar bekor qilindi.")
# ─── Midjourney Boshqaruvi (Qayta chizish / O'lcham) ─────────

@router.callback_query(ADMIN_FILTER, F.data.startswith("mj:"))
async def cb_midjourney_action(cb: CallbackQuery, ai_manager: AIManager) -> None:
    await cb.answer("🎨 Midjourney ishlamoqda...")
    parts = cb.data.split(":")
    action = parts[1] if len(parts) > 1 else ""

    import random
    if action in ("redraw", "seed"):
        task_id = parts[2] if len(parts) > 2 else ""
        task_data = _mj_tasks.get(task_id)
        if not task_data:
            await cb.answer("⚠️ Rasm ma'lumoti eskirgan. Yangi buyruq yozing.", show_alert=True)
            return

        prompt = task_data["prompt"]
        ar = task_data.get("ar", "1:1")
        new_seed = random.randint(100000, 99999999)
        enhanced = task_data.get("enhanced", prompt)

        img_bytes = await generate_free_midjourney_image(enhanced, aspect_ratio=ar, seed=new_seed)
        if not img_bytes:
            await cb.answer("❌ Qayta chizishda xatolik bo'ldi.", show_alert=True)
            return

        new_task_id = uuid.uuid4().hex[:8]
        _mj_tasks[new_task_id] = {"prompt": prompt, "enhanced": enhanced, "ar": ar, "seed": new_seed}

        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(text="🔄 Qaytadan chizish", callback_data=f"mj:redraw:{new_task_id}"),
            InlineKeyboardButton(text="🎲 Yangi Seed", callback_data=f"mj:seed:{new_task_id}"),
        )
        builder.row(
            InlineKeyboardButton(text="📐 16:9", callback_data=f"mj:ar:16:9:{new_task_id}"),
            InlineKeyboardButton(text="📐 1:1", callback_data=f"mj:ar:1:1:{new_task_id}"),
            InlineKeyboardButton(text="📐 9:16", callback_data=f"mj:ar:9:16:{new_task_id}"),
        )

        input_file = BufferedInputFile(file=img_bytes, filename=f"mj_{new_task_id}.jpg")
        caption = (
            f"🎨 **Midjourney v6 Asari**\n\n"
            f"📝 **So'rov:** _{prompt}_\n"
            f"✨ **Midjourney Prompt:** _{enhanced[:200]}..._\n"
            f"📐 O'lcham: `{ar}` | 🎲 Seed: `{new_seed}`"
        )
        try:
            await cb.message.delete()
        except Exception:
            pass
        await cb.message.answer_photo(photo=input_file, caption=caption, reply_markup=builder.as_markup(), parse_mode="Markdown")

    elif action == "ar":
        if len(parts) < 4:
            return
        new_ar = parts[2]
        task_id = parts[3]
        task_data = _mj_tasks.get(task_id)
        if not task_data:
            await cb.answer("⚠️ Rasm ma'lumoti eskirgan. Yangi buyruq yozing.", show_alert=True)
            return

        prompt = task_data["prompt"]
        seed = task_data.get("seed", random.randint(100000, 99999999))
        enhanced = task_data.get("enhanced", prompt)

        img_bytes = await generate_free_midjourney_image(enhanced, aspect_ratio=new_ar, seed=seed)
        if not img_bytes:
            await cb.answer("❌ O'lchamni o'zgartirishda xatolik.", show_alert=True)
            return

        new_task_id = uuid.uuid4().hex[:8]
        _mj_tasks[new_task_id] = {"prompt": prompt, "enhanced": enhanced, "ar": new_ar, "seed": seed}

        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(text="🔄 Qaytadan chizish", callback_data=f"mj:redraw:{new_task_id}"),
            InlineKeyboardButton(text="🎲 Yangi Seed", callback_data=f"mj:seed:{new_task_id}"),
        )
        builder.row(
            InlineKeyboardButton(text="📐 16:9", callback_data=f"mj:ar:16:9:{new_task_id}"),
            InlineKeyboardButton(text="📐 1:1", callback_data=f"mj:ar:1:1:{new_task_id}"),
            InlineKeyboardButton(text="📐 9:16", callback_data=f"mj:ar:9:16:{new_task_id}"),
        )

        input_file = BufferedInputFile(file=img_bytes, filename=f"mj_{new_task_id}.jpg")
        caption = (
            f"🎨 **Midjourney v6 Asari (Yangi O'lcham)**\n\n"
            f"📝 **So'rov:** _{prompt}_\n"
            f"✨ **Midjourney Prompt:** _{enhanced[:200]}..._\n"
            f"📐 O'lcham: `{new_ar}` | 🎲 Seed: `{seed}`"
        )
        try:
            await cb.message.delete()
        except Exception:
            pass
        await cb.message.answer_photo(photo=input_file, caption=caption, reply_markup=builder.as_markup(), parse_mode="Markdown")


# ─── Eslatmalar Callbacks ──────────────────────────────────────

@router.callback_query(ADMIN_FILTER, F.data.startswith("done_rem:"))
async def cb_done_reminder(cb: CallbackQuery) -> None:
    await cb.answer("✅ Bajarildi deb belgilandi")
    rem_id = int(cb.data.replace("done_rem:", ""))
    await db.mark_reminder_sent(rem_id)
    await cb.message.edit_text("✅ **Vazifa bajarildi deb belgilandi!**", parse_mode="Markdown")


@router.callback_query(ADMIN_FILTER, F.data.startswith("snooze_rem:"))
async def cb_snooze_reminder(cb: CallbackQuery) -> None:
    parts = cb.data.split(":")
    rem_id = int(parts[1])
    minutes = int(parts[2]) if len(parts) > 2 else 10
    new_time = await db.snooze_reminder(rem_id, minutes)
    await cb.answer(f"⏰ {minutes} daqiqaga kechiktirildi")
    await cb.message.edit_text(
        f"⏳ **Eslatma {minutes} daqiqaga kechiktirildi.**\n"
        f"🕒 Yangi eslatish vaqti: `{new_time}`",
        parse_mode="Markdown",
    )


@router.callback_query(ADMIN_FILTER, F.data.startswith("del_rem:"))
async def cb_delete_reminder(cb: CallbackQuery) -> None:
    await cb.answer("Bekor qilindi")
    rem_id = int(cb.data.replace("del_rem:", ""))
    await db.delete_reminder(rem_id)
    await cb.message.edit_text("❌ **Eslatma bekor qilindi.**", parse_mode="Markdown")


# ─── Suhbatlar Ro'yxati ───────────────────────────────────────

@router.message(ADMIN_FILTER, F.text.lower() == "suhbatlar")
async def handle_dialogs(message: Message) -> None:
    wait_msg = await message.answer("📋 Suhbatlar yuklanmoqda...")
    result = await get_dialogs(limit=20)
    await wait_msg.edit_text(result, parse_mode="Markdown")


# ─── Asosiy Xabarlar va AI Muloqot ───────────────────────────

@router.message(ADMIN_FILTER, F.text)
async def handle_ai_chat(message: Message, ai_manager: AIManager) -> None:
    user_text = message.text.strip()
    await db.log_event("user_msg", user_text[:80])

    # 1. Email buyruqlarini tekshirish
    if await handle_email_text_command(message, ai_manager):
        return

    # 2. Veb-Havola (URL) Tahlili va Kanal Posti Generatori
    url_match = re.search(r"https?://[^\s]+", user_text)
    if url_match and (len(user_text) < 150 or "post" in user_text.lower() or "tahlil" in user_text.lower() or "tezis" in user_text.lower()):
        target_url = url_match.group(0)
        wait_msg = await message.answer(f"🌐 `{target_url}` sahifasi yuklanib, 3 ta asosiy tezis va kanal posti tayyorlanmoqda...", parse_mode="Markdown")
        analysis = await analyze_url_and_generate_post(target_url, ai_manager)
        await wait_msg.edit_text(analysis[:4000], parse_mode="Markdown")
        return

    # 2.1 Eslatmalar Ro'yxati va Boshqaruvi
    if user_text.lower() in ("/reminders", "eslatmalar", "eslatmalarim", "rejalashtirilgan eslatmalar"):
        active = await db.get_active_reminders(message.chat.id)
        if not active:
            await message.answer(
                "⏰ **Faol eslatmalar yo'q.**\n"
                "Eslatma qo'shish uchun: `21:30 da bot orqali menga eslat: dori ichish` yoki `15 daqiqadan keyin eslat: choy damlash` deb yozing!",
                parse_mode="Markdown",
            )
            return

        lines = ["⏰ **Faol Eslatmalar Ro'yxati:**\n"]
        builder = InlineKeyboardBuilder()
        for r in active:
            lines.append(f"• `#{r['id']}` [{r['remind_at']}] {r['text']}")
            builder.row(InlineKeyboardButton(text=f"❌ #{r['id']} ni o'chirish", callback_data=f"del_rem:{r['id']}"))
        lines.append("\nO'chirish uchun kerakli tugmani bosing.")
        await message.answer("\n".join(lines), reply_markup=builder.as_markup(), parse_mode="Markdown")
        return

    if user_text.lower().startswith("/del_rem ") or user_text.lower().startswith("/delrem "):
        try:
            r_id = int(user_text.split()[-1])
            await db.delete_reminder(r_id)
            await message.answer(f"🗑 `#{r_id}` eslatma bekor qilindi.", parse_mode="Markdown")
        except Exception:
            await message.answer("❌ Noto'g'ri ID. Masalan: `/del_rem 1`", parse_mode="Markdown")
        return

    # 2.2 Aqlli Eslatma O'rnatish (Natural Language Parsing + AI)
    if any(w in user_text.lower() for w in ["eslat", "remind", "eslatma", "eslatgin", "eslatib"]):
        # Tekshiramiz: bu eslatma so'rovi bo'lishi mumkinmi
        rem_res = await parse_reminder_smart(user_text, ai_manager)
        if rem_res:
            rem_time, rem_task = rem_res
            rem_id = await db.add_reminder(message.chat.id, rem_task, rem_time)
            builder = InlineKeyboardBuilder()
            builder.row(InlineKeyboardButton(text="❌ Bekor qilish", callback_data=f"del_rem:{rem_id}"))
            await message.answer(
                f"⏰ **Eslatma muvaffaqiyatli saqlandi!**\n\n"
                f"📝 **Vazifa:** {rem_task}\n"
                f"🕒 **Eslatish vaqti:** `{rem_time}` (Toshkent vaqti)\n\n"
                f"ID: `#{rem_id}` — Belgilangan vaqtda bot sizga signal yuboradi.",
                reply_markup=builder.as_markup(),
                parse_mode="Markdown",
            )
            LogCollector().add(
                action_type="reminder_set",
                description=f"#{rem_id}: {rem_time} - {rem_task[:30]}",
                model_used="reminder_engine",
            )
            return

    # 3. Shaxsiy Ma'lumotlar Bazasi (Knowledge Base / Long-term Memory)
    if user_text.lower() in ("/memory", "/kb", "xotira", "bilimlar bazasi"):
        facts = await db.get_all_facts()
        if not facts:
            await message.answer(
                "🧠 **Doimiy Xotira Bo'sh.**\n"
                "Fakt qo'shish uchun: `Eslab qol: Karta raqamim: 8600 1234...` yoki `/remember kalit: matn` deb yozing!",
                parse_mode="Markdown",
            )
            return

        lines = ["🧠 **Foydalanuvchining Doimiy Bilimlar Bazasi (Memory):**\n"]
        for f in facts:
            lines.append(f"• `{f.get('key')}`: {f.get('content')}")
        lines.append("\n💡 /clear qilinsa ham agent ushbu ma'lumotlarni doim eslab qoladi!")
        await message.answer("\n".join(lines), parse_mode="Markdown")
        return

    # Fakt saqlash buyruqlari
    remember_match = re.match(r"^(?:/remember|eslab\s+qol|fakt\s+saqla|mening\s+kartam)[:\s]+(.+)$", user_text, re.IGNORECASE)
    if remember_match:
        content_to_save = remember_match.group(1).strip()
        # Kalit ajratish
        if ":" in content_to_save:
            f_key, f_val = content_to_save.split(":", 1)
        else:
            f_key = f"fact_{str(uuid.uuid4())[:6]}"
            f_val = content_to_save

        await db.save_fact(f_key.strip().lower(), f_val.strip())
        await message.answer(
            f"✅ **Doimiy xotiraga saqlandi!**\n"
            f"Kalit: `{f_key.strip().lower()}`\n"
            f"Mazmun: `{f_val.strip()}`\n\n"
            f"Bot endi barcha suhbatlarda ushbu faktni inobatga oladi.",
            parse_mode="Markdown",
        )
        return

    # Fakt o'chirish
    if user_text.lower().startswith("/forget "):
        key_to_del = user_text.split(" ", 1)[1].strip()
        await db.delete_fact(key_to_del)
        await message.answer(f"🗑 `{key_to_del}` kaliti doimiy xotiradan o'chirildi.", parse_mode="Markdown")
        return

    # 4. Raqobatchilar Tahlili Buyrug'i
    if user_text.lower() in ("/competitors", "raqobatchilar", "raqobatchilar tahlili"):
        comps = await db.get_competitors()
        if not comps:
            await message.answer(
                "📡 **Kuzatilayotgan raqobatchi kanallar mavjud emas.**\n"
                "Qo'shish uchun: `/add_competitor @kanal_nomi` deb yozing!",
                parse_mode="Markdown",
            )
            return

        wait_msg = await message.answer(f"🔍 {len(comps)} ta raqobatchi kanaldan yangi trendlar tahlil qilinmoqda...")
        report_lines = ["📊 **Raqobatchi Kanallar Monitori:**\n"]
        for c in comps:
            report_lines.append(f"• @{c}")
        report_lines.append("\nKunlik trendlar avtomatik rezyume qilib boriladi.")
        await wait_msg.edit_text("\n".join(report_lines), parse_mode="Markdown")
        return

    if user_text.lower().startswith("/add_competitor "):
        comp_name = user_text.split(" ", 1)[1].strip()
        await db.add_competitor(comp_name)
        await message.answer(f"✅ `@{comp_name.lstrip('@')}` raqobatchilar ro'yxatiga qo'shildi!", parse_mode="Markdown")
        return

    if user_text.lower().startswith("/remove_competitor "):
        comp_name = user_text.split(" ", 1)[1].strip()
        await db.remove_competitor(comp_name)
        await message.answer(f"🗑 `@{comp_name.lstrip('@')}` raqobatchilar ro'yxatidan o'chirildi.", parse_mode="Markdown")
        return

    # 5. Taymerli (Kechiktirilgan) Post Rejalashtirish
    schedule_match = re.match(
        r"^(?:rejalashtir|post\s+rejalashtir)[:\s]+([@\w\d_\s\.\-]+?)\s+(?:vaqt[:=]\s*)?(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})\s+(?:matn[:=]\s*)?(.+)$",
        user_text,
        re.IGNORECASE | re.DOTALL,
    )
    if schedule_match:
        target_ch = schedule_match.group(1).strip()
        sched_time = schedule_match.group(2).strip() + ":00"
        post_content = schedule_match.group(3).strip()

        post_id = await db.add_scheduled_post(target_ch, post_content, sched_time)
        await message.answer(
            f"⏰ **Post muvaffaqiyatli rejalashtirildi!**\n\n"
            f"📌 Manzil: `{target_ch}`\n"
            f"🕒 Vaqt: `{sched_time}`\n"
            f"📝 Matn:\n_{post_content}_\n\n"
            f"ID: `#{post_id}` (Vaqti kelganda avtomatik e'lon qilinadi)",
            parse_mode="Markdown",
        )
        return

    # 6. Guruh yoki kanalni AI bilan tekshirish ("guruhni tekshir: Nomi")
    chat_sum_match = _CHAT_SUMMARY_PATTERN.match(user_text)
    if chat_sum_match:
        target_chat = chat_sum_match.group(1).strip()
        wait_msg = await message.answer(f"⏳ `{target_chat}` guruhidagi so'nggi xabarlar yuklanib, AI tahlil qilinmoqda...")
        summary = await summarize_target_chat(target_chat, ai_manager, limit=30)
        await safe_edit_text(wait_msg, summary, parse_mode="Markdown")
        return

    # 3. Shaxsiy Telegram akkauntini to'liq tekshirish
    tg_check_phrases = [
        "telegram tekshir",
        "telegramimni tekshir",
        "telegram xulosasi",
        "kim yozdi",
        "xabarlarimni tekshir",
        "telegram",
        "/tg",
    ]
    if user_text.lower() in tg_check_phrases or any(user_text.lower().startswith(p) for p in ["telegram tekshir", "telegramimni tekshir"]):
        wait_msg = await message.answer("⏳ Telegram akkauntingizdagi so'nggi xabarlar tahlil qilinmoqda...")
        summary = await summarize_telegram_activity(ai_manager)
        await safe_edit_text(wait_msg, summary, parse_mode="Markdown")
        return

    # 4. Ism / Username / ID bo'yicha boshqalarga aqlli xabar yuborish
    send_match = _match_send_command(user_text)
    if send_match:
        target, text_to_send = send_match
        wait_msg = await message.answer(f"📡 `{target}` qidirilmoqda va xabar yuborilmoqda...", parse_mode="Markdown")
        
        success, result_text, candidates = await send_message_smart(target, text_to_send)

        if success or not candidates:
            # Aniq bitta odamga yuborildi yoki topilmadi
            await safe_edit_text(wait_msg, result_text, parse_mode="Markdown")
            if success:
                LogCollector().add(
                    action_type="userbot",
                    description=f"{target} ga: {text_to_send[:40]}",
                    model_used="userbot",
                )
            return

        # Bir nechta nomzod topilsa -> tanlash tugmalari
        draft_id = str(uuid.uuid4())[:8]
        _pending_smart_sends[draft_id] = text_to_send

        builder = InlineKeyboardBuilder()
        for cand in candidates:
            btn_title = f"{cand['name']} {cand['username']}"[:30]
            builder.row(InlineKeyboardButton(text=btn_title, callback_data=f"smart_send:{cand['id']}:{draft_id}"))

        await safe_edit_text(wait_msg, result_text, reply_markup=builder.as_markup(), parse_mode="Markdown")
        return

    # 4.1 Midjourney v6 AI Rasm Chizish Skilli (/imagine, /midjourney, chiz:, rasm chiz:)
    mj_match = re.match(r"^(?:/imagine|/midjourney|chiz|rasm\s+chiz|rasm\s+yarat|chizib\s+ber|draw)[:\s]+(.+)$", user_text, re.IGNORECASE | re.DOTALL)
    if mj_match:
        raw_prompt = mj_match.group(1).strip()
        if raw_prompt:
            wait_msg = await message.answer(
                "🎨 **Midjourney v6 rasm chizmoqda...**\n\n"
                "✨ Prompt AI tomonidan kinoxit darajasiga boyitilmoqda va fotorealistik ishlanmoqda..."
            )
            await message.bot.send_chat_action(message.chat.id, "upload_photo")
            img_bytes, enhanced_prompt, ar, seed = await draw_midjourney_image(
                raw_prompt=raw_prompt,
                ai_manager=ai_manager,
                enhance=True,
            )
            if img_bytes:
                task_id = uuid.uuid4().hex[:8]
                _mj_tasks[task_id] = {
                    "prompt": raw_prompt,
                    "enhanced": enhanced_prompt,
                    "ar": ar,
                    "seed": seed,
                }
                builder = InlineKeyboardBuilder()
                builder.row(
                    InlineKeyboardButton(text="🔄 Qaytadan chizish", callback_data=f"mj:redraw:{task_id}"),
                    InlineKeyboardButton(text="🎲 Yangi Seed", callback_data=f"mj:seed:{task_id}"),
                )
                builder.row(
                    InlineKeyboardButton(text="📐 16:9", callback_data=f"mj:ar:16:9:{task_id}"),
                    InlineKeyboardButton(text="📐 1:1", callback_data=f"mj:ar:1:1:{task_id}"),
                    InlineKeyboardButton(text="📐 9:16", callback_data=f"mj:ar:9:16:{task_id}"),
                )
                input_file = BufferedInputFile(file=img_bytes, filename=f"mj_{task_id}.jpg")
                caption = (
                    f"🎨 **Midjourney v6 Badiiy Asari:**\n\n"
                    f"📝 **Asl so'rov:** _{raw_prompt}_\n"
                    f"✨ **Midjourney Prompt:** _{enhanced_prompt[:250]}..._\n"
                    f"📐 O'lcham: `{ar}` | 🎲 Seed: `{seed}`"
                )
                await wait_msg.delete()
                await message.answer_photo(
                    photo=input_file,
                    caption=caption,
                    reply_markup=builder.as_markup(),
                    parse_mode="Markdown",
                )
                LogCollector().add(
                    action_type="midjourney_image",
                    description=f"Midjourney: {raw_prompt[:40]}",
                    model_used="midjourney_v6",
                )
                return
            else:
                await safe_edit_text(wait_msg, "❌ Rasm chizishda xatolik yuz berdi. Iltimos qaytadan urinib ko'ring.", parse_mode=None)
                return

    # 4.2 Nous Hermes 3 Avtonom Agent Topshirig'i (/hermes, hermes:)
    hermes_match = re.match(r"^(?:/hermes|hermes)[:\s]+(.+)$", user_text, re.IGNORECASE | re.DOTALL)
    if hermes_match:
        task_prompt = hermes_match.group(1).strip()
        if task_prompt:
            wait_msg = await message.answer(
                "⚡ **Nous Hermes 3 Avtonom Agent ishga tushdi...**\n\n"
                "🧠 Topshiriq ko'p bosqichli tahlil qilinmoqda, mantiqiy rejalashtirish va chuqur hisob-kitob amalga oshirilmoqda..."
            )
            await message.bot.send_chat_action(message.chat.id, "typing")
            hermes_res = await run_hermes_agent(task_prompt, ai_manager)
            await safe_edit_text(wait_msg, hermes_res, parse_mode="Markdown")
            LogCollector().add(
                action_type="hermes_agent",
                description=f"Hermes vazifa: {task_prompt[:40]}",
                model_used="hermes-3-405b",
            )
            return

    # 5. Rasm qidirish va yuborish ("rasmini top: Toshkent", "rasm: Lamborghini", "Eiffel rasmini tashla")
    if re.search(r"(?:rasmini\s+(?:top|tashla|yukla|korsat|ko'rsat)|rasm[:\s]+)", user_text, re.IGNORECASE):
        query_clean = re.sub(r"^(?:rasmini\s+(?:top|tashla|yukla|korsat|ko'rsat)|rasm)[:\s]+", "", user_text, flags=re.IGNORECASE)
        query_clean = re.sub(r"\s+(?:rasmini|rasm)\s+(?:top|tashla|yukla|korsat|ko'rsat).*$", "", query_clean, flags=re.IGNORECASE).strip()
        if query_clean:
            wait_msg = await message.answer(f"🔍 `{query_clean}` bo'yicha internetdan rasm qidirilmoqda...")
            img_url = await search_image_url(query_clean)
            if img_url:
                try:
                    await wait_msg.delete()
                    await message.answer_photo(
                        photo=img_url,
                        caption=f"🖼 **Qidiruv natijasi:** `{query_clean}`",
                    )
                    LogCollector().add(
                        action_type="photo_search",
                        description=f"Rasm topildi: {query_clean}",
                    )
                    return
                except Exception as exc:
                    logger.warning("Rasm yuborishda xato: %s", exc)

            await safe_edit_text(wait_msg, f"❌ `{query_clean}` bo'yicha rasm topilmadi yoki yuklab bo'lmadi.", parse_mode=None)
            return

    # 6. Internetdan jonli qidiruv ("qidir: mavzu", "internetdan qidir: mavzu")
    if re.match(r"^(?:qidir|internetdan\s+qidir|google)[:\s]+", user_text, re.IGNORECASE):
        search_q = re.sub(r"^(?:qidir|internetdan\s+qidir|google)[:\s]+", "", user_text, flags=re.IGNORECASE).strip()
        if search_q:
            wait_msg = await message.answer(f"🌐 `{search_q}` bo'yicha internetdan qidirilmoqda...")
            ai_ans = await answer_with_web_search(search_q, ai_manager)
            await safe_edit_text(wait_msg, ai_ans, parse_mode="Markdown")
            LogCollector().add(
                action_type="web_search",
                description=f"Web search: {search_q[:40]}",
            )
            return

    # 7. Oddiy so'rov → AI bilan to'g'ridan-to'g'ri va tezkor suhbat
    await message.bot.send_chat_action(message.chat.id, "typing")
    response = await ai_manager.generate(user_text)

    # Bulletproof javob yuborish (Markdown xatolarisiz va uzunlik bo'yicha to'g'ri chunking bilan)
    await safe_message_answer(message, response, parse_mode="Markdown")

    # Log yozuv
    provider = ai_manager.current_provider
    model = f"gemini/{GEMINI_MODEL}" if provider == "gemini" else f"or/{ai_manager.current_or_model}"
    LogCollector().add(
        action_type="message",
        description=f"So'rov: {user_text[:50]}",
        model_used=model,
    )

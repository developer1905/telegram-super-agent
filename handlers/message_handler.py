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

import html
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
from core.midjourney_agent import (
    draw_midjourney_image,
    generate_free_midjourney_image,
    MJ_TASKS,
    build_mj_keyboard,
    AVAILABLE_MODELS,
    ASPECT_RATIOS,
)
from core.hermes_agent import run_hermes_agent
from core.tts_agent import generate_speech_audio
from core.crawl_agent import crawl_web_page
from core.browser_agent import take_website_screenshot
from core.mem0_agent import (
    auto_extract_user_memories,
    get_user_profile_report,
    build_profile_keyboard,
    save_profile_fact,
)
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
_media_cache: dict[str, dict] = {}  # task_id -> video_info


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

# ─── Midjourney / FLUX.1 Studio Boshqaruvi (Model, O'lcham, Uslub) ───

@router.callback_query(F.data.startswith("mj:"))
async def cb_midjourney_action(cb: CallbackQuery, ai_manager: AIManager) -> None:
    parts = cb.data.split(":")
    action = parts[1] if len(parts) > 1 else ""

    import random
    from aiogram.types import InputMediaPhoto

    if action in ("redraw", "seed"):
        task_id = parts[2] if len(parts) > 2 else ""
        param = ""
    elif action in ("model", "ar", "style"):
        param = parts[2] if len(parts) > 2 else ""
        task_id = parts[3] if len(parts) > 3 else ""
    else:
        return

    task_data = _mj_tasks.get(task_id)
    if not task_data:
        await cb.answer("⚠️ Rasm ma'lumoti eskirgan. Yangi buyruq yozing.", show_alert=True)
        return

    prompt = task_data["prompt"]
    enhanced = task_data.get("enhanced", prompt)
    ar = task_data.get("ar", "1:1")
    model = task_data.get("model", "flux")
    style = task_data.get("style", "photo")
    seed = task_data.get("seed", random.randint(100000, 99999999))

    if action == "seed":
        seed = random.randint(100000, 99999999)
    elif action == "redraw":
        pass
    elif action == "model":
        model = param
    elif action == "ar":
        ar = param
    elif action == "style":
        style = param

    model_title = AVAILABLE_MODELS.get(model, model).split("(")[0].strip()
    await cb.answer(f"🎨 {model_title} ({ar}) ishlamoqda...")

    img_bytes = await generate_free_midjourney_image(
        prompt=enhanced,
        aspect_ratio=ar,
        style=style,
        seed=seed,
        model=model,
    )
    if not img_bytes:
        await cb.answer("❌ Rasm yaratishda xatolik yuz berdi. Qaytadan urinib ko'ring.", show_alert=True)
        return

    new_task_id = uuid.uuid4().hex[:8]
    _mj_tasks[new_task_id] = {
        "prompt": prompt,
        "enhanced": enhanced,
        "ar": ar,
        "seed": seed,
        "model": model,
        "style": style,
    }

    reply_markup = build_mj_keyboard(new_task_id, current_model=model, current_ar=ar, current_style=style)
    input_file = BufferedInputFile(file=img_bytes, filename=f"mj_{new_task_id}.jpg")
    p_esc = html.escape(prompt)
    caption = (
        f"🎨 <b>Super-Agent Studio: {html.escape(model_title)}</b>\n\n"
        f"📝 <b>So'rov:</b> <i>{p_esc}</i>\n"
        f"📐 O'lcham: <code>{ar}</code> | 🎲 Seed: <code>{seed}</code> | 🎭 Uslub: <code>{style}</code>\n\n"
        f"<i>Quyidagi tugmalar orqali model, o'lcham yoki uslubni bir bosishda o'zgartiring:</i>"
    )

    try:
        await cb.message.edit_media(
            media=InputMediaPhoto(media=input_file, caption=caption, parse_mode="HTML"),
            reply_markup=reply_markup,
        )
    except Exception:
        try:
            await cb.message.delete()
        except Exception:
            pass
        await cb.message.answer_photo(
            photo=input_file,
            caption=caption,
            reply_markup=reply_markup,
            parse_mode="HTML",
        )


# ─── Video Musiqa va MP3 Callbacklari ────────────────────────

@router.callback_query(ADMIN_FILTER, F.data.startswith("media:mp3:"))
async def cb_media_mp3(cb: CallbackQuery) -> None:
    task_id = cb.data.split(":")[-1]
    v_info = _media_cache.get(task_id)
    if not v_info or not os.path.exists(v_info.get("file_path", "")):
        await cb.answer("⚠️ Video fayl xotiradan o'chirilgan, havolani qayta yuboring.", show_alert=True)
        return

    await cb.answer("⏳ MP3 audio ajratilmoqda...")
    from core.media_downloader import get_or_create_mp3
    mp3_info = await get_or_create_mp3(v_info)
    if mp3_info and os.path.exists(mp3_info["audio_path"]):
        from aiogram.types import FSInputFile
        a_file = FSInputFile(mp3_info["audio_path"])
        track_title = html.escape(mp3_info.get("title", "Audio Track")[:80])
        artist_name = html.escape(mp3_info.get("artist", "Super-Agent")[:80])
        caption = (
            f"🎵 <b>{track_title}</b>\n"
            f"👤 <b>Ijrochi:</b> {artist_name}\n\n"
            f"🤖 <b>Super-Agent Audio</b>"
        )
        try:
            await cb.message.reply_audio(
                audio=a_file,
                title=mp3_info.get("title", "Audio Track")[:80],
                performer=mp3_info.get("artist", "Super-Agent")[:80],
                caption=caption,
                parse_mode="HTML",
            )
            LogCollector().add(action_type="media_mp3", description=f"MP3: {track_title[:30]}")
        except Exception as err:
            logger.error("MP3 yuborishda xato: %s", err)
            await cb.message.reply(f"❌ Musiqani yuborishda xatolik: {err}")
    else:
        await cb.message.reply("❌ Videodan MP3 musiqani ajratib bo'lmadi.")


@router.callback_query(ADMIN_FILTER, F.data.startswith("media:shazam:"))
async def cb_media_shazam(cb: CallbackQuery, ai_manager: AIManager) -> None:
    task_id = cb.data.split(":")[-1]
    v_info = _media_cache.get(task_id)
    if not v_info:
        await cb.answer("⚠️ Ma'lumot topilmadi, havolani qayta yuboring.", show_alert=True)
        return

    await cb.answer("🔍 Qo'shiq tahlil qilinmoqda...")
    title = v_info.get("music_title") or v_info.get("title") or ""
    author = v_info.get("music_author") or ""
    platform = v_info.get("platform", "Video")

    prompt = (
        f"Videodan olingan ma'lumotlar:\n"
        f"Platforma: {platform}\n"
        f"Video sarlavhasi / matni: {v_info.get('title', '')}\n"
        f"Musiqa treki: {title}\n"
        f"Ijrochi / Muallif: {author}\n\n"
        f"Topshiriq: Ushbu videoda yangragan asl qo'shiq nomi, ijrochisi, janri va qanday topish mumkinligini "
        f"aniqlab, foydalanuvchiga juda chiroyli, qisqa va aniq ma'lumot ber (o'zbek tilida)."
    )
    res = await ai_manager.generate(prompt, save_history=False)
    await cb.message.reply(f"🔍 <b>Videodagi Qo'shiq Tahlili (Shazam AI):</b>\n\n{res}", parse_mode="HTML")


@router.callback_query(ADMIN_FILTER, F.data == "read_voice_msg")
async def cb_read_voice_msg(cb: CallbackQuery) -> None:
    await cb.answer("🎙 Ovoz tayyorlanmoqda...")
    text_to_speak = cb.message.text or cb.message.caption or ""
    if not text_to_speak:
        await cb.answer("❌ Matn topilmadi", show_alert=True)
        return

    voice_bytes = await generate_speech_audio(text_to_speak)
    if voice_bytes:
        voice_file = BufferedInputFile(file=voice_bytes, filename="superagent_voice.mp3")
        await cb.message.reply_voice(voice=voice_file, caption="🎙 **Ovozli Talqin**")
    else:
        await cb.answer("❌ Ovoz generatsiya qilib bo'lmadi.", show_alert=True)


# ─── Serverni Tozalash & Disk Holati Callbacks ────────────────

@router.callback_query(ADMIN_FILTER, F.data == "clean:server")
async def cb_clean_server(cb: CallbackQuery) -> None:
    await cb.answer("🧹 Tozalanmoqda...")
    from core.cleaner_agent import safe_clean_server_storage
    await safe_edit_text(cb, "🧹 **Server kesh va vaqtinchalik fayllari xavfsiz tozalanmoqda...**")
    res = await safe_clean_server_storage()
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📊 Disk Holatini Ko'rish", callback_data="disk:status"))
    text = (
        f"✅ **Server Xavfsiz Tozalandi!**\n\n"
        f"• 🗑 Bo'shatilgan hajm: `{res['freed_mb']} MB`\n"
        f"• 🟢 Hozirgi bo'sh joy: `{res['after_free_gb']} GB`\n"
        f"• 📊 Disk bandligi: `{res['percent']}%`\n\n"
        f"🔒 _Asosiy baza (`superagent.db`) va tizim sozlamalariga hech qanday ziyon yetmadi._"
    )
    await safe_edit_text(cb, text, reply_markup=builder.as_markup(), parse_mode="Markdown")


@router.callback_query(ADMIN_FILTER, F.data == "disk:status")
async def cb_disk_status(cb: CallbackQuery) -> None:
    await cb.answer()
    from core.cleaner_agent import format_storage_status_report
    report = format_storage_status_report()
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🧹 Server Keshini Tozalash", callback_data="clean:server"))
    await safe_edit_text(cb, report, reply_markup=builder.as_markup(), parse_mode="Markdown")


# ─── TodoList & Notion Callbacks ──────────────────────────────

@router.callback_query(ADMIN_FILTER, F.data.startswith("todo:done:"))
async def cb_todo_done(cb: CallbackQuery) -> None:
    task_id = int(cb.data.replace("todo:done:", ""))
    await db.complete_task(task_id)
    await cb.answer(f"✅ #{task_id} vazifa bajarildi deb belgilandi!")
    from core.todo_notion_agent import format_tasks_list_report
    text, markup = await format_tasks_list_report()
    await safe_edit_text(cb, text, reply_markup=markup, parse_mode="Markdown")


@router.callback_query(ADMIN_FILTER, F.data.startswith("todo:del:"))
async def cb_todo_del(cb: CallbackQuery) -> None:
    task_id = int(cb.data.replace("todo:del:", ""))
    await db.delete_task(task_id)
    await cb.answer("❌ Vazifa o'chirildi")
    from core.todo_notion_agent import format_tasks_list_report
    text, markup = await format_tasks_list_report()
    await safe_edit_text(cb, text, reply_markup=markup, parse_mode="Markdown")


@router.callback_query(ADMIN_FILTER, F.data == "todo:refresh")
async def cb_todo_refresh(cb: CallbackQuery) -> None:
    await cb.answer("🔄 Yangilanmoqda...")
    from core.todo_notion_agent import format_tasks_list_report
    text, markup = await format_tasks_list_report()
    await safe_edit_text(cb, text, reply_markup=markup, parse_mode="Markdown")


@router.callback_query(ADMIN_FILTER, F.data == "todo:add_hint")
async def cb_todo_add_hint(cb: CallbackQuery) -> None:
    await cb.answer()
    hint_text = (
        "➕ **Yangi Vazifa Qo'shish:**\n\n"
        "Botga xohlagan vaqtda quyidagi formatlarda yozishingiz mumkin:\n"
        "• `vazifa: Ertaga soat 10 da hisobot topshirish`\n"
        "• `todo: Do'kondan olma sotib olish 2026-09-20`\n"
        "• `reja: Yangi loyiha dizaynini ko'rib chiqish`\n\n"
        "🎙 Yoki ovozli xabar bilan *'Vazifa qo'sh: Uyga non olib kelish'* deb ayting!"
    )
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ Vazifalar Ro'yxatiga Qaytish", callback_data="todo:refresh"))
    await safe_edit_text(cb, hint_text, reply_markup=builder.as_markup(), parse_mode="Markdown")


# ─── Uptime Monitoring Callbacks ──────────────────────────────

@router.callback_query(ADMIN_FILTER, F.data == "uptime:check_now")
async def cb_uptime_check_now(cb: CallbackQuery) -> None:
    await cb.answer("⏳ Saytlar tekshirilmoqda...")
    from core.uptime_agent import run_uptime_batch_check, format_uptime_dashboard_report
    await run_uptime_batch_check()
    text, markup = await format_uptime_dashboard_report()
    await safe_edit_text(cb, text, reply_markup=markup, parse_mode="Markdown")


@router.callback_query(ADMIN_FILTER, F.data == "uptime:add_hint")
async def cb_uptime_add_hint(cb: CallbackQuery) -> None:
    await cb.answer()
    text = (
        "➕ **Monitoringga Yangi Sayt Qo'shish:**\n\n"
        "Botga quyidagicha yozing:\n"
        "• `/add_site https://mysite.uz Mening Saytim`\n"
        "• `sayt qo'sh: https://api.mysite.uz | Asosiy API`\n\n"
        "O'chirish uchun: `/del_site [id]` deb yozing."
    )
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ Uptime Ro'yxatiga Qaytish", callback_data="uptime:check_now"))
    await safe_edit_text(cb, text, reply_markup=builder.as_markup(), parse_mode="Markdown")


# ─── RSS & Real Madrid Callbacks ──────────────────────────────

@router.callback_query(ADMIN_FILTER, F.data.startswith("news:"))
async def cb_news_topic(cb: CallbackQuery, ai_manager: AIManager) -> None:
    topic = cb.data.replace("news:", "")
    await cb.answer("⏳ Yangiliklar yuklanmoqda...")
    from core.news_football_agent import get_topic_news
    text, markup = await get_topic_news(topic, ai_manager)
    await safe_edit_text(cb, text, reply_markup=markup, parse_mode="Markdown")


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

    # 1. Ijtimoiy tarmoqlardan video yuklash (Instagram, TikTok, YouTube, X, Pinterest)
    from core.media_downloader import extract_media_url, download_social_video, detect_platform, get_or_create_mp3
    media_url = extract_media_url(user_text)
    if media_url:
        platform_name = detect_platform(media_url)
        wait_msg = await message.answer(f"⏳ <b>{platform_name} videosi yuklab olinmoqda...</b>\n<code>{html.escape(media_url[:80])}</code>\n\n<i>Iltimos, kuting (HD, suvsiz formatda)...</i>", parse_mode="HTML")
        await message.bot.send_chat_action(message.chat.id, "upload_video")
        video_info = await download_social_video(media_url)
        if video_info and os.path.exists(video_info.get("file_path", "")):
            try:
                from aiogram.types import FSInputFile
                task_id = uuid.uuid4().hex[:8]
                _media_cache[task_id] = video_info

                v_file = FSInputFile(video_info["file_path"])
                p_safe = html.escape(video_info.get("platform", "Video"))
                t_safe = html.escape(video_info.get("title", "")[:80])
                sz = video_info.get("size_mb", 0)

                music_line = ""
                if video_info.get("music_title"):
                    music_line = f"\n🎵 <b>Musiqa:</b> {html.escape(video_info['music_title'][:60])}"
                    if video_info.get("music_author"):
                        music_line += f" — <i>{html.escape(video_info['music_author'][:40])}</i>"

                caption = (
                    f"🎬 <b>{p_safe} yuklandi!</b>\n\n"
                    f"📝 <b>Nomi:</b> {t_safe}\n"
                    f"📦 <b>Hajmi:</b> <code>{sz} MB</code>"
                    f"{music_line}\n\n"
                    f"🤖 <b>Super-Agent</b>"
                )

                # Tugmalar: MP3 yuklash va Qo'shiqni aniqlash
                builder = InlineKeyboardBuilder()
                builder.row(
                    InlineKeyboardButton(text="🎵 Musiqasini olish (MP3)", callback_data=f"media:mp3:{task_id}"),
                    InlineKeyboardButton(text="🔍 Qo'shiqni aniqlash", callback_data=f"media:shazam:{task_id}"),
                )

                try:
                    await message.reply_video(video=v_file, caption=caption, parse_mode="HTML", reply_markup=builder.as_markup())
                except Exception as vid_err:
                    logger.warning("reply_video muvaffaqiyatsiz (%s), reply_document orqali yuborilmoqda", vid_err)
                    await message.reply_document(document=v_file, caption=caption, parse_mode="HTML", reply_markup=builder.as_markup())

                await wait_msg.delete()
                LogCollector().add(action_type="media_download", description=f"Video: {platform_name}")

                # Agar foydalanuvchi so'rovida "mp3" yoki "musiqa" yozilgan bo'lsa, MP3 ni ham darhol jo'natish
                if any(w in user_text.lower() for w in ["mp3", "musiqa", "audio", "qo'shiq"]):
                    mp3_info = await get_or_create_mp3(video_info)
                    if mp3_info and os.path.exists(mp3_info["audio_path"]):
                        a_file = FSInputFile(mp3_info["audio_path"])
                        m_caption = (
                            f"🎵 <b>{html.escape(mp3_info.get('title', 'Musiqa')[:80])}</b>\n"
                            f"👤 <b>Ijrochi:</b> {html.escape(mp3_info.get('artist', 'Super-Agent')[:80])}\n\n"
                            f"🤖 <b>Super-Agent Audio</b>"
                        )
                        await message.reply_audio(
                            audio=a_file,
                            title=mp3_info.get("title", "Audio Track")[:80],
                            performer=mp3_info.get("artist", "Super-Agent")[:80],
                            caption=m_caption,
                            parse_mode="HTML",
                        )
            except Exception as v_err:
                logger.error("Video yuborishda xato: %s", v_err)
                await safe_edit_text(wait_msg, f"❌ Videoni yuborishda xatolik: {v_err}", parse_mode=None)
            return
        else:
            await safe_edit_text(wait_msg, f"❌ Kechirasiz, {platform_name} videosini yuklab bo'lmadi yoki video hajmi 50MB dan katta.", parse_mode=None)
            return

    # 1.1 Email buyruqlarini tekshirish
    if await handle_email_text_command(message, ai_manager):
        return

    # 2. Veb-Maqola (URL) Tahlili va Kanal Posti Generatori
    url_match = re.search(r"https?://[^\s]+", user_text)
    if url_match and ("maqola" in user_text.lower() or "post tayyorla" in user_text.lower() or "tahlil qil" in user_text.lower() or "tezis" in user_text.lower()):
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

    # 4.1 FLUX.1 & Midjourney v6 AI Rasm Chizish Skilli (/flux, /draw, /imagine, /midjourney, /image, chiz:, rasm chiz:)
    mj_match = re.match(r"^(?:/imagine|/midjourney|/flux|/draw|/art|/image|chiz|rasm\s+chiz|rasm\s+yarat|chizib\s+ber|draw)(?:[:\s]+(.*)|$)", user_text, re.IGNORECASE | re.DOTALL)
    if mj_match:
        raw_prompt = (mj_match.group(1) or "").strip()
        if not raw_prompt:
            helper_text = (
                "🎨 <b>Super-Agent Studio — AI Rasm Markazi</b>\n\n"
                "Qanday rasm chizmoqchisiz? Buyruqdan so'ng xohlagan tasavvuringizni yozing:\n\n"
                "💡 <i>Masalan:</i>\n"
                "<code>/draw Samarqand Registon maydoni kechasi, kiberpank uslubida</code>\n"
                "<code>/flux Kosmik kema qora tuynuk yaqinida --ar 16:9 --model flux</code>\n\n"
                "⚙️ <b>Qo'shimcha parametrlar:</b>\n"
                "• <b>O'lchamlar:</b> <code>--ar 1:1</code>, <code>--ar 16:9</code>, <code>--ar 9:16</code>, <code>--ar 4:3</code>, <code>--ar 3:4</code>\n"
                "• <b>Modellar:</b> <code>--model flux</code>, <code>--model gpt-image-2</code>, <code>--model z-image</code>, <code>--model flux-klein</code>\n"
                "• <b>Uslublar:</b> <code>--style photo</code>, <code>--style anime</code>, <code>--style 3d</code>, <code>--style cyberpunk</code>, <code>--style art</code>\n\n"
                "<i>Rasm chizilgach, ostidagi tugmalar orqali model va o'lchamni bir zumda almashtira olasiz!</i>"
            )
            await message.answer(helper_text, parse_mode="HTML")
            return

        wait_msg = await message.answer(
            "🎨 <b>Super-Agent Studio rasm chizmoqda...</b>\n\n"
            "✨ <i>Prompt AI tomonidan kinoxit darajasiga boyitilmoqda va fotorealistik ishlanmoqda...</i>",
            parse_mode="HTML",
        )
        await message.bot.send_chat_action(message.chat.id, "upload_photo")
        try:
            img_bytes, enhanced_prompt, ar, seed, used_model, *_ = await draw_midjourney_image(
                raw_prompt=raw_prompt,
                ai_manager=ai_manager,
                enhance=True,
            )
        except Exception as draw_err:
            logger.error("Rasm chizishda xatolik: %s", draw_err)
            img_bytes = None

        if img_bytes:
            task_id = uuid.uuid4().hex[:8]
            _mj_tasks[task_id] = {
                "prompt": raw_prompt,
                "enhanced": enhanced_prompt,
                "ar": ar,
                "seed": seed,
                "model": used_model,
                "style": "photo",
            }
            reply_markup = build_mj_keyboard(task_id, current_model=used_model, current_ar=ar, current_style="photo")
            input_file = BufferedInputFile(file=img_bytes, filename=f"studio_{task_id}.jpg")
            p_esc = html.escape(raw_prompt)
            enh_esc = html.escape(enhanced_prompt[:220])
            model_title = AVAILABLE_MODELS.get(used_model, used_model).split("(")[0].strip()
            caption = (
                f"🎨 <b>Super-Agent Studio: {html.escape(model_title)}</b>\n\n"
                f"📝 <b>So'rov:</b> <i>{p_esc}</i>\n"
                f"✨ <b>AI Prompt:</b> <i>{enh_esc}...</i>\n"
                f"📐 O'lcham: <code>{ar}</code> | 🎲 Seed: <code>{seed}</code>\n\n"
                f"<i>Quyidagi tugmalar orqali model yoki proporsiyani almashtirishingiz mumkin:</i>"
            )
            try:
                await wait_msg.delete()
            except Exception:
                pass
            await message.answer_photo(
                photo=input_file,
                caption=caption,
                reply_markup=reply_markup,
                parse_mode="HTML",
            )
            LogCollector().add(
                action_type="midjourney_image",
                description=f"Studio: {raw_prompt[:40]}",
                model_used=used_model,
            )
            return
        else:
            await safe_edit_text(wait_msg, "❌ Rasm chizishda xatolik yuz berdi. Iltimos, qaytadan urinib ko'ring.", parse_mode=None)
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

    # 4.2.A DEEP RESEARCH AGENT (/research, /tadqiqot, tadqiqot:, research:)
    research_match = re.match(r"^(?:/research|/tadqiqot|tadqiqot|research)[:\s]+(.+)$", user_text, re.IGNORECASE | re.DOTALL)
    if research_match:
        research_topic = research_match.group(1).strip()
        if research_topic:
            wait_msg = await message.answer(
                f"🔬 **Deep Research Agent ishga tushdi...**\n`{research_topic[:60]}`\n\n"
                "🌐 Internetdan ko'p bosqichli manbalar qidirilmoqda, faktlar tahlil qilinib hisobot tayyorlanmoqda..."
            )
            await message.bot.send_chat_action(message.chat.id, "typing")
            from core.expert_agents import DeepResearchAgent
            agent = DeepResearchAgent(ai_manager)
            res = await agent.conduct_research(research_topic)
            await safe_edit_text(wait_msg, res, parse_mode="Markdown")
            LogCollector().add(action_type="deep_research", description=f"Tadqiqot: {research_topic[:40]}")
            return

    # 4.2.B CODE REVIEWER & BUG FIXER (/code, /audit, /kod, kod:, audit:)
    code_match = re.match(r"^(?:/code|/audit|/kod|kod|audit)[:\s]+(.+)$", user_text, re.IGNORECASE | re.DOTALL)
    if code_match:
        code_input = code_match.group(1).strip()
        if code_input:
            wait_msg = await message.answer(
                "💻 **Code Reviewer & Security Auditor tahlilni boshladi...**\n\n"
                "🔍 Sintaksis, mantiqiy xatolar, xavfsizlik zaifliklari va samaradorlik tekshirilmoqda..."
            )
            await message.bot.send_chat_action(message.chat.id, "typing")
            from core.expert_agents import CodeReviewerAgent
            agent = CodeReviewerAgent(ai_manager)
            res = await agent.review_code(code_input)
            await safe_edit_text(wait_msg, res, parse_mode="Markdown")
            LogCollector().add(action_type="code_review", description=f"Code Review: {code_input[:30]}")
            return

    # 4.2.C SMART CONTRACT & DOCUMENT ANALYZER (/inspect, /doc, /shartnoma, shartnoma:, hujjat:)
    doc_match = re.match(r"^(?:/inspect|/doc|/shartnoma|shartnoma|hujjat)[:\s]+(.+)$", user_text, re.IGNORECASE | re.DOTALL)
    if doc_match:
        doc_input = doc_match.group(1).strip()
        if doc_input:
            wait_msg = await message.answer(
                "📄 **Smart Contract & Document Analyzer ishga tushdi...**\n\n"
                "⚖️ Hujjatdagi xavfli bandlar, moliyaviy majburiyatlar va huquqiy tuzoqlar tekshirilmoqda..."
            )
            await message.bot.send_chat_action(message.chat.id, "typing")
            from core.expert_agents import DocumentContractAgent
            agent = DocumentContractAgent(ai_manager)
            res = await agent.analyze_document(doc_input)
            await safe_edit_text(wait_msg, res, parse_mode="Markdown")
            LogCollector().add(action_type="doc_inspect", description=f"Doc Inspect: {doc_input[:30]}")
            return

    # 4.2.D VIRAL SMM & CONTENT STRATEGY AGENT (/smm, /post, /viral, smm:, post:)
    smm_match = re.match(r"^(?:/smm|/post|/viral|smm|post)[:\s]+(.+)$", user_text, re.IGNORECASE | re.DOTALL)
    if smm_match:
        smm_input = smm_match.group(1).strip()
        if smm_input:
            wait_msg = await message.answer(
                f"🎯 **Viral SMM Strateg ishga tushdi...**\n`{smm_input[:50]}`\n\n"
                "🚀 3 ta kuchli hook, jalb qiluvchi post, CTA, hashtaglar va haftalik reja tuzilmoqda..."
            )
            await message.bot.send_chat_action(message.chat.id, "typing")
            from core.expert_agents import ViralSMMAgent
            agent = ViralSMMAgent(ai_manager)
            res = await agent.generate_content(smm_input)
            await safe_edit_text(wait_msg, res, parse_mode="Markdown")
            LogCollector().add(action_type="viral_smm", description=f"SMM: {smm_input[:30]}")
            return


    # 4.3 Ovoz Sintezi — Text-to-Speech (/voice, ovoz:, gapir:)
    voice_match = re.match(r"^(?:/voice|ovoz|gapir|ovozga\s+aylantir)[:\s]+(.+)$", user_text, re.IGNORECASE | re.DOTALL)
    if voice_match:
        text_to_speak = voice_match.group(1).strip()
        if text_to_speak:
            wait_msg = await message.answer("🎙 **Matn inson ovoziga aylantirilmoqda...**")
            voice_bytes = await generate_speech_audio(text_to_speak)
            if voice_bytes:
                await wait_msg.delete()
                v_file = BufferedInputFile(file=voice_bytes, filename="voice.mp3")
                await message.reply_voice(voice=v_file, caption=f"🎙 _{text_to_speak[:100]}..._", parse_mode="Markdown")
                LogCollector().add(action_type="tts_voice", description=f"Ovoz: {text_to_speak[:30]}")
                return
            else:
                await safe_edit_text(wait_msg, "❌ Ovoz generatsiya qilib bo'lmadi.")
                return

    # 4.4 Crawl4AI — Chuqur Veb Skraping (/crawl, sayt:, saytni oqi:)
    crawl_match = re.match(r"^(?:/crawl|sayt|saytni\s+oqi|saytni\s+tahlil\s+qil|urlni\s+tekshir)[:\s]+(https?://\S+)(.*)$", user_text, re.IGNORECASE)
    if crawl_match:
        target_url = crawl_match.group(1).strip()
        user_instruct = crawl_match.group(2).strip()
        wait_msg = await message.answer(f"🕷 `{target_url}` sayti (Crawl4AI) orqali chuqur skraping qilinmoqda...")
        crawl_data = await crawl_web_page(target_url)
        if crawl_data.get("status") == "ok":
            page_text = crawl_data.get("content", "")
            page_title = crawl_data.get("title", "")
            crawl_prompt = (
                f"Veb-sahifa: {target_url}\nSarlavha: {page_title}\n\n"
                f"Saytning toza matni:\n{page_text[:4000]}\n\n"
                f"Topshiriq: {user_instruct or 'Saytning mazmuni, xizmatlari va muhim ma\'lumotlarini tahlil qilib, tizimli xulosa ber.'}"
            )
            ai_summary = await ai_manager.generate(crawl_prompt, save_history=False)
            header = f"🌐 **Crawl4AI Tahlili:** [{page_title}]({target_url})\n\n"
            await safe_edit_text(wait_msg, header + ai_summary, parse_mode="Markdown")
            LogCollector().add(action_type="crawl", description=f"Crawl: {target_url[:40]}")
            return
        else:
            await safe_edit_text(wait_msg, f"❌ Saytni o'qishda xatolik: {crawl_data.get('error', 'Noma\'lum')}")
            return

    # 4.5 Browser-Use — Sayt Skrinshotini Olish (/screenshot, skrinshot:)
    ss_match = re.match(r"^(?:/screenshot|skrinshot|ekran\s+rasmi|screenshot)[:\s]+(https?://\S+)", user_text, re.IGNORECASE)
    if ss_match:
        ss_url = ss_match.group(1).strip()
        wait_msg = await message.answer(f"🌐 `{ss_url}` saytining jonli skrinshoti olinmoqda (Browser-Use)...")
        await message.bot.send_chat_action(message.chat.id, "upload_photo")
        ss_bytes = await take_website_screenshot(ss_url)
        if ss_bytes:
            await wait_msg.delete()
            input_ss = BufferedInputFile(file=ss_bytes, filename="screenshot.jpg")
            await message.answer_photo(
                photo=input_ss,
                caption=f"📸 **Veb-sayt Skrinshoti (Browser-Use)**\n🔗 Manzil: `{ss_url}`",
                parse_mode="Markdown",
            )
            LogCollector().add(action_type="screenshot", description=f"Screenshot: {ss_url[:40]}")
            return
        else:
            await safe_edit_text(wait_msg, "❌ Skrinshot olib bo'lmadi. Sayt manzilini tekshiring.")
            return

    # 4.6 Mem0 — Adaptiv Shaxsiy Profil (/profile, profil memo, memo, mem0, profilim)
    lower_u = user_text.lower().strip()
    if lower_u in ("/profile", "profil", "mening profilim", "men haqimda", "profilim", "profil memo", "memo", "mem0", "shaxsiy profil", "xotira memo"):
        prof_text = await get_user_profile_report(message.from_user.id)
        await message.answer(prof_text, reply_markup=build_profile_keyboard(), parse_mode="Markdown")
        return

    # 4.7 Mem0 — Qo'lda fakt qo'shish ("profil: kasb: AI Engineer" yoki "/profile set ism Umid")
    if lower_u.startswith(("/profile set ", "profil qo'sh:", "profil: ", "profilimga: ")):
        cleaned_cmd = re.sub(r"^(?:/profile set\s+|profil qo'sh:\s*|profil:\s*|profilimga:\s*)", "", user_text, flags=re.IGNORECASE).strip()
        if ":" in cleaned_cmd:
            k, v = cleaned_cmd.split(":", 1)
        elif " " in cleaned_cmd:
            k, v = cleaned_cmd.split(" ", 1)
        else:
            k, v = "eslatma", cleaned_cmd
        if k and v:
            await save_profile_fact(k, v)
            await message.answer(f"✅ **Mem0 Profilingizga saqlandi:**\n• **{k.strip().capitalize()}:** {v.strip()}", parse_mode="Markdown")
            return

    # 4.8 Server Xavfsiz Tozalash & Disk Holati (/disk, /clean_server, server holati, serverni tozala)
    if lower_u in ("/disk", "disk", "server holati", "xotira holati", "disk holati"):
        from core.cleaner_agent import format_storage_status_report
        report = format_storage_status_report()
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="🧹 Server Keshini Tozalash", callback_data="clean:server"))
        await message.answer(report, reply_markup=builder.as_markup(), parse_mode="Markdown")
        return

    if lower_u in ("/clean_server", "/cleandisk", "serverni tozala", "keshni tozala", "server tozalash"):
        from core.cleaner_agent import safe_clean_server_storage
        wait_msg = await message.answer("🧹 **Serverdagi keraksiz kesh va vaqtinchalik fayllar xavfsiz tozalanmoqda...**\n_(Ma'lumotlar bazasi va doimiy fayllarga tegilmaydi)_", parse_mode="Markdown")
        res = await safe_clean_server_storage()
        text = (
            f"✅ **Server Xavfsiz Tozalandi!**\n\n"
            f"• 🗑 Bo'shatilgan joy: `{res['freed_mb']} MB`\n"
            f"• 🟢 Hozirgi bo'sh xotira: `{res['after_free_gb']} GB`\n"
            f"• 📊 Disk bandligi: `{res['percent']}%`\n\n"
            f"🔒 _Barcha shaxsiy xabarlar, SQLite bazasi va sozlamalar 100% xavfsiz saqlanib qoldi._"
        )
        await safe_edit_text(wait_msg, text, parse_mode="Markdown")
        return

    # 4.9 TodoList & Notion Vazifalar (/todo, vazifalar, reja, todoist)
    if lower_u in ("/todo", "todo", "vazifalar", "vazifalarim", "reja", "rejalarim", "todolist"):
        from core.todo_notion_agent import format_tasks_list_report
        text, markup = await format_tasks_list_report()
        await message.answer(text, reply_markup=markup, parse_mode="Markdown")
        return

    # Yangi vazifa qo'shish (vazifa: ..., todo: ..., reja: ..., /todo add ...)
    if re.match(r"^(?:/todo\s+(?:add|qo'sh)?|vazifa\s*qo'sh:|vazifa:|reja:|todo:)\s+", user_text, re.IGNORECASE):
        from core.todo_notion_agent import create_new_task
        task_info = await create_new_task(user_text)
        notion_txt = " (🌐 Notion'ga ham sinxronlandi)" if task_info["notion_synced"] else ""
        due_txt = f"\n📅 Muddat: `{task_info['due_date']}`" if task_info["due_date"] else ""
        await message.answer(
            f"✅ **Yangi vazifa saqlandi (#{task_info['id']})**{notion_txt}!\n"
            f"📌 **Vazifa:** {task_info['title']}{due_txt}\n\n"
            f"Barcha vazifalar: /todo",
            parse_mode="Markdown"
        )
        return

    # 4.10 Uptime Monitoring (/uptime, saytlar holati, /add_site)
    if lower_u in ("/uptime", "uptime", "saytlar", "saytlarim", "saytlar holati", "serverlarim"):
        from core.uptime_agent import format_uptime_dashboard_report
        text, markup = await format_uptime_dashboard_report()
        await message.answer(text, reply_markup=markup, parse_mode="Markdown")
        return

    if lower_u.startswith(("/add_site ", "sayt qo'sh:", "sayt qosh:")):
        site_cmd = re.sub(r"^(?:/add_site\s+|sayt\s*qo'sh:\s*|sayt\s*qosh:\s*)", "", user_text, flags=re.IGNORECASE).strip()
        site_url = site_cmd
        site_name = ""
        if "|" in site_cmd:
            site_url, site_name = site_cmd.split("|", 1)
        elif " " in site_cmd:
            parts = site_cmd.split(" ", 1)
            site_url, site_name = parts[0], parts[1]
        site_id = await db.add_uptime_monitor(site_url, site_name)
        await message.answer(
            f"✅ **Sayt monitoringga qo'shildi (#{site_id}):**\n"
            f"🔗 Manzil: `{site_url.strip()}`\n"
            f"💡 Bot har 10 daqiqada tekshirib, xatolik bo'lsa xabar beradi.\n\n"
            f"Ko'rish: /uptime",
            parse_mode="Markdown"
        )
        return

    if lower_u.startswith(("/del_site ", "sayt o'chir:", "sayt ochir:")):
        site_id_str = re.sub(r"^(?:/del_site\s+|sayt\s*o'chir:\s*|sayt\s*ochir:\s*)", "", user_text, flags=re.IGNORECASE).strip()
        try:
            m_id = int(site_id_str)
            await db.delete_uptime_monitor(m_id)
            await message.answer(f"✅ #{m_id} sayt monitoringdan o'chirildi.", parse_mode="Markdown")
        except ValueError:
            await message.answer("❌ Noto'g'ri ID. Masalan: `/del_site 1`")
        return

    # 4.11 RSS Yangiliklar & Tahlil (/news, yangiliklar)
    if lower_u in ("/news", "news", "yangiliklar", "yangilik", "xabarlar"):
        wait_msg = await message.answer("🔍 **Internetdan eng so'nggi yangiliklar yig'ilmoqda va tahlil qilinmoqda...**", parse_mode="Markdown")
        from core.news_football_agent import get_topic_news
        report_text, markup = await get_topic_news("dasturlash", ai_manager)
        await safe_edit_text(wait_msg, report_text, reply_markup=markup, parse_mode="Markdown")
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

    # 6.5 Avtomat Jonli Qidiruv (Agar so'rovda yangilik, oxirgi o'yin, natija, kurs yoki jonli faktlar so'ralsa)
    live_triggers = [
        "yangilik", "natija", "hisob", "o'yin", "o'yini", "kurs", "kursi", "narxi",
        "oxirgi", "so'nggi", "kecha", "bugun nima", "kim yutdi", "kim gol urdi",
        "jadval", "chempionat", "dollar", "valyuta", "qachon o'ynaydi", "necha necha bo'ldi"
    ]
    if any(trig in lower_u for trig in live_triggers) and len(user_text.split()) >= 2:
        wait_msg = await message.answer("🌐 **Internetdan jonli faktlar qidirilmoqda va AI tahlil qilmoqda...**", parse_mode="Markdown")
        ai_ans = await answer_with_web_search(user_text, ai_manager)
        voice_btn = InlineKeyboardBuilder()
        voice_btn.row(InlineKeyboardButton(text="🔊 Ovozda eshitish", callback_data="read_voice_msg"))
        await safe_edit_text(wait_msg, ai_ans, reply_markup=voice_btn.as_markup(), parse_mode="Markdown")
        return

    # 7. Oddiy so'rov → AI bilan to'g'ridan-to'g'ri va tezkor suhbat
    # Mem0 orqa fonda foydalanuvchining shaxsiy odatlarini o'rganadi
    import asyncio
    asyncio.create_task(auto_extract_user_memories(user_text, ai_manager))

    await message.bot.send_chat_action(message.chat.id, "typing")
    response = await ai_manager.generate(user_text)

    # Ovozli eshitish tugmasi
    voice_btn = InlineKeyboardBuilder()
    voice_btn.row(InlineKeyboardButton(text="🔊 Ovozda eshitish", callback_data="read_voice_msg"))

    # Javob yuborish
    try:
        await message.answer(response, reply_markup=voice_btn.as_markup(), parse_mode="Markdown")
    except Exception:
        await safe_message_answer(message, response, parse_mode=None)

    # Log yozuv
    provider = ai_manager.current_provider
    model = f"gemini/{GEMINI_MODEL}" if provider == "gemini" else f"or/{ai_manager.current_or_model}"
    LogCollector().add(
        action_type="message",
        description=f"So'rov: {user_text[:50]}",
        model_used=model,
    )

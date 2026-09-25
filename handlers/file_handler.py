"""
handlers/file_handler.py — Hujjat Qabul Qilish va Tahrirlash

Foydalanuvchi yuborgan faylni:
1. RAMga o'qiydi (diskka yozmasdan)
2. Mazmunini ajratadi (DOCX/PDF/TXT/PY)
3. AI bilan tahlil qiladi
4. Qayta yozish so'rovi bo'lsa, yangi fayl yaratib yuboradi
"""

from __future__ import annotations

import io
import logging

from aiogram import Router, F, Bot
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardButton,
    BufferedInputFile,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import ADMIN_ID, SUPPORTED_MIME_TYPES
from core.ai_manager import AIManager
from core.database import db
from core.excel_analyzer import analyze_spreadsheet
from core.file_editor import (
    extract_text_from_bytes,
    build_analysis_prompt,
    build_rewrite_prompt,
    build_output_bytes,
)
from services.scheduler import LogCollector

logger = logging.getLogger(__name__)
router = Router(name="file")

ADMIN_FILTER = F.from_user.id == ADMIN_ID

# Kutilayotgan qayta yozish so'rovlari: {message_id: (file_bytes, file_type, filename)}
_pending_rewrites: dict[int, tuple[bytes, str, str]] = {}


# ─── Hujjat Handleri ─────────────────────────────────────────

@router.message(F.document)
async def handle_document(message: Message, bot: Bot, ai_manager: AIManager) -> None:
    """
    Foydalanuvchi yuborgan hujjatni qayta ishlaydi:
    - DOCX, PDF, TXT, PY tahlili va qayta yozish
    - XLSX, XLS, CSV jadvallarini chuqur tahlil qilish (Data Analytics)
    - Doimiy xotiraga saqlash
    """
    user_id = message.from_user.id if message.from_user else 0
    if await db.is_user_blocked(user_id):
        await message.answer("❌ Sizning hisobingiz administrator tomonidan bloklangan.")
        return

    doc = message.document
    mime_type = doc.mime_type or ""
    filename = doc.file_name or "fayl"

    # MIME turini aniqlash
    file_type = SUPPORTED_MIME_TYPES.get(mime_type)

    # Kengaytma orqali ham aniqlash
    if not file_type:
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        ext_map = {
            "docx": "docx", "pdf": "pdf", "txt": "txt", "py": "py", "doc": "docx",
            "xlsx": "xlsx", "xls": "xls", "csv": "csv", "pptx": "pptx", "ppt": "pptx",
            "html": "html", "md": "txt", "json": "txt",
        }
        file_type = ext_map.get(ext)

    if not file_type:
        await message.answer(
            f"⚠️ `{filename}` fayl turi qo'llab-quvvatlanmaydi.\n"
            "Qabul qilinadigan formatlar: **DOCX, PDF, PPTX, TXT, PY, XLSX, CSV, HTML**",
            parse_mode="Markdown",
        )
        return

    # Fayl hajmini tekshirish (max 20 MB)
    if doc.file_size and doc.file_size > 20 * 1024 * 1024:
        await message.answer("❌ Fayl hajmi 20 MB dan katta.")
        return

    wait_msg = await message.answer(f"⏳ `{filename}` xotiraga o'qilmoqda...", parse_mode="Markdown")

    # Faylni RAMga yuklash
    try:
        file_obj = await bot.get_file(doc.file_id)
        file_buf = io.BytesIO()
        await bot.download_file(file_obj.file_path, destination=file_buf)
        file_bytes = file_buf.getvalue()
    except Exception as exc:
        await wait_msg.edit_text(f"❌ Fayl yuklanmadi: {exc}")
        logger.error("Fayl yuklanmadi: %s", exc, exc_info=True)
        return

    # ─── EXCEL VA CSV TAHLILI (DATA ANALYTICS) ───────────────
    if file_type in ("xlsx", "xls", "csv") and not (message.caption and "matn" in message.caption.lower()):
        await wait_msg.edit_text(f"📊 `{filename}` jadvali hisob-kitob qilinmoqda...", parse_mode="Markdown")
        analytics_result = await analyze_spreadsheet(
            file_bytes=file_bytes,
            file_name=filename,
            ai_manager=ai_manager,
            user_prompt=message.caption or "",
        )
        from core.safe_send import safe_edit_text
        await safe_edit_text(wait_msg, analytics_result, parse_mode="Markdown")
        return

    # ─── MICROSOFT MARKITDOWN ORQALI MATNNI AJRATISH ─────────
    await wait_msg.edit_text(f"🔍 `{filename}` (Microsoft MarkItDown) tahlil qilinmoqda...", parse_mode="Markdown")
    try:
        from core.markitdown_agent import convert_document_to_markdown
        extracted_text = convert_document_to_markdown(file_bytes, filename=filename)
    except Exception as md_err:
        logger.warning("MarkItDown xatosi (%s), zaxira metodga o'tiladi", md_err)
        extracted_text = extract_text_from_bytes(file_bytes, file_type)

    if not extracted_text or extracted_text.startswith("["):
        extracted_text = extract_text_from_bytes(file_bytes, file_type)

    if not extracted_text or extracted_text.startswith("["):
        # Xato yoki bo'sh
        await wait_msg.edit_text(f"⚠️ {extracted_text or 'Hujjat bo\'sh'}")
        return

    # Arab Lotlari (Arabic Parts) fayli ekanligini avtomatik aniqlash
    lower_txt = extracted_text.lower()
    if ("part of " in lower_txt or "lot of " in lower_txt or "pars fortuna" in lower_txt or "arabic parts" in lower_txt) and ("gemini" in lower_txt or "leo" in lower_txt or "aries" in lower_txt or "°" in lower_txt or "uy" in lower_txt or "house" in lower_txt):
        from core.astrology_agent import parse_custom_arabic_lots
        parsed_lots = parse_custom_arabic_lots(extracted_text)
        if len(parsed_lots) >= 3:
            await db.save_custom_lots(str(message.from_user.id), parsed_lots)
            from core.safe_send import safe_edit_text
            res_msg = (
                f"☪️ **ARAB LOTLARI (ARABIC PARTS) MUVAFFAQIYATLI YUKLANDI!**\n\n"
                f"📊 Fayldan aniqlangan va tizimga saqlangan Lotlar: **{len(parsed_lots)} ta**.\n"
                f"✅ Ushbu lotlar sizning shaxsiy astrologik profilingizga bog'landi!\n\n"
                f"Endi **Nous Hermes 3** va **20 yillik tajribali munajjim-olim** ushbu lotlar asosida voqeaviy chuqur tahlil bera oladi.\n\n"
                f"Tahlil olish uchun: /lots yoki Web App dagi 'Voqealar Prognozi' tugmasini bosing!"
            )
            builder = InlineKeyboardBuilder()
            builder.row(InlineKeyboardButton(text="🧠 20 Yillik Olim Tahlili (Hermes 3)", callback_data="astro:ai_report"))
            await safe_edit_text(wait_msg, res_msg, reply_markup=builder.as_markup(), parse_mode="Markdown")
            return

    # AI tahlili
    prompt = build_analysis_prompt(extracted_text, filename, file_type)

    await message.bot.send_chat_action(message.chat.id, "typing")
    analysis = await ai_manager.generate(prompt, save_history=False)

    # Tugmalar
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="✏️ Qayta Yoz (AI bilan)",
            callback_data=f"rewrite_file:{wait_msg.message_id}",
        ),
        InlineKeyboardButton(
            text="📊 Chuqur Tahlil",
            callback_data=f"deep_analyze:{wait_msg.message_id}",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="⚖️ Shartnoma Xatarlarini Tekshirish",
            callback_data=f"contract_audit:{wait_msg.message_id}",
        ),
        InlineKeyboardButton(
            text="💾 Xotiraga Saqlash",
            callback_data=f"save_kb:{wait_msg.message_id}",
        )
    )

    # Tahlilni yuborish
    header = f"📄 **{filename}** tahlili:\n{'─' * 30}\n\n"
    full_text = header + analysis
    from core.safe_send import safe_edit_text
    await safe_edit_text(
        wait_msg,
        full_text,
        reply_markup=builder.as_markup(),
        parse_mode="Markdown",
    )

    # Kutilayotgan so'rovni saqlash
    _pending_rewrites[wait_msg.message_id] = (file_bytes, file_type, filename)

    LogCollector().add(
        action_type="file",
        description=f"Fayl tahlili: {filename} ({file_type})",
        model_used=ai_manager.current_provider,
    )


# ─── Shartnoma Auditi Callback ────────────────────────────────

@router.callback_query(F.data.startswith("contract_audit:"))
async def cb_contract_audit(cb: CallbackQuery, ai_manager: AIManager) -> None:
    """Hujjatdagi shartnoma xatarlari va noqulay bandlarni tahlil qiladi."""
    msg_id_str = cb.data.replace("contract_audit:", "")
    msg_id = int(msg_id_str) if msg_id_str.isdigit() else 0
    file_data = _pending_rewrites.get(msg_id)
    if not file_data:
        await cb.answer("Fayl ma'lumotlari topilmadi", show_alert=True)
        return

    file_bytes, file_type, filename = file_data
    from core.file_editor import extract_text_from_bytes
    text = extract_text_from_bytes(file_bytes, file_type)
    if not text or text.startswith("["):
        await cb.answer("Fayldan matn ajratib bo'lmadi", show_alert=True)
        return

    await cb.answer("⚖️ Shartnoma xatarlari o'rganilmoqda...")
    from core.expert_agents import DocumentContractAgent
    agent = DocumentContractAgent(ai_manager)
    report = await agent.analyze_document(text)
    from core.safe_send import safe_send_message
    await safe_send_message(cb.bot, cb.message.chat.id, report, parse_mode="Markdown")


# ─── Qayta Yozish Callback ────────────────────────────────────

@router.callback_query(F.data.startswith("rewrite_file:"))
async def cb_rewrite_file(cb: CallbackQuery, ai_manager: AIManager) -> None:
    """Faylni AI bilan qayta yozib yuboradi."""
    msg_id_str = cb.data.replace("rewrite_file:", "")
    try:
        msg_id = int(msg_id_str)
    except ValueError:
        await cb.answer("⚠️ Xatolik")
        return

    if msg_id not in _pending_rewrites:
        await cb.answer("⚠️ Fayl ma'lumoti eskirgan. Qayta yuboring.")
        return

    file_bytes, file_type, filename = _pending_rewrites[msg_id]

    await cb.message.edit_text(
        "✏️ Fayl qayta yozilmoqda... (bu bir necha soniya olishi mumkin)",
    )

    # Matnni ajratib, qayta yozish promptini tuzish
    original_text = extract_text_from_bytes(file_bytes, file_type)
    rewrite_prompt = build_rewrite_prompt(
        original_text,
        instruction="Matnni professionalroq va ravon qilib, strukturasini yaxshilab qayta yoz",
        file_type=file_type,
    )

    rewritten = await ai_manager.generate(rewrite_prompt)

    # Yangi fayl yaratish
    output_bytes, output_name, output_mime = build_output_bytes(rewritten, file_type)

    input_file = BufferedInputFile(
        file=output_bytes,
        filename=output_name,
    )

    await cb.message.answer_document(
        document=input_file,
        caption=f"✅ `{filename}` qayta yozildi!",
        parse_mode="Markdown",
    )
    await cb.message.edit_text("✅ Qayta yozilgan fayl yuqorida.")
    _pending_rewrites.pop(msg_id, None)

    LogCollector().add(
        action_type="file",
        description=f"Qayta yozildi: {filename} ({file_type})",
        model_used=ai_manager.current_provider,
    )
    await cb.answer("✅ Fayl qayta yozildi")


# ─── Chuqur Tahlil Callback ───────────────────────────────────

@router.callback_query(F.data.startswith("deep_analyze:"))
async def cb_deep_analyze(cb: CallbackQuery, ai_manager: AIManager) -> None:
    """Fayl mazmunini chuqurroq tahlil qiladi."""
    msg_id_str = cb.data.replace("deep_analyze:", "")
    try:
        msg_id = int(msg_id_str)
    except ValueError:
        await cb.answer("⚠️ Xatolik")
        return

    if msg_id not in _pending_rewrites:
        await cb.answer("⚠️ Fayl ma'lumoti eskirgan. Qayta yuboring.")
        return

    file_bytes, file_type, filename = _pending_rewrites[msg_id]

    await cb.message.edit_text("🔬 Chuqur tahlil amalga oshirilmoqda...")

    original_text = extract_text_from_bytes(file_bytes, file_type)
    max_chars = 5000
    text_sample = original_text[:max_chars]

    deep_prompt = (
        f"Quyidagi {file_type.upper()} hujjatini JUDA chuqur tahlil qil:\n\n"
        f"```\n{text_sample}\n```\n\n"
        "Tahlilda quyidagilarni qamrab ol:\n"
        "1. 📋 Hujjat maqsadi va qo'llanilishi\n"
        "2. 🎯 Asosiy g'oyalar va fikrlar\n"
        "3. ✅ Kuchli tomonlar\n"
        "4. ❌ Kamchiliklar va xatolar\n"
        "5. 💡 Yaxshilash tavsiyalari\n"
        "6. 📊 Umumiy baho (10 ballik shkalada)\n\n"
        "Har bir bo'lim aniq va batafsil bo'lsin."
    )

    await cb.bot.send_chat_action(cb.message.chat.id, "typing")
    deep_analysis = await ai_manager.generate(deep_prompt)

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="✏️ Qayta Yoz",
            callback_data=f"rewrite_file:{msg_id}",
        )
    )

    await cb.message.edit_text(
        f"🔬 **{filename}** — Chuqur Tahlil:\n{'─'*30}\n\n{deep_analysis[:3800]}",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown",
    )
    await cb.answer("✅ Chuqur tahlil tayyor")


# ─── Doimiy Xotiraga Saqlash Callback ─────────────────────────

@router.callback_query(F.data.startswith("save_kb:"))
async def cb_save_kb(cb: CallbackQuery) -> None:
    """Fayl matnini doimiy xotiraga (Knowledge Base) saqlaydi."""
    msg_id_str = cb.data.replace("save_kb:", "")
    try:
        msg_id = int(msg_id_str)
    except ValueError:
        await cb.answer("⚠️ Xatolik")
        return

    if msg_id not in _pending_rewrites:
        await cb.answer("⚠️ Fayl ma'lumoti eskirgan. Qayta yuboring.")
        return

    file_bytes, file_type, filename = _pending_rewrites[msg_id]
    original_text = extract_text_from_bytes(file_bytes, file_type)

    if not original_text or original_text.startswith("["):
        await cb.answer("❌ Fayl matni bo'sh, saqlanmadi.", show_alert=True)
        return

    # Fakt kaliti: fayl nomi asosida
    fact_key = filename.rsplit(".", 1)[0].replace(" ", "_").lower()
    success = await db.save_fact(
        key=fact_key,
        content=original_text[:4000],
        category="document",
        user_id=str(cb.from_user.id),
    )

    if success:
        await cb.answer("✅ Fayl doimiy xotiraga (RAG Memory) saqlandi!", show_alert=True)
        await cb.message.answer(
            f"🧠 **Fayl xotiraga kiritildi!**\n"
            f"Kalit: `{fact_key}`\n"
            f"Endi bot suhbat tarixi /clear qilinsa ham ushbu ma'lumotlarga tayanib javob beradi.",
            parse_mode="Markdown",
        )
    else:
        await cb.answer("❌ Xotiraga saqlashda xatolik yuz berdi.", show_alert=True)

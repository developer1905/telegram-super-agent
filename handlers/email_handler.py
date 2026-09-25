"""
handlers/email_handler.py — Email Boshqarish Buyruqlari va Tasdiqlash Tizimi

Imkoniyatlar:
- /email — Email menyusi
- O'qilmagan xatlarni tekshirish va AI tahlili
- Yangi xat yozish (AI yordamida yoki to'g'ridan-to'g'ri)
- Xatni yuborishdan oldin Inline Confirmation (Tasdiqlash)
"""

from __future__ import annotations

import logging
import uuid

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import ADMIN_ID, EMAIL_USER
from core.ai_manager import AIManager
from core.email_agent import EmailAgent
from services.scheduler import LogCollector

logger = logging.getLogger(__name__)
router = Router(name="email")

ADMIN_FILTER = F.from_user.id == ADMIN_ID

# Yuborilishi kutilayotgan xatlar (In-memory draft storage)
# draft_id -> {"to": ..., "subject": ..., "body": ...}
PENDING_EMAILS: dict[str, dict[str, str]] = {}


def get_email_agent() -> EmailAgent:
    """EmailAgent nusxasini qaytaradi."""
    return EmailAgent()


def build_email_menu(is_configured: bool) -> InlineKeyboardMarkup:
    """Email asosiy menyu klaviaturasi."""
    builder = InlineKeyboardBuilder()

    if is_configured:
        builder.row(
            InlineKeyboardButton(text="📥 O'qilmagan xatlar & AI Tahlil", callback_data="email:check"),
        )
        builder.row(
            InlineKeyboardButton(text="✍️ Yangi xat yozish (AI)", callback_data="email:compose_help"),
        )
    builder.row(
        InlineKeyboardButton(text="⚙️ Sozlamalar holati", callback_data="email:status"),
        InlineKeyboardButton(text="◀️ Asosiy Menyu", callback_data="menu:main"),
    )
    return builder.as_markup()


# ─── /email Buyrug'i ─────────────────────────────────────────

@router.message(Command("email"))
async def cmd_email(message: Message) -> None:
    """Email boshqaruv markazi."""
    agent = get_email_agent()
    configured = agent.is_configured()

    if configured:
        status_text = f"✅ Ulangan: `{agent.user}`"
    else:
        status_text = (
            "⚠️ Sozlanmagan!\n"
            "`.env` fayliga `EMAIL_USER` va `EMAIL_PASS` (App Password) kiriting."
        )

    text = (
        f"📧 **Shaxsiy Email Agent**\n\n"
        f"Holat: {status_text}\n\n"
        f"Bu agent orqali:\n"
        f"• Shaxsiy pochtangizga kelgan yangi xatlarni AI tahlil qiladi\n"
        f"• Muhim xatlarni saralab, xulosasini beradi\n"
        f"• AI orqali professional javob xatlari tayyorlaydi va yuboradi\n\n"
        f"Quyidagi amallardan birini tanlang:"
    )

    await message.answer(text, reply_markup=build_email_menu(configured), parse_mode="Markdown")


# ─── Yordamchi: Xavfsiz Tahrirlash ───────────────────────────

async def safe_edit_text(
    cb: CallbackQuery,
    text: str,
    reply_markup=None,
    parse_mode: str | None = "Markdown",
) -> None:
    """Xatoliklarsiz xabarni xavfsiz tahrirlash."""
    try:
        await cb.message.edit_text(text=text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception as e:
        logger.debug("email safe_edit_text: %s", e)
        try:
            await cb.message.edit_text(text=text, reply_markup=reply_markup, parse_mode=None)
        except Exception:
            pass


# ─── Callback Handlerlar ─────────────────────────────────────

@router.callback_query(F.data == "email:menu")
async def cb_email_menu(cb: CallbackQuery) -> None:
    await cb.answer()
    agent = get_email_agent()
    configured = agent.is_configured()
    status_text = f"✅ Ulangan: `{agent.user}`" if configured else "⚠️ Sozlanmagan"

    await safe_edit_text(
        cb,
        f"📧 **Shaxsiy Email Agent**\n\nHolat: {status_text}",
        reply_markup=build_email_menu(configured),
        parse_mode="Markdown",
    )


@router.callback_query(F.data == "email:status")
async def cb_email_status(cb: CallbackQuery) -> None:
    await cb.answer()
    agent = get_email_agent()
    configured = agent.is_configured()

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ Orqaga", callback_data="email:menu"))

    if configured:
        text = (
            f"⚙️ **Email Sozlamalari:**\n\n"
            f"• **Foydalanuvchi:** `{agent.user}`\n"
            f"• **IMAP Server:** `{agent.imap_server}:{agent.imap_port}`\n"
            f"• **SMTP Server:** `{agent.smtp_server}:{agent.smtp_port}`\n"
            f"• **Holat:** Faol va tayyor ✅"
        )
    else:
        text = (
            "⚠️ **Email sozlanmagan!**\n\n"
            "Email agenti ishlashi uchun `.env` da quyidagilarni to'ldiring:\n"
            "```env\n"
            "EMAIL_USER=sizning_email@gmail.com\n"
            "EMAIL_PASS=xxxx xxxx xxxx xxxx (App Password)\n"
            "```\n"
            "💡 *Eslatma: Gmail uchun '2-Step Verification' yoqilib, "
            "'App Passwords' bo'limidan 16 xonali maxsus parol olinadi.*"
        )

    await safe_edit_text(cb, text, reply_markup=builder.as_markup(), parse_mode="Markdown")


@router.callback_query(F.data == "email:check")
async def cb_email_check(cb: CallbackQuery, ai_manager: AIManager) -> None:
    if cb.from_user.id != ADMIN_ID:
        await cb.answer("🔒 Shaxsiy pochta xatlarini tekshirish faqat bot egasi uchun ochiq.", show_alert=True)
        return
    agent = get_email_agent()
    if not agent.is_configured():
        await cb.answer("⚠️ Email sozlanmagan!", show_alert=True)
        return

    await cb.answer("📩 Xatlar tekshirilmoqda...")
    await safe_edit_text(cb, "⏳ Pochtadan yangi xatlar olinmoqda va AI tahlil qilmoqda...")

    unread_emails = await agent.fetch_unread(limit=5)
    if not unread_emails and agent.last_error:
        summary = agent.last_error
    else:
        summary = await agent.analyze_inbox(unread_emails, ai_manager)

    # Log yozish
    collector = LogCollector()
    collector.add(
        action_type="email_check",
        description=f"Email tekshirildi ({len(unread_emails)} ta yangi xat)",
        model_used=ai_manager.current_provider,
    )

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🔄 Qayta tekshirish", callback_data="email:check"),
        InlineKeyboardButton(text="◀️ Email Menyu", callback_data="email:menu"),
    )

    await safe_edit_text(
        cb,
        summary[:4000],
        reply_markup=builder.as_markup(),
        parse_mode="Markdown",
    )


@router.callback_query(F.data == "email:compose_help")
async def cb_email_compose_help(cb: CallbackQuery) -> None:
    await cb.answer()
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ Orqaga", callback_data="email:menu"))

    text = (
        "✍️ **Email yozish bo'yicha qo'llanma:**\n\n"
        "AI orqali yangi xat tayyorlash uchun quyidagicha xabar yuboring:\n\n"
        "`email ai: user@example.com | Mavzu yoki vazifa haqida ko'rsatma`\n\n"
        "Misol:\n"
        "`email ai: director@company.uz | Oylik hisobot tayyorligi va dushanba kuni taqdimot qilishim haqida rasmiy xat`\n\n"
        "To'g'ridan-to'g'ri xat yuborish uchun:\n"
        "`email: user@example.com | Mavzu | Xat matni`\n\n"
        "⚠️ Har qanday holatda ham xat **darhol ketmaydi**, avval sizdan tasdiqlash so'raladi!"
    )

    await safe_edit_text(cb, text, reply_markup=builder.as_markup(), parse_mode="Markdown")


# ─── Xatni Tasdiqlash va Yuborish ────────────────────────────

@router.callback_query(F.data.startswith("send_email:"))
async def cb_send_email_confirm(cb: CallbackQuery) -> None:
    if cb.from_user.id != ADMIN_ID:
        await cb.answer("🔒 Xat yuborish faqat bot egasi uchun ochiq.", show_alert=True)
        return
    draft_id = cb.data.replace("send_email:", "")
    draft = PENDING_EMAILS.pop(draft_id, None)

    if not draft:
        await cb.answer("⚠️ Bu xat allaqachon bekor qilingan yoki yuborilgan!", show_alert=True)
        await cb.message.delete()
        return

    await cb.answer("📤 Xat yuborilmoqda...")
    agent = get_email_agent()

    success, msg = await agent.send_email(
        to_email=draft["to"],
        subject=draft["subject"],
        body=draft["body"],
    )

    if success:
        collector = LogCollector()
        collector.add(
            action_type="email_send",
            description=f"Email yuborildi: {draft['to']} | {draft['subject']}",
        )
        await cb.message.edit_text(
            f"✅ **Muvaffaqiyatli yuborildi!**\n\n"
            f"📨 **Kimga:** `{draft['to']}`\n"
            f"📌 **Mavzu:** `{draft['subject']}`",
            parse_mode="Markdown",
        )
    else:
        await cb.message.edit_text(
            f"❌ **Xatolik yuz berdi:**\n{msg}",
            parse_mode="Markdown",
        )


@router.callback_query(F.data.startswith("cancel_email:"))
async def cb_cancel_email(cb: CallbackQuery) -> None:
    draft_id = cb.data.replace("cancel_email:", "")
    PENDING_EMAILS.pop(draft_id, None)
    await cb.message.edit_text("❌ Xat bekor qilindi va yuborilmadi.")
    await cb.answer("Bekor qilindi")


# ─── Matnli Buyruqlar (Triggerlar) ───────────────────────────

async def handle_email_text_command(message: Message, ai_manager: AIManager) -> bool:
    """
    Agar xabar email buyrug'i bo'lsa, ushlab qayta ishlaydi.
    True qaytarsa — demak xabar qabul qilindi.
    """
    text = (message.text or "").strip()
    agent = get_email_agent()

    # 1. "email tekshir" yoki "pochta tekshir"
    if text.lower() in ["email tekshir", "pochta", "pochta tekshir", "xatlar", "yangi xatlar"]:
        if not agent.is_configured():
            await message.answer("⚠️ Email sozlanmagan! Avval `.env` ga EMAIL_USER va EMAIL_PASS kiriting.")
            return True

        wait_msg = await message.answer("⏳ Yangi xatlar tekshirilmoqda va AI tahlili qilinmoqda...")
        unread_emails = await agent.fetch_unread(limit=5)
        if not unread_emails and agent.last_error:
            summary = agent.last_error
        else:
            summary = await agent.analyze_inbox(unread_emails, ai_manager)

        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(text="🔄 Yangilash", callback_data="email:check"),
            InlineKeyboardButton(text="📧 Email Menyu", callback_data="email:menu"),
        )
        await wait_msg.edit_text(summary[:4000], reply_markup=builder.as_markup(), parse_mode="Markdown")
        return True

    # 2. "email ai: <to> | <prompt>"
    if text.lower().startswith("email ai:"):
        raw = text[len("email ai:"):].strip()
        parts = [p.strip() for p in raw.split("|", 1)]
        if len(parts) < 2 or not parts[0] or not parts[1]:
            await message.answer(
                "❌ Noto'g'ri format!\n"
                "Format: `email ai: kimga@example.com | Xat haqida ko'rsatma`",
                parse_mode="Markdown",
            )
            return True

        to_email, instruction = parts[0], parts[1]
        wait_msg = await message.answer(f"⏳ `{to_email}` uchun AI orqali professional xat yozilmoqda...")

        subject, body = await agent.draft_new_email(instruction, to_email, ai_manager)

        # Draft saqlash
        draft_id = str(uuid.uuid4())[:8]
        PENDING_EMAILS[draft_id] = {
            "to": to_email,
            "subject": subject,
            "body": body,
        }

        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(text="✅ Yuborish", callback_data=f"send_email:{draft_id}"),
            InlineKeyboardButton(text="❌ Bekor qilish", callback_data=f"cancel_email:{draft_id}"),
        )

        confirm_text = (
            f"📝 **AI tomonidan tayyorlangan xat loyihasi:**\n\n"
            f"📨 **Kimga:** `{to_email}`\n"
            f"📌 **Mavzu:** `{subject}`\n\n"
            f"📄 **Xat matni:**\n```\n{body}\n```\n\n"
            f"Ushbu xat yuborilsinmi?"
        )

        await wait_msg.edit_text(confirm_text, reply_markup=builder.as_markup(), parse_mode="Markdown")
        return True

    # 3. "email: <to> | <subject> | <body>"
    if text.lower().startswith("email:"):
        raw = text[len("email:"):].strip()
        parts = [p.strip() for p in raw.split("|", 2)]
        if len(parts) < 3 or not parts[0] or not parts[1] or not parts[2]:
            await message.answer(
                "❌ Noto'g'ri format!\n"
                "Format: `email: kimga@example.com | Mavzu | Xat matni`",
                parse_mode="Markdown",
            )
            return True

        to_email, subject, body = parts[0], parts[1], parts[2]

        draft_id = str(uuid.uuid4())[:8]
        PENDING_EMAILS[draft_id] = {
            "to": to_email,
            "subject": subject,
            "body": body,
        }

        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(text="✅ Yuborish", callback_data=f"send_email:{draft_id}"),
            InlineKeyboardButton(text="❌ Bekor qilish", callback_data=f"cancel_email:{draft_id}"),
        )

        confirm_text = (
            f"📨 **Email yuborishni tasdiqlang:**\n\n"
            f"• **Kimga:** `{to_email}`\n"
            f"• **Mavzu:** `{subject}`\n\n"
            f"📄 **Matn:**\n```\n{body}\n```"
        )
        await message.answer(confirm_text, reply_markup=builder.as_markup(), parse_mode="Markdown")
        return True

    return False

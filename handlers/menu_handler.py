"""
handlers/menu_handler.py — Asosiy Menyu va Inline Tugmalar

/start, /help, /status buyruqlari va quyidagi inline tugmalar:
- Model tanlash (Gemini / OpenRouter variantlari)
- Rol tanlash (barcha rollar)
- Hisobot ko'rish (bugungi log)
- Xotirani tozalash
- Userbot ma'lumoti
"""

from __future__ import annotations

import html
import logging
import uuid

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    WebAppInfo,
    ReplyKeyboardMarkup,
    KeyboardButton,
    BufferedInputFile,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import (
    ADMIN_ID,
    GEMINI_MODEL,
    OPENROUTER_MODELS,
    OPENROUTER_MODEL_NAMES,
    WEBAPP_URL,
    get_clean_webapp_url,
)
from core.ai_manager import AIManager
from core.database import db
from core.userbot import get_userbot_info, summarize_telegram_activity
from core.midjourney_agent import (
    build_image_studio_panel,
    get_user_image_settings,
    QUICK_IDEAS,
    draw_midjourney_image,
    build_mj_keyboard,
    AVAILABLE_MODELS,
    MJ_TASKS,
)
from services.roles import ROLES, get_role_keyboard_data
from services.scheduler import LogCollector
from core.safe_send import safe_edit_text, safe_edit_or_send_long_message, safe_send_message

logger = logging.getLogger(__name__)
router = Router(name="menu")

# Faqat admin filtratsiyasi
ADMIN_FILTER = F.from_user.id == ADMIN_ID


# ─── Yordamchi: Doimiy Klaviatura Menyulari (Reply Keyboards) ─

def build_reply_keyboard_menu() -> ReplyKeyboardMarkup:
    """Asosiy ixcham pastki klaviatura menyusi (Guruhlangan toifalar)."""
    buttons = [
        [
            KeyboardButton(text="📱 Mini App Paneli"),
        ],
        [
            KeyboardButton(text="🎨 AI & Kreativ Studio"),
            KeyboardButton(text="💼 Ish & Unumdorlik"),
        ],
        [
            KeyboardButton(text="📈 SMM & Marketing"),
            KeyboardButton(text="⚙️ Sozlamalar & Xotira"),
        ],
        [
            KeyboardButton(text="📊 Holat & Yordam"),
        ],
    ]
    return ReplyKeyboardMarkup(
        keyboard=buttons,
        resize_keyboard=True,
        is_persistent=True,
    )


def build_reply_ai_studio_menu() -> ReplyKeyboardMarkup:
    """1-guruh: AI & Kreativ Studio vositalari."""
    buttons = [
        [
            KeyboardButton(text="🔮 Astrologiya & Natal Karta"),
            KeyboardButton(text="🎨 Rasm Chizish Studio"),
        ],
        [
            KeyboardButton(text="⚡ Hermes Agent"),
            KeyboardButton(text="🔬 Deep Research"),
        ],
        [
            KeyboardButton(text="💻 Kod & Shartnoma Auditi"),
            KeyboardButton(text="🎙 Ovozli Agent (STT & TTS)"),
        ],
        [
            KeyboardButton(text="🎬 Video Yuklovchi"),
        ],
        [
            KeyboardButton(text="🔙 Asosiy Menyu"),
        ],
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True, is_persistent=True)


def build_reply_productivity_menu() -> ReplyKeyboardMarkup:
    """2-guruh: Ish & Unumdorlik vositalari."""
    buttons = [
        [
            KeyboardButton(text="📝 Vazifalar (Notion)"),
            KeyboardButton(text="🌐 Saytlar (Uptime)"),
        ],
        [
            KeyboardButton(text="📧 Email Pochta"),
            KeyboardButton(text="⏰ Eslatmalar"),
        ],
        [
            KeyboardButton(text="📰 Yangiliklar & Tahlil"),
            KeyboardButton(text="👤 Shaxsiy Profil (Mem0)"),
        ],
        [
            KeyboardButton(text="🔙 Asosiy Menyu"),
        ],
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True, is_persistent=True)


def build_reply_smm_menu() -> ReplyKeyboardMarkup:
    """3-guruh: SMM & Marketing vositalari."""
    buttons = [
        [
            KeyboardButton(text="🤖 Avtonom Agent Skillari"),
        ],
        [
            KeyboardButton(text="🎯 Viral SMM"),
            KeyboardButton(text="⏰ Rejalashtirilgan Postlar"),
        ],
        [
            KeyboardButton(text="🔍 Raqobatchilar Tahlili"),
            KeyboardButton(text="📡 Telegram Xulosasi"),
        ],
        [
            KeyboardButton(text="🔄 Tarixni Sinxronlash"),
        ],
        [
            KeyboardButton(text="🔙 Asosiy Menyu"),
        ],
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True, is_persistent=True)


def build_reply_settings_menu() -> ReplyKeyboardMarkup:
    """4-guruh: AI Sozlamalari & Doimiy Xotira."""
    buttons = [
        [
            KeyboardButton(text="🤖 AI Modellar"),
            KeyboardButton(text="🎭 Tizim Rollari"),
        ],
        [
            KeyboardButton(text="🧠 Doimiy Xotira"),
            KeyboardButton(text="🧹 Xotirani Tozalash"),
        ],
        [
            KeyboardButton(text="🔙 Asosiy Menyu"),
        ],
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True, is_persistent=True)


def build_reply_system_menu() -> ReplyKeyboardMarkup:
    """5-guruh: Tizim Holati & Yordam."""
    buttons = [
        [
            KeyboardButton(text="📊 Holat & Statistika"),
            KeyboardButton(text="📋 Bugungi Log"),
        ],
        [
            KeyboardButton(text="📱 Mini App Paneli"),
            KeyboardButton(text="❓ Yordam"),
        ],
        [
            KeyboardButton(text="🔙 Asosiy Menyu"),
        ],
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True, is_persistent=True)


# ─── Yordamchi: Inline Klaviaturalar (Guruhlangan va Ixcham) ─

def build_main_menu() -> InlineKeyboardMarkup:
    """Asosiy menyu inline klaviaturasi (toifalarga guruhlangan)."""
    builder = InlineKeyboardBuilder()

    target_web_url = get_clean_webapp_url()
    if target_web_url:
        builder.row(
            InlineKeyboardButton(
                text="📱 Super-Agent Mini App Paneli",
                web_app=WebAppInfo(url=target_web_url)
            )
        )

    builder.row(
        InlineKeyboardButton(text="🎨 AI & Kreativ", callback_data="menu:cat_ai"),
        InlineKeyboardButton(text="💼 Ish & Unumdorlik", callback_data="menu:cat_prod"),
    )
    builder.row(
        InlineKeyboardButton(text="📈 SMM & Marketing", callback_data="menu:cat_smm"),
        InlineKeyboardButton(text="⚙️ Sozlamalar", callback_data="menu:cat_settings"),
    )
    builder.row(
        InlineKeyboardButton(text="📊 Holat & Statistika", callback_data="menu:status"),
        InlineKeyboardButton(text="❓ Yordam", callback_data="menu:help"),
    )
    return builder.as_markup()


def build_inline_ai_menu() -> InlineKeyboardMarkup:
    """Inline: AI & Kreativ Studio bo'limi."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🔮 Astrologiya & Natal", callback_data="menu:astrology"),
        InlineKeyboardButton(text="🎨 Rasm Studio", callback_data="menu:image_studio"),
    )
    builder.row(
        InlineKeyboardButton(text="⚡ Hermes 3 Agent", callback_data="menu:hermes"),
        InlineKeyboardButton(text="🔬 Deep Research", callback_data="menu:deep_research"),
    )
    builder.row(
        InlineKeyboardButton(text="💻 Kod Auditi", callback_data="menu:code_audit"),
        InlineKeyboardButton(text="🎙 Ovozli Audio", callback_data="menu:tts_info"),
    )
    builder.row(
        InlineKeyboardButton(text="🎬 Video Yuklovchi", callback_data="menu:video_dl"),
    )
    builder.row(
        InlineKeyboardButton(text="◀️ Bosh Menyu", callback_data="menu:main"),
    )
    return builder.as_markup()


def build_inline_productivity_menu() -> InlineKeyboardMarkup:
    """Inline: Ish & Unumdorlik bo'limi."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📝 TodoList (Notion)", callback_data="menu:todo"),
        InlineKeyboardButton(text="🌐 Saytlar Uptime", callback_data="menu:uptime"),
    )
    builder.row(
        InlineKeyboardButton(text="📧 Email Agent", callback_data="email:menu"),
        InlineKeyboardButton(text="⏰ Eslatmalar", callback_data="menu:reminders"),
    )
    builder.row(
        InlineKeyboardButton(text="📰 Yangiliklar & Tahlil", callback_data="menu:news"),
        InlineKeyboardButton(text="👤 Profilim (Mem0)", callback_data="menu:mem0_profile"),
    )
    builder.row(
        InlineKeyboardButton(text="◀️ Bosh Menyu", callback_data="menu:main"),
    )
    return builder.as_markup()


def build_inline_smm_menu() -> InlineKeyboardMarkup:
    """Inline: SMM & Marketing bo'limi."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🎯 Viral SMM", callback_data="menu:viral_smm"),
        InlineKeyboardButton(text="⏰ Reja Postlar", callback_data="menu:scheduled_posts"),
    )
    builder.row(
        InlineKeyboardButton(text="🔍 Raqobatchilar Tahlili", callback_data="menu:competitors"),
        InlineKeyboardButton(text="📡 Telegram Xulosasi", callback_data="menu:tg_summary"),
    )
    builder.row(
        InlineKeyboardButton(text="🔄 Tarixni Sinxronlash", callback_data="menu:sync_history"),
    )
    builder.row(
        InlineKeyboardButton(text="◀️ Bosh Menyu", callback_data="menu:main"),
    )
    return builder.as_markup()


def build_inline_settings_menu() -> InlineKeyboardMarkup:
    """Inline: Sozlamalar & Doimiy Xotira bo'limi."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🤖 Model Tanlash", callback_data="menu:models"),
        InlineKeyboardButton(text="🎭 Rol Tanlash", callback_data="menu:roles"),
    )
    builder.row(
        InlineKeyboardButton(text="🧠 Doimiy Xotira (RAG)", callback_data="menu:memory"),
        InlineKeyboardButton(text="🧹 Xotirani Tozalash", callback_data="menu:clear"),
    )
    builder.row(
        InlineKeyboardButton(text="◀️ Bosh Menyu", callback_data="menu:main"),
    )
    return builder.as_markup()


def build_models_menu() -> InlineKeyboardMarkup:
    """Barcha bepul AI modellari menyusi."""
    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(
            text=f"✨ Google Gemini ({GEMINI_MODEL})",
            callback_data="model:gemini",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="🌐 OmniRoute Gateway (350+ AI)",
            callback_data="model:omniroute",
        )
    )

    for key, name in OPENROUTER_MODEL_NAMES.items():
        builder.row(
            InlineKeyboardButton(
                text=name,
                callback_data=f"model:or_{key}",
            )
        )

    builder.row(
        InlineKeyboardButton(text="◀️ Asosiy Menyu", callback_data="menu:main"),
    )
    return builder.as_markup()


def build_roles_menu() -> InlineKeyboardMarkup:
    """Rol tanlash menyusi."""
    builder = InlineKeyboardBuilder()

    role_data = get_role_keyboard_data()
    for name, key in role_data:
        builder.row(
            InlineKeyboardButton(text=name, callback_data=f"role:{key}")
        )

    builder.row(
        InlineKeyboardButton(text="◀️ Orqaga", callback_data="menu:main"),
    )
    return builder.as_markup()


# ─── Buyruqlar ────────────────────────────────────────────────

@router.message(ADMIN_FILTER, Command("start"))
async def cmd_start(message: Message, ai_manager: AIManager) -> None:
    """Bot ishga tushganda asosiy salomlashish xabari va doimiy klaviatura menyusi."""
    role_name = ROLES.get(ai_manager.current_role, {}).get("name", "Noma'lum")
    if ai_manager.current_provider == "gemini":
        model_info = f"Gemini ({GEMINI_MODEL})"
    else:
        model_key = ai_manager.current_or_model
        model_id = OPENROUTER_MODELS.get(model_key, model_key)
        model_info = f"OpenRouter ({model_id.split('/')[-1]})"

    text = (
        f"👋 Salom, **Super-Agent 2.0 Enterprise** ishga tayyor!\n\n"
        f"🤖 Joriy model: `{model_info}`\n"
        f"🎭 Joriy rol: `{role_name}`\n\n"
        f"**Asosiy Imkoniyatlar:**\n"
        f"• 🎙 Ovozli buyruqlar (Voice-to-Task)\n"
        f"• 📬 Muhim shaxsiy xabarlarni saralash (Smart Inbox Triage)\n"
        f"• 🧠 Doimiy Xotira (Supabase + SQLite RAG)\n"
        f"• 🌐 Jonli veb-havola tahlili va post generatsiyasi\n"
        f"• 📊 Excel va CSV jadvallarini tahlil qilish\n"
        f"• ⏰ SMM taymerli postlar va raqobatchilar tahlili\n"
        f"• 📧 Shaxsiy pochtani boshqarish (Email Agent)\n"
        f"• 📱 Telegram Mini App boshqaruv paneli\n\n"
        f"Barcha bo'limlar pastdagi **Klaviatura Menyusi**da tayyor holatda joylashtirildi 👇"
    )
    # Doimiy pastki klaviaturani o'rnatish
    await message.answer(text, reply_markup=build_reply_keyboard_menu(), parse_mode="Markdown")
    # Inline menyuni ham ko'rsatish
    await message.answer("⚡ **Tezkor Boshqaruv:**", reply_markup=build_main_menu(), parse_mode="Markdown")


# ─── Yordamchi: Xavfsiz Tahrirlash ───────────────────────────

async def safe_edit_text(
    cb: CallbackQuery,
    text: str,
    reply_markup=None,
    parse_mode: str | None = "Markdown",
) -> None:
    """Xatoliklarsiz (message not modified yoki Markdown xatosi) xabarni xavfsiz tahrirlash."""
    try:
        await cb.message.edit_text(text=text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception as e:
        logger.debug("safe_edit_text xatosi: %s. Plain text bilan qayta urinilmoqda.", e)
        try:
            await cb.message.edit_text(text=text, reply_markup=reply_markup, parse_mode=None)
        except Exception:
            pass


# ─── Doimiy Pastki Klaviatura Handleri (Reply Keyboard) ──────

@router.message(ADMIN_FILTER, F.text.in_({"🎨 AI & Kreativ Studio", "AI & Kreativ Studio", "AI Studio", "ai studio"}))
async def rk_group_ai_studio(message: Message) -> None:
    """1-toifa: AI & Kreativ Studio guruh menyusi."""
    text = (
        "🎨 **AI & Kreativ Studio Bo'limi**\n\n"
        "Quyidagi vositalardan birini tanlang:\n"
        "• 🎨 **Rasm Chizish Studio** — FLUX.1 va Midjourney v6 rasm chizish\n"
        "• ⚡ **Hermes Agent** — Nous Hermes 3 avtonom fikrlovchi agent\n"
        "• 🔬 **Deep Research** — Chuqur ko'p manbali internet tadqiqoti\n"
        "• 💻 **Kod & Shartnoma Auditi** — Dasturiy kod va hujjatlar auditi\n"
        "• 🎙 **Ovozli Agent** — Tabiiy ovozli suhbat (STT & TTS)\n"
        "• 🎬 **Video Yuklovchi** — Instagram, TikTok, YouTube dan yuklash"
    )
    await message.answer(text, reply_markup=build_reply_ai_studio_menu(), parse_mode="Markdown")


@router.message(ADMIN_FILTER, F.text.in_({"💼 Ish & Unumdorlik", "Ish & Unumdorlik", "Unumdorlik", "unumdorlik"}))
async def rk_group_productivity(message: Message) -> None:
    """2-toifa: Ish & Unumdorlik guruh menyusi."""
    text = (
        "💼 **Ish & Unumdorlik Bo'limi**\n\n"
        "Kunlik ishlaringizni tartibga soluvchi vositalar:\n"
        "• 📝 **Vazifalar (Notion)** — Aqlli TodoList va Notion sinxronizatsiyasi\n"
        "• 🌐 **Saytlar (Uptime)** — Veb-sayt va serverlar onlayn monitoringi\n"
        "• 📧 **Email Pochta** — Xatlarni o'qish, AI xulosasi va xat yuborish\n"
        "• ⏰ **Eslatmalar** — Aniq vaqtli shaxsiy eslatmalar\n"
        "• 📰 **Yangiliklar & Tahlil** — Dasturlash, kitoblar va futbol yangiliklari\n"
        "• 👤 **Shaxsiy Profil (Mem0)** — AI o'rgangan xotirangiz va qiziqishlaringiz"
    )
    await message.answer(text, reply_markup=build_reply_productivity_menu(), parse_mode="Markdown")


@router.message(ADMIN_FILTER, F.text.in_({"📈 SMM & Marketing", "SMM & Marketing", "SMM", "smm"}))
async def rk_group_smm(message: Message) -> None:
    """3-toifa: SMM & Marketing guruh menyusi."""
    text = (
        "📈 **SMM & Marketing Bo'limi**\n\n"
        "Kanal va guruhlaringizni avtomatlashtirish:\n"
        "• 🎯 **Viral SMM** — Yuqori reaksiyali postlar va kontent-reja\n"
        "• ⏰ **Rejalashtirilgan Postlar** — Avtomatik taymerli post joylash\n"
        "• 🔍 **Raqobatchilar Tahlili** — Trendlar va raqobatchi kanallar monitoringi\n"
        "• 📡 **Telegram Xulosasi** — Akkauntingizdagi yangi xabarlar umumiy tahlili\n"
        "• 🔄 **Tarixni Sinxronlash** — Userbot orqali suhbatlar tarixini yangilash"
    )
    await message.answer(text, reply_markup=build_reply_smm_menu(), parse_mode="Markdown")


@router.message(ADMIN_FILTER, F.text.in_({"⚙️ Sozlamalar & Xotira", "Sozlamalar & Xotira", "Sozlamalar", "sozlamalar"}))
async def rk_group_settings(message: Message) -> None:
    """4-toifa: Sozlamalar & Xotira guruh menyusi."""
    text = (
        "⚙️ **Sozlamalar & Xotira Bo'limi**\n\n"
        "AI modeli va doimiy xotirani boshqarish:\n"
        "• 🤖 **AI Modellar** — Gemini, DeepSeek, Claude, Llama tanlash\n"
        "• 🎭 **Tizim Rollari** — Dasturchi, SMM mutaxassis, Tarjimon, Universal\n"
        "• 🧠 **Doimiy Xotira** — Saqlangan faktlar va RAG bazasi\n"
        "• 🧹 **Xotirani Tozalash** — Joriy chat kontekstini tozalash"
    )
    await message.answer(text, reply_markup=build_reply_settings_menu(), parse_mode="Markdown")


@router.message(ADMIN_FILTER, F.text.in_({"📊 Holat & Yordam", "Holat & Yordam", "Tizim & Yordam"}))
async def rk_group_system(message: Message) -> None:
    """5-toifa: Holat & Yordam guruh menyusi."""
    text = (
        "📊 **Tizim Holati & Yordam**\n\n"
        "• 📊 **Holat & Statistika** — Disk, RAM, modellar va bugungi statistika\n"
        "• 📋 **Bugungi Log** — Barcha amalga oshirilgan amallar hisoboti\n"
        "• 📱 **Mini App Paneli** — Veb boshqaruv panelini ochish\n"
        "• ❓ **Yordam** — To'liq buyruqlar va imkoniyatlar qo'llanmasi"
    )
    await message.answer(text, reply_markup=build_reply_system_menu(), parse_mode="Markdown")


@router.message(ADMIN_FILTER, F.text.in_({"🔙 Asosiy Menyu", "Asosiy Menyu", "asosiy menyu", "🔙 Orqaga", "Orqaga", "orqaga", "/menu", "menu", "Bosh Menyu", "bosh menyu"}))
async def rk_back_to_main(message: Message) -> None:
    """Bosh menyuga qaytish."""
    await message.answer(
        "🏠 **Asosiy Menyu:**\nQuyidagi toifalardan birini tanlang 👇",
        reply_markup=build_reply_keyboard_menu(),
        parse_mode="Markdown",
    )


def build_astrology_menu(has_profile: bool = False) -> InlineKeyboardMarkup:
    """Astrologiya interaktiv boshqaruv paneli klaviaturasi."""
    builder = InlineKeyboardBuilder()
    if has_profile:
        builder.row(
            InlineKeyboardButton(text="🌌 Natal Kartam", callback_data="astro:view_natal"),
            InlineKeyboardButton(text="🔄 Bugungi Tranzitlar", callback_data="astro:view_transits"),
        )
        builder.row(
            InlineKeyboardButton(text="☀️ Yillik Solyar Prognoz", callback_data="astro:view_solar"),
            InlineKeyboardButton(text="☪️ Arab Nuqtalari (Boylik)", callback_data="astro:view_arabic"),
        )
        builder.row(
            InlineKeyboardButton(text="🧠 AI Munajjim Tahlili", callback_data="astro:ai_report"),
        )
        builder.row(
            InlineKeyboardButton(text="✏️ Kartani Yangilash", callback_data="astro:setup"),
            InlineKeyboardButton(text="◀️ Orqaga", callback_data="menu:cat_ai"),
        )
    else:
        builder.row(
            InlineKeyboardButton(text="✨ Natal Karta Yaratish", callback_data="astro:setup"),
        )
        builder.row(
            InlineKeyboardButton(text="◀️ Orqaga", callback_data="menu:cat_ai"),
        )
    return builder.as_markup()


@router.message(ADMIN_FILTER, F.text.in_({"🔮 Astrologiya & Natal Karta", "Astrologiya & Natal Karta", "Astrologiya", "astrologiya", "/astrology", "/natal"}))
async def rk_astrology(message: Message) -> None:
    """Astrologiya va Natal Karta boshqaruv paneli."""
    profile = await db.get_astrology_profile(str(message.from_user.id))
    has_profile = bool(profile and profile.get("chart"))

    if has_profile:
        chart = profile["chart"]
        asc = chart.get("ascendant", {}).get("formatted", "Noma'lum")
        sun_sign = chart.get("planets", {}).get("Quyosh", {}).get("sign", "Noma'lum")
        moon_sign = chart.get("planets", {}).get("Oy", {}).get("sign", "Noma'lum")
        text = (
            f"🔮 **Professional Astrologiya & Natal Karta Paneli**\n\n"
            f"👤 **Egasining xaritasi:** `{profile.get('birth_date')}` `{profile.get('birth_time')}`, `{profile.get('city')}`\n"
            f"☀️ **Quyosh:** `{sun_sign}` | 🌙 **Oy:** `{moon_sign}`\n"
            f"🌟 **Ufq (Ascendant):** `{asc}`\n\n"
            f"Quyidagi bo'limlardan birini tanlang va professional tahlil oling 👇"
        )
    else:
        text = (
            "🔮 **Professional Astrologiya & Natal Karta Tizimi**\n\n"
            "Sizning tug'ilgan ma'lumotlaringiz hali kiritilmagan.\n\n"
            "📌 **Qanday kiritiladi?** Shunchaki chatga yozing:\n"
            "`/natal YYYY-MM-DD HH:MM Shahar`\n\n"
            "Masalan:\n"
            "• `/natal 1998-05-19 14:30 Toshkent`\n"
            "• `/natal 2001-11-05 09:15 Samarqand`\n\n"
            "Yoki quyidagi **'✨ Natal Karta Yaratish'** tugmasini bosing!"
        )

    await message.answer(text, reply_markup=build_astrology_menu(has_profile), parse_mode="Markdown")


@router.message(ADMIN_FILTER, Command("natal"))
async def cmd_natal_param(message: Message, command: CommandObject) -> None:
    """'/natal YYYY-MM-DD HH:MM Shahar' buyrug'i orqali natal karta hisoblash va saqlash."""
    args = (command.args or "").strip()
    if not args:
        await rk_astrology(message)
        return

    parts = args.split()
    date_str = parts[0] if len(parts) > 0 else ""
    time_str = parts[1] if len(parts) > 1 and ":" in parts[1] else "12:00"
    city_parts = parts[2:] if len(parts) > 2 else (parts[1:] if ":" not in time_str else ["Toshkent"])
    city_str = " ".join(city_parts) if city_parts else "Toshkent"

    wait_msg = await message.answer("🔭 **Astronomik koordinatalar va sayyoralar uylari hisoblanmoqda...**", parse_mode="Markdown")
    try:
        from core.astrology_agent import calculate_full_natal_chart, calculate_transits
        chart = calculate_full_natal_chart(date_str, time_str, city_str)
        await db.save_astrology_profile(
            user_id=str(message.from_user.id),
            birth_date=date_str,
            birth_time=time_str,
            city=city_str,
            chart_data=chart,
        )

        asc = chart["ascendant"]["formatted"]
        mc = chart["mc"]["formatted"]
        fortuna = chart["arabic_parts"]["Pars Fortuna (Omad va Boylik)"]["formatted"]
        spirit = chart["arabic_parts"]["Part of Spirit (Ruh va Iroda)"]["formatted"]

        p_lines = []
        for p_name, p_data in chart["planets"].items():
            p_lines.append(f"  • {p_data.get('planet_symbol', '●')} **{p_name}:** `{p_data.get('formatted')}` ({p_data.get('house')})")

        res_text = (
            f"🌌 **SHAXSIY NATAL KARTANGIZ TAYYOR BO'LDI!**\n\n"
            f"📅 **Sana va Vaqt:** `{date_str} {time_str}`\n"
            f"📍 **Joy:** `{chart['city']}` (GMT+{chart['tz']:.0f})\n"
            f"🌟 **Ufq (ASC):** `{asc}`\n"
            f"👑 **Cho'qqi (MC):** `{mc}`\n\n"
            f"🪐 **Sayyoralar Joylashuvi:**\n" + "\n".join(p_lines) + "\n\n"
            f"☪️ **Qadimiy Arab Nuqtalari:**\n"
            f"• 💰 **Pars Fortuna (Omad/Boylik):** `{fortuna}`\n"
            f"• 🕊 **Part of Spirit (Ruh/Maqsad):** `{spirit}`\n\n"
            f"✅ **Karta xotiraga saqlandi!** Endi barcha AI modellar (Hermes, Gemini, DeepSeek) ushbu xaritaning xususiyatlarini biladi."
        )
        await safe_edit_or_send_long_message(wait_msg, res_text, reply_markup=build_astrology_menu(True), parse_mode="Markdown")
    except Exception as e:
        logger.error("cmd_natal xatosi: %s", e)
        try:
            await wait_msg.edit_text(f"❌ Xatolik yuz berdi: {e}\nMisol: `/natal 1998-05-19 14:30 Toshkent`", parse_mode=None)
        except Exception:
            pass


@router.message(ADMIN_FILTER, Command("transit"))
async def cmd_transits(message: Message) -> None:
    """Bugungi kun sayyoralarining natal kartaga ta'sirini ko'rish."""
    profile = await db.get_astrology_profile(str(message.from_user.id))
    if not profile or not profile.get("chart"):
        await message.answer("⚠️ Avval natal kartangizni kiriting: `/natal YYYY-MM-DD HH:MM Shahar`", parse_mode="Markdown")
        return

    from core.astrology_agent import calculate_transits
    chart = profile["chart"]
    transits = calculate_transits(chart.get("planets", {}))

    if not transits:
        await message.answer("🌟 **Bugun sayyoralarda keskin noqulay tranzitlar yo'q.** Tinch va osoyishta davr.")
        return

    lines = [f"🔄 **BUGUNGI KUNINGIZ UCHUN FAOL TRANZITLAR ({datetime.date.today().strftime('%d.%m.%Y')}):**\n"]
    for t in transits:
        lines.append(f"• **{t['transiting_planet']}** {t['symbol']} **{t['natal_planet']}** ({t['orb']}°)\n  └ _{t['meaning']}_")

    await message.answer("\n".join(lines), parse_mode="Markdown")


@router.message(ADMIN_FILTER, Command("solar"))
async def cmd_solar(message: Message, command: CommandObject) -> None:
    """Yillik Quyosh qaytishi (Solar Return) prognozi."""
    profile = await db.get_astrology_profile(str(message.from_user.id))
    if not profile or not profile.get("chart"):
        await message.answer("⚠️ Avval natal kartangizni kiriting: `/natal YYYY-MM-DD HH:MM Shahar`", parse_mode="Markdown")
        return

    from core.astrology_agent import calculate_solar_return_summary
    target_year = 2026
    if command.args and command.args.strip().isdigit():
        target_year = int(command.args.strip())

    chart = profile["chart"]
    sun_lon = chart.get("planets", {}).get("Quyosh", {}).get("longitude", 0.0)
    solar_info = calculate_solar_return_summary(sun_lon, target_year=target_year)

    text = (
        f"☀️ **SOLYAR KARTA — {target_year}-YIL UCHUN SHAXSIY PROGNOZ**\n\n"
        f"🌟 **Quyosh darajasi:** `{solar_info['natal_sun_degree']}`\n\n"
        f"📋 **Yilning Asosiy Tendensiyalari:**\n"
        + "\n".join(solar_info["key_themes"])
    )
    await message.answer(text, parse_mode="Markdown")


@router.message(ADMIN_FILTER, F.text.in_({"🎨 Rasm Chizish", "Rasm Chizish", "rasm chizish", "🎨 Rasm Chizish Studio", "Rasm Chizish Studio", "🎨 Midjourney Rasm", "Midjourney Rasm", "midjourney rasm", "/imagine", "/midjourney"}))
async def rk_midjourney(message: Message) -> None:
    """Reply keyboard '🎨 Rasm Chizish' tugmasi — interaktiv AI Studio paneli ochiladi."""
    user_id = message.from_user.id if message.from_user else 0
    text, markup = build_image_studio_panel(user_id)
    await message.answer(text, reply_markup=markup, parse_mode="HTML")


@router.message(ADMIN_FILTER, F.text.in_({"⚡ Hermes Agent", "Hermes Agent", "hermes agent", "/hermes"}))
async def rk_hermes(message: Message, ai_manager: AIManager) -> None:
    ai_manager.switch_role("hermes_agent")
    text = (
        "⚡ **Nous Hermes 3 Avtonom Agent Faollashtirildi!**\n\n"
        "Hermes 3 — chuqur mantiqiy fikrlash (deep reasoning), ko'p bosqichli rejalashtirish, "
        "aniq hisob-kitoblar va avtonom muammolarni hal qilish bo'yicha dunyodagi eng kuchli ochiq agentdir.\n\n"
        "**Siz unga murakkab topshiriqlar berishingiz mumkin:**\n"
        "• `/hermes Yangi startap loyiha uchun 6 oylik biznes reja, moliyaviy hisob-kitob va marketing strategiyasi tuzib ber`\n"
        "• `hermes: O'zbekiston IT bozoridagi eng istiqbolli 5 ta sohani hisob-kitoblar bilan tahlil qil`\n"
        "• Har qanday matematik yoki mantiqiy masalani bevosita yozishingiz mumkin!"
    )
    await message.answer(text, parse_mode="Markdown")


@router.message(ADMIN_FILTER, F.text.in_({"📝 Vazifalar (Notion)", "Vazifalar (Notion)", "vazifalar", "vazifalarim", "/todo", "todolist"}))
async def rk_todo(message: Message) -> None:
    from core.todo_notion_agent import format_tasks_list_report
    text, markup = await format_tasks_list_report()
    await message.answer(text, reply_markup=markup, parse_mode="Markdown")


@router.message(ADMIN_FILTER, F.text.in_({"🌐 Saytlar (Uptime)", "Saytlar (Uptime)", "saytlar", "uptime", "/uptime"}))
async def rk_uptime(message: Message) -> None:
    from core.uptime_agent import format_uptime_dashboard_report
    text, markup = await format_uptime_dashboard_report()
    await message.answer(text, reply_markup=markup, parse_mode="Markdown")


@router.message(ADMIN_FILTER, F.text.in_({"📰 Yangiliklar & Tahlil", "Yangiliklar & Tahlil", "yangiliklar", "yangilik", "/news"}))
async def rk_news(message: Message, ai_manager: AIManager) -> None:
    from core.news_football_agent import get_topic_news
    text, markup = await get_topic_news("dasturlash", ai_manager)
    await message.answer(text, reply_markup=markup, parse_mode="Markdown")


@router.message(ADMIN_FILTER, F.text.in_({"👤 Shaxsiy Profil (Mem0)", "Shaxsiy Profil (Mem0)", "profilim", "Profilim", "/profile", "profil memo", "memo", "mem0"}))
async def rk_profile(message: Message) -> None:
    from core.mem0_agent import get_user_profile_report, build_profile_keyboard
    wait_msg = await message.answer("⏳ Mem0 xotirasi tekshirilmoqda...")
    profile_text = await get_user_profile_report(message.from_user.id)
    await wait_msg.edit_text(profile_text, reply_markup=build_profile_keyboard(), parse_mode="Markdown")


@router.message(ADMIN_FILTER, F.text.in_({"🎙 Ovozli Agent (STT & TTS)", "🎙 Ovozli Agent (TTS)", "Ovozli Agent (TTS)", "ovozli xabar", "Ovozli xabar", "/voice"}))
async def rk_tts(message: Message) -> None:
    text = (
        "🎙 **Ovozli AI Agent (Speech-to-Text & Text-to-Speech)**\n\n"
        "AI bilan to'liq ovozli rejimda suhbatlashishingiz mumkin!\n\n"
        "**Imkoniyatlar:**\n"
        "1. **Ovozli xabar yuborish (STT):**\n"
        "   Telegramda ovozli xabar yozib yuboring (o'zbek, rus, ingliz) — bot uni so'zma-so'z tinglab, buyrug'ingizni bajaradi!\n\n"
        "2. **Ovozli javob olish (TTS):**\n"
        "   Bot javobni insondek tabiiy o'zbek ovozida (Madina / Sardor) ovozli xabar ko'rinishida yuboradi.\n\n"
        "3. **Matnni ovozga aylantirish:**\n"
        "   `/voice Salom, bugun qanday yangiliklar bor?`\n\n"
        "4. **Ovozli vazifalar:**\n"
        "   *\"Vazifa qo'sh: Ertaga soat 10 da hisobot topshirish\"* deb ovoz yozsangiz, u avtomatik Notion rejalarga tushadi!"
    )
    await message.answer(text, parse_mode="Markdown")


@router.message(ADMIN_FILTER, F.text.in_({"🔬 Deep Research", "Deep Research", "/research", "/tadqiqot"}))
async def rk_deep_research(message: Message) -> None:
    text = (
        "🔬 **Deep Research Agent (Chuqur Internet Tadqiqoti)**\n\n"
        "OpenAI Deep Research tamoyilida ishlovchi avtonom agent!\n"
        "U internetdagi 3-5 ta manbani parallel qidirib, solishtirib, to'liq ilmiy va analitik hisobot tuzadi.\n\n"
        "📌 **Qanday ishlatiladi?**\n"
        "`/research O'zbekistonda 2026-yilda quyosh energetikasi istiqbollari`\n"
        "`/tadqiqot Kripto bozoridagi eng so'nggi o'zgarishlar va trendlar`"
    )
    await message.answer(text, parse_mode="Markdown")


@router.message(ADMIN_FILTER, F.text.in_({"💻 Kod & Shartnoma Auditi", "Kod & Shartnoma Auditi", "/code", "/audit", "/inspect"}))
async def rk_code_audit(message: Message) -> None:
    text = (
        "💻 **Kod Auditi & Shartnoma Tahlilchisi**\n\n"
        "1. **Dasturiy Kod Auditi & Bug Fixer:**\n"
        "   Koddagi xatolar, xavfsizlik zaifliklari va sekinlashuvlarni topib, tayyor to'g'irlangan kod beradi:\n"
        "   `/code def login(user, pass): db.execute('SELECT * FROM users WHERE...')`\n\n"
        "2. **Smart Shartnoma & Hujjat Tahlili:**\n"
        "   Shartnomadagi yashirin xatarlar, jarimalar va bir tomonlama majburiyatlarni tekshiradi:\n"
        "   `/inspect [shartnoma matnini yuboring]`\n"
        "   yoki botga to'g'ridan-to'g'ri PDF/DOCX shartnoma faylini yuboring!"
    )
    await message.answer(text, parse_mode="Markdown")


@router.message(ADMIN_FILTER, F.text.in_({"🎯 Viral SMM", "Viral SMM", "/smm", "/viral", "/post"}))
async def rk_viral_smm(message: Message) -> None:
    text = (
        "🎯 **Viral SMM & Content Strategy Agent**\n\n"
        "Telegram kanallar, Instagram va YouTube uchun millionlab ko'rishlar keltiruvchi kontent-paket tayyorlaydi!\n\n"
        "📦 **Hisobot tarkibi:**\n"
        "• 3 xil kuchli Hook (intriga, fakt, og'riqli savol)\n"
        "• Yuqori konversiyali asosiy post matni\n"
        "• Harakatga undovchi CTA va trend hashtaglar\n"
        "• 7 kunlik haftalik kontent-reja matritsasi\n\n"
        "📌 **Ishlatish:**\n"
        "`/smm Sun'iy intellekt va dasturlash kanali uchun`\n"
        "`/post Yangi online kurs sotuvi uchun`"
    )
    await message.answer(text, parse_mode="Markdown")


@router.message(ADMIN_FILTER, F.text.in_({"🤖 Avtonom Agent Skillari", "Avtonom Agent Skillari", "Avtonom Agent", "/autotask", "/autonomous"}))
async def rk_autonomous_skills(message: Message) -> None:
    """Avtonom Agentning 4 ta asosiy skillari qo'llanmasi."""
    text = (
        "🤖 **Avtonom Agent 4 ta Asosiy Skilli (100% Avtomatlashtirilgan):**\n\n"
        "Shunchaki botga tabiiy tilda buyruq bering — agent intentni darhol aniqlab, o'zi bajaradi:\n\n"
        "1. 📢 **Kanalga Avtonom Post Chiqarish:**\n"
        "• `@kanalim ga AI yangiliklari haqida post chiqar`\n"
        "• `Kanalga motivatsiya haqida post tayyorlab joyla va rasm ham chiz`\n\n"
        "2. 👥 **Guruhga Avtonom Anons / Xabar:**\n"
        "• `@dasturchilar guruhiga bugun soat 20:00 dagi meetup haqida anons ber`\n"
        "• `IT Guruh ga yangi video haqida xabar yubor`\n\n"
        "3. 🤖 **Boshqa Botlar Bilan Muloqot (Inter-Bot Communication):**\n"
        "• `@vkmusic_bot ga /start deb yoz`\n"
        "• `@midjourney_bot ga /imagine cyber samurai deb yoz`\n"
        "*(Bot javobi va yuklagan fayllari to'g'ridan-to'g'ri sizga yetkaziladi)*\n\n"
        "4. ⏰ **Rejalashtirilgan va Muntazam Postlar:**\n"
        "• `Ertaga soat 10:00 da @kanalim ga motivatsion post rejalashtir`\n"
        "• `2026-09-20 18:00 da guruhga anons chiqar: ...`\n\n"
        "⚡ *Hech qanday qo'shimcha menyu shart emas — botga to'g'ridan-to'g'ri shunday yozing!*"
    )
    await message.answer(text, parse_mode="Markdown")


@router.message(ADMIN_FILTER, F.text.in_({"🎬 Video Yuklovchi", "Video Yuklovchi", "video yukla", "/video", "/dl"}))
async def rk_video_downloader(message: Message) -> None:
    text = (
        "🎬 **Instagram, TikTok, YouTube Video Yuklovchi Agenti**\n\n"
        "Menga ijtimoiy tarmoqdagi video havolasini yuboring:\n"
        "• 📸 **Instagram Reels / Post:** `https://www.instagram.com/reel/...`\n"
        "• 🎵 **TikTok (100% Suvsiz HD):** `https://vt.tiktok.com/...`\n"
        "• ▶️ **YouTube Shorts / Video:** `https://youtube.com/shorts/...`\n"
        "• 🐦 **X (Twitter):** `https://x.com/.../status/...`\n\n"
        "Bot videoni darhol Telegram orqali MP4 formatda sizga jo'natadi!"
    )
    await message.answer(text, parse_mode="Markdown")


@router.message(ADMIN_FILTER, F.text.in_({"🤖 AI Modellar", "AI Modellar", "ai modellar", "Modellar", "modellar", "/models"}))
async def rk_models(message: Message) -> None:
    await message.answer("🤖 **AI Modelini tanlang:**", reply_markup=build_models_menu(), parse_mode="Markdown")


@router.message(ADMIN_FILTER, F.text.in_({"🎭 Tizim Rollari", "Tizim Rollari", "tizim rollari", "Rollar", "rollar", "/roles"}))
async def rk_roles(message: Message) -> None:
    await message.answer("🎭 **Tizim rolini tanlang:**", reply_markup=build_roles_menu(), parse_mode="Markdown")


@router.message(ADMIN_FILTER, F.text.in_({"🧠 Doimiy Xotira", "Doimiy Xotira", "doimiy xotira", "Xotira", "xotira", "/memory", "/kb"}))
async def rk_memory(message: Message) -> None:
    facts = await db.get_all_facts()
    if not facts:
        text = (
            "🧠 **Doimiy Xotira (RAG Knowledge Base)**\n\n"
            "Hozircha saqlangan faktlar yo'q.\n\n"
            "💡 Yangi fakt qo'shish uchun botga shunchaki yozing:\n"
            "• `Eslab qol: Karta raqamim: 8600 1234 5678 9012`\n"
            "• `Eslab qol: Manzil: Toshkent, Chilonzor...`\n"
            "• Yoki rezyume / mahsulotlar ro'yxatini (Word/PDF) tashlang!"
        )
    else:
        lines = [f"🧠 **Doimiy Xotiradagi Faktlar ({len(facts)} ta):**\n"]
        for f in facts:
            lines.append(f"• `{f.get('key')}`: {f.get('content')}")
        lines.append("\n💡 /clear qilinsa ham agent ushbu faktlarni doim eslab qoladi!")
        text = "\n".join(lines)
    await message.answer(text[:4000], parse_mode="Markdown")


@router.message(ADMIN_FILTER, F.text.in_({"📊 Holat & Statistika", "Holat & Statistika", "holat & statistika", "Statistika", "statistika", "Holat", "holat", "/status"}))
async def rk_status(message: Message, ai_manager: AIManager) -> None:
    from core.cleaner_agent import get_system_storage_info
    status_info = ai_manager.status()
    stats = await db.get_stats_summary()
    storage = get_system_storage_info()
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🧹 Server Keshini Tozalash", callback_data="clean:server"))
    text = (
        f"{status_info}\n\n"
        f"📊 **Bugungi Statistika:**\n"
        f"• Xabarlar: `{stats['today_user_messages']}` ta\n"
        f"• Userbot yuboruvlari: `{stats['today_userbot_sends']}` ta\n"
        f"• Doimiy xotira (RAG): `{stats['knowledge_count']}` ta fakt\n"
        f"• Rejalashtirilgan postlar: `{stats['pending_posts']}` ta\n"
        f"• Raqobatchi kanallar: `{stats['competitors_count']}` ta\n\n"
        f"🖥 **Server Xotirasi (Disk):**\n"
        f"• Jami: `{storage['total_gb']} GB` | Bo'sh: `{storage['free_gb']} GB` (`{storage['percent']}% band`)\n"
        f"• Asosiy baza: `{storage['db_size_mb']} MB`"
    )
    await message.answer(text, reply_markup=builder.as_markup(), parse_mode="Markdown")


@router.message(ADMIN_FILTER, F.text.in_({"📧 Email Pochta", "Email Pochta", "email pochta", "Pochta", "pochta", "Email", "email", "/email"}))
async def rk_email(message: Message, ai_manager: AIManager) -> None:
    from handlers.email_handler import get_email_agent, build_email_menu
    agent = get_email_agent()
    configured = agent.is_configured()
    status_text = f"✅ Ulangan: `{agent.user}`" if configured else "⚠️ Sozlanmagan"
    await message.answer(
        f"📧 **Shaxsiy Email Agent**\n\nHolat: {status_text}",
        reply_markup=build_email_menu(configured),
        parse_mode="Markdown",
    )


@router.message(ADMIN_FILTER, F.text.in_({"📡 Telegram Xulosasi", "Telegram Xulosasi", "telegram xulosasi", "Telegram", "telegram", "/tg", "/summary"}))
async def rk_tg_summary(message: Message, ai_manager: AIManager) -> None:
    wait_msg = await message.answer("⏳ Telegram akkauntingizdagi so'nggi suhbatlar yuklanmoqda va AI tahlili qilinmoqda...")
    summary = await summarize_telegram_activity(ai_manager)
    await safe_edit_or_send_long_message(wait_msg, summary, parse_mode="Markdown")


@router.message(ADMIN_FILTER, F.text.in_({"⏰ Eslatmalar", "Eslatmalar", "eslatmalar", "eslatmalarim", "/reminders"}))
async def rk_reminders(message: Message) -> None:
    active = await db.get_active_reminders(message.chat.id)
    if not active:
        await message.answer(
            "⏰ **Faol eslatmalar mavjud emas.**\n\n"
            "💡 Yangi eslatma qo'shish juda oson. Shunchaki botga yozing:\n"
            "• `21:30 da bot orqali menga eslat: dori ichish`\n"
            "• `15 daqiqadan keyin eslat: choy damlash`\n"
            "• `Ertaga soat 10:00 da eslat: Akmal bilan uchrashuv`\n\n"
            "Bot belgilangan vaqtda signal beradi va 'Bajarildi' yoki 'Kechiktirish' tugmalarini chiqaradi.",
            parse_mode="Markdown",
        )
        return

    lines = [f"⏰ **Faol Eslatmalar Ro'yxati ({len(active)} ta):**\n"]
    builder = InlineKeyboardBuilder()
    for r in active:
        lines.append(f"• `#{r['id']}` [{r['remind_at']}] {r['text']}")
        builder.row(InlineKeyboardButton(text=f"❌ #{r['id']} ni bekor qilish", callback_data=f"del_rem:{r['id']}"))
    lines.append("\nBekor qilish uchun kerakli tugmani bosing.")
    await message.answer("\n".join(lines), reply_markup=builder.as_markup(), parse_mode="Markdown")


@router.message(ADMIN_FILTER, F.text.in_({"⏰ Rejalashtirilgan Postlar", "Rejalashtirilgan Postlar", "rejalashtirilgan postlar", "Postlar", "postlar", "/schedule", "/posts"}))
async def rk_scheduled_posts(message: Message) -> None:
    posts = await db.get_all_pending_posts()
    if not posts:
        await message.answer(
            "⏰ **Kutilayotgan postlar yo'q.**\n\n"
            "Yangi post rejalashtirish uchun botga yozing:\n"
            "`rejalashtir: @kanal_nomi 2026-09-17 10:00 Post matni...`",
            parse_mode="Markdown",
        )
        return

    lines = [f"⏰ **Kutilayotgan Rejalashtirilgan Postlar ({len(posts)} ta):**\n"]
    for p in posts:
        lines.append(f"• ID #{p['id']} ➔ `{p['chat_id']}` | Vaqt: `{p['scheduled_time']}`\n  _{p['text'][:80]}..._\n")
    await message.answer("\n".join(lines)[:4000], parse_mode="Markdown")


@router.message(ADMIN_FILTER, F.text.in_({"🔍 Raqobatchilar Tahlili", "Raqobatchilar Tahlili", "raqobatchilar tahlili", "Raqobatchilar", "raqobatchilar", "/competitors"}))
async def rk_competitors(message: Message) -> None:
    comps = await db.get_competitors()
    if not comps:
        await message.answer(
            "📡 **Kuzatilayotgan raqobatchilar ro'yxati bo'sh.**\n\n"
            "Kanal qo'shish uchun:\n"
            "`/add_competitor @kanal_nomi` deb yozing!",
            parse_mode="Markdown",
        )
        return

    lines = [f"📊 **Kuzatilayotgan Raqobatchi Kanallar ({len(comps)} ta):**\n"]
    for c in comps:
        lines.append(f"• @{c}")
    lines.append("\nHar kuni soat 10:00 da ushbu kanallardagi eng sara trendlar bo'yicha hisobot tayyorlanadi.")
    await message.answer("\n".join(lines), parse_mode="Markdown")


@router.message(ADMIN_FILTER, F.text.in_({"🔄 Tarixni Sinxronlash", "Tarixni Sinxronlash", "tarixni sinxronlash", "/sync", "/sync_history", "tarixni yukla", "suhbatlarni eslab qol"}))
async def rk_sync_history(message: Message, ai_manager: AIManager) -> None:
    """Telegram suhbatidan barcha avvalgi xabarlarni o'qib bazaga saqlash."""
    from core.userbot import sync_chat_history_from_telegram, userbot
    from core.safe_send import safe_message_reply

    if userbot is None or not userbot.is_connected():
        await safe_message_reply(
            message,
            "⚠️ **Userbot ulanmagan.**\n\n"
            "Telegramdagi yozishmalarni to'g'ridan-to'g'ri o'qish uchun `.env` faylida `USERBOT_SESSION` ko'rsatilgan bo'lishi kerak.",
            parse_mode="Markdown",
        )
        return

    wait_msg = await message.reply("🔄 **Telegram suhbati o'qilmoqda va bazaga qayta saqlanmoqda...**", parse_mode="Markdown")
    try:
        bot_user = await message.bot.get_me()
        target = bot_user.username or message.chat.id
        res = await sync_chat_history_from_telegram(
            target_username_or_id=target,
            ai_manager=ai_manager,
            limit=100,
        )
        await safe_message_reply(message, res.get("message", "Tayyor."), parse_mode="Markdown")
    except Exception as exc:
        logger.error("rk_sync_history xatosi: %s", exc)
        await safe_message_reply(message, f"❌ Xatolik: {exc}", parse_mode=None)


@router.message(ADMIN_FILTER, F.text.in_({"🧹 Xotirani Tozalash", "Xotirani Tozalash", "xotirani tozalash", "Tozalash", "tozalash", "/clear"}))
async def rk_clear_history(message: Message, ai_manager: AIManager) -> None:
    res = ai_manager.clear_history(chat_id=str(message.chat.id))
    await message.answer(res, parse_mode="Markdown")


@router.message(ADMIN_FILTER, F.text.in_({"❓ Yordam", "Yordam", "yordam", "/help", "help"}))
async def rk_help(message: Message) -> None:
    await cmd_help(message)


@router.message(ADMIN_FILTER, F.text.in_({"📱 Mini App Paneli", "Mini App Paneli", "mini app paneli", "Mini App", "mini app", "/webapp", "/panel"}))
async def rk_mini_app(message: Message) -> None:
    target_web_url = get_clean_webapp_url()
    if target_web_url:
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="🚀 Mini Appni Ochish (Ilova)", web_app=WebAppInfo(url=target_web_url)))
        builder.row(InlineKeyboardButton(text="🌐 Brauzerda Ochish", url=target_web_url))
        await message.answer(
            f"📱 **Super-Agent 2.0 Telegram Mini App:**\n\n"
            f"⚡ Quyidagi **'🚀 Mini Appni Ochish (Ilova)'** tugmasini bosing yoki Telegram chat oynasining chap pastki burchagidagi **'📱 Mini App'** menyu tugmasidan foydalaning!\n\n"
            f"🔗 Manzil: `{target_web_url}`",
            reply_markup=builder.as_markup(),
            parse_mode="Markdown",
        )
    else:
        await message.answer(
            "📱 **Telegram Mini App Paneli:**\n\n"
            "Mini Appni Telegram ichida to'g'ridan-to'g'ri ochish uchun `.env` faylingizda `WEBAPP_URL` manzilini ko'rsating:\n"
            "`WEBAPP_URL=https://sizning-domen.onrender.com`\n\n"
            "Shuningdek brauzerda ham kirish mumkin: `http://localhost:8080/webapp`",
            parse_mode="Markdown",
        )


@router.message(ADMIN_FILTER, Command("help"))
async def cmd_help(message: Message) -> None:
    """Yordam xabari."""
    text = (
        "📖 **Super-Agent 2.0 Enterprise Qo'llanmasi**\n\n"
        "**🚀 Agentik & AI Buyruqlari:**\n"
        "• `/imagine [tasvir]` — Midjourney v6 fotorealistik rasm chizish (100% bepul)\n"
        "• `/hermes [topshiriq]` — Nous Hermes 3 avtonom rejalashtiruvchi va chuqur fikrlovchi agent\n"
        "• `/voice [matn]` — Microsoft Edge TTS orqali tabiiy ovozli xabar (o'zbek/rus/ingliz)\n"
        "• `/profile` — Mem0 shaxsiy adaptiv xotira va profilingiz tahlili\n"
        "• `/todo` — Aqlli TodoList va Notion vazifalar menejeri\n"
        "• `/uptime` — Veb-saytlar va serverlar monitoringi (har 10 daqiqada tekshiruv)\n"
        "• `/news` — Dasturlash, O'zbekiston va kitoblar bo'yicha jonli tahliliy yangiliklar\n"
        "• `/disk` & `/clean_server` — Server disk monitoringi va xavfsiz tozalash\n"
        "• `/crawl [url]` — Crawl4AI orqali saytni LLM uchun toza Markdown formatida o'qish\n"
        "• `/screenshot [url]` — Browser-use orqali real-time veb-sayt skrinshotini olish\n"
        "• `/status` — AI modeli va tizim holati\n"
        "• `/clear` — Xotirani tozalash\n"
        "• `/log` — Bugungi faoliyat xulosasi\n"
        "• `/userbot` — Userbot holati\n\n"
        "**📁 Hujjatlar (Microsoft MarkItDown):**\n"
        "Istalgan PDF, Word (DOCX), Excel (XLSX), PowerPoint (PPTX) yoki CSV faylni yuboring — agent uni bir lahzada tahlil qilib, xulosa yoki savollaringizga javob beradi.\n\n"
        "**🎙 Ovozli Muloqot & Vazifalar:**\n"
        "Botga ovozli xabar yuboring — agent ovozingizni tushunib, o'zi ham tabiiy inson ovozida javob qaytaradi! 'Vazifa qo'sh: ...' desangiz avtomat TodoList'ga saqlaydi.\n\n"
        "**📧 Email Agent:**\n"
        "• `pochta` yoki `email tekshir` → O'qilmagan xatlar va AI xulosasi\n"
        "• `email ai: user@example.com | vazifa` → AI xat tayyorlash\n"
        "• `email: user@example.com | Mavzu | Matn` → To'g'ridan-to'g'ri xat\n\n"
        "**🎨 Rasmlar va Multimodal:**\n"
        "Rasm yuborib matn yozing yoki filtr qo'llang:\n"
        "• `grayscale`, `blur`, `sharpen`, `watermark [matn]`, `resize [W] [H]`\n\n"
        "**⚡ Userbot Buyruqlari:**\n"
        "• `yoz @username: [xabar]` → Userbot orqali xabar yuborish\n"
        "• `post: @kanal [matn]` → Kanalga post tayyorlash\n"
        "• `suhbatlar` → Oxirgi Telegram suhbatlari"
    )
    await message.answer(text, parse_mode="Markdown")


@router.message(ADMIN_FILTER, Command("status"))
async def cmd_status(message: Message, ai_manager: AIManager) -> None:
    await message.answer(ai_manager.status(chat_id=str(message.chat.id)), parse_mode="Markdown")


@router.message(ADMIN_FILTER, Command("clear"))
async def cmd_clear(message: Message, ai_manager: AIManager) -> None:
    result = ai_manager.clear_history(chat_id=str(message.chat.id))
    await message.answer(result, parse_mode="Markdown")


@router.message(ADMIN_FILTER, Command("log"))
async def cmd_log(message: Message) -> None:
    collector = LogCollector()
    summary = collector.build_summary_text()
    await message.answer(summary, parse_mode="Markdown")


@router.message(ADMIN_FILTER, Command("userbot"))
async def cmd_userbot(message: Message) -> None:
    info = await get_userbot_info()
    await message.answer(info, parse_mode="Markdown")


# ─── Callback Handlerlari ─────────────────────────────────────

@router.callback_query(ADMIN_FILTER, F.data == "menu:main")
async def cb_main_menu(cb: CallbackQuery, ai_manager: AIManager) -> None:
    await cb.answer()
    await safe_edit_text(
        cb,
        "🏠 **Asosiy Boshqaruv Menyusi:**\nQuyidagi toifalardan birini tanlang 👇",
        reply_markup=build_main_menu(),
    )


@router.callback_query(ADMIN_FILTER, F.data == "menu:cat_ai")
async def cb_cat_ai(cb: CallbackQuery) -> None:
    """Inline: AI & Kreativ Studio toifasi."""
    await cb.answer()
    await safe_edit_text(
        cb,
        "🎨 **AI & Kreativ Studio**\n\nKerakli ijodiy va agentik vositani tanlang:",
        reply_markup=build_inline_ai_menu(),
    )


@router.callback_query(ADMIN_FILTER, F.data == "menu:astrology")
async def cb_menu_astrology(cb: CallbackQuery) -> None:
    """Astrologiya bosh menyusi."""
    await cb.answer()
    profile = await db.get_astrology_profile(str(cb.from_user.id))
    has_profile = bool(profile and profile.get("chart"))
    if has_profile:
        chart = profile["chart"]
        asc = chart.get("ascendant", {}).get("formatted", "Noma'lum")
        sun = chart.get("planets", {}).get("Quyosh", {}).get("sign", "Noma'lum")
        moon = chart.get("planets", {}).get("Oy", {}).get("sign", "Noma'lum")
        text = (
            f"🔮 **Professional Astrologiya & Natal Karta**\n\n"
            f"👤 `{profile.get('birth_date')} {profile.get('birth_time')}`, `{profile.get('city')}`\n"
            f"☀️ Quyosh: `{sun}` | 🌙 Oy: `{moon}`\n"
            f"🌟 Ufq (ASC): `{asc}`\n\n"
            f"Bo'limni tanlang 👇"
        )
    else:
        text = (
            "🔮 **Professional Astrologiya & Natal Karta**\n\n"
            "Sizning tug'ilgan ma'lumotlaringiz hali kiritilmagan.\n"
            "Kiritish uchun chatga yozing:\n"
            "`/natal 1998-05-19 14:30 Toshkent`"
        )
    await safe_edit_text(cb, text, reply_markup=build_astrology_menu(has_profile))


@router.callback_query(ADMIN_FILTER, F.data == "astro:view_natal")
async def cb_astro_view_natal(cb: CallbackQuery) -> None:
    """Natal kartani ko'rish."""
    await cb.answer()
    profile = await db.get_astrology_profile(str(cb.from_user.id))
    if not profile or not profile.get("chart"):
        await cb.answer("Karta topilmadi", show_alert=True)
        return

    chart = profile["chart"]
    asc = chart.get("ascendant", {}).get("formatted")
    mc = chart.get("mc", {}).get("formatted")
    p_lines = []
    for p_name, p_data in chart.get("planets", {}).items():
        p_lines.append(f"• {p_data.get('planet_symbol', '●')} **{p_name}:** `{p_data.get('formatted')}` ({p_data.get('house', '1-Uy')})")

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ Orqaga", callback_data="menu:astrology"))
    text = (
        f"🌌 **SHAXSIY NATAL XARITANGIZ:**\n\n"
        f"📅 `{profile.get('birth_date')} {profile.get('birth_time')}`, `{profile.get('city')}`\n"
        f"🌟 **Ufq (ASC):** `{asc}`\n"
        f"👑 **Cho'qqi (MC):** `{mc}`\n\n"
        f"🪐 **Sayyoralar:**\n" + "\n".join(p_lines)
    )
    await safe_edit_text(cb, text, reply_markup=builder.as_markup())


@router.callback_query(ADMIN_FILTER, F.data == "astro:view_transits")
async def cb_astro_view_transits(cb: CallbackQuery) -> None:
    """Joriy tranzitlarni ko'rish."""
    await cb.answer()
    profile = await db.get_astrology_profile(str(cb.from_user.id))
    if not profile or not profile.get("chart"):
        await cb.answer("Karta topilmadi", show_alert=True)
        return

    from core.astrology_agent import calculate_transits
    chart = profile["chart"]
    transits = calculate_transits(chart.get("planets", {}))

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ Orqaga", callback_data="menu:astrology"))

    if not transits:
        await safe_edit_text(cb, "🌟 **Bugun sayyoralarda keskin noqulay tranzitlar yo'q.** Tinch va osoyishta davr.", reply_markup=builder.as_markup())
        return

    lines = [f"🔄 **BUGUNGI KUN UCHUN FAOL TRANZITLAR ({datetime.date.today().strftime('%d.%m.%Y')}):**\n"]
    for t in transits[:7]:
        lines.append(f"• **{t['transiting_planet']}** {t['symbol']} **{t['natal_planet']}** ({t['orb']}°)\n  └ _{t['meaning']}_")

    await safe_edit_text(cb, "\n".join(lines), reply_markup=builder.as_markup())


@router.callback_query(ADMIN_FILTER, F.data == "astro:view_solar")
async def cb_astro_view_solar(cb: CallbackQuery) -> None:
    """Solyar hisobotni ko'rish."""
    await cb.answer()
    profile = await db.get_astrology_profile(str(cb.from_user.id))
    if not profile or not profile.get("chart"):
        await cb.answer("Karta topilmadi", show_alert=True)
        return

    from core.astrology_agent import calculate_solar_return_summary
    chart = profile["chart"]
    sun_lon = chart.get("planets", {}).get("Quyosh", {}).get("longitude", 0.0)
    solar_info = calculate_solar_return_summary(sun_lon, target_year=2026)

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ Orqaga", callback_data="menu:astrology"))
    text = (
        f"☀️ **SOLYAR KARTA — 2026-YIL UCHUN PROGNOZ**\n\n"
        f"🌟 Quyosh darajasi: `{solar_info['natal_sun_degree']}`\n\n"
        f"📋 **Yilning Asosiy Tendensiyalari:**\n"
        + "\n".join(solar_info["key_themes"])
    )
    await safe_edit_text(cb, text, reply_markup=builder.as_markup())


@router.callback_query(ADMIN_FILTER, F.data == "astro:view_arabic")
async def cb_astro_view_arabic(cb: CallbackQuery) -> None:
    """Arab nuqtalarini ko'rish."""
    await cb.answer()
    profile = await db.get_astrology_profile(str(cb.from_user.id))
    if not profile or not profile.get("chart"):
        await cb.answer("Karta topilmadi", show_alert=True)
        return

    chart = profile["chart"]
    arabic = chart.get("arabic_parts", {})

    lines = ["☪️ **QADIMIY ARAB NUQTALARI (ARABIC PARTS):**\n"]
    for name, d in arabic.items():
        lines.append(f"• **{name}:** `{d.get('formatted')}`\n  └ _{d.get('description')}_\n")

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ Orqaga", callback_data="menu:astrology"))
    await safe_edit_text(cb, "\n".join(lines), reply_markup=builder.as_markup())


@router.callback_query(ADMIN_FILTER, F.data == "astro:ai_report")
async def cb_astro_ai_report(cb: CallbackQuery, ai_manager: AIManager) -> None:
    """20 Yillik tajribali munajjim-olim (Nous Hermes 3 / Gemini) orqali to'liq voqeaviy prognoz."""
    await cb.answer("20 yillik munajjim-olim hisobot tayyorlamoqda...")
    profile = await db.get_astrology_profile(str(cb.from_user.id))
    if not profile or not profile.get("chart"):
        await cb.answer("Avval kartangizni kiriting", show_alert=True)
        return

    custom_lots = profile.get("custom_lots", [])
    wait_msg = await cb.message.answer(
        f"🔮 **20 yillik tajribali munajjim-olim (Nous Hermes 3 / Al-Biruniy) kartangiz va {len(custom_lots)} ta Arab Lotingizni tahlil qilmoqda...**",
        parse_mode="Markdown"
    )

    from core.astrology_agent import build_grandmaster_astrology_prompt
    prompt = build_grandmaster_astrology_prompt(profile, custom_lots, target_year=2026)

    # Nous Hermes 3 ga o'tish
    prev_provider = ai_manager.current_provider
    prev_model = ai_manager.current_or_model
    ai_manager.switch_openrouter_model("hermes")

    try:
        report = await ai_manager.generate(prompt, save_history=False, chat_id=f"astro_{cb.from_user.id}")
        from core.astrology_agent import ensure_uzbek_astrology_report
        report = await ensure_uzbek_astrology_report(report, ai_manager)
        back_btn = InlineKeyboardBuilder()
        back_btn.row(InlineKeyboardButton(text="◀️ Astrologiya Menyusiga Qaytish", callback_data="menu:astrology"))
        await safe_edit_or_send_long_message(wait_msg, report, reply_markup=back_btn.as_markup(), parse_mode="Markdown")
    except Exception as e:
        logger.error("Astro AI report xatosi: %s", e)
        try:
            await wait_msg.edit_text(f"❌ AI hisobot generatsiyasida xatolik: {e}", parse_mode=None)
        except Exception:
            pass
    finally:
        ai_manager.current_provider = prev_provider
        ai_manager.current_or_model = prev_model


@router.message(ADMIN_FILTER, Command("lots"))
async def cmd_lots_management(message: Message) -> None:
    """Foydalanuvchining 513 ta Arab Lotlarini ko'rish yoki yangi lotlar qo'shish."""
    profile = await db.get_astrology_profile(str(message.from_user.id))
    custom_lots = profile.get("custom_lots", []) if profile else []
    
    lines = [
        "☪️ **513 TA QADIMIY ARAB LOTLARI (ARABIC PARTS / LOTS)**\n",
        f"📊 Sizning bazangizda faol Lotlar soni: **{len(custom_lots)} ta**.\n",
    ]
    if custom_lots:
        lines.append("📋 **Saqlangan asosiy lotlar namunalari:**")
        for l in custom_lots[:8]:
            lines.append(f"• **{l.get('name')}:** `{l.get('degree')}° {l.get('sign')}` ({l.get('house', 'Noma\'lum')})")
        if len(custom_lots) > 8:
            lines.append(f"... va yana {len(custom_lots) - 8} ta faol lotlar.")
    else:
        lines.append(
            "Hozircha faqat 5 ta asosiy klassik lot hisoblangan (Pars Fortuna, Ruh, Eros, Karyera, Saboq).\n\n"
            "💡 **513 ta lotni yuklash uchun:**\n"
            "Lotlar ro'yxatini matn ko'rinishida chatga yuboring yoki `.txt` / `.json` fayl sifatida botga tashlang!\n"
            "Masalan:\n"
            "`Lot of Commerce: 14 Gemini`\n"
            "`Lot of Victory: 22 Leo`\n"
            "`Lot of Marriage: 5 Libra`"
        )
    
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🧠 20 Yillik Olim Tahlili (Nous Hermes)", callback_data="astro:ai_report"))
    builder.row(InlineKeyboardButton(text="◀️ Astrologiya Menyusi", callback_data="menu:astrology"))
    await safe_send_message(message.bot, message.chat.id, "\n".join(lines), reply_markup=builder.as_markup(), parse_mode="Markdown")


@router.callback_query(ADMIN_FILTER, F.data == "astro:setup")
async def cb_astro_setup(cb: CallbackQuery) -> None:
    await cb.answer()
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ Orqaga", callback_data="menu:astrology"))
    text = (
        "✏️ **Natal Kartangizni Kiritish yoki Yangilash:**\n\n"
        "Tug'ilgan kuningiz, aniq vaqti va tug'ilgan shahringizni quyidagi formatda chatga yuboring:\n\n"
        "`/natal YYYY-MM-DD HH:MM Shahar`\n\n"
        "Masalan:\n"
        "• `/natal 1998-05-19 14:30 Toshkent`\n"
        "• `/natal 2000-01-01 08:00 Samarqand`\n\n"
        "*(Agar aniq soatini bilmasangiz, 12:00 deb yozing)*"
    )
    await safe_edit_text(cb, text, reply_markup=builder.as_markup())


@router.callback_query(ADMIN_FILTER, F.data == "menu:cat_prod")
async def cb_cat_prod(cb: CallbackQuery) -> None:
    """Inline: Ish & Unumdorlik toifasi."""
    await cb.answer()
    await safe_edit_text(
        cb,
        "💼 **Ish & Unumdorlik Bo'limi**\n\nRejalar, vazifalar va shaxsiy xabarnomalar:",
        reply_markup=build_inline_productivity_menu(),
    )


@router.callback_query(ADMIN_FILTER, F.data == "menu:cat_smm")
async def cb_cat_smm(cb: CallbackQuery) -> None:
    """Inline: SMM & Marketing toifasi."""
    await cb.answer()
    await safe_edit_text(
        cb,
        "📈 **SMM & Marketing Avtopilot**\n\nKanal va guruhlar boshqaruvi:",
        reply_markup=build_inline_smm_menu(),
    )


@router.callback_query(ADMIN_FILTER, F.data == "menu:cat_settings")
async def cb_cat_settings(cb: CallbackQuery) -> None:
    """Inline: Sozlamalar & Doimiy Xotira toifasi."""
    await cb.answer()
    await safe_edit_text(
        cb,
        "⚙️ **Sozlamalar & Doimiy Xotira**\n\nAI modeli, rol va xotira boshqaruvi:",
        reply_markup=build_inline_settings_menu(),
    )


@router.callback_query(ADMIN_FILTER, F.data == "menu:deep_research")
async def cb_deep_research(cb: CallbackQuery) -> None:
    await cb.answer()
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ Orqaga", callback_data="menu:cat_ai"))
    await safe_edit_text(
        cb,
        "🔬 **Deep Research Agent (Chuqur Internet Tadqiqoti)**\n\n"
        "OpenAI Deep Research tamoyilida ishlovchi avtonom agent!\n"
        "U internetdagi 3-5 ta manbani parallel qidirib, to'liq ilmiy va analitik hisobot tuzadi.\n\n"
        "📌 **Ishlatish:** Chatga yozing:\n"
        "`/research O'zbekistonda 2026-yilda AI bozori tahlili`",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(ADMIN_FILTER, F.data == "menu:code_audit")
async def cb_code_audit(cb: CallbackQuery) -> None:
    await cb.answer()
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ Orqaga", callback_data="menu:cat_ai"))
    await safe_edit_text(
        cb,
        "💻 **Kod Auditi & Shartnoma Tahlilchisi**\n\n"
        "1. **Dasturiy Kod Auditi:** Chatga `/code [kodingiz]` deb yuboring.\n"
        "2. **Hujjat & Shartnoma Auditi:** PDF yoki DOCX faylni botga yuboring!",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(ADMIN_FILTER, F.data == "menu:viral_smm")
async def cb_viral_smm(cb: CallbackQuery) -> None:
    await cb.answer()
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ Orqaga", callback_data="menu:cat_smm"))
    await safe_edit_text(
        cb,
        "🎯 **Viral SMM & Content Strategy Agent**\n\n"
        "Yuqori qamrovli postlar va 7 kunlik kontent-reja tuzadi!\n\n"
        "📌 **Ishlatish:** Chatga yozing:\n"
        "`/smm Yangi startap online ta'lim loyihasi uchun`",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(ADMIN_FILTER, F.data == "menu:video_dl")
async def cb_video_dl(cb: CallbackQuery) -> None:
    await cb.answer()
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ Orqaga", callback_data="menu:cat_ai"))
    await safe_edit_text(
        cb,
        "🎬 **Video Yuklovchi Agenti**\n\n"
        "Instagram Reels, TikTok (suvsiz HD), YouTube Shorts havolasini chatga shunchaki yuboring!",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(ADMIN_FILTER, F.data == "menu:competitors")
async def cb_competitors(cb: CallbackQuery) -> None:
    await cb.answer()
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ Orqaga", callback_data="menu:cat_smm"))
    await safe_edit_text(
        cb,
        "🔍 **Raqobatchilar Tahlili**\n\n"
        "Raqobatchi Telegram kanallarining yangi postlari va auditoriya trendlarini kuzatib boradi.\n\n"
        "Yangi kanal qo'shish uchun: `raqobatchi: @kanal_username` deb yozing.",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(ADMIN_FILTER, F.data == "menu:sync_history")
async def cb_sync_history(cb: CallbackQuery, ai_manager: AIManager) -> None:
    await cb.answer()
    from core.userbot import sync_chat_history_from_telegram, userbot
    if userbot is None or not userbot.is_connected():
        await cb.answer("⚠️ Userbot ulanmagan!", show_alert=True)
        return
    await cb.message.answer("🔄 **Telegram suhbati o'qilmoqda va bazaga saqlanmoqda...**", parse_mode="Markdown")
    bot_user = await cb.bot.get_me()
    target = bot_user.username or cb.message.chat.id
    res = await sync_chat_history_from_telegram(target_username_or_id=target, ai_manager=ai_manager, limit=100)
    await cb.message.answer(res.get("message", "Tayyor."), parse_mode="Markdown")


@router.callback_query(ADMIN_FILTER, F.data.in_({"menu:image_studio", "menu:midjourney"}))
async def cb_image_studio(cb: CallbackQuery) -> None:
    await cb.answer()
    text, markup = build_image_studio_panel(cb.from_user.id)
    await safe_edit_text(cb, text, reply_markup=markup, parse_mode="HTML")


@router.callback_query(ADMIN_FILTER, F.data.startswith("img_cfg:"))
async def cb_img_config(cb: CallbackQuery) -> None:
    parts = cb.data.split(":")
    cfg_type = parts[1] if len(parts) > 1 else ""
    cfg_val = parts[2] if len(parts) > 2 else ""

    cfg = get_user_image_settings(cb.from_user.id)
    if cfg_type in ("model", "ar", "style") and cfg_val:
        cfg[cfg_type] = cfg_val
        await cb.answer(f"✅ {cfg_val.upper()} tanlandi!")
    else:
        await cb.answer()

    text, markup = build_image_studio_panel(cb.from_user.id)
    await safe_edit_text(cb, text, reply_markup=markup, parse_mode="HTML")


@router.callback_query(ADMIN_FILTER, F.data.startswith("img_idea:"))
async def cb_img_idea(cb: CallbackQuery, ai_manager: AIManager) -> None:
    idea_key = cb.data.replace("img_idea:", "").strip()
    idea_dict = {k: p for k, _, p in QUICK_IDEAS}
    prompt = idea_dict.get(idea_key)
    if not prompt:
        await cb.answer("G'oya topilmadi", show_alert=True)
        return

    cfg = get_user_image_settings(cb.from_user.id)
    model = cfg.get("model", "flux")
    ar = cfg.get("ar", "1:1")
    style = cfg.get("style", "photo")

    model_title = AVAILABLE_MODELS.get(model, model).split("(")[0].strip()
    await cb.answer(f"🎨 {model_title} ({ar}) ishlamoqda...")
    wait_msg = await cb.message.answer(
        f"🎨 <b>Super-Agent Studio rasm chizmoqda...</b>\n\n"
        f"🤖 Model: <code>{model_title}</code> | 📐 O'lcham: <code>{ar}</code>\n"
        f"📝 <i>{html.escape(prompt)}</i>",
        parse_mode="HTML",
    )
    try:
        await cb.bot.send_chat_action(cb.message.chat.id, "upload_photo")
        full_prompt = f"{prompt} --style {style}"
        img_bytes, enhanced_p, used_ar, seed, used_model, *_ = await draw_midjourney_image(
            raw_prompt=full_prompt,
            ai_manager=ai_manager,
            aspect_ratio=ar,
            model=model,
            enhance=True,
        )
        if img_bytes:
            task_id = uuid.uuid4().hex[:8]
            MJ_TASKS[task_id] = {
                "prompt": prompt,
                "enhanced": enhanced_p,
                "ar": used_ar,
                "seed": seed,
                "model": used_model,
                "style": style,
            }
            reply_markup = build_mj_keyboard(task_id, current_model=used_model, current_ar=used_ar, current_style=style)
            photo_file = BufferedInputFile(file=img_bytes, filename=f"idea_{task_id}.jpg")
            m_title = AVAILABLE_MODELS.get(used_model, used_model).split("(")[0].strip()
            caption = (
                f"🎨 <b>Super-Agent Studio: {html.escape(m_title)}</b>\n\n"
                f"📝 <b>G'oya:</b> <i>{html.escape(prompt)}</i>\n"
                f"📐 O'lcham: <code>{used_ar}</code> | 🎲 Seed: <code>{seed}</code>\n\n"
                f"<i>Quyidagi tugmalar orqali model yoki proporsiyani almashtirishingiz mumkin:</i>"
            )
            try:
                await wait_msg.delete()
            except Exception:
                pass
            await cb.message.answer_photo(photo=photo_file, caption=caption, reply_markup=reply_markup, parse_mode="HTML")
        else:
            await wait_msg.edit_text("❌ Rasm chizishda xatolik yuz berdi. Iltimos qayta urinib ko'ring.")
    except Exception as exc:
        logger.error("Tezkor g'oya rasm xatosi: %s", exc)
        await wait_msg.edit_text(f"❌ Xatolik: {exc}")


@router.callback_query(ADMIN_FILTER, F.data == "menu:hermes")
async def cb_hermes(cb: CallbackQuery, ai_manager: AIManager) -> None:
    await cb.answer()
    ai_manager.switch_role("hermes_agent")
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ Asosiy Menyu", callback_data="menu:main"))
    text = (
        "⚡ **Nous Hermes 3 Avtonom Agent Faollashtirildi!**\n\n"
        "Hermes 3 — chuqur mantiqiy fikrlash (deep reasoning), ko'p bosqichli rejalashtirish, "
        "aniq hisob-kitoblar va avtonom muammolarni hal qilish bo'yicha dunyodagi eng kuchli ochiq agentdir.\n\n"
        "**Siz unga murakkab topshiriqlar berishingiz mumkin:**\n"
        "• `/hermes Yangi startap loyiha uchun 6 oylik biznes reja, moliyaviy hisob-kitob va marketing strategiyasi tuzib ber`\n"
        "• `hermes: O'zbekiston IT bozoridagi eng istiqbolli 5 ta sohani hisob-kitoblar bilan tahlil qil`"
    )
    await safe_edit_text(cb, text, reply_markup=builder.as_markup(), parse_mode="Markdown")


@router.callback_query(ADMIN_FILTER, F.data == "menu:todo")
async def cb_menu_todo(cb: CallbackQuery) -> None:
    await cb.answer()
    from core.todo_notion_agent import format_tasks_list_report
    text, markup = await format_tasks_list_report()
    await safe_edit_text(cb, text, reply_markup=markup, parse_mode="Markdown")


@router.callback_query(ADMIN_FILTER, F.data == "menu:uptime")
async def cb_menu_uptime(cb: CallbackQuery) -> None:
    await cb.answer()
    from core.uptime_agent import format_uptime_dashboard_report
    text, markup = await format_uptime_dashboard_report()
    await safe_edit_text(cb, text, reply_markup=markup, parse_mode="Markdown")


@router.callback_query(ADMIN_FILTER, F.data == "menu:news")
async def cb_menu_news(cb: CallbackQuery, ai_manager: AIManager) -> None:
    await cb.answer()
    from core.news_football_agent import get_topic_news
    text, markup = await get_topic_news("dasturlash", ai_manager)
    await safe_edit_text(cb, text, reply_markup=markup, parse_mode="Markdown")


@router.callback_query(ADMIN_FILTER, F.data == "menu:mem0_profile")
async def cb_mem0_profile(cb: CallbackQuery) -> None:
    await cb.answer()
    from core.mem0_agent import get_user_profile_report, build_profile_keyboard
    profile_text = await get_user_profile_report(cb.from_user.id)
    await safe_edit_text(cb, profile_text, reply_markup=build_profile_keyboard(show_back=True), parse_mode="Markdown")


@router.callback_query(ADMIN_FILTER, F.data == "mem0:refresh")
async def cb_mem0_refresh(cb: CallbackQuery) -> None:
    await cb.answer("🔄 Yangilanmoqda...")
    from core.mem0_agent import get_user_profile_report, build_profile_keyboard
    profile_text = await get_user_profile_report(cb.from_user.id)
    await safe_edit_text(cb, profile_text, reply_markup=build_profile_keyboard(show_back=True), parse_mode="Markdown")


@router.callback_query(ADMIN_FILTER, F.data == "mem0:add_help")
async def cb_mem0_add_help(cb: CallbackQuery) -> None:
    await cb.answer()
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ Profilga qaytish", callback_data="menu:mem0_profile"))
    text = (
        "➕ **Mem0 ga Shaxsiy Ma'lumot Kiritish:**\n\n"
        "Shunchaki botga o'zingiz haqingizda xabar yozing. Masalan:\n\n"
        "• `mening ismim Umid`\n"
        "• `men Toshkentda yashayman`\n"
        "• `kasbim: Senior AI dasturchi`\n"
        "• `bizning kompaniya: MegaTech`\n"
        "• `mening maqsadim: AI agentlar yaratish`\n"
        "• `profil: sevimli kitobim: Atomic Habits`\n\n"
        "Mem0 bularni bir zumda ajratib olib, doimiy profilingizga joylaydi!"
    )
    await safe_edit_text(cb, text, reply_markup=builder.as_markup(), parse_mode="Markdown")


@router.callback_query(ADMIN_FILTER, F.data == "mem0:clear")
async def cb_mem0_clear(cb: CallbackQuery) -> None:
    await cb.answer("🗑 Profil tozalandi", show_alert=True)
    from core.mem0_agent import clear_user_profile, get_user_profile_report, build_profile_keyboard
    await clear_user_profile()
    profile_text = await get_user_profile_report(cb.from_user.id)
    await safe_edit_text(cb, profile_text, reply_markup=build_profile_keyboard(show_back=True), parse_mode="Markdown")


@router.callback_query(ADMIN_FILTER, F.data == "menu:tts_info")
async def cb_tts_info(cb: CallbackQuery) -> None:
    await cb.answer()
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ Asosiy Menyu", callback_data="menu:main"))
    text = (
        "🎙 **Microsoft Edge TTS — Jonli Ovozli Xabarlar**\n\n"
        "AI javoblarini tabiiy inson ovozida (o'zbek, rus, ingliz) audio qilib eshitishingiz mumkin!\n\n"
        "**Imkoniyatlar:**\n"
        "1. **Ixtiyoriy matnni ovozga aylantirish:**\n"
        "   `/voice Salom, bugun qanday yangiliklar bor?`\n\n"
        "2. **AI javoblari ostida '🔊 Ovozda eshitish' tugmasi:**\n"
        "   Bir marta bosish orqali javobni audio shaklida tinglang.\n\n"
        "3. **Ovozli xabar yuborsangiz:**\n"
        "   Bot sizning ovozingizni tushunib, o'zi ham ovozli xabar bilan javob qaytaradi!"
    )
    await safe_edit_text(cb, text, reply_markup=builder.as_markup(), parse_mode="Markdown")


@router.callback_query(ADMIN_FILTER, F.data == "menu:models")
async def cb_models(cb: CallbackQuery) -> None:
    await cb.answer()
    await safe_edit_text(
        cb,
        "🤖 **Model tanlang:**\n"
        "Har bir model o'z kuchli tomonlari bilan farqlanadi.",
        reply_markup=build_models_menu(),
        parse_mode="Markdown",
    )


@router.callback_query(ADMIN_FILTER, F.data == "menu:roles")
async def cb_roles(cb: CallbackQuery) -> None:
    await cb.answer()
    await safe_edit_text(
        cb,
        "🎭 **Rol tanlang:**\n"
        "Rol AI ning uslubi va yo'nalishini belgilaydi.",
        reply_markup=build_roles_menu(),
        parse_mode="Markdown",
    )


@router.callback_query(ADMIN_FILTER, F.data == "menu:status")
async def cb_status(cb: CallbackQuery, ai_manager: AIManager) -> None:
    await cb.answer()
    from core.cleaner_agent import get_system_storage_info
    storage = get_system_storage_info()
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🧹 Server Keshini Tozalash", callback_data="clean:server"))
    builder.row(InlineKeyboardButton(text="◀️ Orqaga", callback_data="menu:main"))
    text = (
        f"{ai_manager.status()}\n\n"
        f"🖥 **Server Diski:** `{storage['used_gb']} GB / {storage['total_gb']} GB` (Bo'sh: `{storage['free_gb']} GB`)\n"
        f"🤖 **Baza hajmi:** `{storage['db_size_mb']} MB`"
    )
    await safe_edit_text(
        cb,
        text,
        reply_markup=builder.as_markup(),
        parse_mode="Markdown",
    )


@router.callback_query(ADMIN_FILTER, F.data == "menu:log")
async def cb_log(cb: CallbackQuery) -> None:
    await cb.answer()
    collector = LogCollector()
    summary = collector.build_summary_text()
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ Orqaga", callback_data="menu:main"))
    await safe_edit_text(
        cb,
        summary[:4000],
        reply_markup=builder.as_markup(),
        parse_mode="Markdown",
    )


@router.callback_query(ADMIN_FILTER, F.data == "menu:memory")
async def cb_memory(cb: CallbackQuery) -> None:
    await cb.answer()
    facts = await db.get_all_facts()
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ Orqaga", callback_data="menu:main"))

    if not facts:
        text = (
            "🧠 **Doimiy Xotira (RAG Knowledge Base)**\n\n"
            "Hozircha hech qanday fakt saqlanmagan.\n\n"
            "💡 Yangi fakt kiritish uchun botga:\n"
            "`Eslab qol: Karta: 8600...` yoki `/remember kalit: qiymat`\n"
            "yoki Word/PDF/TXT fayl tashlang!"
        )
    else:
        lines = [f"🧠 **Doimiy Xotiradagi Faktlar ({len(facts)} ta):**\n"]
        for f in facts[:15]:
            lines.append(f"• `{f.get('key')}`: {f.get('content')[:80]}")
        lines.append("\n💡 /clear qilinsa ham agent ushbu faktlarni doim eslab qoladi!")
        text = "\n".join(lines)

    await safe_edit_text(cb, text[:4000], reply_markup=builder.as_markup(), parse_mode="Markdown")


@router.callback_query(ADMIN_FILTER, F.data == "menu:reminders")
async def cb_reminders(cb: CallbackQuery) -> None:
    await cb.answer()
    active = await db.get_active_reminders(cb.message.chat.id)
    builder = InlineKeyboardBuilder()

    if not active:
        text = (
            "⏰ **Faol eslatmalar mavjud emas.**\n\n"
            "💡 Yangi eslatma qo'shish uchun botga shunchaki yozing:\n"
            "• `21:30 da bot orqali menga eslat: dori ichish`\n"
            "• `15 daqiqadan keyin eslat: choy damlash`\n"
            "• `Ertaga soat 10:00 da eslat: Uchrashuv`"
        )
    else:
        lines = [f"⏰ **Faol Eslatmalar ({len(active)} ta):**\n"]
        for r in active:
            lines.append(f"• `#{r['id']}` [{r['remind_at']}] {r['text']}")
            builder.row(InlineKeyboardButton(text=f"❌ #{r['id']} ni o'chirish", callback_data=f"del_rem:{r['id']}"))
        text = "\n".join(lines)

    builder.row(InlineKeyboardButton(text="◀️ Orqaga", callback_data="menu:main"))
    await safe_edit_text(cb, text[:4000], reply_markup=builder.as_markup(), parse_mode="Markdown")


@router.callback_query(ADMIN_FILTER, F.data == "menu:scheduled_posts")
async def cb_scheduled_posts(cb: CallbackQuery) -> None:
    await cb.answer()
    posts = await db.get_all_pending_posts()
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ Orqaga", callback_data="menu:main"))

    if not posts:
        text = "⏰ **Kutilayotgan postlar yo'q.**\n\nRejalashtirish: `rejalashtir: @kanal 2026-09-17 10:00 Matn`"
    else:
        lines = [f"⏰ **Kutilayotgan Postlar ({len(posts)} ta):**\n"]
        for p in posts:
            lines.append(f"• ID #{p['id']} ➔ `{p['chat_id']}` | `{p['scheduled_time']}`\n  _{p['text'][:60]}..._\n")
        text = "\n".join(lines)

    await safe_edit_text(cb, text[:4000], reply_markup=builder.as_markup(), parse_mode="Markdown")


@router.callback_query(ADMIN_FILTER, F.data == "menu:clear")
async def cb_clear(cb: CallbackQuery, ai_manager: AIManager) -> None:
    chat_id = str(cb.message.chat.id) if cb.message else "0"
    await cb.answer("✅ Xotira tozalandi")
    result = ai_manager.clear_history(chat_id=chat_id)
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ Orqaga", callback_data="menu:main"))
    await safe_edit_text(
        cb,
        result,
        reply_markup=builder.as_markup(),
        parse_mode="Markdown",
    )


@router.callback_query(ADMIN_FILTER, F.data == "menu:userbot")
async def cb_userbot(cb: CallbackQuery) -> None:
    await cb.answer()
    info = await get_userbot_info()
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ Orqaga", callback_data="menu:main"))
    await safe_edit_text(
        cb,
        info,
        reply_markup=builder.as_markup(),
        parse_mode="Markdown",
    )


@router.callback_query(ADMIN_FILTER, F.data == "menu:tg_summary")
async def cb_tg_summary(cb: CallbackQuery, ai_manager: AIManager) -> None:
    await cb.answer("⏳ Telegram xabarlari tahlil qilinmoqda...")
    await safe_edit_text(cb, "⏳ Telegram akkauntingizdagi so'nggi xabarlar yuklanmoqda va AI tahlili qilinmoqda...")
    summary = await summarize_telegram_activity(ai_manager)
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🔄 Qayta tekshirish", callback_data="menu:tg_summary"),
        InlineKeyboardButton(text="◀️ Orqaga", callback_data="menu:main"),
    )
    await safe_edit_text(
        cb,
        summary[:4000],
        reply_markup=builder.as_markup(),
        parse_mode="Markdown",
    )


@router.callback_query(ADMIN_FILTER, F.data == "menu:help")
async def cb_help(cb: CallbackQuery) -> None:
    await cb.answer()
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ Orqaga", callback_data="menu:main"))
    text = (
        "📖 **Qisqa Yordam**\n\n"
        "• Matn yuboring → AI javob beradi\n"
        "• Fayl yuboring → Tahlil + qayta yozish\n"
        "• Rasm yuboring → Tahrirlash yoki tahlil\n"
        "• `yoz @user: xabar` → Userbot xabar\n"
        "• `post: @kanal matn` → Kanal post\n"
        "• `/help` → To'liq yordam"
    )
    await safe_edit_text(
        cb,
        text,
        reply_markup=builder.as_markup(),
        parse_mode="Markdown",
    )


# ─── Model Callback'lari ──────────────────────────────────────

@router.callback_query(ADMIN_FILTER, F.data == "model:gemini")
async def cb_model_gemini(cb: CallbackQuery, ai_manager: AIManager) -> None:
    await cb.answer("✅ Gemini tanlandi")
    result = ai_manager.switch_provider("gemini")
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ Orqaga", callback_data="menu:models"))
    await safe_edit_text(cb, result, reply_markup=builder.as_markup(), parse_mode="Markdown")


@router.callback_query(ADMIN_FILTER, F.data == "model:omniroute")
async def cb_model_omniroute(cb: CallbackQuery, ai_manager: AIManager) -> None:
    await cb.answer("✅ OmniRoute tanlandi")
    result = ai_manager.switch_provider("omniroute")
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ Orqaga", callback_data="menu:models"))
    text = (
        f"{result}\n\n"
        f"🌐 **OmniRoute AI Gateway (350+ AI Provayder):**\n"
        f"150+ bepul tier va 1200+ modellarni o'z ichiga olgan yagona shlyuz.\n\n"
        f"💡 Agar lokal shlyuz ishlatmoqchi bo'lsangiz, terminalda bir marta:\n"
        f"`npx omniroute`\n"
        f"buyrug'ini yurgizib qo'yishingiz mumkin!"
    )
    await safe_edit_text(cb, text, reply_markup=builder.as_markup(), parse_mode="Markdown")


@router.callback_query(ADMIN_FILTER, F.data.startswith("model:or_"))
async def cb_model_openrouter(cb: CallbackQuery, ai_manager: AIManager) -> None:
    await cb.answer("✅ Model tanlandi")
    model_key = cb.data.replace("model:or_", "")
    result = ai_manager.switch_openrouter_model(model_key)
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ Orqaga", callback_data="menu:models"))
    await safe_edit_text(cb, result, reply_markup=builder.as_markup(), parse_mode="Markdown")


# ─── Rol Callback'lari ────────────────────────────────────────

@router.callback_query(ADMIN_FILTER, F.data.startswith("role:"))
async def cb_role(cb: CallbackQuery, ai_manager: AIManager) -> None:
    role_key = cb.data.replace("role:", "")
    role_name = ROLES.get(role_key, {}).get("name", role_key)
    await cb.answer(f"✅ {role_name} roli tanlandi")
    result = ai_manager.switch_role(role_key)
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ Orqaga", callback_data="menu:roles"))
    await safe_edit_text(cb, result, reply_markup=builder.as_markup(), parse_mode="Markdown")

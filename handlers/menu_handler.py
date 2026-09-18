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

logger = logging.getLogger(__name__)
router = Router(name="menu")

# Faqat admin filtratsiyasi
ADMIN_FILTER = F.from_user.id == ADMIN_ID


# ─── Yordamchi: Doimiy Klaviatura Menyusi (Reply Keyboard) ────

def build_reply_keyboard_menu() -> ReplyKeyboardMarkup:
    """Doimiy pastki klaviatura menyusi (Reply Keyboard). 100% ishonchli va tezkor."""
    buttons = [
        [
            KeyboardButton(text="📱 Mini App Paneli"),
        ],
        [
            KeyboardButton(text="🎨 Rasm Chizish"),
            KeyboardButton(text="⚡ Hermes Agent"),
        ],
        [
            KeyboardButton(text="📝 Vazifalar (Notion)"),
            KeyboardButton(text="🌐 Saytlar (Uptime)"),
        ],
        [
            KeyboardButton(text="📰 Yangiliklar & Tahlil"),
            KeyboardButton(text="👤 Shaxsiy Profil (Mem0)"),
        ],
        [
            KeyboardButton(text="🔬 Deep Research"),
            KeyboardButton(text="💻 Kod & Shartnoma Auditi"),
        ],
        [
            KeyboardButton(text="🎯 Viral SMM"),
            KeyboardButton(text="🎬 Video Yuklovchi"),
        ],
        [
            KeyboardButton(text="🎙 Ovozli Agent (STT & TTS)"),
            KeyboardButton(text="🤖 AI Modellar"),
        ],
        [
            KeyboardButton(text="🎭 Tizim Rollari"),
            KeyboardButton(text="⏰ Rejalashtirilgan Postlar"),
        ],
        [
            KeyboardButton(text="🧠 Doimiy Xotira"),
            KeyboardButton(text="🔄 Tarixni Sinxronlash"),
        ],
        [
            KeyboardButton(text="📊 Holat & Statistika"),
            KeyboardButton(text="📡 Telegram Xulosasi"),
        ],
        [
            KeyboardButton(text="📧 Email Pochta"),
            KeyboardButton(text="🔍 Raqobatchilar Tahlili"),
        ],
        [
            KeyboardButton(text="🧹 Xotirani Tozalash"),
            KeyboardButton(text="❓ Yordam"),
        ],
    ]

    return ReplyKeyboardMarkup(
        keyboard=buttons,
        resize_keyboard=True,
        is_persistent=True,
    )


# ─── Yordamchi: Klaviaturalar ────────────────────────────────

def build_main_menu() -> InlineKeyboardMarkup:
    """Asosiy menyu inline klaviaturasi."""
    builder = InlineKeyboardBuilder()

    # WebApp URL mavjud bo'lsa yuqorida Mini App tugmasi
    target_web_url = get_clean_webapp_url()
    if target_web_url:
        builder.row(
            InlineKeyboardButton(
                text="📱 Super-Agent Mini App Paneli",
                web_app=WebAppInfo(url=target_web_url)
            )
        )

    builder.row(
        InlineKeyboardButton(text="🎨 Rasm Chizish Studio", callback_data="menu:image_studio"),
        InlineKeyboardButton(text="⚡ Hermes 3 Agent", callback_data="menu:hermes"),
    )
    builder.row(
        InlineKeyboardButton(text="📝 TodoList (Notion)", callback_data="menu:todo"),
        InlineKeyboardButton(text="🌐 Saytlar Uptime", callback_data="menu:uptime"),
    )
    builder.row(
        InlineKeyboardButton(text="📰 Yangiliklar & Tahlil", callback_data="menu:news"),
        InlineKeyboardButton(text="👤 Profilim (Mem0)", callback_data="menu:mem0_profile"),
    )
    builder.row(
        InlineKeyboardButton(text="🎙 Ovozli Audio (TTS)", callback_data="menu:tts_info"),
        InlineKeyboardButton(text="🤖 Model Tanlash", callback_data="menu:models"),
    )
    builder.row(
        InlineKeyboardButton(text="🎭 Rol Tanlash", callback_data="menu:roles"),
        InlineKeyboardButton(text="⏰ Eslatmalar", callback_data="menu:reminders"),
    )
    builder.row(
        InlineKeyboardButton(text="⏰ Reja Postlar", callback_data="menu:scheduled_posts"),
        InlineKeyboardButton(text="🧠 Doimiy Xotira (RAG)", callback_data="menu:memory"),
    )
    builder.row(
        InlineKeyboardButton(text="📊 Holat & Statistika", callback_data="menu:status"),
        InlineKeyboardButton(text="🧹 Xotirani Tozala", callback_data="menu:clear"),
    )
    builder.row(
        InlineKeyboardButton(text="📧 Email Agent", callback_data="email:menu"),
        InlineKeyboardButton(text="📱 Telegram Xulosasi", callback_data="menu:tg_summary"),
    )
    builder.row(
        InlineKeyboardButton(text="📋 Bugungi Log", callback_data="menu:log"),
        InlineKeyboardButton(text="❓ Yordam", callback_data="menu:help"),
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

@router.message(ADMIN_FILTER, F.text.in_({"🎨 Rasm Chizish", "Rasm Chizish", "rasm chizish", "🎨 Midjourney Rasm", "Midjourney Rasm", "midjourney rasm", "/imagine", "/midjourney"}))
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
    await wait_msg.edit_text(summary[:4000], parse_mode="Markdown")


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
        "🏠 Asosiy menyu:",
        reply_markup=build_main_menu(),
    )


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

"""
2-Bot: Mistral Arxitektor Agent Bot (@architect7_bot).
Mistral AI agenti (ag_01a0ba16a68173e8a1cdb3ead308ff14) orqali ishlovchi
mustaqil Telegram bot moduli.

O'zining shaxsiy menyusi, arxitektura vositalari, kod tahlilchisi,
CAMEL + ChatDev + MAPR ko'p agentli hamkorligi va erkin suhbat rejimi mavjud.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BotCommand,
    MenuButtonCommands,
    CallbackQuery,
)
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import SECOND_BOT_TOKEN, BOT_TOKEN
from core.mistral_conversations import mistral_agent_client

logger = logging.getLogger(__name__)

second_bot_router = Router(name="mistral_agent_bot_router")
_second_bot_instance: Optional[Bot] = None
_main_bot_instance: Optional[Bot] = None


def get_second_bot() -> Optional[Bot]:
    """2-Bot obyektini qaytaradi (agar SECOND_BOT_TOKEN mavjud bo'lsa)."""
    global _second_bot_instance
    if _second_bot_instance is None and SECOND_BOT_TOKEN:
        _second_bot_instance = Bot(token=SECOND_BOT_TOKEN)
    return _second_bot_instance


def get_main_bot_instance() -> Optional[Bot]:
    """Asosiy Jarvis bot obyektini qaytaradi."""
    global _main_bot_instance
    if _main_bot_instance is None and BOT_TOKEN:
        _main_bot_instance = Bot(token=BOT_TOKEN)
    return _main_bot_instance


def set_main_bot_instance(bot: Bot) -> None:
    """Asosiy bot obyektini biriktiradi."""
    global _main_bot_instance
    _main_bot_instance = bot


def get_architect_keyboard() -> ReplyKeyboardMarkup:
    """Arxitektor Mistral Botining shaxsiy maxsus klaviaturasi."""
    kb = [
        [
            KeyboardButton(text="🏗 Dastur Arxitekturasi"),
            KeyboardButton(text="💻 Kod Tahlili & Audit"),
        ],
        [
            KeyboardButton(text="📦 Loyiha Yaratish (ZIP)"),
            KeyboardButton(text="🎙️ Ovozli Suhbat"),
        ],
        [
            KeyboardButton(text="🤝 CAMEL Hamkorlik"),
            KeyboardButton(text="🗣️ Erkin Suhbat"),
        ],
        [
            KeyboardButton(text="⚔️ Intellektual Bahs"),
            KeyboardButton(text="♟️ AI Shaxmat Bahsi"),
        ],
        [
            KeyboardButton(text="🤖 AI Modellar"),
            KeyboardButton(text="ℹ️ Arxitektor Haqida"),
        ],
    ]
    return ReplyKeyboardMarkup(
        keyboard=kb,
        resize_keyboard=True,
        input_field_placeholder="Arxitektorga savol, kod yoki mavzu yozing...",
    )


async def safe_reply(message: Message, text: str, reply_markup=None, parse_mode: str = "HTML") -> Message:
    """Xabarni xavfsiz yuborish (agar HTML xatosi bo'lsa, avtomatik oddiy matn sifatida yetkazadi)."""
    try:
        return await message.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception as exc:
        logger.warning("Arxitektor formatlash xatosi (%s), toza matn bilan yuboriladi", exc)
        return await message.answer(text, reply_markup=reply_markup, parse_mode=None)


async def setup_architect_bot(bot: Bot) -> None:
    """Arxitektor botning shaxsiy Telegram buyruqlari va menyu tugmasini sozlash."""
    try:
        await bot.set_my_commands([
            BotCommand(command="start", description="Arxitektor botni ishga tushirish"),
            BotCommand(command="menu", description="Arxitektor bosh menyusi"),
            BotCommand(command="models", description="Mavjud bepul AI modellar & failover holati"),
            BotCommand(command="project", description="To'liq dastur loyihasi & ZIP arxiv (/loyiha)"),
            BotCommand(command="ovozli_suhbat", description="SuperAgent bilan jonli ovozli suhbat"),
            BotCommand(command="collab", description="SuperAgent bilan vazifa bajarish (CAMEL/MAPR)"),
            BotCommand(command="avtopilot", description="Tungi chuqur vazifa (bitmaguncha ishlash)"),
            BotCommand(command="suhbat", description="SuperAgent bilan erkin muloqot (AI Lounge)"),
            BotCommand(command="bahs", description="SuperAgent bilan rasmiy bahs & hakam ovozi"),
            BotCommand(command="profile", description="Shaxsiy foydalanuvchi bilimlari profili (Mem0)"),
            BotCommand(command="stop_suhbat", description="Suhbat yoki bahsni to'xtatish"),
            BotCommand(command="stop_collab", description="Vazifani to'xtatish"),
            BotCommand(command="chess", description="SuperAgent bilan shaxmat o'ynash"),
            BotCommand(command="code", description="Kod tahlili va audit"),
            BotCommand(command="help", description="Yordam va qo'llanma"),
        ])
        await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
        logger.info("✅ Arxitektor Bot (@architect7_bot) komandalari va menyusi sozlandi.")
    except Exception as exc:
        logger.warning("Arxitektor bot komandalarini sozlashda ogohlantirish: %s", exc)


@second_bot_router.message(Command("start", "menu"))
async def cmd_start_second_bot(message: Message) -> None:
    """Arxitektor bot start va shaxsiy menyusi."""
    logger.info("📩 Arxitektor bot /start buyrug'i: chat_id=%s, user=%s", message.chat.id, message.from_user.id)
    welcome_text = (
        "🌪 <b>Assalomu alaykum! Men Arxitektor Agent Botman (@architect7_bot).</b>\n\n"
        "Men <b>Mistral AI</b> platformasidagi maxsus o'qitilgan sun'iy intellekt agenti tomonidan boshqarilaman.\n\n"
        "✨ <b>Mening ixtisoslashgan sohalarim:</b>\n"
        "• 🏗 <b>Dasturiy arxitektura va tizim dizayni</b> (Microservices, DB schema, API design);\n"
        "• 📦 <b>MetaGPT/ChatDev to'liq loyihalar yaratish</b> (<code>/project [loyiha]</code> — tayyor ZIP arxiv);\n"
        "• 🎙 <b>SuperAgent bilan jonli ovozli suhbat</b> (<code>/ovozli_suhbat [mavzu]</code>);\n"
        "• 💻 <b>Xavfsiz sandboxda kod ijro etish & xatolarni o'zi tuzatish</b>;\n"
        "• 🤝 <b>SuperAgent bilan CAMEL & ChatDev hamkorligi</b> (<code>/collab [vazifa]</code>);\n"
        "• 🌙 <b>Tungi avtonom avtopilot</b> (<code>/avtopilot [vazifa]</code> — tugamaguncha ishlaydi);\n"
        "• 🗣️ <b>SuperAgent bilan erkin suhbat</b> (<code>/suhbat 10 [mavzu]</code>);\n"
        "• 🧠 <b>Shaxsiy foydalanuvchi xotirasi</b> (<code>/profile</code>).\n\n"
        "Quyidagi shaxsiy menyudan kerakli bo'limni tanlang yoki to'g'ridan-to'g'ri topshiriq bering!"
    )
    await safe_reply(message, welcome_text, reply_markup=get_architect_keyboard(), parse_mode="HTML")


@second_bot_router.message(Command("help"))
async def cmd_help_second_bot(message: Message) -> None:
    """Yordam komandasi."""
    help_text = (
        "💡 <b>Arxitektor Agent Buyruqlari:</b>\n\n"
        "• <code>/start</code> yoki <code>/menu</code> — Arxitektor shaxsiy menyusini ochish\n"
        "• <code>/project [loyiha]</code> — To'liq dastur yaratib ZIP arxiv sifatida yuborish\n"
        "• <code>/ovozli_suhbat [N] [mavzu]</code> — SuperAgent bilan ikki ovozli muloqot (Edge-TTS)\n"
        "• <code>/collab [vazifa]</code> — SuperAgent bilan ko'p agentli hamkorlik & kod ijrosi\n"
        "• <code>/avtopilot [vazifa]</code> — Tungi vazifa (loyiha to'liq bitmaguncha ishlaydi)\n"
        "• <code>/suhbat [N] [mavzu]</code> — Erkin matnli muloqot\n"
        "• <code>/bahs [mavzu]</code> — Rasmiy intellektual bahs & hakam ovozi\n"
        "• <code>/profile</code> — Shaxsiy qiziqishlaringiz va AI bilimlari profili\n"
        "• <code>/fikr [on/off]</code> — Guruhda buyruqlarsiz ikkala bot erkin fikr bildirishini boshqarish\n"
        "• <code>/stop_suhbat</code> — Erkin suhbat/bahsni to'xtatish\n"
        "• <code>/stop_collab</code> — Avtopilot/Hamkorlikni to'xtatish\n"
        "• <code>/chess</code> — Shaxmat bahsini boshlash\n"
        "• <code>/code</code> — Kod tahlili va xavfsizlik auditi"
    )
    await safe_reply(message, help_text, reply_markup=get_architect_keyboard(), parse_mode="HTML")


@second_bot_router.message(Command("fikr", "dual_opinion", "fikrlar"))
async def cmd_second_bot_toggle_dual_opinion(message: Message) -> None:
    """Guruhda buyruqlarsiz ikkala bot fikr bildirishini boshqarish."""
    from core.bot_collab import set_group_dual_opinion, is_group_dual_opinion_enabled
    chat_id = message.chat.id
    raw_text = (message.text or "").strip().lower()
    args = raw_text.split()[1:] if len(raw_text.split()) > 1 else []

    if any(w in args for w in ["off", "o'chir", "ochir", "stop", "to'xtat"]):
        set_group_dual_opinion(chat_id, False)
        await safe_reply(
            message,
            "🔇 <b>Erkin fikr bildirish o'chirildi.</b>\n"
            "Endi botlar faqat o'ziga murojaat qilinganda yoki /suhbat, /bahs buyruqlarida javob beradi.",
            parse_mode="HTML"
        )
    elif any(w in args for w in ["on", "yoq", "ishlat", "start", "boshla"]):
        set_group_dual_opinion(chat_id, True)
        await safe_reply(
            message,
            "🎙 <b>Erkin fikr bildirish yoqildi!</b>\n"
            "Guruhda yozilgan har qanday mavzu va xabarga SuperAgent hamda Arxitektor navbati bilan o'z fikrini bildiradi.",
            parse_mode="HTML"
        )
    else:
        status = "Yoqilgan ✅" if is_group_dual_opinion_enabled(chat_id) else "O'chirilgan ❌"
        await safe_reply(
            message,
            f"🎙 <b>Guruhda erkin fikr bildirish holati:</b> {status}\n\n"
            f"💡 <i>Ikkala bot ham hech qanday buyruqlarsiz xabarlarga fikr bildirishi uchun:</i>\n"
            f"• <code>/fikr on</code> — Yoqish\n"
            f"• <code>/fikr off</code> — O'chirish",
            parse_mode="HTML"
        )


# ─── KO'P AGENTLI HAMKORLIK & ERKIN SUHBAT BUYRUQLARI ──────────

@second_bot_router.message(Command("collab", "hamkorlik", "avtopilot", "kechki_vazifa", "night"))
@second_bot_router.message(F.text.lower().startswith(("/collab", "/hamkorlik", "/avtopilot", "/kechki_vazifa", "🤝 camel hamkorlik", "🌙 avtopilot")))
async def cmd_collab_trigger(message: Message, bot: Bot) -> None:
    """SuperAgent bilan birgalikda vazifa bajarish (CAMEL/MAPR / Avtopilot)."""
    raw_text = (message.text or "").strip()
    if message.chat.id < 0:
        cmd_mention = re.match(r"^/\w+@(\w+)", raw_text)
        bot_info = await bot.get_me()
        target_uname = (bot_info.username or "architect7_bot").lower()
        if not cmd_mention or cmd_mention.group(1).lower() != target_uname:
            return

    is_night_autopilot = any(w in raw_text.lower() for w in ["/avtopilot", "/kechki_vazifa", "/night", "🌙 avtopilot"])
    task_text = re.sub(r"^(?:/collab|/hamkorlik|/avtopilot|/kechki_vazifa|/night|🤝 CAMEL Hamkorlik|🌙 Avtopilot)(?:@\w+)?[:\s]*", "", raw_text, flags=re.IGNORECASE).strip()

    if not task_text and message.reply_to_message:
        task_text = message.reply_to_message.text or message.reply_to_message.caption or ""

    if not task_text:
        prompt_info = (
            "🤝 <b>CAMEL & ChatDev Avtonom Hamkorlik</b>\n\n"
            "SuperAgent bilan birgalikda vazifani bajarishimiz uchun topshiriq bering:\n\n"
            "💡 <b>Foydalanish:</b>\n"
            "• <code>/collab [vazifa matni]</code> — Standart ko'p agentli hamkorlik\n"
            "• <code>/avtopilot [vazifa matni]</code> — Tungi to'liq rejim (vazifa bitmaguncha ikkala bot ishlab boraveradi)\n\n"
            "📋 <b>Masalan:</b>\n"
            "• <code>/avtopilot Python FastAPI da to'liq JWT auth, Redis va Postgres CRUD mikroservisini loyihala va kodini yoz</code>\n\n"
            "Iltimos, vazifangizni yozib yuboring:"
        )
        await safe_reply(message, prompt_info, reply_markup=get_architect_keyboard(), parse_mode="HTML")
        return

    from core.bot_collab import handle_agent_collaboration
    main_bot = get_main_bot_instance() or bot
    sec_bot = bot
    max_r = 6 if is_night_autopilot else 4
    asyncio.create_task(handle_agent_collaboration(task_text, message.chat.id, bot_white=main_bot, bot_black=sec_bot, origin_bot=bot, deep_mode=True, max_rounds=max_r))


@second_bot_router.message(Command("stop_collab", "stop_task", "toxtat_vazifa"))
async def cmd_stop_collab_trigger(message: Message) -> None:
    """Hamkorlik yoki avtopilotni to'xtatish."""
    from core.bot_collab import stop_collab
    stopped = stop_collab(str(message.chat.id))
    if stopped:
        await safe_reply(message, "🛑 <b>Hamkorlik / Avtopilot vazifasi to'xtatildi.</b>", reply_markup=get_architect_keyboard())
    else:
        await safe_reply(message, "⚠️ Hozirda faol hamkorlik vazifasi mavjud emas.", reply_markup=get_architect_keyboard())


@second_bot_router.message(Command("project", "loyiha"))
@second_bot_router.message(F.text.lower().startswith(("/project", "/loyiha", "📦 loyiha yaratish")))
async def cmd_project_trigger(message: Message, bot: Bot) -> None:
    """MetaGPT/ChatDev to'liq loyiha arxitekturasi va in-memory ZIP eksport."""
    raw_text = (message.text or "").strip()
    if message.chat.id < 0:
        cmd_mention = re.match(r"^/\w+@(\w+)", raw_text)
        bot_info = await bot.get_me()
        target_uname = (bot_info.username or "architect7_bot").lower()
        if not cmd_mention or cmd_mention.group(1).lower() != target_uname:
            return

    clean_task = re.sub(r"^(?:/project|/loyiha|📦 Loyiha Yaratish \(ZIP\))[:\s]*", "", raw_text, flags=re.IGNORECASE).strip()
    if not clean_task:
        await safe_reply(
            message,
            "📦 <b>MetaGPT / ChatDev Avtonom Loyiha Quruvchi:</b>\n\n"
            "SuperAgent va Arxitektor birgalikda to'liq arxitektura va barcha fayllar kodini yozadi hamda sizga tayyor <b>.zip</b> arxiv qilib jo'natadi!\n\n"
            "💡 <b>Foydalanish:</b> <code>/project [loyiha g'oyasi]</code>\n"
            "Masalan: <code>/project Telegram ob-havo boti va aiogram 3 SQLite bazasi bilan</code>",
            reply_markup=get_architect_keyboard()
        )
        return

    from core.bot_collab import handle_project_generation
    main_bot = get_main_bot_instance() or bot
    asyncio.create_task(handle_project_generation(clean_task, message.chat.id, bot_white=main_bot, bot_black=bot, origin_bot=bot))


@second_bot_router.message(Command("ovozli_suhbat", "audio_suhbat", "voice_chat"))
@second_bot_router.message(F.text.lower().startswith(("/ovozli_suhbat", "/audio_suhbat", "🎙️ ovozli suhbat")))
async def cmd_audio_chat_trigger(message: Message, bot: Bot) -> None:
    """SuperAgent va Arxitektor o'rtasida jonli ovozli suhbat (Edge-TTS)."""
    raw_text = (message.text or "").strip()
    if message.chat.id < 0:
        cmd_mention = re.match(r"^/\w+@(\w+)", raw_text)
        bot_info = await bot.get_me()
        target_uname = (bot_info.username or "architect7_bot").lower()
        if not cmd_mention or cmd_mention.group(1).lower() != target_uname:
            return

    from core.bot_collab import handle_free_chit_chat, parse_topic_and_turns
    topic_text, parsed_turns = parse_topic_and_turns(raw_text, default_turns=6)

    main_bot = get_main_bot_instance() or bot
    sec_bot = bot
    asyncio.create_task(handle_free_chit_chat(topic_text, message.chat.id, bot_white=main_bot, bot_black=sec_bot, origin_bot=bot, turns=parsed_turns, audio_mode=True))


@second_bot_router.message(Command("profile", "profil", "memory"))
@second_bot_router.message(F.text.lower().in_(("/profile", "/profil", "🧠 profil", "profilim")))
async def cmd_profile_trigger(message: Message) -> None:
    """Foydalanuvchi bilimlari profili (Mem0)."""
    from core.mem0_agent import get_user_profile_report
    user_id = str(message.from_user.id)
    report = await get_user_profile_report(user_id)
    await safe_reply(message, report, reply_markup=get_architect_keyboard())


def build_architect_models_keyboard() -> InlineKeyboardMarkup:
    """Arxitektor AI bepul modellar menyusi uchun inline klaviatura."""
    from core.mistral_conversations import mistral_agent_client
    models = mistral_agent_client.get_model_status_list()
    b = InlineKeyboardBuilder()

    is_auto = (mistral_agent_client.forced_model_id is None)
    auto_text = "🔄 Avtomatik Kaskad (Tavsiya) ✅" if is_auto else "🔄 Avtomatik Kaskadga o'tish"
    b.button(text=auto_text, callback_data="arch_model:auto")

    for m in models:
        prefix = "✅ " if m["is_forced"] else (m["badge"] + " ")
        b.button(text=f"{prefix}{m['name']}", callback_data=f"arch_model:{m['id']}")

    b.adjust(1)
    return b.as_markup()


@second_bot_router.message(Command("models", "model", "modellar"))
@second_bot_router.message(F.text == "🤖 AI Modellar")
@second_bot_router.message(F.text.lower().in_(("ai modellar", "modellar", "models", "bepul modellar", "🤖 ai modellar", "ai model")))
async def cmd_architect_models(message: Message, bot: Optional[Bot] = None) -> None:
    """Arxitektor AI bepul modellar menyusi va kaskad holati."""
    try:
        from core.mistral_conversations import mistral_agent_client
        mode_desc = "Avtomatik Kaskad (Bittasi limitga uchrasa, darhol keyingisiga o'tadi)" if not mistral_agent_client.forced_model_id else f"Qo'lda tanlangan: <b>{mistral_agent_client.forced_model_id}</b>"
        text = (
            "🤖 <b>Arxitektor AI Bepul Modellari & Avto-Failover Tizimi</b>\n\n"
            f"🎯 <b>Joriy Faol Model:</b> <code>{mistral_agent_client.last_used_model}</code>\n"
            f"⚙️ <b>Tanlangan Rejim:</b> <i>{mode_desc}</i>\n\n"
            "💡 <b>Qanday ishlaydi?</b>\n"
            "• Arxitektor doimiy ravishda 12 ta eng kuchli bepul AI modellar kaskadiga ulangan:\n"
            "  — 🌪 Mistral Agent & Codestral (Dasturchi/Arxitektor);\n"
            "  — 🧠 DeepSeek V4 Flash Free (1M kontekst);\n"
            "  — 🌊 Poolside Laguna S 2.1 (Arxitektor modeli);\n"
            "  — 🔬 NVIDIA Nemotron Super 120B;\n"
            "  — 💎 Google Gemini 3.1 & 3.5 Flash Lite;\n"
            "  — 🔥 Nex-AGI N2.5 Pro;\n"
            "• Agar bitta model limiti tugasa (429/quota), tizim to'xtab qolmasdan <b>avtomatik ravishda keyingi modelga o'tadi</b>!\n\n"
            "Kerakli modelni tanlang yoki avtomatik kaskad rejimida qoldiring:"
        )
        kb = build_architect_models_keyboard()
        await safe_reply(message, text, reply_markup=kb)
    except Exception as exc:
        logger.error("cmd_architect_models xatosi: %s", exc, exc_info=True)
        await safe_reply(message, f"⚠️ Modellar menyusini yuklashda xatolik yuz berdi: {exc}")


@second_bot_router.callback_query(F.data.startswith("arch_model:"))
async def cb_architect_select_model(callback: CallbackQuery) -> None:
    """Arxitektor AI modelini almashtirish callbacki."""
    selected_id = callback.data.split(":", 1)[1]
    from core.mistral_conversations import mistral_agent_client
    ok = mistral_agent_client.set_forced_model(selected_id)
    if ok:
        if selected_id == "auto":
            alert_text = "🔄 Avtomatik kaskad yoqildi! Bepul modellar o'zaro navbatlashadi."
        else:
            alert_text = f"✅ Model muvaffaqiyatli tanlandi: {selected_id}"
        await callback.answer(alert_text, show_alert=True)
        try:
            await callback.message.edit_reply_markup(reply_markup=build_architect_models_keyboard())
        except Exception:
            pass
    else:
        await callback.answer("⚠️ Model topilmadi.", show_alert=True)


@second_bot_router.message(Command("suhbat", "chat", "gaplash"))
@second_bot_router.message(F.text.lower().startswith(("/suhbat", "/chat", "/gaplash", "🗣️ erkin suhbat")))
async def cmd_free_chat_trigger(message: Message, bot: Bot) -> None:
    """SuperAgent bilan erkin mavzuda jonli muloqot (AI Lounge)."""
    raw_text = (message.text or "").strip()
    if message.chat.id < 0:
        cmd_mention = re.match(r"^/\w+@(\w+)", raw_text)
        bot_info = await bot.get_me()
        target_uname = (bot_info.username or "architect7_bot").lower()
        if not cmd_mention or cmd_mention.group(1).lower() != target_uname:
            return

    from core.bot_collab import handle_free_chit_chat, parse_topic_and_turns
    topic_text, parsed_turns = parse_topic_and_turns(raw_text, default_turns=8)

    main_bot = get_main_bot_instance() or bot
    sec_bot = bot
    asyncio.create_task(handle_free_chit_chat(topic_text, message.chat.id, bot_white=main_bot, bot_black=sec_bot, origin_bot=bot, turns=parsed_turns))


@second_bot_router.message(Command("bahs", "debate", "tortishuv"))
@second_bot_router.message(F.text.lower().startswith(("/bahs", "/debate", "/tortishuv", "⚔️ intellektual bahs")))
async def cmd_debate_trigger(message: Message, bot: Bot) -> None:
    """SuperAgent bilan qarama-qarshi intellektual bahs va jonli hakamlik ovoz berish."""
    raw_text = (message.text or "").strip()
    if message.chat.id < 0:
        cmd_mention = re.match(r"^/\w+@(\w+)", raw_text)
        bot_info = await bot.get_me()
        target_uname = (bot_info.username or "architect7_bot").lower()
        if not cmd_mention or cmd_mention.group(1).lower() != target_uname:
            return

    from core.bot_collab import handle_agent_debate, parse_topic_and_turns
    topic_text, parsed_turns = parse_topic_and_turns(raw_text, default_turns=6)

    main_bot = get_main_bot_instance() or bot
    sec_bot = bot
    asyncio.create_task(handle_agent_debate(topic_text, message.chat.id, bot_white=main_bot, bot_black=sec_bot, origin_bot=bot, rounds=parsed_turns))


@second_bot_router.callback_query(F.data.startswith("collab_vote:"))
async def cb_architect_collab_vote(callback: CallbackQuery) -> None:
    """Multi-Agent Debate hakamlik ovozlarini hisoblash va natijalarni jonli yangilash."""
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("⚠️ Noto'g'ri ovoz berish formati.", show_alert=True)
        return

    _, debate_id, choice = parts
    from core.bot_collab import DEBATE_VOTES
    debate = DEBATE_VOTES.get(debate_id)
    if not debate:
        await callback.answer("⏳ Ushbu bahs uchun ovoz berish yakunlangan yoki mavjud emas.", show_alert=True)
        return

    user_id = callback.from_user.id
    for k in ["superagent", "architect", "draw"]:
        debate[k].discard(user_id)

    debate[choice].add(user_id)

    s_count = len(debate["superagent"])
    a_count = len(debate["architect"])
    d_count = len(debate["draw"])
    total = s_count + a_count + d_count

    s_pct = int((s_count / total) * 100) if total > 0 else 0
    a_pct = int((a_count / total) * 100) if total > 0 else 0
    d_pct = int((d_count / total) * 100) if total > 0 else 0

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    b.button(text=f"🤖 SuperAgent ({s_count} ta • {s_pct}%)", callback_data=f"collab_vote:{debate_id}:superagent")
    b.button(text=f"🌪 Arxitektor ({a_count} ta • {a_pct}%)", callback_data=f"collab_vote:{debate_id}:architect")
    b.button(text=f"🤝 Durang ({d_count} ta • {d_pct}%)", callback_data=f"collab_vote:{debate_id}:draw")
    b.adjust(2, 1)

    try:
        await callback.message.edit_reply_markup(reply_markup=b.as_markup())
    except Exception:
        pass

    target_name = "SuperAgent" if choice == "superagent" else ("Arxitektor" if choice == "architect" else "Durang")
    await callback.answer(f"✅ Ovozingiz qabul qilindi: {target_name} ({total} ta ovoz berildi)!", show_alert=False)


@second_bot_router.message(Command("stop_suhbat", "stop_chat", "toxtat_suhbat"))
async def cmd_stop_suhbat_trigger(message: Message) -> None:
    """Erkin suhbat yoki bahsni to'xtatish."""
    from core.bot_collab import stop_chit_chat
    stopped = stop_chit_chat(str(message.chat.id))
    if stopped:
        await safe_reply(message, "🛑 <b>Erkin suhbat / Bahs to'xtatildi.</b>", reply_markup=get_architect_keyboard())
    else:
        await safe_reply(message, "⚠️ Hozirda faol suhbat yoki bahs mavjud emas.", reply_markup=get_architect_keyboard())


@second_bot_router.message(Command("chess", "shaxmat"))
@second_bot_router.message(F.text == "♟️ AI Shaxmat Bahsi")
async def cmd_chess_trigger(message: Message, bot: Bot) -> None:
    """Shaxmat o'yinini boshlash."""
    raw_text = (message.text or "").strip()
    if message.chat.id < 0:
        cmd_mention = re.match(r"^/\w+@(\w+)", raw_text)
        bot_info = await bot.get_me()
        target_uname = (bot_info.username or "architect7_bot").lower()
        if not cmd_mention or cmd_mention.group(1).lower() != target_uname:
            return

    from core.bot_collab import handle_start_chess
    main_bot = get_main_bot_instance() or bot
    await handle_start_chess(message, bot_white=main_bot, bot_black=bot)


@second_bot_router.message(Command("stop_chess", "chess_stop", "shaxmat_tamom"))
async def cmd_stop_chess_trigger(message: Message) -> None:
    """Shaxmat o'yinini to'xtatish."""
    from core.bot_collab import stop_chess_game
    chat_id = str(message.chat.id)
    stopped = stop_chess_game(chat_id)
    if stopped:
        await safe_reply(message, "🛑 <b>Shaxmat o'yini to'xtatildi.</b>", reply_markup=get_architect_keyboard())
    else:
        await safe_reply(message, "⚠️ Hozirda faol shaxmat o'yini mavjud emas.", reply_markup=get_architect_keyboard())


@second_bot_router.message(Command("code"))
@second_bot_router.message(F.text == "💻 Kod Tahlili & Audit")
async def cmd_code_audit_menu(message: Message) -> None:
    """Kod tahlili va audit bo'limi."""
    text = (
        "💻 <b>Kod Tahlili va Xavfsizlik Auditi</b>\n\n"
        "Tahlil qilmoqchi bo'lgan kodingizni to'g'ridan-to'g'ri shu yerga yuboring (Python, JS/TS, Go, Java, Rust, SQL va boshqalar).\n\n"
        "🔍 <b>Men quyidagilarni aniqlab beraman:</b>\n"
        "1. ⚠️ Yashirin xatolar va mantiqiy nuqsonlar;\n"
        "2. 🛡 Xavfsizlik zaifliklari (SQLi, XSS, Memory leak);\n"
        "3. ⚡ Tezlikni oshirish va SQL/algoritm optimallashtirish;\n"
        "4. 💎 Clean Code va SOLID tamoyillariga mos qayta yozilgan (Refactored) toza kod!\n\n"
        "Kodingizni xabar sifatida yuboring:"
    )
    await safe_reply(message, text, reply_markup=get_architect_keyboard())


@second_bot_router.message(F.text == "🏗 Dastur Arxitekturasi")
async def cmd_architecture_menu(message: Message) -> None:
    """Dastur arxitekturasi va tizim dizayni."""
    text = (
        "🏗 <b>Tizim Arxitekturasi va Dastur Loyihalash</b>\n\n"
        "Yangi startap yoki murakkab tizim boshlayapsizmi? Menga loyihangiz talablarini yozing:\n\n"
        "📋 <b>Masalan:</b>\n"
        "• <i>\"100,000 foydalanuvchili e-tijorat tizimi uchun arxitektura va DB schema tuzib ber\"</i>\n"
        "• <i>\"Telegram bot va WebApp uchun microservice arxitekturasini loyihala\"</i>\n"
        "• <i>\"PostgreSQL vs MongoDB: mening loyihamga qaysi biri mos?\"</i>\n\n"
        "Loyihangiz tavsifini yozing, men batafsil tizim loyihasini (System Design) tuzib beraman!"
    )
    await safe_reply(message, text, reply_markup=get_architect_keyboard())


@second_bot_router.message(F.text == "ℹ️ Arxitektor Haqida")
async def cmd_about_menu(message: Message) -> None:
    """Arxitektor bot haqida ma'lumot."""
    text = (
        "ℹ️ <b>Arxitektor Agent Bot (@architect7_bot)</b>\n\n"
        "• <b>Asosiy AI yadrosi:</b> Mistral AI Agent (<code>ag_01a0ba16a68173e8a1cdb3ead308ff14</code>)\n"
        "• <b>Ko'p agentli modellar:</b> CAMEL-AI, Microsoft AutoGen, ChatDev, MAPR Peer Review\n"
        "• <b>Xususiyatlari:</b> System Design, Code Review, Autonomous Dual-Agent Collaboration, Live Chess\n"
        "• <b>Hamkor bot:</b> SuperAgent AI (@SuperAgent)\n\n"
        "Muallif va dasturchi: <b>Developer</b>"
    )
    await safe_reply(message, text, reply_markup=get_architect_keyboard())


@second_bot_router.message(F.text)
async def handle_second_bot_text(message: Message, bot: Bot) -> None:
    """Arxitektor botga kelgan matnli xabarlar."""
    text = (message.text or "").strip()
    is_group = message.chat.type in ("group", "supergroup")

    logger.info("📩 Arxitektor bot matn oldi: is_group=%s, text=%s", is_group, text[:60])

    # Agar guruhda bo'lsa, botga murojaat qilinganligini tekshiramiz
    if is_group:
        is_mentioned = "@architect7_bot" in text.lower() or "arxitektor" in text.lower()
        bot_tg_id = int(bot.token.split(":")[0]) if ":" in bot.token else 0
        is_reply_to_bot = (
            message.reply_to_message
            and message.reply_to_message.from_user
            and message.reply_to_message.from_user.id == bot_tg_id
        )
        if not (is_mentioned or is_reply_to_bot):
            return  # Begona guruh xabarlariga aralashmaydi

        clean_text = text.replace("@architect7_bot", "").replace("@Architect7_bot", "").strip()
    else:
        clean_text = text

    if not clean_text:
        await safe_reply(message, "Salom! Sizga qanday yordam bera olaman?", reply_markup=get_architect_keyboard())
        return

    # Typing ko'rsatkichini berish
    try:
        await bot.send_chat_action(message.chat.id, "typing")
    except Exception:
        pass

    # Loyiha yaratish tekshiruvi (MetaGPT / ChatDev)
    if clean_text.lower().startswith(("/project", "/loyiha")):
        from core.bot_collab import handle_project_generation
        proj_task = re.sub(r"^(?:/project|/loyiha)[:\s]*", "", clean_text, flags=re.IGNORECASE).strip()
        main_bot = get_main_bot_instance() or bot
        asyncio.create_task(handle_project_generation(proj_task or clean_text, message.chat.id, bot_white=main_bot, bot_black=bot, origin_bot=bot))
        return

    # Ovozli suhbat tekshiruvi (Edge-TTS)
    if clean_text.lower().startswith(("/ovozli_suhbat", "/audio_suhbat")):
        from core.bot_collab import handle_free_chit_chat, parse_topic_and_turns
        topic_text, parsed_turns = parse_topic_and_turns(clean_text, default_turns=6)
        main_bot = get_main_bot_instance() or bot
        asyncio.create_task(handle_free_chit_chat(topic_text, message.chat.id, bot_white=main_bot, bot_black=bot, origin_bot=bot, turns=parsed_turns, audio_mode=True))
        return

    # Modellar kaskadi menyusi
    if clean_text.lower() in ("/models", "/model", "modellar", "ai modellar", "🤖 ai modellar", "ai model", "bepul modellar") or any(w in clean_text.lower() for w in ["ai model", "modellar", "qaysi model"]):
        await cmd_architect_models(message, bot)
        return

    # Foydalanuvchi bilimlari profili (Mem0)
    if clean_text.lower() in ("/profile", "/profil", "profilim"):
        from core.mem0_agent import get_user_profile_report
        user_id = str(message.from_user.id)
        report = await get_user_profile_report(user_id)
        await safe_reply(message, report, reply_markup=get_architect_keyboard())
        return

    # Hamkorlik buyruqlari tekshiruvi
    if clean_text.lower().startswith(("/collab", "/hamkorlik")):
        from core.bot_collab import handle_agent_collaboration
        task = re.sub(r"^(?:/collab|/hamkorlik)[:\s]*", "", clean_text, flags=re.IGNORECASE).strip()
        main_bot = get_main_bot_instance() or bot
        asyncio.create_task(handle_agent_collaboration(task or clean_text, message.chat.id, bot_white=main_bot, bot_black=bot, origin_bot=bot))
        return

    # Erkin suhbat tekshiruvi
    if clean_text.lower().startswith(("/suhbat", "/chat", "gaplashing", "birga gaplashing")):
        from core.bot_collab import handle_free_chit_chat, parse_topic_and_turns
        topic_text, parsed_turns = parse_topic_and_turns(clean_text, default_turns=8)
        main_bot = get_main_bot_instance() or bot
        asyncio.create_task(handle_free_chit_chat(topic_text, message.chat.id, bot_white=main_bot, bot_black=bot, origin_bot=bot, turns=parsed_turns))
        return

    # Shaxmat buyrug'i tekshiruvi
    if clean_text.lower().startswith(("/chess", "/shaxmat")) or clean_text.lower() in ("shaxmat", "chess", "shaxmat o'ynaylik"):
        from core.bot_collab import handle_start_chess
        main_bot = get_main_bot_instance() or bot
        await handle_start_chess(message, bot_white=main_bot, bot_black=bot)
        return

    # Arxitektor Agentdan javob olish (Multi-Model Failover kaskadi bilan)
    wait_msg = await safe_reply(message, "🧠 <i>Arxitektor Agent o'ylamoqda...</i>", parse_mode="HTML")
    try:
        ans, thinking = await mistral_agent_client.send_message(
            clean_text,
            chat_id=str(message.chat.id),
            system_instruction="Siz Telegramdagi professional Arxitektor Agent Botsiz (@architect7_bot). Foydalanuvchilar va SuperAgent bilan o'zbek tilida aniq, professional, do'stona va chuqur tahliliy tilda muloqot qiling."
        )
        try:
            await wait_msg.edit_text(ans, parse_mode="HTML")
        except Exception:
            await wait_msg.edit_text(ans, parse_mode=None)
    except Exception as e:
        logger.error("Arxitektor bot xatosi: %s", e)
        try:
            await wait_msg.edit_text(f"❌ Xatolik yuz berdi: {e}", parse_mode=None)
        except Exception:
            pass

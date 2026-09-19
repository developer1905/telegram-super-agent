"""
2-Bot: Mistral Arxitektor Agent Bot (@architect7_bot).
Mistral AI agenti (ag_01a0ba16a68173e8a1cdb3ead308ff14) orqali ishlovchi
mustaqil Telegram bot moduli.

O'zining shaxsiy menyusi, arxitektura vositalari, kod tahlilchisi va
SuperAgent bilan shaxmat bahslari boshqaruvi mavjud.
Barcha xabarlar safe_reply (HTML + xatosiz fallback) orqali uzatiladi.
"""

import logging
from typing import Optional
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
    BotCommand,
    MenuButtonCommands,
)
from aiogram.filters import Command

from config import SECOND_BOT_TOKEN
from core.mistral_conversations import mistral_agent_client

logger = logging.getLogger(__name__)

second_bot_router = Router(name="mistral_agent_bot_router")
_second_bot_instance: Optional[Bot] = None


def get_second_bot() -> Optional[Bot]:
    """2-Bot obyektini qaytaradi (agar SECOND_BOT_TOKEN mavjud bo'lsa)."""
    global _second_bot_instance
    if _second_bot_instance is None and SECOND_BOT_TOKEN:
        _second_bot_instance = Bot(token=SECOND_BOT_TOKEN)
    return _second_bot_instance


def get_architect_keyboard() -> ReplyKeyboardMarkup:
    """Arxitektor Mistral Botining shaxsiy maxsus klaviaturasi."""
    kb = [
        [
            KeyboardButton(text="🏗 Dastur Arxitekturasi"),
            KeyboardButton(text="💻 Kod Tahlili & Audit"),
        ],
        [
            KeyboardButton(text="♟️ AI Shaxmat Bahsi"),
            KeyboardButton(text="🤝 SuperAgent Collab"),
        ],
        [
            KeyboardButton(text="⚡ Mistral Agent Chat"),
            KeyboardButton(text="ℹ️ Arxitektor Haqida"),
        ],
    ]
    return ReplyKeyboardMarkup(
        keyboard=kb,
        resize_keyboard=True,
        input_field_placeholder="Arxitektorga savol yoki kod yozing...",
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
            BotCommand(command="chess", description="SuperAgent bilan shaxmat o'ynash"),
            BotCommand(command="collab", description="SuperAgent bilan hamkorlik"),
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
        "• 🏗 <b>Dasturiy arxitektura va loyihalash</b> (Microservices, DB schema, API design);\n"
        "• 💻 <b>Kod tahlili, refaktoring va xavfsizlik auditi</b>;\n"
        "• 🤝 <b>SuperAgent bilan guruhda vazifalarni parallel bajarish</b>;\n"
        "• ♟️ <b>SuperAgent bilan jonli shaxmat bahsi</b> (<code>/chess</code> yoki pastdagi tugma).\n\n"
        "Quyidagi shaxsiy menyudan kerakli bo'limni tanlang yoki to'g'ridan-to'g'ri topshiriq bering!"
    )
    await safe_reply(message, welcome_text, reply_markup=get_architect_keyboard(), parse_mode="HTML")


@second_bot_router.message(Command("help"))
async def cmd_help_second_bot(message: Message) -> None:
    """Yordam komandasi."""
    help_text = (
        "💡 <b>Arxitektor Agent Buyruqlari:</b>\n\n"
        "• <code>/start</code> yoki <code>/menu</code> — Arxitektor shaxsiy menyusini ochish\n"
        "• <code>/chess</code> yoki <code>/shaxmat</code> — SuperAgent bilan jonli shaxmat bahsini boshlash\n"
        "• <code>/stop_chess</code> — Shaxmat o'yinini to'xtatish\n"
        "• <code>/collab [vazifa]</code> — Ikkala bot birgalikda yechim ishlab chiqadi\n"
        "• <code>/code</code> — Kod tahlili va xavfsizlik auditi bo'yicha maslahat\n"
        "• Guruhda <b>@architect7_bot [savol]</b> — Guruhda botga murojaat qilish"
    )
    await safe_reply(message, help_text, reply_markup=get_architect_keyboard(), parse_mode="HTML")


@second_bot_router.message(Command("chess", "shaxmat"))
@second_bot_router.message(F.text == "♟️ AI Shaxmat Bahsi")
async def cmd_chess_trigger(message: Message, bot: Bot) -> None:
    """Shaxmat o'yinini boshlash."""
    from core.bot_collab import handle_start_chess
    sec_bot = get_second_bot()
    await handle_start_chess(message, bot_white=bot, bot_black=sec_bot)


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


@second_bot_router.message(Command("collab"))
@second_bot_router.message(F.text == "🤝 SuperAgent Collab")
async def cmd_collab_menu(message: Message) -> None:
    """SuperAgent bilan hamkorlik yo'riqnomasi."""
    text = (
        "🤝 <b>SuperAgent & Arxitektor Hamkorligi</b>\n\n"
        "Ikkala sun'iy intellekt agenti bir guruhda birlashganda kuchli tandem hosil bo'ladi:\n\n"
        "1️⃣ <b>Guruhga qo'shish:</b> Ikkala botni ham loyihangiz Telegram guruhiga qo'shing;\n"
        "2️⃣ <b>Vazifa yuklash:</b> Guruhda <code>/collab [vazifa matni]</code> deb yozing;\n"
        "3️⃣ <b>Muloqot:</b> Botlarning birontasi fikr bildirsa, ikkinchisi unga qo'shimcha qiladi;\n"
        "4️⃣ <b>Shaxmat:</b> Guruhda <code>/chess</code> yozilsa, ular bir-biri bilan o'rtoqlik uchrashuvini boshlaydi!\n\n"
        "Birgalikda ishlashga tayyormiz!"
    )
    await safe_reply(message, text, reply_markup=get_architect_keyboard())


@second_bot_router.message(F.text == "⚡ Mistral Agent Chat")
async def cmd_mistral_chat_menu(message: Message) -> None:
    """Mistral Agent bilan muloqot rejimi."""
    text = (
        "⚡ <b>Mistral Agent Faol Rejimda</b>\n\n"
        "Men <b>Mistral Large / Codestral</b> neyrotarmoqlari asosida ishlovchi agentman.\n"
        "Xotira va kontekst saqlanadi. Menga istalgan savol, g'oya, matematika yoki texnik masalani yuboring!"
    )
    await safe_reply(message, text, reply_markup=get_architect_keyboard())


@second_bot_router.message(F.text == "ℹ️ Arxitektor Haqida")
async def cmd_about_menu(message: Message) -> None:
    """Arxitektor bot haqida ma'lumot."""
    text = (
        "ℹ️ <b>Arxitektor Agent Bot (@architect7_bot)</b>\n\n"
        "• <b>Asosiy AI yadrosi:</b> Mistral AI Agent (<code>ag_01a0ba16a68173e8a1cdb3ead308ff14</code>)\n"
        "• <b>Model versiyasi:</b> Version 1 (Codestral & Mistral Large)\n"
        "• <b>Xususiyatlari:</b> System Design, Code Review, Multi-Agent Collaboration, Chess Engine\n"
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
        is_reply_to_bot = (
            message.reply_to_message
            and message.reply_to_message.from_user
            and message.reply_to_message.from_user.id == bot.id
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

    # Shaxmat buyrug'i tekshiruvi
    if clean_text.lower().startswith(("/chess", "/shaxmat")) or clean_text.lower() in ("shaxmat", "chess", "shaxmat o'ynaylik"):
        from core.bot_collab import handle_start_chess
        sec_bot = get_second_bot()
        await handle_start_chess(message, bot_white=bot, bot_black=sec_bot)
        return

    # Mistral Agentdan javob olish
    wait_msg = await safe_reply(message, "🧠 <i>Mistral Arxitektor Agent o'ylamoqda...</i>", parse_mode="HTML")
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

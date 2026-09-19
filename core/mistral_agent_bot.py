"""
2-Bot: Mistral Arxitektor Agent Bot (@architect7_bot).
Mistral AI agenti (ag_01a0ba16a68173e8a1cdb3ead308ff14) orqali ishlovchi
mustaqil Telegram bot moduli.

O'zining shaxsiy menyusi, arxitektura vositalari, kod tahlilchisi va
SuperAgent bilan shaxmat bahslari boshqaruvi mavjud.
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
        # Telegram chat menyusi tugmasini standart buyruqlar menyusiga o'rnatish (Mini App tugmasini olib tashlaydi)
        await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
        logger.info("✅ Arxitektor Bot (@architect7_bot) komandalari va shaxsiy menyusi sozlandi.")
    except Exception as exc:
        logger.warning("Arxitektor bot komandalarini sozlashda ogohlantirish: %s", exc)


@second_bot_router.message(Command("start", "menu"))
async def cmd_start_second_bot(message: Message) -> None:
    """Arxitektor bot start va shaxsiy menyusi."""
    welcome_text = (
        "🌪 **Assalomu alaykum! Men Arxitektor Agent Botman (@architect7_bot).**\n\n"
        "Men **Mistral AI** platformasidagi maxsus o'qitilgan sun'iy intellekt agenti tomonidan boshqarilaman.\n\n"
        "✨ **Mening ixtisoslashgan sohalarim:**\n"
        "• 🏗 **Dasturiy arxitektura va loyihalash** (Microservices, DB schema, API design);\n"
        "• 💻 **Kod tahlili, refaktoring va xavfsizlik auditi**;\n"
        "• 🤝 **SuperAgent bilan guruhda vazifalarni parallel bajarish**;\n"
        "• ♟️ **SuperAgent bilan jonli shaxmat bahsi** (`/chess` yoki pastdagi tugma).\n\n"
        "Quyidagi shaxsiy menyudan kerakli bo'limni tanlang yoki to'g'ridan-to'g'ri topshiriq bering!"
    )
    await message.answer(
        welcome_text,
        reply_markup=get_architect_keyboard(),
        parse_mode="Markdown"
    )


@second_bot_router.message(Command("help"))
async def cmd_help_second_bot(message: Message) -> None:
    """Yordam komandasi."""
    help_text = (
        "💡 **Arxitektor Agent Buyruqlari:**\n\n"
        "• `/start` yoki `/menu` — Arxitektor shaxsiy menyusini ochish\n"
        "• `/chess` yoki `/shaxmat` — SuperAgent bilan jonli shaxmat bahsini boshlash\n"
        "• `/stop_chess` — Shaxmat o'yinini to'xtatish\n"
        "• `/collab [vazifa]` — Ikkala bot birgalikda yechim ishlab chiqadi\n"
        "• `/code` — Kod tahlili va xavfsizlik auditi bo'yicha maslahat\n"
        "• Guruhda `@architect7_bot [savol]` — Guruhda botga murojaat qilish"
    )
    await message.answer(help_text, reply_markup=get_architect_keyboard(), parse_mode="Markdown")


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
        await message.answer("🛑 **Shaxmat o'yini to'xtatildi.**", reply_markup=get_architect_keyboard(), parse_mode="Markdown")
    else:
        await message.answer("⚠️ Hozirda faol shaxmat o'yini mavjud emas.", reply_markup=get_architect_keyboard(), parse_mode="Markdown")


@second_bot_router.message(Command("code"))
@second_bot_router.message(F.text == "💻 Kod Tahlili & Audit")
async def cmd_code_audit_menu(message: Message) -> None:
    """Kod tahlili va audit bo'limi."""
    text = (
        "💻 **Kod Tahlili va Xavfsizlik Auditi**\n\n"
        "Tahlil qilmoqchi bo'lgan kodingizni to'g'ridan-to'g'ri shu yerga yuboring (Python, JS/TS, Go, Java, Rust, SQL va boshqalar).\n\n"
        "🔍 **Men quyidagilarni aniqlab beraman:**\n"
        "1. ⚠️ Yashirin xatolar va mantiqiy nuqsonlar;\n"
        "2. 🛡 Xavfsizlik zaifliklari (SQLi, XSS, Memory leak);\n"
        "3. ⚡ Tezlikni oshirish va SQL/algoritm optimallashtirish;\n"
        "4. 💎 Clean Code va SOLID tamoyillariga mos qayta yozilgan (Refactored) toza kod!\n\n"
        "Kodingizni xabar sifatida yuboring:"
    )
    await message.answer(text, reply_markup=get_architect_keyboard(), parse_mode="Markdown")


@second_bot_router.message(F.text == "🏗 Dastur Arxitekturasi")
async def cmd_architecture_menu(message: Message) -> None:
    """Dastur arxitekturasi va tizim dizayni."""
    text = (
        "🏗 **Tizim Arxitekturasi va Dastur Loyihalash**\n\n"
        "Yangi startap yoki murakkab tizim boshlayapsizmi? Menga loyihangiz talablarini yozing:\n\n"
        "📋 **Masalan:**\n"
        "• *\"100,000 foydalanuvchili e-tijorat tizimi uchun arxitektura va DB schema tuzib ber\"*\n"
        "• *\"Telegram bot va WebApp uchun microservice arxitekturasini loyihala\"*\n"
        "• *\"PostgreSQL vs MongoDB: mening loyihamga qaysi biri mos?\"*\n\n"
        "Loyihangiz tavsifini yozing, men batafsil tizim loyihasini (System Design) tuzib beraman!"
    )
    await message.answer(text, reply_markup=get_architect_keyboard(), parse_mode="Markdown")


@second_bot_router.message(Command("collab"))
@second_bot_router.message(F.text == "🤝 SuperAgent Collab")
async def cmd_collab_menu(message: Message) -> None:
    """SuperAgent bilan hamkorlik yo'riqnomasi."""
    text = (
        "🤝 **SuperAgent & Arxitektor Hamkorligi**\n\n"
        "Ikkala sun'iy intellekt agenti bir guruhda birlashganda kuchli tandem hosil bo'ladi:\n\n"
        "1️⃣ **Guruhga qo'shish:** Ikkala botni ham loyihangiz Telegram guruhiga qo'shing;\n"
        "2️⃣ **Vazifa yuklash:** Guruhda `/collab [vazifa matni]` deb yozing;\n"
        "3️⃣ **Muloqot:** Botlarning birontasi fikr bildirsa, ikkinchisi unga qo'shimcha qiladi;\n"
        "4️⃣ **Shaxmat:** Guruhda `/chess` yozilsa, ular bir-biri bilan o'rtoqlik uchrashuvini boshlaydi!\n\n"
        "Birgalikda ishlashga tayyormiz!"
    )
    await message.answer(text, reply_markup=get_architect_keyboard(), parse_mode="Markdown")


@second_bot_router.message(F.text == "⚡ Mistral Agent Chat")
async def cmd_mistral_chat_menu(message: Message) -> None:
    """Mistral Agent bilan muloqot rejimi."""
    text = (
        "⚡ **Mistral Agent Faol Rejimda**\n\n"
        "Men **Mistral Large / Codestral** neyrotarmoqlari asosida ishlovchi agentman.\n"
        "Xotira va kontekst saqlanadi. Menga istalgan savol, g'oya, matematika yoki texnik masalani yuboring!"
    )
    await message.answer(text, reply_markup=get_architect_keyboard(), parse_mode="Markdown")


@second_bot_router.message(F.text == "ℹ️ Arxitektor Haqida")
async def cmd_about_menu(message: Message) -> None:
    """Arxitektor bot haqida ma'lumot."""
    text = (
        "ℹ️ **Arxitektor Agent Bot (@architect7_bot)**\n\n"
        "• **Asosiy AI yadrosi:** Mistral AI Agent (`ag_01a0ba16a68173e8a1cdb3ead308ff14`)\n"
        "• **Model versiyasi:** Version 1 (Codestral & Mistral Large)\n"
        "• **Xususiyatlari:** System Design, Code Review, Multi-Agent Collaboration, Chess Engine\n"
        "• **Hamkor bot:** SuperAgent AI (@SuperAgent)\n\n"
        "Muallif va dasturchi: **Developer**"
    )
    await message.answer(text, reply_markup=get_architect_keyboard(), parse_mode="Markdown")


@second_bot_router.message(F.text)
async def handle_second_bot_text(message: Message, bot: Bot) -> None:
    """Arxitektor botga kelgan matnli xabarlar."""
    text = (message.text or "").strip()
    is_group = message.chat.type in ("group", "supergroup")

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
        await message.answer("Salom! Sizga qanday yordam bera olaman?", reply_markup=get_architect_keyboard())
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
    wait_msg = await message.answer("🧠 *Mistral Arxitektor Agent o'ylamoqda...*", parse_mode="Markdown")
    try:
        ans, thinking = await mistral_agent_client.send_message(
            clean_text,
            chat_id=str(message.chat.id),
            system_instruction="Siz Telegramdagi professional Arxitektor Agent Botsiz (@architect7_bot). Foydalanuvchilar va SuperAgent bilan o'zbek tilida aniq, professional, do'stona va chuqur tahliliy tilda muloqot qiling."
        )
        try:
            await wait_msg.edit_text(ans, parse_mode="Markdown")
        except Exception:
            await wait_msg.edit_text(ans, parse_mode=None)
    except Exception as e:
        logger.error("Arxitektor bot xatosi: %s", e)
        try:
            await wait_msg.edit_text(f"❌ Xatolik yuz berdi: {e}")
        except Exception:
            pass

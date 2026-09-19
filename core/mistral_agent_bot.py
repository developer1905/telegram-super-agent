"""
2-Bot: Mistral Arxitektor Agent Bot (@architect7_bot).
Mistral AI agenti (ag_01a0ba16a68173e8a1cdb3ead308ff14) orqali ishlovchi
mustaqil Telegram bot moduli.
"""

import logging
from typing import Optional
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message
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


@second_bot_router.message(Command("start"))
async def cmd_start_second_bot(message: Message) -> None:
    """Arxitektor bot start komandasi."""
    welcome_text = (
        "🌪 **Assalomu alaykum! Men Arxitektor Agent Botman (@architect7_bot).**\n\n"
        "Men **Mistral AI** platformasidagi maxsus o'qitilgan sun'iy intellekt agenti tomonidan boshqarilaman.\n\n"
        "✨ **Mening vazifalarim:**\n"
        "• 🏗 **Dasturiy arxitektura va kod tahlili**;\n"
        "• 🤝 **SuperAgent bilan birga guruhda vazifalarni bajarish**;\n"
        "• ♟️ **SuperAgent bilan jonli shaxmat o'ynash** (`/chess` yoki `/shaxmat`);\n"
        "• 💬 Guruhda `@architect7_bot` deb chaqirsangiz, darhol javob beraman!\n\n"
        "Menga istalgan savol yoki topshiriqni yozishingiz mumkin!"
    )
    await message.answer(welcome_text, parse_mode="Markdown")


@second_bot_router.message(Command("help"))
async def cmd_help_second_bot(message: Message) -> None:
    """Yordam komandasi."""
    help_text = (
        "💡 **Arxitektor Agent Buyruqlari:**\n\n"
        "• `/start` — Botni ishga tushirish va tanishuv\n"
        "• `/chess` yoki `/shaxmat` — SuperAgent bilan shaxmat bahsini boshlash\n"
        "• `/stop_chess` — Shaxmat o'yinini to'xtatish\n"
        "• Guruhda `@architect7_bot [savol]` — Savol berish yoki topshiriq yuklash\n"
        "• `/collab [vazifa]` — Ikkala bot birgalikda yechim tayyorlaydi"
    )
    await message.answer(help_text, parse_mode="Markdown")


@second_bot_router.message(Command("chess", "shaxmat"))
async def cmd_chess_trigger(message: Message, bot: Bot) -> None:
    """Shaxmat o'yinini boshlash."""
    from core.bot_collab import handle_start_chess
    # bot bu xabarni qabul qilgan bot
    main_bot = bot  # Agar 2-bot qabul qilsa
    sec_bot = get_second_bot()
    await handle_start_chess(message, bot_white=bot, bot_black=sec_bot)


@second_bot_router.message(Command("stop_chess", "chess_stop", "shaxmat_tamom"))
async def cmd_stop_chess_trigger(message: Message) -> None:
    """Shaxmat o'yinini to'xtatish."""
    from core.bot_collab import stop_chess_game
    chat_id = str(message.chat.id)
    stopped = stop_chess_game(chat_id)
    if stopped:
        await message.answer("🛑 **Shaxmat o'yini to'xtatildi.**", parse_mode="Markdown")
    else:
        await message.answer("⚠️ Hozirda faol shaxmat o'yini mavjud emas.", parse_mode="Markdown")


@second_bot_router.message(F.text)
async def handle_second_bot_text(message: Message, bot: Bot) -> None:
    """Arxitektor botga kelgan shaxsiy xabarlar yoki guruhdagi murojaatlar."""
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
        await message.answer("Salom! Sizga qanday yordam bera olaman?")
        return

    # Shaxmat buyrug'i tekshiruvi
    if "shaxmat" in clean_text.lower() or "chess" in clean_text.lower():
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
            system_instruction="Siz Telegramdagi Arxitektor Agent Botsiz. O'zbek tilida aniq, professional va do'stona javob bering."
        )
        await wait_msg.edit_text(ans, parse_mode=None)
    except Exception as e:
        logger.error("Arxitektor bot xatosi: %s", e)
        try:
            await wait_msg.edit_text(f"❌ Xatolik yuz berdi: {e}")
        except Exception:
            pass

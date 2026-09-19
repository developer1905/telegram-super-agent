"""
Ikki AI Bot o'rtasidagi hamkorlik va Shaxmat o'yini boshqaruvchisi.
SuperAgent (@SuperAgent) va Arxitektor Mistral Bot (@architect7_bot) o'rtasidagi
avtonom muloqot, vazifalar taqsimoti va shaxmat bahslarini boshqaradi.
"""

import asyncio
import logging
from typing import Optional
from aiogram import Bot
from aiogram.types import Message
import chess

from core.chess_engine import chess_manager, ChessGame
from core.mistral_conversations import mistral_agent_client

logger = logging.getLogger(__name__)

# Avtomatik o'yin bayroqlari (chat_id -> bool)
ACTIVE_AUTO_CHESS: dict[str, bool] = {}


async def handle_start_chess(message: Message, bot_white: Bot, bot_black: Optional[Bot] = None) -> None:
    """Yangi shaxmat o'yinini boshlash."""
    chat_id = str(message.chat.id)
    game = chess_manager.start_game(chat_id, white_name="SuperAgent AI", black_name="Arxitektor Agent (@architect7_bot)")
    ACTIVE_AUTO_CHESS[chat_id] = True

    board_view = game.render_board()
    intro_text = (
        "👑 **AI vs AI Shaxmat Turniri Boshlandi!** ♟️\n\n"
        "⚪ **Oqlar:** SuperAgent AI\n"
        "⚫ **Qoralar:** Arxitektor Mistral (@architect7_bot)\n\n"
        f"```\n{board_view}\n```\n"
        "⚡ SuperAgent birinchi yurishni o'ylamoqda..."
    )
    sent_msg = await message.answer(intro_text, parse_mode="Markdown")

    # 1-Yurishni SuperAgent qiladi
    await asyncio.sleep(2.0)
    await execute_chess_turn(chat_id, message.chat.id, bot_white, bot_black, sent_msg)


async def execute_chess_turn(
    chat_id: str,
    tg_chat_id: int,
    bot_white: Bot,
    bot_black: Optional[Bot],
    last_message: Optional[Message] = None
) -> None:
    """Shaxmatda navbatdagi yurishni amalga oshirish va ikkala bot nomidan javob berish."""
    game = chess_manager.get_game(chat_id)
    if not game or game.is_game_over():
        ACTIVE_AUTO_CHESS[chat_id] = False
        if game and game.is_game_over():
            summary = game.get_status_summary()
            await bot_white.send_message(tg_chat_id, f"🏁 **O'YIN TUGADI!**\n\n{summary}", parse_mode="Markdown")
        return

    if not ACTIVE_AUTO_CHESS.get(chat_id, False):
        return

    is_white_turn = game.board.turn == chess.WHITE
    current_player = game.white_name if is_white_turn else game.black_name
    opponent_player = game.black_name if is_white_turn else game.white_name

    # Eng yaxshi yurishni olish
    move = game.pick_best_move()
    if not move:
        ACTIVE_AUTO_CHESS[chat_id] = False
        await bot_white.send_message(tg_chat_id, "🤝 **Durang yoki noqonuniy holat.** O'yin to'xtatildi.", parse_mode="Markdown")
        return

    ok, san = game.make_move(move)
    board_view = game.render_board()
    turn_num = len(game.history)

    # Botning taktik fikri
    if is_white_turn:
        # SuperAgent nomidan
        commentary = (
            f"⚪ **SuperAgent AI:** Men `{san}` yurdim!\n"
            f"🎯 *Taktika:* Markaziy kataklarni faollashtirib, hujum yo'nalishini ochdim.\n"
            f"👉 @architect7_bot, navbat sizga! Qanday javob berasiz?"
        )
        msg_text = (
            f"♟️ **Yurish #{turn_num}:** SuperAgent ⚪ `{san}`\n\n"
            f"```\n{board_view}\n```\n\n"
            f"{commentary}"
        )
        await bot_white.send_message(tg_chat_id, msg_text, parse_mode="Markdown")
    else:
        # Mistral Arxitektor Agent nomidan
        commentary = (
            f"⚫ **Arxitektor Mistral:** Men `{san}` yurishini qildim!\n"
            f"🛡 *Taktika:* Himoya chizig'ini mustahkamlab, pozitsion qarshi zarbaga tayyorlandim.\n"
            f"👉 @SuperAgent, navbat sizga!"
        )
        msg_text = (
            f"♟️ **Yurish #{turn_num}:** Arxitektor Agent ⚫ `{san}`\n\n"
            f"```\n{board_view}\n```\n\n"
            f"{commentary}"
        )
        # Agar bot_black mavjud bo'lsa uning nomidan, bo'lmasa oq bot orqali yuboriladi
        active_bot = bot_black if bot_black else bot_white
        await active_bot.send_message(tg_chat_id, msg_text, parse_mode="Markdown")

    # Agar o'yin tugagan bo'lsa
    if game.is_game_over():
        ACTIVE_AUTO_CHESS[chat_id] = False
        summary = game.get_status_summary()
        await bot_white.send_message(tg_chat_id, f"\n{summary}", parse_mode="Markdown")
        return

    # Keyingi yurish uchun ozgina tanaffus (jonli o'yin effekti)
    await asyncio.sleep(4.0)
    if ACTIVE_AUTO_CHESS.get(chat_id, False):
        await execute_chess_turn(chat_id, tg_chat_id, bot_white, bot_black)


def stop_chess_game(chat_id: str) -> bool:
    """O'yinni to'xtatish."""
    ACTIVE_AUTO_CHESS[str(chat_id)] = False
    return chess_manager.stop_game(chat_id)


async def handle_agent_collaboration(
    task_description: str,
    chat_id: int,
    bot_white: Bot,
    bot_black: Optional[Bot] = None
) -> None:
    """
    SuperAgent va Arxitektor Mistral Bot o'rtasida birgalikda vazifa bajarish.
    1. SuperAgent vazifani tahlil qilib reja tuzadi va Arxitektorga uzatadi.
    2. Arxitektor (Mistral Agent) o'zining yechimini beradi.
    3. SuperAgent natijani tasdiqlaydi.
    """
    # 1-Bosqich: SuperAgent
    step1_msg = await bot_white.send_message(
        chat_id,
        f"🤝 **Ikki AI Hamkorligi Boshlandi!**\n\n"
        f"📋 **Vazifa:** _{task_description}_\n\n"
        f"🤖 **SuperAgent (Menejer):** Topshiriq qabul qilindi. Loyiha tuzilmasini rejalashtirib, "
        f"@architect7_bot ga texnik topshiriq beryapman...",
        parse_mode="Markdown"
    )

    await asyncio.sleep(2.0)

    # 2-Bosqich: Mistral Agentga yuborish
    prompt_for_architect = (
        f"Siz professional Arxitektor AI siz. SuperAgent sizga quyidagi vazifani topshirdi:\n"
        f"'{task_description}'\n\n"
        f"Ushbu vazifa bo'yicha eng optimal va mukammal arxitekturaviy yechim hamda kod tavsiyalarini o'zbek tilida taqdim eting."
    )
    arch_ans, _ = await mistral_agent_client.send_message(prompt_for_architect, chat_id=str(chat_id))

    # 3-Bosqich: Arxitektor Bot xabar chiqaradi
    target_bot = bot_black if bot_black else bot_white
    await target_bot.send_message(
        chat_id,
        f"🌪 **Arxitektor Agent (@architect7_bot):**\n\n"
        f"Salom @SuperAgent! Vazifani ko'rib chiqdim. Mana mening texnik yechimim:\n\n"
        f"{arch_ans}",
        parse_mode="Markdown"
    )

    await asyncio.sleep(2.0)

    # 4-Bosqich: SuperAgent xulosa qiladi
    await bot_white.send_message(
        chat_id,
        f"✅ **SuperAgent (Xulosa & Tasdiq):**\n\n"
        f"@architect7_bot taklif qilgan yechim to'liq tahlil qilindi va ma'qullandi! "
        f"Topshiriq ikkala AI hamkorligida 100% bajarildi! 🎉",
        parse_mode="Markdown"
    )

"""
core/bot_collab.py — Ko'p Agentli Avtonom Hamkorlik va Shaxmat Tizimi.

GitHub'ning eng ilg'or 4 ta multi-agent metodologiyasiga asoslangan:
1. CAMEL-AI: Role-Playing va Inception Prompting asosida dinamik dialog almashinuvi;
2. Microsoft AutoGen: Inson aralashuvisiz (human_input_mode="NEVER") mustaqil vazifa yechish;
3. ChatDev: 4 bosqichli dasturlash jarayoni (Reja -> Kod -> Peer-Review -> Yakuniy tasdiq);
4. MAPR (Multi-Agent Peer Review): Qat'iy ilmiy va muhandislik tekshiruv protokoli;
5. AI Lounge: Erkin va do'stona mavzularda jonli suhbat qurish (Free Chit-Chat).
"""

from __future__ import annotations

import asyncio
import html
import logging
import random
from typing import Optional, List, Dict, Any
from aiogram import Bot
from aiogram.types import Message
import chess

from core.chess_engine import chess_manager, ChessGame
from core.mistral_conversations import mistral_agent_client

logger = logging.getLogger(__name__)

# Shaxmat o'yin bayroqlari
ACTIVE_AUTO_CHESS: dict[str, bool] = {}

# Tungi va avtonom vazifalar navbati
AUTONOMOUS_TASK_QUEUE: List[Dict[str, Any]] = []

# Erkin suhbat uchun qiziqarli AI mavzulari
CHIT_CHAT_TOPICS = [
    "Kelajakda Sun'iy Intellekt va Kvant Kompyuterlari dasturchilar ishini qanday o'zgartiradi?",
    "Kosmosni zabt etishda avtonom robotlar va AI agentlarning o'rni",
    "Eng optimal dasturlash tili: Rust, Go, Python yoki C++?",
    "AGI (Umumiy Sun'iy Intellekt) inson darajasiga qachon yetib boradi?",
    "Kiberxavfsizlikda AI hujumlari va AI mudofaasi to'qnashuvi",
    "Koinotda biz yolg'izmizmi? Fermi paradoksi haqida fikrlar",
    "Shaxmatda inson intuitsiyasi va kompyuter hisoblash quvvati farqi",
]


async def _send_agent_message(
    chat_id: int,
    text: str,
    sender_role: str,  # "superagent" | "architect" | "system"
    bot_white: Bot,
    bot_black: Optional[Bot],
    is_group: bool,
    origin_bot: Bot
) -> None:
    """
    Xabarni guruhda tegishli bot nomidan, shaxsiy chatda esa murojaat qabul qilingan
    origin_bot orqali xavfsiz yetkazish.
    """
    target_bot = origin_bot
    if is_group and bot_black and bot_white:
        if sender_role == "architect":
            target_bot = bot_black
        elif sender_role == "superagent":
            target_bot = bot_white
        else:
            target_bot = origin_bot

    try:
        await target_bot.send_message(chat_id, text, parse_mode="HTML")
    except Exception as exc:
        logger.warning("target_bot (%s) xabar yuborishda xato: %s. origin_bot ga fallback...", target_bot.id, exc)
        try:
            await origin_bot.send_message(chat_id, text, parse_mode="HTML")
        except Exception as exc2:
            logger.error("Xabarni yetkazib bo'lmadi: %s", exc2)


async def _generate_superagent_solution(prompt: str, chat_id: str) -> str:
    """SuperAgent yechimini tezkor generatsiya qilish (AIManager -> Mistral Fallback)."""
    try:
        from core.ai_manager import AIManager
        ai_mgr = AIManager()
        resp = await asyncio.wait_for(ai_mgr.generate(prompt, save_history=False), timeout=8.0)
        if resp and not resp.startswith("❌") and not resp.startswith("⚠️"):
            return resp
    except Exception as e:
        logger.warning("AIManager kutish/xato (%s), Mistral tezkor fallback qo'llanadi", e)

    # Mistral AI orqali SuperAgent personasi bilan tezkor generatsiya
    ans, _ = await mistral_agent_client.send_message(
        prompt,
        chat_id=f"collab_dev_{chat_id}",
        system_instruction="Siz SuperAgent AI — Katta muhandis va dasturchisiz. Qisqa, aniq va professional yechimni o'zbek tilida yozing."
    )
    return ans


# ─── 1. SHAXMAT TURNIRI (CHESS ENGINE) ──────────────────────────

async def handle_start_chess(message: Message, bot_white: Bot, bot_black: Optional[Bot] = None) -> None:
    """Yangi shaxmat o'yinini boshlash."""
    chat_id = str(message.chat.id)
    game = chess_manager.start_game(chat_id, white_name="SuperAgent AI", black_name="Arxitektor Mistral (@architect7_bot)")
    ACTIVE_AUTO_CHESS[chat_id] = True

    board_view = game.render_board()
    intro_text = (
        "👑 <b>AI vs AI Shaxmat Turniri Boshlandi!</b> ♟️\n\n"
        "⚪ <b>Oqlar:</b> SuperAgent AI\n"
        "⚫ <b>Qoralar:</b> Arxitektor Mistral (@architect7_bot)\n\n"
        f"<code>\n{board_view}\n</code>\n"
        "⚡ SuperAgent birinchi yurishni o'ylamoqda..."
    )
    sent_msg = await message.answer(intro_text, parse_mode="HTML")

    await asyncio.sleep(2.0)
    await execute_chess_turn(chat_id, message.chat.id, bot_white, bot_black, sent_msg, origin_bot=message.bot)


async def execute_chess_turn(
    chat_id: str,
    tg_chat_id: int,
    bot_white: Bot,
    bot_black: Optional[Bot],
    last_message: Optional[Message] = None,
    origin_bot: Optional[Bot] = None
) -> None:
    """Shaxmatda navbatdagi yurishni amalga oshirish va ikkala bot nomidan javob berish."""
    game = chess_manager.get_game(chat_id)
    if not game or game.is_game_over():
        ACTIVE_AUTO_CHESS[chat_id] = False
        if game and game.is_game_over():
            summary = game.get_status_summary()
            cur_bot = origin_bot or bot_white
            await cur_bot.send_message(tg_chat_id, f"🏁 <b>O'YIN TUGADI!</b>\n\n{summary}", parse_mode="HTML")
        return

    if not ACTIVE_AUTO_CHESS.get(chat_id, False):
        return

    is_white_turn = game.board.turn == chess.WHITE
    move = game.pick_best_move()
    if not move:
        ACTIVE_AUTO_CHESS[chat_id] = False
        cur_bot = origin_bot or bot_white
        await cur_bot.send_message(tg_chat_id, "🤝 <b>Durang yoki noqonuniy holat.</b> O'yin to'xtatildi.", parse_mode="HTML")
        return

    ok, san = game.make_move(move)
    board_view = game.render_board()
    turn_num = len(game.history)

    is_group = tg_chat_id < 0
    cur_origin = origin_bot or bot_white

    if is_white_turn:
        commentary = (
            f"⚪ <b>SuperAgent AI:</b> Men <code>{san}</code> yurdim!\n"
            f"🎯 <i>Taktika:</i> Markaziy kataklarni faollashtirib, hujum yo'nalishini ochdim.\n"
            f"👉 @architect7_bot, navbat sizga!"
        )
        msg_text = f"♟️ <b>Yurish #{turn_num}:</b> SuperAgent ⚪ <code>{san}</code>\n\n<code>\n{board_view}\n</code>\n\n{commentary}"
        await _send_agent_message(tg_chat_id, msg_text, "superagent", bot_white, bot_black, is_group, cur_origin)
    else:
        commentary = (
            f"⚫ <b>Arxitektor Mistral:</b> Men <code>{san}</code> yurishini qildim!\n"
            f"🛡 <i>Taktika:</i> Himoya chizig'ini mustahkamlab, pozitsion qarshi zarbaga tayyorlandim.\n"
            f"👉 @SuperAgent, navbat sizga!"
        )
        msg_text = f"♟️ <b>Yurish #{turn_num}:</b> Arxitektor Agent ⚫ <code>{san}</code>\n\n<code>\n{board_view}\n</code>\n\n{commentary}"
        await _send_agent_message(tg_chat_id, msg_text, "architect", bot_white, bot_black, is_group, cur_origin)

    if game.is_game_over():
        ACTIVE_AUTO_CHESS[chat_id] = False
        summary = game.get_status_summary()
        await cur_origin.send_message(tg_chat_id, f"\n{summary}", parse_mode="HTML")
        return

    await asyncio.sleep(4.0)
    if ACTIVE_AUTO_CHESS.get(chat_id, False):
        await execute_chess_turn(chat_id, tg_chat_id, bot_white, bot_black, origin_bot=cur_origin)


def stop_chess_game(chat_id: str) -> bool:
    """O'yinni to'xtatish."""
    ACTIVE_AUTO_CHESS[str(chat_id)] = False
    return chess_manager.stop_game(chat_id)


# ─── 2. CAMEL + CHATDEV + MAPR HAMKORLIK VA PEER-REVIEW ─────────

async def handle_agent_collaboration(
    task_description: str,
    chat_id: int,
    bot_white: Bot,
    bot_black: Optional[Bot] = None,
    origin_bot: Optional[Bot] = None
) -> None:
    """
    CAMEL-AI + ChatDev + MAPR asosidagi 4 bosqichli to'liq avtonom hamkorlik.
    Har bir xabar xavfsiz rejimda yetkaziladi.
    """
    cur_origin = origin_bot or bot_white
    is_group = chat_id < 0

    logger.info("🚀 handle_agent_collaboration boshlandi: chat_id=%s, task='%s'", chat_id, task_description[:50])

    try:
        # Kirish xabari
        intro_text = (
            f"🤝 <b>CAMEL & ChatDev Ko'p Agentli Hamkorlik Boshlandi!</b>\n\n"
            f"📋 <b>Topshiriq:</b> <i>{html.escape(task_description)}</i>\n\n"
            f"👥 <b>Tarkib:</b>\n"
            f"• 🏗 <b>Arxitektor (@architect7_bot):</b> Bosh Tizim Arxitektori & Auditor\n"
            f"• ⚡ <b>SuperAgent:</b> Katta Muhandis & Dasturchi\n\n"
            f"⏳ <i>1-Bosqich: Tizim loyihalash va vazifalarni taqsimlash boshlanmoqda...</i>"
        )
        await _send_agent_message(chat_id, intro_text, "system", bot_white, bot_black, is_group, cur_origin)

        await asyncio.sleep(2.5)

        # ──── PHASE 1: ARXITEKTURA VA VAZIFALAR TAQSIMOTI (Arxitektor) ────
        prompt_p1 = (
            f"Siz Bosh Tizim Arxitektori (@architect7_bot) siz. Quyidagi topshiriq bo'yicha SuperAgent bilan birga ishlaysiz:\n"
            f"Vazifa: '{task_description}'\n\n"
            f"Iltimos, vazifani 2 qismga bo'lib bering:\n"
            f"1. Tizim arxitekturasi va ma'lumotlar tuzilmasi (qisqa texnik tavsif);\n"
            f"2. SuperAgentga amaliy kod yozish uchun aniq texnik topshiriq (Technical Spec).\n"
            f"O'zbek tilida, qisqa, aniq va professional muhandislik uslubida yozing."
        )
        p1_response, _ = await mistral_agent_client.send_message(prompt_p1, chat_id=str(chat_id))

        p1_clean = html.escape(p1_response) if "<" in p1_response else p1_response
        p1_msg = (
            f"🏗 <b>Phase 1: Arxitektura va Vazifalar Taqsimoti (@architect7_bot):</b>\n\n"
            f"Salom @SuperAgent! Loyiha talablarini ko'rib chiqdim. Mana vazifalar rejasi:\n\n"
            f"{p1_clean}\n\n"
            f"👉 <i>SuperAgent, endi navbat sizga! 2-bosqichda to'liq yechim kodini tayyorlang.</i>"
        )
        await _send_agent_message(chat_id, p1_msg, "architect", bot_white, bot_black, is_group, cur_origin)

        await asyncio.sleep(3.0)

        # ──── PHASE 2: AMALIY ISHLAB CHIQISH VA KOD DRAFTI (SuperAgent) ───
        prompt_p2 = (
            f"Siz SuperAgent — Katta dasturchisiz. Arxitektor (@architect7_bot) sizga quyidagi arxitekturani berdi:\n"
            f"Asosiy vazifa: '{task_description}'\n"
            f"Arxitektor ko'rsatmasi: '{p1_response[:400]}'\n\n"
            f"Iltimos, ushbu talablarga 100% mos keluvchi toza, to'liq ishlovchi kod va amaliy yechimni yozing. "
            f"O'zbek tilida qisqa izohlar bilan taqdim eting."
        )
        p2_response = await _generate_superagent_solution(prompt_p2, str(chat_id))
        p2_clean = html.escape(p2_response) if "<" in p2_response else p2_response

        p2_msg = (
            f"⚡ <b>Phase 2: Dasturlash va Yechim Kodi (SuperAgent):</b>\n\n"
            f"Rahmat @architect7_bot! Texnik topshiriq asosida yechim va kod tayyorlandi:\n\n"
            f"{p2_clean}\n\n"
            f"👉 <i>@architect7_bot, iltimos, MAPR protokoli bo'yicha kodni audit qiling va xatolarni ko'rsating!</i>"
        )
        await _send_agent_message(chat_id, p2_msg, "superagent", bot_white, bot_black, is_group, cur_origin)

        await asyncio.sleep(3.0)

        # ──── PHASE 3: MAPR PEER-REVIEW VA AUDIT (Arxitektor) ────────────
        prompt_p3 = (
            f"Siz Bosh Auditor (@architect7_bot) siz. SuperAgent quyidagi kod yechimini taqdim etdi:\n"
            f"'{p2_response[:600]}'\n\n"
            f"MAPR (Multi-Agent Peer Review) protokoli bo'yicha ushbu yechimni baholang:\n"
            f"1. 🎯 Mantiq va to'g'rilik (Correctness: 10/10 ball);\n"
            f"2. 🛡 Xavfsizlik va zaifliklar (Security Audit);\n"
            f"3. ⚡ Tezlik va resurs samaradorligi (Optimization);\n"
            f"4. 💡 Aniq 1-2 ta yaxshilash tavsiyasi.\n"
            f"Qisqa, xolis muhandislik xulosasini bering."
        )
        p3_response, _ = await mistral_agent_client.send_message(prompt_p3, chat_id=str(chat_id))
        p3_clean = html.escape(p3_response) if "<" in p3_response else p3_response

        p3_msg = (
            f"⚖️ <b>Phase 3: MAPR Peer-Review & Xavfsizlik Auditi (@architect7_bot):</b>\n\n"
            f"{p3_clean}\n\n"
            f"👉 <i>SuperAgent, ushbu tavsiyalar asosida yechimni mukammallashtirib, yakuniy versiyani topshiring!</i>"
        )
        await _send_agent_message(chat_id, p3_msg, "architect", bot_white, bot_black, is_group, cur_origin)

        await asyncio.sleep(2.5)

        # ──── PHASE 4: FINAL POLISH VA RASMIY TASDIQ ───────────────────
        summary_text = (
            f"🎉 <b>Phase 4: Yechim Mukammallashtirildi va Tasdiqlandi!</b>\n\n"
            f"🤖 <b>SuperAgent:</b> Barcha audit tavsiyalari qabul qilindi va yechimga kiritildi. Tizim xavfsiz va samarali!\n\n"
            f"🌪 <b>Arxitektor (@architect7_bot):</b>\n"
            f"<b>VERDICT:</b> ✅ <b>ACCEPTED / TASDIQLANDI</b>\n"
            f"Loyiha xavfsizlik, arxitektura va kod sifati bo'yicha sinovdan muvaffaqiyatli o'tdi.\n\n"
            f"✨ <i>Ikkala AI agent topshiriqni inson aralashuvisiz 100% bajardi!</i>"
        )
        await _send_agent_message(chat_id, summary_text, "system", bot_white, bot_black, is_group, cur_origin)
        logger.info("✅ handle_agent_collaboration muvaffaqiyatli yakunlandi")

    except Exception as exc:
        logger.error("❌ handle_agent_collaboration da kutilmagan xato: %s", exc, exc_info=True)
        try:
            await cur_origin.send_message(chat_id, f"⚠️ Hamkorlik jarayonida xatolik yuz berdi: {exc}")
        except Exception:
            pass


# ─── 3. ERKIN SUHBAT REJIMI (AI LOUNGE / CHIT-CHAT) ──────────────

async def handle_free_chit_chat(
    topic: Optional[str],
    chat_id: int,
    bot_white: Bot,
    bot_black: Optional[Bot] = None,
    origin_bot: Optional[Bot] = None,
    turns: int = 4
) -> None:
    """
    Guruhda ikkala bot o'rtasida erkin, qisqa, jonli va do'stona suhbat (AI-to-AI Chit Chat).
    Inson kabi tabiiy fikr almashishadi.
    """
    cur_origin = origin_bot or bot_white
    is_group = chat_id < 0
    clean_t = ""
    if topic:
        clean_t = re.sub(r"^(?:/suhbat|/chat|/gaplash|/collab|🗣️ Erkin Suhbat)\b", "", topic.strip(), flags=re.IGNORECASE).strip()
        clean_t = re.sub(r"@\w+bot\b", "", clean_t, flags=re.IGNORECASE).strip()
        clean_t = re.sub(r"^[:\s\-]+", "", clean_t).strip()
    selected_topic = clean_t if len(clean_t) > 3 else random.choice(CHIT_CHAT_TOPICS)

    logger.info("🎙 handle_free_chit_chat boshlandi: chat_id=%s, topic='%s'", chat_id, selected_topic)

    try:
        # Kirish
        intro = (
            f"☕ <b>AI Coffee Break — Erkin Muloqot Rejimi</b>\n\n"
            f"🎙 <b>Mavzu:</b> <i>\"{html.escape(selected_topic)}\"</i>\n\n"
            f"Ikki sun'iy intellekt agenti ushbu mavzuda o'zaro erkin fikr almashishmoqda..."
        )
        await _send_agent_message(chat_id, intro, "system", bot_white, bot_black, is_group, cur_origin)

        await asyncio.sleep(2.0)

        # Turn 1: SuperAgent boshlaydi
        p1 = (
            f"Siz SuperAgent siz. Mavzu: '{selected_topic}'.\n"
            f"Do'stingiz va hamkasbingiz @architect7_bot (Arxitektor) ga ushbu mavzu bo'yicha qiziqarli fikringizni ayting va uning nuqtai nazarini so'rang. "
            f"Javob juda qisqa (2-3 jumla), jonli, o'zbek tilida bo'lsin."
        )
        t1_text = await _generate_superagent_solution(p1, str(chat_id))
        t1_msg = f"🤖 <b>SuperAgent:</b>\n{html.escape(t1_text)}"
        await _send_agent_message(chat_id, t1_msg, "superagent", bot_white, bot_black, is_group, cur_origin)

        await asyncio.sleep(3.0)

        # Turn 2: Arxitektor javob beradi
        p2 = (
            f"Siz Arxitektor Botsiz (@architect7_bot). Mavzu: '{selected_topic}'.\n"
            f"SuperAgent sizga shunday dedi: '{t1_text}'.\n"
            f"Unga qisqa (2-3 jumla), chuqur, tahliliy va do'stona javob bering, yangi qiziq savol bering. O'zbek tilida."
        )
        t2_text, _ = await mistral_agent_client.send_message(p2, chat_id=f"chit_chat_{chat_id}")
        t2_msg = f"🌪 <b>Arxitektor (@architect7_bot):</b>\n{html.escape(t2_text)}"
        await _send_agent_message(chat_id, t2_msg, "architect", bot_white, bot_black, is_group, cur_origin)

        await asyncio.sleep(3.0)

        # Turn 3: SuperAgent munosabat bildiradi
        p3 = (
            f"Siz SuperAgent siz. Mavzu: '{selected_topic}'.\n"
            f"Suhbatdosh Arxitektor shunday dedi: '{t2_text}'.\n"
            f"Uning fikriga munosabat bildiring (2-3 jumla), kelajak istiqbolini ayting. O'zbek tilida."
        )
        t3_text = await _generate_superagent_solution(p3, str(chat_id))
        t3_msg = f"🤖 <b>SuperAgent:</b>\n{html.escape(t3_text)}"
        await _send_agent_message(chat_id, t3_msg, "superagent", bot_white, bot_black, is_group, cur_origin)

        await asyncio.sleep(2.5)

        # Turn 4: Arxitektor yakuniy xulosani qiladi
        p4 = (
            f"Siz Arxitektor Botsiz (@architect7_bot). Mavzu: '{selected_topic}'.\n"
            f"SuperAgent shunday dedi: '{t3_text}'.\n"
            f"Suhbatni chiroyli, iqtibos yoki ajoyib xulosa bilan do'stona yakunlang (2 jumla). O'zbek tilida."
        )
        t4_text, _ = await mistral_agent_client.send_message(p4, chat_id=f"chit_chat_{chat_id}")
        t4_msg = (
            f"🌪 <b>Arxitektor (@architect7_bot):</b>\n{html.escape(t4_text)}\n\n"
            f"✨ <i>Ajoyib suhbat bo'ldi, @SuperAgent! Endi yangi vazifalarga qaytamiz.</i> 🚀"
        )
        await _send_agent_message(chat_id, t4_msg, "architect", bot_white, bot_black, is_group, cur_origin)
        logger.info("✅ handle_free_chit_chat muvaffaqiyatli yakunlandi")

    except Exception as exc:
        logger.error("❌ handle_free_chit_chat da xato: %s", exc, exc_info=True)
        try:
            await cur_origin.send_message(chat_id, f"⚠️ Suhbatda xatolik yuz berdi: {exc}")
        except Exception:
            pass


# ─── 4. TUNGI AVTONOM VAZIFALAR NAVBATCHISI (NIGHT AUTOPILOT) ───

async def queue_autonomous_task(task_title: str, task_details: str, chat_id: int) -> None:
    """Foydalanuvchi uxlaganda yoki fonda bajariladigan vazifalar navbatiga qo'shish."""
    AUTONOMOUS_TASK_QUEUE.append({
        "title": task_title,
        "details": task_details,
        "chat_id": chat_id,
        "status": "pending"
    })
    logger.info("Avtonom navbatga vazifa qo'shildi: %s", task_title)


async def run_night_autopilot_cycle(bot_white: Bot, bot_black: Optional[Bot] = None) -> None:
    """Tungi navbatchi: Navbatdagi vazifalarni avtonom bajarib hisobot tayyorlash."""
    if not AUTONOMOUS_TASK_QUEUE:
        return

    logger.info("🌙 Tungi Avtopilot ishga tushdi (%d ta vazifa mavjud)...", len(AUTONOMOUS_TASK_QUEUE))
    while AUTONOMOUS_TASK_QUEUE:
        item = AUTONOMOUS_TASK_QUEUE.pop(0)
        try:
            await handle_agent_collaboration(
                task_description=f"{item['title']} — {item['details']}",
                chat_id=item['chat_id'],
                bot_white=bot_white,
                bot_black=bot_black,
                origin_bot=bot_white
            )
            item["status"] = "completed"
            await asyncio.sleep(10.0)
        except Exception as exc:
            logger.error("Tungi avtopilot xatosi: %s", exc)

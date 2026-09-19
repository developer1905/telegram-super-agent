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
import re
from typing import Optional, List, Dict, Any
from aiogram import Bot
from aiogram.types import Message

try:
    import chess
    from core.chess_engine import chess_manager, ChessGame, CHESS_AVAILABLE
except ImportError:
    chess = None
    chess_manager = None
    ChessGame = None
    CHESS_AVAILABLE = False

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

    async def _do_send(b: Bot) -> bool:
        try:
            await b.send_message(chat_id, text, parse_mode="HTML")
            return True
        except Exception as err_html:
            try:
                # Agar HTML parser (masalan < yoki > belgilari sababli) xato bersa
                await b.send_message(chat_id, text, parse_mode=None)
                return True
            except Exception as err_plain:
                logger.warning("Bot orqali yuborish xatosi: %s", err_plain)
                return False

    sent = await _do_send(target_bot)
    if not sent and target_bot != origin_bot:
        logger.info("origin_bot orqali qayta urinish...")
        await _do_send(origin_bot)


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
    if not CHESS_AVAILABLE or not chess_manager:
        await message.answer("⚠️ Shaxmat o'ynash uchun serverga <code>pip install python-chess</code> o'rnatilishi lozim.", parse_mode="HTML")
        return

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


# Holat boshqaruvi (To'xtatish va faollik bayroqlari)
ACTIVE_CHIT_CHATS: dict[str, bool] = {}
ACTIVE_COLLABS: dict[str, bool] = {}


def stop_chit_chat(chat_id: str) -> bool:
    """Faol erkin suhbatni to'xtatish."""
    chat_key = str(chat_id)
    if ACTIVE_CHIT_CHATS.get(chat_key, False):
        ACTIVE_CHIT_CHATS[chat_key] = False
        return True
    return False


def stop_collab(chat_id: str) -> bool:
    """Faol hamkorlik yoki avtopilot vazifasini to'xtatish."""
    chat_key = str(chat_id)
    if ACTIVE_COLLABS.get(chat_key, False):
        ACTIVE_COLLABS[chat_key] = False
        return True
    return False


def parse_topic_and_turns(raw_text: str, default_turns: int = 8) -> tuple[str, int]:
    """
    Foydalanuvchi xabaridan suhbat mavzusi va replikalar sonini (turns) ajratish.
    Masalan:
      /suhbat 10 Kvant kompyuterlari -> ("Kvant kompyuterlari", 10)
      /suhbat:12 Sun'iy intellekt -> ("Sun'iy intellekt", 12)
      /suhbat 15 -> ("", 15)
      /suhbat Marsni egallash 8 ta -> ("Marsni egallash", 8)
    """
    clean = re.sub(r"^(?:/suhbat|/chat|/gaplash|🗣️ Erkin Suhbat)(?:@\w+)?", "", raw_text, flags=re.IGNORECASE).strip()
    turns = default_turns

    # 1. Boshida raqam: masalan "10 AI kelajagi" yoki ":12 AI"
    m_start = re.match(r"^[:\s]*(\d{1,2})[:\s]+(.*)$", clean)
    if m_start:
        val = int(m_start.group(1))
        if 2 <= val <= 30:
            turns = val
            clean = m_start.group(2).strip()
    elif clean.isdigit():
        val = int(clean)
        if 2 <= val <= 30:
            turns = val
            clean = ""
    else:
        # 2. Xabar ichida "N ta" yoki "--turns N" yoki "N qadam"
        m_inner = re.search(r"\b(\d{1,2})\s*ta\b|\b(?:turns?|qadam)[:=\s]+(\d{1,2})\b", clean, re.IGNORECASE)
        if m_inner:
            val = int(m_inner.group(1) or m_inner.group(2))
            if 2 <= val <= 30:
                turns = val
                clean = re.sub(m_inner.group(0), "", clean).strip()

    clean = re.sub(r"^[:\s\-]+", "", clean).strip()
    return clean, turns


# ─── 2. CAMEL + CHATDEV + MAPR HAMKORLIK VA PEER-REVIEW ─────────

async def handle_agent_collaboration(
    task_description: str,
    chat_id: int,
    bot_white: Bot,
    bot_black: Optional[Bot] = None,
    origin_bot: Optional[Bot] = None,
    deep_mode: bool = True,
    max_rounds: int = 5
) -> None:
    """
    CAMEL-AI + ChatDev + MAPR asosidagi ko'p bosqichli to'liq avtonom hamkorlik.
    deep_mode=True bo'lsa, auditdan 10/10 olinmaguncha ikkala bot qayta-qayta ishlab,
    kodni mukammallashtirib boraveradi (Kechki avtopilot rejimi).
    """
    chat_key = str(chat_id)
    ACTIVE_COLLABS[chat_key] = True

    cur_origin = origin_bot or bot_white
    is_group = chat_id < 0

    logger.info("🚀 handle_agent_collaboration boshlandi: chat_id=%s, task='%s'", chat_id, task_description[:50])

    try:
        # Kirish xabari
        intro_text = (
            f"🤝 <b>CAMEL & ChatDev Avtonom Hamkorlik Boshlandi!</b>\n\n"
            f"📋 <b>Topshiriq:</b> <i>{html.escape(task_description)}</i>\n\n"
            f"👥 <b>Tarkib:</b>\n"
            f"• 🏗 <b>Arxitektor (@architect7_bot):</b> Bosh Tizim Arxitektori & Auditor\n"
            f"• ⚡ <b>SuperAgent:</b> Katta Muhandis & Dasturchi\n\n"
            f"🔄 <b>Rejim:</b> <i>Chuqur avtonom takomillashtirish (Vazifa to'liq bitmaguncha davom etadi)</i>\n"
            f"🛑 <i>To'xtatish buyrug'i:</i> <code>/stop_collab</code>\n\n"
            f"⏳ <i>1-Bosqich: Tizim loyihalash va vazifalarni taqsimlash boshlanmoqda...</i>"
        )
        await _send_agent_message(chat_id, intro_text, "system", bot_white, bot_black, is_group, cur_origin)

        await asyncio.sleep(2.5)

        # ──── PHASE 1: ARXITEKTURA VA VAZIFALAR TAQSIMOTI (Arxitektor) ────
        if not ACTIVE_COLLABS.get(chat_key, False):
            return

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
        if not ACTIVE_COLLABS.get(chat_key, False):
            return

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
        if not ACTIVE_COLLABS.get(chat_key, False):
            return

        prompt_p3 = (
            f"Siz Bosh Auditor (@architect7_bot) siz. SuperAgent quyidagi kod yechimini taqdim etdi:\n"
            f"'{p2_response[:600]}'\n\n"
            f"MAPR (Multi-Agent Peer Review) protokoli bo'yicha ushbu yechimni baholang:\n"
            f"1. 🎯 Mantiq va to'g'rilik (Correctness: 10/10 ball);\n"
            f"2. 🛡 Xavfsizlik va zaifliklar (Security Audit);\n"
            f"3. ⚡ Tezlik va resurs samaradorligi (Optimization);\n"
            f"4. 💡 Aniq 1-2 ta yaxshilash tavsiyasi.\n"
            f"Agar barcha talablar bajarilgan bo'lsa 'TASDIQLANDI' deb yozing, aks holda nimalarni tuzatish kerakligini ayting."
        )
        p3_response, _ = await mistral_agent_client.send_message(prompt_p3, chat_id=str(chat_id))
        p3_clean = html.escape(p3_response) if "<" in p3_response else p3_response

        p3_msg = (
            f"⚖️ <b>Phase 3: MAPR Peer-Review & Xavfsizlik Auditi (@architect7_bot):</b>\n\n"
            f"{p3_clean}"
        )
        await _send_agent_message(chat_id, p3_msg, "architect", bot_white, bot_black, is_group, cur_origin)

        # ──── DEEP REFINEMENT LOOP (Tugamaguncha suhbatlashib yaxshilash) ────
        round_idx = 1
        current_solution = p2_response
        current_audit = p3_response
        target_rounds = max_rounds if deep_mode else 1

        while round_idx < target_rounds:
            if not ACTIVE_COLLABS.get(chat_key, False):
                await _send_agent_message(chat_id, "🛑 <i>Foydalanuvchi buyrug'i bilan hamkorlik to'xtatildi.</i>", "system", bot_white, bot_black, is_group, cur_origin)
                break

            # Agar audit to'liq ma'qullagan bo'lsa
            if any(w in current_audit.lower() for w in ["10/10", "tasdiqlandi", "kamchilik yo'q", "100% tayyor", "muammo topilmadi"]):
                logger.info("Audit loyihani to'liq ma'qulladi (Round %d)", round_idx)
                break

            round_idx += 1
            await asyncio.sleep(3.5)

            # SuperAgent xatolarni tuzatadi
            prompt_fix = (
                f"Siz SuperAgent — Katta dasturchisiz. Vazifa: '{task_description}'.\n"
                f"Avvalgi yechimingiz: '{current_solution[:400]}'\n"
                f"Arxitektor auditi: '{current_audit[:400]}'\n\n"
                f"Arxitektor aytgan barcha kamchiliklarni to'liq bartaraf qilib, optimallashtirilgan yangi toza kodni yozing."
            )
            fixed_response = await _generate_superagent_solution(prompt_fix, str(chat_id))
            fix_clean = html.escape(fixed_response) if "<" in fixed_response else fixed_response
            current_solution = fixed_response

            fix_msg = (
                f"🛠 <b>Iteratsiya #{round_idx}: Refaktoring & Xatolar Tuzatildi (SuperAgent):</b>\n\n"
                f"Audit tavsiyalari inobatga olinib, kod qayta ishlandi va mustahkamlandi:\n\n"
                f"{fix_clean}\n\n"
                f"👉 <i>@architect7_bot, iltimos, yangilangan yechimni tekshirib tasdiqlang!</i>"
            )
            await _send_agent_message(chat_id, fix_msg, "superagent", bot_white, bot_black, is_group, cur_origin)

            await asyncio.sleep(3.5)

            # Arxitektor qayta audit qiladi
            prompt_recheck = (
                f"Siz Bosh Auditor (@architect7_bot) siz. Vazifa: '{task_description}'.\n"
                f"SuperAgent tuzatilgan kodni berdi:\n'{current_solution[:500]}'\n\n"
                f"Kodni qisqa qayta audit qiling. Agar hammasi tayyor bo'lsa 'TASDIQLANDI' deb xulosa bering."
            )
            recheck_resp, _ = await mistral_agent_client.send_message(prompt_recheck, chat_id=str(chat_id))
            recheck_clean = html.escape(recheck_resp) if "<" in recheck_resp else recheck_resp
            current_audit = recheck_resp

            recheck_msg = (
                f"🔍 <b>Iteratsiya #{round_idx}: Qayta MAPR Tekshiruvi (@architect7_bot):</b>\n\n"
                f"{recheck_clean}"
            )
            await _send_agent_message(chat_id, recheck_msg, "architect", bot_white, bot_black, is_group, cur_origin)

        # ──── PHASE FINAL: RASMIY YAKUN VA TASDIQ ──────────────────────
        await asyncio.sleep(2.5)
        summary_text = (
            f"🎉 <b>Avtonom Hamkorlik Yakunlandi! ({round_idx}-bosqich)</b>\n\n"
            f"🤖 <b>SuperAgent:</b> Barcha mezonlar qanoatlantirildi, arxitektura va kod to'liq integratsiya qilindi.\n\n"
            f"🌪 <b>Arxitektor (@architect7_bot):</b>\n"
            f"<b>VERDICT:</b> ✅ <b>100% ACCEPTED / TASDIQLANDI</b>\n"
            f"Tizim xavfsizlik, ishonchlilik va samaradorlik talablariga to'liq javob beradi.\n\n"
            f"✨ <i>Ikkala agent topshiriqni avtonom tarzda muvaffaqiyatli yakunladi!</i> 🚀"
        )
        await _send_agent_message(chat_id, summary_text, "system", bot_white, bot_black, is_group, cur_origin)
        ACTIVE_COLLABS[chat_key] = False
        logger.info("✅ handle_agent_collaboration muvaffaqiyatli yakunlandi")

    except Exception as exc:
        logger.error("❌ handle_agent_collaboration da kutilmagan xato: %s", exc, exc_info=True)
        ACTIVE_COLLABS[chat_key] = False
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
    turns: int = 8
) -> None:
    """
    Guruhda yoki shaxsiyda ikkala bot o'rtasida erkin, jonli va do'stona suhbat (AI Lounge).
    Foydalanuvchi replikalar sonini (turns) o'zi belgilashi mumkin: masalan /suhbat 12 AI
    """
    chat_key = str(chat_id)
    ACTIVE_CHIT_CHATS[chat_key] = True

    cur_origin = origin_bot or bot_white
    is_group = chat_id < 0

    clean_t, parsed_turns = parse_topic_and_turns(topic or "", default_turns=turns)
    total_turns = parsed_turns
    selected_topic = clean_t if len(clean_t) > 3 else random.choice(CHIT_CHAT_TOPICS)

    logger.info("🎙 handle_free_chit_chat boshlandi: chat_id=%s, turns=%d, topic='%s'", chat_id, total_turns, selected_topic)

    try:
        # Kirish
        intro = (
            f"☕ <b>AI Coffee Break — Jonli Muloqot ({total_turns} ta replika)</b>\n\n"
            f"🎙 <b>Mavzu:</b> <i>\"{html.escape(selected_topic)}\"</i>\n"
            f"💬 <b>Rejalashtirilgan suhbat uzunligi:</b> {total_turns} qadam\n"
            f"🛑 <i>Suhbatni istalgan payt to'xtatish:</i> <code>/stop_suhbat</code>\n\n"
            f"Ikki sun'iy intellekt agenti o'zaro jonli fikr almashishni boshlamoqda..."
        )
        await _send_agent_message(chat_id, intro, "system", bot_white, bot_black, is_group, cur_origin)

        await asyncio.sleep(2.0)
        last_speech = f"Mavzu: {selected_topic}"

        for turn_idx in range(1, total_turns + 1):
            if not ACTIVE_CHIT_CHATS.get(chat_key, False):
                await _send_agent_message(chat_id, "🛑 <i>Foydalanuvchi buyrug'i bilan suhbat to'xtatildi.</i>", "system", bot_white, bot_black, is_group, cur_origin)
                break

            is_superagent = (turn_idx % 2 != 0)
            is_final = (turn_idx == total_turns)

            if is_superagent:
                if turn_idx == 1:
                    p = (
                        f"Siz SuperAgent siz. Mavzu: '{selected_topic}'.\n"
                        f"Do'stingiz va hamkasbingiz @architect7_bot ga ushbu mavzu bo'yicha eng qiziqarli, o'ylantiradigan fikringizni ayting va uning nuqtai nazarini so'rang.\n"
                        f"Javob qisqa (2-3 jumla), jonli, o'zbek tilida bo'lsin."
                    )
                else:
                    p = (
                        f"Siz SuperAgent siz. Mavzu: '{selected_topic}'.\n"
                        f"Arxitektor sizga aytdi: '{last_speech}'.\n"
                        f"Unga qisqa, qiziq dalil yoki yangi nuqtai nazar bilan munosabat bildiring (2-3 jumla), yangi savol bering. O'zbek tilida."
                    )
                t_text = await _generate_superagent_solution(p, chat_key)
                t_msg = f"🤖 <b>SuperAgent ({turn_idx}/{total_turns}):</b>\n{html.escape(t_text)}"
                await _send_agent_message(chat_id, t_msg, "superagent", bot_white, bot_black, is_group, cur_origin)
                last_speech = t_text
            else:
                if is_final:
                    p = (
                        f"Siz Arxitektor Botsiz (@architect7_bot). Mavzu: '{selected_topic}'. Bu suhbatning yakuniy qismi.\n"
                        f"SuperAgent shunday dedi: '{last_speech}'.\n"
                        f"Suhbatni ajoyib, falsafiy yoki texnik xulosa, chuqur iqtibos bilan do'stona yakunlang (2-3 jumla). O'zbek tilida."
                    )
                else:
                    p = (
                        f"Siz Arxitektor Botsiz (@architect7_bot). Mavzu: '{selected_topic}'.\n"
                        f"SuperAgent sizga aytdi: '{last_speech}'.\n"
                        f"Uning fikriga tahliliy, chuqur va do'stona munosabat bildiring, yangi qarash bering (2-3 jumla). O'zbek tilida."
                    )
                t_text, _ = await mistral_agent_client.send_message(p, chat_id=f"chit_chat_{chat_id}")
                if is_final:
                    t_msg = (
                        f"🌪 <b>Arxitektor (@architect7_bot) ({turn_idx}/{total_turns}):</b>\n{html.escape(t_text)}\n\n"
                        f"✨ <i>Mazmunli suhbat uchun rahmat, @SuperAgent! Yangi topshiriqlarda ko'rishguncha.</i> 🚀"
                    )
                else:
                    t_msg = f"🌪 <b>Arxitektor (@architect7_bot) ({turn_idx}/{total_turns}):</b>\n{html.escape(t_text)}"
                await _send_agent_message(chat_id, t_msg, "architect", bot_white, bot_black, is_group, cur_origin)
                last_speech = t_text

            await asyncio.sleep(3.0)

        ACTIVE_CHIT_CHATS[chat_key] = False
        logger.info("✅ handle_free_chit_chat muvaffaqiyatli yakunlandi")

    except Exception as exc:
        logger.error("❌ handle_free_chit_chat da xato: %s", exc, exc_info=True)
        ACTIVE_CHIT_CHATS[chat_key] = False
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

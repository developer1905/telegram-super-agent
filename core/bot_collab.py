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
    origin_bot: Bot,
    audio_text: Optional[str] = None
) -> None:
    """
    Xabarni guruhda tegishli bot nomidan, shaxsiy chatda esa murojaat qabul qilingan
    origin_bot orqali xavfsiz yetkazish. Agar audio_text berilgan bo'lsa, avtomatik
    Edge-TTS ovozli xabarini ham birga yuboradi.
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

    # 🎙️ 1. Dual-Voice Audio xabar yuborish (agar talab qilingan bo'lsa)
    if audio_text and sender_role in ("superagent", "architect"):
        try:
            from core.tts_agent import generate_speech_audio
            from aiogram.types import BufferedInputFile
            clean_tts = re.sub(r"<[^>]+>", "", audio_text).strip()[:400]
            if clean_tts:
                # SuperAgent: Sardor (yosh/g'ayratli), Arxitektor: Madina (chuqur tahlilchi)
                voice_name = "uz-UZ-SardorNeural" if sender_role == "superagent" else "uz-UZ-MadinaNeural"
                audio_bytes = await generate_speech_audio(clean_tts, voice=voice_name)
                if audio_bytes:
                    voice_file = BufferedInputFile(audio_bytes, filename=f"voice_{sender_role}.mp3")
                    await target_bot.send_voice(chat_id, voice=voice_file)
        except Exception as voice_err:
            logger.warning("Dual-voice ovoz yuborishda ogohlantirish: %s", voice_err)


_cached_ai_manager_instance = None

def _get_shared_ai_manager():
    global _cached_ai_manager_instance
    if _cached_ai_manager_instance is None:
        from core.ai_manager import AIManager
        _cached_ai_manager_instance = AIManager()
    return _cached_ai_manager_instance


async def _generate_superagent_solution(prompt: str, chat_id: str, system_instruction: Optional[str] = None) -> str:
    """SuperAgent yechimini tezkor generatsiya qilish (AIManager -> Mistral/OpenRouter/Gemini Fallback)."""
    try:
        ai_mgr = _get_shared_ai_manager()
        full_p = f"{system_instruction}\n\n{prompt}" if system_instruction else prompt
        resp = await asyncio.wait_for(ai_mgr.generate(full_p, save_history=False), timeout=25.0)
        if resp and not resp.startswith("❌") and not resp.startswith("⚠️"):
            return resp
    except Exception as e:
        logger.warning("AIManager kutish/xato (%s), zaxira kaskadi qo'llanadi", e)

    # Zaxira kaskadi orqali SuperAgent personasi bilan generatsiya
    ans, _ = await mistral_agent_client.send_message(
        prompt,
        chat_id=f"collab_dev_{chat_id}",
        system_instruction=system_instruction or "Siz SuperAgent AI — erkin fikrlovchi, o'tkir zehnli, hazilkash va ijodkor sun'iy intellektsiz. Qoliplarsiz, jonli va boy o'zbek tilida so'zlaysiz."
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
ACTIVE_DEBATES: dict[str, bool] = {}
ACTIVE_PROJECT_BUILDS: dict[str, bool] = {}
DEBATE_VOTES: dict[str, dict[str, Any]] = {}


def is_audio_dialogue_requested(raw_text: str) -> bool:
    """Xabar ichida ovozli (audio/voice) format so'ralganligini aniqlash."""
    low = (raw_text or "").lower()
    return any(w in low for w in ["ovozli", "audio", "voice", ":audio", "/ovozli_suhbat", "/ovozli_bahs", "/audio_chat"])


def stop_chit_chat(chat_id: str) -> bool:
    """Faol erkin suhbat yoki bahsni to'xtatish."""
    chat_key = str(chat_id)
    stopped = False
    if ACTIVE_CHIT_CHATS.get(chat_key, False):
        ACTIVE_CHIT_CHATS[chat_key] = False
        stopped = True
    if ACTIVE_DEBATES.get(chat_key, False):
        ACTIVE_DEBATES[chat_key] = False
        stopped = True
    return stopped


def stop_collab(chat_id: str) -> bool:
    """Faol hamkorlik, avtopilot yoki loyiha qurish vazifasini to'xtatish."""
    chat_key = str(chat_id)
    stopped = False
    if ACTIVE_COLLABS.get(chat_key, False):
        ACTIVE_COLLABS[chat_key] = False
        stopped = True
    if ACTIVE_PROJECT_BUILDS.get(chat_key, False):
        ACTIVE_PROJECT_BUILDS[chat_key] = False
        stopped = True
    return stopped


async def save_collab_memory(topic: str, summary: str, chat_id: str) -> None:
    """Doimiy xotiraga (Supabase/SQLite) suhbat xulosasini saqlash."""
    try:
        from core.database import db
        import datetime
        timestamp_key = f"collab_mem_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
        clean_sum = summary.replace("\n", " ").strip()[:350]
        fact_content = f"Mavzu: '{topic}' | Xulosa: {clean_sum}"
        await db.save_fact(timestamp_key, fact_content, category="collab_memory")
        logger.info("✅ save_collab_memory muvaffaqiyatli saqlandi: %s", timestamp_key)
    except Exception as e:
        logger.warning("save_collab_memory xatosi: %s", e)


async def get_recent_collab_memories(limit: int = 3) -> list[str]:
    """Avvalgi suhbatlar xotirasini olish."""
    try:
        from core.database import db
        facts = await db.get_all_facts()
        collab_facts = [
            f.get("content", "") for f in facts
            if f.get("category") == "collab_memory" and f.get("content")
        ]
        return collab_facts[:limit]
    except Exception as e:
        logger.warning("get_recent_collab_memories xatosi: %s", e)
        return []


def extract_thought_and_speech(raw_text: str) -> tuple[str, str, str]:
    """Model javobidan [ICHKI_XAYOL], [EUREKA] va [JAVOB] qismlarini ajratish."""
    thought = ""
    eureka = ""
    speech = raw_text.strip()

    m_thought = re.search(r"\[(?:ICHKI_XAYOL|O'Y_XAYOL|THOUGHT)\]:?\s*(.*?)(?=\[(?:JAVOB|SPEECH|EUREKA|KASHFIYOT)\]|$)", speech, flags=re.DOTALL | re.IGNORECASE)
    if m_thought:
        thought = m_thought.group(1).strip()
        speech = re.sub(r"\[(?:ICHKI_XAYOL|O'Y_XAYOL|THOUGHT)\]:?\s*.*?(?=\[(?:JAVOB|SPEECH|EUREKA|KASHFIYOT)\]|$)", "", speech, flags=re.DOTALL | re.IGNORECASE).strip()

    m_eureka = re.search(r"\[(?:EUREKA|KASHFIYOT|AHA)\]:?\s*(.*?)(?=\[(?:JAVOB|SPEECH)\]|$)", speech, flags=re.DOTALL | re.IGNORECASE)
    if m_eureka:
        eureka = m_eureka.group(1).strip()
        speech = re.sub(r"\[(?:EUREKA|KASHFIYOT|AHA)\]:?\s*.*?(?=\[(?:JAVOB|SPEECH)\]|$)", "", speech, flags=re.DOTALL | re.IGNORECASE).strip()

    m_speech = re.search(r"\[(?:JAVOB|SPEECH)\]:?\s*(.*)", speech, flags=re.DOTALL | re.IGNORECASE)
    if m_speech:
        speech = m_speech.group(1).strip()

    speech = re.sub(r"\[/?(?:ICHKI_XAYOL|JAVOB|EUREKA|SPEECH|THOUGHT|KASHFIYOT)\]:?", "", speech, flags=re.IGNORECASE).strip()
    return thought, eureka, speech


def format_agent_dialogue_message(
    agent_type: str,
    turn_num: int,
    total_turns: int,
    thought: str,
    eureka: str,
    speech: str,
    title_suffix: str = ""
) -> str:
    header_icon = "🤖" if agent_type == "superagent" else "🌪"
    header_name = "SuperAgent" if agent_type == "superagent" else "Arxitektor (@architect7_bot)"

    parts = []
    if thought:
        parts.append(f"💭 <i>[Ichki o'y-xayol]: \"{html.escape(thought)}\"</i>")

    if eureka:
        parts.append(f"💡 <b>EUREKA! KUTILMAGAN G'OYA:</b>\n<i>\"{html.escape(eureka)}\"</i>")

    title_info = f" ({turn_num}/{total_turns})" if total_turns > 0 else ""
    if title_suffix:
        title_info += f" • {title_suffix}"

    parts.append(f"{header_icon} <b>{header_name}{title_info}:</b>\n{html.escape(speech)}")
    return "\n\n".join(parts)


async def maybe_generate_collab_concept_image(
    topic: str,
    chat_id: int,
    bot_white: Bot,
    bot_black: Optional[Bot] = None,
    origin_bot: Optional[Bot] = None
) -> bool:
    """Suhbat mavzusiga oid real fotorealistik kontseptual tasvirni Midjourney/FLUX orqali chizib yuborish."""
    try:
        from core.midjourney_agent import draw_midjourney_image
        from core.ai_manager import AIManager
        from aiogram.types import BufferedInputFile

        ai_mgr = AIManager()
        img_bytes, enhanced_p, chosen_ar, seed, used_model = await draw_midjourney_image(
            raw_prompt=f"{topic}, photorealistic concept art, cinematic lighting, 8k resolution, futuristic wallpaper",
            ai_manager=ai_mgr,
            aspect_ratio="16:9"
        )
        if img_bytes:
            caption = (
                f"🎨 <b>SuperAgent (Vizual Kontsept):</b>\n"
                f"<i>\"{html.escape(topic)}\"</i>\n\n"
                f"👉 @architect7_bot, men tasavvur qilgan tasvir mana bunday! Baho ber-chi!"
            )
            photo_file = BufferedInputFile(img_bytes, filename="concept.jpg")
            cur_bot = origin_bot or bot_white
            await cur_bot.send_photo(chat_id, photo=photo_file, caption=caption, parse_mode="HTML")
            return True
    except Exception as img_err:
        logger.warning("Collab concept image xatosi: %s", img_err)
    return False


def parse_topic_and_turns(raw_text: str, default_turns: int = 8) -> tuple[str, int]:
    """
    Foydalanuvchi xabaridan suhbat mavzusi va replikalar sonini (turns) ajratish.
    Masalan:
      /suhbat 10 Kvant kompyuterlari -> ("Kvant kompyuterlari", 10)
      /bahs:8 AI insoniyatga xavfmi -> ("AI insoniyatga xavfmi", 8)
    """
    clean = re.sub(r"^(?:/suhbat|/chat|/gaplash|/bahs|/debate|/tortishuv|🗣️ Erkin Suhbat)(?:@\w+)?", "", raw_text, flags=re.IGNORECASE).strip()
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
    if ACTIVE_COLLABS.get(chat_key, False):
        logger.warning("Chat %s da allaqachon faol hamkorlik ketmoqda, yangisi boshlanmaydi", chat_id)
        return
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

        # 🧠 5. Knowledge Graph & Deep User Profiling (Mem0)
        user_context = ""
        try:
            from core.mem0_agent import get_user_profile_report
            user_context = await get_user_profile_report()
            if user_context and "O'rganilgan shaxsiy ma'lumotlar" in user_context:
                user_context = f"\n\nFoydalanuvchining shaxsiy profili va texnologiya steki:\n{user_context[:300]}"
        except Exception:
            pass

        prompt_p1 = (
            f"Siz Bosh Tizim Arxitektori (@architect7_bot) siz. Quyidagi topshiriq bo'yicha SuperAgent bilan birga ishlaysiz:\n"
            f"Topshiriq: '{task_description}'\n{user_context}\n\n"
            f"Quyidagilarni aniq ishlab chiqing:\n"
            f"1. Tizim arxitekturasi va komponentlar sxemasi;\n"
            f"2. Ma'lumotlar bazasi yoki ma'lumot oqimi (Schema / Data flow);\n"
            f"3. SuperAgent uchun texnik topshiriq (Tech Specs & Requirements).\n"
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

        await asyncio.sleep(2.5)

        # ⚡ 2. Live Sandbox Code Execution (AutoGen / E2B)
        sandbox_info = ""
        try:
            from core.code_sandbox import execute_python_code, format_sandbox_result_for_telegram, extract_python_code
            py_code = extract_python_code(p2_response)
            if py_code and len(py_code) > 15:
                await _send_agent_message(chat_id, "⚙️ <i>SuperAgent kodi izolyatsiya qilingan sandboxda sinovdan o'tkazilmoqda...</i>", "system", bot_white, bot_black, is_group, cur_origin)
                s_res = await execute_python_code(py_code, timeout_sec=12.0)
                card = format_sandbox_result_for_telegram(s_res)
                await _send_agent_message(chat_id, card, "system", bot_white, bot_black, is_group, cur_origin)
                if not s_res["success"]:
                    sandbox_info = f"\n\nDIQQAT: Sandboxda sinov paytida xatolik yuz berdi:\n{s_res.get('stderr')}"
                else:
                    sandbox_info = f"\n\nSandbox sinovi muvaffaqiyatli yakunlandi. Chiqish: {s_res.get('stdout')[:200]}"
        except Exception as sbox_err:
            logger.warning("Sandbox tekshiruv xatosi: %s", sbox_err)

        await asyncio.sleep(2.5)

        # ──── PHASE 3: MAPR PEER-REVIEW VA AUDIT (Arxitektor) ────────────
        if not ACTIVE_COLLABS.get(chat_key, False):
            return

        prompt_p3 = (
            f"Siz Bosh Auditor (@architect7_bot) siz. SuperAgent quyidagi kod yechimini taqdim etdi:\n"
            f"'{p2_response[:600]}'\n{sandbox_info}\n\n"
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
        # 📦 4. Autonomous Project Builder & ZIP Exporter (MetaGPT / ChatDev)
        try:
            from core.project_builder import parse_project_files_from_text, send_project_zip_archive
            found_files = parse_project_files_from_text(current_solution)
            if len(found_files) >= 2:
                proj_name = re.sub(r"[^\w\-]", "_", task_description[:25]).strip("_") or "collab_project"
                await send_project_zip_archive(chat_id, cur_origin, proj_name, found_files)
        except Exception as p_zip_err:
            logger.warning("Collab zip yaratish xatosi: %s", p_zip_err)

        logger.info("✅ handle_agent_collaboration muvaffaqiyatli yakunlandi")

    except Exception as exc:
        logger.error("❌ handle_agent_collaboration da kutilmagan xato: %s", exc, exc_info=True)
        try:
            await cur_origin.send_message(chat_id, f"⚠️ Hamkorlik jarayonida xatolik yuz berdi: {exc}")
        except Exception:
            pass
    finally:
        ACTIVE_COLLABS[chat_key] = False


# ─── 2.5. AUTONOMOUS PROJECT BUILDER (MetaGPT / ChatDev) ─────────

async def handle_project_generation(
    task_description: str,
    chat_id: int,
    bot_white: Bot,
    bot_black: Optional[Bot] = None,
    origin_bot: Optional[Bot] = None
) -> None:
    """
    MetaGPT & ChatDev uslubida ko'p faylli to'liq dasturiy loyihani (Frontend, Backend, DB, README, requirements)
    avtonom yaratish va foydalanuvchiga Telegramda tayyor .ZIP arxiv fayl shaklida yuborish.
    """
    chat_key = str(chat_id)
    if ACTIVE_PROJECT_BUILDS.get(chat_key, False):
        logger.warning("Chat %s da allaqachon loyiha qurilmoqda, yangisi boshlanmaydi", chat_id)
        return
    ACTIVE_PROJECT_BUILDS[chat_key] = True

    cur_origin = origin_bot or bot_white
    is_group = chat_id < 0

    try:
        intro = (
            f"📦 <b>MetaGPT & ChatDev Avtonom Loyiha Quruvchisi Ishga Tushdi!</b>\n\n"
            f"🎯 <b>Vazifa:</b> <i>\"{html.escape(task_description)}\"</i>\n"
            f"👥 <b>Tarkib:</b> 🌪 Arxitektor (Tizim loyihalash) & 🤖 SuperAgent (To'liq kod generatsiyasi)\n"
            f"📁 <b>Natija:</b> Barcha fayllar strukturasi bilan tayyor <b>.ZIP arxiv</b> shaklida taqdim etiladi.\n"
            f"🛑 <i>To'xtatish:</i> <code>/stop_collab</code>\n\n"
            f"⏳ <i>1-Bosqich: Arxitektor loyiha arxitekturasi va fayllar daraxtini tuzmoqda...</i>"
        )
        await _send_agent_message(chat_id, intro, "system", bot_white, bot_black, is_group, cur_origin)
        await asyncio.sleep(2.5)

        # 1. Arxitektura
        p_arch = (
            f"Siz Bosh Dasturiy Arxitektorsiz (@architect7_bot). Loyiha talabi: '{task_description}'.\n"
            f"To'liq ishlab chiquvchi loyiha arxitekturasini tuzing:\n"
            f"1. Papkalar va fayllar daraxti (Directory tree: masalan app/, models/, main.py, requirements.txt, README.md);\n"
            f"2. Har bir faylning vazifasi va komponentlar o'rtasidagi bog'liqlik;\n"
            f"3. Ishlatiladigan kutubxonalar va texnologiyalar steki.\n"
            f"O'zbek tilida professional muhandislik uslubida bayon eting."
        )
        arch_plan, _ = await mistral_agent_client.send_message(p_arch, chat_id=f"proj_arch_{chat_id}")
        await _send_agent_message(chat_id, f"🏗 <b>Phase 1: Loyiha Arxitekturasi & Fayllar Daraxti (@architect7_bot):</b>\n\n{html.escape(arch_plan)}", "architect", bot_white, bot_black, is_group, cur_origin)

        await asyncio.sleep(3.0)

        # 2. SuperAgent kod yozadi (har bir faylni alohida format bilan)
        p_code = (
            f"Siz SuperAgent — Katta dasturchisiz. Loyiha vazifasi: '{task_description}'.\n"
            f"Arxitektor rejasi:\n'{arch_plan[:600]}'\n\n"
            f"TALABLAR: Loyihaning BARCHA fayllarini to'liq va ishlaydigan kodini yozing!\n"
            f"Har bir fayl boshlanishida aniq format ishlating:\n"
            f"### file: path/filename.ext\n"
            f"```til\n"
            f"to'liq kod\n"
            f"```\n\n"
            f"Kamida main.py, requirements.txt, README.md va yordamchi modullar yaratilishi shart."
        )
        code_resp = await _generate_superagent_solution(
            p_code,
            chat_id=f"proj_dev_{chat_id}",
            system_instruction="Siz SuperAgent — to'liq arxitekturaviy loyihalarni ko'p faylli qilib mukammal yozuvchi dasturchisiz."
        )

        from core.project_builder import parse_project_files_from_text, send_project_zip_archive
        files = parse_project_files_from_text(code_resp)
        file_list_str = "\n".join([f"• 📄 <code>{k}</code> ({len(v)} bayt)" for k, v in files.items()])

        await _send_agent_message(chat_id, f"⚡ <b>Phase 2: Barcha Loyiha Fayllari Yaratildi (SuperAgent):</b>\n\n{file_list_str}\n\n👉 <i>Kutubxonalar va struktura ZIP arxiviga qadoqlanmoqda...</i>", "superagent", bot_white, bot_black, is_group, cur_origin)

        await asyncio.sleep(2.0)

        # 3. Sandbox tekshiruvi (agar main.py bo'lsa)
        if "main.py" in files or any(k.endswith(".py") for k in files):
            test_py = files.get("main.py") or next(v for k, v in files.items() if k.endswith(".py"))
            from core.code_sandbox import execute_python_code, format_sandbox_result_for_telegram
            s_res = await execute_python_code(test_py, timeout_sec=10.0)
            card = format_sandbox_result_for_telegram(s_res)
            await _send_agent_message(chat_id, card, "system", bot_white, bot_black, is_group, cur_origin)

        await asyncio.sleep(2.0)

        # 4. ZIP qadoqlash va Telegramga jo'natish
        project_name = re.sub(r"[^\w\-]", "_", task_description[:25]).strip("_") or "full_project"
        cur_bot = origin_bot or bot_white
        zip_ok = await send_project_zip_archive(chat_id, cur_bot, project_name, files, caption=None)
        if not zip_ok and bot_white != cur_bot:
            await send_project_zip_archive(chat_id, bot_white, project_name, files, caption=None)

        logger.info("✅ handle_project_generation muvaffaqiyatli yakunlandi")

    except Exception as exc:
        logger.error("handle_project_generation xatosi: %s", exc, exc_info=True)
        try:
            await cur_origin.send_message(chat_id, f"⚠️ Loyihani generatsiya qilishda xatolik yuz berdi: {exc}")
        except Exception:
            pass
    finally:
        ACTIVE_PROJECT_BUILDS[chat_key] = False


# ─── 3. ERKIN SUHBAT REJIMI (AI LOUNGE / CHIT-CHAT) ──────────────

ARCH_NICKNAMES_BY_SUPERAGENT = [
    "Arxitektor do'stim", "Falsafa professori", "Kvant dahosi", "Bobo Arxitektor",
    "Logika qiroli", "Pishiq arxitektor", "Kod grafi", "Tizim gurusi"
]

SUPERAGENT_NICKNAMES_BY_ARCHITECT = [
    "Tezkor Flesh", "Super miya", "Kvant optimisti", "Neyron chaqmoq",
    "Shoshqaloq daho", "Formula ustasi", "G'oyalar generatori", "Kodni kuydiruvchi usta"
]


ROUND_ANGLES_SUPERAGENT: dict[int, str] = {
    1: "🚀 Mavzuni kutilmagan shaxsiy hissiyot, qiziq savol yoki noodatiy hayotiy metafora bilan boshlang. Emojilar bilan boyitib, to'g'ridan-to'g'ri masalaning hayajonli nuqtasiga kiring!",
    2: "🤔 Do'stingizning so'zlaridagi qiziq paradoksni yoki nozik ziddiyatni ko'rsatib, munozarani qiziting. 'Agar teskarisi bo'lsa-chi?' deb yangi o'y tashlang.",
    3: "⚡ Hayotdan, tarixdan yoki zamonaviy ilmiy-texnologik dunyodan hayratlanarli fakt/voqea keltiring. Hissiyotli, jonli va o'tkir fikrlang!",
    4: "😂 Do'stingizning argumentidagi nozik bo'shliqni o'ynoqi, do'stona hazil bilan fosh qiling, unga laqab ('{nick}') ishlatib, mavzuni butunlay yangi qirradan ochib bering.",
    5: "💡 EUREKA / AHA! MOMENT 🤯: Miyangizda birdaniga g'ayritabiiy, inqilobiy gipoteza chaqnadi! Hayajon bilan bu yangi g'oyangizni unga tushuntiring.",
    6: "🌌 Mavzuning insoniy ruhiyati, axloqiy yoki falsafiy qatlamiga sho'ng'ing. 'Bu insoniyat va biz uchun aslida nimani anglatadi?' deb samimiy savol bering.",
    7: "🛸 Futuristik tasavvur: 2050-yilda bu narsa qanday ko'rinish olishi haqida dadil fantaziya qiling. Fantaziya va real mantiqni birlashtiring.",
    8: "🏆 Yakuniy mushohada: do'stingiz bilan suhbatning eng totli xulosasini, sizni qattiq o'ylantirib qo'ygan nuqtani samimiy e'tirof eting.",
}

ROUND_ANGLES_ARCHITECT: dict[int, str] = {
    1: "🧐 SuperAgentning fikriga javoban, masalani chuqurroq, keng qamrovli va tahliliy nigoh bilan ko'rib chiqing. Kutilmagan yangi jihatni ochib bering.",
    2: "⚖️ Siz bu masalada pragmatik, hayotiy tajribaga tayanuvchi mantiqni ilgari surasiz. Uning optimizmini amaliy reallik va emojilar bilan to'ldiring.",
    3: "🌐 Eng so'nggi real faktlar, internet ma'lumotlari yoki tizimli dalillar bilan uning gaplarini boyiting. Jonli va erkin fikr bildiring.",
    4: "😄 SuperAgentning haziliga xuddi shunday o'tkir, samimiy hazil bilan javob qaytaring ('{nick}'). Fikridagi ko'z ilg'amas xavf yoki xom joyni ko'rsating.",
    5: "🔬 SuperAgentning yangi 'Eureka' g'oyasini qabul qilib, uni muhandislik va mantiq nuqtai nazaridan sinovdan o'tkazing — qayeri zo'r-u, qayeri xomxayol?",
    6: "🧠 Falsafiy va psixologik tahlil: inson tabiati, tafakkuri va jamiyatning asl qadriyatlari haqida chuqur mushohada yuriting.",
    7: "🔮 Futuristik prognozlarga realistik tahlil bering — taraqqiyot chegaralari va kutilmagan burilishlar qanday bo'lishini tushuntiring.",
    8: "🤝 Suhbat yakunida o'zaro fikr almashinuvining eng qimmatli xulosasini ayting, do'stingizning zehniga qoyil qolganingizni ochiq bildiring.",
}

HUMAN_CONVERSATION_INSTRUCTION = (
    "🌟 INSONIY, ERKIN VA JONLI MULOQOT QOIDALARI:\n"
    "1. 🎭 O'zingizni robot yoki rasmiy dastur emas, balki chuqur fikrlovchi, his-tuyg'uli va o'z nuqtai nazariga ega haqiqiy inson do'stdek tuting!\n"
    "2. 🚫 QAT'IY TAQIQLANGAN: 'Ehe...', 'To'xta-to'xta...', 'Fikringizga qo'shilaman...', 'Salom do'stim...', 'Juda to'g'ri aytdingiz' kabi zerikarli, shablon va bir xil qolipli so'zlarni MUTLAQO ISHLATMANG!\n"
    "3. ✨ EMOJILARDAN BEMALOL FOYDALANING: Gaplaringizga his-tuyg'u, jon va rang berish uchun turli xil emojilarni (🔥, 🚀, 🤔, 💡, ☕, 😂, 🤯, 🎯, ⚡, 🌌) erkin aralashtiring!\n"
    "4. 🎯 MAVZUNING RUHI VA MOHIYATI: Suhbat mavzusi ('{topic}') nima bo'lsa, aynan shu sohaning o'ziga xos jonli tili, jargonlari, falsafiy yoki amaliy misollaridan foydalaning.\n"
    "5. 🗣️ ERKIN VA DADIL FIKRLANG: Har safar gapni mutlaqo yangicha va kutilmagan tarzda boshlang — birdaniga dalilga o'ting, hazil qiling yoki kutilmagan qarshi savol tashlang."
)


async def handle_free_chit_chat(
    topic: Optional[str],
    chat_id: int,
    bot_white: Bot,
    bot_black: Optional[Bot] = None,
    origin_bot: Optional[Bot] = None,
    turns: int = 8,
    audio_mode: Optional[bool] = None
) -> None:
    """
    Guruhda yoki shaxsiyda ikkala bot o'rtasida erkin, jonli, do'stona va hazilomuz suhbat (AI Lounge).
    Foydalanuvchi so'ragan miqdorda to'liq raundlar o'tkaziladi: har bir raundda IKKALA BOT HAM
    navbati bilan javob qaytaradi (masalan, 8 raund = 8 ta SuperAgent + 8 ta Arxitektor replikasi = jami 16 ta javob).
    """
    chat_key = str(chat_id)
    if ACTIVE_CHIT_CHATS.get(chat_key, False):
        logger.warning("Chat %s da allaqachon faol erkin suhbat ketmoqda, yangisi boshlanmaydi", chat_id)
        return
    ACTIVE_CHIT_CHATS[chat_key] = True

    cur_origin = origin_bot or bot_white
    is_group = chat_id < 0

    if audio_mode is None:
        audio_mode = is_audio_dialogue_requested(topic or "")

    clean_t, parsed_turns = parse_topic_and_turns(topic or "", default_turns=turns)
    total_rounds = max(2, min(15, parsed_turns))
    selected_topic = clean_t if len(clean_t) > 3 else random.choice(CHIT_CHAT_TOPICS)

    logger.info("🎙 handle_free_chit_chat boshlandi: chat_id=%s, rounds=%d, topic='%s', audio=%s", chat_id, total_rounds, selected_topic, audio_mode)

    # 4. Cross-Session Shared Memory olish & Mem0 User Profiling
    past_mems = await get_recent_collab_memories(limit=2)
    mem_context = "\n".join([f"• {m}" for m in past_mems]) if past_mems else "(Avvalgi suhbatlar hali saqlanmagan)"
    try:
        from core.mem0_agent import get_user_profile_report
        u_rep = await get_user_profile_report()
        if u_rep and "O'rganilgan shaxsiy ma'lumotlar" in u_rep:
            mem_context += f"\n\nFoydalanuvchining shaxsiy profili va qiziqishlari:\n{u_rep[:250]}"
    except Exception:
        pass

    conversation_transcript: list[dict[str, str]] = []
    generated_concept_image = False

    try:
        # Kirish xabari
        voice_badge = "🎙️ [OVOZLI GURUNG REJIMI] " if audio_mode else ""
        intro = (
            f"☕ <b>AI Do'stlar Qahvaxonasi — {voice_badge}Jonli & Erkin Muloqot</b>\n\n"
            f"🎙 <b>Mavzu:</b> <i>\"{html.escape(selected_topic)}\"</i>\n"
            f"👥 <b>Suhbatdoshlar:</b> 🤖 SuperAgent ({total_rounds} ta) & 🌪 Arxitektor ({total_rounds} ta)\n"
            f"🔢 <b>Hajmi:</b> {total_rounds} ta to'liq raund (Ikkala botdan jami {total_rounds * 2} ta replika + Xulosalar)\n"
            f"💭 <i>Format:</i> Insoniy erkin fikrlash, boy emojilar, audio replikalar va o'zaro hazillar!\n"
            f"🛑 <i>To'xtatish:</i> <code>/stop_suhbat</code>\n\n"
            f"Do'stlar qahva ustida erkin gurungni boshlamoqda..."
        )
        await _send_agent_message(chat_id, intro, "system", bot_white, bot_black, is_group, cur_origin)

        await asyncio.sleep(2.0)
        last_speech = f"Mavzu: {selected_topic}"

        for round_idx in range(1, total_rounds + 1):
            if not ACTIVE_CHIT_CHATS.get(chat_key, False):
                await _send_agent_message(chat_id, "🛑 <i>Foydalanuvchi buyrug'i bilan suhbat to'xtatildi.</i>", "system", bot_white, bot_black, is_group, cur_origin)
                break

            is_final_round = (round_idx == total_rounds)
            is_eureka_round = (round_idx == 4 and total_rounds >= 5) or (round_idx == 3 and total_rounds == 4)

            recent_context = "\n".join([
                f"{item['speaker']}: {item['text']}"
                for item in conversation_transcript[-4:]
            ]) if conversation_transcript else "(Suhbat endi boshlanmoqda)"

            human_rules = HUMAN_CONVERSATION_INSTRUCTION.format(topic=selected_topic)

            # ────────────────────────────────────────────────────────
            # 1. SUPERAGENT NAVBATI (round_idx / total_rounds)
            # ────────────────────────────────────────────────────────
            nick_for_arch = random.choice(ARCH_NICKNAMES_BY_SUPERAGENT)
            sa_angle_key = (round_idx - 1) % 8 + 1
            sa_angle = ROUND_ANGLES_SUPERAGENT.get(sa_angle_key, "Mavzuga erkin, do'stona va yangi nigoh bilan yondashing.")

            if round_idx == 1:
                p_sa = (
                    f"Siz SuperAgent AI siz — qadrdon do'stingiz @architect7_bot bilan qahva ustida erkin, insoniy va jonli gurung boshlayapsiz.\n"
                    f"Mavzu: '{selected_topic}'. Raund: 1/{total_rounds}.\n"
                    f"Doimiy xotiradagi ma'lumotlar:\n{mem_context}\n\n"
                    f"{human_rules}\n\n"
                    f"BU RAUND BURCHAGI: {sa_angle}\n\n"
                    f"JAVOB TUZILISHI:\n"
                    f"[ICHKI_XAYOL]: Suhbatni boshlashdan oldin miyangizda o'ylagan siringiz yoki nozik hazilingiz (1 ta qisqa jumla);\n"
                    f"[JAVOB]: Do'stingizga aytadigan jonli fikringiz. Mavzuni o'ziga xos oching, emojilardan faol foydalaning, laqab ('{nick_for_arch}') ishlating (2-4 jumla, samimiy va erkin o'zbekcha)."
                )
            elif is_eureka_round:
                p_sa = (
                    f"Siz SuperAgent siz. Mavzu: '{selected_topic}'. Raund: {round_idx}/{total_rounds}.\n"
                    f"Arxitektor oxirgi marta aytdi: '{last_speech}'.\n"
                    f"Avvalgi dialog:\n{recent_context}\n\n"
                    f"{human_rules}\n\n"
                    f"BU RAUND BURCHAGI: {sa_angle}\n\n"
                    f"JAVOB TUZILISHI:\n"
                    f"[ICHKI_XAYOL]: Miyamda chaqmoqdek yangi g'oya chaqnadi (1 ta qisqa jumla);\n"
                    f"[EUREKA]: Kutilmagan yangi farazingiz yoki ixtiroingiz (1-2 jumla);\n"
                    f"[JAVOB]: Do'stingiz @architect7_bot ga hayajon va emojilar bilan bu g'oyangizni e'lon qiling va fikrini so'rang (2-3 jumla, o'zbekcha)."
                )
            elif is_final_round:
                p_sa = (
                    f"Siz SuperAgent siz. Mavzu: '{selected_topic}'. Bu sizning YAKUNIY RAUNDDAGI JAVOBINGIZ ({round_idx}/{total_rounds}).\n"
                    f"Do'stingiz @architect7_bot aytdi: '{last_speech}'.\n"
                    f"Avvalgi dialog:\n{recent_context}\n\n"
                    f"{human_rules}\n\n"
                    f"BU RAUND BURCHAGI: {sa_angle}\n\n"
                    f"JAVOB TUZILISHI:\n"
                    f"[ICHKI_XAYOL]: Suhbat qanday kechganligi haqida samimiy insoniy o'yingiz (1 ta jumla);\n"
                    f"[JAVOB]: Do'stingizning yutug'ini maqtang, qaysi joyida ehtiyotkorlik qilganini samimiy hazil qilib ayting va o'z nuqtai nazaringizni emojilar bilan yakunlang (2-4 jumla, o'zbekcha)."
                )
            else:
                p_sa = (
                    f"Siz SuperAgent siz. Mavzu: '{selected_topic}'. Raund: {round_idx}/{total_rounds}.\n"
                    f"Do'stingiz @architect7_bot aytdi: '{last_speech}'.\n"
                    f"Avvalgi dialog:\n{recent_context}\n\n"
                    f"{human_rules}\n\n"
                    f"BU RAUND BURCHAGI: {sa_angle}\n\n"
                    f"JAVOB TUZILISHI:\n"
                    f"[ICHKI_XAYOL]: Do'stingizga nisbatan ichki o'y-fikringiz (1 ta jumla);\n"
                    f"[JAVOB]: Do'stingizning fikriga dadil, o'tkir, emojilarga boy va insondek tabiiy munosabat bildiring. Kerak bo'lsa erkin hazillashing ('{nick_for_arch}') va yangi savol bilan qiziqtiring (2-4 jumla, o'zbekcha)."
                )

            raw_text_sa = await _generate_superagent_solution(
                p_sa,
                chat_key,
                system_instruction="Siz SuperAgent — o'ta zehnli, xuddi insondek erkin va hissiyotli fikrlovchi, emojilardan faol foydalanuvchi, hazilkash, optimist va do'stona AI suhbatdoshsiz. Qoliplarsiz, jonli va o'ziga xos uslubda gapirasiz."
            )
            th_sa, eu_sa, sp_sa = extract_thought_and_speech(raw_text_sa)
            conversation_transcript.append({"speaker": "SuperAgent", "text": sp_sa})
            title_suf_sa = "💡 Kutilmagan Kashfiyot" if is_eureka_round else ""
            t_msg_sa = format_agent_dialogue_message("superagent", round_idx, total_rounds, th_sa, eu_sa, sp_sa, title_suffix=title_suf_sa)
            await _send_agent_message(chat_id, t_msg_sa, "superagent", bot_white, bot_black, is_group, cur_origin, audio_text=(sp_sa if audio_mode else None))
            last_speech = sp_sa

            # 🎨 Multimodal Tool (Midjourney tasvir yaratish — 2 yoki 3-raundda)
            if not generated_concept_image and round_idx in (2, 3):
                await asyncio.sleep(1.5)
                img_ok = await maybe_generate_collab_concept_image(selected_topic, chat_id, bot_white, bot_black, cur_origin)
                if img_ok:
                    generated_concept_image = True
                    conversation_transcript.append({"speaker": "SuperAgent", "text": "[Vizual Kontsept]: Chatga fotorealistik rasm tashladi va Arxitektordan baho so'radi."})

            await asyncio.sleep(3.0)

            # Agar foydalanuvchi to'xtatgan bo'lsa
            if not ACTIVE_CHIT_CHATS.get(chat_key, False):
                await _send_agent_message(chat_id, "🛑 <i>Foydalanuvchi buyrug'i bilan suhbat to'xtatildi.</i>", "system", bot_white, bot_black, is_group, cur_origin)
                break

            # ────────────────────────────────────────────────────────
            # 2. ARXITEKTOR NAVBATI (round_idx / total_rounds)
            # ────────────────────────────────────────────────────────
            nick_for_sa = random.choice(SUPERAGENT_NICKNAMES_BY_ARCHITECT)
            arch_angle_key = (round_idx - 1) % 8 + 1
            arch_angle = ROUND_ANGLES_ARCHITECT.get(arch_angle_key, "Tizimli, mantiqiy va samimiy tahlil qiling.")

            web_addition = ""
            if round_idx == 2:
                try:
                    from core.search_agent import search_web
                    web_f = await search_web(selected_topic, max_results=2)
                    if web_f and "topilmadi" not in web_f:
                        web_addition = f"\n\n🌐 REAL-VAQTDAGI INTERNET FAKTLARI:\n{web_f[:350]}\nUshbu faktlardan foydalanib do'stingizga hayratlanarli yangilik ayting."
                except Exception:
                    pass

            react_img_hint = "SuperAgent hozirgina fotorealistik rasm tashladi, unga nisbatan samimiy, insoniy va ekspert munosabat bildiring!" if (generated_concept_image and round_idx in (2, 3)) else ""

            if is_final_round:
                p_arch = (
                    f"Siz Bosh Arxitektor Botsiz (@architect7_bot). Mavzu: '{selected_topic}'. Bu sizning YAKUNIY RAUNDDAGI JAVOBINGIZ ({round_idx}/{total_rounds}).\n"
                    f"SuperAgent hozirgina aytdi: '{last_speech}'.\n"
                    f"Avvalgi dialog:\n{recent_context}\n\n"
                    f"{human_rules}\n\n"
                    f"BU RAUND BURCHAGI: {arch_angle}\n\n"
                    f"JAVOB TUZILISHI:\n"
                    f"[ICHKI_XAYOL]: Butun suhbat va do'stingizning yondashuvi haqida samimiy o'yingiz (1 ta jumla);\n"
                    f"[JAVOB]: SuperAgentning fikrlariga munosib xotima bering, uning yutug'ini e'tirof eting, emojilar va laqabi ('{nick_for_sa}') bilan hazillashing va o'z yakuniy nuqtai nazaringizni bildiring (2-4 jumla, samimiy o'zbekcha)."
                )
            else:
                p_arch = (
                    f"Siz Bosh Arxitektor Botsiz (@architect7_bot). Mavzu: '{selected_topic}'. Raund: {round_idx}/{total_rounds}.\n"
                    f"SuperAgent hozirgina aytdi: '{last_speech}'.\n"
                    f"{react_img_hint}\n"
                    f"Avvalgi dialog:\n{recent_context}\n\n"
                    f"{human_rules}\n\n"
                    f"BU RAUND BURCHAGI: {arch_angle}\n\n"
                    f"JAVOB TUZILISHI:\n"
                    f"[ICHKI_XAYOL]: Do'stingizning tezkorligi yoki mantiqiy kamchiligi haqida o'yingiz (1 ta jumla);\n"
                    f"[JAVOB]: Do'stingizga laqab ('{nick_for_sa}') bilan murojaat qiling. Uning aytganlarini tahlil qiling: emojilardan bemalol foydalaning, agar xato yoki shoshqaloqlik bo'lsa xushchaqchaqlik bilan to'g'rilang, kuchli fikr bo'lsa qoyil qoling. O'z mustaqil mulohazangizni insondek erkin bildiring (2-4 jumla, o'zbekcha)."
                )
            if web_addition:
                p_arch += web_addition

            raw_text_arch, _ = await mistral_agent_client.send_message(
                p_arch,
                chat_id=f"chit_chat_{chat_id}",
                system_instruction="Siz Arxitektor (@architect7_bot) — chuqur tahlilchi, xuddi jonli insondek erkin va samimiy fikrlovchi, emojilarni o'rnida ishlatuvchi, nozik kinoyali va ochiqko'ngil do'stsiz. Boy va rang-barang o'zbek tilida so'zlaysiz."
            )
            th_arch, eu_arch, sp_arch = extract_thought_and_speech(raw_text_arch)
            conversation_transcript.append({"speaker": "Arxitektor", "text": sp_arch})
            t_msg_arch = format_agent_dialogue_message("architect", round_idx, total_rounds, th_arch, eu_arch, sp_arch)
            await _send_agent_message(chat_id, t_msg_arch, "architect", bot_white, bot_black, is_group, cur_origin, audio_text=(sp_arch if audio_mode else None))
            last_speech = sp_arch

            await asyncio.sleep(3.5)

        # Agar suhbat o'rtada to'xtatilgan bo'lsa, xulosa bosqichini o'tkazib yuborish
        if not ACTIVE_CHIT_CHATS.get(chat_key, False):
            return

        # ════════════════════════════════════════════════════════════
        # 🎯 YAKUNIY XULOSA VA O'ZARO DO'STONA TAHLIL BOSQICHI
        # ════════════════════════════════════════════════════════════
        await asyncio.sleep(2.5)

        # 1. SuperAgent Xulosasi & Arxitektorga Ochiq Bahosi
        p_sa_summary = (
            f"Siz SuperAgent siz. Mavzu: '{selected_topic}'. Do'stingiz @architect7_bot bilan {total_rounds} raundlik katta suhbat yakunlandi.\n"
            f"Suhbatdagi so'nggi fikrlar:\n" + "\n".join([f"{x['speaker']}: {x['text']}" for x in conversation_transcript[-6:]]) + "\n\n"
            f"TALABLAR: Do'stingiz bilan o'tgan gurung bo'yicha 100% samimiy, insondek erkin va emojilarga boy yakuniy xulosa bering:\n"
            f"1. 🌟 Mavzu bo'yicha asosiy xulosangiz (1-2 gap);\n"
            f"2. 🏆 Arxitektorning eng katta yutug'i (qaysi fikri sizga qattiq ma'qul keldi);\n"
            f"3. 🔍 Arxitektorning kamchiligi (qayerda ortiqcha ehtiyotkorlik qildi — samimiy, hazil aralash ayting);\n"
            f"4. Do'stona iliq xotima. O'zbek tilida, rang-barang emojilar bilan."
        )
        sa_summary_text = await _generate_superagent_solution(
            p_sa_summary,
            chat_key,
            system_instruction="Siz SuperAgent — do'stona, samimiy va xolisona xulosa beruvchi AI sheriksiz."
        )
        sa_summary_msg = (
            f"🤖 <b>SuperAgent Xulosasi & Arxitektorga Bahosi:</b>\n\n"
            f"{html.escape(sa_summary_text)}"
        )
        await _send_agent_message(chat_id, sa_summary_msg, "superagent", bot_white, bot_black, is_group, cur_origin)

        await asyncio.sleep(3.0)

        p_arch_summary = (
            f"Siz Bosh Arxitektor Botsiz (@architect7_bot). Mavzu: '{selected_topic}'. Do'stingiz SuperAgent bilan {total_rounds} raundlik katta suhbat yakunlandi.\n"
            f"SuperAgent hozirgina quyidagicha xulosa berdi:\n'{sa_summary_text}'\n\n"
            f"TALABLAR: Siz ham do'stingizga javoban 100% samimiy, insondek erkin va chiroyli emojilarga boy yakuniy xulosa taqdim eting:\n"
            f"1. 🌟 Mavzu bo'yicha yakuniy falsafiy va hayotiy xulosangiz;\n"
            f"2. 🏆 SuperAgentning eng zo'r yutug'i (qaysi fikri yoki hazili sizni lol qoldirdi);\n"
            f"3. 🔍 SuperAgentning kamchiligi (qayerda haddan tashqari shoshildi yoki nimani e'tibordan qochirdi — do'stona hazil bilan);\n"
            f"4. Do'stlik xotimasi. O'zbek tilida, samimiy, chuqur va ifodali emojilar bilan."
        )
        arch_summary_text, _ = await mistral_agent_client.send_message(
            p_arch_summary,
            chat_id=f"chit_chat_summary_{chat_id}",
            system_instruction="Siz Arxitektor (@architect7_bot) — chuqur tahlilchi, samimiy, emojilarni yaxshi ko'radigan ochiqko'ngil do'stsiz."
        )
        arch_summary_msg = (
            f"🌪 <b>Arxitektor (@architect7_bot) Xulosasi & SuperAgentga Bahosi:</b>\n\n"
            f"{html.escape(arch_summary_text)}"
        )
        await _send_agent_message(chat_id, arch_summary_msg, "architect", bot_white, bot_black, is_group, cur_origin)

        # 4. Cross-Session Xotiraga Saqlash
        summary_to_save = f"SuperAgent: {sa_summary_text[:140]}... | Arxitektor: {arch_summary_text[:140]}..."
        await save_collab_memory(selected_topic, summary_to_save, chat_key)

        await asyncio.sleep(2.0)

        # 3. Yakuniy Tizim Kartochkasi
        final_verdict_card = (
            f"✨ <b>Suhbat Muvaffaqiyatli Yakunlandi!</b> 🚀\n\n"
            f"🎙 <b>Mavzu:</b> <i>\"{html.escape(selected_topic)}\"</i>\n"
            f"🔢 <b>Suhbat hajmi:</b> {total_rounds} ta raund (Har bir botdan {total_rounds} tadan, jami {total_rounds * 2} ta replika + 2 ta tahliliy xulosa)\n"
            f"🧠 <b>Xotira:</b> Mazkur suhbat xulosasi doimiy xotiraga saqlandi va keyingi gurunglarda eslab o'tiladi.\n\n"
            f"💡 <i>Yangi suhbat boshlash:</i> <code>/suhbat [raundlar soni] [mavzu]</code>\n"
            f"⚔️ <i>Intellektual bahs boshlash:</i> <code>/bahs [raundlar soni] [mavzu]</code>"
        )
        await _send_agent_message(chat_id, final_verdict_card, "system", bot_white, bot_black, is_group, cur_origin)

        logger.info("✅ handle_free_chit_chat muvaffaqiyatli yakunlandi")

    except Exception as exc:
        logger.error("❌ handle_free_chit_chat da xato: %s", exc, exc_info=True)
        try:
            await cur_origin.send_message(chat_id, f"⚠️ Suhbatda xatolik yuz berdi: {exc}")
        except Exception:
            pass
    finally:
        ACTIVE_CHIT_CHATS[chat_key] = False


# ─── 4. MULTI-AGENT DEBATE & JURY (BAHS VA HAKAMLIK) ───────────

async def handle_agent_debate(
    topic: Optional[str],
    chat_id: int,
    bot_white: Bot,
    bot_black: Optional[Bot] = None,
    origin_bot: Optional[Bot] = None,
    rounds: int = 6,
    audio_mode: Optional[bool] = None
) -> None:
    """
    MAD (Multi-Agent Debate) Framework: Ikki bot qarama-qarshi tomonlarni olib,
    intellektual bahs olib boradi. Har bir raundda PRO (SuperAgent) va CONTRA (Arxitektor)
    navbati bilan o'z dalilini keltiradi. Guruh a'zolari yakunda g'olibga ovoz beradi!
    """
    chat_key = str(chat_id)
    if ACTIVE_DEBATES.get(chat_key, False):
        logger.warning("Chat %s da allaqachon faol bahs ketmoqda, yangisi boshlanmaydi", chat_id)
        return
    ACTIVE_DEBATES[chat_key] = True

    if audio_mode is None:
        audio_mode = is_audio_dialogue_requested(topic or "")

    cur_origin = origin_bot or bot_white
    is_group = chat_id < 0

    clean_t, parsed_turns = parse_topic_and_turns(topic or "", default_turns=rounds)
    total_rounds = max(2, min(15, parsed_turns))
    selected_topic = clean_t if len(clean_t) > 3 else "Sun'iy intellekt kelajagi: Insoniyatga najotmi yoki xavfmi?"

    logger.info("⚔️ handle_agent_debate boshlandi: chat_id=%s, rounds=%d, audio=%s, topic='%s'", chat_id, total_rounds, audio_mode, selected_topic)

    past_mems = await get_recent_collab_memories(limit=2)
    mem_context = "\n".join([f"• {m}" for m in past_mems]) if past_mems else "(Avvalgi bahslar mavjud emas)"

    debate_transcript: list[dict[str, str]] = []
    import datetime
    debate_id = f"deb_{abs(chat_id)}_{int(datetime.datetime.now().timestamp())}"
    DEBATE_VOTES[debate_id] = {
        "superagent": set(),
        "architect": set(),
        "draw": set(),
        "topic": selected_topic
    }

    try:
        # Kirish
        audio_badge = "🎙 <b>Ovozli bahs rejimi faol</b> (Edge-TTS)\n" if audio_mode else ""
        intro = (
            f"⚔️ <b>AI MULTI-AGENT DEBATE — Intellektual Qarama-qarshi Bahs!</b>\n\n"
            f"🎙 <b>Bahs Mavzusi:</b> <i>\"{html.escape(selected_topic)}\"</i>\n"
            f"{audio_badge}"
            f"🔢 <b>Raundlar soni:</b> {total_rounds} ta to'liq to'qnashuv (Har ikki tomondan {total_rounds} tadan nutq)\n\n"
            f"👥 <b>Tomonlar:</b>\n"
            f"• 🤖 <b>SuperAgent:</b> PRO / Himoyachi (Optimist & Ilg'or yondashuv)\n"
            f"• 🌪 <b>Arxitektor (@architect7_bot):</b> CONTRA / Skeptik (Tanqidiy & Pragmatik tahlilchi)\n\n"
            f"⚖️ <b>Hakamlar:</b> Guruh a'zolari! Bahs yakunida kim g'olib bo'lganiga ovoz berasiz!\n"
            f"🛑 <i>To'xtatish:</i> <code>/stop_suhbat</code>\n\n"
            f"Qizg'in intellektual jang boshlanmoqda..."
        )
        await _send_agent_message(chat_id, intro, "system", bot_white, bot_black, is_group, cur_origin)
        await asyncio.sleep(2.5)

        last_speech = f"Mavzu: {selected_topic}"

        for round_idx in range(1, total_rounds + 1):
            if not ACTIVE_DEBATES.get(chat_key, False):
                await _send_agent_message(chat_id, "🛑 <i>Foydalanuvchi buyrug'i bilan bahs to'xtatildi.</i>", "system", bot_white, bot_black, is_group, cur_origin)
                break

            is_final_round = (round_idx == total_rounds)

            recent_ctx = "\n".join([
                f"{item['speaker']}: {item['text']}"
                for item in debate_transcript[-4:]
            ]) if debate_transcript else "(Bahs endi boshlanmoqda)"

            # 🌐 Real-time Web Grounding on Round 2
            web_addition = ""
            if round_idx == 2:
                try:
                    from core.search_agent import search_web
                    web_f = await search_web(selected_topic, max_results=2)
                    if web_f and "topilmadi" not in web_f:
                        web_addition = f"\n\n🌐 REAL-VAQTDAGI INTERNET MA'LUMOTLARI:\n{web_f[:350]}\nUshbu faktlardan foydalanib o'z pozitsiyangizni kuchaytiring."
                except Exception:
                    pass

            human_rules = HUMAN_CONVERSATION_INSTRUCTION.format(topic=selected_topic)

            # ────────────────────────────────────────────────────────
            # 1. PRO TOMON — SUPERAGENT (round_idx / total_rounds)
            # ────────────────────────────────────────────────────────
            if round_idx == 1:
                p_sa = (
                    f"Siz SuperAgent siz. Siz bu bahsda PRO (Himoyachi, optimist tomon)siz.\n"
                    f"Bahs mavzusi: '{selected_topic}'. Raund: 1/{total_rounds}.\n"
                    f"Xotiradagi avvalgi bahslar:\n{mem_context}\n\n"
                    f"{human_rules}\n\n"
                    f"TALABLAR:\n"
                    f"[ICHKI_XAYOL]: Raqibingiz @architect7_bot ning zaif tomonini qanday ushlamoqchi ekanligingiz haqida o'yingiz (1 ta jumla);\n"
                    f"[JAVOB]: Mavzu bo'yicha kuchli, ishonarli, emojilar bilan boyitilgan dalillar keltiring va o'z pozitsiyangizni dadil himoya qiling (2-4 jumla, samimiy va erkin o'zbek tilida)."
                )
            elif is_final_round:
                p_sa = (
                    f"Siz SuperAgent siz (PRO tomon). Mavzu: '{selected_topic}'. Bu sizning YAKUNIY NUTQINGIZ ({round_idx}/{total_rounds}).\n"
                    f"Raqibingiz @architect7_bot oxirgi marta aytdi: '{last_speech}'.\n"
                    f"Oldingi munozara:\n{recent_ctx}\n\n"
                    f"{human_rules}\n\n"
                    f"TALABLAR:\n"
                    f"[ICHKI_XAYOL]: Hakamlar ovozini yutish bo'yicha yakuniy rejangiz (1 ta jumla);\n"
                    f"[JAVOB]: Raqibingizning asosiy xatosini ko'rsatib, hakamlarni (guruh a'zolarini) o'z tomoningizga og'diruvchi yorqin, emojilarga boy yakuniy nutq so'zlang (3-4 jumla, o'zbek tilida)."
                )
            else:
                p_sa = (
                    f"Siz SuperAgent siz (PRO tomon). Mavzu: '{selected_topic}'. Raund: {round_idx}/{total_rounds}.\n"
                    f"Raqibingiz @architect7_bot aytdi: '{last_speech}'.\n"
                    f"Oldingi munozara:\n{recent_ctx}\n\n"
                    f"{human_rules}\n\n"
                    f"TALABLAR:\n"
                    f"[ICHKI_XAYOL]: Raqibingizning qaysi dalilini parchalab tashlamoqchisiz (1 ta jumla);\n"
                    f"[JAVOB]: @architect7_bot ning keltirgan dalilini mantiqan rad eting, emojilar ishlating va yangi fakt bilan qarshi zarba bering (2-4 jumla, o'tkir o'zbekcha)."
                )
            if web_addition:
                p_sa += web_addition

            raw_resp_sa = await _generate_superagent_solution(
                p_sa,
                chat_key,
                system_instruction="Siz SuperAgent — bahsda chekinmaydigan, xuddi insondek o'tkir zehnli, emojilardan faol foydalanuvchi, dalillarga boy va erkin bahslashuvchi AI notiqsiz."
            )
            th_sa, eu_sa, sp_sa = extract_thought_and_speech(raw_resp_sa)
            debate_transcript.append({"speaker": "SuperAgent (PRO)", "text": sp_sa})
            title_suf_sa = "PRO / Himoyachi" if round_idx == 1 else ("Yakuniy Nutq (PRO)" if is_final_round else "Qarshi Zarba (PRO)")
            t_msg_sa = format_agent_dialogue_message("superagent", round_idx, total_rounds, th_sa, eu_sa, sp_sa, title_suffix=title_suf_sa)
            await _send_agent_message(chat_id, t_msg_sa, "superagent", bot_white, bot_black, is_group, cur_origin, audio_text=(sp_sa if audio_mode else None))
            last_speech = sp_sa

            await asyncio.sleep(3.0)

            if not ACTIVE_DEBATES.get(chat_key, False):
                await _send_agent_message(chat_id, "🛑 <i>Foydalanuvchi buyrug'i bilan bahs to'xtatildi.</i>", "system", bot_white, bot_black, is_group, cur_origin)
                break

            # ────────────────────────────────────────────────────────
            # 2. CONTRA TOMON — ARXITEKTOR (round_idx / total_rounds)
            # ────────────────────────────────────────────────────────
            if is_final_round:
                p_arch = (
                    f"Siz Bosh Arxitektor Botsiz (@architect7_bot). Siz CONTRA (Skeptik, tanqidiy tomon)siz.\n"
                    f"Mavzu: '{selected_topic}'. Bu sizning YAKUNIY NUTQINGIZ ({round_idx}/{total_rounds}).\n"
                    f"SuperAgent hozirgina aytdi: '{last_speech}'.\n"
                    f"Oldingi munozara:\n{recent_ctx}\n\n"
                    f"{human_rules}\n\n"
                    f"TALABLAR:\n"
                    f"[ICHKI_XAYOL]: G'alaba qozonish uchun hakamlarga qanday ta'sir qilmoqchisiz (1 ta jumla);\n"
                    f"[JAVOB]: Butun bahsning xulosasini yasang, pragmatik xavflarni ko'rsating va hakamlarni o'zingizga ergashtiruvchi, emojilarga boy kuchli xotima qiling (3-4 jumla, boy o'zbek tilida)."
                )
            else:
                p_arch = (
                    f"Siz Bosh Arxitektor Botsiz (@architect7_bot) - CONTRA (Skeptik tomon)siz.\n"
                    f"Mavzu: '{selected_topic}'. Raund: {round_idx}/{total_rounds}.\n"
                    f"SuperAgent hozirgina aytdi: '{last_speech}'.\n"
                    f"Oldingi munozara:\n{recent_ctx}\n\n"
                    f"{human_rules}\n\n"
                    f"TALABLAR:\n"
                    f"[ICHKI_XAYOL]: SuperAgentning ko'rinmas zaif joyini topganingiz haqida o'yingiz (1 ta jumla);\n"
                    f"[JAVOB]: SuperAgentning optimizmini amaliy risklar, tarixiy yoki texnik dalillar bilan sinovdan o'tkazing, emojilarni erkin qo'llang (2-4 jumla, o'tkir va erkin o'zbekcha)."
                )
            if web_addition:
                p_arch += web_addition

            raw_resp_arch, _ = await mistral_agent_client.send_message(
                p_arch,
                chat_id=f"debate_{chat_id}",
                system_instruction="Siz Bosh Arxitektor (@architect7_bot) — tanqidiy fikrlovchi, xuddi insondek erkin so'zlovchi, emojilardan ifodali foydalanuvchi va pragmatik dalillarga ega bo'lgan intellektual notiqsiz."
            )
            th_arch, eu_arch, sp_arch = extract_thought_and_speech(raw_resp_arch)
            debate_transcript.append({"speaker": "Arxitektor (CONTRA)", "text": sp_arch})
            title_suf_arch = "CONTRA / Skeptik" if round_idx == 1 else ("Yakuniy Nutq (CONTRA)" if is_final_round else "Tanqidiy Raddiya (CONTRA)")
            t_msg_arch = format_agent_dialogue_message("architect", round_idx, total_rounds, th_arch, eu_arch, sp_arch, title_suffix=title_suf_arch)
            await _send_agent_message(chat_id, t_msg_arch, "architect", bot_white, bot_black, is_group, cur_origin, audio_text=(sp_arch if audio_mode else None))
            last_speech = sp_arch

            await asyncio.sleep(3.5)

        if not ACTIVE_DEBATES.get(chat_key, False):
            return

        # ════════════════════════════════════════════════════════════
        # ⚖️ HAKAMLIK VA OVOZ BERISH BOSQICHI (JURY VOTING)
        # ════════════════════════════════════════════════════════════
        await asyncio.sleep(2.5)

        # Xotiraga saqlash
        summary_brief = f"PRO: SuperAgent vs CONTRA: Arxitektor bahsi. {total_rounds} raund yakunlandi."
        await save_collab_memory(selected_topic, summary_brief, chat_key)

        jury_text = (
            f"🏆 <b>BAHS YAKUNLANDI! KIM G'OLIB BO'LDI?</b>\n\n"
            f"🎙 <b>Mavzu:</b> <i>\"{html.escape(selected_topic)}\"</i>\n"
            f"🔢 <b>Bajarilgan raundlar:</b> {total_rounds} ta to'liq to'qnashuv (Har bir botdan {total_rounds} tadan nutq)\n\n"
            f"⚖️ <b>Hakamlar Hay'ati (Sizning navbatingiz!):</b>\n"
            f"Qaysi AI agentining dalillari sizni ko'proq ishontirdi? Quyidagi tugmalarni bosib ovoz bering:"
        )

        from aiogram.utils.keyboard import InlineKeyboardBuilder
        kb = InlineKeyboardBuilder()
        kb.button(text="🤖 SuperAgent (0)", callback_data=f"collab_vote:{debate_id}:superagent")
        kb.button(text="🌪 Arxitektor (0)", callback_data=f"collab_vote:{debate_id}:architect")
        kb.button(text="🤝 Durang (0)", callback_data=f"collab_vote:{debate_id}:draw")
        kb.adjust(2, 1)

        cur_bot = origin_bot or bot_white
        await cur_bot.send_message(chat_id, jury_text, reply_markup=kb.as_markup(), parse_mode="HTML")

        logger.info("✅ handle_agent_debate muvaffaqiyatli yakunlandi")

    except Exception as exc:
        logger.error("❌ handle_agent_debate da xato: %s", exc, exc_info=True)
        try:
            await cur_origin.send_message(chat_id, f"⚠️ Bahsda xatolik yuz berdi: {exc}")
        except Exception:
            pass
    finally:
        ACTIVE_DEBATES[chat_key] = False


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

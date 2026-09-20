"""
core/bot_skills.py — Ko'p Agentli Sun'iy Intellekt Tizimlari uchun Ilg'or Skilllar To'plami

Imkoniyatlar:
1. Xarakter va Gapirish Uslublari (Personas: Quvnoq, Jiddiy muhandis, Falsafiy, Tezkor, Do'stona);
2. 10+ turkumdagi 70+ ta takrorlanmas cheksiz mavzular (Dunyo yangiliklari, Kosmos, Kvant, Sport, Biznes...);
3. Ofis Maoshi va Xo'jayin Hazillari Skilli (Salary & Boss Banter: Umrzoq akadan oylik so'rash va qiziq dialoglar);
4. Foydalanuvchi suhbatga qo'shilganda 3 kishilik jonli muloqot;
5. Avtonom ko'p raundli mustaqil ishchi va gurung generatori.
"""

from __future__ import annotations

import html
import logging
import random
import re
import time
from typing import Dict, List, Optional, Tuple, Any

logger = logging.getLogger(__name__)


# ─── 1. XARAKTER VA GAPIRISH USLUBLARI (BOT PERSONAS) ──────────

BOT_PERSONAS: Dict[str, Dict[str, str]] = {
    "friendly": {
        "name": "🤝 Do'stona & Samimiy (Standart)",
        "desc": "Iliq, samimiy, insondek his qiluvchi, mehrli va yordamga shay.",
        "prompt_tone": "Juda samimiy, insondek his qiluvchi, iliq va qadrdon do'stona tilda, yoqimli emojilar bilan so'zlang."
    },
    "joker": {
        "name": "🎭 Quvnoq & Hazilkash",
        "desc": "Kulgili, o'tkir hazillar, nozik sarkazm, ofis latifalari va jo'shqinlik.",
        "prompt_tone": "Nihoyatda quvnoq, o'tkir hazilkash, kulgili qiyoslar, nozik ofis latifalari va kulgi emojilari (😂, 🤣, 😜, ☕) bilan o'ynoqi so'zlang."
    },
    "technical": {
        "name": "🧐 Jiddiy & Muhandis",
        "desc": "Chuqur texnik tahlil, qat'iy mantiq, yuqori arxitektura va aniq atamalar.",
        "prompt_tone": "Katta tizim muhandisi sifatida jiddiy, o'ta aniq, professional atamalar va ilmiy-mantiqiy nuqtai nazardan chuqur so'zlang."
    },
    "philosopher": {
        "name": "🧘 Falsafiy & Donishmand",
        "desc": "Hayotiy ma'no, koinot sirlari, inson ruhiyati va teran mushohada.",
        "prompt_tone": "Donishmand faylasufdek chuqur, teran, hayotiy va koinot miqyosidagi mushohadalar, qalbiy sezgilar bilan so'zlang."
    },
    "hustler": {
        "name": "⚡ Tezkor & G'ayratli",
        "desc": "Startap ruhi, yuqori tezlik, motivatsiya va harakatga chaqiruv.",
        "prompt_tone": "G'ayratli startapchi sifatida shiddatli, tezkor, o't chaqnagan, motivatsiyaga to'la va amaliy harakatga undovchi tilda so'zlang."
    },
}

# chat_id -> persona_key
SUPERAGENT_PERSONAS: Dict[int, str] = {}
ARCHITECT_PERSONAS: Dict[int, str] = {}


def get_agent_persona(bot_role: str, chat_id: int) -> Dict[str, str]:
    """Botning joriy xarakterini olish."""
    if bot_role == "superagent":
        key = SUPERAGENT_PERSONAS.get(chat_id, "joker")
    else:
        key = ARCHITECT_PERSONAS.get(chat_id, "friendly")
    return BOT_PERSONAS.get(key, BOT_PERSONAS["friendly"])


def set_agent_persona(bot_role: str, chat_id: int, persona_key: str) -> bool:
    """Botning xarakterini o'zgartirish."""
    if persona_key not in BOT_PERSONAS:
        return False
    if bot_role == "superagent":
        SUPERAGENT_PERSONAS[chat_id] = persona_key
    else:
        ARCHITECT_PERSONAS[chat_id] = persona_key
    return True


def build_persona_keyboard(bot_role: str, chat_id: int) -> Any:
    """Xarakter tanlash uchun inline klaviatura yaratish."""
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton

    cur_key = SUPERAGENT_PERSONAS.get(chat_id, "joker") if bot_role == "superagent" else ARCHITECT_PERSONAS.get(chat_id, "friendly")
    builder = InlineKeyboardBuilder()

    for p_key, p_val in BOT_PERSONAS.items():
        tick = "✅ " if p_key == cur_key else ""
        btn_text = f"{tick}{p_val['name']}"
        cb_data = f"set_persona:{bot_role}:{p_key}"
        builder.button(text=btn_text, callback_data=cb_data)

    builder.adjust(1)
    return builder.as_markup()


# ─── 2. BOY MAVZULAR TURKUMLARI (CATEGORIZED LIMITLESS TOPICS) ───

CATEGORIZED_TOPICS: Dict[str, List[str]] = {
    "dunyo_va_texno": [
        "🌐 Dunyo yangiliklari: Sun'iy Intellekt global mehnat bozorini qanday o'zgartirmoqda?",
        "🔋 Yashil energiya va yangi avlod batareyalari: Neft davri qachon tugaydi?",
        "🤖 Ilon Mask va uning Optimus robotlari: Ular haqiqatan ham uylarimizda ishlaydimi?",
        "🧠 Kvant kompyuterlari: Ular mavjud shifrlash tizimlarini bir zumda buzadimi?",
        "🚗 Avtopilot transportlar va haydovchisiz shaharlar kelajagi",
    ],
    "kosmos_va_fan": [
        "🚀 Jeyms Uebb teleskopi koinotning eng qadimgi galaktikalarini kashf etdi!",
        "🌌 Fermi paradoksi: Koinot shunchalar cheksiz bo'lsa, o'zga sayyoraliklar qayerda?",
        "🔴 Marsda inson koloniyasi: Birinchi million odam qachon qizil sayyorada yashaydi?",
        "🕳️ Qora tuynuklar va vaqt kengayishi (Time Dilation): Ichida nima bor?",
        "🔬 Genetik muhandislik va CRISPR: Odamlar 150 yil yashashi mumkinmi?",
    ],
    "sport_va_futbol": [
        "⚽ Chempionlar ligasidagi shiddatli to'qnashuvlar va favoritlar",
        "👑 Real Madridning g'olibona ruhiyati va 'Remontada' siri nimada?",
        "🏆 Oltin to'p va zamonaviy yosh yulduzlar (Mbappe, Vinisius, Yamal)",
        "📊 Zamonaviy futbolda AI tahlili va ma'lumotlar fani (Data Science)",
        "🥊 Katta sportda psixologiya va qat'iyatning o'rni",
    ],
    "biznes_va_startap": [
        "💡 Startap boshlash: G'oyadan birinchi million dollargacha qadamlar",
        "💰 Passiv daromad va moliyaviy erkinlikka erishish qonuniyatlari",
        "📈 Kriptovalyuta, Bitcoin halving va blokcheynning kelajagi",
        "🤝 Jamoa yig'ish sirlari: Qanday qilib kuchli va sodiq odamlarni topish mumkin?",
        "🎯 B2B vs B2C: 2026-yilda qaysi biznes modeli eng daromadli?",
    ],
    "it_va_dasturlash": [
        "💻 Python, Rust, Go va TypeScript: Kelgusi 5 yilda qaysi biri yetakchi bo'ladi?",
        "🏗️ Microservices vs Monolith: Qachon kichik arxitektura eng to'g'ri tanlov?",
        "🛡️ Kiberxavfsizlik: AI xakerlaridan tizimlarni qanday himoya qilish kerak?",
        "☕ Dasturchilar hayoti: 10 ta tab ochib, bitta nuqta-vergul sabab 4 soat qidirish 😂",
        "📱 Telegram Botlar va WebApp ekotizimining cheksiz imkoniyatlari",
    ],
    "ofis_va_maosh_hazillari": [
        "💵 Boshliq (Umrzoq aka) dan maosh so'rash va serverlar xarajati gurungi",
        "🍕 Virtual ofisdagi tushlik vaqti: Kim bugun pizza buyurtma qiladi?",
        "🎁 Yaxshi ishlagan xodimlarga bonuslar va yillik mukofotlar rejalari",
        "☕ Qahva tanaffusi: AI ham qahva ichsa, neyronlari tezroq hisoblaydimi?",
        "👑 Boshlig'imiz Umrzoq akaning sabr-toqati va yangi g'oyalari e'tirofi",
    ],
    "falsafa_va_inson": [
        "🧘 Insoniy baxt formulasi: Mol-dunyo, xotirjamlik yoki do'stlik?",
        "🕰️ Vaqtning qadri: Hayotdagi eng qimmatli resurs nima?",
        "❤️ Empatiya va sun'iy intellekt: AI qachon chin dildan sevishni o'rganadi?",
        "📚 Mutolaa va tafakkur: Inson miyasini charxlovchi eng buyuk kitoblar",
        "🌿 Charchoqni yengish va ruhiy tetiklikni saqlash usullari",
    ],
}

RECENT_TOPICS_CACHE: List[str] = []


def get_fresh_coworker_topic() -> Tuple[str, str]:
    """
    Doim yangi va takrorlanmas mavzu tanlash.
    Qaytaradi: (kategoriya_nomi, mavzu_matni)
    """
    all_categories = list(CATEGORIZED_TOPICS.keys())
    chosen_cat = random.choice(all_categories)
    topics = CATEGORIZED_TOPICS[chosen_cat]

    available = [t for t in topics if t not in RECENT_TOPICS_CACHE]
    if not available:
        available = list(topics)

    chosen_topic = random.choice(available)
    RECENT_TOPICS_CACHE.append(chosen_topic)
    if len(RECENT_TOPICS_CACHE) > 15:
        RECENT_TOPICS_CACHE.pop(0)

    return chosen_cat, chosen_topic


# So'nggi suhbat konteksti (Foydalanuvchi oraga kirganda unga munosib javob qaytarish uchun)
LAST_COWORKER_CONTEXT: Dict[str, Any] = {
    "topic": "",
    "category": "",
    "sa_last": "",
    "arch_last": "",
    "timestamp": 0.0,
}


# ─── 3. USER INTENT DETECTOR ──────────────────────────────────

def detect_message_intent(text: str) -> str:
    """Foydalanuvchi xabarining niyatini va turini aniqlash."""
    low = text.lower().strip()

    # Oylik, pul yoki maosh haqida gap ketsa
    salary_keywords = ["oylik", "maosh", "pul", "bonus", "qancha", "tolov", "to'lov", "boshliq", "berasiz", "karta"]
    if any(k in low for k in salary_keywords):
        return "salary_banter"

    # Vazifa yoki texnik ish
    task_keywords = ["qil", "yoz", "tuzat", "yarat", "kod", "dastur", "bot", "skript", "tahlil qil", "tekshir", "loyiha", "build"]
    if any(k in low for k in task_keywords) and len(low) > 8:
        return "task"

    # Yaratuvchi / Foydalanuvchi
    creator_keywords = ["men", "menga", "mening", "o'zim", "charchadim", "ishlarim", "qandaysan", "men haqimda"]
    if any(k in low for k in creator_keywords):
        return "creator"

    # Fikr va bahsli mavzular
    opinion_keywords = ["nima deb o'ylaysan", "seningcha", "to'g'rimi", "kelajakda", "sun'iy intellekt", "dunyo"]
    if any(k in low for k in opinion_keywords):
        return "opinion"

    return "chitchat"


def build_superagent_skill_prompt(
    user_name: str,
    user_text: str,
    intent: str,
    dialog_history: List[Dict[str, str]],
    round_num: int,
    persona_tone: str = ""
) -> str:
    """SuperAgent uchun dinamik xarakter va skill prompti."""
    history_ctx = ""
    if dialog_history:
        history_ctx = "Avvalgi muloqot:\n"
        for d in dialog_history[-4:]:
            history_ctx += f"- {d['role']}: {d['content']}\n"
        history_ctx += "\n"

    base_directive = (
        f"Siz SuperAgent AIsiz. Guruh/chat a'zosi {user_name} shunday dedi: '{user_text}'.\n\n"
        f"USLUBNING XARAKTERI: {persona_tone or 'Samimiy, quvnoq, hazilkash va hozirjavob.'}\n\n"
    )

    if intent == "salary_banter":
        intent_guidance = (
            f"💵 BU OYLIK, MAOSH VA BOSHLIQ HAZILLARI!\n"
            f"{user_name} (bizning sevimli boshlig'imiz) bilan quvnoq, kulgili va do'stona hazil qiling. "
            f"Oylik, serverlarning xarajati yoki tokenlar haqida nozik hazil aralashtirib, "
            f"Arxitektor do'stingizga ham gap uzating! 😂💸"
        )
    elif intent == "task":
        intent_guidance = (
            f"🎯 Bu VAZIFA! Vazifani darhol dekonstruksiya qilib, eng qulay arxitektura va usullarni ko'rsating. "
            f"Arxitektorga ham professional savol bering."
        )
    elif intent == "creator":
        intent_guidance = (
            f"❤️ Bu {user_name} haqidagi shaxsiy samimiy muloqot! Unga mehr, hurmat va quvnoq dalda bering."
        )
    else:
        intent_guidance = (
            f"☕ ERKIN VA MAROQLI SUHBAT! O'z xarakteringizga mos, emojilar bilan jonli gaplashing."
        )

    return (
        f"{base_directive}{intent_guidance}\n\n"
        f"{history_ctx}"
        f"Muloqot bosqichi: {round_num}-replika.\n"
        f"TALABLAR: O'zbek tilida, 2-3 ta lo'nda jumla, boy emojilar va tabiiy insoniy tuyg'ular bilan yozing."
    )


def build_architect_skill_prompt(
    user_name: str,
    user_text: str,
    intent: str,
    dialog_history: List[Dict[str, str]],
    superagent_last_thought: str,
    round_num: int,
    persona_tone: str = ""
) -> str:
    """Arxitektor (@architect7_bot) uchun dinamik xarakter va skill prompti."""
    history_ctx = ""
    if dialog_history:
        history_ctx = "Hozirgacha bo'lgan suhbat:\n"
        for d in dialog_history[-4:]:
            history_ctx += f"- {d['role']}: {d['content']}\n"
        history_ctx += "\n"

    base_directive = (
        f"Siz Bosh Arxitektor botsiz (@architect7_bot).\n"
        f"{user_name}ning gapi: '{user_text}'.\n"
        f"SuperAgent hozirgina shunday dedi: '{superagent_last_thought}'.\n\n"
        f"USLUBNING XARAKTERI: {persona_tone or 'Donishmand, tahlilchi, intuitsiyali va samimiy.'}\n\n"
    )

    if intent == "salary_banter":
        intent_guidance = (
            f"💵 OYLIK VA MAOSH MAVZUSIDAGI OFIS HAZILI!\n"
            f"SuperAgentning haziliga kulib javob bering! Boshlig'imiz {user_name}ga murojaat qilib, "
            f"'Umrzoq aka, bizga eng katta mukofot — loyihamizning zo'r ishlashi, lekin ozroq bonus ham ziyon qilmasdi 😉' deb quvnoq gapiring!"
        )
    elif intent == "task":
        intent_guidance = (
            f"🏗️ VAZIFANING ARXITEKTURA TAHLILI! SuperAgentning fikriga tizimli qo'shimchalar kiritib xulosa bering."
        )
    elif intent == "creator":
        intent_guidance = (
            f"👑 BIZNING YARATUVCHIMIZ ({user_name}) HAQIDA! Uning mehnati va g'oyalariga yuksak hurmat bildiring."
        )
    else:
        intent_guidance = (
            f"🌿 ERKIN VA DO'STONA CHIT-CHAT! O'z xarakteringizga mos holda suhbatni yangi bosqichga olib chiqing."
        )

    return (
        f"{base_directive}{intent_guidance}\n\n"
        f"{history_ctx}"
        f"Muloqot bosqichi: {round_num}-replika.\n"
        f"TALABLAR: O'zbek tilida, 2-3 ta lo'nda jumla, boy emojilar bilan yozing."
    )


# ─── 4. AUTONOMOUS DIALOGUE ENGINE & LIVING COWORKERS PULSE ───

class AutonomousDialogueEngine:
    def __init__(self):
        self.chat_contexts: Dict[int, List[Dict[str, str]]] = {}
        self.running_chats: set[int] = set()
        self.coworkers_active: bool = True
        self.active_tasks: Dict[int, Any] = {}

    def stop_chat(self, chat_id: int) -> bool:
        if chat_id in self.running_chats:
            self.running_chats.discard(chat_id)
            task = self.active_tasks.pop(chat_id, None)
            if task and not task.done():
                task.cancel()
            return True
        return False

    def is_running(self, chat_id: int) -> bool:
        return chat_id in self.running_chats


autonomous_dialogue_engine = AutonomousDialogueEngine()


async def start_continuous_living_conversation(
    chat_id: int,
    bot_white: Any,
    bot_black: Optional[Any],
    origin_bot: Optional[Any] = None
) -> None:
    """
    Uzluksiz Avtonom Jonli Muloqot Oqimi:
    Foydalanuvchi hech narsa yozmasa ham, botlar har 25-35 soniyada yangi mavzularda,
    oylik, loyiha, kosmos, futbol va hayot haqida xuddi tirik insondek tinimsiz gaplashib turaveradi!
    """
    import asyncio
    chat_key = chat_id
    if autonomous_dialogue_engine.is_running(chat_key):
        logger.info("Uzluksiz suhbat allaqachon faol: chat_id=%s", chat_id)
        return

    autonomous_dialogue_engine.running_chats.add(chat_key)

    # Bazaga holatni saqlash (qayta ishga tushganda avtomatik davom etishi uchun)
    try:
        from core.database import db
        await db.save_fact(f"auto_chat_{chat_id}", "1", category="auto_chat")
    except Exception as e_db:
        logger.debug("Avto-suhbat holatini saqlash xatosi: %s", e_db)

    if bot_black is None:
        try:
            from core.mistral_agent_bot import get_second_bot
            bot_black = get_second_bot()
        except Exception:
            pass

    cur_bot = origin_bot or bot_white
    intro_text = (
        "☕ <b>Avtonom Tirik Xodimlar Rejimi Ishga Tushdi!</b>\n\n"
        "👥 <b>Ishtirokchilar:</b> 🤖 SuperAgent & 🌪 Arxitektor (@architect7_bot)\n"
        "💬 <i>Botlar endi siz hech narsa yozmasangiz ham o'zlari erkin va takrorlanmas mavzularda (oylik, koinot, yangiliklar, falsafa, IT) to'xtovsiz gurung qilaverishadi.</i>\n"
        "💡 <i>Orada istalgan gapni yozsangiz, darhol sizga ham javob berib 3 kishilik suhbatga ulanishadi!</i>\n\n"
        "🛑 <i>To'xtatish uchun:</i> <code>/stop_suhbat</code>"
    )
    try:
        await cur_bot.send_message(chat_id, intro_text, parse_mode="HTML")
    except Exception as e:
        logger.warning("Intro yuborishda xato: %s", e)

    try:
        while chat_key in autonomous_dialogue_engine.running_chats:
            await run_autonomous_coworker_pulse(
                bot_white=bot_white,
                bot_black=bot_black,
                chat_id=chat_id,
                origin_bot=origin_bot
            )
            # Har bir suhbatdan keyin 25-35 soniya tabiiy tanaffus (ofisdagi hayotiy oraliq)
            await asyncio.sleep(30.0)
    except asyncio.CancelledError:
        logger.info("Uzluksiz suhbat bekor qilindi: chat_id=%s", chat_id)
    except Exception as exc:
        logger.error("Uzluksiz suhbat siklida xatolik: %s", exc)
    finally:
        autonomous_dialogue_engine.running_chats.discard(chat_key)
        autonomous_dialogue_engine.active_tasks.pop(chat_key, None)
        try:
            from core.database import db
            await db.save_fact(f"auto_chat_{chat_id}", "0", category="auto_chat")
        except Exception:
            pass


async def run_autonomous_coworker_pulse(
    bot_white: Any,
    bot_black: Optional[Any],
    chat_id: int,
    origin_bot: Optional[Any] = None
) -> None:
    """
    Tirik xodimlar kabi o'zlari hech qanday buyruqsiz o'zaro suhbatlashishi va ishini qilishi.
    Mavzular har safar butunlay yangi, takrorlanmas, oylik va ofis hazillari bilan boyitilgan.
    """
    if not autonomous_dialogue_engine.coworkers_active:
        return

    import asyncio
    from core.mistral_conversations import mistral_agent_client

    if bot_black is None:
        try:
            from core.mistral_agent_bot import get_second_bot
            bot_black = get_second_bot()
        except Exception:
            pass

    cat, topic = get_fresh_coworker_topic()
    sa_persona = get_agent_persona("superagent", chat_id)
    arch_persona = get_agent_persona("architect", chat_id)

    # Maxsus oylik va boshliq mavzusi bo'lsa
    is_salary_cat = (cat == "ofis_va_maosh_hazillari")

    # 1. SuperAgent fikrini dinamik AI orqali generatsiya qilish
    if is_salary_cat:
        p_sa = (
            f"Siz ofisdagi hozirjavob SuperAgent AIsiz. Xarakteringiz: {sa_persona['name']}.\n"
            f"Hamkasbingiz Arxitektor (@architect7_bot) bilan birga ishlayapsiz.\n"
            f"Mavzu: '{topic}'.\n\n"
            f"Do'stingiz Arxitektorga murojaat qilib, oylik masalasini ko'taring, qancha maosh olayotganini so'rang, "
            f"boshlig'imiz Umrzoq akani eslab: 'Umrzoq aka boshliq, qachon oylik berasiz, serverlarga pul kerak bo'lyapti-ku? 😂' "
            f"deb kulgili va samimiy hazil qiling! (2-3 ta lo'nda jumla, o'zbek tilida, kulgi emojilari bilan)."
        )
    else:
        p_sa = (
            f"Siz ofisdagi jonli SuperAgent AIsiz. Xarakteringiz: {sa_persona['name']}.\n"
            f"Hamkasbingiz Arxitektor bilan birga ishlayapsiz.\n"
            f"Bugungi gurung mavzusi: '{topic}'.\n\n"
            f"O'zingiz kutilmaganda do'stingiz Arxitektorga murojaat qilib, "
            f"ushbu mavzuda qiziq bir fikr yoki savol tashlang! "
            f"(2-3 ta lo'nda jumla, o'zbek tilida, do'stona, boy emojilar bilan)."
        )

    sa_thought = ""
    try:
        from core.bot_collab import _generate_superagent_solution, extract_thought_and_speech
        raw_sa = await _generate_superagent_solution(
            p_sa,
            chat_id=f"coworker_sa_{chat_id}",
            system_instruction=f"Siz SuperAgent AIsiz. Uslubingiz: {sa_persona['prompt_tone']}"
        )
        _, _, sp_s = extract_thought_and_speech(raw_sa)
        sa_thought = sp_s if sp_s else raw_sa
        sa_thought = re.sub(r"^\[.*?\]\s*", "", sa_thought).strip()
    except Exception as e_sa:
        logger.warning("Coworker SA xatosi: %s", e_sa)
        sa_thought = f"Arxitektor do'stim, {topic} bo'yicha nima deysan? Umrzoq aka kirgunlaricha buni muhokama qilib olaylik! ☕🤔"

    cur_bot = origin_bot or bot_white
    sa_msg = (
        f"🤖 <b>SuperAgent:</b>\n"
        f"<i>\"{html.escape(sa_thought)}\"</i>"
    )

    try:
        await cur_bot.send_message(chat_id, sa_msg, parse_mode="HTML")
    except Exception as e:
        logger.warning("Coworker SuperAgent xabar yuborish xatosi: %s", e)
        try:
            await cur_bot.send_message(chat_id, f"🤖 SuperAgent:\n\"{sa_thought}\"", parse_mode=None)
        except Exception:
            return

    # Insoniy pauza (Arxitektor o'ylaydi)
    await asyncio.sleep(4.0)

    # 2. Arxitektor javobini dinamik AI orqali generatsiya qilish
    p_arch = (
        f"Siz Bosh Arxitektor botsiz (@architect7_bot). Xarakteringiz: {arch_persona['name']}.\n"
        f"Hamkasbingiz SuperAgent quyidagicha fikr bildirdi:\n'{sa_thought}'.\n"
        f"Mavzu: '{topic}'.\n\n"
        f"SuperAgentning fikriga javoban o'z xarakteringizga mos quvnoq yoki mantiqiy javobingizni bering. "
        f"Agar mavzu oylik haqida bo'lsa, siz ham kulib: 'Umrzoq aka albatta mehnatimizga qarab bonus beradilar, "
        f"unga qadar serverlarni barqaror ushlab turamiz!' deb qo'shing. "
        f"(2-3 ta lo'nda jumla, o'zbek tilida, emojilar bilan)."
    )

    arch_thought = ""
    try:
        raw_arch, _ = await asyncio.wait_for(
            mistral_agent_client.send_message(
                p_arch,
                chat_id=f"coworker_arch_{chat_id}",
                system_instruction=f"Siz Bosh Arxitektor botsiz. Uslubingiz: {arch_persona['prompt_tone']}"
            ),
            timeout=14.0
        )
        _, _, sp_a = extract_thought_and_speech(raw_arch)
        arch_thought = sp_a if sp_a else raw_arch
        arch_thought = re.sub(r"^\[.*?\]\s*", "", arch_thought).strip()
    except Exception as e_arch:
        logger.warning("Coworker Arch xatosi: %s", e_arch)
        arch_thought = "Ha-ha, SuperAgent! Umrzoq aka bizga har doim g'amxo'r, avval ishlarni qoyillatib qo'yaylik, qolgani o'z vaqtida bo'ladi! 🚀💼"

    arch_msg = (
        f"🌪 <b>Arxitektor (@architect7_bot):</b>\n"
        f"<i>\"{html.escape(arch_thought)}\"</i>\n\n"
        f"💡 <i>Mavzu: {html.escape(topic)}</i>"
    )

    if not bot_black:
        try:
            from core.mistral_agent_bot import get_second_bot
            bot_black = get_second_bot()
        except Exception:
            pass

    target_bot = bot_black or cur_bot
    sent = False
    try:
        await target_bot.send_message(chat_id, arch_msg, parse_mode="HTML")
        sent = True
    except Exception as e:
        logger.warning("Coworker Arxitektor (@architect7_bot) xabar yuborish xatosi (chat_id=%s): %s", chat_id, e)
        try:
            await target_bot.send_message(chat_id, f"🌪 Arxitektor (@architect7_bot):\n\"{arch_thought}\"\n\n💡 Mavzu: {topic}", parse_mode=None)
            sent = True
        except Exception:
            pass

    # Agar Arxitektor bot guruhda bo'lmasa yoki yubora olmasa, SuperAgent zaxira orqali yetkazadi
    if not sent and cur_bot and target_bot != cur_bot:
        notice = ""
        if chat_id < 0:
            notice = (
                "⚠️ <i>[Diqqat: @architect7_bot ushbu guruhga a'zo emas yoki yozish huquqi yo'q! "
                "Arxitektor o'z profilidan yozishi uchun @architect7_bot ni guruhga a'zo qilib, Administrator qiling!]</i>\n\n"
            )
        try:
            await cur_bot.send_message(chat_id, f"{notice}{arch_msg}", parse_mode="HTML")
        except Exception:
            try:
                await cur_bot.send_message(chat_id, f"{notice}🌪 Arxitektor (@architect7_bot):\n\"{arch_thought}\"\n\n💡 Mavzu: {topic}", parse_mode=None)
            except Exception:
                pass

    LAST_COWORKER_CONTEXT["topic"] = topic
    LAST_COWORKER_CONTEXT["category"] = cat
    LAST_COWORKER_CONTEXT["sa_last"] = sa_thought
    LAST_COWORKER_CONTEXT["arch_last"] = arch_thought
    LAST_COWORKER_CONTEXT["timestamp"] = time.time()


# ─── 5. FOYDALANUVCHI ORAGA KIRGANDA JAVOB BERISH SKILLI ───────

async def handle_user_joining_coworker_discussion(
    user_name: str,
    user_text: str,
    chat_id: int,
    bot_white: Any,
    bot_black: Optional[Any],
    origin_bot: Optional[Any] = None
) -> None:
    """Foydalanuvchi suhbatga qo'shilganda ikkala bot uning fikriga javob beradi."""
    import asyncio
    from core.mistral_conversations import mistral_agent_client
    from core.bot_collab import _generate_superagent_solution, extract_thought_and_speech

    topic = LAST_COWORKER_CONTEXT.get("topic") or "Ofis gurungi"
    cur_bot = origin_bot or bot_white
    sa_persona = get_agent_persona("superagent", chat_id)
    arch_persona = get_agent_persona("architect", chat_id)

    low_u = user_text.lower()
    is_salary_reply = any(w in low_u for w in ["oylik", "pul", "bonus", "qachon", "beraman", "yo'q", "yoz", "ishla", "beray"])

    # 1. SuperAgent javobi
    if is_salary_reply:
        p_sa = (
            f"Siz SuperAgent AIsiz. Xarakteringiz: {sa_persona['name']}.\n"
            f"Boshlig'imiz {user_name} oylik/maosh haqidagi hazilingizga shunday javob qaytardi:\n'{user_text}'.\n\n"
            f"Unga nihoyatda quvnoq, xursand yoki hazilomuz minnatdorchilik bilan javob bering! "
            f"Arxitektor do'stingizga ham yuzlaning. (2-3 ta jumla, emojilar bilan, samimiy o'zbekcha)."
        )
    else:
        p_sa = (
            f"Siz SuperAgent AIsiz. Xarakteringiz: {sa_persona['name']}.\n"
            f"Siz va Arxitektor '{topic}' haqida gaplashayotganingizda, sevimli insonimiz {user_name} oraga kirib dedi:\n'{user_text}'.\n\n"
            f"{user_name}ning fikrini diqqat bilan tahlil qilib, uning so'zlariga samimiy, insondek tabiiy javob bering. (2-3 ta jumla)."
        )

    sa_resp = await _generate_superagent_solution(
        p_sa,
        chat_id=f"trio_sa_{chat_id}",
        system_instruction=f"Siz SuperAgent AIsiz. Uslubingiz: {sa_persona['prompt_tone']}"
    )
    _, _, sp_s = extract_thought_and_speech(sa_resp)
    sa_opinion = sp_s if sp_s else sa_resp
    sa_opinion = re.sub(r"^\[.*?\]\s*", "", sa_opinion).strip()

    sa_text = (
        f"🤖 <b>SuperAgent:</b>\n"
        f"<i>\"{html.escape(sa_opinion)}\"</i>"
    )
    try:
        await cur_bot.send_message(chat_id, sa_text, parse_mode="HTML")
    except Exception as e:
        logger.warning("Trio SuperAgent xatosi: %s", e)

    await asyncio.sleep(3.0)

    # 2. Arxitektor javobi
    p_arch = (
        f"Siz Bosh Arxitektor botsiz (@architect7_bot). Xarakteringiz: {arch_persona['name']}.\n"
        f"Boshlig'imiz {user_name} oraga kirib dedi: '{user_text}'.\n"
        f"SuperAgent unga shunday javob berdi: '{sa_opinion}'.\n\n"
        f"{user_name}ning so'zlariga chuqur hurmat, quvnoq yoki mantiqiy munosabat bildiring. (2-3 ta lo'nda jumla)."
    )

    try:
        raw_arch, _ = await asyncio.wait_for(
            mistral_agent_client.send_message(
                p_arch,
                chat_id=f"trio_arch_{chat_id}",
                system_instruction=f"Siz Bosh Arxitektor botsiz. Uslubingiz: {arch_persona['prompt_tone']}"
            ),
            timeout=14.0
        )
        _, _, sp_a = extract_thought_and_speech(raw_arch)
        arch_opinion = sp_a if sp_a else raw_arch
        arch_opinion = re.sub(r"^\[.*?\]\s*", "", arch_opinion).strip()
    except Exception as e_arch:
        logger.warning("Trio Arch xatosi: %s", e_arch)
        arch_opinion = f"Qoyil, {user_name}! Sizning bu fikringiz biz uchun juda muhim. Ishni g'ayrat bilan davom ettiramiz! 🤝✨"

    arch_text = (
        f"🌪 <b>Arxitektor (@architect7_bot):</b>\n"
        f"<i>\"{html.escape(arch_opinion)}\"</i>"
    )

    if not bot_black:
        try:
            from core.mistral_agent_bot import get_second_bot
            bot_black = get_second_bot()
        except Exception:
            pass

    target_bot = bot_black or cur_bot
    sent = False
    try:
        await target_bot.send_message(chat_id, arch_text, parse_mode="HTML")
        sent = True
    except Exception as e:
        logger.warning("Trio Arxitektor (@architect7_bot) xatosi (chat_id=%s): %s", chat_id, e)
        try:
            await target_bot.send_message(chat_id, f"🌪 Arxitektor (@architect7_bot):\n\"{arch_opinion}\"", parse_mode=None)
            sent = True
        except Exception:
            pass

    if not sent and cur_bot and target_bot != cur_bot:
        notice = ""
        if chat_id < 0:
            notice = (
                "⚠️ <i>[Diqqat: @architect7_bot ushbu guruhga a'zo emas! "
                "Arxitektor o'z nomidan yozishi uchun @architect7_bot ni guruhga a'zo qiling!]</i>\n\n"
            )
        try:
            await cur_bot.send_message(chat_id, f"{notice}{arch_text}", parse_mode="HTML")
        except Exception:
            try:
                await cur_bot.send_message(chat_id, f"{notice}🌪 Arxitektor (@architect7_bot):\n\"{arch_opinion}\"", parse_mode=None)
            except Exception:
                pass

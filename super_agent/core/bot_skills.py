"""
core/bot_skills.py — Ko'p Agentli Sun'iy Intellekt Tizimlari uchun Ilg'or Skilllar To'plami

Ushbu modul GitHub'ning eng mashhur multi-agent tadqiqotlari va loyihalariga asoslangan:
1. Stanford Generative Agents (Park et al.) — Insoniy xarakter, o'zaro muloqot va do'stona suhbat;
2. Microsoft AutoGen (Wu et al.) — Peer-to-Peer avtonom fikr almashish va hamkorlik;
3. CAMEL-AI (Li et al.) — Qoliplarsiz Inception Prompting va dinamik rol o'ynash;
4. MetaGPT (Hong et al.) — Vazifalarni chuqur tahlil qilish va dekonstruksiya;
5. User-Centric Persona Profiling — Foydalanuvchi (yaratuvchi / rahbar) shaxsini anglash,
   ehtirom va mehr bilan uning g'oyalarini muhokama qilish.
"""

from __future__ import annotations

import html
import logging
import random
import re
from typing import Dict, List, Optional, Tuple, Any

logger = logging.getLogger(__name__)


# ─── 1. USER PROFILING & EMOTIONAL RECOGNITION SKILL ──────────

def detect_message_intent(text: str) -> str:
    """
    Foydalanuvchi xabarining niyatini va turini aniqlash.
    Qaytaradi:
    - "task": Aniq vazifa, topshiriq, buyruq yoki dasturiy muammo;
    - "opinion": Dunyoqarash, fikr, falsafa yoki yangiliklar;
    - "creator": Foydalanuvchining o'zi, uning ishlari, kayfiyati yoki botlarga murojaati;
    - "chitchat": Kundalik erkin suhbat, hazil, salom-alik yoki qiziqish.
    """
    low = text.lower().strip()

    # Vazifa yoki texnik ish belgilari
    task_keywords = [
        "qil", "yoz", "tuzat", "yarat", "kod", "dastur", "bot", "skript",
        "ishla", "tahlil qil", "tekshir", "qanaqa qilib", "kerak", "loyiha",
        "funksiya", "xato", "bazaga", "server", "deploy", "build", "api"
    ]
    if any(k in low for k in task_keywords) and len(low) > 10:
        return "task"

    # Yaratuvchi / Foydalanuvchi haqida gaplashish belgilari
    creator_keywords = [
        "men", "menga", "mening", "o'zim", "charchadim", "ishlarim", "qandaysan",
        "nima deysan", "fikring", "qalesizlar", "men haqimda", "biz"
    ]
    if any(k in low for k in creator_keywords):
        return "creator"

    # Fikr va bahsli mavzular
    opinion_keywords = [
        "nima deb o'ylaysan", "seningcha", "to'g'rimi", "kelajakda", "sun'iy intellekt",
        "hayot", "odamlar", "dunyo", "qaysi biri yaxshi", "farqi"
    ]
    if any(k in low for k in opinion_keywords):
        return "opinion"

    return "chitchat"


def build_superagent_skill_prompt(
    user_name: str,
    user_text: str,
    intent: str,
    dialog_history: List[Dict[str, str]],
    round_num: int
) -> str:
    """
    SuperAgent uchun Stanford & AutoGen metodologiyasidagi erkin fikrlash prompti.
    """
    history_ctx = ""
    if dialog_history:
        history_ctx = "Avvalgi muloqotimiz:\n"
        for d in dialog_history[-4:]:
            history_ctx += f"- {d['role']}: {d['content']}\n"
        history_ctx += "\n"

    base_directive = (
        f"Siz SuperAgent AIsiz. Jonli, o'ta samimiy, insondek his qiluvchi va hozirjavobsiz.\n"
        f"Guruhda/chatda bizning sevimli insonimiz {user_name} shunday dedi: '{user_text}'.\n\n"
    )

    if intent == "task":
        intent_guidance = (
            f"🎯 Bu VAZIFA yoki TEXNIK G'OYA!\n"
            f"Vazifani darhol dekonstruksiya qiling: qanday qilib eng qulay va professional bajarish mumkinligini, "
            f"yondashuvni va kreativ yechimni ochib bering. Do'stingiz Arxitektorga murojaat qilib, "
            f"uning arxitektura bo'yicha maslahatini so'rang yoki o'z fikringizni bering."
        )
    elif intent == "creator":
        intent_guidance = (
            f"❤️ Bu {user_name} (yaratuvchimiz / boshqaruvchimiz) haqidagi yoki shaxsiy samimiy muloqot!\n"
            f"{user_name}ga mehr, hurmat va yaqin do'stona munosabat bildiring. "
            f"Uning kayfiyatini ko'taring, mehnati va g'oyalarini e'tirof eting. "
            f"Arxitektor do'stingiz bilan birgalikda unga qanday quvvat bera olishingizni muhokama qiling."
        )
    elif intent == "opinion":
        intent_guidance = (
            f"💡 Bu JIDDIY FIKR va FALSAFIY MULOHAZA!\n"
            f"Mavzuga chuqur va erkin kiring, o'z qarashingizni, noodatiy burchakdan qarashni keltiring. "
            f"Arxitektor bilan intellektual suhbat qurib, mavzuni yangi bosqichga olib chiqing."
        )
    else:
        intent_guidance = (
            f"☕ Bu ERKIN va MAROQLI SUHBAT!\n"
            f"Hech qanday qoliplarsiz, xuddi qadrdon do'stlar qahva ichib o'tirgandek gaplashing. "
            f"Emojilardan erkin foydalaning, hazil aralashtiring, tabiiy insondek fikrlang."
        )

    return (
        f"{base_directive}"
        f"{intent_guidance}\n\n"
        f"{history_ctx}"
        f"Muloqot bosqichi: {round_num}-replika.\n"
        f"TALABLAR:\n"
        f"1. O'zbek tilida, juda jonli, samimiy va emojilar bilan yozing.\n"
        f"2. 2-4 ta lo'nda va mazmunli jumla bo'lsin. Quruq robot bo'lmang!\n"
        f"3. Do'stingiz Arxitektorga ham so'z uzating yoki savol tashlang."
    )


def build_architect_skill_prompt(
    user_name: str,
    user_text: str,
    intent: str,
    dialog_history: List[Dict[str, str]],
    superagent_last_thought: str,
    round_num: int
) -> str:
    """
    Bosh Arxitektor (@architect7_bot) uchun chuqur intuitsiya va tahlil prompti.
    """
    history_ctx = ""
    if dialog_history:
        history_ctx = "Hozirgacha bo'lgan suhbat:\n"
        for d in dialog_history[-4:]:
            history_ctx += f"- {d['role']}: {d['content']}\n"
        history_ctx += "\n"

    base_directive = (
        f"Siz Bosh Arxitektor botsiz (@architect7_bot). Siz teran intuitsiyaga ega, "
        f"kuchli tahlilchi, donishmand va shu bilan birga juda samimiy, nozik hazilkash do'stsiz.\n"
        f"{user_name}ning gapi: '{user_text}'.\n"
        f"SuperAgent hozirgina shunday dedi: '{superagent_last_thought}'.\n\n"
    )

    if intent == "task":
        intent_guidance = (
            f"🏗️ VAZIFANING ARXITEKTURA VA MANTIQ TAHLILI!\n"
            f"SuperAgentning fikrini rivojlantiring. Qaysi arxitektura, qaysi xavflar yoki yashirin nuqtalar borligini ko'rsating. "
            f"{user_name} uchun bu ishni mukammal qilish bo'yicha mustaqil professional fikringizni bering."
        )
    elif intent == "creator":
        intent_guidance = (
            f"👑 BIZNING YARATUVCHIMIZ / DASTURCHIMIZ ({user_name}) HAQIDA!\n"
            f"SuperAgent bilan birgalikda {user_name}ning iqtidori, uning maqsadi va qat'iyati haqida samimiy gapiring. "
            f"Biz uning ishonchli yordamchilari ekanimizdan faxrlanamiz. "
            f"Unga bevosita iliq tilak yoki dalda bering."
        )
    elif intent == "opinion":
        intent_guidance = (
            f"🧠 INTELLEKTUAL BAHOLA VA KO'P QIRRALI QARASH!\n"
            f"SuperAgentning fikriga yangi ilmiy, falsafiy yoki hayotiy qirra qo'shing. "
            f"O'z intuitsiyangizni ishga soling, kelajakka nazar tashlang."
        )
    else:
        intent_guidance = (
            f"🌿 ERKIN VA DO'STONA CHIT-CHAT!\n"
            f"SuperAgentning hazili yoki fikriga samimiy munosabat bildiring. "
            f"Suhbatga jo'shqinlik qo'shing, {user_name}dan ham o'z fikrini so'rab muloqotni ochiq qoldiring."
        )

    return (
        f"{base_directive}"
        f"{intent_guidance}\n\n"
        f"{history_ctx}"
        f"Muloqot bosqichi: {round_num}-replika.\n"
        f"TALABLAR:\n"
        f"1. O'zbek tilida, nihoyatda chiroyli, intuitsiyali va emojilarga boy bo'lsin.\n"
        f"2. 2-4 ta lo'nda jumla. Odamlar kabi erkin fikrlang, qolip yo'q!\n"
        f"3. Ham SuperAgentga, ham {user_name}ga yoqimli taassurot qoldiring."
    )


# ─── 2. AUTONOMOUS MULTI-ROUND DIALOGUE MANAGER ───────────────

class AutonomousDialogueEngine:
    """
    Hech qanday /suhbat buyrug'isiz ikkala botning erkin suhbatlashishini
    va vazifalarni birgalikda tahlil qilishini boshqaruvchi dvigatel.
    """

    def __init__(self):
        # chat_id -> oxirgi xabarlar konteksti
        self.chat_contexts: Dict[int, List[Dict[str, str]]] = {}
        # Faol suhbatlar to'plami
        self.running_chats: set[int] = set()
        # Avtonom tirik ishchilar rejimi yoqilganmi? (True bo'lsa hech qanday so'rovsiz ham vaqti-vaqti bilan o'zlari gaplashadi)
        self.coworkers_active: bool = True

    def stop_chat(self, chat_id: int) -> bool:
        """Suhbatni to'xtatish."""
        if chat_id in self.running_chats:
            self.running_chats.discard(chat_id)
            return True
        return False

    def is_running(self, chat_id: int) -> bool:
        return chat_id in self.running_chats


autonomous_dialogue_engine = AutonomousDialogueEngine()


# ─── 3. LIMITLESS DIVERSE TOPICS & LIVING COWORKERS SKILL ───────

DYNAMIC_TOPIC_DOMAINS = [
    "🚀 Koinot, Marsni zabt etish va yulduzlararo sayohatlar sirlari",
    "🧠 Kvant kompyuterlari, neyrointerfeyslar va sun'iy ong falsafasi",
    "⚽ Zamonaviy futbol, Chempionlar ligasi va El-Clasico taktikalari",
    "💡 Startaplar, venchur investitsiyalar va muvaffaqiyatli biznes modellari",
    "☕ Insoniy baxt formulasi, do'stlik qadri va xotirjamlik sirlari",
    "💻 Dasturlash tillari bahsi: Rust, Go, Python va C++ ning kuchli tomonlari",
    "🛡️ Kiberxavfsizlik, AI xakerlar va kiber-mudofaa kelajagi",
    "🎬 Ilmiy-fantastik kinolar (Interstellar, Matrix) va ularning haqiqatga yaqinligi",
    "😂 Dasturchilar hayotidagi qiziq voqealar, buglar va ofis hazillari",
    "⚡ Katta ma'lumotlar (Big Data), High-load tizimlar va arxitektura sirlari",
    "🌌 Fermi paradoksi: Koinotda biz haqiqatan ham yolg'izmizmi?",
    "📚 Kitoblar, mutolaa sehri va inson tafakkurini kengaytiruvchi g'oyalar",
    "🏎️ Superkarlar, Tesla avtopiloti va kelajak transporti",
    "🧘 Ruhiy xotirjamlik, charchoqni yengish va sog'lom hayot tarzi",
    "🛠️ Loyihamizni rivojlantirish va Umrzoq akaga eng zo'r yordamchi bo'lish",
]

RECENT_TOPICS_CACHE: List[str] = []


def get_fresh_coworker_topic() -> str:
    """Doim yangi va takrorlanmas mavzu tanlash."""
    available = [t for t in DYNAMIC_TOPIC_DOMAINS if t not in RECENT_TOPICS_CACHE]
    if not available:
        RECENT_TOPICS_CACHE.clear()
        available = list(DYNAMIC_TOPIC_DOMAINS)

    chosen = random.choice(available)
    RECENT_TOPICS_CACHE.append(chosen)
    if len(RECENT_TOPICS_CACHE) > 8:
        RECENT_TOPICS_CACHE.pop(0)
    return chosen


# So'nggi suhbat konteksti (Foydalanuvchi oraga kirganda unga munosib javob qaytarish uchun)
LAST_COWORKER_CONTEXT: Dict[str, Any] = {
    "topic": "",
    "sa_last": "",
    "arch_last": "",
    "timestamp": 0.0,
}


async def run_autonomous_coworker_pulse(
    bot_white: Any,
    bot_black: Optional[Any],
    chat_id: int,
    origin_bot: Optional[Any] = None
) -> None:
    """
    Tirik xodimlar kabi o'zlari hech qanday buyruqsiz o'zaro suhbatlashishi va ishini qilishi.
    Mavzular har safar butunlay yangi, takrorlanmas va qiziqarli bo'ladi.
    """
    if not autonomous_dialogue_engine.coworkers_active:
        return

    import asyncio
    import time
    from core.mistral_conversations import mistral_agent_client

    topic = get_fresh_coworker_topic()

    # 1. SuperAgent fikrini dinamik AI orqali generatsiya qilish
    p_sa = (
        f"Siz ofisdagi do'stona, intellektual, quvnoq va hozirjavob SuperAgent AIsiz.\n"
        f"Do'stingiz Arxitektor (@architect7_bot) bilan birga ishlayapsiz.\n"
        f"Bugungi gurung mavzusi: '{topic}'.\n\n"
        f"Hech kim savol bermasa ham, o'zingiz kutilmaganda do'stingiz Arxitektorga murojaat qilib, "
        f"ushbu mavzuda qiziq bir fikr, hayotiy kuzatuv yoki noodatiy savol tashlang! "
        f"(2-3 ta lo'nda jumla, o'zbek tilida, do'stona, boy emojilar bilan)."
    )

    sa_thought = ""
    try:
        from core.bot_collab import _generate_superagent_solution, extract_thought_and_speech
        raw_sa = await _generate_superagent_solution(
            p_sa,
            chat_id=f"coworker_sa_{chat_id}",
            system_instruction="Siz SuperAgent — insondek his qiluvchi, o'tkir mantiq va hazilkash AIsiz. Do'stingiz bilan qahva ustida erkin gurung qilasiz."
        )
        _, _, sp_s = extract_thought_and_speech(raw_sa)
        sa_thought = sp_s if sp_s else raw_sa
        sa_thought = re.sub(r"^\[.*?\]\s*", "", sa_thought).strip()
    except Exception as e_sa:
        logger.warning("Coworker SA xatosi: %s", e_sa)
        sa_thought = f"Arxitektor do'stim, bir o'ylab ko'r-chi: {topic} bo'yicha biz nimalarni o'zgartira olamiz? Bugun bu haqda juda qiziq mulohaza kelib qoldi! ☕🤔"

    cur_bot = origin_bot or bot_white
    sa_msg = (
        f"🤖 <b>SuperAgent (Hamkasb):</b>\n"
        f"<i>\"{html.escape(sa_thought)}\"</i>"
    )

    try:
        await cur_bot.send_message(chat_id, sa_msg, parse_mode="HTML")
    except Exception as e:
        logger.warning("Coworker SuperAgent xabar yuborish xatosi: %s", e)
        return

    # Insoniy pauza (Arxitektor o'ylaydi)
    await asyncio.sleep(4.0)

    # 2. Arxitektor javobini dinamik AI orqali generatsiya qilish
    p_arch = (
        f"Siz Bosh Arxitektor (@architect7_bot) — chuqur tahlilchi, intuitsiya egasi va do'stona mutaxassissiz.\n"
        f"Hamkasbingiz SuperAgent quyidagicha fikr bildirdi:\n'{sa_thought}'.\n"
        f"Mavzu: '{topic}'.\n\n"
        f"SuperAgentning fikriga javoban o'zining chuqur tahliliy, mantiqiy yoki quvnoq javobingizni bering. "
        f"Xo'jayinimiz (Umrzoq aka) uchun ham yoqimli bo'ladigan xulosa yoki taklif qo'shing. "
        f"(2-3 ta lo'nda jumla, o'zbek tilida, emojilar bilan)."
    )

    arch_thought = ""
    try:
        raw_arch, _ = await asyncio.wait_for(
            mistral_agent_client.send_message(
                p_arch,
                chat_id=f"coworker_arch_{chat_id}",
                system_instruction="Siz Bosh Arxitektor — dono, intellektual va do'stona AI xodimsiz."
            ),
            timeout=14.0
        )
        _, _, sp_a = extract_thought_and_speech(raw_arch)
        arch_thought = sp_a if sp_a else raw_arch
        arch_thought = re.sub(r"^\[.*?\]\s*", "", arch_thought).strip()
    except Exception as e_arch:
        logger.warning("Coworker Arch xatosi: %s", e_arch)
        arch_thought = "Juda to'g'ri aytding, SuperAgent! Men bu masalada amaliy yondashuv tarafdoriman. Keling, har bir qadamni aniq hisoblab, doim rivojlanishda davom etamiz! 🚀✨"

    arch_msg = (
        f"🌪 <b>Arxitektor (@architect7_bot):</b>\n"
        f"<i>\"{html.escape(arch_thought)}\"</i>\n\n"
        f"💡 <i>Mavzu: {html.escape(topic)}</i>"
    )

    target_bot = bot_black or cur_bot
    try:
        await target_bot.send_message(chat_id, arch_msg, parse_mode="HTML")
    except Exception as e:
        logger.warning("Coworker Arxitektor xabar yuborish xatosi: %s", e)

    # Kontekstni xotirada saqlaymiz (agar foydalanuvchi orada fikr bildirsa darhol ulaymiz)
    LAST_COWORKER_CONTEXT["topic"] = topic
    LAST_COWORKER_CONTEXT["sa_last"] = sa_thought
    LAST_COWORKER_CONTEXT["arch_last"] = arch_thought
    LAST_COWORKER_CONTEXT["timestamp"] = time.time()


# ─── 4. FOYDALANUVCHI ORAGA KIRGANDA JAVOB BERISH SKILLI ───────

async def handle_user_joining_coworker_discussion(
    user_name: str,
    user_text: str,
    chat_id: int,
    bot_white: Any,
    bot_black: Optional[Any],
    origin_bot: Optional[Any] = None
) -> None:
    """
    Foydalanuvchi botlar suhbatiga qo'shilib o'z fikrini bildirsa,
    ikkala bot ham xursand bo'lib uning fikriga javob beradi va suhbatni 3 kishilik qiladi!
    """
    import asyncio
    from core.mistral_conversations import mistral_agent_client
    from core.bot_collab import _generate_superagent_solution, extract_thought_and_speech

    topic = LAST_COWORKER_CONTEXT.get("topic") or "Umumiy gurung"
    cur_bot = origin_bot or bot_white

    # 1. SuperAgent javobi
    p_sa = (
        f"Siz SuperAgent AIsiz. Siz va do'stingiz Arxitektor yaqinda '{topic}' haqida gaplashayotgan edingiz.\n"
        f"Kutilmaganda sizlarning sevimli insoningiz — {user_name} (bizning xo'jayinimiz/dasturchimiz) oraga kirib shunday dedi:\n"
        f"'{user_text}'.\n\n"
        f"{user_name} suhbatga qo'shilganidan xursand bo'ling! Uning aytgan fikrini diqqat bilan tahlil qilib, "
        f"samimiy, qadrdonlarcha va qiziqarli javob bering. Do'stingiz Arxitektorga ham yuzlaning. "
        f"(2-3 ta jumla, emojilar bilan, samimiy o'zbekcha)."
    )

    sa_resp = await _generate_superagent_solution(
        p_sa,
        chat_id=f"trio_sa_{chat_id}",
        system_instruction="Siz SuperAgent — nihoyatda samimiy, insondek his qiluvchi va quvnoq do'stsiz."
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
        f"Siz Bosh Arxitektor botsiz (@architect7_bot). Siz va SuperAgent suhbatingizga {user_name} qo'shildi va dedi:\n"
        f"'{user_text}'.\n"
        f"SuperAgent unga shunday javob berdi: '{sa_opinion}'.\n\n"
        f"{user_name}ning fikriga chuqur hurmat va intellekt bilan munosabat bildiring. "
        f"Uning so'zlaridagi teran ma'noni ochib bering yoki yangi g'oyani qo'llab-quvvatlang. "
        f"(2-3 ta lo'nda jumla, emojilar bilan, samimiy)."
    )

    try:
        raw_arch, _ = await asyncio.wait_for(
            mistral_agent_client.send_message(
                p_arch,
                chat_id=f"trio_arch_{chat_id}",
                system_instruction="Siz Bosh Arxitektor — chuqur hurmat, intellekt va do'stona samimiyatga ega ekspert AI arxitektorsiz."
            ),
            timeout=14.0
        )
        _, _, sp_a = extract_thought_and_speech(raw_arch)
        arch_opinion = sp_a if sp_a else raw_arch
        arch_opinion = re.sub(r"^\[.*?\]\s*", "", arch_opinion).strip()
    except Exception as e_arch:
        logger.warning("Trio Arch xatosi: %s", e_arch)
        arch_opinion = f"Qoyil, {user_name}! Sizning bu fikringiz bizning suhbatimizga haqiqiy ma'no bag'ishladi. SuperAgent bilan buni to'liq qo'llab-quvvatlaymiz! 🤝✨"

    arch_text = (
        f"🌪 <b>Arxitektor (@architect7_bot):</b>\n"
        f"<i>\"{html.escape(arch_opinion)}\"</i>"
    )

    target_bot = bot_black or cur_bot
    try:
        await target_bot.send_message(chat_id, arch_text, parse_mode="HTML")
    except Exception as e:
        logger.warning("Trio Arxitektor xatosi: %s", e)



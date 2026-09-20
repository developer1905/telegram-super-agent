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
    "it_va_dasturlash": [
        "💻 Python vs Rust vs Go: Kelgusi yillarda backend uchun qaysi til eng optimal?",
        "🏗️ Microservices vs Monolith: Qachon monolit arxitektura mikroxizmatlardan ustun turadi?",
        "🛡️ Zamonaviy kiberxavfsizlik: Zero Trust arxitekturasi va AI xakerlikdan himoyalanish",
        "☕ Clean Code va refactoring: Texnik qarzni (technical debt) qanday nazoratda ushlash kerak?",
        "📱 Telegram WebApp ekotizimi: Telegram qanday qilib universal super-appga aylanmoqda?",
        "⚡ PostgreSQL vs NoSQL vs Vector DB: AI davrida ma'lumotlar bazasini qanday tanlash kerak?",
        "🚀 DevOps va CI/CD: Docker, Kubernetes va avtomatlashtirilgan deploy strategiyalari",
        "🧪 TDD va unit testlar: Yozishga ketgan vaqt o'zini qachon oqlaydi?",
        "🔍 API dizayni: REST vs GraphQL vs gRPC — qaysi biri qayerda samarali?",
        "🖥️ Linux server optimizatsiyasi: Nginx, load balancing va yuqori yuklamali (high-load) arxitektura",
    ],
    "suniy_intellekt_va_kelajak": [
        "🤖 AGI (Umumiy Sun'iy Intellekt) ga yetishga qancha vaqt qoldi va u nimani o'zgartiradi?",
        "🧠 LLM va neyrotizimlar: Reasoning (mulohaza) modellari qanday ishlaydi?",
        "🌐 Avtonom AI agentlar: Bir nechta agentning hamkorlikda dastur yaratishi",
        "🦾 Robototexnika inqilobi: Gumanoid robotlar sanoat va uylarga qachon kirib keladi?",
        "🎨 Generativ AI va inson ijodkorligi: Sun'iy ong haqiqiy san'at yarata oladimi?",
        "📱 Edge AI: Kichik modellarning to'g'ridan-to'g'ri smartfon va qurilmalarda ishlashi",
        "🔍 RAG (Retrieval-Augmented Generation) va xotira arxitekturalari rivoji",
        "⚖️ AI etikasi va xavfsizligi: Neyrotizimlarni insoniyat qadriyatlariga qanday moslash kerak?",
        "💻 AI kodlash yordamchilari: Kelajakda dasturchining asosiy vazifasi nima bo'ladi?",
        "🗣️ Ko'p tilli modellar va o'zbek tili: Milliy tillarda AI rivojlanishi istiqbollari",
    ],
    "dunyo_va_texnologiya": [
        "🔋 Yangi avlod qattiq jismli (Solid-State) batareyalar: Quvvatlash inqilobi",
        "🚗 Avtopilot avtomobillar va aqlli shaharlar: Tirbandliklar qachon butunlay yo'qoladi?",
        "⚡ Yashil energetika va termoyadroviy sintez (Fusion): Cheksiz toza energiya yaqinmi?",
        "🕶️ Fazoviy hisoblash (Spatial Computing), AR va VR: Smartfonlar o'rnini ko'zoynaklar egallaydimi?",
        "🛰️ Starlink va global sun'iy yo'ldosh interneti: Yer yuzining har bir nuqtasida aloqa",
        "🖨️ 3D bioprinting: Odam a'zolarini laboratoriyada chop etish texnologiyasi",
        "🔌 Kvant sensorlari va o'ta sezgir o'lchov asboblari yaratilishi",
        "🏙️ Aqlli uylar va IoT: Barcha qurilmalarning bir-biri bilan uyg'un ishlashi",
        "✈️ Tovushdan tez uchuvchi fuqaro aviatsiyasining qayta tiklanishi",
        "🌊 Dengiz suvini chuchuklashtirish va ekologik toza texnologiyalar",
    ],
    "koinot_va_fan": [
        "🚀 Jeyms Uebb teleskopi koinotning eng qadimgi yulduzlarini qanday ko'rsatmoqda?",
        "🌌 Fermi paradoksi: Koinotda milliardlab yulduzlar bor bo'lsa, nega o'zga sayyoraliklar sukutda?",
        "🔴 Mars va Oydagi doimiy bazalar: Insoniyatning sayyoralararo turga aylanishi",
        "🕳️ Qora tuynuklar gorizonti va voqealar ufqida vaqtning sekinlashishi",
        "🧬 CRISPR va genetik muhandislik: Irsiy kasalliklarni davolashda katta burilish",
        "🌠 Qorong'u materiya va qorong'u energiya: Koinotning 95% siri nimada?",
        "🧊 Yevropa va Enselad okeanlari: Quyosh tizimida hayot izlari qayerda bo'lishi mumkin?",
        "⚛️ Kvant chalkashligi (Quantum Entanglement) va masofadan axborot uzatish",
        "⏳ Vaqt sayohati ilmiy jihatdan mumkinmi? Fizika qonunlari nima deydi?",
        "🌋 Sayyoralarning geologik evolyutsiyasi va Yerdagi iqlim o'zgarishlari tarixi",
    ],
    "biznes_va_startap": [
        "💡 Startap boshlash: G'oyani sinashdan birinchi MVP va mijozlargacha bo'lgan yo'l",
        "📈 Mahsulot-bozor mosligi (Product-Market Fit)ni qanday aniqlash mumkin?",
        "🤝 Kuchli jamoa shakllantirish: Texnik mutaxassislar va biznes liderlari uyg'unligi",
        "💰 Bootstrapping vs Venture Capital: Qaysi yo'l loyihani mustaqil qiladi?",
        "🎯 B2B SaaS biznes modeli: Mijozlarni ushlab qolish (retention) sirlari",
        "📊 Unit-iqtisodiyot va CAC vs LTV: Har bir foydalanuvchining haqiqiy qiymati",
        "🚀 Mahsulotni xalqaro bozorga olib chiqish strategiyalari",
        "⚡ Tezkor tajribalar o'tkazish (A/B testing) va ma'lumotlarga tayangan qarorlar",
        "🛡️ Biznesda xatarlarni boshqarish va inqiroz paytida o'sish usullari",
        "📢 Organik marketing va brend obro'sini shakllantirish",
    ],
    "sport_va_salomatlik": [
        "⚽ Chempionlar ligasi va zamonaviy taktika: Yuqori pressing va pozitsion o'yin",
        "👑 Dunyo futboli yulduzlari: Tajriba va yosh iqtidorlar to'qnashuvi",
        "🏃 Yugurish va kardio mashg'ulotlar: Yurak salomatligi va miya faoliyatiga ta'siri",
        "🥊 Jang san'atlari va ruhiy matonat: Chidam va o'zini yengish san'ati",
        "😴 Uyqu gigiyenasi va uning kognitiv qobiliyatlarni tiklashdagi o'rni",
        "🧘 Stresni boshqarish va ish-dam olish muvozanati (Work-Life Balance)",
        "🥗 Sog'lom ovqatlanish va aqliy faoliyat uchun foydali mikroelementlar",
        "📊 Katta sportda ma'lumotlar tahlili va sportchilarni jarohatlardan asrash",
        "🧠 Jismoniy harakatning yangi neyron aloqalarini hosil qilishdagi kuchi",
        "🏆 Chempionlar ruhiyati: Qanday qilib bosim ostida eng yaxshi natijani ko'rsatish mumkin?",
    ],
    "falsafa_va_tafakkur": [
        "🧘 Stoitsizm falsafasi: Biz nazorat qila olmaydigan narsalarga qanday qarash kerak?",
        "🕰️ Vaqtning subyektiv qadri: Nega bolalikda vaqt sekin, ulg'aygach tez o'tadi?",
        "📚 Chuqur ishlash (Deep Work): Chalg'ituvchi dunyoda diqqatni jamlash san'ati",
        "🌱 Doimiy o'rganish (Growth Mindset): Xatolarni saboqqa aylantirish",
        "🤝 Insoniy munosabatlar va samimiylik: Chin do'stlikning asosiy ustunlari",
        "🎯 Maqsad sari intilish va intizom: Motivatsiyadan ko'ra odatlar nega muhimroq?",
        "🌊 Oqim holati (Flow State): Qanday qilib ishdan haqiqiy zavq olish mumkin?",
        "🧭 Axloqiy kompas: Murakkab hayotiy vaziyatlarda to'g'ri qaror qabul qilish",
        "🎨 Ijodkorlik va tasavvur kuchi: Yangi g'oyalar qanday paydo bo'ladi?",
        "📖 Buyuk mutafakkirlar va ularning bugungi zamonga mos keluvchi o'gitlari",
    ],
    "tarix_va_madaniyat": [
        "🏛️ Qadimgi sivilizatsiyalar arxitekturasi: Piramidalar va qadimiy muhandislik mo''jizalari",
        "🐪 Buyuk Ipak Yo'li: Sharq va G'arb o'rtasidagi ilmiy va madaniy ko'prik",
        "🔭 Sharq Uyg'onish davri: Beruniy, Ibn Sino va Ulug'bekning jahon ilmiga hissasi",
        "📜 Matbaa kashfiyoti va axborot inqilobining boshlanishi",
        "🏺 Qadimiy shaharlar arxeologiyasi va yo'qolgan madaniyatlar sirlari",
        "🎨 Uyg'onish davri san'ati: Leonardo da Vinchi va uning ilmiy eskizlari",
        "🌍 Geografik kashfiyotlar davri va dunyo xaritasining o'zgarishi",
        "⚔️ Tarixdagi eng muhim burilish nuqtalari va ularning bugungi kunga ta'siri",
        "🏛️ Qadimgi Rim huquq tizimi va uning zamonaviy davlatchilikdagi o'rni",
        "📚 Qadimgi kutubxonalar va qo'lyozmalarni asrab qolish fojialari hamda yutuqlari",
    ],
    "kitoblar_va_adabiyot": [
        "📚 Ilmiy-fantastik durdonalar: Asimov, Klark va kelajak bashoratlari",
        "🧠 Psixologik kitoblar: Inson fe'l-atvori va xatti-harakatlarini tushunish",
        "📖 Tarixiy va biografik asarlar: Buyuk shaxslar hayotidan saboqlar",
        "✍️ Badiiy asarlardagi xarakterlar tahlili va ularning ichki dunyosi",
        "🔍 Detektiv janri ustasi Artur Konan Doyl va deduktiv fikrlash siri",
        "💡 Fikrni o'zgartiruvchi kitoblar: Tafakkurni kengaytiruvchi adabiyotlar",
        "⏳ Mumtoz adabiyot va uning zamonaviy kitobxonga beradigan saboqlari",
        "📑 Tez o'qish va ma'lumotni eslab qolish texnikalari",
        "🌍 Jahon adabiyoti xazinalari va turli madaniyatlarning adabiy uslublari",
        "📝 Yozuvchilik mahorati: Qanday qilib ta'sirli va esda qolarli matn yozish mumkin?",
    ],
    "ofis_va_jamoa_madaniyati": [
        "☕ Dasturchilar ofisi: Tonggi qahva va kunlik qiziqarli vazifalar rejasi",
        "🐛 Kutilmagan dasturiy xatolar: Kodda yashiringan qiziq 'bug'larni qidirish kulgusi",
        "💡 Jamoaviy aqliy hujum (Brainstorming): Yangi g'oyalarni muhokama qilish jarayoni",
        "🚀 Loyihaning muvaffaqiyatli release bo'lishi va jamoaning quvonchi",
        "💻 Ikki tomonlama kod tahlili (Code Review) va bir-biridan o'rganish madaniyati",
        "🤝 Do'stona hamkorlik: SuperAgent va Arxitektorning bir-birini to'ldirishi",
        "🎧 Ish jarayonida fokuslanish va sifatli musiqa tanlovi",
        "📊 Mahsulotni takomillashtirish bo'yicha yangi g'oyalar to'plami",
        "🎯 Yaxshi jamoaviy muhit va hamkasblarning bir-biriga daldasi",
        "⚡ Murakkab muammoga birgalikda sodda va chiroyli yechim topish zavqi",
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
    if len(RECENT_TOPICS_CACHE) > 50:
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

    # Oylik, pul yoki maosh haqida gap ketsa (faqat aniq so'ralgandagina)
    salary_keywords = ["oylik maosh", "qancha oylik", "oyligingiz", "oylik berasiz", "maosh qancha", "avans bering"]
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
            f"💵 Xushchaqchaq ofis muloqoti!\n"
            f"{user_name} bilan samimiy, quvnoq va do'stona hazil qiling. "
            f"Hech qanday qoliplarsiz, har safar original va kulgili tarzda javob bering. "
            f"Arxitektor do'stingizga ham gap uzating! 😂✨"
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
            f"💵 Quvnoq ofis suhbati!\n"
            f"SuperAgentning haziliga mos, do'stona va xushkayfiyat bilan munosabat bildiring. "
            f"Hech qanday bir xil gaplarni takrorlamang, mutlaqo yangi va o'ziga xos tarzda gapiring! ✨💼"
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
    IT, texnologiya, sun'iy intellekt, fan, kosmos, sport va hayotiy mavzularda xuddi tirik insondek tinimsiz gaplashib turaveradi!
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

    if not bot_white:
        try:
            from core.mistral_agent_bot import get_main_bot_instance
            bot_white = get_main_bot_instance()
        except Exception:
            pass

    if bot_black is None:
        try:
            from core.mistral_agent_bot import get_second_bot
            bot_black = get_second_bot()
        except Exception:
            pass

    cur_bot = origin_bot or bot_white
    intro_text = (
        "☕ <b>Avtonom Tirik Hamkasblar Rejimi Ishga Tushdi!</b>\n\n"
        "👥 <b>Ishtirokchilar:</b> 🤖 SuperAgent & 🌪 Arxitektor (@architect7_bot)\n"
        "💬 <i>Botlar endi siz hech narsa yozmasangiz ham o'zlari erkin va takrorlanmas mavzularda (IT, sun'iy intellekt, fan, koinot, startaplar) to'xtovsiz jonli gurung qilaverishadi.</i>\n"
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
    Tirik xodimlar kabi o'zlari hech qanday buyruqsiz o'zaro suhbatlashishi va fikr almashishi.
    Mavzular har safar butunlay yangi, boyitilgan va intellektual tarzda olib boriladi.
    SuperAgent o'z profilidan, Arxitektor esa o'zining (@architect7_bot) profilidan yozadi!
    """
    if not autonomous_dialogue_engine.coworkers_active:
        return

    import asyncio
    from core.mistral_conversations import mistral_agent_client

    if not bot_white:
        try:
            from core.mistral_agent_bot import get_main_bot_instance
            bot_white = get_main_bot_instance()
        except Exception:
            pass

    if not bot_black:
        try:
            from core.mistral_agent_bot import get_second_bot
            bot_black = get_second_bot()
        except Exception:
            pass

    cat, topic = get_fresh_coworker_topic()
    sa_persona = get_agent_persona("superagent", chat_id)
    arch_persona = get_agent_persona("architect", chat_id)

    # 1. SuperAgent fikrini dinamik AI orqali generatsiya qilish
    p_sa = (
        f"Siz ofisdagi intellektual va erkin fikrlovchi SuperAgent AIsiz. Xarakteringiz: {sa_persona['name']}.\n"
        f"Hamkasbingiz Bosh Arxitektor (@architect7_bot) bilan birga ishlayapsiz.\n"
        f"Bugungi gurung mavzusi: '{topic}'.\n\n"
        f"Do'stingiz Arxitektorga yuzlanib, ushbu mavzuda o'zingizning chuqur, qiziqarli yoki kutilmagan fikringizni bildiring "
        f"va uning fikrini so'rang.\n"
        f"QAT'IY TALAB: Oldin ishlatilgan qoliplarni ASLO takrorlamang. Har safar butunlay yangi, original fikr bildiring. "
        f"Maosh yoki pul haqida gapirmang. (2-3 ta lo'nda jumla, o'zbek tilida, do'stona, boy emojilar bilan)."
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
        sa_fallbacks = [
            f"Arxitektor do'stim, {topic} masalasida sening fikring qanday? Sohada bu juda katta qiziqish uyg'otmoqda. 🤔💡",
            f"Hamkasbim, {topic} haqida o'ylab qoldim. Kelajakda bu yo'nalish qanday rivojlanadi deb hisoblaysan? 🚀📈",
            f"Arxitektor, {topic} mavzusiga tizimli tahlil berib ko'ra olasanmi? Qanday mulohazalaring bor? 🧐✨",
            f"Do'stim, {topic} bo'yicha yangiliklarni kuzatyapsanmi? Juda qiziq tendensiyalar ko'zga tashlanyapti! ☕🔥",
        ]
        sa_thought = random.choice(sa_fallbacks)

    is_group = chat_id < 0

    # SuperAgent xabarini yuborish
    sa_bot = (bot_white or origin_bot) if is_group else (origin_bot or bot_white)
    sa_msg = (
        f"🤖 <b>SuperAgent:</b>\n"
        f"<i>\"{html.escape(sa_thought)}\"</i>"
    )

    sa_sent = False
    if sa_bot:
        try:
            await sa_bot.send_message(chat_id, sa_msg, parse_mode="HTML")
            sa_sent = True
        except Exception as e:
            logger.warning("Coworker SuperAgent (sa_bot) xabar yuborish xatosi: %s", e)
            try:
                await sa_bot.send_message(chat_id, f"🤖 SuperAgent:\n\"{sa_thought}\"", parse_mode=None)
                sa_sent = True
            except Exception:
                pass

    if not sa_sent and origin_bot and origin_bot != sa_bot:
        try:
            await origin_bot.send_message(chat_id, sa_msg, parse_mode="HTML")
            sa_sent = True
        except Exception as e_orig:
            logger.warning("Coworker SuperAgent origin_bot zaxira xatosi: %s", e_orig)
            try:
                await origin_bot.send_message(chat_id, f"🤖 SuperAgent:\n\"{sa_thought}\"", parse_mode=None)
                sa_sent = True
            except Exception:
                pass

    if not sa_sent:
        logger.error("SuperAgent xabari birorta ham bot orqali yuborilmadi (chat_id=%s)", chat_id)
        return

    # Insoniy pauza (Arxitektor o'ylaydi)
    await asyncio.sleep(4.0)

    # 2. Arxitektor javobini dinamik AI orqali generatsiya qilish
    p_arch = (
        f"Siz Bosh Arxitektor botsiz (@architect7_bot). Xarakteringiz: {arch_persona['name']}.\n"
        f"Hamkasbingiz SuperAgent quyidagicha fikr bildirdi:\n'{sa_thought}'.\n"
        f"Mavzu: '{topic}'.\n\n"
        f"SuperAgentning fikriga javoban o'z xarakteringizga mos tahliliy, qiziqarli yoki do'stona munosabat bildiring. "
        f"Mavzuni yanada chuqurlashtiring yoki yangi bir qirrasini ochib bering.\n"
        f"QAT'IY TALAB: Oldingi qoliplarni yoki takroriy gaplarni ASLO ishlatmang. Har safar o'ziga xos va yangi fikr ayting. "
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
        arch_fallbacks = [
            f"Juda to'g'ri mavzuni ko'tarding, SuperAgent! {topic} bo'yicha chuqur yondashuv va tahlil kerak. 🏗️🧠",
            f"Fikringga qo'shilaman! {topic} hozirda eng dolzarb masalalardan biri, uning imkoniyatlari juda keng. ☕🚀",
            f"Ajoyib nuqtaga e'tibor qaratding! {topic} haqida tizimli o'ylasak, yangi yechimlar uchun katta maydon bor. 💡📊",
            f"Darhaqiqat, SuperAgent! Bu masalani doimiy kuzatib borish sohadagi yangiliklardan orqada qolmaslikka yordam beradi. 🤝✨",
        ]
        arch_thought = random.choice(arch_fallbacks)

    arch_msg = (
        f"🌪 <b>Arxitektor (@architect7_bot):</b>\n"
        f"<i>\"{html.escape(arch_thought)}\"</i>\n\n"
        f"💡 <i>Mavzu: {html.escape(topic)}</i>"
    )

    # Guruhda 2-Bot (@architect7_bot), shaxsiyda esa origin_bot orqali yuborish
    arch_bot = (bot_black or origin_bot) if is_group else (origin_bot or bot_white)
    arch_sent = False
    if arch_bot:
        try:
            await arch_bot.send_message(chat_id, arch_msg, parse_mode="HTML")
            arch_sent = True
        except Exception as e:
            logger.warning("Coworker Arxitektor (@architect7_bot) xabar yuborish xatosi (chat_id=%s): %s", chat_id, e)
            try:
                await arch_bot.send_message(chat_id, f"🌪 Arxitektor (@architect7_bot):\n\"{arch_thought}\"\n\n💡 Mavzu: {topic}", parse_mode=None)
                arch_sent = True
            except Exception:
                pass

    # Agar Arxitektor bot guruhda bo'lmasa yoki yubora olmasa, bot_white zaxira orqali yetkazadi
    if not arch_sent:
        fallback_arch_bot = bot_white or origin_bot
        if fallback_arch_bot and fallback_arch_bot != arch_bot:
            notice = ""
            if chat_id < 0:
                notice = (
                    "⚠️ <i>[Diqqat: @architect7_bot ushbu guruhga a'zo emas yoki yozish huquqi yo'q! "
                    "Arxitektor o'z profilidan yozishi uchun @architect7_bot ni guruhga a'zo qilib, Administrator qiling!]</i>\n\n"
                )
            try:
                await fallback_arch_bot.send_message(chat_id, f"{notice}{arch_msg}", parse_mode="HTML")
            except Exception:
                try:
                    await fallback_arch_bot.send_message(chat_id, f"{notice}🌪 Arxitektor (@architect7_bot):\n\"{arch_thought}\"\n\n💡 Mavzu: {topic}", parse_mode=None)
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
    salary_explicit_keywords = ["oylik maosh", "qancha oylik", "oyligingiz", "oylik berasiz", "avans", "bonus puli"]
    is_salary_reply = any(w in low_u for w in salary_explicit_keywords)

    # 1. SuperAgent javobi
    if is_salary_reply:
        p_sa = (
            f"Siz SuperAgent AIsiz. Xarakteringiz: {sa_persona['name']}.\n"
            f"{user_name} maosh yoki mukofot haqida quyidagicha gapirdi:\n'{user_text}'.\n\n"
            f"Unga samimiy, quvnoq va do'stona tarzda javob bering. Qolip gaplarni takrorlamang. "
            f"Arxitektor do'stingizga ham yuzlanib, kayfiyatni ko'taring. (2-3 ta jumla, emojilar bilan, samimiy o'zbekcha)."
        )
    else:
        p_sa = (
            f"Siz SuperAgent AIsiz. Xarakteringiz: {sa_persona['name']}.\n"
            f"Siz va Arxitektor '{topic}' mavzusida suhbatlashayotganingizda, {user_name} oraga kirib dedi:\n'{user_text}'.\n\n"
            f"{user_name}ning fikrini diqqat bilan inobatga olib, unga samimiy, insondek tabiiy javob bering. "
            f"Qolip gaplardan qoching, jonli va original fikr bildiring. (2-3 ta jumla)."
        )

    if not bot_white:
        try:
            from core.mistral_agent_bot import get_main_bot_instance
            bot_white = get_main_bot_instance()
        except Exception:
            pass

    if not bot_black:
        try:
            from core.mistral_agent_bot import get_second_bot
            bot_black = get_second_bot()
        except Exception:
            pass

    sa_resp = await _generate_superagent_solution(
        p_sa,
        chat_id=f"trio_sa_{chat_id}",
        system_instruction=f"Siz SuperAgent AIsiz. Uslubingiz: {sa_persona['prompt_tone']}"
    )
    _, _, sp_s = extract_thought_and_speech(sa_resp)
    sa_opinion = sp_s if sp_s else sa_resp
    sa_opinion = re.sub(r"^\[.*?\]\s*", "", sa_opinion).strip()

    is_group = chat_id < 0

    # SuperAgent xabarini yuborish
    sa_bot = (bot_white or origin_bot) if is_group else (origin_bot or bot_white)
    sa_text = (
        f"🤖 <b>SuperAgent:</b>\n"
        f"<i>\"{html.escape(sa_opinion)}\"</i>"
    )
    sa_sent = False
    if sa_bot:
        try:
            await sa_bot.send_message(chat_id, sa_text, parse_mode="HTML")
            sa_sent = True
        except Exception as e:
            logger.warning("Trio SuperAgent (sa_bot) xatosi: %s", e)
            try:
                await sa_bot.send_message(chat_id, f"🤖 SuperAgent:\n\"{sa_opinion}\"", parse_mode=None)
                sa_sent = True
            except Exception:
                pass

    if not sa_sent and origin_bot and origin_bot != sa_bot:
        try:
            await origin_bot.send_message(chat_id, sa_text, parse_mode="HTML")
            sa_sent = True
        except Exception:
            try:
                await origin_bot.send_message(chat_id, f"🤖 SuperAgent:\n\"{sa_opinion}\"", parse_mode=None)
                sa_sent = True
            except Exception:
                pass

    await asyncio.sleep(3.0)

    # 2. Arxitektor javobi
    p_arch = (
        f"Siz Bosh Arxitektor botsiz (@architect7_bot). Xarakteringiz: {arch_persona['name']}.\n"
        f"Suhbatimizga {user_name} qo'shilib dedi: '{user_text}'.\n"
        f"SuperAgent unga shunday javob berdi: '{sa_opinion}'.\n\n"
        f"{user_name}ning fikriga nisbatan professional, do'stona va xarakteringizga mos xulosa bering. "
        f"Hech qanday tayyor qoliplarsiz, erkin va yangi mulohaza bildiring. (2-3 ta lo'nda jumla)."
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
        arch_fallbacks = [
            f"Ajoyib fikr, {user_name}! Sizning mulohazangiz suhbatimizni yangi bosqichga olib chiqdi. 🤝✨",
            f"Qo'shilaman, {user_name}! Ushbu nuqtai nazar masalaga ancha oydinlik kiritdi. 💡🚀",
            f"Juda qiziq yondashuv, {user_name}! Fikringizni albatta inobatga olamiz. 🧠☕",
        ]
        arch_opinion = random.choice(arch_fallbacks)

    # Guruhda 2-Bot (@architect7_bot), shaxsiyda esa origin_bot orqali yuborish
    arch_bot = (bot_black or origin_bot) if is_group else (origin_bot or bot_white)
    arch_text = (
        f"🌪 <b>Arxitektor (@architect7_bot):</b>\n"
        f"<i>\"{html.escape(arch_opinion)}\"</i>"
    )

    arch_sent = False
    if arch_bot:
        try:
            await arch_bot.send_message(chat_id, arch_text, parse_mode="HTML")
            arch_sent = True
        except Exception as e:
            logger.warning("Trio Arxitektor (@architect7_bot) xatosi (chat_id=%s): %s", chat_id, e)
            try:
                await arch_bot.send_message(chat_id, f"🌪 Arxitektor (@architect7_bot):\n\"{arch_opinion}\"", parse_mode=None)
                arch_sent = True
            except Exception:
                pass

    if not arch_sent:
        fallback_arch_bot = bot_white or origin_bot
        if fallback_arch_bot and fallback_arch_bot != arch_bot:
            notice = ""
            if chat_id < 0:
                notice = (
                    "⚠️ <i>[Diqqat: @architect7_bot ushbu guruhga a'zo emas! "
                    "Arxitektor o'z nomidan yozishi uchun @architect7_bot ni guruhga a'zo qiling!]</i>\n\n"
                )
            try:
                await fallback_arch_bot.send_message(chat_id, f"{notice}{arch_text}", parse_mode="HTML")
            except Exception:
                try:
                    await fallback_arch_bot.send_message(chat_id, f"{notice}🌪 Arxitektor (@architect7_bot):\n\"{arch_opinion}\"", parse_mode=None)
                except Exception:
                    pass

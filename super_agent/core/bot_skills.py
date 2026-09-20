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

    def stop_chat(self, chat_id: int) -> bool:
        """Suhbatni to'xtatish."""
        if chat_id in self.running_chats:
            self.running_chats.discard(chat_id)
            return True
        return False

    def is_running(self, chat_id: int) -> bool:
        return chat_id in self.running_chats


autonomous_dialogue_engine = AutonomousDialogueEngine()

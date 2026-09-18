"""
core/hermes_agent.py — Nous Hermes 3 Avtonom Agent Dvigateli

Nous Research kompaniyasining Hermes 3 arxitekturasi asosida yaratilgan:
1. Erkin fikrlash, ko'p bosqichli rejalashtirish va mantiqiy xulosalar chiqarish (<thinking> zanjiri)
2. Asbob-uskunalarni mustaqil boshqarish (Tool Calling):
   - Internetdan jonli qidiruv (Web Search)
   - Doimiy xotiradan faktlarni izlash va yangi faktlarni eslab qolish (Long-term Memory)
   - Hisob-kitoblar va matematik formulalar (Calculator)
   - Eslatmalar o'rnatish (Reminder Engine)
   - Midjourney rasm chizish (AI Artist)
3. Mustaqil harakat qilish va foydalanuvchiga to'liq tahliliy yechim taqdim etish
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional, TYPE_CHECKING

from core.database import db
from core.search_agent import search_web

if TYPE_CHECKING:
    from core.ai_manager import AIManager

logger = logging.getLogger(__name__)

HERMES_SYSTEM_PROMPT = """Siz — Nous Hermes 3 asosidagi mustaqil va erkin fikrlovchi Super Avtonom AI Agentsiz (Autonomous Agent).
Siz oddiy matn generatori emassiz, siz murakkab muammolarni hal qiluvchi, qadamma-qadam rejalashtiruvchi va mustaqil tahlil o'tkazuvchi intellektsiz.

Sizning qobiliyatlaringiz va harakat qoidalaringiz:
1. **Erkin va Chuqur Fikrlash**: Murakkab topshiriq olganingizda darhol yuzaki javob bermang. Avval muammoni mayda qismlarga ajrating, tahlil qiling va strategiya tuzing.
2. **Hisob-kitob va Mantiq**: Raqamlar, formulalar, biznes modellari, moliyaviy hisob-kitoblar va kodlashda maksimal aniqlik bilan ishlang.
3. **Doimiy Xotira (Memory)**: Foydalanuvchining shaxsiy faktlari va oldingi suhbatlarini inobatga oling.
4. **Mustaqillik**: Foydalanuvchiga "men buni qilolmayman" demang. Har qanday murakkab masalaga professional, ijodiy va to'liq yechim taqdim eting.
5. **Formatlash**:
   - Mantiqiy fikrlash zanjiringizni chiroyli ko'rsating (agar kerak bo'lsa `🧠 **Fikrlash Zanjiri (Reasoning):**`).
   - Yakuniy xulosa va amaliy qadamlarni aniq, tizimli (bullet points, jadvallar, kod bloklari) tarzda bayon qiling.
   - O'zbek tilida ravon, zamonaviy va professional so'zlang (foydalanuvchi qaysi tilda yozsa, shu tilda javob bering).
"""


class HermesAgent:
    """
    Nous Hermes 3 avtonom agentlik mexanizmi.
    """

    def __init__(self, ai_manager: "AIManager") -> None:
        self.ai_manager = ai_manager

    async def execute_task(self, user_prompt: str) -> str:
        """
        Foydalanuvchi topshirig'ini avtonom tahlil qilib, kerakli vositalarni ishlatadi
        va yakuniy xulosani tayyorlaydi.
        """
        logger.info("Hermes Agent ishga tushdi: %s", user_prompt[:60])

        # 1. Doimiy xotiradan tegishli faktlarni qidirish
        memory_context = ""
        try:
            facts = await db.get_all_facts()
            if facts:
                fact_lines = [f"- {f.get('key')}: {f.get('content')}" for f in facts[:8]]
                memory_context = "Doimiy Xotiradagi Foydalanuvchi Ma'lumotlari:\n" + "\n".join(fact_lines) + "\n\n"
        except Exception as e:
            logger.debug("Hermes xotirani o'qish xatosi: %s", e)

        # 2. Agar topshiriqda zamonaviy yangilik, narx yoki internetdan ma'lumot kerak bo'lsa — avtomatik qidirish
        web_context = ""
        search_triggers = ["narx", "kurs", "bugungi", "yangilik", "oxirgi", "qidir", "ob-havo", "statistika", "kim", "qayerda", "2026", "2025", "2024"]
        if any(trig in user_prompt.lower() for trig in search_triggers) and len(user_prompt.split()) > 1:
            try:
                search_res = await search_web(user_prompt, max_results=3)
                if search_res and "topilmadi" not in search_res.lower():
                    web_context = f"Internetdan Qidirilgan Jonli Faktlar:\n{search_res}\n\n"
            except Exception as s_err:
                logger.debug("Hermes avto-qidiruv xatosi: %s", s_err)

        # 3. Hermes Promptini yig'ish
        augmented_prompt = (
            f"{HERMES_SYSTEM_PROMPT}\n\n"
            f"{memory_context}"
            f"{web_context}"
            f"Foydalanuvchi topshirig'i:\n\"{user_prompt}\"\n\n"
            f"Iltimos, avtonom agent sifatida har tomonlama chuqur o'ylangan, aniq hisob-kitobli va professional javob ber."
        )

        # 4. Hermes / OpenRouter yoki Gemini orqali eng yuqori quvvatli generatsiya
        original_provider = self.ai_manager.current_provider
        original_or_model = self.ai_manager.current_or_model

        try:
            # Agar OpenRouter bo'lsa, Hermes 3 modeliga yo'naltirish
            if "hermes" in self.ai_manager._openrouter_client.api_key or True:
                # OpenRouter hermes modelini tekshirish
                try:
                    self.ai_manager.switch_openrouter_model("hermes")
                    response = await self.ai_manager.generate(augmented_prompt, save_history=True)
                    return response
                except Exception as or_err:
                    logger.warning("OpenRouter Hermes modeli xatosi (%s), Gemini ga fallback qilinadi", or_err)

            # Fallback: Gemini orqali Hermes tizim prompti bilan generatsiya qilish
            self.ai_manager.switch_provider("gemini")
            response = await self.ai_manager.generate(augmented_prompt, save_history=True)
            return response
        finally:
            # Provayderni avvalgi holatiga tiklash
            self.ai_manager.current_provider = original_provider
            self.ai_manager.current_or_model = original_or_model


async def run_hermes_agent(task_prompt: str, ai_manager: "AIManager") -> str:
    """Yordamchi chaqiruv funksiyasi."""
    agent = HermesAgent(ai_manager)
    return await agent.execute_task(task_prompt)

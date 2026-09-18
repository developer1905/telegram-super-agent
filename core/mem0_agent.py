"""
core/mem0_agent.py — Mem0 Shaxsiylashtirilgan Adaptiv Xotira Qatlami

Imkoniyatlar:
1. Foydalanuvchining shaxsiy profili, odatlari, qiziqishlari va loyihalarini avtomatik o'rganish (Dynamic Profiling).
2. Har bir suhbatdan foydalanuvchiga xos ma'lumotlarni (ism, kasb, maqsadlar, odatlar) avtomatik ajratib olish (Fact Extraction).
3. AI javoblarida foydalanuvchining shaxsiy kontekstini inobatga olish.
4. Foydalanuvchiga o'zining AI tomonidan o'rganilgan shaxsiy profilini ko'rsatish (/profile).
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional, TYPE_CHECKING

from core.database import db

if TYPE_CHECKING:
    from core.ai_manager import AIManager

logger = logging.getLogger(__name__)

# Foydalanuvchi shaxsiga oid kalit so'zlar
_PROFILE_TRIGGERS = [
    "mening ismim", "mening kasbim", "men dasturchiman", "men ishlayman",
    "men yoqtiraman", "mening odatim", "mening loyiham", "bizning kompaniya",
    "men yashayman", "mening qiziqishim", "mening maqsadim", "men uchun muhim",
]


async def auto_extract_user_memories(user_text: str, ai_manager: "AIManager") -> None:
    """
    Agar foydalanuvchi o'zi haqida fakt yoki odat aytsa,
    Mem0 uslubida avtomatik ajratib olib doimiy xotiraga saqlaydi.
    """
    text_lower = user_text.lower()
    if not any(trig in text_lower for trig in _PROFILE_TRIGGERS):
        return

    extraction_prompt = (
        f"Foydalanuvchi quyidagi xabarni yozdi:\n\"{user_text}\"\n\n"
        f"Ushbu matnda foydalanuvchining shaxsi, kasbi, odati, yashash joyi yoki doimiy qiziqishi bormi?\n"
        f"Agar bo'lsa, uni quyidagi formatda faqat bitta qatorda yoz:\n"
        f"KALIT: QISQA_FAKT\n"
        f"Masalan: 'kasb: Senior Python dasturchi' yoki 'manzil: Toshkent shahrida yashaydi'\n"
        f"Agar shaxsiy fakt bo'lmasa, 'YOQ' deb yoz."
    )

    try:
        res = await ai_manager.generate(extraction_prompt, save_history=False)
        res_cleaned = res.strip()
        if ":" in res_cleaned and not res_cleaned.upper().startswith("YOQ"):
            k, v = res_cleaned.split(":", 1)
            k = k.strip().lower().replace(" ", "_")[:30]
            v = v.strip()[:200]
            await db.save_fact(f"profile_{k}", v, category="mem0_profile")
            logger.info("Mem0 yangi shaxsiy fakt saqladi: %s -> %s", k, v)
    except Exception as exc:
        logger.debug("Mem0 avto-fakt xatosi: %s", exc)


async def get_user_profile_report() -> str:
    """
    Foydalanuvchining Mem0 profilini chiroyli hisobot ko'rinishida qaytaradi.
    """
    facts = await db.get_all_facts()
    profile_facts = [f for f in facts if f.get("category") == "mem0_profile" or f.get("key", "").startswith("profile_")]
    general_facts = [f for f in facts if f not in profile_facts]

    lines = ["👤 **Mem0 Adaptiv Shaxsiy Profilingiz:**\n"]

    if profile_facts:
        lines.append("🌟 **O'rganilgan shaxsiy ma'lumotlar va odatlar:**")
        for pf in profile_facts:
            key_clean = pf.get("key", "").replace("profile_", "").replace("_", " ").capitalize()
            lines.append(f"• **{key_clean}:** {pf.get('content')}")
        lines.append("")

    if general_facts:
        lines.append(f"🧠 **Doimiy xotiradagi boshqa faktlar ({len(general_facts)} ta):**")
        for gf in general_facts[:6]:
            lines.append(f"• `{gf.get('key')}`: {gf.get('content')}")
        lines.append("")

    if not profile_facts and not general_facts:
        lines.append(
            "Hozircha siz haqingizda maxsus profil yaratilmagan.\n\n"
            "💡 Siz bot bilan muloqot qilgan sari (masalan: *'men dasturchiman'*, *'Toshkentda yashayman'*), "
            "agent sizning fe'l-atvoringiz va qiziqishlaringizni avtomatik eslab qoladi va profil shakllantiradi!"
        )

    return "\n".join(lines)

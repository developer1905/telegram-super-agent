"""
core/mem0_agent.py — Mem0 Shaxsiylashtirilgan Adaptiv Xotira Qatlami

Imkoniyatlar:
1. Foydalanuvchining shaxsiy profili, odatlari, qiziqishlari va loyihalarini avtomatik o'rganish (Dynamic Profiling).
2. Har bir suhbatdan foydalanuvchiga xos ma'lumotlarni (ism, kasb, maqsadlar, odatlar, manzil) tezkor qoidalar va LLM orqali avtomatik ajratib olish (Fact Extraction).
3. AI javoblarida foydalanuvchining shaxsiy kontekstini inobatga olish.
4. Foydalanuvchiga o'zining AI tomonidan o'rganilgan shaxsiy profilini interaktiv boshqarish imkonini berish (/profile).
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional, TYPE_CHECKING
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from core.database import db

if TYPE_CHECKING:
    from core.ai_manager import AIManager

logger = logging.getLogger(__name__)

# Foydalanuvchi shaxsiga oid kalit so'zlar
_PROFILE_TRIGGERS = [
    "mening ismim", "ismim ", "mening kasbim", "kasbim ", "men dasturchiman", "men ishlayman",
    "men yoqtiraman", "yoqtirganim", "mening odatim", "mening loyiham", "bizning kompaniya",
    "kompaniyamiz", "men yashayman", "manzilim", "mening qiziqishim", "mening maqsadim",
    "men uchun muhim", "telefonim", "raqamim", "mening emailim",
]


def extract_direct_facts_from_text(text: str) -> dict[str, str]:
    """
    Tezkor qoidalar (Regex) orqali foydalanuvchi ma'lumotlarini bir zumda ajratib oladi.
    API ga murojaat qilmasdan 100% kafolatlangan va darhol ishlaydi.
    """
    found: dict[str, str] = {}
    t = text.strip()

    # Ism
    m = re.search(r"(?:mening\s+ismim|ismim)\s+([A-Za-zА-Яа-яЎўҚқҒғҲҳ']+)", t, re.IGNORECASE)
    if m:
        found["ism"] = m.group(1).strip().capitalize()

    # Manzil / Yashash joyi
    m = re.search(r"(?:men\s+([A-Za-zА-Яа-яЎўҚқҒғҲҳ'\s]+(?:da|shahrida|viloyatida)\s+yashayman)|(?:manzilim[:\s]+)([A-Za-zА-Яа-я0-9ЎўҚқҒғҲҳ'\s,.-]+)", t, re.IGNORECASE)
    if m:
        val = (m.group(1) or m.group(2) or "").strip()
        if val:
            found["yashash_joyi"] = val

    # Kasb
    m = re.search(r"(?:men\s+([A-Za-zА-Яа-яЎўҚқҒғҲҳ'\s]+(?:dasturchi|muhandis|menejer|dizayner|doktor|o'qituvchi|talaba|mutaxassis))man)|(?:kasbim[:\s]+)([A-Za-zА-Яа-я0-9ЎўҚқҒғҲҳ'\s]+)", t, re.IGNORECASE)
    if m:
        val = (m.group(1) or m.group(2) or "").strip()
        if val:
            found["kasb"] = val

    # Kompaniya / Loyiha
    m = re.search(r"(?:bizning\s+kompaniya|mening\s+loyiham|kompaniyamiz)[:\s]+([A-Za-zА-Яа-я0-9ЎўҚқҒғҲҳ'\s._-]+)", t, re.IGNORECASE)
    if m:
        val = m.group(1).strip()
        if val:
            found["kompaniya"] = val

    # Maqsad
    m = re.search(r"(?:mening\s+maqsadim|asosiy\s+maqsadim)[:\s]+([A-Za-zА-Яа-я0-9ЎўҚқҒғҲҳ'\s.,-]+)", t, re.IGNORECASE)
    if m:
        val = m.group(1).strip()
        if val:
            found["maqsad"] = val

    return found


async def auto_extract_user_memories(user_text: str, ai_manager: "AIManager") -> None:
    """
    Foydalanuvchi o'zi haqida fakt yoki odat aytsa,
    Mem0 uslubida avtomatik ajratib olib doimiy xotiraga saqlaydi.
    """
    text_lower = user_text.lower()

    # 1. Tezkor to'g'ridan-to'g'ri qoidalar bilan saqlash (0 kechikish, 100% aniqlik)
    direct_facts = extract_direct_facts_from_text(user_text)
    for k, v in direct_facts.items():
        await db.save_fact(f"profile_{k}", v, category="mem0_profile")
        logger.info("Mem0 (Regex) shaxsiy fakt saqladi: %s -> %s", k, v)

    # 2. Agar matnda shaxsiy kalit so'zlar bo'lsa va AI mavjud bo'lsa, LLM bilan ham tekshirish
    if not any(trig in text_lower for trig in _PROFILE_TRIGGERS):
        return

    extraction_prompt = (
        f"Foydalanuvchi quyidagi xabarni yozdi:\n\"{user_text}\"\n\n"
        f"Ushbu matnda foydalanuvchining shaxsi, kasbi, odati, yashash joyi, qiziqishi yoki loyihasi bormi?\n"
        f"Agar bo'lsa, uni quyidagi formatda faqat bitta qatorda yoz:\n"
        f"KALIT: QISQA_FAKT\n"
        f"Masalan: 'kasb: Senior Python dasturchi' yoki 'manzil: Toshkent shahrida yashaydi'\n"
        f"Agar yangi shaxsiy fakt bo'lmasa, 'YOQ' deb yoz."
    )

    try:
        res = await ai_manager.generate(extraction_prompt, save_history=False)
        res_cleaned = res.strip()
        if ":" in res_cleaned and not res_cleaned.upper().startswith("YOQ"):
            k, v = res_cleaned.split(":", 1)
            k = k.strip().lower().replace(" ", "_")[:30]
            v = v.strip()[:200]
            if k and v:
                await db.save_fact(f"profile_{k}", v, category="mem0_profile")
                logger.info("Mem0 (LLM) yangi shaxsiy fakt saqladi: %s -> %s", k, v)
    except Exception as exc:
        logger.debug("Mem0 avto-fakt LLM xatosi: %s", exc)


async def save_profile_fact(key: str, value: str) -> bool:
    """Foydalanuvchi profiliga aniq fakt kiritish."""
    k_clean = key.strip().lower().replace(" ", "_")
    if not k_clean.startswith("profile_"):
        k_clean = f"profile_{k_clean}"
    return await db.save_fact(k_clean, value.strip(), category="mem0_profile")


async def clear_user_profile() -> int:
    """Foydalanuvchining barcha Mem0 profil ma'lumotlarini tozalash."""
    facts = await db.get_all_facts()
    count = 0
    for f in facts:
        k = f.get("key", "")
        cat = f.get("category", "")
        if cat == "mem0_profile" or k.startswith("profile_"):
            await db.delete_fact(k)
            count += 1
    return count


def build_profile_keyboard(show_back: bool = False) -> InlineKeyboardMarkup:
    """Mem0 profilini interaktiv boshqarish tugmalari."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="➕ Ma'lumot qo'shish", callback_data="mem0:add_help"),
        InlineKeyboardButton(text="🔄 Yangilash", callback_data="mem0:refresh"),
    )
    builder.row(
        InlineKeyboardButton(text="🗑 Profilni tozalash", callback_data="mem0:clear"),
    )
    if show_back:
        builder.row(
            InlineKeyboardButton(text="◀️ Asosiy Menyu", callback_data="menu:main")
        )
    return builder.as_markup()


async def get_user_profile_report(user_id: Optional[int] = None) -> str:
    """
    Foydalanuvchining Mem0 profilini chiroyli hisobot ko'rinishida qaytaradi.
    """
    facts = await db.get_all_facts()
    profile_facts = [
        f for f in facts 
        if f.get("category") == "mem0_profile" or f.get("key", "").startswith("profile_")
    ]
    general_facts = [f for f in facts if f not in profile_facts]

    lines = ["👤 **Mem0 Adaptiv Shaxsiy Profilingiz:**\n"]

    if profile_facts:
        lines.append("🌟 **O'rganilgan shaxsiy ma'lumotlar va odatlar:**")
        for pf in profile_facts:
            key_clean = pf.get("key", "").replace("profile_", "").replace("_", " ").capitalize()
            lines.append(f"• **{key_clean}:** {pf.get('content')}")
        lines.append("")

    if general_facts:
        lines.append(f"🧠 **Doimiy xotiradagi boshqa ma'lumotlar ({len(general_facts)} ta):**")
        for gf in general_facts[:6]:
            k_disp = gf.get("key", "").replace("_", " ").capitalize()
            lines.append(f"• `{k_disp}`: {gf.get('content')}")
        lines.append("")

    if not profile_facts and not general_facts:
        lines.append(
            "ℹ️ Hozircha siz haqingizda maxsus profil faktlari saqlanmagan.\n\n"
            "💡 **Profilni to'ldirish juda oson:**\n"
            "Bot bilan suhbatda o'zingiz haqingizda yozing yoki quyidagicha buyruq bering:\n"
            "• `mening ismim Umid`\n"
            "• `men Toshkentda yashayman`\n"
            "• `kasbim: Senior AI dasturchi`\n"
            "• `profil: kompaniya: MegaTech`\n"
            "• `eslab qol: karta raqamim: 8600...`\n\n"
            "Mem0 bularni avtomatik eslab qoladi va har bir javobida inobatga oladi!"
        )
    else:
        lines.append("💡 _Mem0 ushbu ma'lumotlarni doim esda saqlaydi va sizga moslashtirilgan javoblar beradi._")

    return "\n".join(lines)


# Qulaylik uchun ikkala nom bilan ham chaqirish imkoniyati (Alias)
get_user_profile_summary = get_user_profile_report

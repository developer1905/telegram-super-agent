"""
core/reminder_manager.py — Aqlli Eslatmalar Menejeri (Natural Language Reminder Engine)

Imkoniyatlar:
1. "21:30 da bot orqali menga eslat: dori ichish"
2. "menga 15 daqiqadan keyin eslat: choy damlash"
3. "ertaga soat 09:00 da hisobotni eslat"
4. "eslat: 22:00 kitob o'qish"
5. Murakkab ovozli yoki erkin matnlarni Gemini 3.6 Flash yordamida aniq vaqt va vazifaga ajratish.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Optional

try:
    import zoneinfo
    TASHKENT_TZ = zoneinfo.ZoneInfo("Asia/Tashkent")
except Exception:
    TASHKENT_TZ = None

logger = logging.getLogger(__name__)


def get_current_tashkent_time() -> datetime:
    """Toshkent joriy vaqtini qaytaradi."""
    if TASHKENT_TZ:
        return datetime.now(TASHKENT_TZ)
    return datetime.now()


def parse_reminder_fast(text: str) -> tuple[Optional[str], Optional[str]]:
    """
    Regex va qoidalar asosida tezkor tahlil.
    Qaytaradi: (remind_at_iso, reminder_text) yoki (None, None).
    """
    t = text.strip()
    now = get_current_tashkent_time()

    # 1. Nisbiy vaqt: "15 daqiqadan keyin", "2 soatdan keyin", "30 min"
    rel_m = re.search(r"(\d+)\s*(daqiqa|minut|min|soat)\s*(?:dan\s*keyin|so'ng)?", t, re.IGNORECASE)
    if rel_m:
        val = int(rel_m.group(1))
        unit = rel_m.group(2).lower()
        if "soat" in unit:
            target_dt = now + timedelta(hours=val)
        else:
            target_dt = now + timedelta(minutes=val)

        clean_text = re.sub(r"^(?:menga\s+)?(?:bot\s+orqali\s+)?eslat(?:gin|ib\s*qo'y|ma)?[:\s]*", "", t, flags=re.IGNORECASE)
        clean_text = re.sub(r"(\d+)\s*(?:daqiqa|minut|min|soat)\s*(?:dan\s*keyin|so'ng)?", "", clean_text, flags=re.IGNORECASE)
        clean_text = re.sub(r"(?:bot\s+orqali\s+)?(?:menga\s+)?eslat(?:gin|ib\s*qo'y|ma)?[:\s]*", "", clean_text, flags=re.IGNORECASE)
        clean_text = clean_text.strip(":- ")
        return target_dt.strftime("%Y-%m-%d %H:%M:00"), clean_text or "Eslatma"

    # 2. Aniq soat va daqiqa: "21:30 da", "soat 21:30", "ertaga 10:00"
    time_m = re.search(r"(?:soat\s*)?(\b\d{1,2}:\d{2}\b)(?:\s*da)?", t, re.IGNORECASE)
    if time_m:
        time_str = time_m.group(1)
        try:
            h, m = map(int, time_str.split(":"))
            if 0 <= h < 24 and 0 <= m < 60:
                target_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
                is_tomorrow = "ertaga" in t.lower()
                # Agar bugun bu vaqt o'tib ketgan bo'lsa yoki "ertaga" so'zi bo'lsa
                if target_dt <= now or is_tomorrow:
                    target_dt += timedelta(days=1)

                clean_text = t
                clean_text = re.sub(r"(?:ertaga\s+)?(?:soat\s*)?\b\d{1,2}:\d{2}\b(?:\s*da)?", "", clean_text, flags=re.IGNORECASE)
                clean_text = re.sub(r"^(?:menga\s+)?(?:bot\s+orqali\s+)?eslat(?:gin|ib\s*qo'y|ma)?[:\s]*", "", clean_text, flags=re.IGNORECASE)
                clean_text = re.sub(r"(?:bot\s+orqali\s+)?(?:menga\s+)?eslat(?:gin|ib\s*qo'y|ma)?[:\s]*", "", clean_text, flags=re.IGNORECASE)
                clean_text = clean_text.strip(":- ")
                return target_dt.strftime("%Y-%m-%d %H:%M:00"), clean_text or "Eslatma"
        except ValueError:
            pass

    return None, None


async def parse_reminder_with_ai(text: str, ai_manager: Any) -> tuple[Optional[str], Optional[str]]:
    """
    Murakkab tabiiy matnlar uchun Gemini AI orqali vaqt va vazifani ajratish.
    """
    now = get_current_tashkent_time()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")

    prompt = (
        f"Hozirgi sana va vaqt (Toshkent vaqti): {now_str}.\n"
        f"Foydalanuvchi quyidagi eslatma so'rovini yubordi:\n"
        f"\"{text}\"\n\n"
        f"Vazifa: Ushbu matndan eslatma vaqtini (YYYY-MM-DD HH:MM:00 formatida) va eslatma mazmunini ajrat.\n"
        f"Faqat quyidagi JSON formatida javob ber:\n"
        f"{{\"time\": \"YYYY-MM-DD HH:MM:00\", \"text\": \"vazifa matni\"}}\n"
        f"Hech qanday qo'shimcha so'z yoki tushuntirish yozma, faqat sof JSON."
    )

    try:
        raw_res = await ai_manager.generate(prompt, save_history=False)
        raw_clean = re.sub(r"```json|```", "", raw_res).strip()
        data = json.loads(raw_clean)
        time_val = data.get("time")
        text_val = data.get("text", "Eslatma")
        if time_val and re.match(r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}", time_val):
            return time_val, text_val
    except Exception as exc:
        logger.warning("AI reminder parsing xatosi: %s", exc)

    return None, None


async def parse_reminder_smart(text: str, ai_manager: Any = None) -> tuple[Optional[str], Optional[str]]:
    """
    Birlashgan aqlli tahlil:
    Avval tezkor regex orqali tekshiradi, agar topilmasa AI ga murojaat qiladi.
    """
    t_dt, t_text = parse_reminder_fast(text)
    if t_dt:
        return t_dt, t_text

    if ai_manager is not None:
        return await parse_reminder_with_ai(text, ai_manager)

    return None, None

"""
core/news_football_agent.py — Jonli Internet Qidiruv va AI Tahlil Agenti

Imkoniyatlar:
1. Real Madrid Klubining Barcha Musobaqalari Bo'yicha Jonli Internet Tahlili:
   - Internetdan (DuckDuckGo + Sport RSS) eng so'nggi o'yinlar, hisoblar, gollar va to'purarlarni topish.
   - AI agent (Gemini / Hermes) orqali chuqur tahlil qilib, aniq raqamlar, daqiqalar va statistika bilan O'zbek tilida chiqarish.
   - UEFA Champions League, La Liga, Copa del Rey, Supercopa de España.
   - Mbappé, Vinícius Jr, Bellingham va boshqa yetakchilarning to'purarlik jadvali.
2. Dasturlash & Yangi Texnologiyalar (Jonli qidiruv + chuqur tahlil).
3. O'zbekiston Yangiliklari (Kun.uz, Daryo.uz va jonli iqtisodiy/texnologik voqealar).
4. Kitoblar (Bestseller kitoblar, xulosalar va amaliy tavsiyalar).
"""

from __future__ import annotations

import asyncio
import logging
import re
import xml.etree.ElementTree as ET
from typing import List, Dict, Any, Optional, TYPE_CHECKING

import aiohttp
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from core.search_agent import search_web

if TYPE_CHECKING:
    from core.ai_manager import AIManager

logger = logging.getLogger(__name__)

# RSS Zaxira Manbalari
RSS_SOURCES = {
    "dasturlash": [
        "https://habr.com/ru/rss/hubs/programming/all/",
        "https://news.ycombinator.com/rss",
    ],
    "uzbekistan": [
        "https://kun.uz/rss",
        "https://daryo.uz/rss",
    ]
}


async def fetch_rss_feed_items(url: str, limit: int = 4) -> List[Dict[str, str]]:
    """Standart XML RSS 2.0 yoki Atom tasmasini yuklab sarlavhalarni ajratish."""
    items: List[Dict[str, str]] = []
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=8), headers={"User-Agent": "Mozilla/5.0"}) as resp:
                if resp.status != 200:
                    return []
                text = await resp.text()

        root = ET.fromstring(text)
        for item in root.findall(".//item")[:limit]:
            title = item.findtext("title") or ""
            link = item.findtext("link") or ""
            desc = item.findtext("description") or ""
            desc_clean = re.sub(r"<[^>]+>", "", desc).strip()[:180]
            if title:
                items.append({
                    "title": title.strip(),
                    "link": link.strip(),
                    "description": desc_clean,
                })
    except Exception as exc:
        logger.debug("RSS fetch xatosi (%s): %s", url, exc)
    return items


def build_news_keyboard(current_topic: str = "dasturlash") -> InlineKeyboardMarkup:
    """Mavzular bo'yicha navigatsiya tugmalari (Dasturlash, O'zbekiston, Kitoblar)."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="💻 Dasturlash & IT" if current_topic != "dasturlash" else "💻 Dasturlash (Faol)",
            callback_data="news:dasturlash"
        ),
        InlineKeyboardButton(
            text="🇺🇿 O'zbekiston" if current_topic != "uzbekistan" else "🇺🇿 O'zbekiston (Faol)",
            callback_data="news:uzbekistan"
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="📚 Kitoblar & Bestseller" if current_topic != "books" else "📚 Kitoblar (Faol)",
            callback_data="news:books"
        ),
    )
    builder.row(
        InlineKeyboardButton(text="🔄 Yangilash", callback_data=f"news:{current_topic}"),
        InlineKeyboardButton(text="◀️ Asosiy Menyu", callback_data="menu:main"),
    )
    return builder.as_markup()


# ─── 1. DASTURLASH VA TEXNOLOGIYALAR ──────────────────────────

async def get_programming_news(ai_manager: Optional["AIManager"] = None) -> str:
    """Dasturlash va IT yangiliklarini internetdan qidirib AI orqali tahlil qilish."""
    from core.search_agent import search_realtime_news
    import datetime

    today_str = datetime.datetime.now().strftime("%Y-yil %d-%B")
    search_query = "AI LLM Python programming framework models tech news"
    live_data = await search_realtime_news(search_query, category="tech", max_results=5)

    if not ai_manager:
        return f"💻 **Dasturlash Yangiliklari ({today_str}):**\n\n{live_data}"

    prompt = (
        f"Bugungi sana: {today_str}.\n"
        "Siz erkin fikrlovchi IT arxitektor va dasturchisiz.\n\n"
        f"Internetdan so'nggi real-vaqtdagi yangiliklar:\n{live_data}\n\n"
        "Ushbu ma'lumotlar asosida O'zbek dasturchilari va muhandislari uchun 3-4 ta eng dolzarb "
        "texnologiya, sun'iy intellekt, yangi kutubxonalar va dasturlash tendentsiyalari bo'yicha "
        "chuqur, tushunarli va aniq foydali hisobot tayyorlang. Faqat eng so'nggi yangiliklar yoritilsin, "
        "har bir punktda yangi vositaning amaliy foydasi ko'rsatilsin."
    )

    try:
        report = await ai_manager.generate(prompt, save_history=False)
        return report.strip()
    except Exception as exc:
        logger.error("Dasturlash yangiliklari AI xatosi: %s", exc)
        return f"💻 **Dasturlash Yangiliklari ({today_str}):**\n\n{live_data}"


# ─── 3. O'ZBEKISTON YANGILIKLARI ──────────────────────────────

async def get_uzbekistan_news(ai_manager: Optional["AIManager"] = None) -> str:
    """O'zbekistonning eng so'nggi muhim voqealari tahlili."""
    from core.search_agent import search_realtime_news
    import datetime

    today_str = datetime.datetime.now().strftime("%Y-yil %d-%B")
    # Kun.uz RSS orqali to'g'ridan-to'g'ri bugungi so'nggi voqealar
    live_data = await search_realtime_news("O'zbekiston iqtisodiyot texnologiya ta'lim", category="uzbekistan", max_results=5)

    if not ai_manager:
        return f"🇺🇿 **O'zbekiston Yangiliklari ({today_str}):**\n\n{live_data}"

    prompt = (
        f"Bugungi sana: {today_str}.\n"
        "Siz O'zbekiston yangiliklari bo'yicha tahlilchisisiz.\n\n"
        f"O'zbekistonning bugungi so'nggi yangiliklari (Kun.uz / Rasmiy manbalar):\n{live_data}\n\n"
        "Ushbu ma'lumotlar asosida O'zbekistonning eng muhim sohalaridagi (Iqtisodiyot, Texnologiyalar "
        "va Jamiyat) yangiliklarni aniq sanasi, qabul qilingan qarorlar va natijalar bilan "
        "saralangan holda chiroyli O'zbek tilida bayon eting. Faqat bugungi va eng so'nggi faktlarni taqdim eting."
    )

    try:
        report = await ai_manager.generate(prompt, save_history=False)
        return report.strip()
    except Exception as exc:
        logger.error("O'zbekiston yangiliklari AI xatosi: %s", exc)
        return f"🇺🇿 **O'zbekiston Yangiliklari ({today_str}):**\n\n{live_data}"


# ─── 4. KITOBLAR VA TAVSIYALAR ────────────────────────────────

async def get_books_recommendations(ai_manager: Optional["AIManager"] = None) -> str:
    """Kitoblar, mutolaa va biznes bestsellerlari tahlili."""
    if not ai_manager:
        return (
            "📚 **Eng Sara Kitoblar Tavsiyasi:**\n\n"
            "1. 'Atomic Habits' — James Clear (Odatlar kuchi)\n"
            "2. 'Deep Work' — Cal Newport (Diqqatni jamlash)\n"
            "3. 'Zero to One' — Peter Thiel (Startap va innovatsiya)\n"
            "4. 'The Pragmatic Programmer' — Andrew Hunt (Dasturlash mahorati)"
        )

    prompt = (
        "Siz erkin fikrlaydigan kitobxon va intellektual agentsiz.\n\n"
        "Dasturchilar, tadbirkorlar va rivojlanishni istaganlar uchun 3 ta dunyo miqyosidagi eng kuchli "
        "bestseller kitobni tanlang (masalan, Atomic Habits, Deep Work, Zero to One yoki boshqa saralar).\n"
        "Har bir kitob bo'yicha quyidagilarni aniq yozing:\n"
        "• Muallif va asosiy g'oyasi\n"
        "• Kitobdan 2 ta eng muhim hayotiy xulosa (aniq tamoyillar)\n"
        "• Bu kitobni kimlar o'qishi shartligi\n"
        "Chiroyli, ilhomlantiruvchi O'zbek tilida formatlab bering."
    )

    try:
        report = await ai_manager.generate(prompt, save_history=False)
        return report.strip()
    except Exception as exc:
        logger.error("Kitoblar AI xatosi: %s", exc)
        return "📚 Kitoblar tavsiyasi tayyorlanmoqda."


# ─── 4. ASOSIY DISPETCHER ─────────────────────────────────────

async def get_topic_news(topic: str, ai_manager: Optional["AIManager"] = None) -> tuple[str, InlineKeyboardMarkup]:
    """Tanlangan mavzu bo'yicha internetdan izlab, AI bilan qayta ishlangan hisobot qaytaradi."""
    clean_t = topic.lower().strip()
    if clean_t in ("uzbekistan", "uz", "ozbekiston"):
        text = await get_uzbekistan_news(ai_manager)
        current = "uzbekistan"
    elif clean_t in ("books", "kitoblar", "kitob"):
        text = await get_books_recommendations(ai_manager)
        current = "books"
    else:
        text = await get_programming_news(ai_manager)
        current = "dasturlash"

    return text, build_news_keyboard(current)

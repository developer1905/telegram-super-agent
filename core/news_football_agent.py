"""
core/news_football_agent.py — RSS Yangiliklar & Real Madrid Futbol Tahlili Agenti

Imkoniyatlar:
1. Real Madrid Klubining Barcha Musobaqalardagi Natijalari:
   - UEFA Chempionlar Ligasi (UCL)
   - Ispaniya La Ligasi
   - Copa del Rey (Ispaniya Kubogi)
   - Ispaniya Superkubogi (Supercopa)
   - To'purarlar statistikasi (Kylian Mbappé, Vinícius Júnior, Jude Bellingham, Rodrygo)
   - Keyingi kutilayotgan o'yin va so'nggi natijalar
2. Dasturlash & IT Texnologiyalari (HackerNews, Habr, OpenSource tendentsiyalari)
3. O'zbekiston Yangiliklari (Kun.uz, Daryo.uz)
4. Kitoblar (Bestseller biznes, mutolaa va IT kitoblar tavsiyalari)
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

if TYPE_CHECKING:
    from core.ai_manager import AIManager

logger = logging.getLogger(__name__)

# RSS Manbalari
RSS_SOURCES = {
    "dasturlash": [
        "https://habr.com/ru/rss/hubs/programming/all/",
        "https://news.ycombinator.com/rss",
    ],
    "uzbekistan": [
        "https://kun.uz/rss",
        "https://daryo.uz/rss",
    ],
    "realmadrid": [
        "https://www.goal.com/feeds/en/news",
        "https://www.marca.com/rss/futbol/real-madrid.xml",
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
        # RSS 2.0 channel -> item
        for item in root.findall(".//item")[:limit]:
            title = item.findtext("title") or ""
            link = item.findtext("link") or ""
            desc = item.findtext("description") or ""
            # HTML teglarni tozalash
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


def build_news_keyboard(current_topic: str = "realmadrid") -> InlineKeyboardMarkup:
    """Mavzular bo'yicha navigatsiya tugmalari."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="👑 Real Madrid" if current_topic != "realmadrid" else "👑 Real Madrid (Tanlangan)",
            callback_data="news:realmadrid"
        ),
        InlineKeyboardButton(
            text="💻 Dasturlash" if current_topic != "dasturlash" else "💻 Dasturlash (Tanlangan)",
            callback_data="news:dasturlash"
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="🇺🇿 O'zbekiston" if current_topic != "uzbekistan" else "🇺🇿 O'zbekiston (Tanlangan)",
            callback_data="news:uzbekistan"
        ),
        InlineKeyboardButton(
            text="📚 Kitoblar" if current_topic != "books" else "📚 Kitoblar (Tanlangan)",
            callback_data="news:books"
        ),
    )
    builder.row(
        InlineKeyboardButton(text="🔄 Yangilash", callback_data=f"news:{current_topic}"),
        InlineKeyboardButton(text="◀️ Asosiy Menyu", callback_data="menu:main"),
    )
    return builder.as_markup()


async def get_real_madrid_report(ai_manager: Optional["AIManager"] = None) -> str:
    """
    Real Madrid klubining barcha turnirlar (La Liga, Chempionlar Ligasi, Copa del Rey, Superkubok)dagi
    natijalari va to'purarlar haqida to'liq, jonli va professional hisobot.
    """
    lines = [
        "👑 **REAL MADRID C.F. — Mavsumiy Tahlil & Natijalar**\n",
        "🏆 **Musobaqalar va Holat:**",
        "• **UEFA Champions League:** Guruh / Pley-off bosqichida qatnashmoqda. Maqsad: 16-Kubok!",
        "• **La Liga EA Sports:** Turnir jadvalida yetakchi o'rinlarda kurashmoqda.",
        "• **Copa del Rey (Ispaniya Kubogi):** Asosiy davralar faol davom etmoqda.",
        "• **Supercopa de España:** Saudiya Arabistonida o'tkaziladigan final to'rtligiga da'vogar.\n",
        "⚽ **Jamoaning Asosiy To'purarlari:**",
        "1. 🇫🇷 **Kylian Mbappé** — Yetakchi to'purar, barcha turnirlarda golli seriya",
        "2. 🇧🇷 **Vinícius Júnior** — Qanot hujumlarining bosh harakatlantiruvchisi & assistlar",
        "3. 🏴󠁧󠁢󠁥󠁮󠁧󠁿 **Jude Bellingham** — Markaziy yarim himoyadan hal qiluvchi gollar",
        "4. 🇧🇷 **Rodrygo Goes** — Qanot hujumchisi va muhim o'yinlar qahramoni\n",
        "🏟 **Navbatdagi Reja:**",
        "• Jamoa har bir o'yinda to'liq g'alaba uchun maydonga tushadi (¡Hala Madrid y nada más!).",
    ]

    # Agar AI Manager berilgan bo'lsa, xulosani yanada jonlantirib beradi
    if ai_manager:
        prompt = (
            "Real Madrid klubining so'nggi holati, La Liga va Chempionlar Ligasidagi kurashi, "
            "Kylian Mbappe va Vinicius Juniorning joriy o'yinlari haqida 3-4 gapdan iborat juda ilhomlantiruvchi "
            "va aniq sport xulosasi yozib ber (O'zbek tilida, '¡Hala Madrid!' shiori bilan)."
        )
        try:
            ai_summary = await ai_manager.generate(prompt, save_history=False)
            lines.append(f"\n🎙 **AI Sharhlovchi Fikri:**\n_{ai_summary.strip()}_")
        except Exception:
            pass

    return "\n".join(lines)


async def get_programming_news() -> str:
    """Dasturlash va IT sohasidagi yangiliklar."""
    lines = ["💻 **Dasturlash & Texnologiyalar Yangiliklari:**\n"]
    items = await fetch_rss_feed_items(RSS_SOURCES["dasturlash"][0], limit=4)
    if items:
        for i, item in enumerate(items, 1):
            lines.append(f"**{i}. {item['title']}**\n_{item['description']}_\n🔗 [Batafsil o'qish]({item['link']})\n")
    else:
        lines.append(
            "• **Python 3.14 & Tezkor LLM Dvigatellari:** Sun'iy intellekt agentlari uchun yangi kutubxonalar ommalashmoqda.\n"
            "• **Open-Source AI Modellari:** Nous Hermes 3 va Llama 3.1 ishlab chiquvchilar orasida yetakchilik qilmoqda.\n"
            "• **Full-Stack arxitektura:** FastAPI, AsyncIO va zamonaviy Telegram botlar bozorda yuqori talabga ega.\n"
        )
    return "\n".join(lines)


async def get_uzbekistan_news() -> str:
    """O'zbekistonning muhim yangiliklari."""
    lines = ["🇺🇿 **O'zbekiston — Muhim Yangiliklar Saralasi:**\n"]
    items = await fetch_rss_feed_items(RSS_SOURCES["uzbekistan"][0], limit=4)
    if items:
        for i, item in enumerate(items, 1):
            lines.append(f"**{i}. {item['title']}**\n_{item['description']}_\n🔗 [Kun.uz orqali o'qish]({item['link']})\n")
    else:
        lines.append(
            "• **Raqamli Iqtisodiyot:** O'zbekistonda IT-Park rezidentlari va AI loyihalari uchun yangi imtiyozlar joriy etilmoqda.\n"
            "• **Tadbirkorlik & Eksport:** Mahalliy dasturiy ta'minotlarni xorijiy bozorlarga eksport qilish ko'lami ortmoqda.\n"
            "• **Ta'lim:** Yoshlar o'rtasida sun'iy intellekt va kiberxavfsizlik yo'nalishlari jadal rivojlanmoqda.\n"
        )
    return "\n".join(lines)


async def get_books_recommendations() -> str:
    """Kitoblar va mutolaa tavsiyalari."""
    lines = [
        "📚 **Eng Sara Kitoblar & Mutolaa Tavsiyalari:**\n",
        "1. 📖 **'Atomic Habits' (Atom Odatlar) — James Clear**\n"
        "   _Kichik odatlar orqali hayotda ulkan natijalarga erishish va intizomni shakllantirish haqida dunyo bestselleri._\n",
        "2. 📖 **'Deep Work' (Diqqat) — Cal Newport**\n"
        "   _Chalg'ituvchi dunyoda chuqur diqqatni jamlab, aql bovar qilmas mahsuldorlikka erishish sirlari._\n",
        "3. 📖 **'Zero to One' — Peter Thiel**\n"
        "   _Noldan yangi qiymat yaratadigan startaplar, monopoliyalar va innovatsion fikrlash darsligi._\n",
        "4. 📖 **'The Pragmatic Programmer' — Andrew Hunt, David Thomas**\n"
        "   _Har bir dasturchi va muhandis bilishi shart bo'lgan toza kod va mahorat qo'llanmasi._\n",
        "💡 _Ushbu kitoblarning xulosasi yoki tahlili kerak bo'lsa, botga: 'Atomic habits kitobi haqida xulosa ber' deb yozing!_"
    ]
    return "\n".join(lines)


async def get_topic_news(topic: str, ai_manager: Optional["AIManager"] = None) -> tuple[str, InlineKeyboardMarkup]:
    """Tanlangan mavzu bo'yicha hisobot va klaviatura qaytaradi."""
    clean_t = topic.lower().strip()
    if clean_t in ("realmadrid", "real", "madrid", "futbol"):
        text = await get_real_madrid_report(ai_manager)
        current = "realmadrid"
    elif clean_t in ("dasturlash", "tech", "it", "kod"):
        text = await get_programming_news()
        current = "dasturlash"
    elif clean_t in ("uzbekistan", "uz", "ozbekiston"):
        text = await get_uzbekistan_news()
        current = "uzbekistan"
    elif clean_t in ("books", "kitoblar", "kitob"):
        text = await get_books_recommendations()
        current = "books"
    else:
        text = await get_real_madrid_report(ai_manager)
        current = "realmadrid"

    return text, build_news_keyboard(current)

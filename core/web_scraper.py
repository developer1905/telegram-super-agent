"""
core/web_scraper.py — Jonli URL Scraping va Kanal Posti Generatori

Foydalanuvchi yuborgan ixtiyoriy veb-havolani (maqola, yangilik, blog) yuklab oladi,
ichidagi asosiy matnni tozalab o'qiydi, 3 ta asosiy tezis qiladi va
Telegram kanallar uchun tayyor, chiroyli post generatsiya qilib beradi.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

import httpx
from bs4 import BeautifulSoup

from core.database import db

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


async def scrape_url(url: str) -> tuple[Optional[str], Optional[str]]:
    """Veb-sahifadan sarlavha va tozalangan matnni ajratib olish."""
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "uz,en-US,en;q=0.9,ru;q=0.8",
    }
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                logger.warning("URL status kodi %d: %s", resp.status_code, url)
                return None, None

            html = resp.text
            soup = BeautifulSoup(html, "html.parser")

            # Keraksiz teglarni olib tashlash
            for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form", "noscript"]):
                tag.decompose()

            # Sarlavhani topish
            title = ""
            if soup.title and soup.title.string:
                title = soup.title.string.strip()
            elif soup.find("h1"):
                title = soup.find("h1").get_text(strip=True)

            # Asosiy matnni olish (article yoki p teglar)
            article = soup.find("article") or soup.find("main") or soup.body
            if article:
                paragraphs = article.find_all(["p", "h2", "h3", "li"])
                text_pieces = [p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 20]
                full_text = "\n".join(text_pieces)
            else:
                full_text = soup.get_text(separator="\n", strip=True)

            # Ortiqcha bo'shliqlarni tozalash
            full_text = re.sub(r"\n{3,}", "\n\n", full_text).strip()
            return title or url, full_text

    except Exception as exc:
        logger.error("scrape_url xatosi (%s): %s", url, exc)
        return None, None


async def analyze_url_and_generate_post(url: str, ai_manager: Any) -> str:
    """
    URL dan olingan ma'lumot asosida 3 ta tezis va Telegram kanal postini generatsiya qilish.
    """
    title, content = await scrape_url(url)
    if not content or len(content) < 50:
        return (
            "❌ Sahifa matnini yuklab bo'lmadi yoki sayt botlardan himoyalangan.\n"
            "Iltimos, boshqa havola berib ko'ring yoki matnni to'g'ridan-to'g'ri yuboring."
        )

    prompt = (
        f"Siz professional SMM va kontent tahlilchisisiz.\n"
        f"Quyidagi veb-sahifa (maqola) ma'lumotlarini tahlil qiling:\n\n"
        f"🔗 Manba: {url}\n"
        f"📌 Sarlavha: {title}\n\n"
        f"📄 Maqola matni:\n"
        f"{content[:3500]}\n\n"
        f"Vazifalar:\n"
        f"1. 📌 **3 ta Asosiy Tezis:** Maqolaning eng muhim 3 ta xulosasini aniq, londa ko'rinishda yozing.\n"
        f"2. 📢 **Telegram Kanal Uchun Tayyor Post:** Ushbu maqola asosida kanalda chop etishga 100% tayyor, "
        f"ko'zni quvontiradigan emojilar, qiziqarli kirish, asosiy mazmun, xulosa va mos #hashtag lar bilan boyitilgan post tayyorlang."
    )

    result = await ai_manager.generate(prompt, save_history=False)
    await db.log_event("url_scrape", f"Scraped and analyzed: {url[:50]}")
    return result

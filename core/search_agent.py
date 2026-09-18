"""
core/search_agent.py — DuckDuckGo Orqali Internetdan Qidirish va Rasm Yuklash Agenti

Imkoniyatlar:
1. Internetdan jonli ma'lumotlar va yangiliklarni qidirish (DDGS text)
2. Rasmlarni qidirish va to'g'ridan-to'g'ri URL larni topish
3. Rasm baytlarini RAM (BytesIO) da yuklab olish (0$ disk, xavfsiz)
4. AI bilan birlashtirilgan Web Search javoblari
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import urllib.parse
import urllib.request
from typing import Optional, TYPE_CHECKING

import aiohttp
from duckduckgo_search import DDGS

if TYPE_CHECKING:
    from core.ai_manager import AIManager

logger = logging.getLogger(__name__)


import re
import xml.etree.ElementTree as ET

def _sync_google_news_rss(query: str, max_results: int = 5, lang: str = "en") -> list[dict]:
    """Google News RSS orqali real-vaqtdagi (so'nggi soat va kunlardagi) xabarlarni olish."""
    try:
        encoded = urllib.parse.quote(query)
        if lang == "uz":
            url = f"https://news.google.com/rss/search?q={encoded}&hl=uz&gl=UZ&ceid=UZ:uz"
        elif lang == "ru":
            url = f"https://news.google.com/rss/search?q={encoded}&hl=ru&gl=RU&ceid=RU:ru"
        else:
            url = f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read()
            root = ET.fromstring(content)
            items = []
            for item in root.findall(".//item")[:max_results]:
                title = item.find("title").text if item.find("title") is not None else ""
                link = item.find("link").text if item.find("link") is not None else ""
                pub_date = item.find("pubDate").text if item.find("pubDate") is not None else ""
                desc = item.find("description").text if item.find("description") is not None else ""
                clean_desc = re.sub(r"<[^>]+>", " ", desc).strip()
                if title:
                    items.append({
                        "title": title,
                        "body": f"🗓 [Sana: {pub_date}]\n{clean_desc[:250]}",
                        "href": link,
                        "date": pub_date,
                    })
            return items
    except Exception as exc:
        logger.debug("Google News RSS xatosi: %s", exc)
        return []


def _sync_kun_uz_rss(max_results: int = 5) -> list[dict]:
    """Kun.uz RSS orqali O'zbekistonning bugungi so'nggi yangiliklarini olish."""
    try:
        url = "https://kun.uz/news/rss"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            root = ET.fromstring(resp.read())
            items = []
            for item in root.findall(".//item")[:max_results]:
                title = item.find("title").text if item.find("title") is not None else ""
                link = item.find("link").text if item.find("link") is not None else ""
                pub_date = item.find("pubDate").text if item.find("pubDate") is not None else ""
                desc = item.find("description").text if item.find("description") is not None else ""
                clean_desc = re.sub(r"<[^>]+>", " ", desc).strip()
                if title:
                    items.append({
                        "title": title,
                        "body": f"🗓 [Bugun: {pub_date}]\n{clean_desc[:250]}",
                        "href": link,
                        "date": pub_date,
                    })
            return items
    except Exception as exc:
        logger.debug("Kun.uz RSS xatosi: %s", exc)
        return []


def _sync_web_search(query: str, max_results: int = 5, timelimit: Optional[str] = "m") -> list[dict]:
    """
    Gibrid real-vaqt qidiruvi:
    1. Google News RSS (real-time yangiliklar va sport natijalari)
    2. DuckDuckGo (timelimit='w' yoki 'm' orqali yangi sahifalar)
    """
    results: list[dict] = []

    # 1. Google News RSS orqali eng yangi sana bilan olingan xabarlar
    google_news = _sync_google_news_rss(query, max_results=max_results)
    if google_news:
        results.extend(google_news)

    # 2. Agar natijalar kam bo'lsa, DuckDuckGo orqali to'ldirish
    if len(results) < max_results:
        needed = max_results - len(results)
        try:
            ddgs = DDGS()
            # Avval oxirgi oy ('m') yoki hafta ('w') chegarasi bilan
            ddg_items = list(ddgs.text(query, max_results=needed, timelimit=timelimit or "m"))
            results.extend(ddg_items)
        except Exception:
            try:
                ddgs = DDGS()
                results.extend(list(ddgs.text(query, max_results=needed)))
            except Exception as exc:
                logger.debug("DDGS fallback xatosi: %s", exc)

    return results[:max_results]


async def search_web(query: str, max_results: int = 5, timelimit: Optional[str] = "m") -> str:
    """
    Internetdan real-vaqtda qidirib, natijalarni formatlangan matn ko'rinishida qaytaradi.
    """
    results = await asyncio.to_thread(_sync_web_search, query, max_results, timelimit)
    if not results:
        return "Internetdan ma'lumot topilmadi."

    lines = []
    for i, r in enumerate(results, 1):
        title = r.get("title", "Sarlavhasiz")
        body = r.get("body", "")
        href = r.get("href", "")
        lines.append(f"{i}. **{title}**\n{body}\nManba: {href}\n")

    return "\n".join(lines)


async def search_realtime_news(query: str, category: str = "general", max_results: int = 5) -> str:
    """
    Maxsus soha bo'yicha eng so'nggi (bugungi / kechagi) xabarlarni qaytaradi.
    """
    if category == "uzbekistan":
        # Kun.uz RSS dan to'g'ridan-to'g'ri o'zbekcha yangiliklar
        kun_items = await asyncio.to_thread(_sync_kun_uz_rss, max_results)
        if kun_items:
            lines = [f"{i}. **{r['title']}**\n{r['body']}\nManba: {r['href']}\n" for i, r in enumerate(kun_items, 1)]
            return "\n".join(lines)

    # Boshqa kategoriyalar uchun Google News RSS
    return await search_web(query, max_results=max_results, timelimit="w")


# ─── Rasm Qidirish (DuckDuckGo + Wikimedia Fallback) ─────────

def _sync_ddg_image(query: str) -> Optional[str]:
    """DuckDuckGo orqali rasm URL ni olish."""
    try:
        ddgs = DDGS()
        images = list(ddgs.images(query, max_results=3))
        if images and images[0].get("image"):
            return images[0]["image"]
    except Exception as exc:
        logger.warning("DDGS image search cheklovi: %s", exc)
    return None


def _sync_wikimedia_image(query: str) -> Optional[str]:
    """Zaxira: Wikimedia Commons API orqali yuqori sifatli rasm topish."""
    try:
        encoded = urllib.parse.quote(query)
        url = (
            f"https://commons.wikimedia.org/w/api.php?"
            f"action=query&generator=search&gsrsearch={encoded}&gsrlimit=1&"
            f"prop=imageinfo&iiprop=url&format=json"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "SuperAgentBot/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            pages = data.get("query", {}).get("pages", {})
            for pid, pdata in pages.items():
                imageinfo = pdata.get("imageinfo", [])
                if imageinfo and imageinfo[0].get("url"):
                    return imageinfo[0]["url"]
    except Exception as exc:
        logger.warning("Wikimedia image xatosi: %s", exc)
    return None


async def search_image_url(query: str) -> Optional[str]:
    """
    So'rov bo'yicha rasm URL manzilini topadi.
    """
    # 1. DuckDuckGo orqali
    img_url = await asyncio.to_thread(_sync_ddg_image, query)
    if img_url:
        return img_url

    # 2. Zaxira: Wikimedia orqali
    img_url = await asyncio.to_thread(_sync_wikimedia_image, query)
    return img_url


async def download_image_bytes(image_url: str) -> Optional[bytes]:
    """
    Rasm URL idan baytlarni RAM ga yuklab oladi (BytesIO uchun).
    """
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        }
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(image_url) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    if len(data) > 1024:  # Kamida 1KB bo'lishi kerak
                        return data
    except Exception as exc:
        logger.error("Rasm yuklab olishda xato: %s", exc)
    return None


# ─── AI Bilan Birlashtirilgan Jonli Qidiruv & Avtonom Tahlil ──

async def answer_with_web_search(user_query: str, ai_manager: "AIManager") -> str:
    """
    Internetdan eng so'nggi ma'lumotlarni qidiradi va AI yordamida
    erkin fikrlaydigan agent uslubida chuqur, aniq raqamlar va faktlar bilan
    boyitilgan professional javob tayyorlaydi.
    """
    raw_search = await search_web(user_query, max_results=6)

    prompt = (
        f"Foydalanuvchi quyidagi savolni berdi:\n\"{user_query}\"\n\n"
        f"Internetdan real vaqtda olingan eng so'nggi qidiruv ma'lumotlari:\n{raw_search}\n\n"
        "Siz erkin fikrlaydigan, mustaqil intellektual va chuqur tahlilchi AI agentsiz.\n"
        "Ushbu ma'lumotlar va o'z mantiqingiz asosida foydalanuvchiga quyidagi talablarga rioya qilib javob bering:\n"
        "1. Quruq va umumiy gaplar bo'lmasin. Aniq raqamlar, sanalar, hisoblar, ismlar va statistikani ko'rsating.\n"
        "2. Masalani erkin va har tomonlama tahlil qiling, sabab va oqibatlarni tushuntiring.\n"
        "3. Javobni chiroyli Markdown formatida, aniq va ravon O'zbek tilida bayon qiling.\n"
        "4. Javob oxirida ma'lumot qayerdan olingani (manba havolalari)ni ko'rsatib o'ting."
    )

    try:
        ai_response = await ai_manager.generate(prompt)
        return ai_response
    except Exception as exc:
        logger.error("AI web search tahlilida xato: %s", exc)
        return f"🌐 **Internetdan qidiruv natijalari:**\n\n{raw_search}"

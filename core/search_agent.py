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


def _sync_web_search(query: str, max_results: int = 5) -> list[dict]:
    """DuckDuckGo orqali sinxron qidiruv."""
    try:
        ddgs = DDGS()
        results = list(ddgs.text(query, max_results=max_results))
        return results
    except Exception as exc:
        logger.error("DDGS web search xatosi: %s", exc)
        return []


async def search_web(query: str, max_results: int = 5) -> str:
    """
    Internetdan qidirib, natijalarni formatlangan matn ko'rinishida qaytaradi.
    """
    results = await asyncio.to_thread(_sync_web_search, query, max_results)
    if not results:
        return "Internetdan ma'lumot topilmadi."

    lines = []
    for i, r in enumerate(results, 1):
        title = r.get("title", "Sarlavhasiz")
        body = r.get("body", "")
        href = r.get("href", "")
        lines.append(f"{i}. **{title}**\n{body}\nManba: {href}\n")

    return "\n".join(lines)


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


# ─── AI Bilan Birlashtirilgan Jonli Qidiruv ───────────────────

async def answer_with_web_search(user_query: str, ai_manager: "AIManager") -> str:
    """
    Internetdan eng so'nggi ma'lumotlarni qidiradi va AI yordamida
    to'liq, chiroyli va manbalar bilan boyitilgan javob tayyorlaydi.
    """
    raw_search = await search_web(user_query, max_results=5)

    prompt = (
        f"Foydalanuvchi quyidagi savolni berdi:\n\"{user_query}\"\n\n"
        f"Internetdan olingan eng so'nggi ma'lumotlar:\n{raw_search}\n\n"
        f"Ushbu ma'lumotlar asosida foydalanuvchiga O'zbek tilida aniq, tushunarli, "
        f"eng so'nggi faktlarga asoslangan professional javob tayyorla. "
        f"Javob oxirida muhim manba havolalarini ko'rsatib o't."
    )

    try:
        ai_response = await ai_manager.generate(prompt)
        return ai_response
    except Exception as exc:
        logger.error("AI web search tahlilida xato: %s", exc)
        return f"🌐 **Internetdan qidiruv natijalari:**\n\n{raw_search}"

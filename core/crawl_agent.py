"""
core/crawl_agent.py — Crawl4AI Uslubidagi Intellektual Veb-Krouler & Skraper

Imkoniyatlar:
1. Istalgan veb-sahifa yoki maqoladan asosiy matn, sarlavhalar va jadvallarni tozalab olish.
2. Reklamalar, skriptlar, cookie bannerlar va menyularni tozalash (Readability & Content Extraction).
3. LLM (Sun'iy Intellekt) uchun 100% tayyor toza Markdown matnini shakllantirish.
4. Xavfsiz asinxron aiohttp va BeautifulSoup4 orqali yengil va tezkor ishlash (0% RAM ziyon).
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional
from urllib.parse import urlparse

import aiohttp
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


async def crawl_web_page(url: str, max_chars: int = 5000) -> dict:
    """
    Veb-sahifani Crawl4AI uslubida chuqur skraping qilib,
    toza sarlavha, matn va metadata bilan qaytaradi.
    """
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "uz,ru,en-US;q=0.9,en;q=0.8",
    }

    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(url, allow_redirects=True) as resp:
                if resp.status != 200:
                    return {
                        "status": "error",
                        "error": f"Veb-sahifaga ulanib bo'lmadi (HTTP {resp.status})",
                        "url": url,
                    }

                html = await resp.text(errors="replace")

        # HTML ni tahlil qilish
        soup = BeautifulSoup(html, "html.parser")

        # Keraksiz elementlarni olib tashlash
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript", "svg", "form"]):
            tag.decompose()

        # Sarlavhani aniqlash
        title = ""
        if soup.title and soup.title.string:
            title = soup.title.string.strip()
        elif soup.find("h1"):
            title = soup.find("h1").get_text(strip=True)
        else:
            title = urlparse(url).netloc

        # Asosiy kontentni izlash (article, main yoki content teglari)
        main_content = soup.find("article") or soup.find("main") or soup.find(id=re.compile(r"content|main|post|article", re.I)) or soup.body

        if not main_content:
            main_content = soup

        # Paragraf va jadvallarni yig'ish
        markdown_lines = []
        for el in main_content.find_all(["h1", "h2", "h3", "h4", "p", "li", "table"]):
            if el.name in ("h1", "h2", "h3", "h4"):
                level = int(el.name[1])
                txt = el.get_text(strip=True)
                if txt:
                    markdown_lines.append(f"\n{'#' * level} {txt}\n")
            elif el.name == "p":
                txt = el.get_text(strip=True)
                if len(txt) > 20:  # Faqat mazmunli paragraflar
                    markdown_lines.append(txt)
            elif el.name == "li":
                txt = el.get_text(strip=True)
                if txt:
                    markdown_lines.append(f"• {txt}")
            elif el.name == "table":
                rows = el.find_all("tr")
                for r in rows[:15]:
                    cells = [c.get_text(strip=True) for c in r.find_all(["td", "th"])]
                    if cells:
                        markdown_lines.append("| " + " | ".join(cells) + " |")

        full_text = "\n\n".join(markdown_lines).strip()

        # Agar maxsus paragraflar topilmasa, oddiy tozalangan matnni olamiz
        if not full_text:
            full_text = main_content.get_text(separator="\n", strip=True)

        # Cheklash
        cleaned_text = full_text[:max_chars]

        return {
            "status": "ok",
            "url": url,
            "title": title,
            "domain": urlparse(url).netloc,
            "content": cleaned_text,
            "length": len(cleaned_text),
        }

    except Exception as exc:
        logger.error("Crawl agent xatosi: %s", exc)
        return {
            "status": "error",
            "error": str(exc),
            "url": url,
        }

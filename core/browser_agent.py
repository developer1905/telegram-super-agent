"""
core/browser_agent.py — Veb Brauzer & Skrinshot Agenti (Browser-Use)

Imkoniyatlar:
1. Istalgan veb-saytning yuqori aniqlikdagi jonli skrinshotini (Screenshot) olish.
2. Server RAM xotirasini tejash uchun bulutli tezyurar render xizmatlari va zaxira usullardan foydalanish (1GB micro instance xavfsizligi).
3. Skrinshot tasvirini to'g'ridan-to'g'ri Telegramga rasm sifatida yuborish.
4. Gemini Vision orqali saytning vizual dizayni va tuzilishini tahlil qilish.
"""

from __future__ import annotations

import asyncio
import logging
import urllib.parse
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)


async def take_website_screenshot(url: str) -> Optional[bytes]:
    """
    Veb-sayt manzilining to'liq va sifatli skrinshotini oladi.
    RAM ga xavfsiz yuklaydi (BytesIO formatida).
    """
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    encoded_url = urllib.parse.quote(url, safe="")

    # 1. Thum.io tezyurar va bepul skrinshot dvigateli
    thum_url = f"https://image.thum.io/get/width/1280/crop/800/{url}"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    }

    try:
        timeout = aiohttp.ClientTimeout(total=25)
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(thum_url) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    if len(data) > 5000:  # Haqiqiy rasm fayli
                        logger.info("Veb skrinshot muvaffaqiyatli olindi (thum.io): %s (%d bayt)", url, len(data))
                        return data
    except Exception as exc:
        logger.warning("Thum.io skrinshot xatosi: %s", exc)

    # 2. Zaxira skrinshot dvigateli (Microlink API)
    try:
        microlink_api = f"https://api.microlink.io?url={encoded_url}&screenshot=true&meta=false"
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=25)) as session:
            async with session.get(microlink_api) as resp:
                if resp.status == 200:
                    res_json = await resp.json()
                    img_url = res_json.get("data", {}).get("screenshot", {}).get("url")
                    if img_url:
                        async with session.get(img_url) as img_resp:
                            if img_resp.status == 200:
                                return await img_resp.read()
    except Exception as m_exc:
        logger.warning("Microlink skrinshot xatosi: %s", m_exc)

    return None

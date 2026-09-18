"""
core/uptime_agent.py — Veb-saytlar va Serverlar Uptime Monitoring Agenti

Imkoniyatlar:
1. Shaxsiy veb-saytlar, domenlar yoki API'larning doimiy onlayn holatini tekshirish (HTTP status va kechikish ms).
2. Sayt o'chib qolsa (HTTP 500, 502, 404 yoki Timeout), zudlik bilan Telegram'ga favqulodda ogohlantirish yuborish.
3. Sayt qayta tiklanganda (Recovered), tiklanish xabari berish.
4. Barcha saytlar holatini chiroyli status dashboard ko'rinishida ko'rsatish (/uptime).
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import List, Dict, Any, Tuple

import aiohttp
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import UPTIME_TIMEOUT
from core.database import db

logger = logging.getLogger(__name__)


async def check_url_health(url: str, timeout_sec: int = UPTIME_TIMEOUT) -> Tuple[int, float]:
    """
    URL manzilini tekshirib (HTTP status, response_time_ms) qaytaradi.
    Agar ulanib bo'lmasa yoki timeout bo'lsa: (0, 0.0).
    """
    clean_url = url.strip()
    if not clean_url.startswith(("http://", "https://")):
        clean_url = f"https://{clean_url}"

    start_time = time.time()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                clean_url,
                timeout=aiohttp.ClientTimeout(total=timeout_sec),
                allow_redirects=True,
                headers={"User-Agent": "SuperAgent-UptimeMonitor/2.0"}
            ) as resp:
                elapsed_ms = round((time.time() - start_time) * 1000, 1)
                return resp.status, elapsed_ms
    except asyncio.TimeoutError:
        logger.debug("Uptime timeout: %s", clean_url)
        return 504, round((time.time() - start_time) * 1000, 1)
    except Exception as exc:
        logger.debug("Uptime check xatosi: %s -> %s", clean_url, exc)
        return 0, 0.0


async def run_uptime_batch_check() -> List[Dict[str, Any]]:
    """
    Barcha faol saytlarni bir vaqtda (parallel) tekshirib,
    holat o'zgarishlari (Down yoki Recovered) ro'yxatini qaytaradi.
    """
    monitors = await db.get_uptime_monitors(active_only=True)
    if not monitors:
        return []

    alerts: List[Dict[str, Any]] = []

    async def _check_one(m: Dict[str, Any]):
        m_id = m["id"]
        url = m["url"]
        name = m.get("name") or url
        last_status = m.get("last_status") or 0
        alert_sent = m.get("alert_sent") or 0

        status_code, resp_ms = await check_url_health(url)
        is_ok = 200 <= status_code < 400

        new_alert_sent = alert_sent
        # Sayt o'chdi (Avval ishlagan, hozir o'chdi)
        if not is_ok and alert_sent == 0:
            new_alert_sent = 1
            alerts.append({
                "type": "DOWN",
                "name": name,
                "url": url,
                "status": status_code,
                "time_ms": resp_ms,
            })
        # Sayt qayta tiklandi (Avval o'chgan, hozir ishladi)
        elif is_ok and alert_sent == 1:
            new_alert_sent = 0
            alerts.append({
                "type": "RECOVERED",
                "name": name,
                "url": url,
                "status": status_code,
                "time_ms": resp_ms,
            })

        await db.update_uptime_status(m_id, status_code, resp_ms, new_alert_sent)

    await asyncio.gather(*[_check_one(m) for m in monitors], return_exceptions=True)
    return alerts


async def format_uptime_dashboard_report() -> Tuple[str, InlineKeyboardMarkup]:
    """
    Foydalanuvchi uchun to'liq saytlar holati hisoboti.
    """
    monitors = await db.get_uptime_monitors(active_only=True)
    builder = InlineKeyboardBuilder()

    if not monitors:
        text = (
            "🌐 **Saytlar va Serverlar Uptime Monitoringi**\n\n"
            "Hozircha kuzatilayotgan veb-saytlar yo'q.\n\n"
            "💡 **Yangi sayt qo'shish juda oson:**\n"
            "Botga quyidagicha yozing:\n"
            "• `/add_site https://mysite.uz Mening Saytim`\n"
            "• `sayt qo'sh: https://api.mysite.com | Asosiy API`\n\n"
            "Bot har 10 daqiqada saytni tekshirib turadi va agar sayt o'chsa, zudlik bilan sizga xabar beradi!"
        )
        builder.row(InlineKeyboardButton(text="➕ Sayt Qo'shish Yo'riqnomasi", callback_data="uptime:add_hint"))
        return text, builder.as_markup()

    lines = [f"🌐 **Saytlar Uptime Monitoring Holati** ({len(monitors)} ta sayt):\n"]

    for m in monitors:
        status = m.get("last_status", 0)
        ms = m.get("response_ms", 0.0)
        name = m.get("name") or m["url"]
        last_checked = m.get("last_checked") or "Hozirgina"

        if 200 <= status < 400:
            status_icon = "🟢 Onlayn"
        elif status == 0:
            status_icon = "⚪ Tekshirilmoqda"
        else:
            status_icon = f"🔴 Xato ({status})"

        lines.append(f"• **{name}**\n  🔗 `{m['url']}`\n  Holat: {status_icon} | Kechikish: `{ms} ms`\n")

    lines.append("💡 _Har bir sayt har 10 daqiqada avtomatik tekshirib boriladi._")

    builder.row(
        InlineKeyboardButton(text="🔄 Hozir Tekshirish", callback_data="uptime:check_now"),
        InlineKeyboardButton(text="➕ Sayt Qo'shish", callback_data="uptime:add_hint"),
    )

    return "\n".join(lines), builder.as_markup()

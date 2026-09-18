"""
core/todo_notion_agent.py — Smart TodoList va Notion Integratsiya Agenti

Imkoniyatlar:
1. Vazifalarni tezkor yaratish (matnli yoki ovozli buyruq orqali).
2. O'zbekiston/Lokal vaqt bilan rejalashtirish (Due dates).
3. Notion API bilan avtomatik sinxronizatsiya:
   - Agar NOTION_API_KEY va NOTION_DATABASE_ID bo'lsa, Notion dagi ma'lumotlar bazasiga avtomat qo'shadi.
   - Agar Notion kaliti bo'lmasa, ichki SQLite bazasida 100% mustaqil va bepul ishlaydi (Zero-Downtime Fallback).
4. Interaktiv Inline tugmalar (bir marta bosishda vazifani 'Bajarildi' qilish).
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import re
from typing import Optional, Dict, Any, List

import aiohttp
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import NOTION_API_KEY, NOTION_DATABASE_ID
from core.database import db

logger = logging.getLogger(__name__)


async def sync_task_to_notion(title: str, due_date: str = "") -> str:
    """
    Agar Notion API kaliti berilgan bo'lsa, vazifani Notion sahifasiga qo'shadi.
    Muvaffaqiyatli bo'lsa page_id qaytaradi, aks holda bo'sh string.
    """
    if not (NOTION_API_KEY and NOTION_DATABASE_ID):
        return ""

    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    }

    properties: Dict[str, Any] = {
        "Name": {
            "title": [{"text": {"content": title[:200]}}]
        },
        "Status": {
            "select": {"name": "In Progress"}
        }
    }

    if due_date:
        # Sana formati ISO YYYY-MM-DD
        properties["Due Date"] = {"date": {"start": due_date[:10]}}

    payload = {
        "parent": {"database_id": NOTION_DATABASE_ID},
        "properties": properties,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.notion.com/v1/pages",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status in (200, 201):
                    data = await resp.json()
                    page_id = data.get("id", "")
                    logger.info("Notion ga vazifa muvaffaqiyatli sinxronlandi: %s (page_id: %s)", title, page_id)
                    return page_id
                else:
                    err_txt = await resp.text()
                    logger.warning("Notion API xatosi (%s): %s", resp.status, err_txt[:100])
                    return ""
    except Exception as exc:
        logger.warning("Notion ga ulanishda xato: %s", exc)
        return ""


async def create_new_task(text_command: str) -> Dict[str, Any]:
    """
    Matndan vazifa va sanani ajratib olib yangi task yaratadi.
    Format namunalari:
    - 'vazifa: ertaga hisobot tayyorlash'
    - 'reja: bugun soat 18:00 da dori sotib olish'
    - 'todo: Akmalga qo'ng'iroq qilish 2026-09-20'
    """
    clean_text = re.sub(r"^(?:/todo\s+(?:add|qo'sh|qosh)?|vazifa\s*qo'sh:|vazifa:|reja:|todo:)\s*", "", text_command, flags=re.IGNORECASE).strip()
    
    # Sanani ajratish (YYYY-MM-DD)
    due_date = ""
    date_match = re.search(r"(\d{4}-\d{2}-\d{2})", clean_text)
    if date_match:
        due_date = date_match.group(1)
        clean_text = clean_text.replace(due_date, "").strip()

    title = clean_text.strip() or "Yangi vazifa"

    # 1. Notion ga sinxronlash (agar sozlangan bo'lsa)
    notion_id = await sync_task_to_notion(title, due_date)

    # 2. Ichki SQLite bazasiga saqlash
    task_id = await db.add_task(
        title=title,
        description="",
        due_date=due_date,
        notion_page_id=notion_id
    )

    return {
        "id": task_id,
        "title": title,
        "due_date": due_date,
        "notion_synced": bool(notion_id),
    }


async def format_tasks_list_report(status: str = "pending") -> tuple[str, InlineKeyboardMarkup]:
    """
    Vazifalar ro'yxati matni va 'Bajarildi' inline tugmalarini hosil qiladi.
    """
    tasks = await db.get_tasks(status=status, limit=15)
    notion_status = "✅ Notion Ulangan" if (NOTION_API_KEY and NOTION_DATABASE_ID) else "💾 Lokal Baza (Offline)"

    builder = InlineKeyboardBuilder()

    if not tasks:
        text = (
            f"📝 **Aqlli TodoList & Vazifalar Menejeri**\n"
            f"🔗 Tizim holati: `{notion_status}`\n\n"
            f"🎉 **Hozircha barcha vazifalar bajarilgan! Kutilayotgan vazifalar yo'q.**\n\n"
            f"💡 **Yangi vazifa qo'shish usullari:**\n"
            f"• `vazifa: Ertaga soat 10 da pretsentatsiya tayyorlash`\n"
            f"• `todo: Do'kondan olma sotib olish 2026-09-19`\n"
            f"• Ovozli xabarda: *'Vazifa qo'sh: Bugun kitob o'qish'* deb ayting!"
        )
        builder.row(InlineKeyboardButton(text="➕ Yangi Vazifa Qo'shish", callback_data="todo:add_hint"))
        builder.row(InlineKeyboardButton(text="🔄 Yangilash", callback_data="todo:refresh"))
        return text, builder.as_markup()

    lines = [
        f"📝 **TodoList & Vazifalar Ro'yxati** ({len(tasks)} ta faol):\n",
        f"🔗 Holat: `{notion_status}`\n",
    ]

    for t in tasks:
        due_str = f" ➔ 📅 `{t['due_date']}`" if t.get("due_date") else ""
        notion_mark = " 🌐" if t.get("notion_page_id") else ""
        lines.append(f"• `#{t['id']}` ⬜ **{t['title']}**{due_str}{notion_mark}")
        # Har bir vazifa uchun bitta teginishda bajarish tugmasi
        btn_text = f"✅ #{t['id']} Bajarildi"
        builder.row(
            InlineKeyboardButton(text=btn_text, callback_data=f"todo:done:{t['id']}"),
            InlineKeyboardButton(text=f"❌ O'chirish", callback_data=f"todo:del:{t['id']}")
        )

    lines.append("\n💡 _Vazifani tugatgach, pastdagi tegishli '✅ Bajarildi' tugmasini bosing._")

    builder.row(
        InlineKeyboardButton(text="➕ Yangi Vazifa", callback_data="todo:add_hint"),
        InlineKeyboardButton(text="🔄 Yangilash", callback_data="todo:refresh"),
    )

    return "\n".join(lines), builder.as_markup()

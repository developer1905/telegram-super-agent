"""
core/database.py — Supabase + SQLite Hybrid Doimiy Xotira (RAG & Memory)

Foydalanuvchining shaxsiy faktlari (karta raqamlari, manzil, xizmatlar, narxlar),
kechiktirilgan postlar, raqobatchi kanallar va statistikani doimiy saqlaydi.
Agar SUPABASE_URL va SUPABASE_KEY berilgan bo'lsa Supabase ga yozadi,
aks holda avtomatik lokal SQLite bazasiga tayanadi (Zero-Downtime Fallback).
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
import sqlite3
from typing import Any, Optional

from config import SUPABASE_URL, SUPABASE_KEY

logger = logging.getLogger(__name__)

DB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
SQLITE_PATH = os.path.join(DB_DIR, "superagent.db")


class DatabaseManager:
    """Supabase va SQLite gibrid ma'lumotlar bazasi menejeri."""

    def __init__(self) -> None:
        self.use_supabase = bool(SUPABASE_URL and SUPABASE_KEY)
        self._supabase_client: Any = None
        self._supabase_reminders_available: bool = True
        self._supabase_chats_available: bool = True

        if self.use_supabase:
            try:
                from supabase import create_client, Client
                self._supabase_client: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
                logger.info("DatabaseManager: Supabase ga muvaffaqiyatli ulandi.")
            except Exception as exc:
                logger.warning("DatabaseManager: Supabase ga ulanishda xato: %s. SQLite ga o'tilmoqda.", exc)
                self.use_supabase = False

        self._init_sqlite()

    def _get_sqlite_conn(self) -> sqlite3.Connection:
        """Optimallashtirilgan SQLite ulanishi (30s timeout, busy_timeout)."""
        conn = sqlite3.connect(SQLITE_PATH, timeout=30.0)
        conn.execute("PRAGMA busy_timeout = 15000;")
        return conn

    def _init_sqlite(self) -> None:
        """Lokal SQLite bazasi va kerakli jadvallarni initsializatsiya qilish."""
        os.makedirs(DB_DIR, exist_ok=True)
        with sqlite3.connect(SQLITE_PATH, timeout=30.0) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA journal_mode = WAL;")
            cursor.execute("PRAGMA busy_timeout = 15000;")
            cursor.execute("PRAGMA synchronous = NORMAL;")

            # 1. Knowledge Base (Doimiy xotira)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS knowledge_base (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT UNIQUE NOT NULL,
                    content TEXT NOT NULL,
                    category TEXT DEFAULT 'general',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 2. Scheduled Posts (Kechiktirilgan postlar)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS scheduled_posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id TEXT NOT NULL,
                    text TEXT NOT NULL,
                    media_type TEXT DEFAULT 'none',
                    scheduled_time TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 3. Competitor Channels (Raqobatchi kanallar)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS competitor_channels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_username TEXT UNIQUE NOT NULL,
                    last_scraped TEXT DEFAULT '',
                    active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 4. Bot Stats (Statistika)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS bot_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    details TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 5. Reminders (Eslatmalar)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id TEXT NOT NULL,
                    text TEXT NOT NULL,
                    remind_at TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 6. Managed Chats (Boshqarilayotgan kanallar va guruhlar)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS managed_chats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id TEXT UNIQUE NOT NULL,
                    title TEXT NOT NULL,
                    chat_type TEXT NOT NULL,
                    username TEXT DEFAULT '',
                    is_active INTEGER DEFAULT 1,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 7. Chat History (Suhbat tarixi — server qayta yonganda ham o'chib ketmaydi)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS chat_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

    # ─── 1. SHAXSIY MA'LUMOTLAR BAZASI (KNOWLEDGE BASE / RAG) ──────

    async def save_fact(self, key: str, content: str, category: str = "general") -> bool:
        """Doimiy faktni saqlash (masalan: 'card_number', 'company_services', 'resume')."""
        key_clean = key.strip().lower()
        now_iso = datetime.datetime.utcnow().isoformat()

        # Supabase ga yozishga urinish
        if self.use_supabase and self._supabase_client:
            try:
                loop = asyncio.get_running_loop()
                data = {
                    "key": key_clean,
                    "content": content,
                    "category": category,
                    "updated_at": now_iso,
                }
                await loop.run_in_executor(
                    None,
                    lambda: self._supabase_client.table("knowledge_base").upsert(data, on_conflict="key").execute()
                )
                logger.info("Supabase: Fakt saqlandi: '%s'", key_clean)
            except Exception as exc:
                logger.warning("Supabase xatosi, SQLite ga yozilmoqda: %s", exc)

        # Har doim lokal SQLite ga ham yozib qo'yamiz (tezkor kesh va oflayn ishlash uchun)
        try:
            with self._get_sqlite_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO knowledge_base (key, content, category, updated_at)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(key) DO UPDATE SET
                        content = excluded.content,
                        category = excluded.category,
                        updated_at = CURRENT_TIMESTAMP
                """, (key_clean, content, category))
                conn.commit()
            return True
        except Exception as exc:
            logger.error("SQLite save_fact xatosi: %s", exc)
            return False

    async def get_all_facts(self) -> list[dict]:
        """Barcha saqlangan faktlarni olish."""
        if self.use_supabase and self._supabase_client:
            try:
                loop = asyncio.get_running_loop()
                res = await loop.run_in_executor(
                    None,
                    lambda: self._supabase_client.table("knowledge_base").select("*").execute()
                )
                if res.data:
                    return res.data
            except Exception as exc:
                logger.warning("Supabase get_all_facts xatosi: %s. SQLite dan olinmoqda.", exc)

        try:
            with self._get_sqlite_conn() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("SELECT key, content, category, updated_at FROM knowledge_base ORDER BY updated_at DESC")
                rows = cursor.fetchall()
                return [dict(r) for r in rows]
        except Exception as exc:
            logger.error("SQLite get_all_facts xatosi: %s", exc)
            return []

    async def delete_fact(self, key: str) -> bool:
        """Faktni o'chirish."""
        key_clean = key.strip().lower()
        if self.use_supabase and self._supabase_client:
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None,
                    lambda: self._supabase_client.table("knowledge_base").delete().eq("key", key_clean).execute()
                )
            except Exception as exc:
                logger.warning("Supabase delete_fact xatosi: %s", exc)

        try:
            with self._get_sqlite_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM knowledge_base WHERE key = ?", (key_clean,))
                conn.commit()
            return True
        except Exception as exc:
            logger.error("SQLite delete_fact xatosi: %s", exc)
            return False

    async def build_rag_context(self) -> str:
        """AI promptiga qo'shish uchun doimiy xotiradagi barcha faktlarni formatlash."""
        facts = await self.get_all_facts()
        if not facts:
            return ""

        lines = ["--- FOYDALANUVCHINING DOIMIY BILIMLAR BAZASI (LONG-TERM MEMORY) ---"]
        for f in facts:
            lines.append(f"• [{f.get('category', 'general').upper()}] {f.get('key')}: {f.get('content')}")
        lines.append("--- BILIMLAR BAZASI TUGADI (Agar kerak bo'lsa, ushbu ma'lumotlarga tayangan holda javob bering) ---\n")
        return "\n".join(lines)

    # ─── 2. TAYMERLI (KECHIKTIRILGAN) POSTLAR (SCHEDULED POSTS) ────

    async def add_scheduled_post(self, chat_id: str, text: str, scheduled_time: str, media_type: str = "none") -> int:
        """Kechiktirilgan postni rejalashtirish."""
        try:
            with self._get_sqlite_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO scheduled_posts (chat_id, text, scheduled_time, media_type, status)
                    VALUES (?, ?, ?, ?, 'pending')
                """, (str(chat_id), text, scheduled_time, media_type))
                conn.commit()
                return cursor.lastrowid or 0
        except Exception as exc:
            logger.error("add_scheduled_post xatosi: %s", exc)
            return 0

    async def get_due_posts(self) -> list[dict]:
        """Vaqti kelgan (scheduled_time <= hozirgi vaqt) e'lon qilinmagan postlarni olish."""
        now_iso = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with self._get_sqlite_conn() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT id, chat_id, text, scheduled_time, media_type
                    FROM scheduled_posts
                    WHERE status = 'pending' AND scheduled_time <= ?
                    ORDER BY scheduled_time ASC
                """, (now_iso,))
                rows = cursor.fetchall()
                return [dict(r) for r in rows]
        except Exception as exc:
            logger.error("get_due_posts xatosi: %s", exc)
            return []

    async def mark_post_published(self, post_id: int) -> None:
        """Post muvaffaqiyatli chiqarilgach, statusini 'published' ga o'zgartirish."""
        try:
            with self._get_sqlite_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("UPDATE scheduled_posts SET status = 'published' WHERE id = ?", (post_id,))
                conn.commit()
        except Exception as exc:
            logger.error("mark_post_published xatosi: %s", exc)

    async def get_all_pending_posts(self) -> list[dict]:
        """Kutilayotgan barcha rejalashtirilgan postlar ro'yxati."""
        try:
            with self._get_sqlite_conn() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT id, chat_id, text, scheduled_time, status
                    FROM scheduled_posts
                    WHERE status = 'pending'
                    ORDER BY scheduled_time ASC
                """)
                return [dict(r) for r in cursor.fetchall()]
        except Exception as exc:
            logger.error("get_all_pending_posts xatosi: %s", exc)
            return []

    # ─── 3. RAQOBATCHILAR MONITORI (COMPETITOR CHANNELS) ───────────

    async def add_competitor(self, channel_username: str) -> bool:
        """Kuzatish uchun yangi raqobatchi kanal qo'shish."""
        ch = channel_username.strip().lstrip("@").lower()
        if not ch:
            return False
        try:
            with self._get_sqlite_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO competitor_channels (channel_username, active)
                    VALUES (?, 1)
                    ON CONFLICT(channel_username) DO UPDATE SET active = 1
                """, (ch,))
                conn.commit()
            return True
        except Exception as exc:
            logger.error("add_competitor xatosi: %s", exc)
            return False

    async def get_competitors(self) -> list[str]:
        """Faol raqobatchi kanallar ro'yxatini olish."""
        try:
            with self._get_sqlite_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT channel_username FROM competitor_channels WHERE active = 1")
                return [row[0] for row in cursor.fetchall()]
        except Exception as exc:
            logger.error("get_competitors xatosi: %s", exc)
            return []

    async def remove_competitor(self, channel_username: str) -> bool:
        """Raqobatchi kanalni kuzatuvdan olib tashlash."""
        ch = channel_username.strip().lstrip("@").lower()
        try:
            with self._get_sqlite_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM competitor_channels WHERE channel_username = ?", (ch,))
                conn.commit()
            return True
        except Exception as exc:
            logger.error("remove_competitor xatosi: %s", exc)
            return False

    # ─── 4. STATISTIKA VA AMALLARNI QAYD ETISH (BOT STATS) ─────────

    async def log_event(self, event_type: str, details: str = "") -> None:
        """Amal yoki hodisani statistikaga yozish."""
        try:
            with self._get_sqlite_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO bot_stats (event_type, details)
                    VALUES (?, ?)
                """, (event_type, str(details)[:250]))
                conn.commit()
        except Exception as exc:
            logger.debug("log_event xatosi: %s", exc)

    async def get_stats_summary(self) -> dict:
        """Bugungi va umumiy statistika xulosasi."""
        today_prefix = datetime.date.today().isoformat()
        res = {
            "total_events": 0,
            "today_events": 0,
            "today_user_messages": 0,
            "today_userbot_sends": 0,
            "today_ai_queries": 0,
            "knowledge_count": 0,
            "pending_posts": 0,
            "competitors_count": 0,
        }
        try:
            with self._get_sqlite_conn() as conn:
                cursor = conn.cursor()
                # Umumiy hodisalar
                cursor.execute("SELECT COUNT(*) FROM bot_stats")
                res["total_events"] = cursor.fetchone()[0]

                # Bugungi hodisalar
                cursor.execute("SELECT COUNT(*) FROM bot_stats WHERE created_at LIKE ?", (f"{today_prefix}%",))
                res["today_events"] = cursor.fetchone()[0]

                # Bugungi xabarlar
                cursor.execute("SELECT COUNT(*) FROM bot_stats WHERE event_type = 'user_msg' AND created_at LIKE ?", (f"{today_prefix}%",))
                res["today_user_messages"] = cursor.fetchone()[0]

                # Bugungi userbot yuborgan xabarlari
                cursor.execute("SELECT COUNT(*) FROM bot_stats WHERE event_type = 'userbot_send' AND created_at LIKE ?", (f"{today_prefix}%",))
                res["today_userbot_sends"] = cursor.fetchone()[0]

                # Bugungi AI so'rovlari
                cursor.execute("SELECT COUNT(*) FROM bot_stats WHERE event_type = 'ai_query' AND created_at LIKE ?", (f"{today_prefix}%",))
                res["today_ai_queries"] = cursor.fetchone()[0]

                # Bilimlar soni
                cursor.execute("SELECT COUNT(*) FROM knowledge_base")
                res["knowledge_count"] = cursor.fetchone()[0]

                # Kutilayotgan postlar
                cursor.execute("SELECT COUNT(*) FROM scheduled_posts WHERE status = 'pending'")
                res["pending_posts"] = cursor.fetchone()[0]

                # Raqobatchilar soni
                cursor.execute("SELECT COUNT(*) FROM competitor_channels WHERE active = 1")
                res["competitors_count"] = cursor.fetchone()[0]

        except Exception as exc:
            logger.error("get_stats_summary xatosi: %s", exc)

        return res

    # ─── 5. ESLATMALAR (REMINDERS) ───────────────────────────────

    async def add_reminder(self, chat_id: int | str, text: str, remind_at: str) -> int:
        """Yangi eslatma qo'shish. remind_at formati: 'YYYY-MM-DD HH:MM:SS'."""
        if self.use_supabase and self._supabase_client and self._supabase_reminders_available:
            try:
                loop = asyncio.get_running_loop()
                data = {
                    "chat_id": str(chat_id),
                    "text": text,
                    "remind_at": remind_at,
                    "status": "pending",
                }
                res = await loop.run_in_executor(
                    None,
                    lambda: self._supabase_client.table("reminders").insert(data).execute()
                )
                if res.data:
                    return res.data[0].get("id", 1)
            except Exception as exc:
                err_s = str(exc)
                if "PGRST205" in err_s or "Could not find the table" in err_s:
                    self._supabase_reminders_available = False
                    logger.info("DatabaseManager: Supabase da 'reminders' jadvali mavjud emas. Eslatmalar lokal SQLite bazasida uzluksiz ishlaydi.")
                else:
                    logger.warning("Supabase add_reminder xato: %s. SQLite ga yozilmoqda.", exc)

        loop = asyncio.get_running_loop()
        def _insert():
            with self._get_sqlite_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    "INSERT INTO reminders (chat_id, text, remind_at, status) VALUES (?, ?, ?, 'pending')",
                    (str(chat_id), text, remind_at),
                )
                conn.commit()
                return cur.lastrowid
        return await loop.run_in_executor(None, _insert)

    async def get_due_reminders(self) -> list[dict]:
        """Vaqti kelgan (yuborilishi kerak bo'lgan) faol eslatmalarni qaytaradi."""
        try:
            import zoneinfo
            now_str = datetime.datetime.now(zoneinfo.ZoneInfo("Asia/Tashkent")).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if self.use_supabase and self._supabase_client and self._supabase_reminders_available:
            try:
                loop = asyncio.get_running_loop()
                res = await loop.run_in_executor(
                    None,
                    lambda: self._supabase_client.table("reminders")
                        .select("*")
                        .eq("status", "pending")
                        .lte("remind_at", now_str)
                        .execute()
                )
                if res.data:
                    return res.data
            except Exception as exc:
                err_s = str(exc)
                if "PGRST205" in err_s or "Could not find the table" in err_s or "42703" in err_s or "does not exist" in err_s:
                    self._supabase_reminders_available = False
                    logger.info("DatabaseManager: Supabase 'reminders' jadvalida mos kelmaslik aniqlandi. Eslatmalar lokal SQLite bazasida uzluksiz ishlaydi.")
                else:
                    logger.warning("Supabase get_due_reminders xato: %s. SQLite dan olinmoqda.", exc)

        loop = asyncio.get_running_loop()
        def _query():
            with self._get_sqlite_conn() as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute(
                    "SELECT * FROM reminders WHERE status = 'pending' AND remind_at <= ? ORDER BY remind_at ASC",
                    (now_str,),
                )
                return [dict(r) for r in cur.fetchall()]
        return await loop.run_in_executor(None, _query)

    async def mark_reminder_sent(self, reminder_id: int) -> bool:
        """Eslatmani yuborilgan (sent) deb belgilash."""
        if self.use_supabase and self._supabase_client:
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None,
                    lambda: self._supabase_client.table("reminders").update({"status": "sent"}).eq("id", reminder_id).execute()
                )
            except Exception as exc:
                logger.warning("Supabase mark_reminder_sent xato: %s", exc)

        loop = asyncio.get_running_loop()
        def _update():
            with self._get_sqlite_conn() as conn:
                cur = conn.cursor()
                cur.execute("UPDATE reminders SET status = 'sent' WHERE id = ?", (reminder_id,))
                conn.commit()
                return cur.rowcount > 0
        return await loop.run_in_executor(None, _update)

    async def get_active_reminders(self, chat_id: Optional[int | str] = None) -> list[dict]:
        """Foydalanuvchining hali kelmagan faol eslatmalari ro'yxati (chat_id berilmasa barchasi)."""
        loop = asyncio.get_running_loop()
        def _query():
            with self._get_sqlite_conn() as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                if chat_id is not None:
                    cur.execute(
                        "SELECT * FROM reminders WHERE chat_id = ? AND status = 'pending' ORDER BY remind_at ASC",
                        (str(chat_id),),
                    )
                else:
                    cur.execute(
                        "SELECT * FROM reminders WHERE status = 'pending' ORDER BY remind_at ASC LIMIT 50",
                    )
                return [dict(r) for r in cur.fetchall()]
        return await loop.run_in_executor(None, _query)

    async def delete_reminder(self, reminder_id: int) -> bool:
        """Eslatmani bekor qilish yoki o'chirish."""
        if self.use_supabase and self._supabase_client:
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None,
                    lambda: self._supabase_client.table("reminders").update({"status": "cancelled"}).eq("id", reminder_id).execute()
                )
            except Exception:
                pass

        loop = asyncio.get_running_loop()
        def _delete():
            with self._get_sqlite_conn() as conn:
                cur = conn.cursor()
                cur.execute("UPDATE reminders SET status = 'cancelled' WHERE id = ?", (reminder_id,))
                conn.commit()
                return cur.rowcount > 0
        return await loop.run_in_executor(None, _delete)

    async def snooze_reminder(self, reminder_id: int, minutes: int = 10) -> Optional[str]:
        """Eslatmani X daqiqaga kechiktirish."""
        try:
            import zoneinfo
            new_dt = datetime.datetime.now(zoneinfo.ZoneInfo("Asia/Tashkent")) + datetime.timedelta(minutes=minutes)
        except Exception:
            new_dt = datetime.datetime.now() + datetime.timedelta(minutes=minutes)
        new_time_str = new_dt.strftime("%Y-%m-%d %H:%M:00")

        loop = asyncio.get_running_loop()
        def _snooze():
            with self._get_sqlite_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    "UPDATE reminders SET remind_at = ?, status = 'pending' WHERE id = ?",
                    (new_time_str, reminder_id),
                )
                conn.commit()
                return new_time_str if cur.rowcount > 0 else None
        return await loop.run_in_executor(None, _snooze)

    # ─── 6. BOSHQARILAYOTGAN GURUHLAR VA KANALLAR (MANAGED CHATS) ─

    async def add_or_update_managed_chat(
        self,
        chat_id: int | str,
        title: str,
        chat_type: str,
        username: str = "",
    ) -> bool:
        """Bot qo'shilgan guruh yoki kanalni ro'yxatga oladi yoki yangilaydi."""
        str_id = str(chat_id)
        now_str = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

        # Supabase ga yozishga urinish
        if self.use_supabase and self._supabase_client:
            try:
                loop = asyncio.get_running_loop()
                data = {
                    "chat_id": str_id,
                    "title": title,
                    "chat_type": chat_type,
                    "username": username or "",
                    "is_active": 1,
                    "updated_at": now_str,
                }
                await loop.run_in_executor(
                    None,
                    lambda: self._supabase_client.table("managed_chats").upsert(data, on_conflict="chat_id").execute()
                )
            except Exception as exc:
                logger.warning("Supabase managed_chats xato: %s. SQLite ga yozilmoqda.", exc)

        loop = asyncio.get_running_loop()
        def _upsert():
            with self._get_sqlite_conn() as conn:
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO managed_chats (chat_id, title, chat_type, username, is_active, updated_at)
                    VALUES (?, ?, ?, ?, 1, ?)
                    ON CONFLICT(chat_id) DO UPDATE SET
                        title = excluded.title,
                        chat_type = excluded.chat_type,
                        username = excluded.username,
                        is_active = 1,
                        updated_at = excluded.updated_at
                """, (str_id, title, chat_type, username or "", now_str))
                conn.commit()
                return True
        return await loop.run_in_executor(None, _upsert)

    async def remove_managed_chat(self, chat_id: int | str) -> bool:
        """Bot guruh yoki kanaldan chiqarilganda nofaol (is_active = 0) qilib belgilaydi."""
        str_id = str(chat_id)
        loop = asyncio.get_running_loop()
        def _deactivate():
            with self._get_sqlite_conn() as conn:
                cur = conn.cursor()
                cur.execute("UPDATE managed_chats SET is_active = 0 WHERE chat_id = ?", (str_id,))
                conn.commit()
                return cur.rowcount > 0
        return await loop.run_in_executor(None, _deactivate)

    async def get_managed_chats(self, chat_type: Optional[str] = None) -> list[dict]:
        """Faol boshqarilayotgan guruhlar va kanallar ro'yxati."""
        loop = asyncio.get_running_loop()
        def _query():
            with self._get_sqlite_conn() as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                if chat_type:
                    cur.execute(
                        "SELECT * FROM managed_chats WHERE is_active = 1 AND chat_type = ? ORDER BY id DESC",
                        (chat_type,),
                    )
                else:
                    cur.execute(
                        "SELECT * FROM managed_chats WHERE is_active = 1 ORDER BY id DESC",
                    )
                return [dict(r) for r in cur.fetchall()]
        return await loop.run_in_executor(None, _query)

    async def get_primary_channel(self) -> Optional[dict]:
        """Oxirgi qo'shilgan faol kanalni qaytaradi (avtomatik post chiqarish uchun)."""
        channels = await self.get_managed_chats(chat_type="channel")
        return channels[0] if channels else None

    # ─── 7. DOIMIY SUHBAT XOTIRASI (CHAT HISTORY) ─────────────────

    async def add_chat_message(self, role: str, content: str) -> None:
        """Suhbat xabarini saqlash (Supabase va SQLite)."""
        now_iso = datetime.datetime.utcnow().isoformat()
        if self.use_supabase and self._supabase_client:
            try:
                loop = asyncio.get_running_loop()
                data = {"role": role, "content": content, "created_at": now_iso}
                await loop.run_in_executor(
                    None,
                    lambda: self._supabase_client.table("chat_history").insert(data).execute()
                )
            except Exception:
                pass

        loop = asyncio.get_running_loop()
        def _insert():
            with self._get_sqlite_conn() as conn:
                cur = conn.cursor()
                cur.execute("INSERT INTO chat_history (role, content) VALUES (?, ?)", (role, content))
                conn.commit()
        await loop.run_in_executor(None, _insert)

    async def get_recent_chat_history(self, limit: int = 20) -> list[dict]:
        """Oxirgi suhbat xabarlarini yuklash (restartdan keyin ham eslab qolish uchun)."""
        if self.use_supabase and self._supabase_client:
            try:
                loop = asyncio.get_running_loop()
                res = await loop.run_in_executor(
                    None,
                    lambda: self._supabase_client.table("chat_history")
                        .select("role, content")
                        .order("id", desc=True)
                        .limit(limit)
                        .execute()
                )
                if res.data:
                    return list(reversed(res.data))
            except Exception:
                pass

        loop = asyncio.get_running_loop()
        def _query():
            with self._get_sqlite_conn() as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute(
                    "SELECT role, content FROM chat_history ORDER BY id DESC LIMIT ?",
                    (limit,)
                )
                rows = cur.fetchall()
                return list(reversed([dict(r) for r in rows]))
        return await loop.run_in_executor(None, _query)

    async def clear_chat_history(self) -> None:
        """Suhbat tarixini tozalash."""
        if self.use_supabase and self._supabase_client:
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None,
                    lambda: self._supabase_client.table("chat_history").delete().neq("id", 0).execute()
                )
            except Exception:
                pass

        loop = asyncio.get_running_loop()
        def _clear():
            with self._get_sqlite_conn() as conn:
                conn.execute("DELETE FROM chat_history")
                conn.commit()
        await loop.run_in_executor(None, _clear)


# Global database singleton
db = DatabaseManager()

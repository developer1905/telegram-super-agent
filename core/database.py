"""
core/database.py — Supabase + SQLite Hybrid Doimiy Xotira (RAG & Memory)

Foydalanuvchining shaxsiy faktlari (karta raqamlari, manzil, xizmatlar, narxlar),
kechiktirilgan postlar, raqobatchi kanallar va statistikani doimiy saqlaydi.
Agar SUPABASE_URL va SUPABASE_KEY berilgan bo'lsa Supabase ga yozadi,
aks holda avtomatik lokal SQLite bazasiga tayanadi (Zero-Downtime Fallback).
"""

from __future__ import annotations

import asyncio
import contextlib
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

    def __init__(self, sqlite_path: Optional[str] = None) -> None:
        self.sqlite_path = sqlite_path or SQLITE_PATH
        self.use_supabase = bool(SUPABASE_URL and SUPABASE_KEY) and (sqlite_path is None)
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

    @contextlib.contextmanager
    def _get_sqlite_conn(self):
        """Optimallashtirilgan SQLite ulanishi (30s timeout, busy_timeout va avtomatik close)."""
        conn = sqlite3.connect(self.sqlite_path, timeout=30.0)
        conn.execute("PRAGMA busy_timeout = 15000;")
        try:
            yield conn
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _init_sqlite(self) -> None:
        """Lokal SQLite bazasi va kerakli jadvallarni initsializatsiya qilish."""
        target_dir = os.path.dirname(self.sqlite_path)
        if target_dir:
            os.makedirs(target_dir, exist_ok=True)
        with sqlite3.connect(self.sqlite_path, timeout=30.0) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA journal_mode = WAL;")
            cursor.execute("PRAGMA busy_timeout = 15000;")
            cursor.execute("PRAGMA synchronous = NORMAL;")

            # 1. Knowledge Base (Doimiy xotira — Multi-tenancy qo'llab-quvvatlanadi)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS knowledge_base (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT NOT NULL,
                    content TEXT NOT NULL,
                    category TEXT DEFAULT 'general',
                    user_id TEXT DEFAULT 'admin',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, key)
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

            # LOG_CHANNEL_ID ni avtomatik managed_chats ga kiritish
            try:
                from config import LOG_CHANNEL_ID
                if LOG_CHANNEL_ID:
                    cursor.execute("""
                        INSERT INTO managed_chats (chat_id, title, chat_type, username, is_active)
                        VALUES (?, 'Asosiy Hisobot Kanali', 'channel', '', 1)
                        ON CONFLICT(chat_id) DO UPDATE SET is_active = 1
                    """, (str(LOG_CHANNEL_ID),))
            except Exception:
                pass

            # 7. Chat History (Ko'p chatli doimiy suhbat tarixi — guruh, kanal va shaxsiy chatlar uchun)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS chat_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id TEXT NOT NULL DEFAULT '0',
                    user_id TEXT DEFAULT '',
                    sender_name TEXT DEFAULT '',
                    chat_type TEXT DEFAULT 'private',
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Mavjud eski bazani yangi ustunlar bilan xavfsiz kengaytirish (migration)
            for col, col_def in [
                ("chat_id", "TEXT DEFAULT '0'"),
                ("user_id", "TEXT DEFAULT ''"),
                ("sender_name", "TEXT DEFAULT ''"),
                ("chat_type", "TEXT DEFAULT 'private'"),
            ]:
                try:
                    cursor.execute(f"ALTER TABLE chat_history ADD COLUMN {col} {col_def};")
                except Exception:
                    pass

            try:
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_chat_hist_chat ON chat_history (chat_id, id DESC);")
            except Exception:
                pass

            # 8. Tasks (TodoList & Notion sinxronizatsiyasi)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    due_date TEXT DEFAULT '',
                    status TEXT DEFAULT 'pending',
                    notion_page_id TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 9. Uptime Monitors (Veb-saytlar monitoringi)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS uptime_monitors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT UNIQUE NOT NULL,
                    name TEXT DEFAULT '',
                    is_active INTEGER DEFAULT 1,
                    last_status INTEGER DEFAULT 0,
                    last_checked TEXT DEFAULT '',
                    response_ms REAL DEFAULT 0.0,
                    alert_sent INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 10. Astrology Profiles (Shaxsiy Natal Karta va Astrologik Xotira)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS astrology_profiles (
                    user_id TEXT PRIMARY KEY,
                    birth_date TEXT NOT NULL,
                    birth_time TEXT NOT NULL,
                    city TEXT NOT NULL,
                    chart_json TEXT NOT NULL,
                    custom_lots_json TEXT DEFAULT '[]',
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            try:
                cursor.execute("ALTER TABLE astrology_profiles ADD COLUMN custom_lots_json TEXT DEFAULT '[]'")
            except Exception:
                pass

            # Multi-tenancy va Data Ownership: user_id ustunlari va indekslari
            for alter_sql in [
                "ALTER TABLE knowledge_base ADD COLUMN user_id TEXT DEFAULT 'admin';",
                "ALTER TABLE tasks ADD COLUMN user_id TEXT DEFAULT 'admin';",
                "ALTER TABLE uptime_monitors ADD COLUMN user_id TEXT DEFAULT 'admin';",
                "ALTER TABLE reminders ADD COLUMN user_id TEXT DEFAULT '';",
            ]:
                try:
                    cursor.execute(alter_sql)
                except Exception:
                    pass

            # Agar eski bazada key ustida qat'iy global UNIQUE constraint bo'lsa, uni user_id + key ga yangilash
            try:
                cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='knowledge_base';")
                row = cursor.fetchone()
                if row and row[0] and "key TEXT UNIQUE" in row[0]:
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS knowledge_base_v2 (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            key TEXT NOT NULL,
                            content TEXT NOT NULL,
                            category TEXT DEFAULT 'general',
                            user_id TEXT DEFAULT 'admin',
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            UNIQUE(user_id, key)
                        );
                    """)
                    cursor.execute("""
                        INSERT OR IGNORE INTO knowledge_base_v2 (id, key, content, category, user_id, created_at, updated_at)
                        SELECT id, key, content, category, COALESCE(user_id, 'admin'), created_at, updated_at FROM knowledge_base;
                    """)
                    cursor.execute("DROP TABLE knowledge_base;")
                    cursor.execute("ALTER TABLE knowledge_base_v2 RENAME TO knowledge_base;")
            except Exception as e:
                logger.warning("knowledge_base schema v2 migration: %s", e)

            for idx_sql in [
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_kb_user_key ON knowledge_base (user_id, key);",
                "CREATE INDEX IF NOT EXISTS idx_tasks_user ON tasks (user_id, status);",
                "CREATE INDEX IF NOT EXISTS idx_uptime_user ON uptime_monitors (user_id);",
                "CREATE INDEX IF NOT EXISTS idx_reminders_user ON reminders (user_id, status);",
            ]:
                try:
                    cursor.execute(idx_sql)
                except Exception:
                    pass

            # Mavjud faktlarni admin ID ga avtomatik bog'lash
            from config import ADMIN_ID
            admin_id_str = str(ADMIN_ID).strip() if ADMIN_ID else "admin"
            try:
                cursor.execute("UPDATE knowledge_base SET user_id = ? WHERE user_id = 'admin';", (admin_id_str,))
            except Exception:
                pass

            conn.commit()

    # ─── 1. SHAXSIY MA'LUMOTLAR BAZASI (KNOWLEDGE BASE / RAG) ──────

    async def save_fact(self, key: str, content: str, category: str = "general", user_id: str = "admin") -> bool:
        """Doimiy faktni saqlash (masalan: 'card_number', 'company_services', 'resume')."""
        key_clean = key.strip().lower()
        user_id_clean = str(user_id or "admin").strip()
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # Supabase ga yozishga urinish
        if self.use_supabase and self._supabase_client:
            try:
                loop = asyncio.get_running_loop()
                data = {
                    "key": key_clean,
                    "content": content,
                    "category": category,
                    "user_id": user_id_clean,
                    "updated_at": now_iso,
                }
                await loop.run_in_executor(
                    None,
                    lambda: self._supabase_client.table("knowledge_base").upsert(data, on_conflict="key").execute()
                )
                logger.info("Supabase: Fakt saqlandi: '%s'", key_clean)
            except Exception as exc:
                try:
                    data_no_uid = {
                        "key": key_clean,
                        "content": content,
                        "category": category,
                        "updated_at": now_iso,
                    }
                    await loop.run_in_executor(
                        None,
                        lambda: self._supabase_client.table("knowledge_base").upsert(data_no_uid, on_conflict="key").execute()
                    )
                    logger.info("Supabase: Fakt saqlandi (user_id siz): '%s'", key_clean)
                except Exception as exc2:
                    logger.warning("Supabase xatosi, SQLite ga yozilmoqda: %s", exc2)

        # Har doim lokal SQLite ga ham yozib qo'yamiz (tezkor kesh va oflayn ishlash uchun)
        try:
            with self._get_sqlite_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO knowledge_base (key, content, category, user_id, updated_at)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(user_id, key) DO UPDATE SET
                        content = excluded.content,
                        category = excluded.category,
                        updated_at = CURRENT_TIMESTAMP
                """, (key_clean, content, category, user_id_clean))
                conn.commit()
            return True
        except Exception as exc:
            logger.error("SQLite save_fact xatosi: %s", exc)
            return False

    async def get_all_facts(self, user_id: Optional[str] = None) -> list[dict]:
        """Saqlangan faktlarni olish (user_id ko'rsatilsa, faqat shu foydalanuvchining ma'lumotlari)."""
        from config import ADMIN_ID
        admin_id_str = str(ADMIN_ID).strip() if ADMIN_ID else "admin"

        user_id_str = str(user_id).strip() if user_id is not None else None
        is_admin_user = (user_id_str is None) or (user_id_str in (admin_id_str, "admin"))

        if self.use_supabase and self._supabase_client:
            try:
                loop = asyncio.get_running_loop()
                def _sb_fetch():
                    q = self._supabase_client.table("knowledge_base").select("*")
                    if user_id_str is not None and not is_admin_user:
                        q = q.eq("user_id", user_id_str)
                    return q.execute()
                res = await loop.run_in_executor(None, _sb_fetch)
                if res.data:
                    # Supabase dagi faktlarni lokal SQLite ga zudlik bilan sinxronlaymiz
                    def _sync_to_sqlite(facts_list):
                        try:
                            with self._get_sqlite_conn() as conn:
                                cur = conn.cursor()
                                for f in facts_list:
                                    k = str(f.get("key", "")).strip().lower()
                                    c = str(f.get("content", ""))
                                    cat = str(f.get("category", "general"))
                                    u = str(f.get("user_id", "admin"))
                                    if k and c:
                                        cur.execute("""
                                            INSERT INTO knowledge_base (key, content, category, user_id, updated_at)
                                            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                                            ON CONFLICT(user_id, key) DO UPDATE SET
                                                content = excluded.content,
                                                category = excluded.category,
                                                updated_at = CURRENT_TIMESTAMP
                                        """, (k, c, cat, u))
                                conn.commit()
                        except Exception as sync_e:
                            logger.debug("Lokal SQLite knowledge_base kesh xatosi: %s", sync_e)
                    await loop.run_in_executor(None, lambda: _sync_to_sqlite(res.data))
                    return res.data
            except Exception as exc:
                logger.warning("Supabase get_all_facts xatosi: %s. SQLite dan olinmoqda.", exc)

        try:
            with self._get_sqlite_conn() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                if user_id_str is not None:
                    if is_admin_user:
                        cursor.execute(
                            "SELECT key, content, category, user_id, updated_at FROM knowledge_base WHERE user_id = ? OR user_id = 'admin' OR user_id = ? ORDER BY updated_at DESC",
                            (user_id_str, admin_id_str)
                        )
                    else:
                        cursor.execute(
                            "SELECT key, content, category, user_id, updated_at FROM knowledge_base WHERE user_id = ? ORDER BY updated_at DESC",
                            (user_id_str,)
                        )
                else:
                    cursor.execute("SELECT key, content, category, user_id, updated_at FROM knowledge_base ORDER BY updated_at DESC")
                rows = cursor.fetchall()
                return [dict(r) for r in rows]
        except Exception as exc:
            logger.error("SQLite get_all_facts xatosi: %s", exc)
            return []

    async def delete_fact(self, key: str, user_id: Optional[str] = None) -> bool:
        """Faktni o'chirish (user_id ko'rsatilsa faqat o'sha foydalanuvchining fakti o'chiriladi)."""
        key_clean = key.strip().lower()
        user_id_str = str(user_id).strip() if user_id is not None else None
        if self.use_supabase and self._supabase_client:
            try:
                loop = asyncio.get_running_loop()
                def _sb_del():
                    q = self._supabase_client.table("knowledge_base").delete().eq("key", key_clean)
                    if user_id_str is not None and user_id_str != "admin":
                        q = q.eq("user_id", user_id_str)
                    return q.execute()
                await loop.run_in_executor(None, _sb_del)
            except Exception as exc:
                logger.warning("Supabase delete_fact xatosi: %s", exc)

        try:
            with self._get_sqlite_conn() as conn:
                cursor = conn.cursor()
                if user_id_str is not None and user_id_str != "admin":
                    cursor.execute("DELETE FROM knowledge_base WHERE key = ? AND user_id = ?", (key_clean, user_id_str))
                else:
                    cursor.execute("DELETE FROM knowledge_base WHERE key = ?", (key_clean,))
                conn.commit()
            return True
        except Exception as exc:
            logger.error("SQLite delete_fact xatosi: %s", exc)
            return False

    async def build_rag_context(self, user_id: Optional[str] = None, context_type: str = "private") -> str:
        """AI promptiga qo'shish uchun doimiy xotiradagi faktlarni formatlash.
        
        Qat'iy xavfsizlik qoidasi:
        - Agar context_type 'group', 'supergroup' yoki 'channel' bo'lsa, shaxsiy faktlar HECH QACHON kiritilmaydi (bo'sh satr qaytaradi).
        - Agar user_id ko'rsatilsa, faqat shu foydalanuvchining shaxsiy faktlari qaytariladi.
        """
        if context_type in ("group", "supergroup", "channel"):
            return ""

        facts = await self.get_all_facts(user_id=user_id)
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
            "managed_chats_count": 0,
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

                # Bilimlar soni (Lokal SQLite)
                cursor.execute("SELECT COUNT(*) FROM knowledge_base")
                res["knowledge_count"] = cursor.fetchone()[0]

                # Kutilayotgan postlar
                cursor.execute("SELECT COUNT(*) FROM scheduled_posts WHERE status = 'pending'")
                res["pending_posts"] = cursor.fetchone()[0]

                # Raqobatchilar soni
                cursor.execute("SELECT COUNT(*) FROM competitor_channels WHERE active = 1")
                res["competitors_count"] = cursor.fetchone()[0]

                # Boshqarilayotgan kanallar va guruhlar soni
                cursor.execute("SELECT COUNT(*) FROM managed_chats WHERE is_active = 1")
                res["managed_chats_count"] = cursor.fetchone()[0]

        except Exception as exc:
            logger.error("get_stats_summary xatosi: %s", exc)

        # Supabase ga ulangan bo'lsa, xotira sonini tekshirib maksimal qiymatni olamiz
        if self.use_supabase and self._supabase_client:
            try:
                loop = asyncio.get_running_loop()
                def _sb_count():
                    c_res = self._supabase_client.table("knowledge_base").select("key", count="exact").execute()
                    return c_res.count if c_res and c_res.count is not None else 0
                sb_cnt = await loop.run_in_executor(None, _sb_count)
                if sb_cnt > 0:
                    res["knowledge_count"] = max(res["knowledge_count"], sb_cnt)
            except Exception as sb_err:
                logger.debug("get_stats_summary Supabase knowledge count xatosi: %s", sb_err)

        return res

    # ─── 5. ESLATMALAR (REMINDERS) ───────────────────────────────

    async def add_reminder(self, chat_id: int | str, text: str, remind_at: str, user_id: Optional[int | str] = None) -> int:
        """Yangi eslatma qo'shish. remind_at formati: 'YYYY-MM-DD HH:MM:SS'."""
        user_id_str = str(user_id or chat_id).strip()
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
                    "INSERT INTO reminders (chat_id, text, remind_at, status, user_id) VALUES (?, ?, ?, 'pending', ?)",
                    (str(chat_id), text, remind_at, user_id_str),
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

    async def get_active_reminders(self, chat_id: Optional[int | str] = None, user_id: Optional[int | str] = None) -> list[dict]:
        """Foydalanuvchining hali kelmagan faol eslatmalari ro'yxati (chat_id yoki user_id bo'yicha)."""
        target_id = str(user_id or chat_id).strip() if (user_id is not None or chat_id is not None) else None
        loop = asyncio.get_running_loop()
        def _query():
            with self._get_sqlite_conn() as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                if target_id is not None:
                    cur.execute(
                        "SELECT * FROM reminders WHERE (chat_id = ? OR user_id = ?) AND status = 'pending' ORDER BY remind_at ASC",
                        (target_id, target_id),
                    )
                else:
                    cur.execute(
                        "SELECT * FROM reminders WHERE status = 'pending' ORDER BY remind_at ASC LIMIT 50",
                    )
                return [dict(r) for r in cur.fetchall()]
        return await loop.run_in_executor(None, _query)

    async def delete_reminder(self, reminder_id: int, user_id: Optional[int | str] = None) -> bool:
        """Eslatmani bekor qilish yoki o'chirish (agar user_id berilsa, mulkdorlik tekshiriladi)."""
        user_id_str = str(user_id).strip() if user_id is not None else None
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
                if user_id_str and user_id_str != "admin":
                    cur.execute("UPDATE reminders SET status = 'cancelled' WHERE id = ? AND (user_id = ? OR chat_id = ?)", (reminder_id, user_id_str, user_id_str))
                else:
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

        # LOG_CHANNEL_ID mavjud bo'lsa va bazada hali kiritilmagan bo'lsa, avtomatik kiritish
        from config import LOG_CHANNEL_ID
        if LOG_CHANNEL_ID:
            str_log_id = str(LOG_CHANNEL_ID)
            def _ensure_log_channel():
                try:
                    with self._get_sqlite_conn() as conn:
                        cur = conn.cursor()
                        cur.execute("SELECT 1 FROM managed_chats WHERE chat_id = ?", (str_log_id,))
                        if not cur.fetchone():
                            cur.execute("""
                                INSERT INTO managed_chats (chat_id, title, chat_type, username, is_active)
                                VALUES (?, 'Asosiy Hisobot Kanali', 'channel', '', 1)
                            """, (str_log_id,))
                            conn.commit()
                except Exception:
                    pass
            await loop.run_in_executor(None, _ensure_log_channel)

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

    async def add_chat_message(
        self,
        role: str,
        content: str,
        chat_id: str = "0",
        user_id: str = "",
        sender_name: str = "",
        chat_type: str = "private",
    ) -> None:
        """Suhbat xabarini chat_id bo'yicha saqlash (Supabase va SQLite)."""
        now_iso = datetime.datetime.utcnow().isoformat()
        chat_id_str = str(chat_id)
        if self.use_supabase and self._supabase_client and self._supabase_chats_available:
            try:
                loop = asyncio.get_running_loop()
                data = {
                    "chat_id": chat_id_str,
                    "user_id": str(user_id),
                    "sender_name": sender_name,
                    "chat_type": chat_type,
                    "role": role,
                    "content": content,
                    "created_at": now_iso,
                }
                await loop.run_in_executor(
                    None,
                    lambda: self._supabase_client.table("chat_history").insert(data).execute()
                )
            except Exception as e:
                logger.warning("Supabase 'chat_history' xatosi (%s). Chat xotirasi SQLite ga o'tkazildi.", e)
                self._supabase_chats_available = False

        loop = asyncio.get_running_loop()
        def _insert():
            with self._get_sqlite_conn() as conn:
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO chat_history (chat_id, user_id, sender_name, chat_type, role, content)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (chat_id_str, str(user_id), sender_name, chat_type, role, content))
                conn.commit()
        await loop.run_in_executor(None, _insert)

    async def get_recent_chat_history(self, chat_id: Optional[str] = None, limit: int = 30) -> list[dict]:
        """Oxirgi suhbat xabarlarini chat_id bo'yicha yuklash."""
        chat_id_str = str(chat_id) if chat_id is not None else None
        if self.use_supabase and self._supabase_client and self._supabase_chats_available:
            try:
                loop = asyncio.get_running_loop()
                def _sb_query():
                    q = self._supabase_client.table("chat_history").select("role, content, sender_name, chat_id, created_at")
                    if chat_id_str is not None:
                        q = q.eq("chat_id", chat_id_str)
                    return q.order("id", desc=True).limit(limit).execute()
                res = await loop.run_in_executor(None, _sb_query)
                if res and hasattr(res, "data") and res.data:
                    return list(reversed(res.data))
            except Exception as e:
                logger.warning("Supabase 'chat_history' o'qishda xato (%s). Chat xotirasi SQLite ga o'tkazildi.", e)
                self._supabase_chats_available = False

        loop = asyncio.get_running_loop()
        def _query():
            with self._get_sqlite_conn() as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                if chat_id_str is not None:
                    cur.execute(
                        "SELECT role, content, sender_name, chat_id, created_at FROM chat_history WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
                        (chat_id_str, limit)
                    )
                else:
                    cur.execute(
                        "SELECT role, content, sender_name, chat_id, created_at FROM chat_history ORDER BY id DESC LIMIT ?",
                        (limit,)
                    )
                rows = cur.fetchall()
                return list(reversed([dict(r) for r in rows]))
        return await loop.run_in_executor(None, _query)

    async def clear_chat_history(self, chat_id: Optional[str] = None) -> None:
        """Suhbat tarixini tozalash (chat_id berilsa faqat o'sha chat, berilmasa barchasi)."""
        chat_id_str = str(chat_id) if chat_id is not None else None
        if self.use_supabase and self._supabase_client:
            try:
                loop = asyncio.get_running_loop()
                def _sb_delete():
                    q = self._supabase_client.table("chat_history").delete()
                    if chat_id_str is not None:
                        return q.eq("chat_id", chat_id_str).execute()
                    return q.neq("id", 0).execute()
                await loop.run_in_executor(None, _sb_delete)
            except Exception:
                pass

        loop = asyncio.get_running_loop()
        def _clear():
            with self._get_sqlite_conn() as conn:
                if chat_id_str is not None:
                    conn.execute("DELETE FROM chat_history WHERE chat_id = ?", (chat_id_str,))
                else:
                    conn.execute("DELETE FROM chat_history")
                conn.commit()
        await loop.run_in_executor(None, _clear)

    # ─── 8. TODOLIST VA VAZIFALAR (TASKS) ──────────────────────────

    async def add_task(self, user_id: "int | str | None" = None, title: str = "", description: str = "", due_date: str = "", notion_page_id: str = "") -> int:
        """Yangi vazifa qo'shish."""
        if title == "" and user_id is not None and not isinstance(user_id, int):
            title = str(user_id)
            user_id = "admin"
        actual_title = title.strip() if title else ""
        if not actual_title:
            return 0
        actual_user_id = str(user_id or "admin").strip()
        loop = asyncio.get_running_loop()
        def _insert():
            with self._get_sqlite_conn() as conn:
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO tasks (title, description, due_date, status, notion_page_id, user_id)
                    VALUES (?, ?, ?, 'pending', ?, ?)
                """, (actual_title, description.strip(), due_date.strip(), notion_page_id.strip(), actual_user_id))
                conn.commit()
                return cur.lastrowid or 0
        return await loop.run_in_executor(None, _insert)

    async def get_tasks(self, user_id: "int | str | None" = None, status: str = "pending", limit: int = 50) -> list[dict]:
        """Vazifalar ro'yxatini olish (user_id ko'rsatilsa faqat shu userning vazifalari)."""
        actual_user_id = str(user_id).strip() if user_id is not None else None
        loop = asyncio.get_running_loop()
        def _get():
            with self._get_sqlite_conn() as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                if actual_user_id:
                    if status == "all":
                        cur.execute("SELECT * FROM tasks WHERE user_id = ? ORDER BY id DESC LIMIT ?", (actual_user_id, limit))
                    else:
                        cur.execute("SELECT * FROM tasks WHERE user_id = ? AND status = ? ORDER BY id DESC LIMIT ?", (actual_user_id, status, limit))
                else:
                    if status == "all":
                        cur.execute("SELECT * FROM tasks ORDER BY id DESC LIMIT ?", (limit,))
                    else:
                        cur.execute("SELECT * FROM tasks WHERE status = ? ORDER BY id DESC LIMIT ?", (status, limit))
                return [dict(r) for r in cur.fetchall()]
        return await loop.run_in_executor(None, _get)

    async def complete_task(self, task_id: int, user_id: "int | str | None" = None) -> bool:
        """Vazifani bajarilgan (completed) deb belgilash."""
        actual_user_id = str(user_id).strip() if user_id is not None else None
        loop = asyncio.get_running_loop()
        def _update():
            with self._get_sqlite_conn() as conn:
                cur = conn.cursor()
                if actual_user_id and actual_user_id != "admin":
                    cur.execute("UPDATE tasks SET status = 'completed', updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?", (task_id, actual_user_id))
                else:
                    cur.execute("UPDATE tasks SET status = 'completed', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (task_id,))
                conn.commit()
                return cur.rowcount > 0
        return await loop.run_in_executor(None, _update)

    async def delete_task(self, task_id: int, user_id: "int | str | None" = None) -> bool:
        """Vazifani butunlay o'chirish."""
        actual_user_id = str(user_id).strip() if user_id is not None else None
        loop = asyncio.get_running_loop()
        def _del():
            with self._get_sqlite_conn() as conn:
                cur = conn.cursor()
                if actual_user_id and actual_user_id != "admin":
                    cur.execute("DELETE FROM tasks WHERE id = ? AND user_id = ?", (task_id, actual_user_id))
                else:
                    cur.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
                conn.commit()
                return cur.rowcount > 0
        return await loop.run_in_executor(None, _del)

    # ─── 9. UPTIME MONITORINGI ─────────────────────────────────────

    async def add_uptime_monitor(self, user_id: "int | str | None" = None, url: str = "", name: str = "") -> int:
        """Kuzatuvga yangi veb-sayt yoki API URL qo'shish."""
        loop = asyncio.get_running_loop()
        clean_url = url.strip()
        if not clean_url.startswith(("http://", "https://")):
            clean_url = f"https://{clean_url}"
        clean_name = name.strip() or clean_url.replace("https://", "").replace("http://", "").split("/")[0]
        actual_user_id = str(user_id or "admin").strip()

        def _add():
            with self._get_sqlite_conn() as conn:
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO uptime_monitors (url, name, is_active, last_status, last_checked, user_id)
                    VALUES (?, ?, 1, 0, '', ?)
                    ON CONFLICT(url) DO UPDATE SET
                        name = excluded.name,
                        is_active = 1,
                        user_id = excluded.user_id
                """, (clean_url, clean_name, actual_user_id))
                conn.commit()
                return cur.lastrowid or 0
        return await loop.run_in_executor(None, _add)

    async def get_uptime_monitors(self, user_id: "int | str | None" = None, active_only: bool = True) -> list[dict]:
        """Kuzatilayotgan barcha saytlarni olish (user_id ko'rsatilsa faqat o'sha foydalanuvchining saytlari)."""
        actual_user_id = str(user_id).strip() if user_id is not None else None
        loop = asyncio.get_running_loop()
        def _get():
            with self._get_sqlite_conn() as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                if actual_user_id and actual_user_id != "admin":
                    if active_only:
                        cur.execute("SELECT * FROM uptime_monitors WHERE is_active = 1 AND user_id = ? ORDER BY id ASC", (actual_user_id,))
                    else:
                        cur.execute("SELECT * FROM uptime_monitors WHERE user_id = ? ORDER BY id ASC", (actual_user_id,))
                else:
                    if active_only:
                        cur.execute("SELECT * FROM uptime_monitors WHERE is_active = 1 ORDER BY id ASC")
                    else:
                        cur.execute("SELECT * FROM uptime_monitors ORDER BY id ASC")
                return [dict(r) for r in cur.fetchall()]
        return await loop.run_in_executor(None, _get)

    async def update_uptime_status(self, monitor_id: int, status_code: int, response_ms: float, alert_sent: int = 0) -> bool:
        """Sayt tekshiruv natijasini yangilash."""
        loop = asyncio.get_running_loop()
        def _upd():
            with self._get_sqlite_conn() as conn:
                cur = conn.cursor()
                now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                cur.execute("""
                    UPDATE uptime_monitors
                    SET last_status = ?, response_ms = ?, last_checked = ?, alert_sent = ?
                    WHERE id = ?
                """, (status_code, response_ms, now_str, alert_sent, monitor_id))
                conn.commit()
                return cur.rowcount > 0
        return await loop.run_in_executor(None, _upd)

    async def delete_uptime_monitor(self, monitor_id: int, user_id: "int | str | None" = None) -> bool:
        """Saytni kuzatuvdan o'chirish."""
        actual_user_id = str(user_id).strip() if user_id is not None else None
        loop = asyncio.get_running_loop()
        def _del():
            with self._get_sqlite_conn() as conn:
                cur = conn.cursor()
                if actual_user_id and actual_user_id != "admin":
                    cur.execute("DELETE FROM uptime_monitors WHERE id = ? AND user_id = ?", (monitor_id, actual_user_id))
                else:
                    cur.execute("DELETE FROM uptime_monitors WHERE id = ?", (monitor_id,))
                conn.commit()
                return cur.rowcount > 0
        return await loop.run_in_executor(None, _del)

    # ─── 10. ASTROLOGIYA VA NATAL KARTA PROFILLARI ─────────────────

    async def save_astrology_profile(self, user_id: str, birth_date: str, birth_time: str, city: str, chart_data: dict) -> bool:
        """Foydalanuvchining shaxsiy astrologik profili va hisoblangan kartasini saqlash."""
        loop = asyncio.get_running_loop()
        u_id = str(user_id)
        chart_str = json.dumps(chart_data, ensure_ascii=False)
        def _save():
            with self._get_sqlite_conn() as conn:
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO astrology_profiles (user_id, birth_date, birth_time, city, chart_json, updated_at)
                    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(user_id) DO UPDATE SET
                        birth_date = excluded.birth_date,
                        birth_time = excluded.birth_time,
                        city = excluded.city,
                        chart_json = excluded.chart_json,
                        updated_at = CURRENT_TIMESTAMP
                """, (u_id, birth_date, birth_time, city, chart_str))
                conn.commit()
                return True
        return await loop.run_in_executor(None, _save)

    async def get_astrology_profile(self, user_id: str) -> Optional[dict]:
        """Foydalanuvchining shaxsiy astrologik kartasini olish."""
        loop = asyncio.get_running_loop()
        u_id = str(user_id)
        def _get():
            with self._get_sqlite_conn() as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute("SELECT * FROM astrology_profiles WHERE user_id = ? LIMIT 1", (u_id,))
                row = cur.fetchone()
                if not row:
                    return None
                if row:
                    res = dict(row)
                    try:
                        res["chart"] = json.loads(res.get("chart_json") or "{}")
                    except Exception:
                        res["chart"] = {}
                    try:
                        res["custom_lots"] = json.loads(res.get("custom_lots_json") or "[]")
                    except Exception:
                        res["custom_lots"] = []
                    return res
                return None
        return await loop.run_in_executor(None, _get)

    async def save_custom_lots(self, user_id: str, lots: list) -> bool:
        """Foydalanuvchining 513 tagacha bo'lgan maxsus Arab Lotlarini saqlash."""
        loop = asyncio.get_running_loop()
        u_id = str(user_id)
        lots_str = json.dumps(lots, ensure_ascii=False)
        def _save_lots():
            with self._get_sqlite_conn() as conn:
                cur = conn.cursor()
                # Avval profil bormi tekshiramiz
                cur.execute("SELECT user_id FROM astrology_profiles WHERE user_id = ?", (u_id,))
                if cur.fetchone():
                    cur.execute("UPDATE astrology_profiles SET custom_lots_json = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?", (lots_str, u_id))
                else:
                    # Agar profil bo'lmasa, dastlabki bo'sh profil bilan yaratamiz
                    cur.execute("""
                        INSERT INTO astrology_profiles (user_id, birth_date, birth_time, city, chart_json, custom_lots_json, updated_at)
                        VALUES (?, '2000-01-01', '12:00', 'Toshkent', '{}', ?, CURRENT_TIMESTAMP)
                    """, (u_id, lots_str))
                conn.commit()
                return True
        return await loop.run_in_executor(None, _save_lots)


# Global database singleton
db = DatabaseManager()

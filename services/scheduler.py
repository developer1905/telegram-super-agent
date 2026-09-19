"""
services/scheduler.py — Kunlik Log va Hisobot Xizmati

Kun davomida foydalanuvchi faoliyatini xotiraga yig'adi.
Har kuni soat 21:00 da AI yordamida kunlik hisobot tayyorlab,
adminga va log kanaliga yuboradi.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config import ADMIN_ID, LOG_CHANNEL_ID, REPORT_HOUR, REPORT_MINUTE, UPTIME_CHECK_INTERVAL

if TYPE_CHECKING:
    from aiogram import Bot
    from core.ai_manager import AIManager

logger = logging.getLogger(__name__)


# ─── Log Yozuvi ──────────────────────────────────────────────

@dataclass
class LogEntry:
    """Bitta faoliyat yozuvi."""
    timestamp: datetime
    action_type: str   # "message", "file", "photo", "userbot", "model_switch", "role_switch"
    description: str
    model_used: str = "unknown"


# ─── Log Yig'uvchi ────────────────────────────────────────────

class LogCollector:
    """
    Kunlik faoliyat loglarini xotiraga yig'adi.
    Singleton pattern — butun loyihada bitta nusxasi ishlatiladi.
    """

    _instance: Optional["LogCollector"] = None

    def __new__(cls) -> "LogCollector":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._logs: list[LogEntry] = []
        return cls._instance

    def add(
        self,
        action_type: str,
        description: str,
        model_used: str = "unknown",
    ) -> None:
        """Log yozuvi qo'shadi."""
        entry = LogEntry(
            timestamp=datetime.now(),
            action_type=action_type,
            description=description,
            model_used=model_used,
        )
        self._logs.append(entry)
        logger.debug("Log qo'shildi: [%s] %s", action_type, description)

    def get_today_logs(self) -> list[LogEntry]:
        """Bugungi kun loglarini qaytaradi."""
        today = datetime.now().date()
        return [e for e in self._logs if e.timestamp.date() == today]

    def clear_today(self) -> int:
        """Bugungi loglarni tozalab, soni qaytaradi."""
        today = datetime.now().date()
        before = len(self._logs)
        self._logs = [e for e in self._logs if e.timestamp.date() != today]
        return before - len(self._logs)

    def build_summary_text(self) -> str:
        """Bugungi loglar asosida hisobot matnini tuzadi."""
        logs = self.get_today_logs()
        if not logs:
            return "Bugun hech qanday faoliyat qayd etilmadi."

        # Statistika
        action_counts: dict[str, int] = {}
        model_counts: dict[str, int] = {}
        for entry in logs:
            action_counts[entry.action_type] = action_counts.get(entry.action_type, 0) + 1
            model_counts[entry.model_used] = model_counts.get(entry.model_used, 0) + 1

        lines = [f"📊 **{datetime.now().strftime('%d-%m-%Y')} — Kunlik Faoliyat**\n"]
        lines.append(f"📝 **Jami faoliyatlar:** {len(logs)} ta\n")

        # Turlari bo'yicha
        type_labels = {
            "message": "💬 Matn so'rovlari",
            "file": "📄 Fayl tahrirlash",
            "photo": "🖼 Rasm tahrirlash",
            "userbot": "📡 Userbot xabarlari",
            "model_switch": "🔄 Model almashtirishlar",
            "role_switch": "🎭 Rol almashtirishlar",
            "post": "📢 Kanal postlari",
        }
        lines.append("**Faoliyat turlari:**")
        for atype, count in sorted(action_counts.items(), key=lambda x: x[1], reverse=True):
            label = type_labels.get(atype, atype)
            lines.append(f"  • {label}: {count} ta")

        # Modellar bo'yicha
        lines.append("\n**AI Modellari qo'llanilishi:**")
        for model, count in sorted(model_counts.items(), key=lambda x: x[1], reverse=True):
            lines.append(f"  • `{model}`: {count} marta")

        # So'nggi 5 ta faoliyat
        recent = logs[-5:]
        lines.append("\n**So'nggi 5 ta faoliyat:**")
        for entry in recent:
            time_str = entry.timestamp.strftime("%H:%M")
            lines.append(f"  `{time_str}` [{entry.action_type}] {entry.description[:60]}")

        return "\n".join(lines)


# ─── Hisobot Generatori ───────────────────────────────────────

async def generate_and_send_report(bot: "Bot", ai_manager: "AIManager") -> None:
    """
    APScheduler tomonidan chaqiriladigan asosiy vazifa.
    AI yordamida hisobot tayyorlab, adminga va log kanaliga yuboradi.
    """
    logger.info("Kunlik hisobot tayyorlanmoqda...")
    collector = LogCollector()

    raw_summary = collector.build_summary_text()

    # AI bilan hisobotni boyitamiz
    ai_prompt = (
        f"Quyidagi kunlik faoliyat statistikasini tahlil qilib, "
        f"professional hisobot yoz (O'zbekcha). "
        f"Statistika:\n\n{raw_summary}\n\n"
        f"Hisobotga qo'sh: 1) Asosiy xulosalar, 2) Samaradorlik bahosi, "
        f"3) Ertangi kun uchun tavsiyalar. Qisqa va aniq bo'lsin."
    )

    try:
        ai_report = await ai_manager.generate(ai_prompt)
    except Exception as exc:
        logger.error("Hisobot AI generatsiyasida xato: %s", exc)
        ai_report = "(AI hisobot yozishda xato yuz berdi)"

    date_str = datetime.now().strftime("%d.%m.%Y")
    full_report = (
        f"📋 **KUNLIK HISOBOT — {date_str}**\n"
        f"{'─' * 35}\n\n"
        f"{raw_summary}\n\n"
        f"{'─' * 35}\n"
        f"🧠 **AI Tahlili:**\n{ai_report}"
    )

    # Adminga yuborish
    try:
        await bot.send_message(
            chat_id=ADMIN_ID,
            text=full_report[:4096],
            parse_mode="Markdown",
        )
        logger.info("Hisobot adminga yuborildi: %s", ADMIN_ID)
    except Exception as exc:
        logger.error("Hisobotni adminga yuborishda xato: %s", exc)

    # Log kanaliga yuborish (agar sozlangan bo'lsa)
    if LOG_CHANNEL_ID and LOG_CHANNEL_ID != 0:
        try:
            await bot.send_message(
                chat_id=LOG_CHANNEL_ID,
                text=full_report[:4096],
                parse_mode="Markdown",
            )
            logger.info("Hisobot log kanaliga yuborildi: %s", LOG_CHANNEL_ID)
        except Exception as exc:
            logger.error("Hisobotni kanalga yuborishda xato: %s", exc)

    # Kunlik loglarni tozalash
    cleared = collector.clear_today()
    logger.info("Kunlik loglar tozalandi: %d ta yozuv", cleared)


# ─── Email Avtomatik Tekshiruv ────────────────────────────────

_seen_email_ids: set[str] = set()


async def check_new_emails_job(bot: "Bot", ai_manager: "AIManager") -> None:
    """
    Davriy ravishda yangi kelgan xatlarni tekshiradi.
    Yangi muhim xat kelsa, adminga AI xulosasi bilan xabar beradi.
    """
    from core.email_agent import EmailAgent

    agent = EmailAgent()
    if not agent.is_configured():
        return

    try:
        unread = await agent.fetch_unread(limit=5)
        if not unread:
            return

        global _seen_email_ids
        new_items = [e for e in unread if e.msg_id not in _seen_email_ids]

        if not new_items:
            return

        for item in new_items:
            _seen_email_ids.add(item.msg_id)

        # Xabarnoma tayyorlash
        summary = await agent.analyze_inbox(new_items, ai_manager)
        text = (
            f"🔔 **Pochtaga yangi xat keldi!**\n\n"
            f"{summary}\n\n"
            f"💡 Javob yozish uchun: `email ai: {new_items[0].sender} | Ko'rsatma`"
        )

        await bot.send_message(
            chat_id=ADMIN_ID,
            text=text[:4000],
            parse_mode="Markdown",
        )
        logger.info("Yangi email xabarnomasi adminga yuborildi: %d ta xat", len(new_items))

    except Exception as exc:
        logger.error("Email tekshirish jobida xatolik: %s", exc)


# ─── Kechiktirilgan Postlarni E'lon Qilish (Scheduled Posts) ────

async def check_scheduled_posts_job(bot: "Bot") -> None:
    """
    Har 60 soniyada ma'lumotlar bazasidagi vaqti kelgan postlarni tekshirib,
    tegishli kanal yoki guruhga avtomatik e'lon qiladi.
    """
    from core.database import db
    from core.userbot import post_to_channel_or_chat

    due_posts = await db.get_due_posts()
    if not due_posts:
        return

    for post in due_posts:
        post_id = post["id"]
        chat_id = post["chat_id"]
        text = post["text"]

        try:
            logger.info("Rejalashtirilgan post e'lon qilinmoqda: #%d -> %s", post_id, chat_id)
            res = await post_to_channel_or_chat(bot, chat_id, text)
            await db.mark_post_published(post_id)
            await db.log_event("scheduled_post", f"Published post #{post_id} to {chat_id}")

            # Adminga muvaffaqiyat xabarnomasi
            await bot.send_message(
                chat_id=ADMIN_ID,
                text=f"⏰ **Rejalashtirilgan post muvaffaqiyatli e'lon qilindi!**\n\n"
                     f"📌 Manzil: `{chat_id}`\n"
                     f"📝 Post ID: `#{post_id}`\n\n"
                     f"📡 Natija:\n{res}",
                parse_mode="Markdown",
            )
        except Exception as exc:
            logger.error("Kechiktirilgan postni e'lon qilishda xato (#%d): %s", post_id, exc)


# ─── Raqobatchilar Trendlari Kunlik Tahlili ────────────────────

async def daily_competitor_analysis_job(bot: "Bot", ai_manager: "AIManager") -> None:
    """
    Raqobatchilar kanallaridagi eng so'nggi va ko'p reaksiyali postlarni tahlil qilib,
    adminga kunlik trendlar rezyumesini yuboradi.
    """
    from core.database import db
    from core.userbot import userbot

    comps = await db.get_competitors()
    if not comps:
        return

    client = userbot.get_client()
    if not client or not client.is_connected():
        logger.warning("CompetitorJob: Userbot ulanmagan.")
        return

    report_parts = []
    for ch in comps:
        try:
            messages = await client.get_messages(ch, limit=10)
            clean_texts = []
            for m in messages:
                if m.text and len(m.text) > 30:
                    clean_texts.append(f"[{m.views or 0} views] {m.text[:150]}...")

            if clean_texts:
                report_parts.append(f"📡 Kanal @{ch}:\n" + "\n".join(clean_texts[:4]))
        except Exception as exc:
            logger.warning("Raqobatchi kanal @%s ni o'qib bo'lmadi: %s", ch, exc)

    if not report_parts:
        return

    prompt = (
        "Siz SMM tahlilchisisiz. Quyida raqobatchi Telegram kanallarining so'nggi postlari keltirilgan:\n\n"
        + "\n\n".join(report_parts)
        + "\n\nVazifa:\n"
        "1. Raqobatchilar bugun qaysi mavzularga ko'proq urg'u berishmoqda (Trendlar)?\n"
        "2. Auditoriya qaysi postlarga ko'proq qiziqish bildirgan?\n"
        "3. O'z kanalimiz uchun 2 ta samarali post g'oyasini taklif qiling.\n"
        "O'zbek tilida, qisqa va amaliy rezyume tayyorlang."
    )

    from core.safe_send import safe_send_message

    ai_analysis = await ai_manager.generate(prompt, save_history=False)
    await safe_send_message(
        bot=bot,
        chat_id=ADMIN_ID,
        text=f"📊 **Kunlik Raqobatchilar Trendlari va Rezyumesi:**\n\n{ai_analysis}",
        parse_mode="Markdown",
    )


# ─── Eslatmalar Davriy Tekshiruvi ────────────────────────────

async def check_reminders_job(bot: "Bot") -> None:
    """
    Har 20 soniyada kutilayotgan eslatmalarni tekshiradi va
    vaqti kelgan bo'lsa foydalanuvchiga shaxsiy bildirishnoma yuboradi.
    """
    from core.database import db
    from core.safe_send import safe_send_message
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton

    due_reminders = await db.get_due_reminders()
    if not due_reminders:
        return

    for rem in due_reminders:
        rem_id = rem["id"]
        chat_id = rem["chat_id"]
        text = rem["text"]
        remind_at = rem["remind_at"]

        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(text="✅ Bajarildi", callback_data=f"done_rem:{rem_id}"),
            InlineKeyboardButton(text="⏰ +10 daqiqa", callback_data=f"snooze_rem:{rem_id}:10"),
        )
        builder.row(
            InlineKeyboardButton(text="⏰ +1 soat", callback_data=f"snooze_rem:{rem_id}:60"),
        )

        msg_text = (
            f"🔔 **ESLATMA VAQTI KELDI!** ⏰\n"
            f"{'─' * 30}\n\n"
            f"📌 **Vazifa:**\n{text}\n\n"
            f"🕒 Belgilangan vaqt: `{remind_at}`\n"
            f"{'─' * 30}\n"
            f"Bajarilganini tasdiqlang yoki vaqtni suring 👇"
        )

        try:
            target_chat = int(chat_id) if str(chat_id).lstrip("-").isdigit() else chat_id
            sent_msg = await safe_send_message(
                bot=bot,
                chat_id=target_chat,
                text=msg_text,
                reply_markup=builder.as_markup(),
                parse_mode="Markdown",
            )
            if sent_msg:
                await db.mark_reminder_sent(rem_id)
                logger.info("Eslatma yuborildi: #%d -> %s", rem_id, chat_id)
            else:
                logger.warning("Eslatma yuborilmadi (#%d): chat_id=%s", rem_id, chat_id)
        except Exception as exc:
            logger.error("Eslatmani yuborishda xato (#%d): %s", rem_id, exc)


async def check_uptime_monitors_job(bot: "Bot") -> None:
    """Veb-saytlar va serverlar holatini avtomat tekshirib, xato bo'lsa adminga xabar yuborish."""
    try:
        from core.uptime_agent import run_uptime_batch_check
        alerts = await run_uptime_batch_check()
        for a in alerts:
            if a["type"] == "DOWN":
                msg = (
                    f"🚨 **FAVQULODDA: Veb-sayt o'chdi!**\n\n"
                    f"🌐 **Sayt:** `{a['name']}`\n"
                    f"🔗 **URL:** {a['url']}\n"
                    f"❌ **Xatolik kodi:** `{a['status']}`\n"
                    f"⏱ **Kechikish:** `{a['time_ms']} ms`\n\n"
                    f"Server yoki xostingizni zudlik bilan tekshiring!"
                )
            else:
                msg = (
                    f"🟢 **XUSHXABAR: Veb-sayt qayta tiklandi!**\n\n"
                    f"🌐 **Sayt:** `{a['name']}`\n"
                    f"🔗 **URL:** {a['url']}\n"
                    f"✅ **Holat:** Onlayn (`{a['status']}`)\n"
                    f"⏱ **Kechikish:** `{a['time_ms']} ms`"
                )
            try:
                await bot.send_message(chat_id=ADMIN_ID, text=msg, parse_mode="Markdown")
            except Exception as e:
                logger.error("Uptime alert yuborishda xato: %s", e)
    except Exception as exc:
        logger.debug("check_uptime_monitors_job xatosi: %s", exc)


# ─── Scheduler Sozlash ────────────────────────────────────────

def setup_scheduler(bot: "Bot", ai_manager: "AIManager") -> AsyncIOScheduler:
    """
    APScheduler ni sozlab qaytaradi:
    1. Har kuni REPORT_HOUR:REPORT_MINUTE da kunlik hisobot
    2. Har EMAIL_CHECK_INTERVAL daqiqada email tekshiruvi
    3. Har 60 soniyada taymerli postlarni tekshirish (SMM Avtopilot)
    4. Har kuni soat 10:00 da raqobatchilar tahlili
    5. Har 20 soniyada eslatmalarni tekshirish (Real-time Reminders)
    6. Har UPTIME_CHECK_INTERVAL daqiqada veb-saytlar uptime monitoringi
    """
    from apscheduler.triggers.interval import IntervalTrigger
    from config import EMAIL_CHECK_INTERVAL

    scheduler = AsyncIOScheduler(timezone="Asia/Tashkent")

    # 1. Kunlik hisobot
    scheduler.add_job(
        generate_and_send_report,
        trigger=CronTrigger(
            hour=REPORT_HOUR,
            minute=REPORT_MINUTE,
            timezone="Asia/Tashkent",
        ),
        args=[bot, ai_manager],
        id="daily_report",
        name="Kunlik Hisobot",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # 2. Email tekshiruv (har 15 daqiqada)
    scheduler.add_job(
        check_new_emails_job,
        trigger=IntervalTrigger(
            minutes=EMAIL_CHECK_INTERVAL,
            timezone="Asia/Tashkent",
        ),
        args=[bot, ai_manager],
        id="email_check",
        name="Email Tekshiruv",
        replace_existing=True,
        misfire_grace_time=60,
    )

    # 3. Kechiktirilgan postlar (har 1 daqiqada)
    scheduler.add_job(
        check_scheduled_posts_job,
        trigger=IntervalTrigger(
            seconds=60,
            timezone="Asia/Tashkent",
        ),
        args=[bot],
        id="scheduled_posts_check",
        name="Kechiktirilgan Postlar",
        replace_existing=True,
        misfire_grace_time=30,
    )

    # 4. Raqobatchilar monitoringi (har kuni soat 10:00 da)
    scheduler.add_job(
        daily_competitor_analysis_job,
        trigger=CronTrigger(
            hour=10,
            minute=0,
            timezone="Asia/Tashkent",
        ),
        args=[bot, ai_manager],
        id="competitor_daily",
        name="Raqobatchilar Tahlili",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # 5. Eslatmalar tekshiruvi (har 20 soniyada)
    scheduler.add_job(
        check_reminders_job,
        trigger=IntervalTrigger(
            seconds=20,
            timezone="Asia/Tashkent",
        ),
        args=[bot],
        id="reminders_check",
        name="Eslatmalar Tekshiruvi",
        replace_existing=True,
        misfire_grace_time=15,
    )

    # 6. Uptime Saytlar Monitoringi (har UPTIME_CHECK_INTERVAL daqiqada)
    scheduler.add_job(
        check_uptime_monitors_job,
        trigger=IntervalTrigger(
            minutes=UPTIME_CHECK_INTERVAL,
            timezone="Asia/Tashkent",
        ),
        args=[bot],
        id="uptime_check",
        name="Uptime Saytlar Monitoringi",
        replace_existing=True,
        misfire_grace_time=60,
    )

    # 7. Tungi Avtonom Dual-Agent Navbatchisi (02:30 da siz uxlaganda mustaqil tahlil qiladi)
    async def night_autopilot_job():
        try:
            from core.bot_collab import run_night_autopilot_cycle
            from core.mistral_agent_bot import get_second_bot
            sec_bot = get_second_bot()
            await run_night_autopilot_cycle(bot_white=bot, bot_black=sec_bot)
        except Exception as na_err:
            logger.error("Tungi avtopilot job xatosi: %s", na_err)

    scheduler.add_job(
        night_autopilot_job,
        trigger=CronTrigger(hour=2, minute=30, timezone="Asia/Tashkent"),
        id="night_dual_agent_autopilot",
        name="Tungi Dual-Agent Avtopiloti",
        replace_existing=True,
        misfire_grace_time=300,
    )

    logger.info(
        "Scheduler sozlandi: Hisobot %02d:%02d da, Email har %d daqiqada, Uptime har %d daqiqada faol",
        REPORT_HOUR, REPORT_MINUTE, EMAIL_CHECK_INTERVAL, UPTIME_CHECK_INTERVAL,
    )
    return scheduler

"""
core/email_agent.py — IMAP va SMTP orqali Shaxsiy Email Agent

Funksiyalari:
1. O'qilmagan xatlarni (UNSEEN) IMAP orqali xavfsiz qabul qilish.
2. Yangi kelgan xatlarni AI (Gemini/OpenRouter) yordamida tahlil qilish va umumlashtirish.
3. Kelgan xatlarga AI orqali professional javob loyihasi (Draft) tayyorlash.
4. Telegram orqali tasdiqlanganidan so'ng SMTP orqali xat yuborish.
5. In-memory — hech qanday xat diskka yozilmaydi.
"""

from __future__ import annotations

import asyncio
import email
from email.header import decode_header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import imaplib
import logging
import smtplib
from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

from config import (
    EMAIL_USER,
    EMAIL_PASS,
    EMAIL_IMAP_SERVER,
    EMAIL_IMAP_PORT,
    EMAIL_SMTP_SERVER,
    EMAIL_SMTP_PORT,
)

if TYPE_CHECKING:
    from core.ai_manager import AIManager

logger = logging.getLogger(__name__)


@dataclass
class EmailItem:
    """Xat haqidagi qisqacha ma'lumot."""
    msg_id: str
    sender: str
    subject: str
    date: str
    body: str

    @property
    def snippet(self) -> str:
        """Xat matnidan dastlabki 150 ta belgi."""
        clean = " ".join(self.body.split())
        return clean[:150] + "..." if len(clean) > 150 else clean


def _decode_str(header_value: Optional[str]) -> str:
    """Email sarlavhalarini to'g'ri UTF-8 ga dekodlash."""
    if not header_value:
        return ""
    decoded_parts = []
    for part, enc in decode_header(header_value):
        if isinstance(part, bytes):
            try:
                decoded_parts.append(part.decode(enc or "utf-8", errors="replace"))
            except Exception:
                decoded_parts.append(part.decode("latin-1", errors="replace"))
        else:
            decoded_parts.append(str(part))
    return "".join(decoded_parts)


def _extract_body(msg: email.message.Message) -> str:
    """Email xabari ichidan matnni ajratib olish (HTML yoki plain text)."""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition"))
            if content_type == "text/plain" and "attachment" not in content_disposition:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    try:
                        return payload.decode(charset, errors="replace")
                    except Exception:
                        return payload.decode("latin-1", errors="replace")
            elif content_type == "text/html" and not body and "attachment" not in content_disposition:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    try:
                        body = payload.decode(charset, errors="replace")
                    except Exception:
                        body = payload.decode("latin-1", errors="replace")
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            try:
                body = payload.decode(charset, errors="replace")
            except Exception:
                body = payload.decode("latin-1", errors="replace")

    # Juda oddiy HTML tozalash
    import re
    body = re.sub(r"<[^>]+>", " ", body)
    return "\n".join(line.strip() for line in body.splitlines() if line.strip())


class EmailAgent:
    """
    Shaxsiy Email Boshqaruvchi Agent.
    Barcha IMAP/SMTP operatsiyalari bloklanmasligi uchun asyncio.to_thread orqali ishlaydi.
    """

    def __init__(self) -> None:
        self.user = EMAIL_USER
        self.password = EMAIL_PASS
        self.imap_server = EMAIL_IMAP_SERVER
        self.imap_port = EMAIL_IMAP_PORT
        self.smtp_server = EMAIL_SMTP_SERVER
        self.smtp_port = EMAIL_SMTP_PORT
        self.last_error: str = ""

    def is_configured(self) -> bool:
        """Email sozlamalari mavjudligini tekshiradi."""
        return bool(self.user and self.password)

    # ─── IMAP: Xatlarni o'qish ─────────────────────────────────

    def _sync_fetch_unread(self, limit: int = 5) -> list[EmailItem]:
        """Sinxron tarzda oxirgi o'qilmagan xatlarni oladi."""
        if not self.is_configured():
            return []

        items: list[EmailItem] = []
        mail = None
        try:
            mail = imaplib.IMAP4_SSL(self.imap_server, self.imap_port)
            mail.login(self.user, self.password)
            mail.select("INBOX", readonly=True)

            status, search_data = mail.search(None, "UNSEEN")
            # Agar o'qilmagan xat bo'lmasa, pochtadagi eng so'nggi xatlarni olamiz (ALL)
            if status != "OK" or not search_data or not search_data[0]:
                status, search_data = mail.search(None, "ALL")

            if status != "OK" or not search_data or not search_data[0]:
                return []

            msg_ids = search_data[0].split()
            # Eng so'nggi xatlarni olish (oxiridan boshlab)
            target_ids = msg_ids[-limit:]
            target_ids.reverse()

            for mid in target_ids:
                res, data = mail.fetch(mid, "(RFC822)")
                if res != "OK" or not data or not data[0]:
                    continue

                raw_email = data[0][1]
                msg = email.message_from_bytes(raw_email)

                subject = _decode_str(msg.get("Subject", "Mavzusiz"))
                sender = _decode_str(msg.get("From", "Noma'lum"))
                date_str = _decode_str(msg.get("Date", ""))
                body = _extract_body(msg)

                items.append(
                    EmailItem(
                        msg_id=mid.decode() if isinstance(mid, bytes) else str(mid),
                        sender=sender,
                        subject=subject,
                        date=date_str,
                        body=body[:2500],  # Xotira va prompt hajmini cheklash
                    )
                )

        except Exception as exc:
            err_msg = str(exc)
            logger.error("IMAP orqali xatlarni olishda xatolik: %s", exc)
            if any(w in err_msg for w in ["AUTHENTICATIONFAILED", "Invalid credentials", "Application-specific password required"]):
                self.last_error = (
                    "⚠️ **Google Gmail Autentifikatsiya Xatosi:**\n\n"
                    "Google Gmail sizning asosiy hisob parolingizni to'g'ridan-to'g'ri qabul qilmaydi.\n"
                    "Buning uchun maxsus **16 xonali Ilova Paroli (App Password)** kiritilishi shart!\n\n"
                    "🔑 **To'g'rilash bo'yicha qo'llanma:**\n"
                    "1. [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords) sahifasiga kiring.\n"
                    "2. 2-bosqichli tekshirish (2-Step Verification) yoqilgan bo'lishi kerak.\n"
                    "3. Yangi ilova nomiga `SuperAgent` deb yozib, **Yaratish** tugmasini bosing.\n"
                    "4. Berilgan 16 xonali kodni nusxalang (masalan: `naba gkdt eeev gwmb`).\n"
                    "5. Agar bot **Render** da ishlayotgan bo'lsa, Render boshqaruv panelidagi **Environment** bo'limida `EMAIL_PASS` qiymatini shu 16 xonali parol bilan yangilang va botni qayta ishga tushiring (Restart)!"
                )
            else:
                self.last_error = f"❌ Pochta xatosi: {exc}"
        finally:
            if mail:
                try:
                    mail.close()
                    mail.logout()
                except Exception:
                    pass

        return items

    async def fetch_unread(self, limit: int = 5) -> list[EmailItem]:
        """Asinxron o'qilmagan xatlarni olish."""
        return await asyncio.to_thread(self._sync_fetch_unread, limit)

    # ─── SMTP: Xat yuborish ────────────────────────────────────

    def _sync_send_email(self, to_email: str, subject: str, body: str) -> tuple[bool, str]:
        """Sinxron tarzda SMTP orqali xat jo'natadi."""
        if not self.is_configured():
            return False, "Email sozlamalari (EMAIL_USER / EMAIL_PASS) kiritilmagan!"

        msg = MIMEMultipart("alternative")
        msg["From"] = self.user
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))

        try:
            if self.smtp_port == 465:
                # SSL
                with smtplib.SMTP_SSL(self.smtp_server, self.smtp_port, timeout=15) as server:
                    server.login(self.user, self.password)
                    server.sendmail(self.user, [to_email], msg.as_string())
            else:
                # TLS (587)
                with smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=15) as server:
                    server.starttls()
                    server.login(self.user, self.password)
                    server.sendmail(self.user, [to_email], msg.as_string())

            logger.info("Xat muvaffaqiyatli yuborildi: %s", to_email)
            return True, f"Xat muvaffaqiyatli yuborildi: `{to_email}`"

        except Exception as exc:
            logger.error("SMTP orqali xat yuborishda xato: %s", exc)
            return False, f"Xat yuborishda xatolik: {exc}"

    async def send_email(self, to_email: str, subject: str, body: str) -> tuple[bool, str]:
        """Asinxron xat yuborish."""
        return await asyncio.to_thread(self._sync_send_email, to_email, subject, body)

    # ─── AI Integratsiyasi ─────────────────────────────────────

    async def analyze_inbox(
        self,
        emails: list[EmailItem],
        ai_manager: "AIManager",
    ) -> str:
        """Kelgan xatlar ro'yxatini AI yordamida saralab, xulosalab beradi."""
        if not emails:
            return "📭 Yangi o'qilmagan xatlar mavjud emas."

        summary_prompt = (
            "Quyida foydalanuvchining shaxsiy Gmail pochtasiga kelgan so'nggi xatlar keltirilgan.\n"
            "Har bir xatni batafsil o'rganib chiqib, foydalanuvchiga O'zbek tilida aniq, tushunarli "
            "va to'liq mazmunini ko'rsatuvchi hisobot tayyorla.\n\n"
            "Har bir xat uchun quyidagi formatdan foydalan:\n"
            "📩 **Xat [raqami]:** [Jo'natuvchi nomi va emaili]\n"
            "📌 **Mavzu:** [Mavzu]\n"
            "🕒 **Vaqti:** [Sana va vaqt]\n"
            "📄 **Xatning asosiy mazmuni:** [Xat ichida nima deyilgani, muhim tafsilotlar, agar kod yoki xatolik bo'lsa o'shalar]\n"
            "⚡ **Muhimlik darajasi:** [Juda muhim / Oddiy / Bildirishnoma / Spam]\n"
            "💡 **Tavsiya / Qilinishi kerak bo'lgan ish:** [Foydalanuvchi nima qilishi kerak]\n\n"
            "Xatlar ma'lumotlari:\n"
        )

        for i, item in enumerate(emails, 1):
            clean_body = item.body.strip()
            summary_prompt += (
                f"\n--- Xat #{i} ---\n"
                f"Kimdan: {item.sender}\n"
                f"Mavzu: {item.subject}\n"
                f"Sana: {item.date}\n"
                f"Xat matni:\n{clean_body[:1000]}\n"
            )

        try:
            ai_res = await ai_manager.generate(summary_prompt, save_history=False)
            return f"📬 **Pochtangizdagi so'nggi xatlar ({len(emails)} ta) tahlili:**\n\n{ai_res}"
        except Exception as exc:
            logger.error("Email AI tahlilida xatolik: %s", exc)
            # Fallback format
            res = [f"📬 **Pochtangizdagi so'nggi xatlar ({len(emails)} ta):**\n"]
            for i, em in enumerate(emails, 1):
                res.append(
                    f"**{i}. Kimdan:** `{em.sender}`\n"
                    f"**📌 Mavzu:** {em.subject}\n"
                    f"**🕒 Sana:** {em.date}\n"
                    f"**📄 Mazmuni:** {em.body[:250]}\n"
                )
            return "\n".join(res)

    async def draft_reply(
        self,
        email_item: EmailItem,
        user_instructions: str,
        ai_manager: "AIManager",
    ) -> tuple[str, str]:
        """
        Kelgan xatga javob xati loyihasini (Draft) tuzadi.
        Qaytaradi: (reply_subject, reply_body)
        """
        prompt = (
            f"Sen professional shaxsiy AI assistentsan. Quyidagi xatga javob xati loyihasini yozishing kerak.\n\n"
            f"ASL XAT:\n"
            f"Kimdan: {email_item.sender}\n"
            f"Mavzu: {email_item.subject}\n"
            f"Matn: {email_item.body[:1000]}\n\n"
            f"FOYDALANUVCHINING KO'RSATMASI:\n{user_instructions}\n\n"
            f"Talablar:\n"
            f"1. O'ta muloyim, aniq va professional ohangda bo'lsin.\n"
            f"2. Faqat tayyor javob matnini taqdim et (ortiqcha tushuntirishlarsiz).\n"
            f"3. Xat oxirida hurmat bilan yakunla."
        )

        reply_subject = email_item.subject
        if not reply_subject.lower().startswith("re:"):
            reply_subject = f"Re: {reply_subject}"

        try:
            reply_body = await ai_manager.generate(prompt, save_history=False)
            return reply_subject, reply_body
        except Exception as exc:
            logger.error("AI orqali javob yozishda xato: %s", exc)
            return reply_subject, f"Assalomu alaykum.\n\nXatingizni qabul qildim.\n\n{user_instructions}\n\nHurmat bilan."

    async def draft_new_email(
        self,
        prompt_instruction: str,
        to_email: str,
        ai_manager: "AIManager",
    ) -> tuple[str, str]:
        """
        Noldan yangi xat uchun mavzu va matn generatsiya qiladi.
        Qaytaradi: (subject, body)
        """
        ai_prompt = (
            f"Sen professional AI kotibsan. Quyidagi ko'rsatma asosida `{to_email}` manziliga yuboriladigan "
            f"xat loyihasini yarat:\n"
            f"Ko'rsatma: {prompt_instruction}\n\n"
            f"Javobingni aniq quyidagi formatda ber:\n"
            f"MAVZU: [Mavzu shu yerda]\n"
            f"MATN:\n[Xat matni shu yerda]"
        )

        try:
            generated = await ai_manager.generate(ai_prompt, save_history=False)
            subject = "Muhim xabar"
            body = generated

            if "MAVZU:" in generated and "MATN:" in generated:
                parts = generated.split("MATN:", 1)
                subject_part = parts[0].replace("MAVZU:", "").strip()
                if subject_part:
                    subject = subject_part
                body = parts[1].strip()

            return subject, body
        except Exception as exc:
            logger.error("Yangi xat generatsiyasida xato: %s", exc)
            return "Xabar", prompt_instruction

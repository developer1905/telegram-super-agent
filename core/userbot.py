"""
core/userbot.py — Telethon Userbot Asboblari (Smart Search va AI Bilan Kengaytirilgan)

Imkoniyatlar:
- Username bo'lmagan shaxslarni Ismi / Telefonda saqlangan nomi bo'yicha topish va xabar yuborish
- Guruh va kanallarni nomi bo'yicha topish va ularga post/xabar yuborish
- Guruh yoki kanaldagi so'nggi xabarlarni o'qib AI xulosasini berish
- Shaxsiy suhbatlarni tahlil qilish
- Kesh va tezkor xotira (RAM) optimallashtirish
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional, Union, TYPE_CHECKING

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import (
    ChatAdminRequiredError,
    UserPrivacyRestrictedError,
    FloodWaitError,
    UsernameNotOccupiedError,
    ChannelPrivateError,
)

from config import API_ID, API_HASH, USERBOT_SESSION

if TYPE_CHECKING:
    from core.ai_manager import AIManager

logger = logging.getLogger(__name__)

# Global userbot client (main.py tomonidan ishga tushiriladi)
userbot: Optional[TelegramClient] = None

# Tezlik uchun: dialoglar keshi (60 soniya yashaydi)
_dialogs_cache: list = []
_cache_time: float = 0.0


def create_userbot_client() -> TelegramClient:
    """
    Telethon client yaratadi.
    StringSession bo'lsa uni ishlatadi, bo'lmasa fayl sessiyaga tushadi.
    """
    if USERBOT_SESSION:
        session = StringSession(USERBOT_SESSION)
    else:
        session = "userbot"
    return TelegramClient(session, API_ID, API_HASH)


def get_client() -> Optional[TelegramClient]:
    """Userbot client obyektini xavfsiz qaytaradi."""
    global userbot
    return userbot


async def _get_cached_dialogs(force_refresh: bool = False, limit: int = 150) -> list:
    """Tezkor ishlash uchun suhbatlarni RAM da keshlaydi."""
    global userbot, _dialogs_cache, _cache_time
    if userbot is None or not userbot.is_connected():
        return []

    now = time.time()
    if not force_refresh and _dialogs_cache and (now - _cache_time < 60):
        return _dialogs_cache

    try:
        dialogs = await userbot.get_dialogs(limit=limit)
        _dialogs_cache = dialogs
        _cache_time = now
        return dialogs
    except Exception as exc:
        logger.error("Dialoglarni olishda xato: %s", exc)
        return _dialogs_cache or []


# ─── Ism bo'yicha Aqlli Qidiruv (Smart Search) ────────────────

async def search_targets(query: str, target_type: str = "any") -> list[dict]:
    """
    Foydalanuvchi, guruh yoki kanalni Ismi, Sarlavhasi yoki Username'i bo'yicha qidiradi.
    Username bo'lmagan shaxslarni ham 100% aniqlikda topadi.

    Args:
        query: Qidirilayotgan ism/nom (masalan: "Ali", "Olimjon", "Dasturchilar")
        target_type: "user" | "chat" | "channel" | "any"
    """
    clean_q = query.strip().lower().lstrip("@")
    if not clean_q:
        return []

    dialogs = await _get_cached_dialogs()
    matches = []

    for d in dialogs:
        entity = d.entity
        first_name = getattr(entity, "first_name", "") or ""
        last_name = getattr(entity, "last_name", "") or ""
        full_name = f"{first_name} {last_name}".strip()
        title = getattr(entity, "title", "") or ""
        username = getattr(entity, "username", "") or ""

        # Turini aniqlash
        is_user = getattr(entity, "bot", False) is False and title == ""
        is_channel = getattr(entity, "broadcast", False) is True
        is_group = (title != "") and not is_channel

        if target_type == "user" and not is_user:
            continue
        if target_type == "channel" and not is_channel:
            continue
        if target_type == "group" and not is_group:
            continue

        display_name = title if title else (full_name or username or f"ID: {entity.id}")
        searchable_text = f"{display_name} {username}".lower()

        # Moslikni tekshirish
        score = 0
        if clean_q == username.lower() or clean_q == display_name.lower():
            score = 100
        elif display_name.lower().startswith(clean_q):
            score = 80
        elif clean_q in searchable_text:
            score = 50

        if score > 0:
            kind_str = "Foydalanuvchi" if is_user else ("Kanal" if is_channel else "Guruh")
            matches.append({
                "entity": entity,
                "id": entity.id,
                "name": display_name,
                "username": f"@{username}" if username else "(username yo'q)",
                "type": kind_str,
                "score": score,
            })

    # Eng aniq mos kelganlarini oldinga qo'yish
    matches.sort(key=lambda x: x["score"], reverse=True)
    return matches


# ─── Aqlli Xabar Yuborish (Smart Sender) ──────────────────────

async def send_message_smart(target_query: str, message_text: str) -> tuple[bool, str, list[dict]]:
    """
    Foydalanuvchiga Ismi, Username yoki ID si bo'yicha xabar yuboradi.
    
    Qaytaradi:
        (success: bool, text_response: str, candidate_list: list[dict])
    """
    global userbot
    if userbot is None or not userbot.is_connected():
        return False, "❌ Userbot ulanmagan.", []

    target_query = target_query.strip()

    # 1. Agar to'g'ridan-to'g'ri @username yoki raqamli ID bo'lsa
    if target_query.startswith("@") or target_query.lstrip("-").isdigit():
        target = target_query[1:] if target_query.startswith("@") else int(target_query)
        try:
            entity = await userbot.get_entity(target)
            await userbot.send_message(entity, message_text, parse_mode="markdown")
            name = getattr(entity, "title", None) or getattr(entity, "first_name", str(target))
            return True, f"✅ `{name}` ga xabar yuborildi!", []
        except UserPrivacyRestrictedError:
            name = getattr(entity, "first_name", str(target))
            return False, (
                f"⚠️ **Telegram Maxfiylik Cheklovi:**\n"
                f"`{name}` o'z Telegram sozlamalarida 'Menga faqat kontaktlarim yozsin' deb cheklab qo'ygan.\n\n"
                f"👉 **Yechim:** Ushbu odamni telefoningizdagi Kontaktlar (Contacts) ro'yxatiga qo'shib qo'ying, shunda bot darhol unga yoza oladi!"
            ), []
        except ChatAdminRequiredError:
            return False, f"⚠️ Ushbu chat/kanalga post yozish uchun sizda Adminlik huquqi kerak.", []
        except FloodWaitError as e:
            return False, f"⏳ Telegram cheklovi (FloodWait): {e.seconds} soniya kuting.", []
        except Exception as exc:
            logger.error("send_message_smart xatosi: %s", exc)
            return False, f"❌ Xabar yuborishda xatolik: {exc}", []

    # 2. Ism bo'yicha qidiruv (Username yo'q tanishlar uchun)
    candidates = await search_targets(target_query, target_type="user")

    if not candidates:
        # Barcha turlar bo'yicha ham qidirib ko'ramiz
        candidates = await search_targets(target_query, target_type="any")

    if not candidates:
        return False, f"❌ `{target_query}` nomli kontakt yoki suhbatdosh topilmadi.", []

    # Aniq 1 ta odam topilsa yoki birinchi nomzod juda yuqori aniqlikda bo'lsa
    if len(candidates) == 1 or candidates[0]["score"] == 100:
        best = candidates[0]
        try:
            await userbot.send_message(best["entity"], message_text, parse_mode="markdown")
            username_info = f" ({best['username']})" if best['username'] != "(username yo'q)" else ""
            return True, f"✅ **{best['name']}**{username_info} ga xabar muvaffaqiyatli yuborildi!", []
        except UserPrivacyRestrictedError:
            return False, (
                f"⚠️ **Telegram Maxfiylik Cheklovi:**\n"
                f"**{best['name']}** o'z Telegramida begonalardan xabarni cheklagan.\n"
                f"👉 Uni telefoningizda kontaktlarga qo'shsangiz, xabar yetib boradi!"
            ), []
        except Exception as exc:
            return False, f"❌ Xabar yuborishda xato: {exc}", []

    # Bir nechta o'xshash nomdagi odamlar topilsa
    text = (
        f"🔍 **'{target_query}' bo'yicha bir nechta odam/suhbat topildi:**\n"
        f"Iltimos, aniqroq yozing yoki quyidagilardan birini tanlang:\n\n"
    )
    for i, c in enumerate(candidates[:5], 1):
        text += f"{i}. **{c['name']}** {c['username']} — ID: `{c['id']}`\n"
    text += f"\n💡 Masalan: `yoz {candidates[0]['id']}: {message_text}`"

    return False, text, candidates[:5]


def normalize_target_channel_id(target_query: str | int) -> str | int:
    """Kanal yoki guruh ID sini to'g'ri -100 formatga keltiradi."""
    if isinstance(target_query, int):
        if target_query > 0 and target_query > 10000000:
            return -int(f"100{target_query}")
        elif target_query < 0 and not str(target_query).startswith("-100") and len(str(abs(target_query))) >= 9:
            return -int(f"100{abs(target_query)}")
        return target_query

    t = str(target_query).strip()
    if t.startswith("@"):
        return t
    if t.lstrip("-").isdigit():
        num = int(t)
        if num > 0 and num > 10000000:
            return -int(f"100{num}")
        elif num < 0 and not str(num).startswith("-100") and len(str(abs(num))) >= 9:
            return -int(f"100{abs(num)}")
        return num
    return t


async def post_to_channel_or_chat(bot: Any, target_query: str | int, message_text: str) -> str:
    """
    Guruh yoki kanalga post e'lon qilish.
    1-navbatda: Telegram Bot (aiogram.Bot) orqali yuborishga harakat qiladi (chunki bot kanalga admin qilingan).
    2-navbatda: Agar bot yubora olmasa, Userbot (Telethon) orqali yuborishga urinadi.
    """
    from config import LOG_CHANNEL_ID

    if not target_query or str(target_query).lower() in ("default", "asosiy", "kanal", "0", ""):
        if LOG_CHANNEL_ID and LOG_CHANNEL_ID != 0:
            target_query = LOG_CHANNEL_ID
        else:
            try:
                from core.database import db
                primary = await db.get_primary_channel()
                if primary:
                    target_query = primary["chat_id"]
                else:
                    return (
                        "❌ Qaysi kanalga post chiqarish ko'rsatilmadi.\n"
                        "💡 Iltimos, botni kanalingizga **Admin** qilib qo'shing yoki `.env` faylida `LOG_CHANNEL_ID` ni kiriting."
                    )
            except Exception:
                return "❌ Qaysi kanalga post chiqarish ko'rsatilmadi va .env da LOG_CHANNEL_ID sozlanmagan."

    norm_target = normalize_target_channel_id(target_query)

    # 1. aiogram Bot orqali to'g'ridan-to'g'ri kanalga yuborish (Primary)
    if bot is not None:
        try:
            try:
                sent = await bot.send_message(chat_id=norm_target, text=message_text, parse_mode="Markdown")
            except Exception:
                sent = await bot.send_message(chat_id=norm_target, text=message_text, parse_mode=None)

            chat_title = getattr(sent.chat, "title", str(norm_target))
            return f"✅ **{chat_title}** kanaliga muvaffaqiyatli post e'lon qilindi! (Bot orqali, ID: #{sent.message_id})"
        except Exception as bot_exc:
            logger.warning("Bot orqali yuborish o'xshamadi (%s): %s. Userbot orqali urinilmoqda...", norm_target, bot_exc)

    # 2. Userbot orqali yuborish (Fallback)
    userbot_res = await post_to_group_or_channel_smart(str(norm_target), message_text)
    if userbot_res.startswith("✅"):
        return userbot_res

    # Ikkalasi ham o'xshamasa
    return (
        f"⚠️ **Kanalga post yuborib bo'lmadi!**\n\n"
        f"📌 Manzil: `{norm_target}`\n\n"
        f"👉 **Sabab va Yechim:**\n"
        f"1. Bot kanalga **Admin** qilib qo'shilganiga va **'Post messages' (Xabarlar yuborish)** ruxsati berilganiga ishonch hosil qiling.\n"
        f"2. Agar yopiq kanal bo'lsa, kanal ID si `-100...` bilan boshlanishi kerak (hozir: `{norm_target}`)."
    )


# ─── Guruh va Kanallarga Post / Xabar Yuborish ───────────────

async def post_to_group_or_channel_smart(target_query: str, message_text: str) -> str:
    """
    Guruh yoki kanalga uning Nomi yoki @username orqali post yuboradi.
    """
    global userbot
    if userbot is None or not userbot.is_connected():
        return "❌ Userbot ulanmagan."

    target_query = target_query.strip()

    # 1. @username yoki ID
    if target_query.startswith("@") or target_query.lstrip("-").isdigit():
        target = target_query[1:] if target_query.startswith("@") else int(target_query)
        try:
            entity = await userbot.get_entity(target)
            msg = await userbot.send_message(entity, message_text, parse_mode="markdown")
            name = getattr(entity, "title", str(target))
            return f"✅ `{name}` ga muvaffaqiyatli post chiqarildi! (ID: {msg.id})"
        except ChatAdminRequiredError:
            return "⚠️ Ushbu kanalga xabar yozish uchun sizda Admin huquqi bo'lishi kerak."
        except ChannelPrivateError:
            return "⚠️ Bu xususiy (yopiq) kanal yoki guruh. Avval unga a'zo bo'lishingiz kerak."
        except Exception as exc:
            return f"❌ Post chiqarishda xato: {exc}"

    # 2. Nom bo'yicha guruh/kanal qidirish
    candidates = await search_targets(target_query, target_type="any")
    chats = [c for c in candidates if c["type"] in ("Kanal", "Guruh")]

    if not chats:
        return f"❌ `{target_query}` nomli guruh yoki kanal topilmadi."

    best = chats[0]
    try:
        msg = await userbot.send_message(best["entity"], message_text, parse_mode="markdown")
        return f"✅ **{best['name']}** ({best['type']}) ga xabar muvaffaqiyatli yuborildi! (ID: {msg.id})"
    except ChatAdminRequiredError:
        return f"⚠️ **{best['name']}** kanaliga post yozish uchun sizda Admin huquqi kerak."
    except Exception as exc:
        return f"❌ Post chiqarishda xato: {exc}"


# ─── Guruh / Kanal / Suhbatni AI Bilan Tahlil Qilish ──────────

async def summarize_target_chat(target_query: str, ai_manager: "AIManager", limit: int = 30) -> str:
    """
    Istalgan guruh, kanal yoki suhbatdagi oxirgi xabarlarni o'qib, AI xulosasini beradi.
    """
    global userbot
    if userbot is None or not userbot.is_connected():
        return "❌ Userbot ulanmagan."

    # Entity ni topish
    entity = None
    target_query = target_query.strip()

    if target_query.startswith("@") or target_query.lstrip("-").isdigit():
        try:
            entity = await userbot.get_entity(target_query[1:] if target_query.startswith("@") else int(target_query))
        except Exception:
            pass

    if not entity:
        candidates = await search_targets(target_query, target_type="any")
        if candidates:
            entity = candidates[0]["entity"]

    if not entity:
        return f"❌ `{target_query}` nomli suhbat yoki guruh topilmadi."

    title = getattr(entity, "title", None) or f"{getattr(entity, 'first_name', '')} {getattr(entity, 'last_name', '')}".strip()

    try:
        messages = await userbot.get_messages(entity, limit=limit)
        if not messages:
            return f"📭 `{title}` suhbatida xabarlar topilmadi."

        text_blocks = []
        for m in reversed(messages):
            if not m.message:
                continue
            sender_name = "Noma'lum"
            if m.sender:
                sender_name = getattr(m.sender, "first_name", "") or getattr(m.sender, "title", "Ismsiz")
            time_str = m.date.strftime("%H:%M") if m.date else ""
            text_blocks.append(f"[{time_str}] {sender_name}: {m.message[:300]}")

        if not text_blocks:
            return f"📭 `{title}` da faqat media yoki bo'sh xabarlar mavjud."

        raw_context = "\n".join(text_blocks[:30])

        ai_prompt = (
            f"Quyida '{title}' guruh/suhbatidagi so'nggi xabarlar keltirilgan.\n"
            f"Bularni o'rganib chiqib, quyidagi formatda O'zbek tilida qisqa, tushunarli hisobot tayyorla:\n\n"
            f"1. 🎯 **Asosiy mavzu:** Nimalar muhokama qilindi?\n"
            f"2. 👥 **Faol ishtirokchilar va ularning fikrlari**\n"
            f"3. 📌 **Muhim yangiliklar yoki qabul qilingan qarorlar**\n"
            f"4. ⚡ **Menga (foydalanuvchiga) tegishli topshiriq yoki savollar bormi?**\n\n"
            f"Xabarlar:\n{raw_context}"
        )

        analysis = await ai_manager.generate(ai_prompt, save_history=False)
        return f"📊 **'{title}' bo'yicha AI Tahlili:**\n\n{analysis}"

    except Exception as exc:
        logger.error("summarize_target_chat xatosi: %s", exc)
        return f"❌ Guruh xabarlarini tahlil qilishda xato: {exc}"


# ─── Shaxsiy Akkaunt So'nggi Suhbatlar Tahlili ───────────────

async def fetch_recent_dialog_messages(limit: int = 15) -> list[dict]:
    """Shaxsiy akkauntdagi so'nggi suhbatlarni oladi."""
    dialogs = await _get_cached_dialogs(limit=limit)
    results = []
    for d in dialogs:
        entity = d.entity
        title = getattr(entity, "title", None) or (
            f"{getattr(entity, 'first_name', '')} {getattr(entity, 'last_name', '')}".strip()
        )
        username = getattr(entity, "username", "")
        unread = d.unread_count
        last_msg = d.message.message if d.message else ""
        date_str = d.message.date.strftime("%H:%M, %d-%b") if d.message and d.message.date else ""
        is_user = getattr(entity, "bot", False) is False and getattr(entity, "title", None) is None

        results.append({
            "title": title or "Noma'lum",
            "username": f"@{username}" if username else "(username yo'q)",
            "id": entity.id,
            "unread": unread,
            "last_message": last_msg[:300],
            "date": date_str,
            "is_user": is_user,
        })
    return results


async def summarize_telegram_activity(ai_manager: "AIManager") -> str:
    """Telegram akkauntdagi so'nggi xabarlar bo'yicha to'liq AI xulosasi."""
    dialogs = await fetch_recent_dialog_messages(limit=15)
    if not dialogs:
        return "📭 Telegram akkauntingizda so'nggi xabarlar topilmadi yoki Userbot ulanmagan."

    prompt = (
        "Quyida foydalanuvchining shaxsiy Telegram akkauntidagi so'nggi suhbatlar va xabarlar keltirilgan.\n"
        "Shularni tahlil qilib, foydalanuvchiga o'ta tushunarli, samimiy va professional O'zbek tilida hisobot ber:\n\n"
        "1. 📬 **Kimlardan yangi xabarlar bor** va ularning qisqacha maqsadi nima?\n"
        "2. ⚠️ **Zudlik bilan javob berish kerak bo'lgan** muhim odamlar yoki xabarlar bormi?\n"
        "3. 💡 **Tavsiya** (kimga birinchi yozish kerak).\n\n"
        "Xabarlar ma'lumotlari:\n"
    )

    for i, d in enumerate(dialogs, 1):
        unread_mark = f" [🔴 {d['unread']} ta o'qilmagan]" if d['unread'] > 0 else ""
        prompt += (
            f"\n{i}. Suhbatdosh: {d['title']} {d['username']}{unread_mark}\n"
            f"   Vaqt: {d['date']}\n"
            f"   So'nggi xabar: {d['last_message']}\n"
        )

    try:
        analysis = await ai_manager.generate(prompt, save_history=False)
        return f"📱 **Telegram Akkauntingiz Tahlili (AI Xulosasi):**\n\n{analysis}"
    except Exception as exc:
        logger.error("Telegram xulosasida xatolik: %s", exc)
        lines = ["📱 **Telegramdagi so'nggi suhbatlar:**\n"]
        for d in dialogs[:7]:
            un = f" ({d['unread']} ta yangi)" if d['unread'] > 0 else ""
            lines.append(f"• **{d['title']}**{un}: {d['last_message'][:60]}")
        return "\n".join(lines)


async def get_userbot_info() -> str:
    """Userbot haqida ma'lumot qaytaradi."""
    global userbot
    if userbot is None or not userbot.is_connected():
        return "❌ Userbot ulanmagan."
    try:
        me = await userbot.get_me()
        name = f"{me.first_name or ''} {me.last_name or ''}".strip()
        username = f"@{me.username}" if me.username else "username yo'q"
        return (
            f"👤 **Userbot Ma'lumoti**\n"
            f"Ism: {name}\n"
            f"Username: {username}\n"
            f"ID: `{me.id}`\n"
            f"Telefon: `{me.phone}`"
        )
    except Exception as exc:
        return f"❌ Ma'lumot olishda xato: {exc}"


async def get_dialogs(limit: int = 20) -> str:
    """
    Foydalanuvchining suhbatlari ro'yxatini matn sifatida qaytaradi.
    Render va handlerlar uchun majburiy funksiya.
    """
    global userbot
    if userbot is None or not userbot.is_connected():
        return "❌ Userbot ulanmagan."

    try:
        dialogs = await _get_cached_dialogs(limit=limit)
        lines = [f"📋 **So'nggi {limit} ta suhbat:**\n"]
        for d in dialogs[:limit]:
            entity = d.entity
            name = getattr(entity, "title", None) or (
                f"{getattr(entity, 'first_name', '')} {getattr(entity, 'last_name', '')}".strip()
            )
            username = getattr(entity, "username", "")
            username_str = f" (@{username})" if username else ""
            lines.append(f"• **{name}**{username_str} — `{entity.id}`")

        return "\n".join(lines)
    except Exception as exc:
        logger.error("get_dialogs xatosi: %s", exc)
        return f"❌ Suhbatlarni olishda xato: {exc}"


# ─── Telegram Suhbat Tarixini O'qib Bazaga Qayta Saqlash ──────

async def sync_chat_history_from_telegram(
    target_username_or_id: Union[str, int],
    ai_manager: Optional["AIManager"] = None,
    limit: int = 100,
) -> dict:
    """
    Telegram suhbatidan (masalan, bot bilan bo'lgan chatdan) barcha avvalgi
    xabarlarni to'g'ridan-to'g'ri o'qib chiqib, doimiy bazaga (Supabase va SQLite)
    qayta saqlaydi va AI xotirasiga darhol yuklaydi.
    """
    global userbot
    if userbot is None or not userbot.is_connected():
        return {"success": False, "count": 0, "message": "❌ Userbot ulanmagan."}

    try:
        # Entity ni aniqlash
        entity = await userbot.get_entity(target_username_or_id)
        messages = await userbot.get_messages(entity, limit=limit)
        if not messages:
            return {"success": True, "count": 0, "message": "📭 Ushbu suhbatda xabarlar topilmadi."}

        # Eskisidan yangisiga qarab tartiblaymiz
        valid_msgs = [m for m in reversed(messages) if m.message and m.message.strip()]
        
        saved_count = 0
        from core.database import db

        for m in valid_msgs:
            text = m.message.strip()
            # Buyruqlarni e'tiborsiz qoldirish
            if text in ("/start", "/menu", "/status", "/clear", "/sync", "/sync_history"):
                continue

            role = "user" if m.out else "assistant"
            await db.add_chat_message(role=role, content=text)
            saved_count += 1

        # Agar ai_manager berilgan bo'lsa, xotirasini yangilash
        if ai_manager is not None:
            loaded = await db.get_recent_chat_history(limit=30)
            if loaded:
                ai_manager.history = loaded
                ai_manager._history_loaded = True

        return {
            "success": True,
            "count": saved_count,
            "message": f"✅ Telegramdan **{saved_count} ta** avvalgi xabar o'qildi va xotiraga muvaffaqiyatli saqlandi!\nEndi bot barcha gaplashilgan mavzularni to'liq eslaydi.",
        }

    except Exception as exc:
        logger.error("sync_chat_history_from_telegram xatosi: %s", exc)
        return {"success": False, "count": 0, "message": f"❌ Xatolik yuz berdi: {exc}"}


# ─── Boshqa Botlar Bilan Avtonom Muloqot (Inter-Bot Communication) ─

async def interact_with_bot_and_wait_reply(
    bot_target: str,
    prompt_or_command: str,
    timeout_sec: int = 20,
    forward_to_chat_id: Optional[int | str] = None,
) -> tuple[bool, str, Optional[int]]:
    """
    Telethon Userbot orqali boshqa botga (masalan: @vkmusic_bot, @midjourney_bot, @chatgpt_bot)
    avtonom so'rov yuboradi, uning javobini kutadi va natijani qaytaradi.
    Agar media (audio, fayl, rasm) kelsa, uni ixtiyoriy ravishda admin chatiga forward qiladi.

    Returns:
        (success: bool, response_summary: str, reply_msg_id: Optional[int])
    """
    global userbot
    if userbot is None or not userbot.is_connected():
        return False, "❌ Userbot (Telethon) ulanmagan yoki sessiya faol emas.", None

    clean_target = bot_target.strip().lstrip("@")
    if not clean_target:
        return False, "❌ Bot username'i ko'rsatilmadi.", None

    try:
        entity = await userbot.get_entity(f"@{clean_target}")
    except Exception as exc:
        logger.error("Botni topishda xato (@%s): %s", clean_target, exc)
        return False, f"❌ `@{clean_target}` boti Telegram tarmog'idan topilmadi ({exc}).", None

    try:
        sent_msg = await userbot.send_message(entity, prompt_or_command)
        logger.info("Inter-bot so'rov yuborildi: @%s ga -> '%s'", clean_target, prompt_or_command[:50])
    except Exception as exc:
        logger.error("Botga xabar yuborishda xato (@%s): %s", clean_target, exc)
        return False, f"❌ `@{clean_target}` botiga xabar yuborib bo'lmadi: {exc}", None

    # Botdan javob kutish (polling usuli)
    start_time = time.time()
    last_sent_id = sent_msg.id
    received_reply = None

    while time.time() - start_time < timeout_sec:
        await asyncio.sleep(1.5)
        try:
            messages = await userbot.get_messages(entity, limit=5)
            for m in messages:
                if m.id > last_sent_id and not m.out:
                    received_reply = m
                    break
            if received_reply:
                break
        except Exception as exc:
            logger.debug("Bot xabarlarini tekshirishda xatolik: %s", exc)

    if not received_reply:
        return (
            False,
            f"⏳ `@{clean_target}` botiga so'rov yuborildi (`{prompt_or_command}`), "
            f"lekin u {timeout_sec} soniya ichida javob qaytarmadi. "
            f"(Ehtimol bot band yoki sekin ishlamoqda).",
            None,
        )

    # Javob matnini tayyorlash
    reply_text = received_reply.message or ""
    media_info = ""

    if received_reply.media:
        media_type = type(received_reply.media).__name__.replace("MessageMedia", "")
        media_info = f"📎 [Keltirilgan media: {media_type}]"

    # Agar adminga to'g'ridan-to'g'ri forward qilish ko'rsatilgan bo'lsa
    if forward_to_chat_id:
        try:
            admin_target = int(forward_to_chat_id) if str(forward_to_chat_id).lstrip("-").isdigit() else forward_to_chat_id
            await userbot.forward_messages(admin_target, received_reply.id, entity)
            logger.info("Bot javobi adminga (%s) forward qilindi", forward_to_chat_id)
        except Exception as fwd_exc:
            logger.warning("Bot javobini forward qilishda xato: %s", fwd_exc)

    summary_lines = [f"🤖 **`@{clean_target}` Botining Javobi:**\n"]
    if reply_text:
        summary_lines.append(reply_text)
    if media_info:
        summary_lines.append(f"\n{media_info}")

    return True, "\n".join(summary_lines), received_reply.id


"""
core/safe_send.py — Xavfsiz Telegram Xabarlar Yuboruvchisi (Bulletproof Messaging)

Vazifalari:
1. Markdown formatlash xatolarida (unclosed tags, bad entities) avtomatik plain text fallback.
2. 4096 belgidan oshgan xabarlarni xavfsiz qismlarga (chunks) bo'lib yuborish.
3. FloodWait / RetryAfter xatolarida avtomatik kutish va qayta urinish.
4. MessageNotModified xatolarini sokin o'tkazib yuborish.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional, Union

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message, ReplyKeyboardMarkup, ReplyKeyboardRemove

logger = logging.getLogger(__name__)

MAX_TG_TEXT_LEN = 4000


def chunk_text(text: str, max_len: int = MAX_TG_TEXT_LEN) -> list[str]:
    """Matnni Telegram sig'imi bo'yicha qismlarga bo'ladi."""
    if len(text) <= max_len:
        return [text]

    chunks = []
    lines = text.split("\n")
    current_chunk = []
    current_len = 0

    for line in lines:
        line_len = len(line) + 1
        if current_len + line_len > max_len:
            if current_chunk:
                chunks.append("\n".join(current_chunk))
                current_chunk = []
                current_len = 0

            # Agar bitta qatorning o'zi max_len dan uzun bo'lsa
            while len(line) > max_len:
                chunks.append(line[:max_len])
                line = line[max_len:]
            if line:
                current_chunk.append(line)
                current_len = len(line)
        else:
            current_chunk.append(line)
            current_len += line_len

    if current_chunk:
        chunks.append("\n".join(current_chunk))

    return chunks or [text[:max_len]]


async def safe_send_message(
    bot: Bot,
    chat_id: Union[int, str],
    text: str,
    reply_markup: Optional[Union[InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove]] = None,
    parse_mode: Optional[str] = "Markdown",
    reply_to_message_id: Optional[int] = None,
) -> Optional[Message]:
    """
    Chatga xabarni xavfsiz yuboradi.
    Agar Markdown xatosi bo'lsa, avtomatik ravishda parse_mode=None bilan qayta urinadi.
    """
    chunks = chunk_text(text)
    last_msg = None

    for i, chunk in enumerate(chunks):
        markup = reply_markup if i == len(chunks) - 1 else None
        retry_count = 0

        while retry_count < 2:
            try:
                last_msg = await bot.send_message(
                    chat_id=chat_id,
                    text=chunk,
                    reply_markup=markup,
                    parse_mode=parse_mode,
                    reply_to_message_id=reply_to_message_id if i == 0 else None,
                )
                break
            except TelegramRetryAfter as e:
                logger.warning("Telegram FloodWait: %s soniya kutilmoqda...", e.retry_after)
                await asyncio.sleep(e.retry_after + 0.5)
                retry_count += 1
            except TelegramBadRequest as e:
                err_str = str(e).lower()
                if "can't parse entities" in err_str or "unmatched" in err_str:
                    logger.debug("Markdown parse xatosi: %s. Plain text bilan qayta yuborilmoqda.", e)
                    parse_mode = None
                    retry_count += 1
                else:
                    logger.error("safe_send_message TelegramBadRequest: %s", e)
                    break
            except Exception as exc:
                logger.error("safe_send_message noma'lum xato: %s", exc)
                break

    return last_msg


async def safe_message_answer(
    message: Message,
    text: str,
    reply_markup: Optional[Union[InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove]] = None,
    parse_mode: Optional[str] = "Markdown",
) -> Optional[Message]:
    """Message.answer uchun xavfsiz wrapper."""
    return await safe_send_message(
        bot=message.bot,
        chat_id=message.chat.id,
        text=text,
        reply_markup=reply_markup,
        parse_mode=parse_mode,
    )


async def safe_message_reply(
    message: Message,
    text: str,
    reply_markup: Optional[Union[InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove]] = None,
    parse_mode: Optional[str] = "Markdown",
) -> Optional[Message]:
    """Message.reply uchun xavfsiz wrapper."""
    return await safe_send_message(
        bot=message.bot,
        chat_id=message.chat.id,
        text=text,
        reply_markup=reply_markup,
        parse_mode=parse_mode,
        reply_to_message_id=message.message_id,
    )


async def safe_edit_text(
    target: Union[Message, CallbackQuery],
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    parse_mode: Optional[str] = "Markdown",
) -> Optional[Message]:
    """
    Xabarni xavfsiz tahrirlash (Message yoki CallbackQuery).
    MessageNotModified xatosini xotirjam qabul qiladi.
    Markdown parse xatosida avtomatik plain text fallback qiladi.
    """
    msg = target.message if isinstance(target, CallbackQuery) else target
    if not msg:
        return None

    try:
        return await msg.edit_text(
            text=text[:MAX_TG_TEXT_LEN],
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
    except TelegramBadRequest as e:
        err_str = str(e).lower()
        if "message is not modified" in err_str:
            return msg
        if "can't parse entities" in err_str or "unmatched" in err_str:
            logger.debug("safe_edit_text: Markdown xatosi (%s), plain text bilan urinilmoqda.", e)
            try:
                return await msg.edit_text(
                    text=text[:MAX_TG_TEXT_LEN],
                    reply_markup=reply_markup,
                    parse_mode=None,
                )
            except Exception as e2:
                logger.debug("safe_edit_text plain text fallback ham xato berdi: %s", e2)
        else:
            logger.debug("safe_edit_text TelegramBadRequest: %s", e)
    except Exception as exc:
        logger.debug("safe_edit_text boshqa xato: %s", exc)

    return None


async def safe_edit_or_send_long_message(
    target: Union[Message, CallbackQuery],
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    parse_mode: Optional[str] = "Markdown",
) -> Optional[Message]:
    """
    Xabarni xavfsiz tahrirlaydi yoki agar 4000 belgidan oshsa, qismlarga bo'lib yuboradi.
    Markdown parse xatolarida (can't parse entities) avtomatik plain text fallback qiladi.
    """
    msg = target.message if isinstance(target, CallbackQuery) else target
    if not msg:
        return None

    chunks = chunk_text(text, max_len=MAX_TG_TEXT_LEN)
    if not chunks:
        return msg

    first_chunk = chunks[0]
    markup_for_first = reply_markup if len(chunks) == 1 else None

    last_msg = None
    try:
        last_msg = await msg.edit_text(
            text=first_chunk,
            reply_markup=markup_for_first,
            parse_mode=parse_mode,
        )
    except TelegramBadRequest as e:
        err_str = str(e).lower()
        if "message is not modified" in err_str:
            last_msg = msg
        elif "can't parse entities" in err_str or "unmatched" in err_str:
            logger.debug("safe_edit_or_send_long_message Markdown xatosi: %s. Plain text qo'llanilmoqda.", e)
            try:
                last_msg = await msg.edit_text(
                    text=first_chunk,
                    reply_markup=markup_for_first,
                    parse_mode=None,
                )
            except Exception as e2:
                logger.error("safe_edit_or_send_long_message plain text edit xatosi: %s", e2)
        else:
            logger.error("safe_edit_or_send_long_message TelegramBadRequest: %s", e)
    except Exception as exc:
        logger.error("safe_edit_or_send_long_message edit error: %s", exc)

    # Agar matn 1 dan ortiq qismdan iborat bo'lsa, qolgan qismlarni ketma-ket yuboramiz
    if len(chunks) > 1:
        for i, extra_chunk in enumerate(chunks[1:]):
            is_last = (i == len(chunks) - 2)
            extra_markup = reply_markup if is_last else None
            sent = await safe_send_message(
                bot=msg.bot,
                chat_id=msg.chat.id,
                text=extra_chunk,
                reply_markup=extra_markup,
                parse_mode=parse_mode,
            )
            if sent:
                last_msg = sent

    return last_msg

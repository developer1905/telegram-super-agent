"""
tests/test_safe_send.py — Bulletproof Messaging va Safe Send Testlari (Phase 25)

Testlar:
1. chunk_text: 4096 belgidan qisqa matnlar bo'linmaydi
2. chunk_text: 4096 belgidan uzun matnlar xavfsiz qismlarga bo'linadi (har bir qism <= max_len)
3. chunk_text: Hech qanday newline bo'lmagan ulkan satrlar ham to'g'ri bo'linadi
4. safe_send_message: Oddiy xabarni muvaffaqiyatli yuborish
5. safe_send_message: Markdown parse xatosi yuz berganda avtomatik plain text (parse_mode=None) fallback
6. safe_edit_text: "message is not modified" xatosi tinchgina o'tkazib yuboriladi va crash bermaydi
7. safe_edit_text: Markdown tahrirlash xatosi bo'lganda plain text ga fallback qiladi
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest

from aiogram.exceptions import TelegramBadRequest
from core.safe_send import (
    chunk_text,
    safe_send_message,
    safe_edit_text,
    MAX_TG_TEXT_LEN,
)


class TestChunkText:
    """Matnni Telegram chegaralari bo'yicha qismlarga bo'lish testlari."""

    def test_short_text_not_chunked(self):
        text = "Salom, bu qisqa xabar."
        chunks = chunk_text(text, max_len=100)
        assert chunks == [text]

    def test_long_multiline_text_chunked(self):
        lines = [f"Qator raqami {i}: " + ("x" * 50) for i in range(50)]
        full_text = "\n".join(lines)
        max_len = 500
        chunks = chunk_text(full_text, max_len=max_len)

        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk) <= max_len
        reconstructed = "\n".join(chunks)
        assert len(reconstructed) >= len(full_text)

    def test_single_line_exceeding_max_len(self):
        giant_word = "a" * 1200
        chunks = chunk_text(giant_word, max_len=500)
        assert len(chunks) == 3
        assert len(chunks[0]) == 500
        assert len(chunks[1]) == 500
        assert len(chunks[2]) == 200
        assert "".join(chunks) == giant_word


class TestSafeSendMessage:
    """safe_send_message funksiyasining nosozliklarga bardoshliligi."""

    def test_successful_send(self):
        async def _test():
            mock_bot = AsyncMock()
            mock_msg = MagicMock()
            mock_bot.send_message.return_value = mock_msg

            result = await safe_send_message(
                bot=mock_bot,
                chat_id=123456,
                text="Oddiy xabar",
                parse_mode="Markdown",
            )

            assert result == mock_msg
            mock_bot.send_message.assert_awaited_once_with(
                chat_id=123456,
                text="Oddiy xabar",
                reply_markup=None,
                parse_mode="Markdown",
                reply_to_message_id=None,
            )

        asyncio.run(_test())

    def test_markdown_syntax_error_fallback(self):
        """Markdown entities xatosi bo'lganda parse_mode=None bilan qayta urinishi kerak."""
        async def _test():
            mock_bot = AsyncMock()
            mock_msg = MagicMock()

            # Birinchi chaqiriqda Bad Request (can't parse entities), ikkinchisida muvaffaqiyat
            mock_bot.send_message.side_effect = [
                TelegramBadRequest(method="sendMessage", message="Bad Request: can't parse entities: unclosed tag"),
                mock_msg,
            ]

            result = await safe_send_message(
                bot=mock_bot,
                chat_id=123456,
                text="*Buzuq markdown [link",
                parse_mode="Markdown",
            )

            assert result == mock_msg
            assert mock_bot.send_message.await_count == 2
            # Ikkinchi chaqiriqda parse_mode None bo'lishi shart
            second_call_kwargs = mock_bot.send_message.await_args_list[1].kwargs
            assert second_call_kwargs["parse_mode"] is None

        asyncio.run(_test())


class TestSafeEditText:
    """safe_edit_text funksiyasining testlari."""

    def test_message_not_modified_ignored_cleanly(self):
        async def _test():
            mock_msg = AsyncMock()
            mock_msg.edit_text.side_effect = TelegramBadRequest(
                method="editMessageText",
                message="Bad Request: message is not modified: specified new message content and reply markup are exactly the same",
            )

            result = await safe_edit_text(mock_msg, "O'zgarmagan matn")
            assert result == mock_msg

        asyncio.run(_test())

    def test_markdown_fallback_on_edit(self):
        async def _test():
            mock_msg = AsyncMock()
            mock_return = MagicMock()
            mock_msg.edit_text.side_effect = [
                TelegramBadRequest(method="editMessageText", message="Bad Request: can't parse entities"),
                mock_return,
            ]

            result = await safe_edit_text(mock_msg, "Buzuq **markdown")
            assert result == mock_return
            assert mock_msg.edit_text.await_count == 2
            second_call_kwargs = mock_msg.edit_text.await_args_list[1].kwargs
            assert second_call_kwargs["parse_mode"] is None

        asyncio.run(_test())

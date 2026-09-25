"""
tests/test_all_features_visible_to_all_users.py — Botdagi barcha funksiyalar barcha foydalanuvchilarga ko'rinishi va ma'lumotlar ajratilganligi testi
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from unittest.mock import AsyncMock, MagicMock
from config import ADMIN_ID
from core.database import db
from handlers.menu_handler import build_reply_keyboard_menu, build_main_menu, cmd_start
from core.astrology_agent import calculate_full_natal_chart


def test_start_menu_contains_all_categories_for_regular_user():
    """Oddiy foydalanuvchiga /start bosilganda barcha toifalar va to'liq klaviatura berilishini tekshirish."""
    async def _test():
        guest_uid = 888123456
        message = MagicMock()
        message.from_user.id = guest_uid
        message.from_user.username = "test_regular"
        message.from_user.first_name = "Ali"
        message.from_user.last_name = "Valiyev"
        message.answer = AsyncMock()

        ai_mgr = MagicMock()
        ai_mgr.current_role = "default"
        ai_mgr.current_provider = "gemini"

        await cmd_start(message, ai_mgr)

        # 2 ta xabar yuboriladi: 1) matn + ReplyKeyboard, 2) Asosiy Menyu + InlineKeyboard
        assert message.answer.call_count == 2

        first_call = message.answer.call_args_list[0]
        reply_kb = first_call.kwargs.get("reply_markup")
        assert reply_kb is not None

        # Reply keyboard tugmalarida barcha 5 ta toifa bo'lishi kerak
        button_texts = [btn.text for row in reply_kb.keyboard for btn in row]
        assert "🎨 AI & Kreativ Studio" in button_texts
        assert "💼 Ish & Unumdorlik" in button_texts
        assert "📈 SMM & Marketing" in button_texts
        assert "⚙️ Sozlamalar & Xotira" in button_texts
        assert "📊 Holat & Yordam" in button_texts

        second_call = message.answer.call_args_list[1]
        inline_kb = second_call.kwargs.get("reply_markup")
        assert inline_kb is not None
        inline_texts = [btn.text for row in inline_kb.inline_keyboard for btn in row]
        assert any("AI & Kreativ" in t for t in inline_texts)
        assert any("Ish & Unumdorlik" in t for t in inline_texts)
        assert any("SMM & Marketing" in t for t in inline_texts)
        assert any("Sozlamalar" in t for t in inline_texts)

    asyncio.run(_test())


def test_astrology_natal_chart_isolated_per_user():
    """Har bir foydalanuvchi o'z natal kartasiga ega bo'lishi va ma'lumotlar aralashmasligi testi."""
    async def _test():
        admin_uid = str(ADMIN_ID)
        user_a_uid = "600111222"
        user_b_uid = "600333444"

        # 1. Admin uchun natal karta
        admin_chart = calculate_full_natal_chart("1995-05-15", "14:00", "Toshkent")
        await db.save_astrology_profile(
            user_id=admin_uid,
            birth_date="1995-05-15",
            birth_time="14:00",
            city="Toshkent",
            chart_data=admin_chart,
        )

        # 2. User A uchun natal karta
        user_a_chart = calculate_full_natal_chart("2000-01-01", "10:30", "Samarqand")
        await db.save_astrology_profile(
            user_id=user_a_uid,
            birth_date="2000-01-01",
            birth_time="10:30",
            city="Samarqand",
            chart_data=user_a_chart,
        )

        # 3. User B hali karta kiritmagan
        user_b_profile = await db.get_astrology_profile(user_b_uid)
        assert user_b_profile is None

        # 4. User A o'z kartasini oladi va u Adminning ma'lumotlari bilan aralashmagan
        user_a_profile = await db.get_astrology_profile(user_a_uid)
        assert user_a_profile is not None
        assert user_a_profile["city"] == "Samarqand"
        assert user_a_profile["birth_date"] == "2000-01-01"
        assert user_a_profile["city"] != admin_chart["city"] or user_a_profile["birth_date"] != "1995-05-15"

        # 5. Admin o'z kartasini oladi
        admin_profile = await db.get_astrology_profile(admin_uid)
        assert admin_profile is not None
        assert admin_profile["city"] == "Toshkent"
        assert admin_profile["birth_date"] == "1995-05-15"

    asyncio.run(_test())


def test_facts_isolation_in_menu_memory():
    """Doimiy xotira (get_all_facts) har bir foydalanuvchining o'z ma'lumotlarini alohida ko'rsatish testi."""
    async def _test():
        uid_1 = "711000111"
        uid_2 = "722000222"

        await db.save_fact("sirli_kalit_1", "Parol12345", user_id=uid_1)
        await db.save_fact("sevimli_rang", "Yashil", user_id=uid_2)

        facts_1 = await db.get_all_facts(user_id=uid_1)
        facts_2 = await db.get_all_facts(user_id=uid_2)

        keys_1 = [f.get("key") for f in facts_1]
        keys_2 = [f.get("key") for f in facts_2]

        assert "sirli_kalit_1" in keys_1
        assert "sevimli_rang" not in keys_1

        assert "sevimli_rang" in keys_2
        assert "sirli_kalit_1" not in keys_2

        # Tozalash
        await db.delete_fact("sirli_kalit_1", user_id=uid_1)
        await db.delete_fact("sevimli_rang", user_id=uid_2)

    asyncio.run(_test())


if __name__ == "__main__":
    print("Testing start menu...", flush=True)
    test_start_menu_contains_all_categories_for_regular_user()
    print("Testing astrology natal chart isolation...", flush=True)
    test_astrology_natal_chart_isolated_per_user()
    print("Testing facts isolation in memory...", flush=True)
    test_facts_isolation_in_menu_memory()
    print("ALL TESTS PASSED SUCCESSFULLY!", flush=True)


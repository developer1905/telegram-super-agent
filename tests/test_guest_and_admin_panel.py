"""
tests/test_guest_and_admin_panel.py — Multi-tenant Guest Access & Admin Panel Tests
"""

import asyncio
import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from config import ADMIN_ID, BOT_TOKEN
from core.database import db
import security.api_auth as sa


def test_user_registration_and_blocking():
    """Foydalanuvchi ro'yxatdan o'tishi va bloklash mexanizmi testi."""
    async def _test():
        test_uid = 999111222
        # 1. Yangi foydalanuvchini ro'yxatga olish
        reg_res = await db.register_or_update_user(
            user_id=test_uid,
            username="testguest",
            first_name="Guest",
            last_name="User",
        )
        assert reg_res is not None
        assert reg_res["user_id"] == str(test_uid)

        # Yangi foydalanuvchi bloklanmagan bo'lishi kerak
        is_blocked = await db.is_user_blocked(test_uid)
        assert is_blocked is False

        # Xabarlar sonini oshirish
        await db.increment_user_message_count(test_uid)

        # 2. Foydalanuvchini bloklash
        await db.set_user_blocked_status(test_uid, is_blocked=True, reason="Spam / Hacking urinishi")
        assert await db.is_user_blocked(test_uid) is True

        # Ro'yxatda ma'lumotlar borligini tekshirish
        users = await db.get_all_users()
        guest_entry = next((u for u in users if str(u["user_id"]) == str(test_uid)), None)
        assert guest_entry is not None
        assert guest_entry["is_blocked"] == 1
        assert guest_entry["blocked_reason"] == "Spam / Hacking urinishi"
        assert guest_entry["message_count"] >= 1

        # 3. Blokdan chiqarish
        await db.set_user_blocked_status(test_uid, is_blocked=False)
        assert await db.is_user_blocked(test_uid) is False

        # 4. Admin hech qachon bloklanmasligini tekshirish
        await db.set_user_blocked_status(ADMIN_ID, is_blocked=True)
        assert await db.is_user_blocked(ADMIN_ID) is False

    asyncio.run(_test())


def test_rag_data_isolation():
    """Foydalanuvchilar orasida shaxsiy ma'lumotlar (RAG faktlar) tarqalmasligi testi."""
    async def _test():
        admin_uid = str(ADMIN_ID)
        guest_uid = "888777666"

        # Admin uchun maxfiy fakt saqlash
        await db.save_fact("admin_private_credit_card", "8600 9999 8888 7777", user_id=admin_uid)
        # Guest uchun o'zining fakti
        await db.save_fact("guest_public_hobby", "Futbol o'ynash", user_id=guest_uid)

        # Guest uchun RAG kontekst qurish
        guest_rag = await db.build_rag_context(user_id=guest_uid, context_type="private")
        assert "Futbol o'ynash" in guest_rag
        assert "8600 9999 8888 7777" not in guest_rag  # Admin kartasi guestga KELMASLIGI shart!

        # Tozalash
        await db.delete_fact("admin_private_credit_card", user_id=admin_uid)
        await db.delete_fact("guest_public_hobby", user_id=guest_uid)

    asyncio.run(_test())


def test_api_astrology_and_admin_security_guards():
    """Astrologiya va Admin Panel endpointlari faqat admin uchun ochiqligini tekshirish."""
    async def _test():
        guest_uid = "777888999"
        orig_validate = sa.validate_telegram_init_data

        try:
            # 1. Guest astrologiyaga murojaat qilganda -> 403 Forbidden
            sa.validate_telegram_init_data = lambda *args, **kwargs: (True, guest_uid, None)

            req_astro = make_mocked_request(
                "POST",
                "/api/astrology/calculate",
                headers={"X-Telegram-Init-Data": "query_id=guest_test&auth_date=12345"}
            )
            res_astro = await sa.require_webapp_auth(req_astro)
            assert res_astro is not None
            assert res_astro.status == 403

            # 2. Guest admin panelga murojaat qilganda -> 403 Forbidden
            req_admin = make_mocked_request(
                "GET",
                "/api/admin/users",
                headers={"X-Telegram-Init-Data": "query_id=guest_test&auth_date=12345"}
            )
            res_admin = await sa.require_webapp_auth(req_admin)
            assert res_admin is not None
            assert res_admin.status == 403

            # 3. Bloklangan foydalanuvchi oddiy API ga ham kira olmasligi -> 403 Forbidden
            blocked_uid = "555444333"
            await db.register_or_update_user(blocked_uid, username="blocked_user")
            await db.set_user_blocked_status(blocked_uid, is_blocked=True, reason="Hacking")

            sa.validate_telegram_init_data = lambda *args, **kwargs: (True, blocked_uid, None)

            req_blocked = make_mocked_request(
                "GET",
                "/api/facts",
                headers={"X-Telegram-Init-Data": "query_id=blocked_test&auth_date=12345"}
            )
            res_blocked = await sa.require_webapp_auth(req_blocked)
            assert res_blocked is not None
            assert res_blocked.status == 403

            # 4. Admin bo'lsa -> Ruxsat beriladi (res is None)
            sa.validate_telegram_init_data = lambda *args, **kwargs: (True, str(ADMIN_ID), None)
            req_admin_allowed = make_mocked_request(
                "GET",
                "/api/admin/users",
                headers={"X-Telegram-Init-Data": "query_id=admin_test&auth_date=12345"}
            )
            res_allowed = await sa.require_webapp_auth(req_admin_allowed)
            assert res_allowed is None  # None degani muvaffaqiyatli o'tdi

        finally:
            sa.validate_telegram_init_data = orig_validate

    asyncio.run(_test())

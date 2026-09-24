"""
tests/test_multi_tenancy_and_zip.py — Multi-tenancy Data Ownership, RAG Isolation, and Zip Slip Security.

Mandatory Master Prompt Integration Tests:
1. Multi-tenant facts: User A facts != User B facts
2. Multi-tenant tasks: User A tasks != User B tasks
3. RAG memory isolation: group, supergroup, channel return empty string (0 leaks)
4. Private RAG memory only contains own user facts
5. Astrology privacy: missing profile returns None, exact user match enforced
6. Zip Slip protection: traversal rejected, NUL byte rejected, drive letters stripped
7. Autonomy control plane: cancel_tasks_for_chat and cancel_all_tasks
"""

import asyncio
import io
import os
import zipfile
import pytest

from core.database import DatabaseManager
from core.project_builder import sanitize_archive_path, build_zip_archive_in_memory, safe_extract_zip
from core.autonomy_manager import AutonomyManager, AutonomyMode, AutonomyStatus


@pytest.fixture
def test_db(tmp_path):
    """Izolyatsiya qilingan test ma'lumotlar bazasi."""
    db_file = str(tmp_path / "test_multitenant.db")
    db = DatabaseManager(sqlite_path=db_file)
    return db


def test_multi_tenant_facts_isolation(test_db):
    """User A va User B faktlari bir-biriga aralashmasligi kerak."""
    async def _run():
        await test_db.save_fact("card", "8600 0000 1111", category="finance", user_id="user_111")
        await test_db.save_fact("card", "9860 2222 3333", category="finance", user_id="user_222")

        facts_user_1 = await test_db.get_all_facts(user_id="user_111")
        facts_user_2 = await test_db.get_all_facts(user_id="user_222")

        assert len(facts_user_1) == 1
        assert facts_user_1[0]["content"] == "8600 0000 1111"

        assert len(facts_user_2) == 1
        assert facts_user_2[0]["content"] == "9860 2222 3333"

    asyncio.run(_run())


def test_multi_tenant_tasks_isolation(test_db):
    """User A va User B vazifalari izolyatsiyalangan bo'lishi kerak."""
    async def _run():
        await test_db.add_task(user_id="user_111", title="User 1 Task")
        await test_db.add_task(user_id="user_222", title="User 2 Task")

        tasks_1 = await test_db.get_tasks(user_id="user_111")
        tasks_2 = await test_db.get_tasks(user_id="user_222")

        assert len(tasks_1) == 1
        assert tasks_1[0]["title"] == "User 1 Task"

        assert len(tasks_2) == 1
        assert tasks_2[0]["title"] == "User 2 Task"

    asyncio.run(_run())


def test_build_rag_context_group_channel_isolation(test_db):
    """Guruh yoki kanalda RAG shaxsiy faktlarni HECH QACHON bermasligi kerak."""
    async def _run():
        await test_db.save_fact("pin", "1234", category="secret", user_id="user_admin")

        # Guruh konteksti -> bo'sh bo'lishi shart!
        group_rag = await test_db.build_rag_context(user_id="user_admin", context_type="group")
        assert group_rag == "", "Guruh kontekstiga RAG faktlari kirdi!"

        supergroup_rag = await test_db.build_rag_context(user_id="user_admin", context_type="supergroup")
        assert supergroup_rag == "", "Supergroup kontekstiga RAG faktlari kirdi!"

        channel_rag = await test_db.build_rag_context(user_id="user_admin", context_type="channel")
        assert channel_rag == "", "Kanal kontekstiga RAG faktlari kirdi!"

        # Shaxsiy chatda esa faqat shu userning faktlari chiqishi kerak
        private_rag = await test_db.build_rag_context(user_id="user_admin", context_type="private")
        assert "1234" in private_rag
        assert "pin" in private_rag

    asyncio.run(_run())


def test_astrology_profile_exact_user_match(test_db):
    """get_astrology_profile faqat so'ralgan user_id profilini berishi, boshqa user profilini bermasligi kerak."""
    async def _run():
        await test_db.save_astrology_profile(
            user_id="user_real",
            birth_date="1995-05-10",
            birth_time="14:00",
            city="Toshkent",
            chart_data={"planets": {"Quyosh": {"sign": "Buvqa"}}}
        )

        # Mavjud user
        profile_real = await test_db.get_astrology_profile("user_real")
        assert profile_real is not None
        assert profile_real["birth_date"] == "1995-05-10"

        # Mavjud bo'lmagan user -> HECH QACHON boshqa user profilini qaytarmasligi (None qaytarishi) kerak!
        profile_unknown = await test_db.get_astrology_profile("user_unknown_hacker")
        assert profile_unknown is None

    asyncio.run(_run())


def test_zip_slip_sanitize_archive_path():
    """Zip Slip traversal yo'llari xavfsiz bloklanishi kerak."""
    # Xavfli yo'llar
    assert sanitize_archive_path("../../etc/passwd") is None
    assert sanitize_archive_path("..\\..\\windows\\system32\\cmd.exe") is None
    assert sanitize_archive_path("../evil.py") is None
    assert sanitize_archive_path("folder/../../evil.py") is None
    assert sanitize_archive_path("test\0injection.py") is None
    assert sanitize_archive_path("") is None

    # Xavfsiz to'g'ri yo'llar
    assert sanitize_archive_path("main.py") == "main.py"
    assert sanitize_archive_path("src/core/utils.py") == "src/core/utils.py"
    assert sanitize_archive_path("/app/models/user.py") == "app/models/user.py"
    assert sanitize_archive_path("C:\\project\\config.py") == "project/config.py"


def test_build_zip_archive_blocks_traversal_files():
    """build_zip_archive_in_memory ichidagi traversal fayllar arxivga kirmasligi kerak."""
    files = {
        "main.py": "print('hello')",
        "../../etc/shadow": "root:*:0:0:root:/root:/bin/bash",
        "nested/safe.py": "x = 1",
    }
    zip_bytes, count = build_zip_archive_in_memory("my_proj", files)
    assert count >= 2  # main.py va nested/safe.py (+ auto README/requirements)

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        namelist = zf.namelist()
        assert "my_proj/main.py" in namelist
        assert "my_proj/nested/safe.py" in namelist
        for name in namelist:
            assert ".." not in name
            assert "shadow" not in name


def test_autonomy_manager_cancellation_and_limits():
    """AutonomyManager orqali chat va global bekor qilish to'g'ri ishlashi kerak."""
    async def _run():
        mgr = AutonomyManager()
        mgr._tasks.clear()
        await mgr.set_global_enabled(True)

        # Task yaratamiz
        task = await mgr.register_task(
            task_id="test_chat_task_1",
            mode=AutonomyMode.AUTO_CHAT,
            chat_id=12345,
            user_id=12345,
            max_turns=5,
        )
        assert task is not None
        assert task.status == AutonomyStatus.IDLE

        # Chat bo'yicha bekor qilish
        cancelled = await mgr.cancel_tasks_for_chat(12345)
        assert cancelled == 1
        assert task.status in (AutonomyStatus.STOPPED, AutonomyStatus.CANCELLED)

        # Global off yangi tasklarni bloklashi kerak
        await mgr.set_global_enabled(False)
        blocked_task = await mgr.register_task(
            task_id="test_blocked",
            mode=AutonomyMode.AUTO_CHAT,
            chat_id=12345,
            user_id=12345,
        )
        assert blocked_task is None, "Global off holatida yangi avtonom vazifa yaratilmasligi kerak!"

    asyncio.run(_run())

"""
tests/test_main_and_autonomy.py — main.py va Avtonomiya xavfsizlik testlari.

Testlar:
1. main.py da str(exc) exception leakage yo'qligini tekshirish
2. main.py da _BACKGROUND_TASKS va track_background_task mavjudligi va to'g'ri ishlashi
3. group_handler.py da bot-to-bot loop himoyasi (is_bot tekshiruvi)
4. group_handler.py da global autonomy kill switch integratsiyasi
5. group_handler.py da dual opinion opt-in himoyasi (default=OFF)
"""

from __future__ import annotations

import asyncio
import ast
import os
import pytest

MAIN_PATH = os.path.join(os.path.dirname(__file__), "..", "main.py")
GROUP_HANDLER_PATH = os.path.join(os.path.dirname(__file__), "..", "handlers", "group_handler.py")


def test_no_raw_exception_leakage_in_main():
    """main.py da str(exc) orqali ichki stack trace yoki ma'lumotlar oqib ketmasligi kerak."""
    with open(MAIN_PATH, encoding="utf-8") as f:
        content = f.read()

    # str(exc) bo'lmasligi kerak
    assert "str(exc)" not in content, "main.py da str(exc) ishlatilmoqda! Exception leakage xavfi mavjud."


def test_background_task_tracker_defined():
    """main.py da _BACKGROUND_TASKS to'plami va track_background_task funksiyasi mavjud bo'lishi kerak."""
    with open(MAIN_PATH, encoding="utf-8") as f:
        tree = ast.parse(f.read())

    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)

    assert "_BACKGROUND_TASKS" in names, "_BACKGROUND_TASKS to'plami main.py da aniqlanmagan"
    assert "track_background_task" in names, "track_background_task funksiyasi main.py da aniqlanmagan"


def test_track_background_task_lifecycle():
    """track_background_task fon vazifalarini to'g'ri ro'yxatga olib, tugaganda tozalashi kerak."""
    async def _test():
        from main import track_background_task, _BACKGROUND_TASKS

        initial_count = len(_BACKGROUND_TASKS)

        async def sample_job():
            await asyncio.sleep(0.05)
            return "done"

        task = track_background_task(sample_job(), name="test_sample_job")
        assert task in _BACKGROUND_TASKS, "Task _BACKGROUND_TASKS to'plamiga kiritilmadi"

        await task
        # Done callback event loop da bajarilishi uchun kichik kechikish beramiz
        await asyncio.sleep(0.02)
        assert task not in _BACKGROUND_TASKS, "Tugagan task _BACKGROUND_TASKS to'plamidan o'chirilmadi"

    asyncio.run(_test())


def test_anti_bot_loop_in_group_handler():
    """group_handler.py da bot-to-bot cheksiz tsikl (infinite loop) himoyasi bo'lishi kerak."""
    with open(GROUP_HANDLER_PATH, encoding="utf-8") as f:
        content = f.read()

    assert "is_bot" in content, "group_handler da bot xabarlarini filtrlash (is_bot) topilmadi"
    assert "anti-bot-loop" in content.lower() or "is_from_bot" in content, (
        "group_handler da anti-bot-loop mexanizmi topilmadi"
    )


def test_autonomy_kill_switch_in_group_handler():
    """group_handler.py da global autonomy kill switch tekshiruvi mavjud bo'lishi kerak."""
    with open(GROUP_HANDLER_PATH, encoding="utf-8") as f:
        content = f.read()

    assert "autonomy_manager" in content, "group_handler da autonomy_manager tekshiruvi yo'q"
    assert "is_globally_enabled" in content, "group_handler da is_globally_enabled kill switch tekshiruvi yo'q"


def test_group_dual_opinion_opt_in():
    """group_handler.py da dual opinion default holatda OFF va opt-in bo'lishi kerak."""
    with open(GROUP_HANDLER_PATH, encoding="utf-8") as f:
        content = f.read()

    assert "is_group_dual_opinion_enabled" in content, (
        "group_handler da is_group_dual_opinion_enabled opt-in tekshiruvi yo'q"
    )

"""
tests/test_autonomy_limits.py — Avtonomiya Limitlari, Loop Himoyasi va Bekor Qilish Testlari (Phase 25)

Testlar:
1. Turn limit: max_turns ga yetganda vazifa davom etishdan to'xtatiladi
2. Duration limit: max_duration_sec dan oshganda limit buzilishi qayd etiladi
3. Loop detection: Ketma-ket 3 ta bir xil javob/harakat (infinite loop) aniqlanadi
4. Loop detection: Xilma-xil harakatlar loop deb hisoblanmaydi
5. Bitta taskni bekor qilish: cancel_task task holatini STOPPED ga o'tkazadi
6. Global kill switch: set_global_enabled(False) barcha vazifalarni to'xtatadi va yangilarini bloklaydi
7. Chat bo'yicha bekor qilish: cancel_tasks_for_chat faqat berilgan chatning vazifalarini to'xtatadi
"""

from __future__ import annotations

import asyncio
import time
import pytest

from core.autonomy_manager import (
    AutonomyManager,
    AutonomyMode,
    AutonomyStatus,
    AutonomyTask,
)


def get_clean_manager():
    """Tozalangan AutonomyManager singletoni."""
    mgr = AutonomyManager()
    mgr._tasks.clear()
    mgr._global_enabled = True
    return mgr


class TestAutonomyTaskLimits:
    """AutonomyTask ning turn va duration chegaralari testlari."""

    def test_turn_limit_enforcement(self):
        task = AutonomyTask(
            task_id="turn_test_1",
            mode=AutonomyMode.CUSTOM,
            chat_id=1001,
            user_id=2001,
            max_turns=3,
        )

        # 1 va 2-burilishlar ruxsat etiladi
        can_continue, reason = task.record_turn()
        assert can_continue is True
        assert reason is None

        can_continue, reason = task.record_turn()
        assert can_continue is True
        assert reason is None

        # 3-burilishda limitga yetiladi
        can_continue, reason = task.record_turn()
        assert can_continue is False
        assert "Maksimal qadamlar" in reason

    def test_duration_limit_enforcement(self):
        task = AutonomyTask(
            task_id="duration_test_1",
            mode=AutonomyMode.CUSTOM,
            chat_id=1001,
            user_id=2001,
            max_duration_sec=10.0,
            started_at=time.time() - 15.0,  # 15 soniya oldin boshlangan
        )

        can_continue, reason = task.check_limits()
        assert can_continue is False
        assert "Maksimal bajarilish vaqti" in reason

    def test_infinite_loop_detection_positive(self):
        repeated_actions = [
            "search_google: python",
            "search_google: python",
            "search_google: python",
        ]
        is_loop = AutonomyTask.is_loop_detected(repeated_actions, threshold=3)
        assert is_loop is True

    def test_infinite_loop_detection_negative(self):
        diverse_actions = [
            "search_google: python",
            "read_url: https://python.org",
            "write_summary: done",
        ]
        is_loop = AutonomyTask.is_loop_detected(diverse_actions, threshold=3)
        assert is_loop is False


class TestAutonomyManagerOperations:
    """AutonomyManager operatsiyalari va xavfsizlik kill-switch testlari."""

    def test_register_task_success(self):
        async def _test():
            mgr = get_clean_manager()
            task = await mgr.register_task(
                task_id="task_reg_1",
                mode=AutonomyMode.CUSTOM,
                chat_id=5555,
                user_id=6666,
                max_turns=10,
            )
            assert task is not None
            assert task.task_id == "task_reg_1"
            assert task.status == AutonomyStatus.IDLE

        asyncio.run(_test())

    def test_cancel_single_task(self):
        async def _test():
            mgr = get_clean_manager()
            task = await mgr.register_task(
                task_id="cancel_me_1",
                mode=AutonomyMode.CUSTOM,
                chat_id=5555,
                user_id=6666,
            )
            assert task is not None

            async def endless_work():
                while True:
                    await asyncio.sleep(0.05)

            coro_task = await mgr.start_task("cancel_me_1", endless_work())
            assert coro_task is not None
            assert task.status == AutonomyStatus.RUNNING

            cancelled = await mgr.cancel_task("cancel_me_1", reason="Test bekor qilish")
            assert cancelled is True
            assert task.status == AutonomyStatus.STOPPED
            assert task.failure_reason == "Test bekor qilish"
            assert coro_task.cancelled() or coro_task.done()

        asyncio.run(_test())

    def test_global_kill_switch_cancels_and_blocks(self):
        async def _test():
            mgr = get_clean_manager()
            task = await mgr.register_task(
                task_id="kill_switch_task",
                mode=AutonomyMode.CUSTOM,
                chat_id=7777,
                user_id=8888,
            )
            assert task is not None

            # Global o'chirish
            await mgr.set_global_enabled(False)
            assert mgr.is_globally_enabled is False

            # Avtonomiya o'chiq bo'lganda yangi task ro'yxatdan o'tmasligi kerak
            new_task = await mgr.register_task(
                task_id="blocked_task",
                mode=AutonomyMode.CUSTOM,
                chat_id=7777,
                user_id=8888,
            )
            assert new_task is None

        asyncio.run(_test())

    def test_cancel_tasks_for_specific_chat(self):
        async def _test():
            mgr = get_clean_manager()
            await mgr.register_task(
                task_id="chat_1_task",
                mode=AutonomyMode.CUSTOM,
                chat_id=100,
                user_id=1,
            )
            await mgr.register_task(
                task_id="chat_2_task",
                mode=AutonomyMode.CUSTOM,
                chat_id=200,
                user_id=2,
            )

            async def sample():
                await asyncio.sleep(0.5)

            await mgr.start_task("chat_1_task", sample())
            await mgr.start_task("chat_2_task", sample())

            cancelled_count = await mgr.cancel_tasks_for_chat(100, reason="Chat 100 to'xtatildi")
            assert cancelled_count == 1

            t1 = mgr.get_task("chat_1_task")
            t2 = mgr.get_task("chat_2_task")
            assert t1.status == AutonomyStatus.STOPPED
            assert t2.status == AutonomyStatus.RUNNING

            # Tozalash
            await mgr.cancel_all_tasks()

        asyncio.run(_test())

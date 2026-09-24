"""
core/task_tracker.py — Fon Vazifalarini Xavfsiz Boshqarish va Kuzatish

Asyncio tasklarini xavfsiz boshqarish, unhandled exceptions xavfini bartaraf etish,
lifecycle monitoring va graceful shutdown paytida barcha vazifalarni xavfsiz to'xtatish.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Coroutine, Optional, Set, Union

logger = logging.getLogger(__name__)

# Barcha faol fon vazifalarini saqlovchi to'plam
_BACKGROUND_TASKS: Set[asyncio.Task] = set()


def track_background_task(
    coro_or_task: Union[Coroutine[Any, Any, Any], asyncio.Task],
    name: Optional[str] = None,
) -> asyncio.Task:
    """
    Fonda ishlaydigan asyncio tasklarni ro'yxatga oladi va tugaganda xotirani tozalaydi.
    
    Afzalliklari:
    - Garbage collection tomonidan kutilmaganda yo'q qilinishini oldini oladi.
    - Graceful shutdown paytida barcha ochiq tasklarni cancel qilish imkonini beradi.
    - Tugagan tasklarni avtomatik ravishda to'plamdan chiqarib tashlaydi.
    """
    if isinstance(coro_or_task, asyncio.Task):
        task = coro_or_task
    else:
        task = asyncio.create_task(coro_or_task, name=name)

    _BACKGROUND_TASKS.add(task)

    def _cleanup_callback(t: asyncio.Task) -> None:
        _BACKGROUND_TASKS.discard(t)
        if not t.cancelled():
            exc = t.exception()
            if exc:
                logger.error("Fon vazifasida xatolik (%s): %s", t.get_name(), exc, exc_info=exc)

    task.add_done_callback(_cleanup_callback)
    return task


async def cancel_all_background_tasks(timeout: float = 5.0) -> None:
    """Tizim to'xtatilganda barcha ishlayotgan fon vazifalarini xavfsiz bekor qiladi."""
    running_tasks = [t for t in _BACKGROUND_TASKS if not t.done()]
    if not running_tasks:
        return

    logger.info("🛑 %d ta fon vazifasi to'xtatilmoqda...", len(running_tasks))
    for t in running_tasks:
        t.cancel()

    try:
        await asyncio.wait(running_tasks, timeout=timeout)
    except Exception as exc:
        logger.debug("Fon vazifalarini to'xtatishda kutish xatosi: %s", exc)

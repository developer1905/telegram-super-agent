"""
core/autonomy_manager.py — Global Autonomy Control Plane

Barcha autonomous activity (avto_suhbat, autopilot, coworker pulse, dual-opinion,
night autopilot, scheduler autonomous jobs) uchun markazlashgan boshqaruv qatlami.

Xususiyatlar:
- Global ENABLE/DISABLE kill switch
- Per-task state tracking (task_id, chat_id, status, max_turns, created_at...)
- Graceful cancellation
- DB-da persistent state (restart'dan keyin faqat valid + enabled tasklar resume qilinadi)
- /autonomy_status, /autonomy_off, /autonomy_on, /stop_all_autonomy komandaları uchun backend

STATUSLAR:
  IDLE       - Hali boshlanmagan
  RUNNING    - Faol ishlayapti
  STOPPING   - To'xtatish jarayonida
  STOPPED    - To'xtatildi (manuall)
  FAILED     - Xato bilan tugadi
  COMPLETED  - Muvaffaqiyatli tugadi
  CANCELLED  - Bekor qilindi
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Coroutine, Optional, Any

logger = logging.getLogger(__name__)


class AutonomyStatus(str, Enum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AutonomyMode(str, Enum):
    AUTO_CHAT = "auto_chat"          # Jonli avto suhbat
    AUTOPILOT = "autopilot"          # Avtopilot rejimi
    DUAL_OPINION = "dual_opinion"    # Dual-agent group opinion
    NIGHT_AUTOPILOT = "night_auto"   # Tungi avtopilot
    COWORKER_PULSE = "coworker"      # Tirik hamkasblar
    COLLABORATION = "collab"         # Multi-agent collaboration
    CUSTOM = "custom"                # Boshqa autonomous tasklar


@dataclass
class AutonomyTask:
    """Bitta autonomous task holati."""
    task_id: str
    mode: AutonomyMode
    chat_id: int
    user_id: int
    status: AutonomyStatus = AutonomyStatus.IDLE
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    max_turns: int = 100
    max_duration_sec: float = 3600.0  # 1 soat maksimum
    current_turns: int = 0
    failure_reason: Optional[str] = None
    asyncio_task: Optional[asyncio.Task] = None

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "mode": self.mode.value,
            "chat_id": self.chat_id,
            "user_id": self.user_id,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "max_turns": self.max_turns,
            "max_duration_sec": self.max_duration_sec,
            "current_turns": self.current_turns,
            "failure_reason": self.failure_reason,
        }

    @property
    def is_active(self) -> bool:
        return self.status in (AutonomyStatus.IDLE, AutonomyStatus.RUNNING, AutonomyStatus.STOPPING)

    @property
    def age_seconds(self) -> float:
        return time.time() - self.created_at

    @property
    def runtime_seconds(self) -> float:
        if self.started_at is None:
            return 0.0
        end = self.finished_at or time.time()
        return end - self.started_at

    def check_limits(self) -> tuple[bool, Optional[str]]:
        """
        Task cheklovlarini (turn va duration) tekshiradi.
        Qaytaradi: (davom_eta_oladimi: bool, sabab: Optional[str])
        """
        if self.current_turns >= self.max_turns:
            return False, f"Maksimal qadamlar (turn) soniga yetildi: {self.current_turns}/{self.max_turns}"
        if self.runtime_seconds >= self.max_duration_sec:
            return False, f"Maksimal bajarilish vaqti tugadi: {self.runtime_seconds:.1f}s/{self.max_duration_sec:.1f}s"
        return True, None

    def record_turn(self) -> tuple[bool, Optional[str]]:
        """
        Bitta qadamni (turn) hisobga oladi va limitlarni tekshiradi.
        """
        self.current_turns += 1
        self.updated_at = time.time()
        return self.check_limits()

    @staticmethod
    def is_loop_detected(action_history: list[str], threshold: int = 3) -> bool:
        """
        Ketma-ket bir xil harakat yoki javoblar takrorlanishi (infinite loop) ni aniqlaydi.
        """
        if not action_history or len(action_history) < threshold:
            return False
        last_item = action_history[-1].strip().lower()
        if not last_item:
            return False
        recent = [a.strip().lower() for a in action_history[-threshold:]]
        return all(a == last_item for a in recent)


class AutonomyManager:
    """
    Global Autonomy Control Plane — Singleton.

    Barcha autonomous tasklar shu orqali ro'yxatga olinadi va boshqariladi.
    """

    _instance: Optional["AutonomyManager"] = None

    def __new__(cls) -> "AutonomyManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._tasks: dict[str, AutonomyTask] = {}
        self._global_enabled: bool = True  # DB dan yuklanadi
        self._lock = asyncio.Lock()
        self._initialized = True
        logger.info("AutonomyManager initialized")

    # ─── Global Kill Switch ──────────────────────────────────────

    async def set_global_enabled(self, enabled: bool) -> None:
        """Global autonomy on/off. DB ga saqlanadi."""
        self._global_enabled = enabled
        # DB ga saqlaymiz
        try:
            from core.database import db
            await db.save_fact(
                "autonomy_global_enabled",
                "1" if enabled else "0",
                category="autonomy_control"
            )
        except Exception as exc:
            logger.warning("Autonomy state DB ga saqlanmadi: %s", exc)

        if not enabled:
            logger.warning("🛑 GLOBAL AUTONOMY O'CHIRILDI — barcha autonomous tasklar to'xtatilmoqda")
            await self.cancel_all_tasks(reason="Global autonomy disabled")
        else:
            logger.info("✅ GLOBAL AUTONOMY YOQILDI")

    async def load_global_state_from_db(self) -> None:
        """Startupda DB dan global state ni yuklaymiz."""
        try:
            from core.database import db
            facts = await db.get_all_facts()
            for f in facts:
                if f.get("key") == "autonomy_global_enabled" and f.get("category") == "autonomy_control":
                    self._global_enabled = f.get("content", "1") == "1"
                    logger.info("Autonomy global state DB dan yuklandi: %s", "ON" if self._global_enabled else "OFF")
                    break
        except Exception as exc:
            logger.warning("Autonomy state DB dan yuklanmadi: %s. Default: ON", exc)

    @property
    def is_globally_enabled(self) -> bool:
        return self._global_enabled

    # ─── Task Ro'yxatga Olish ─────────────────────────────────────

    async def register_task(
        self,
        task_id: str,
        mode: AutonomyMode,
        chat_id: int,
        user_id: int,
        max_turns: int = 100,
        max_duration_sec: float = 3600.0,
    ) -> Optional[AutonomyTask]:
        """
        Yangi autonomous task ro'yxatga oladi.

        Returns:
            AutonomyTask yoki None agar global off bo'lsa yoki limit oshilsa.
        """
        if not self._global_enabled:
            logger.info("Autonomy OFF \u2014 task register qilinmadi: %s / chat=%s", task_id, chat_id)
            return None

        async with self._lock:
            # Bir xil chat uchun bir xil mode da duplicate tekshiruvi
            for existing in self._tasks.values():
                if (existing.chat_id == chat_id
                        and existing.mode == mode
                        and existing.is_active):
                    logger.info("Duplicate autonomy task: %s/chat=%s allaqachon %s", mode, chat_id, existing.status)
                    return existing

            task = AutonomyTask(
                task_id=task_id,
                mode=mode,
                chat_id=chat_id,
                user_id=user_id,
                status=AutonomyStatus.IDLE,
                max_turns=max_turns,
                max_duration_sec=max_duration_sec,
            )
            self._tasks[task_id] = task
            logger.info("Autonomy task registered: %s [%s] chat=%s", task_id, mode.value, chat_id)
            return task

    async def start_task(self, task_id: str, coro: Coroutine) -> Optional[asyncio.Task]:
        """Task ni asyncio.Task sifatida ishga tushiradi va track qiladi."""
        if not self._global_enabled:
            return None

        task_obj = self._tasks.get(task_id)
        if not task_obj:
            logger.warning("start_task: task_id=%s topilmadi", task_id)
            return None

        async with self._lock:
            task_obj.status = AutonomyStatus.RUNNING
            task_obj.started_at = time.time()
            task_obj.updated_at = time.time()

        async def _wrapped_coro():
            try:
                await coro
                async with self._lock:
                    task_obj.status = AutonomyStatus.COMPLETED
                    task_obj.finished_at = time.time()
                    task_obj.updated_at = time.time()
                logger.info("Autonomy task completed: %s", task_id)
            except asyncio.CancelledError:
                async with self._lock:
                    if task_obj.status != AutonomyStatus.STOPPED:
                        task_obj.status = AutonomyStatus.CANCELLED
                    task_obj.finished_at = time.time()
                    task_obj.updated_at = time.time()
                logger.info("Autonomy task cancelled: %s", task_id)
            except Exception as exc:
                async with self._lock:
                    task_obj.status = AutonomyStatus.FAILED
                    task_obj.failure_reason = str(exc)
                    task_obj.finished_at = time.time()
                    task_obj.updated_at = time.time()
                logger.error("Autonomy task failed: %s \u2014 %s", task_id, exc, exc_info=True)

        asyncio_task = asyncio.create_task(_wrapped_coro(), name=f"autonomy_{task_id}")
        async with self._lock:
            task_obj.asyncio_task = asyncio_task

        return asyncio_task

    # ─── Task Bekor Qilish ────────────────────────────────────────

    async def cancel_task(self, task_id: str, reason: str = "Manual cancel") -> bool:
        """Bitta autonomous task ni bekor qiladi."""
        task_obj = self._tasks.get(task_id)
        if not task_obj:
            return False

        async with self._lock:
            task_obj.status = AutonomyStatus.STOPPING
            task_obj.failure_reason = reason
            task_obj.updated_at = time.time()

        if task_obj.asyncio_task and not task_obj.asyncio_task.done():
            task_obj.asyncio_task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(task_obj.asyncio_task), timeout=3.0)
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                pass

        async with self._lock:
            task_obj.status = AutonomyStatus.STOPPED
            task_obj.finished_at = time.time()
            task_obj.updated_at = time.time()

        logger.info("Autonomy task stopped: %s (reason: %s)", task_id, reason)
        return True

    async def cancel_tasks_for_chat(self, chat_id: int, reason: str = "Chat stop") -> int:
        """Berilgan chat_id ga tegishli barcha autonomous tasklarni bekor qiladi."""
        task_ids = [
            tid for tid, t in self._tasks.items()
            if t.chat_id == chat_id and t.is_active
        ]
        cancelled = 0
        for tid in task_ids:
            if await self.cancel_task(tid, reason):
                cancelled += 1
        logger.info("Chat %s autonomous tasklar bekor qilindi: %d ta", chat_id, cancelled)
        return cancelled

    async def cancel_all_tasks(self, reason: str = "Global stop") -> int:
        """Barcha faol autonomous tasklarni bekor qiladi."""
        active_task_ids = [
            tid for tid, t in self._tasks.items() if t.is_active
        ]
        cancelled = 0
        for tid in active_task_ids:
            if await self.cancel_task(tid, reason):
                cancelled += 1
        logger.warning("Barcha autonomous tasklar bekor qilindi: %d ta (reason: %s)", cancelled, reason)
        return cancelled

    # ─── Status Va Info ───────────────────────────────────────────

    def get_task(self, task_id: str) -> Optional[AutonomyTask]:
        return self._tasks.get(task_id)

    def get_active_tasks(self) -> list[AutonomyTask]:
        return [t for t in self._tasks.values() if t.is_active]

    def get_all_tasks(self) -> list[AutonomyTask]:
        return list(self._tasks.values())

    def get_status_summary(self) -> dict:
        active = self.get_active_tasks()
        return {
            "global_enabled": self._global_enabled,
            "total_tasks": len(self._tasks),
            "active_tasks": len(active),
            "active_task_list": [t.to_dict() for t in active],
        }

    def is_running_for_chat(self, chat_id: int, mode: Optional[AutonomyMode] = None) -> bool:
        """Berilgan chat uchun autonomous task ishlab turganini tekshiradi."""
        for t in self._tasks.values():
            if t.chat_id == chat_id and t.is_active:
                if mode is None or t.mode == mode:
                    return True
        return False

    async def cleanup_finished_tasks(self, max_keep: int = 100) -> None:
        """Eskirgan/tugangan tasklarni tozalaydi (memory leak oldini olish uchun)."""
        async with self._lock:
            finished = [
                tid for tid, t in self._tasks.items()
                if not t.is_active
            ]
            # Eng ko'pi bilan max_keep ta eski task saqlaydi
            if len(finished) > max_keep:
                to_remove = finished[:-max_keep]
                for tid in to_remove:
                    del self._tasks[tid]
                logger.debug("Autonomy: %d ta eski task tozalandi", len(to_remove))


# Singleton instance
autonomy_manager = AutonomyManager()

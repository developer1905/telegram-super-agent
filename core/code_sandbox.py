"""
core/code_sandbox.py — Xavfsiz Kod Execution (Security-Hardened)

XAVFSIZLIK ARXITEKTURASI:
- Docker-based isolated execution (PREFERRED, ishlab chiqarishda tavsiya qilinadi)
- Agar Docker mavjud bo'lmasa: execution RAD etiladi (unsafe fallback YO'Q)

Docker izolyatsiyasi:
- Non-root foydalanuvchi
- Read-only filesystem (write faqat /tmp/sandbox ga)
- Network DISABLED
- CPU limit: 0.5 core
- Memory limit: 128MB
- Process limit (pids-limit): 50
- Execution timeout: configurable (default 12s)
- stdout/stderr size limit: 4KB
- Automatic container cleanup
- No host filesystem mount

MUHIM: AI-generated code execution va oddiy utility subprocess larni
bu modul orqali birga ishlatmang. Bu faqat AI kod sandboxi uchun.

Regex-based filtering (eski usul) production sandbox sifatida ISHLATILMAYDI.
"""

from __future__ import annotations

import asyncio
import html
import logging
import os
import re
import sys
import tempfile
import time
import uuid
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# Docker mavjudligini bir marta tekshiramiz
_DOCKER_AVAILABLE: Optional[bool] = None
_DOCKER_CHECK_LOCK = asyncio.Lock()


async def _check_docker_available() -> bool:
    """Docker daemon mavjudligi va ishlayotganligini tekshiradi."""
    global _DOCKER_AVAILABLE
    if _DOCKER_AVAILABLE is not None:
        return _DOCKER_AVAILABLE

    async with _DOCKER_CHECK_LOCK:
        if _DOCKER_AVAILABLE is not None:
            return _DOCKER_AVAILABLE

        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "info",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.communicate(), timeout=5.0)
            _DOCKER_AVAILABLE = (proc.returncode == 0)
        except (FileNotFoundError, asyncio.TimeoutError, Exception):
            _DOCKER_AVAILABLE = False

        logger.info("Docker sandbox mavjud: %s", _DOCKER_AVAILABLE)
        return _DOCKER_AVAILABLE


def extract_python_code(text: str) -> str:
    """Matn ichidagi ```python ... ``` yoki ``` ... ``` blokini ajratib oladi."""
    m = re.search(r"```(?:python|py)?\s*(.*?)\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return text.strip()


def _basic_safety_precheck(code: str) -> Tuple[bool, Optional[str]]:
    """
    Kod xavfsizligini dastlabki tekshirish (Docker bilan ham ishlatiladi, chunki obvious muammolarni aniqlash uchun).
    Bu Docker isolation ning o'rnini BOSMAYDI — faqat qo'shimcha qatlam.
    """
    # Juda uzun kodlar qabul qilinmaydi
    if len(code) > 50_000:
        return False, "Kod juda uzun (>50KB). Iltimos, qisqaroq bo'lakda yuboring."

    # Bo'sh kod
    if not code.strip():
        return False, "Bo'sh kod yuborildi."

    return True, None


async def execute_python_code_docker(
    code: str,
    timeout_sec: float = 12.0,
    image: str = "python:3.11-slim",
) -> dict:
    """
    Python kodini Docker containerida izolyatsiya qilingan holda ishga tushiradi.

    Docker sozlamalari:
    - --rm: container avtomatik o'chiriladi
    - --network none: tarmoq o'chirilgan
    - --memory 128m: xotira limiti
    - --cpus 0.5: CPU limiti
    - --pids-limit 50: jarayonlar soni limiti
    - --read-only: filesystem faqat o'qish uchun
    - --tmpfs /tmp/sandbox:size=10m: faqat sandbox tmp uchun yozish
    - --user nobody: non-root
    """
    tmp_id = uuid.uuid4().hex[:12]
    tmp_dir = tempfile.gettempdir()
    host_code_file = os.path.join(tmp_dir, f"sandbox_{tmp_id}.py")

    try:
        with open(host_code_file, "w", encoding="utf-8") as f:
            f.write(code)

        start_t = time.time()

        docker_cmd = [
            "docker", "run",
            "--rm",
            "--network", "none",
            "--memory", "128m",
            "--cpus", "0.5",
            "--pids-limit", "50",
            "--read-only",
            "--tmpfs", "/tmp/sandbox:size=10m,noexec",
            "--user", "nobody",
            "--workdir", "/tmp/sandbox",
            "--name", f"sandbox_{tmp_id}",
            "-v", f"{host_code_file}:/sandbox_code.py:ro",
            image,
            "python", "-c",
            # sys.setrecursionlimit cheklovi + kod yuklash
            "import sys; sys.setrecursionlimit(1000); exec(open('/sandbox_code.py').read())",
        ]

        proc = await asyncio.create_subprocess_exec(
            *docker_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout_data, stderr_data = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_sec + 5.0  # Docker overhead uchun extra 5s
            )
        except asyncio.TimeoutError:
            # Container ni majburan o'chiramiz
            try:
                kill_proc = await asyncio.create_subprocess_exec(
                    "docker", "kill", f"sandbox_{tmp_id}",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await asyncio.wait_for(kill_proc.communicate(), timeout=5.0)
            except Exception:
                pass
            return {
                "success": False,
                "stdout": "",
                "stderr": f"TimeoutError: Kod {timeout_sec}s ichida yakunlanmadi.",
                "returncode": -1,
                "duration": round(time.time() - start_t, 2),
                "error_message": "Vaqt me'yori tugadi.",
                "sandbox_type": "docker",
            }

        duration = round(time.time() - start_t, 3)
        # stdout/stderr uchun 4KB limit
        stdout_str = stdout_data.decode("utf-8", errors="replace").strip()[:4096]
        stderr_str = stderr_data.decode("utf-8", errors="replace").strip()[:4096]
        returncode = proc.returncode

        return {
            "success": returncode == 0,
            "stdout": stdout_str,
            "stderr": stderr_str,
            "returncode": returncode,
            "duration": duration,
            "error_message": stderr_str if returncode != 0 else None,
            "sandbox_type": "docker",
        }

    except Exception as exc:
        logger.error("Docker sandbox xatosi: %s", exc)
        return {
            "success": False,
            "stdout": "",
            "stderr": "Docker sandbox ichki xatosi.",
            "returncode": -1,
            "duration": 0.0,
            "error_message": "Sandbox ichki xatosi.",
            "sandbox_type": "docker",
        }
    finally:
        try:
            if os.path.exists(host_code_file):
                os.remove(host_code_file)
        except Exception:
            pass


async def execute_python_code(
    code_or_text: str,
    timeout_sec: float = 12.0,
    user_id: int = 0,
    context_type: str = "private",
    is_admin: bool = False,
    user_permissions: Optional[list[str]] = None,
) -> dict:
    """
    Python kodini xavfsiz sandbox da ishga tushiradi.

    XAVFSIZLIK QARORLARI:
    - ToolPermissionManager orqali ruxsatlar tekshiruvi (HIGH risk).
    - Docker mavjud bo'lsa: Docker-based izolyatsiya (ishlab chiqarishda tavsiya qilinadi).
    - Docker mavjud bo'lmasa: EXECUTION RAD ETILADI (unsafe host execution qilinmaydi).

    Qaytaradi:
    {
        "success": bool,
        "stdout": str,
        "stderr": str,
        "returncode": int,
        "duration": float,
        "error_message": Optional[str],
        "sandbox_type": str,  # "docker" | "unavailable" | "permission_denied"
    }
    """
    # 0. Tool Permission tekshiruvi
    if user_id > 0:
        from security.tool_permission import tool_permission_manager
        allowed, reason = tool_permission_manager.can_execute(
            tool_name="execute_code",
            user_id=user_id,
            context_type=context_type,
            user_permissions=user_permissions,
            is_admin=is_admin,
        )
        if not allowed:
            return {
                "success": False,
                "stdout": "",
                "stderr": f"Xavfsizlik: {reason}",
                "returncode": -1,
                "duration": 0.0,
                "error_message": reason,
                "sandbox_type": "permission_denied",
            }

    code = extract_python_code(code_or_text)

    # Dastlabki tekshirish
    safe, safety_err = _basic_safety_precheck(code)
    if not safe:
        return {
            "success": False,
            "stdout": "",
            "stderr": safety_err or "Xavfsizlik tekshiruvidan o'tmadi.",
            "returncode": -1,
            "duration": 0.0,
            "error_message": safety_err,
            "sandbox_type": "rejected",
        }

    # Docker tekshiruvi
    docker_ok = await _check_docker_available()

    if not docker_ok:
        # MUHIM: Docker yo'q bo'lsa host da ishlatmaymiz
        logger.warning(
            "Kod execution rad etildi: Docker sandbox mavjud emas. "
            "Host subprocess orqali xavfsizlanmagan kod ishlatilmaydi."
        )
        return {
            "success": False,
            "stdout": "",
            "stderr": (
                "⚠️ Kod execution vaqtincha mavjud emas.\n\n"
                "Sabab: Xavfsiz Docker sandbox o'rnatilmagan.\n"
                "AI tomonidan yaratilgan kod Docker izolyatsiyasisiz serverda ishlatilmaydi.\n\n"
                "Yechim: Serverga Docker o'rnating yoki kodni lokal kompyuteringizda ishga tushiring."
            ),
            "returncode": -1,
            "duration": 0.0,
            "error_message": "Docker sandbox mavjud emas. Xavfsiz execution mumkin emas.",
            "sandbox_type": "unavailable",
        }

    return await execute_python_code_docker(code, timeout_sec=timeout_sec)


def format_sandbox_result_for_telegram(res: dict) -> str:
    """Sandbox natijasini Telegram HTML formatiga o'giradi."""
    duration = res.get("duration", 0.0)
    sandbox_type = res.get("sandbox_type", "unknown")
    sandbox_badge = " 🐳 Docker" if sandbox_type == "docker" else ""

    if res.get("success"):
        stdout = res.get("stdout") or "(Chiqish xabari yo'q — muvaffaqiyatli yakunlandi)"
        return (
            f"⚡ <b>Kod Sandboxda Sinovdan O'tdi:</b> ✅ <b>MUVAFFAQIYATLI</b>{sandbox_badge} (<code>{duration}s</code>)\n"
            f"📥 <b>Stdout:</b>\n<pre><code>{html.escape(stdout)}</code></pre>"
        )
    else:
        sandbox_type_val = res.get("sandbox_type", "")
        if sandbox_type_val == "unavailable":
            stderr = res.get("stderr", "Docker sandbox mavjud emas.")
            return (
                f"⚠️ <b>Kod Execution Mavjud Emas</b>\n\n"
                f"<pre>{html.escape(stderr[:800])}</pre>"
            )
        stderr = res.get("stderr") or res.get("error_message") or "Noma'lum xato"
        return (
            f"⚡ <b>Kod Sandboxda Sinovdan O'tdi:</b> ❌ <b>XATOLIK ANIQLANDI</b>{sandbox_badge} (<code>{duration}s</code>)\n"
            f"⚠️ <b>Traceback:</b>\n<pre><code>{html.escape(stderr[:1800])}</code></pre>\n"
            f"🔄 <i>Agentlar xatolikni avtonom tarzda tuzatishga (Self-Healing) kirishmoqda...</i>"
        )

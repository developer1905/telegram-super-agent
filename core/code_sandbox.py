"""
core/code_sandbox.py — Xavfsiz Python Sandbox va Avtonom Kod Tekshiruvi (Code Execution)

Imkoniyatlar:
1. SuperAgent va Arxitektor tomonidan yozilgan Python kodlarini serverda izolyatsiya qilingan muhitda ishga tushirish.
2. Natijalarni (stdout, stderr, chiqish kodi) ushlab, Telegram chatga chiroyli taqdim etish.
3. Agar xatolik (Traceback) chiqsa, xatolikni avtonom tuzatish (Self-Healing) uchun agentlarga qaytarish.
4. Xavfli buyruqlarni (os.system, rm -rf, formatlash) xavfsizlik filtrlari orqali bloklash.
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
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# Xavfli tizim operatsiyalarini bloklash filtri
BLOCKED_PATTERNS = [
    r"\bshutil\.rmtree\b",
    r"\bos\.system\b",
    r"\bsubprocess\b",
    r"\brm\s+-rf\b",
    r"\bformat\s+[A-Z]:\b",
    r"\bdel\s+/[sfq]\b",
    r"\bos\.remove\(r?['\"]/etc",
    r"\bos\.remove\(r?['\"]C:\\Windows",
]


def extract_python_code(text: str) -> str:
    """Matn ichidagi ```python ... ``` yoki ``` ... ``` blokini ajratib oladi."""
    m = re.search(r"```(?:python|py)?\s*(.*?)\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return text.strip()


def check_code_safety(code: str) -> Tuple[bool, Optional[str]]:
    """Kodda o'ta xavfli tizim buyruqlari bor-yo'qligini tekshiradi."""
    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, code, re.IGNORECASE):
            return False, f"Xavfsizlik cheklovi: '{pattern}' kabi potensial xavfli tizim buyrug'i aniqlandi."
    return True, None


async def execute_python_code(
    code_or_text: str,
    timeout_sec: float = 12.0
) -> dict:
    """
    Python kodini alohida vaqtinchalik faylda va izolyatsiya qilingan subprocess orqali ishga tushiradi.
    
    Qaytaradi:
    {
        "success": bool,
        "stdout": str,
        "stderr": str,
        "returncode": int,
        "duration": float,
        "error_message": Optional[str]
    }
    """
    code = extract_python_code(code_or_text)
    if not code:
        return {
            "success": False,
            "stdout": "",
            "stderr": "Kod topilmadi.",
            "returncode": -1,
            "duration": 0.0,
            "error_message": "Bo'sh kod yuborildi."
        }

    is_safe, safety_err = check_code_safety(code)
    if not is_safe:
        return {
            "success": False,
            "stdout": "",
            "stderr": safety_err or "Xavfsizlik cheklovi.",
            "returncode": -1,
            "duration": 0.0,
            "error_message": safety_err
        }

    # Vaqtinchalik fayl yaratish
    tmp_dir = os.path.join(tempfile.gettempdir(), "superagent_sandbox")
    os.makedirs(tmp_dir, exist_ok=True)
    tmp_path = os.path.join(tmp_dir, f"sandbox_{int(time.time() * 1000)}.py")

    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(code)

    start_t = time.time()
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            tmp_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=tmp_dir
        )

        try:
            stdout_data, stderr_data = await asyncio.wait_for(proc.communicate(), timeout=timeout_sec)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            return {
                "success": False,
                "stdout": "",
                "stderr": f"TimeoutError: Kod belgilangan {timeout_sec} soniya ichida yakunlanmadi (cheksiz tsikl bo'lishi mumkin).",
                "returncode": -1,
                "duration": round(time.time() - start_t, 2),
                "error_message": "Vaqt me'yori tugadi."
            }

        duration = round(time.time() - start_t, 3)
        stdout_str = stdout_data.decode("utf-8", errors="replace").strip()
        stderr_str = stderr_data.decode("utf-8", errors="replace").strip()
        returncode = proc.returncode

        success = (returncode == 0)

        return {
            "success": success,
            "stdout": stdout_str[:1800],
            "stderr": stderr_str[:1800],
            "returncode": returncode,
            "duration": duration,
            "error_message": stderr_str if not success else None
        }

    except Exception as exc:
        logger.error("Sandbox ijro xatosi: %s", exc)
        return {
            "success": False,
            "stdout": "",
            "stderr": str(exc),
            "returncode": -1,
            "duration": round(time.time() - start_t, 2),
            "error_message": str(exc)
        }
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass


def format_sandbox_result_for_telegram(res: dict) -> str:
    """Sandbox natijasini Telegram HTML formatiga o'giradi."""
    duration = res.get("duration", 0.0)
    if res.get("success"):
        stdout = res.get("stdout") or "(Chiqish xabari yo'q — muvaffaqiyatli yakunlandi)"
        return (
            f"⚡ <b>Kod Sandboxda Sinovdan O'tdi:</b> ✅ <b>MUVAFFAQIYATLI</b> (<code>{duration}s</code>)\n"
            f"📥 <b>Stdout:</b>\n<pre><code>{html.escape(stdout)}</code></pre>"
        )
    else:
        stderr = res.get("stderr") or res.get("error_message") or "Noma'lum xato"
        return (
            f"⚡ <b>Kod Sandboxda Sinovdan O'tdi:</b> ❌ <b>XATOLIK ANIQLANDI</b> (<code>{duration}s</code>)\n"
            f"⚠️ <b>Traceback:</b>\n<pre><code>{html.escape(stderr)}</code></pre>\n"
            f"🔄 <i>Agentlar xatolikni avtonom tarzda tuzatishga (Self-Healing) kirishmoqda...</i>"
        )

"""
core/cleaner_agent.py — Serverni Xavfsiz Tozalash va Disk Monitoring Agenti

Imkoniyatlar:
1. Disk va RAM holatini aniq o'lchash (Total, Used, Free, Foiz).
2. Xavfsiz tozalash:
   - Python keshlarini tozalash (__pycache__, *.pyc, *.pyo).
   - Vaqtinchalik fayllarni tozalash (data/temp, /tmp/telegram_*).
   - Linux tizim keshlarini tozalash (journalctl --vacuum-time=3d, pip cache purge).
   - XAVFSIZLIK KAFOLATI: superagent.db, .env, .git, sessiyalar va doimiy xotira HECH QACHON O'CHIRILMAYDI!
3. Qancha joy bo'shatilganini aniq hisoblash va hisobot berish.
"""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import shutil
import sys
from typing import Dict, Any

logger = logging.getLogger(__name__)

# Asosiy papkalar
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT_DIR, "data")
TEMP_DIR = os.path.join(DATA_DIR, "temp")


def get_system_storage_info() -> Dict[str, Any]:
    """Disk va tizim xotirasi haqida to'liq ma'lumot olish."""
    target_path = "/" if platform.system() != "Windows" else ROOT_DIR
    try:
        usage = shutil.disk_usage(target_path)
        total_gb = usage.total / (1024 ** 3)
        used_gb = usage.used / (1024 ** 3)
        free_gb = usage.free / (1024 ** 3)
        percent = (usage.used / usage.total) * 100
    except Exception as exc:
        logger.error("disk_usage xatosi: %s", exc)
        total_gb, used_gb, free_gb, percent = 0.0, 0.0, 0.0, 0.0

    # Botning o'z hajmini hisoblash
    bot_size_mb = 0.0
    db_size_mb = 0.0
    sqlite_path = os.path.join(DATA_DIR, "superagent.db")
    if os.path.exists(sqlite_path):
        db_size_mb = os.path.getsize(sqlite_path) / (1024 ** 2)

    try:
        total_size = 0
        for dirpath, dirnames, filenames in os.walk(ROOT_DIR):
            dirnames[:] = [d for d in dirnames if d not in {".git", ".venv", "venv", "__pycache__", "node_modules", ".gemini", ".pytest_cache"}]
            for f in filenames:
                fp = os.path.join(dirpath, f)
                if os.path.exists(fp) and not os.path.islink(fp):
                    total_size += os.path.getsize(fp)
        bot_size_mb = total_size / (1024 ** 2)
    except Exception:
        pass

    return {
        "total_gb": round(total_gb, 2),
        "used_gb": round(used_gb, 2),
        "free_gb": round(free_gb, 2),
        "percent": round(percent, 1),
        "bot_size_mb": round(bot_size_mb, 2),
        "db_size_mb": round(db_size_mb, 2),
        "os": platform.system(),
    }


def format_storage_status_report() -> str:
    """Foydalanuvchi uchun chiroyli disk holati hisoboti."""
    info = get_system_storage_info()
    progress_blocks = int(info["percent"] / 10)
    progress_bar = "█" * progress_blocks + "░" * (10 - progress_blocks)

    lines = [
        "🖥 **Server Xotirasi (Disk & RAM) Holati:**\n",
        f"📊 **Disk Bandligi:** `[{progress_bar}] {info['percent']}%`",
        f"• 💾 Jami hajm: `{info['total_gb']} GB`",
        f"• 📦 Band qilingan: `{info['used_gb']} GB`",
        f"• 🟢 Bo'sh joy: `{info['free_gb']} GB`\n",
        f"🤖 **Bot Fayllari:**",
        f"• Botning to'liq hajmi: `{info['bot_size_mb']} MB`",
        f"• Asosiy baza (superagent.db): `{info['db_size_mb']} MB`",
        f"• Server OS: `{info['os']}`\n",
        "💡 _Keraksiz kesh va eski jurnallarni xavfsiz tozalash uchun /clean_server buyrug'ini bering._",
    ]
    return "\n".join(lines)


async def safe_clean_server_storage() -> Dict[str, Any]:
    """
    Serverdagi vaqtinchalik va keraksiz kesh fayllarni xavfsiz tozalash.
    HECH QACHON o'chirilmaydi:
    - data/superagent.db (Baza)
    - .env, configs, session fayllar
    - git fayllari
    """
    before_info = get_system_storage_info()
    cleaned_items: list[str] = []
    freed_bytes = 0

    loop = asyncio.get_running_loop()

    def _clean_sync() -> int:
        nonlocal freed_bytes
        bytes_removed = 0

        # 1. Python keshlarini (__pycache__, *.pyc, *.pyo) tozalash
        for root, dirs, files in os.walk(ROOT_DIR):
            if ".git" in root or "venv" in root:
                continue
            for d in list(dirs):
                if d == "__pycache__":
                    dp = os.path.join(root, d)
                    try:
                        for f in os.listdir(dp):
                            fp = os.path.join(dp, f)
                            bytes_removed += os.path.getsize(fp)
                        shutil.rmtree(dp, ignore_errors=True)
                        cleaned_items.append("__pycache__")
                    except Exception as e:
                        logger.debug("clean pycache xato: %s", e)
            for f in files:
                if f.endswith((".pyc", ".pyo")):
                    fp = os.path.join(root, f)
                    try:
                        bytes_removed += os.path.getsize(fp)
                        os.remove(fp)
                    except Exception:
                        pass

        # 2. Vaqtinchalik audio/rasm fayllarini tozalash (data/temp)
        if os.path.exists(TEMP_DIR):
            for f in os.listdir(TEMP_DIR):
                fp = os.path.join(TEMP_DIR, f)
                try:
                    if os.path.isfile(fp):
                        bytes_removed += os.path.getsize(fp)
                        os.remove(fp)
                except Exception:
                    pass

        # 3. Linux /tmp dagi eski telegram fayllarini tozalash
        if platform.system() != "Windows" and os.path.exists("/tmp"):
            for f in os.listdir("/tmp"):
                if f.startswith(("telegram_", "tmp_", "pip-", "bot_")):
                    fp = os.path.join("/tmp", f)
                    try:
                        if os.path.isfile(fp):
                            bytes_removed += os.path.getsize(fp)
                            os.remove(fp)
                        elif os.path.isdir(fp):
                            shutil.rmtree(fp, ignore_errors=True)
                    except Exception:
                        pass

        return bytes_removed

    # Sinxron fayl tozalashni alohida thread'da bajarish
    freed_bytes = await loop.run_in_executor(None, _clean_sync)

    # 4. Linux tizim buyruqlari (journalctl, pip cache)
    if platform.system() != "Windows":
        try:
            # Pip keshini tozalash
            proc = await asyncio.create_subprocess_shell(
                "pip cache purge",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
        except Exception:
            pass

        try:
            # Systemd journalctl 3 kundan eski loglarni tozalash
            proc = await asyncio.create_subprocess_shell(
                "sudo journalctl --vacuum-time=3d",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
        except Exception:
            pass

    after_info = get_system_storage_info()
    freed_mb = round(freed_bytes / (1024 ** 2), 2)

    return {
        "freed_mb": freed_mb,
        "freed_bytes": freed_bytes,
        "before_free_gb": before_info["free_gb"],
        "after_free_gb": after_info["free_gb"],
        "percent": after_info["percent"],
    }

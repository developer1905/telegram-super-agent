"""
core/project_builder.py — Avtonom Ko'p Faylli Loyiha Quruvchisi va ZIP Eksportchi (MetaGPT / ChatDev)

Imkoniyatlar:
1. SuperAgent va Arxitektor birgalikda to'liq ko'p faylli dasturiy loyiha (Frontend, Backend, DB, README, requirements) yaratadi.
2. Matndan barcha fayllar va papkalarni (### file: path/name.ext) avtomatik ajratib oladi.
3. Barcha fayllarni RAM (BytesIO) da toza .ZIP arxiviga qadoqlaydi.
4. Telegram orqali yuklab olish mumkin bo'lgan rasmiy hujjat (Document) sifatida foydalanuvchiga yuboradi.
"""

from __future__ import annotations

import asyncio
import html
import io
import logging
import os
import re
import zipfile
from typing import Dict, Optional, Tuple

from aiogram import Bot
from aiogram.types import BufferedInputFile

logger = logging.getLogger(__name__)


def parse_project_files_from_text(raw_text: str) -> Dict[str, str]:
    """
    LLM javobidan fayllar nomi va kodlarini ajratib oladi.
    Qo'llab-quvvatlanadigan formatlar:
    1. ### file: app/main.py
       ```python
       ...
       ```
    2. ### Fayl: index.html
       ```html
       ...
       ```
    3. **File: requirements.txt**
       ```
       ...
       ```
    """
    files: Dict[str, str] = {}

    pattern = re.compile(
        r"(?:###|\*\*|##)\s*(?:file|fayl|path|filepath)[:\s]+([A-Za-z0-9_./\\-]+)\s*(?:\*\*|\n)?\s*```[a-zA-Z0-9_-]*\s*\n(.*?)```",
        flags=re.DOTALL | re.IGNORECASE
    )

    matches = pattern.findall(raw_text)
    for path_raw, content in matches:
        clean_path = path_raw.strip().replace("\\", "/").lstrip("./")
        if clean_path and content:
            files[clean_path] = content.strip()

    # Agar maxsus belgilar topilmasa, lekin umumiy kod bloklari bo'lsa
    if not files:
        code_blocks = re.findall(r"```([a-zA-Z0-9_-]*)\s*\n(.*?)```", raw_text, flags=re.DOTALL)
        if code_blocks:
            for idx, (lang, content) in enumerate(code_blocks, 1):
                ext = "py"
                if lang.lower() in ("html", "htm"):
                    ext = "html"
                elif lang.lower() in ("js", "javascript"):
                    ext = "js"
                elif lang.lower() in ("css", "style"):
                    ext = "css"
                elif lang.lower() in ("json",):
                    ext = "json"
                elif lang.lower() in ("sql",):
                    ext = "sql"
                elif lang.lower() in ("txt", "requirements"):
                    ext = "txt"

                filename = f"module_{idx}.{ext}" if ext != "txt" else "requirements.txt"
                if ext == "py" and idx == 1:
                    filename = "main.py"
                files[filename] = content.strip()

    return files


def sanitize_archive_path(filepath: str) -> Optional[str]:
    """
    ZIP arxiv fayl yo'lini xavfsiz holatga keltiradi (Zip Slip va Directory Traversal himoyasi).
    
    Qoidalar:
    - NUL byte (\0) bo'lsa darhol rad etiladi (None qaytaradi)
    - Windows drive letterlari (C:, D: va hk) olib tashlanadi
    - Barcha teskari chiziqlar (\\) to'g'ri chiziqqa (/) aylantiriladi
    - Boshidagi va oxiridagi / yoki bo'shliqlar tozalanadi
    - Har qanday '..' yoki '.' segmentlari rad etiladi
    - Faqat xavfsiz nisbiy yo'l qaytariladi, aks holda None
    """
    if not filepath or "\0" in filepath:
        return None

    # Windows drive letter olib tashlash (masalan, C:\path -> \path)
    clean = re.sub(r"^[a-zA-Z]:", "", filepath)
    clean = clean.replace("\\", "/").strip().strip("/")

    parts = []
    for segment in clean.split("/"):
        segment = segment.strip()
        if not segment or segment == ".":
            continue
        if segment == "..":
            # Traversal urinishini xavfsiz bloklaymiz
            return None
        # Faqat ruxsat etilgan xavfsiz belgilar
        if re.search(r"[/\\:*?\"<>|\0]", segment):
            return None
        parts.append(segment)

    if not parts:
        return None

    return "/".join(parts)


def safe_extract_zip(zip_file: zipfile.ZipFile, target_dir: str) -> list[str]:
    """
    ZIP arxivini xavfsiz (Zip Slip dan himoyalangan holda) diskka ochish.
    Har bir a'zoning to'liq yo'li target_dir ichida ekanligini qat'iy kafolatlaydi.
    """
    abs_target_dir = os.path.abspath(target_dir)
    extracted_files = []

    for member in zip_file.infolist():
        # Zip slip tekshiruvi
        dest_path = os.path.abspath(os.path.join(abs_target_dir, member.filename))
        if not dest_path.startswith(abs_target_dir + os.sep) and dest_path != abs_target_dir:
            logger.warning("Zip Slip xavfi aniqlandi va bloklandi: %s -> %s", member.filename, dest_path)
            continue

        zip_file.extract(member, abs_target_dir)
        extracted_files.append(dest_path)

    return extracted_files


def build_zip_archive_in_memory(
    project_name: str,
    files: Dict[str, str],
    task_desc: str = ""
) -> Tuple[bytes, int]:
    """
    Fayllar lug'atini RAM da .ZIP arxiviga aylantiradi.
    Qaytaradi: (zip_bytes, fayllar_soni)
    Barcha fayl yo'llari Zip Slip xavfsizlik filtri (sanitize_archive_path) orqali tekshiriladi.
    """
    zip_buffer = io.BytesIO()

    # Agar README.md bo'lmasa, avtomatik yaratish
    if not any(k.lower() in ("readme.md", "readme.txt") for k in files):
        readme_content = (
            f"# {project_name.capitalize()} Project\n\n"
            f"Ushbu loyiha **SuperAgent & Arxitektor (@architect7_bot)** ko'p agentli sun'iy intellekt tizimi tomonidan avtonom yaratildi.\n\n"
            f"## 📋 Loyiha Tavsifi\n{task_desc or 'Avtomatlashtirilgan dasturiy loyiha.'}\n\n"
            f"## 🚀 Ishga Tushirish\n"
            f"1. Kerakli kutubxonalarni o'rnating:\n"
            f"```bash\npip install -r requirements.txt\n```\n"
            f"2. Asosiy modulni ishga tushiring:\n"
            f"```bash\npython main.py\n```\n"
        )
        files["README.md"] = readme_content

    # Agar requirements.txt bo'lmasa va Python fayllar bo'lsa
    has_py = any(k.endswith(".py") for k in files)
    has_req = any(k.lower() == "requirements.txt" for k in files)
    if has_py and not has_req:
        files["requirements.txt"] = "# Loyiha kutubxonalari\nrequests\naiohttp\npydantic\n"

    valid_file_count = 0
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        clean_proj_name = re.sub(r"[^\w\-]", "_", project_name).strip("_") or "project"
        for filepath, code in files.items():
            safe_rel_path = sanitize_archive_path(filepath)
            if not safe_rel_path:
                logger.warning("Xavfli yoki noto'g'ri fayl yo'li ZIP ga kiritilmadi: %r", filepath)
                continue
            archive_path = f"{clean_proj_name}/{safe_rel_path}"
            zf.writestr(archive_path, code)
            valid_file_count += 1

    zip_buffer.seek(0)
    return zip_buffer.getvalue(), valid_file_count


async def send_project_zip_archive(
    chat_id: int,
    bot: Bot,
    project_name: str,
    files: Dict[str, str],
    caption: str = ""
) -> bool:
    """ZIP arxivini Telegram chatiga yuborish."""
    try:
        zip_bytes, count = build_zip_archive_in_memory(project_name, files)
        filename = f"{re.sub(r'[^a-zA-Z0-9_-]', '_', project_name).lower()}_project.zip"
        doc = BufferedInputFile(zip_bytes, filename=filename)

        cap = caption or (
            f"📦 <b>Tayyor Loyiha ArxiVi:</b> <code>{filename}</code>\n\n"
            f"📁 <b>Fayllar soni:</b> {count} ta fayl (to'liq struktura va README bilan)\n"
            f"🤖 <b>Mualliflar:</b> SuperAgent & Arxitektor (@architect7_bot)\n\n"
            f"<i>Faylni yuklab olib, arxivdan chiqaring va ishlatishni boshlang!</i> 🚀"
        )
        await bot.send_document(chat_id=chat_id, document=doc, caption=cap, parse_mode="HTML")
        return True
    except Exception as exc:
        logger.error("ZIP yuborishda xatolik: %s", exc)
        return False

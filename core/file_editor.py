"""
core/file_editor.py — Hujjat Muharriri

DOCX, PDF, TXT, PY fayllarini RAMda o'qib tahlil qiladi
va AI yordamida qayta yozilgan yangi faylni BytesIO sifatida qaytaradi.
Diskka hech narsa yozilmaydi (xotira xavfsizligi).
"""

from __future__ import annotations

import io
import logging
from typing import Optional, Tuple

import docx
from docx import Document
from pypdf import PdfReader

logger = logging.getLogger(__name__)


# ─── Mazmunni O'qish ──────────────────────────────────────────

def extract_text_from_bytes(file_bytes: bytes, file_type: str) -> str:
    """
    Turli formatdagi fayllardan matn ajratib oladi.

    Args:
        file_bytes: Fayl baytlari
        file_type:  "docx" | "pdf" | "txt" | "py"

    Returns:
        Ajratilgan matn (bo'sh bo'lsa izoh)
    """
    buf = io.BytesIO(file_bytes)
    text = ""

    try:
        if file_type == "docx":
            doc = Document(buf)
            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
            text = "\n".join(paragraphs)

        elif file_type == "pdf":
            reader = PdfReader(buf)
            pages: list[str] = []
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    pages.append(page_text.strip())
            text = "\n\n".join(pages)

        elif file_type in ("txt", "py"):
            # UTF-8 birinchi, keyin latin-1 fallback
            try:
                text = file_bytes.decode("utf-8")
            except UnicodeDecodeError:
                text = file_bytes.decode("latin-1", errors="replace")

        else:
            return f"[Qo'llab-quvvatlanmaydigan fayl turi: {file_type}]"

    except Exception as exc:
        logger.error("Fayl o'qishda xato (%s): %s", file_type, exc, exc_info=True)
        return f"[Fayl o'qishda xato: {exc}]"

    return text.strip() if text.strip() else "[Fayl bo'sh yoki o'qib bo'lmadi]"


def build_analysis_prompt(text: str, filename: str, file_type: str) -> str:
    """Fayl tahlili uchun AI promptini tuzadi."""
    max_chars = 6000  # Token limitga mos
    truncated = text[:max_chars]
    suffix = "\n\n[... matn qisqartirildi ...]" if len(text) > max_chars else ""

    return (
        f"Quyidagi `{filename}` ({file_type.upper()}) faylini tahlil qil:\n\n"
        f"```\n{truncated}{suffix}\n```\n\n"
        "Quyidagilarni qil:\n"
        "1. Fayl mazmunini qisqacha izohlá\n"
        "2. Asosiy fikrlar yoki kodning maqsadini ayt\n"
        "3. Yaxshilash bo'yicha tavsiyalar ber\n"
        "4. Agar so'ralsa, to'liq qayta yozishga tayyor bo'l"
    )


def build_rewrite_prompt(text: str, instruction: str, file_type: str) -> str:
    """Qayta yozish uchun AI promptini tuzadi."""
    max_chars = 5000
    truncated = text[:max_chars]

    return (
        f"Quyidagi {file_type.upper()} fayl mazmunini ko'rsatma asosida qayta yoz:\n\n"
        f"**Ko'rsatma:** {instruction}\n\n"
        f"**Asl mazmun:**\n```\n{truncated}\n```\n\n"
        "Faqat qayta yozilgan mazmunni qaytار (tushuntirish kerak emas)."
    )


# ─── Yangi Fayl Yaratish ─────────────────────────────────────

def create_docx_bytes(content: str) -> bytes:
    """
    Matndan yangi DOCX fayl yaratadi (xotiradan).

    Args:
        content: DOCX ichiga yoziladigan matn

    Returns:
        DOCX fayl baytlari
    """
    doc = Document()
    doc.add_heading("Super-Agent tomonidan qayta yozildi", level=1)

    # Paragraflarni saqlash
    for paragraph in content.split("\n"):
        if paragraph.strip():
            doc.add_paragraph(paragraph)
        else:
            doc.add_paragraph("")  # Bo'sh qator

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.read()


def create_txt_bytes(content: str) -> bytes:
    """Matndan TXT fayl baytlarini yaratadi."""
    return content.encode("utf-8")


def create_py_bytes(content: str) -> bytes:
    """Python kodidan .py fayl baytlarini yaratadi."""
    header = "# -*- coding: utf-8 -*-\n# Super-Agent tomonidan qayta yozilgan kod\n\n"
    return (header + content).encode("utf-8")


def build_output_bytes(content: str, original_type: str) -> Tuple[bytes, str, str]:
    """
    Qayta yozilgan mazmundan natija faylini yaratadi.

    Returns:
        (fayl_baytlari, fayl_nomi, mime_turi)
    """
    if original_type == "docx":
        return (
            create_docx_bytes(content),
            "rewritten.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    elif original_type == "py":
        return create_py_bytes(content), "rewritten.py", "text/plain"
    else:
        # txt va boshqalar
        return create_txt_bytes(content), "rewritten.txt", "text/plain"

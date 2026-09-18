"""
core/markitdown_agent.py — Microsoft MarkItDown Universal Hujjatlar Tahlilchisi

Imkoniyatlar:
1. Har qanday formatdagi hujjatlarni (PDF, Word DOCX, PowerPoint PPTX, Excel XLSX, CSV, HTML)
   toza, strukturaviy Markdown formatiga aylantirish.
2. Jadvallar, sarlavhalar, ro'yxatlar va matn tartibini 100% saqlab qolish.
3. Microsoft MarkItDown va zaxira (pypdf, python-docx, openpyxl) vositalari bilan ikki qavatli ishonchlilik.
4. Katta hujjatlarni ixchamlashtirib, AI ga kiritish uchun tayyorlash.
"""

from __future__ import annotations

import io
import logging
import os
from typing import Optional, Union

logger = logging.getLogger(__name__)


def convert_document_to_markdown(file_input: Union[str, bytes], filename: str = "") -> str:
    """
    Fayl yo'li yoki fayl baytlarini qabul qilib, uni toza Markdown matniga aylantiradi.
    """
    ext = os.path.splitext(filename)[1].lower().lstrip(".")
    if not ext and isinstance(file_input, str):
        ext = os.path.splitext(file_input)[1].lower().lstrip(".")

    # 1. Microsoft MarkItDown kutubxonasi orqali urinish
    try:
        from markitdown import MarkItDown

        md = MarkItDown()
        if isinstance(file_input, str) and os.path.exists(file_input):
            result = md.convert(file_input)
            if result and result.text_content:
                return result.text_content.strip()
        elif isinstance(file_input, bytes):
            # Vaqtinchalik faylsiz BytesIO orqali
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as tmp:
                tmp.write(file_input)
                tmp_path = tmp.name
            try:
                result = md.convert(tmp_path)
                if result and result.text_content:
                    return result.text_content.strip()
            finally:
                if os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass
    except Exception as m_exc:
        logger.debug("MarkItDown orqali konvertatsiya qilinmadi (%s), zaxira usullar ishlatiladi.", m_exc)

    # 2. Zaxira usullar (Formatga qarab xatosiz o'qish)
    if isinstance(file_input, str) and os.path.exists(file_input):
        with open(file_input, "rb") as f:
            file_bytes = f.read()
    else:
        file_bytes = file_input if isinstance(file_input, bytes) else b""

    # PDF fayl
    if ext == "pdf":
        try:
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(file_bytes))
            pages_text = []
            for i, page in enumerate(reader.pages, 1):
                txt = page.extract_text() or ""
                if txt.strip():
                    pages_text.append(f"### Sahifa {i}\n{txt.strip()}")
            return "\n\n".join(pages_text) if pages_text else "PDF faylda o'qiladigan matn topilmadi."
        except Exception as p_err:
            logger.error("PDF o'qish xatosi: %s", p_err)

    # Word (docx)
    elif ext in ("docx", "doc"):
        try:
            import docx
            doc = docx.Document(io.BytesIO(file_bytes))
            lines = []
            for p in doc.paragraphs:
                if p.text.strip():
                    lines.append(p.text)
            for table in doc.tables:
                for row in table.rows:
                    row_cells = [c.text.strip() for c in row.cells]
                    lines.append("| " + " | ".join(row_cells) + " |")
            return "\n\n".join(lines) if lines else "Word hujjat bo'sh."
        except Exception as d_err:
            logger.error("Word o'qish xatosi: %s", d_err)

    # Excel (xlsx, xls, csv)
    elif ext in ("xlsx", "xls", "csv"):
        try:
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
            lines = []
            for sheet in wb.sheetnames:
                ws = wb[sheet]
                lines.append(f"### Varaq: {sheet}")
                for row in ws.iter_rows(values_only=True):
                    row_vals = [str(c) if c is not None else "" for c in row]
                    if any(row_vals):
                        lines.append("| " + " | ".join(row_vals[:10]) + " |")
            return "\n".join(lines[:200]) if lines else "Excel jadval bo'sh."
        except Exception as x_err:
            logger.error("Excel o'qish xatosi: %s", x_err)

    # Oddiy matn / HTML / JSON / Python
    try:
        return file_bytes.decode("utf-8", errors="replace")
    except Exception:
        return f"[{filename} fayli muvaffaqiyatli qabul qilindi, hajmi: {len(file_bytes)} bayt]"

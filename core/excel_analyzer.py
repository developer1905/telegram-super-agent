"""
core/excel_analyzer.py — Excel va CSV Fayllarni Aqlli Tahlil Qilish (Data Analytics)

Excel (.xlsx, .xls) va CSV jadvallarini to'g'ridan-to'g'ri xotirada (RAM) o'qiydi,
ustunlar, qatorlar, moliyaviy sonlar (yig'indi, o'rtacha, min, max) bo'yicha
boshlang'ich hisob-kitoblarni amalga oshiradi va Gemini / OpenRouter orqali
chuqur biznes va moliyaviy tahlil hamda xulosalarni taqdim etadi.
"""

from __future__ import annotations

import csv
import io
import logging
from typing import Any

import openpyxl

from core.database import db

logger = logging.getLogger(__name__)


def parse_csv_in_memory(file_bytes: bytes) -> tuple[list[str], list[list[Any]]]:
    """CSV baytlarini xotirada o'qib sarlavhalar va qatorlarni qaytarish."""
    # Matnni dekodlash (utf-8 yoki windows-1251)
    text = ""
    for enc in ("utf-8", "utf-8-sig", "cp1251", "latin-1"):
        try:
            text = file_bytes.decode(enc)
            break
        except UnicodeDecodeError:
            continue

    if not text:
        text = file_bytes.decode("utf-8", errors="replace")

    reader = csv.reader(io.StringIO(text))
    rows = [r for r in reader if any(cell.strip() for cell in r)]
    if not rows:
        return [], []
    headers = rows[0]
    data_rows = rows[1:]
    return headers, data_rows


def parse_xlsx_in_memory(file_bytes: bytes) -> tuple[list[str], list[str], list[list[Any]]]:
    """Excel (.xlsx) faylini xotirada o'qish."""
    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
    sheet_names = wb.sheetnames
    active_sheet = wb.active or wb[sheet_names[0]]

    rows: list[list[Any]] = []
    for row in active_sheet.iter_rows(values_only=True):
        if any(cell is not None and str(cell).strip() != "" for cell in row):
            rows.append(list(row))

    if not rows:
        return sheet_names, [], []

    headers = [str(h) if h is not None else f"Col_{i+1}" for i, h in enumerate(rows[0])]
    data_rows = rows[1:]
    return sheet_names, headers, data_rows


async def analyze_spreadsheet(
    file_bytes: bytes,
    file_name: str,
    ai_manager: Any,
    user_prompt: str = "",
) -> str:
    """
    Excel yoki CSV faylini tahlil qilish va AI orqali professional xulosa chiqarish.
    """
    try:
        lower_name = file_name.lower()
        sheet_info = ""

        if lower_name.endswith(".csv"):
            headers, data_rows = parse_csv_in_memory(file_bytes)
        else:
            sheet_names, headers, data_rows = parse_xlsx_in_memory(file_bytes)
            sheet_info = f"Varaqlar (Sheets): {', '.join(sheet_names)}\n"

        if not headers or not data_rows:
            return "❌ Jadval bo'sh yoki ma'lumotlarni o'qib bo'lmadi."

        total_rows = len(data_rows)
        total_cols = len(headers)

        # Sonli ustunlarni aniqlash va dastlabki hisob-kitoblar
        numeric_stats: dict[str, dict[str, float]] = {}
        for col_idx, col_name in enumerate(headers):
            values: list[float] = []
            for row in data_rows:
                if col_idx < len(row):
                    cell = row[col_idx]
                    if isinstance(cell, (int, float)):
                        values.append(float(cell))
                    elif isinstance(cell, str):
                        clean_str = cell.replace(" ", "").replace(",", ".").replace("$", "").replace("so'm", "").strip()
                        try:
                            values.append(float(clean_str))
                        except ValueError:
                            pass

            if len(values) > (total_rows * 0.4):  # Agar kamida 40% son bo'lsa
                numeric_stats[col_name] = {
                    "count": len(values),
                    "sum": round(sum(values), 2),
                    "avg": round(sum(values) / len(values), 2),
                    "min": round(min(values), 2),
                    "max": round(max(values), 2),
                }

        # Dastlabki 10 ta qator namunasi
        sample_rows = data_rows[:10]
        sample_text_lines = [" | ".join(headers)]
        sample_text_lines.append("-" * 40)
        for r in sample_rows:
            sample_text_lines.append(" | ".join(str(c) if c is not None else "" for c in r[:total_cols]))
        sample_table = "\n".join(sample_text_lines)

        # Statistik ma'lumotlar matni
        stats_text_lines = []
        for col, s in numeric_stats.items():
            stats_text_lines.append(
                f"• {col}: Jami: {s['sum']:,} | O'rtacha: {s['avg']:,} | Min: {s['min']:,} | Max: {s['max']:,}"
            )
        stats_summary = "\n".join(stats_text_lines) if stats_text_lines else "Sonli ustunlar aniqlanmadi."

        # AI ga tahlil uchun yuborish
        prompt = (
            f"Siz bosh moliya tahlilchisi va Data Analyst sun'iy intellektisiz.\n"
            f"Foydalanuvchi quyidagi faylni yubordi: {file_name}\n"
            f"{sheet_info}"
            f"Umumiy qatorlar soni: {total_rows} ta\n"
            f"Ustunlar soni: {total_cols} ta\n"
            f"Ustunlar ro'yxati: {', '.join(headers)}\n\n"
            f"📊 Dastlabki hisoblangan ko'rsatkichlar:\n{stats_summary}\n\n"
            f"📋 Ma'lumotlardan namuna (boshlang'ich qatorlar):\n"
            f"```\n{sample_table[:1800]}\n```\n\n"
            f"Foydalanuvchi so'rovi: {user_prompt or 'Ushbu jadval bo\'yicha to\'liq tahlil va xulosa bering'}\n\n"
            f"Vazifalar:\n"
            f"1. 📌 **Asosiy Ko'rsatkichlar:** Jadvalning asosiy maqsadi, moliyaviy yoki miqdoriy hajmi.\n"
            f"2. 📈 **Tendensiyalar va Muhim Nuqtalar:** Eng yuqori/past ko'rsatkichlar, kutilmagan farqlar yoki trendlar.\n"
            f"3. 💡 **Tavsiyalar va Xulosa:** Biznes yoki boshqaruv qarorlari uchun 2-3 ta aniq amaliy tavsiya.\n"
            f"O'zbek tilida, chiroyli Markdown formatida va tushunarli raqamlar bilan yozing."
        )

        analysis = await ai_manager.generate(prompt, save_history=False)
        await db.log_event("data_analysis", f"Analyzed {file_name} ({total_rows} rows)")

        return (
            f"📊 **Ma'lumotlar Tahlili: {file_name}**\n"
            f"Qatorlar: `{total_rows}` | Ustunlar: `{total_cols}`\n\n"
            f"{analysis}"
        )

    except Exception as exc:
        logger.error("analyze_spreadsheet xatosi (%s): %s", file_name, exc)
        return f"❌ Faylni tahlil qilishda xatolik yuz berdi: {exc}"

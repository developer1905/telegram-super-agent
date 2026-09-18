"""
core/tts_agent.py — Microsoft Edge AI Ovoz Sintezi (Text-to-Speech)

Imkoniyatlar:
1. Matnni inson ovozidan farq qilmaydigan tabiiy ovozga aylantirish (100% Bepul, API kalitsiz)
2. O'zbekcha (Madina, Sardor), Ruscha (Svetlana, Dmitry) va Inglizcha (Jenny, Guy) ovozlar
3. Matn tilini avtomatik aniqlab, mos ovozni tanlash
4. Markdown va keraksiz belgilarni tozalab, silliq o'qish
5. Xotirada (RAM) audio baytlarini tayyorlash va Telegramga ovozli xabar (Voice Note) yuborish
"""

from __future__ import annotations

import asyncio
import io
import logging
import re
from typing import Optional

from config import DEFAULT_VOICE, VOICE_OPTIONS

logger = logging.getLogger(__name__)


def clean_text_for_speech(text: str) -> str:
    """Markdown formatlash belgilari, havolalar va kod bloklarini nutq uchun tozalaydi."""
    t = text
    # Kod bloklarini tozalash
    t = re.sub(r"```[\s\S]*?```", "kod namunasi", t)
    t = re.sub(r"`.*?`", "", t)
    # Havolalarni tozalash [matn](url) -> matn
    t = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", t)
    t = re.sub(r"https?://\S+", "", t)
    # Markdown belgilarini olib tashlash
    t = re.sub(r"[*_~#>`\-|]", "", t)
    # Emojilarni tozalash (ba'zi TTS dvigatellari emojilarni g'alati o'qiydi)
    t = re.sub(r"[\U00010000-\U0010ffff]", "", t)
    # Ortiqcha bo'shliqlarni qisqartirish
    t = re.sub(r"\s+", " ", t).strip()
    return t


def auto_detect_voice(text: str, preferred_voice: Optional[str] = None) -> str:
    """Matn tiliga qarab eng mos ovozni tanlaydi."""
    if preferred_voice and preferred_voice in VOICE_OPTIONS.values():
        return preferred_voice

    sample = text[:300].lower()

    # O'zbek tili belgilari: o', g', sh, ch, menga, sizga, uchun, yaxshi, bo'ladi
    uzbek_markers = ["o'", "g'", " o‘", " g‘", "menga", "sizga", "uchun", "yaxshi", "bo'ladi", "qanday", "nima", "kerak", "rahmat"]
    if any(m in sample for m in uzbek_markers):
        return DEFAULT_VOICE  # uz-UZ-MadinaNeural

    # Kirill alifbosi (Ruscha)
    cyrillic_chars = len(re.findall(r"[\u0400-\u04FF]", sample))
    total_letters = len(re.findall(r"\w", sample)) or 1
    if cyrillic_chars / total_letters > 0.4:
        return "ru-RU-SvetlanaNeural"

    # Inglizcha
    return "en-US-JennyNeural"


async def generate_speech_audio(
    text: str,
    voice: Optional[str] = None,
    rate: str = "+0%",
    pitch: str = "+0Hz",
) -> Optional[bytes]:
    """
    Matnni edge-tts orqali audio baytlariga aylantiradi.
    
    Qaytaradi:
        bytes (MP3 formatida audio) yoki None
    """
    cleaned = clean_text_for_speech(text)
    if not cleaned:
        return None

    # Agar matn juda uzun bo'lsa, nutq uchun birinchi 1200 belgisini olamiz (taxminan 1.5 daqiqa audio)
    if len(cleaned) > 1200:
        cleaned = cleaned[:1200].rsplit(".", 1)[0] + "."

    selected_voice = voice or auto_detect_voice(cleaned, voice)

    try:
        import edge_tts

        communicate = edge_tts.Communicate(
            text=cleaned,
            voice=selected_voice,
            rate=rate,
            pitch=pitch,
        )

        audio_buffer = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_buffer.write(chunk["data"])

        audio_bytes = audio_buffer.getvalue()
        if len(audio_bytes) > 500:
            logger.info("TTS muvaffaqiyatli generatsiya qilindi (%s, %d bayt)", selected_voice, len(audio_bytes))
            return audio_bytes
        else:
            logger.warning("TTS audio baytlari juda kichik")

    except ImportError:
        logger.warning("edge-tts kutubxonasi o'rnatilmagan. pip install edge-tts bajaring.")
    except Exception as exc:
        logger.error("TTS generatsiyasida xatolik: %s", exc)

    return None

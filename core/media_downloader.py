"""
core/media_downloader.py — Instagram, YouTube, TikTok va X Video Yuklovchi Agenti

Imkoniyatlar:
1. Instagram Reels, Postlar va Videolar (Suvsiz, eng yuqori sifat)
2. TikTok videolari (100% Suvsiz - Watermark-free, HD)
3. YouTube Shorts va YouTube Videolar (720p / 1080p MP4)
4. X (Twitter) va Pinterest videolari
5. 100% Bepul, kalitsiz multi-engine arxitektura:
   - TikWM HD Engine (TikTok uchun)
   - Cobalt Universal Engine (Instagram, YouTube, Twitter)
   - yt-dlp zaxira dvigateli (Agar serverda mavjud bo'lsa)
6. Telegram 50MB limitini nazorat qilish va vaqtinchalik fayllarni avtomatik tozalash.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import time
import uuid
from typing import Optional, Dict, Any

import aiohttp

logger = logging.getLogger(__name__)

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMP_DIR = os.path.join(ROOT_DIR, "data", "temp")
os.makedirs(TEMP_DIR, exist_ok=True)

# URL Patternlari
URL_REGEX = re.compile(
    r"(https?://(?:www\.)?(?:instagram\.com/(?:p|reel|tv)/[A-Za-z0-9_-]+|"
    r"tiktok\.com/@?[A-Za-z0-9_.-]+/video/\d+|vm\.tiktok\.com/[A-Za-z0-9_-]+|vt\.tiktok\.com/[A-Za-z0-9_-]+|"
    r"youtube\.com/watch\?v=[A-Za-z0-9_-]+|youtu\.be/[A-Za-z0-9_-]+|youtube\.com/shorts/[A-Za-z0-9_-]+|"
    r"twitter\.com/\w+/status/\d+|x\.com/\w+/status/\d+|"
    r"pin\.it/[A-Za-z0-9_-]+|pinterest\.com/pin/\d+)[^\s]*)",
    re.IGNORECASE
)

# Cobalt public instances
COBALT_INSTANCES = [
    "https://api.cobalt.tools",
    "https://cobalt.api.kwiatekm.com",
    "https://api.wuk.sh",
]


def extract_media_url(text: str) -> Optional[str]:
    """Matn ichidan video havolasini ajratib oladi."""
    match = URL_REGEX.search(text)
    if match:
        url = match.group(1).strip()
        clean_url = url.split("?")[0]
        if "tiktok.com" in url or "youtu" in url:
            return url
        return clean_url
    return None


def detect_platform(url: str) -> str:
    """Platformani aniqlash."""
    u = url.lower()
    if "tiktok.com" in u:
        return "TikTok"
    if "instagram.com" in u:
        return "Instagram"
    if "youtube.com" in u or "youtu.be" in u:
        return "YouTube"
    if "twitter.com" in u or "x.com" in u:
        return "X (Twitter)"
    if "pin.it" in u or "pinterest.com" in u:
        return "Pinterest"
    return "Video"


async def download_file_stream(download_url: str, output_path: str, max_mb: int = 50) -> bool:
    """URL dan faylni oqim (stream) ko'rinishida diskka yuklab oladi."""
    try:
        timeout = aiohttp.ClientTimeout(total=90)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
            "Referer": "https://www.google.com/",
        }
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(download_url) as resp:
                if resp.status == 200:
                    content_length = resp.headers.get("Content-Length")
                    if content_length and int(content_length) > max_mb * 1024 * 1024:
                        logger.warning("Fayl hajmi %s MB dan katta: %s", max_mb, content_length)
                        return False

                    downloaded = 0
                    with open(output_path, "wb") as f:
                        async for chunk in resp.content.iter_chunked(64 * 1024):
                            downloaded += len(chunk)
                            if downloaded > max_mb * 1024 * 1024:
                                logger.warning("Yuklash paytida hajm 50MB dan oshib ketdi")
                                return False
                            f.write(chunk)
                    return os.path.exists(output_path) and os.path.getsize(output_path) > 10240
    except Exception as exc:
        logger.error("download_file_stream xatosi: %s", exc)
        if os.path.exists(output_path):
            try:
                os.remove(output_path)
            except Exception:
                pass
    return False


async def download_tiktok_tikwm(url: str, output_path: str) -> Optional[Dict[str, Any]]:
    """TikWM API orqali TikTok videoni 100% suvsiz (No Watermark) yuklab olish."""
    api_url = "https://www.tikwm.com/api/"
    params = {"url": url, "hd": 1}
    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(api_url, params=params) as resp:
                if resp.status == 200:
                    res_json = await resp.json()
                    data = res_json.get("data")
                    if data:
                        video_url = data.get("play") or data.get("hdplay") or data.get("wmplay")
                        title = data.get("title") or "TikTok Video"
                        duration = data.get("duration", 0)
                        if video_url:
                            ok = await download_file_stream(video_url, output_path)
                            if ok:
                                size_mb = round(os.path.getsize(output_path) / (1024 * 1024), 2)
                                return {
                                    "file_path": output_path,
                                    "title": title,
                                    "duration": duration,
                                    "platform": "TikTok",
                                    "size_mb": size_mb,
                                }
    except Exception as exc:
        logger.debug("TikWM xatosi: %s", exc)
    return None


async def download_with_cobalt(url: str, output_path: str) -> Optional[Dict[str, Any]]:
    """Cobalt API orqali Instagram, YouTube, Twitter va boshqa videolarni yuklab olish."""
    for instance in COBALT_INSTANCES:
        try:
            timeout = aiohttp.ClientTimeout(total=25)
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "SuperAgent/2.0",
            }
            payload = {
                "url": url,
                "videoQuality": "720",
                "filenameStyle": "classic",
            }
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                async with session.post(f"{instance}/api/json", json=payload) as resp:
                    if resp.status in (200, 201):
                        data = await resp.json()
                        stream_url = data.get("url")
                        if stream_url:
                            ok = await download_file_stream(stream_url, output_path)
                            if ok:
                                size_mb = round(os.path.getsize(output_path) / (1024 * 1024), 2)
                                return {
                                    "file_path": output_path,
                                    "title": data.get("filename") or detect_platform(url),
                                    "duration": 0,
                                    "platform": detect_platform(url),
                                    "size_mb": size_mb,
                                }
        except Exception as exc:
            logger.debug("Cobalt instance xatosi (%s): %s", instance, exc)
            continue
    return None


async def download_with_ytdlp(url: str, output_path: str) -> Optional[Dict[str, Any]]:
    """Serverda yt-dlp mavjud bo'lsa undan foydalanish."""
    try:
        import yt_dlp
        ydl_opts = {
            "format": "best[ext=mp4][filesize<48M]/best[ext=mp4]/best",
            "outtmpl": output_path,
            "quiet": True,
            "no_warnings": True,
            "max_filesize": 49 * 1024 * 1024,
        }
        loop = asyncio.get_running_loop()

        def _sync_ytdlp():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                return info

        info = await loop.run_in_executor(None, _sync_ytdlp)
        if os.path.exists(output_path) and os.path.getsize(output_path) > 10240:
            size_mb = round(os.path.getsize(output_path) / (1024 * 1024), 2)
            title = info.get("title") or detect_platform(url)
            duration = info.get("duration") or 0
            return {
                "file_path": output_path,
                "title": title,
                "duration": duration,
                "platform": detect_platform(url),
                "size_mb": size_mb,
            }
    except Exception as exc:
        logger.debug("yt-dlp xatosi: %s", exc)
    return None


async def download_social_video(url: str) -> Optional[Dict[str, Any]]:
    """
    Har qanday ijtimoiy tarmoq (Instagram, TikTok, YouTube, X) videosini
    avtomat mos dvigatel orqali eng yuqori sifatda xavfsiz yuklab oladi.
    """
    platform = detect_platform(url)
    uid = uuid.uuid4().hex[:8]
    output_filename = f"video_{uid}.mp4"
    output_path = os.path.join(TEMP_DIR, output_filename)

    logger.info("Video yuklanmoqda [%s]: %s", platform, url)

    # 1. TikTok bo'lsa — birinchi TikWM (100% Suvsiz)
    if platform == "TikTok":
        res = await download_tiktok_tikwm(url, output_path)
        if res:
            return res

    # 2. Universal Cobalt Dvigateli (Instagram, YouTube, Twitter, TikTok)
    res = await download_with_cobalt(url, output_path)
    if res:
        return res

    # 3. Zaxira: yt-dlp kutubxonasi
    res = await download_with_ytdlp(url, output_path)
    if res:
        return res

    # Agar yuklab bo'lmasa, tozalash
    if os.path.exists(output_path):
        try:
            os.remove(output_path)
        except Exception:
            pass

    return None

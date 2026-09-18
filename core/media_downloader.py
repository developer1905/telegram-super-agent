"""
core/media_downloader.py — Instagram, YouTube, TikTok va X Video Yuklovchi Agenti

100% Barqaror va Tezkor Arxitektura:
1. Instagram Reels, Postlar va Videolar:
   - Instaloader dvigateli (bevosita HD video oqimi)
   - yt-dlp zaxira dvigateli
2. TikTok videolari (Suvsiz - Watermark-free, HD):
   - TikWM API Engine
   - yt-dlp zaxira dvigateli
3. YouTube Shorts va YouTube Videolar (720p / 1080p MP4):
   - yt-dlp maxsus Android/iOS mobile player client emulyatsiyasi bilan
4. X (Twitter), Pinterest va boshqa platformalar:
   - yt-dlp universal dvigateli
5. Telegram 50MB limiti va vaqtinchalik fayllar xavfsizligi.
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

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
}


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


async def download_file_stream(download_url: str, output_path: str, max_mb: int = 50, referer: Optional[str] = None) -> bool:
    """URL dan faylni oqim (stream) ko'rinishida diskka yuklab oladi."""
    try:
        timeout = aiohttp.ClientTimeout(total=120)
        headers = dict(DEFAULT_HEADERS)
        if referer:
            headers["Referer"] = referer

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
                                logger.warning("Yuklash paytida hajm %s MB dan oshib ketdi", max_mb)
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


async def download_instagram_reel(url: str, output_path: str) -> Optional[Dict[str, Any]]:
    """
    Instagram Reels va Postlarni Instaloader orqali yuklab olish.
    """
    shortcode_match = re.search(r"/(?:p|reel|tv)/([A-Za-z0-9_-]+)", url)
    if not shortcode_match:
        return None

    shortcode = shortcode_match.group(1)
    loop = asyncio.get_running_loop()

    def _sync_extract() -> tuple[Optional[str], str, int]:
        try:
            import instaloader
            L = instaloader.Instaloader(
                download_pictures=False,
                download_videos=False,
                download_video_thumbnails=False,
                download_geotags=False,
                download_comments=False,
                save_metadata=False,
                compress_json=False,
                quiet=True,
            )
            post = instaloader.Post.from_shortcode(L.context, shortcode)
            if post.is_video and post.video_url:
                title = (post.caption or "Instagram Reel").split("\n")[0][:100]
                duration = getattr(post, "video_duration", 0) or 0
                return post.video_url, title, int(duration)
        except Exception as err:
            logger.debug("Instaloader extract xatosi (%s): %s", shortcode, err)
        return None, "Instagram Reel", 0

    video_url, title, duration = await loop.run_in_executor(None, _sync_extract)
    if video_url:
        ok = await download_file_stream(video_url, output_path, referer="https://www.instagram.com/")
        if ok and os.path.exists(output_path) and os.path.getsize(output_path) > 10240:
            size_mb = round(os.path.getsize(output_path) / (1024 * 1024), 2)
            return {
                "file_path": output_path,
                "title": title or "Instagram Reel",
                "duration": duration,
                "platform": "Instagram",
                "size_mb": size_mb,
            }

    return None


async def download_tiktok_tikwm(url: str, output_path: str) -> Optional[Dict[str, Any]]:
    """
    TikWM API orqali TikTok videoni 100% suvsiz (No Watermark, HD) yuklab olish.
    """
    api_url = "https://www.tikwm.com/api/"
    params = {"url": url, "hd": 1}
    try:
        timeout = aiohttp.ClientTimeout(total=25)
        headers = dict(DEFAULT_HEADERS)
        headers["Referer"] = "https://www.tikwm.com/"

        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            # Agar vt.tiktok.com bo'lsa, avval to'liq URL ni ochish
            if "vt.tiktok.com" in url or "vm.tiktok.com" in url:
                try:
                    async with session.get(url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=10)) as red_resp:
                        if red_resp.status == 200:
                            params["url"] = str(red_resp.url)
                except Exception:
                    pass

            async with session.get(api_url, params=params) as resp:
                if resp.status == 200:
                    res_json = await resp.json()
                    data = res_json.get("data")
                    if data and isinstance(data, dict):
                        video_url = data.get("play") or data.get("hdplay") or data.get("wmplay")
                        title = data.get("title") or "TikTok Video"
                        duration = data.get("duration", 0)
                        if video_url:
                            if video_url.startswith("/"):
                                video_url = f"https://www.tikwm.com{video_url}"
                            ok = await download_file_stream(video_url, output_path, referer="https://www.tikwm.com/")
                            if ok and os.path.exists(output_path) and os.path.getsize(output_path) > 10240:
                                size_mb = round(os.path.getsize(output_path) / (1024 * 1024), 2)
                                return {
                                    "file_path": output_path,
                                    "title": title[:100],
                                    "duration": duration,
                                    "platform": "TikTok",
                                    "size_mb": size_mb,
                                }
    except Exception as exc:
        logger.debug("TikWM xatosi: %s", exc)
    return None


async def download_with_ytdlp(url: str, output_path: str) -> Optional[Dict[str, Any]]:
    """
    yt-dlp orqali YouTube, TikTok, Instagram, X va boshqa videolarni yuklab olish.
    """
    try:
        import yt_dlp

        ydl_opts = {
            "format": "best[ext=mp4][filesize<48M]/best[filesize<48M]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best",
            "outtmpl": output_path,
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "socket_timeout": 30,
            "nocheckcertificate": True,
            "max_filesize": 49 * 1024 * 1024,
            "extractor_args": {
                "youtube": {
                    "player_client": ["android", "ios", "web"]
                }
            },
            "http_headers": dict(DEFAULT_HEADERS),
        }
        loop = asyncio.get_running_loop()

        def _sync_ytdlp():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                return info

        info = await loop.run_in_executor(None, _sync_ytdlp)
        if os.path.exists(output_path) and os.path.getsize(output_path) > 10240:
            size_mb = round(os.path.getsize(output_path) / (1024 * 1024), 2)
            title = (info.get("title") or detect_platform(url))[:100]
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
    avtomat mos dvigatel orqali eng yuqori sifatda (suvsiz) yuklab oladi.
    """
    platform = detect_platform(url)
    uid = uuid.uuid4().hex[:8]
    output_filename = f"video_{uid}.mp4"
    output_path = os.path.join(TEMP_DIR, output_filename)

    logger.info("Video yuklanmoqda [%s]: %s", platform, url)

    # 1. Instagram: Birinchi Instaloader, keyin yt-dlp
    if platform == "Instagram":
        res = await download_instagram_reel(url, output_path)
        if res:
            return res
        res = await download_with_ytdlp(url, output_path)
        if res:
            return res

    # 2. TikTok: Birinchi TikWM (suvsiz), keyin yt-dlp
    elif platform == "TikTok":
        res = await download_tiktok_tikwm(url, output_path)
        if res:
            return res
        res = await download_with_ytdlp(url, output_path)
        if res:
            return res

    # 3. YouTube, X (Twitter), Pinterest yoki boshqalar: yt-dlp
    else:
        res = await download_with_ytdlp(url, output_path)
        if res:
            return res

    # Oxirgi chora: agar yuqoridagilar o'xshamagan bo'lsa
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

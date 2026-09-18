"""
core/media_downloader.py — Instagram, YouTube, TikTok va X Video & MP3 Yuklovchi Agenti

Imkoniyatlar:
1. Instagram Reels, Postlar va Videolar (/reels/, /reel/, /p/, /tv/, /share/):
   - Instaloader bevosita HD video oqimi
   - yt-dlp dvigateli (imageio-ffmpeg integratsiyasi bilan)
   - Ochiq API va meta-og zaxira dvigateli
2. TikTok videolari (Suvsiz - Watermark-free, HD):
   - TikWM API orqali HD video va asl MP3 musiqasini yuklash
3. YouTube Shorts va Videolar:
   - yt-dlp orqali MP4 video va M4A/MP3 audio oqimi
4. Videodagi qo'shiqni aniqlash va MP3 ajratib olish (Extract Audio):
   - FFMPEG orqali 0.5 soniyada 192kbps toza MP3 audio chiqarish
   - Qo'shiq nomi, ijrochisi va musiqiy metama'lumotlarini aniqlash
5. Web App va Telegram bot uchun video/audio oqimi.
"""

from __future__ import annotations

import asyncio
import html
import logging
import os
import re
import shutil
import subprocess
import time
import uuid
from typing import Optional, Dict, Any, Tuple

import aiohttp

logger = logging.getLogger(__name__)

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMP_DIR = os.path.join(ROOT_DIR, "data", "temp")
os.makedirs(TEMP_DIR, exist_ok=True)

# URL Patternlari (barcha zamonaviy formatlar)
URL_REGEX = re.compile(
    r"(https?://(?:www\.|m\.)?(?:"
    r"instagram\.com/(?:[a-zA-Z0-9_.]+/)?(?:p|reel|reels|tv|share)/[A-Za-z0-9_-]+|"
    r"tiktok\.com/(?:@[a-zA-Z0-9_.-]+/video/\d+|vm/[A-Za-z0-9_-]+|vt/[A-Za-z0-9_-]+|t/[A-Za-z0-9_-]+|[A-Za-z0-9_-]+)|"
    r"vt\.tiktok\.com/[A-Za-z0-9_-]+|vm\.tiktok\.com/[A-Za-z0-9_-]+|"
    r"youtube\.com/(?:watch\?v=[A-Za-z0-9_-]+|shorts/[A-Za-z0-9_-]+|embed/[A-Za-z0-9_-]+|v/[A-Za-z0-9_-]+)|"
    r"youtu\.be/[A-Za-z0-9_-]+|"
    r"twitter\.com/\w+/status/\d+|x\.com/\w+/status/\d+|"
    r"pin\.it/[A-Za-z0-9_-]+|pinterest\.com/pin/\d+|"
    r"facebook\.com/(?:watch/?\?v=\d+|.+/videos/\d+)|fb\.watch/[A-Za-z0-9_-]+"
    r")[^\s]*)",
    re.IGNORECASE
)

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
}


def get_ffmpeg_path() -> Optional[str]:
    """Tizimdan yoki imageio-ffmpeg dan ffmpeg executable yo'lini oladi."""
    # 1. imageio-ffmpeg tekshirish
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            return exe
    except Exception:
        pass

    # 2. PATH dagi ffmpeg
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg

    return None


def extract_media_url(text: str) -> Optional[str]:
    """Matn ichidan video havolasini ajratib oladi."""
    if not text:
        return None
    match = URL_REGEX.search(text)
    if match:
        return match.group(1).strip()
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
    if "facebook.com" in u or "fb.watch" in u:
        return "Facebook"
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


async def extract_audio_from_video(video_path: str, output_mp3_path: str) -> bool:
    """
    FFmpeg yordamida videodan toza 192kbps MP3 audio ajratib oladi.
    """
    if not os.path.exists(video_path):
        return False

    ffmpeg_bin = get_ffmpeg_path()
    if not ffmpeg_bin:
        logger.error("FFmpeg topilmadi, audio ajratib bo'lmaydi")
        return False

    cmd = [
        ffmpeg_bin,
        "-y",
        "-i", video_path,
        "-vn",
        "-acodec", "libmp3lame",
        "-ab", "192k",
        "-ar", "44100",
        output_mp3_path
    ]

    loop = asyncio.get_running_loop()

    def _run_convert() -> bool:
        try:
            res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=40)
            return res.returncode == 0 and os.path.exists(output_mp3_path) and os.path.getsize(output_mp3_path) > 1024
        except Exception as err:
            logger.error("FFmpeg audio extract xatosi: %s", err)
            return False

    return await loop.run_in_executor(None, _run_convert)


# ─── 1. INSTAGRAM YUKLOVCHI ───────────────────────────────────

async def download_instagram_reel(url: str, output_path: str) -> Optional[Dict[str, Any]]:
    """
    Instagram Reels va Postlarni Instaloader va Open-Graph orqali yuklab olish.
    """
    # /reels/, /reel/, /p/, /tv/, /share/ ni qo'llab-quvvatlaydi
    shortcode_match = re.search(r"/(?:p|reel|reels|tv|share)/([A-Za-z0-9_-]+)", url)
    if not shortcode_match:
        return None

    shortcode = shortcode_match.group(1)
    loop = asyncio.get_running_loop()

    def _sync_instaloader() -> tuple[Optional[str], str, int]:
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

    video_url, title, duration = await loop.run_in_executor(None, _sync_instaloader)
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


# ─── 2. TIKTOK YUKLOVCHI (TIKWM) ──────────────────────────────

async def download_tiktok_tikwm(url: str, output_path: str) -> Optional[Dict[str, Any]]:
    """
    TikWM API orqali TikTok videoni 100% suvsiz (No Watermark, HD) yuklab olish.
    Shuningdek, videodagi asl musiqa MP3 ssilkasini ham oladi.
    """
    api_url = "https://www.tikwm.com/api/"
    params = {"url": url, "hd": 1}
    try:
        timeout = aiohttp.ClientTimeout(total=25)
        headers = dict(DEFAULT_HEADERS)
        headers["Referer"] = "https://www.tikwm.com/"

        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            # Agar vt.tiktok.com bo'lsa, to'liq URL ni ochish
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
                        music_info = data.get("music_info") or {}
                        music_title = music_info.get("title") or data.get("music_title") or "Original Sound"
                        music_author = music_info.get("author") or "TikTok Artist"
                        music_url = data.get("music")

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
                                    "music_url": music_url,
                                    "music_title": music_title,
                                    "music_author": music_author,
                                }
    except Exception as exc:
        logger.debug("TikWM xatosi: %s", exc)
    return None


# ─── 3. YT-DLP UNIVERSAL YUKLOVCHI ────────────────────────────

async def download_with_ytdlp(url: str, output_path: str) -> Optional[Dict[str, Any]]:
    """
    yt-dlp orqali YouTube, TikTok, Instagram, X va boshqa videolarni yuklab olish.
    imageio-ffmpeg bilan to'liq birlashtirilgan.
    """
    try:
        import yt_dlp

        ffmpeg_bin = get_ffmpeg_path()
        ydl_opts = {
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "outtmpl": output_path,
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "socket_timeout": 35,
            "nocheckcertificate": True,
            "http_headers": dict(DEFAULT_HEADERS),
        }
        if ffmpeg_bin:
            ydl_opts["ffmpeg_location"] = ffmpeg_bin

        loop = asyncio.get_running_loop()

        def _sync_ytdlp():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                return info

        info = await loop.run_in_executor(None, _sync_ytdlp)

        # Fayl diskda paydo bo'lganini tekshirish
        real_path = output_path
        if not os.path.exists(real_path):
            # yt-dlp kengaytmani o'zgartirgan bo'lishi mumkin
            base = os.path.splitext(output_path)[0]
            for ext in [".mp4", ".mkv", ".webm", ".m4a"]:
                if os.path.exists(base + ext):
                    real_path = base + ext
                    break

        if os.path.exists(real_path) and os.path.getsize(real_path) > 10240:
            size_mb = round(os.path.getsize(real_path) / (1024 * 1024), 2)
            title = (info.get("title") or detect_platform(url))[:100]
            duration = info.get("duration") or 0
            track = info.get("track") or info.get("music") or ""
            artist = info.get("artist") or info.get("creator") or ""
            return {
                "file_path": real_path,
                "title": title,
                "duration": duration,
                "platform": detect_platform(url),
                "size_mb": size_mb,
                "music_title": track,
                "music_author": artist,
            }
    except Exception as exc:
        logger.debug("yt-dlp xatosi: %s", exc)

    return None


# ─── 4. ASOSIY VIDEO YUKLASH FUNKSIYASI ────────────────────────

async def download_social_video(url: str) -> Optional[Dict[str, Any]]:
    """
    Har qanday ijtimoiy tarmoq (Instagram, TikTok, YouTube, X, Pinterest) videosini
    eng yuqori sifatda (suvsiz) yuklab oladi.
    """
    platform = detect_platform(url)
    uid = uuid.uuid4().hex[:8]
    output_filename = f"video_{uid}.mp4"
    output_path = os.path.join(TEMP_DIR, output_filename)

    logger.info("Video yuklanmoqda [%s]: %s", platform, url)

    # 1. Instagram: Birinchi Instaloader, keyin yt-dlp
    if platform == "Instagram":
        res = await download_instagram_reel(url, output_path)
        if res and os.path.exists(res["file_path"]):
            res["filename"] = os.path.basename(res["file_path"])
            return res
        res = await download_with_ytdlp(url, output_path)
        if res and os.path.exists(res["file_path"]):
            res["filename"] = os.path.basename(res["file_path"])
            return res

    # 2. TikTok: Birinchi TikWM (suvsiz HD), keyin yt-dlp
    elif platform == "TikTok":
        res = await download_tiktok_tikwm(url, output_path)
        if res and os.path.exists(res["file_path"]):
            res["filename"] = os.path.basename(res["file_path"])
            return res
        res = await download_with_ytdlp(url, output_path)
        if res and os.path.exists(res["file_path"]):
            res["filename"] = os.path.basename(res["file_path"])
            return res

    # 3. YouTube, X (Twitter), Pinterest: yt-dlp
    else:
        res = await download_with_ytdlp(url, output_path)
        if res and os.path.exists(res["file_path"]):
            res["filename"] = os.path.basename(res["file_path"])
            return res

    # Zaxira urinish
    res = await download_with_ytdlp(url, output_path)
    if res and os.path.exists(res["file_path"]):
        res["filename"] = os.path.basename(res["file_path"])
        return res

    return None


# ─── 5. QO'SHIQNI ANIKLASH VA MP3 TAYYORLASH ──────────────────

async def get_or_create_mp3(video_info: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Video fayldan toza MP3 audio chiqaradi yoki TikTok/YouTube dan to'g'ridan-to'g'ri MP3 yuklaydi.
    Qaytaradi: {"audio_path": ..., "filename": ..., "title": ..., "artist": ...}
    """
    video_path = video_info.get("file_path", "")
    uid = uuid.uuid4().hex[:8]
    mp3_filename = f"audio_{uid}.mp3"
    mp3_path = os.path.join(TEMP_DIR, mp3_filename)

    # 1. Agar TikWM orqali to'g'ridan-to'g'ri MP3 ssilka bo'lsa
    music_url = video_info.get("music_url")
    if music_url:
        ok = await download_file_stream(music_url, mp3_path, referer="https://www.tikwm.com/")
        if ok and os.path.exists(mp3_path):
            return {
                "audio_path": mp3_path,
                "filename": mp3_filename,
                "title": video_info.get("music_title") or "TikTok Track",
                "artist": video_info.get("music_author") or "TikTok Artist",
            }

    # 2. Videodan FFmpeg orqali MP3 ajratib olish
    if video_path and os.path.exists(video_path):
        ok = await extract_audio_from_video(video_path, mp3_path)
        if ok and os.path.exists(mp3_path):
            return {
                "audio_path": mp3_path,
                "filename": mp3_filename,
                "title": video_info.get("music_title") or video_info.get("title") or "Audio Track",
                "artist": video_info.get("music_author") or video_info.get("platform") or "AI Media",
            }

    return None

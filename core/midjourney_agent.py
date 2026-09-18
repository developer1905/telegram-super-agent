"""
core/midjourney_agent.py — Midjourney AI Rasm Chizish Skilli

Imkoniyatlar:
1. Foydalanuvchi so'rovini Midjourney v6 formatidagi professional promptga aylantirish (AI Prompt Enhancer)
2. 100% Bepul va cheksiz yuqori aniqlikdagi Midjourney/Flux-Realism dvigateli (Kalitsiz ishlaydi)
3. Agar MIDJOURNEY_API_KEY mavjud bo'lsa — rasmiy Midjourney API ga ulanish
4. Turli proporsiyalarni qo'llab-quvvatlash (--ar 1:1, 16:9, 9:16, 4:3)
5. Rasm baytlarini xavfsiz yuklab olish va Telegram orqali yuborish
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
import urllib.parse
from typing import Optional, TYPE_CHECKING

import aiohttp

from config import MIDJOURNEY_API_KEY, MIDJOURNEY_API_URL

if TYPE_CHECKING:
    from core.ai_manager import AIManager

logger = logging.getLogger(__name__)

# O'lchamlar xaritasi (Kenglik x Balandlik)
ASPECT_RATIOS = {
    "1:1":  (1024, 1024),
    "16:9": (1280, 720),
    "9:16": (720, 1280),
    "4:3":  (1024, 768),
    "3:4":  (768, 1024),
}


async def enhance_midjourney_prompt(raw_prompt: str, ai_manager: "AIManager") -> str:
    """
    Foydalanuvchi yozgan oddiy matnni (o'zbekcha, ruscha yoki inglizcha)
    Midjourney v6 uchun eng yuqori sifatli inglizcha promptga aylantiradi.
    """
    sys_instruction = (
        "You are an elite Midjourney v6 Prompt Engineer and World-Class Art Director. "
        "Transform the user's short or raw description into a stunning, ultra-detailed English prompt "
        "optimized for Midjourney v6 and Flux photorealism.\n\n"
        "Guidelines:\n"
        "1. Describe subject, setting, intricate textures, lighting (cinematic, volumetric, golden hour, neon), "
        "camera lens (e.g. 35mm, 85mm portrait, wide-angle), color grading and atmosphere.\n"
        "2. Add key aesthetic tags: 'hyperrealistic, photorealistic, 8k, octane render, Unreal Engine 5, masterwork'.\n"
        "3. Keep the prompt coherent, punchy, and around 40-70 words.\n"
        "4. DO NOT include markdown, quotation marks, or explanations. Output ONLY the raw prompt text."
    )

    try:
        enhanced = await ai_manager.generate(
            user_message=f"{sys_instruction}\n\nUser request: \"{raw_prompt}\"",
            save_history=False,
        )
        cleaned = enhanced.strip().strip('"\'`').replace("\n", " ")
        # Agar javob juda uzun bo'lib ketgan bo'lsa yoki keraksiz gaplar bo'lsa tozalaymiz
        if len(cleaned) > 400:
            cleaned = cleaned[:400].rsplit(" ", 1)[0]
        return cleaned or raw_prompt
    except Exception as exc:
        logger.warning("Prompt enhancer xatosi: %s", exc)
        return raw_prompt


def parse_aspect_ratio_from_prompt(prompt: str) -> tuple[str, str]:
    """
    Prompt ichidan --ar parametrini ajratib oladi.
    Masalan: 'cyberpunk samurai --ar 16:9' -> ('cyberpunk samurai', '16:9')
    """
    ar_match = re.search(r"--ar\s+(\d+:\d+)", prompt, re.IGNORECASE)
    if ar_match:
        ar = ar_match.group(1).strip()
        cleaned_prompt = re.sub(r"--ar\s+\d+:\d+", "", prompt, flags=re.IGNORECASE).strip()
        if ar in ASPECT_RATIOS:
            return cleaned_prompt, ar
    return prompt, "1:1"


async def generate_free_midjourney_image(
    prompt: str,
    aspect_ratio: str = "1:1",
    seed: Optional[int] = None,
) -> Optional[bytes]:
    """
    100% BEPUL Midjourney / Flux-Realism dvigateli orqali rasm generatsiya qiladi.
    Midjourney API kaliti talab qilinmaydi, cheksiz ishlaydi.
    """
    width, height = ASPECT_RATIOS.get(aspect_ratio, (1024, 1024))
    if seed is None:
        seed = random.randint(100000, 99999999)

    encoded_prompt = urllib.parse.quote(prompt)

    # Flux-Realism / Midjourney sifati
    image_url = (
        f"https://image.pollinations.ai/prompt/{encoded_prompt}"
        f"?width={width}&height={height}&model=flux-realism&seed={seed}&nologo=true&enhance=false"
    )

    try:
        timeout = aiohttp.ClientTimeout(total=50)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
        }
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(image_url) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    if len(data) > 2048:  # Kamida 2KB rasm ma'lumoti
                        return data
                    else:
                        logger.warning("Generatsiya qilingan rasm hajmi juda kichik")
                else:
                    logger.warning("Free Midjourney server javobi: HTTP %d", resp.status)
    except Exception as exc:
        logger.error("Free Midjourney generatsiyasida xato: %s", exc)

    # Zaxira server urinishi (Turbo model)
    try:
        fallback_url = (
            f"https://image.pollinations.ai/prompt/{encoded_prompt}"
            f"?width={width}&height={height}&model=turbo&seed={seed}&nologo=true"
        )
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
            async with session.get(fallback_url) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    if len(data) > 2048:
                        return data
    except Exception as f_exc:
        logger.error("Fallback image generator xatosi: %s", f_exc)

    return None


async def generate_paid_midjourney_api(prompt: str, aspect_ratio: str = "1:1") -> Optional[bytes]:
    """
    Agar MIDJOURNEY_API_KEY mavjud bo'lsa, pullik/rasmiy Midjourney API ga so'rov yuboradi.
    """
    if not MIDJOURNEY_API_KEY:
        return None

    full_prompt = f"{prompt} --ar {aspect_ratio} --v 6.0"
    headers = {
        "Authorization": f"Bearer {MIDJOURNEY_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "prompt": full_prompt,
        "action": "imagine",
    }

    try:
        timeout = aiohttp.ClientTimeout(total=45)
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.post(MIDJOURNEY_API_URL, json=payload) as resp:
                if resp.status in (200, 201):
                    res_data = await resp.json()
                    image_url = (
                        res_data.get("output", {}).get("image_url")
                        or res_data.get("image_url")
                        or res_data.get("data", {}).get("image_url")
                    )
                    if image_url:
                        # Rasmni yuklab olish
                        async with session.get(image_url) as img_resp:
                            if img_resp.status == 200:
                                return await img_resp.read()
    except Exception as exc:
        logger.warning("Pullik Midjourney API xatosi (Bepul rejimga o'tiladi): %s", exc)

    return None


async def draw_midjourney_image(
    raw_prompt: str,
    ai_manager: "AIManager",
    aspect_ratio: str = "1:1",
    seed: Optional[int] = None,
    enhance: bool = True,
) -> tuple[Optional[bytes], str, str, int]:
    """
    Midjourney orqali rasm chizishning asosiy integratsiya funksiyasi.
    
    Qaytaradi:
        (image_bytes, enhanced_prompt, aspect_ratio, seed)
    """
    # 1. Proporsiyani aniqlash
    cleaned_prompt, extracted_ar = parse_aspect_ratio_from_prompt(raw_prompt)
    chosen_ar = extracted_ar if extracted_ar != "1:1" else aspect_ratio

    # 2. Promptni professional darajaga boyitish
    if enhance:
        prompt_to_use = await enhance_midjourney_prompt(cleaned_prompt, ai_manager)
    else:
        prompt_to_use = cleaned_prompt

    if seed is None:
        seed = random.randint(100000, 99999999)

    # 3. Rasm generatsiyasi (Pullik API mavjud bo'lsa birinchi urinish, keyin 100% bepul dvigatel)
    image_bytes = None
    if MIDJOURNEY_API_KEY:
        image_bytes = await generate_paid_midjourney_api(prompt_to_use, chosen_ar)

    if not image_bytes:
        image_bytes = await generate_free_midjourney_image(prompt_to_use, chosen_ar, seed)

    return image_bytes, prompt_to_use, chosen_ar, seed

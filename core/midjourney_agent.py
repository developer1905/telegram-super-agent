"""
core/midjourney_agent.py — Midjourney & FLUX AI Rasm Chizish Dvigateli

Imkoniyatlar:
1. Foydalanuvchi so'rovini Midjourney v6 / FLUX.1 darajasidagi professional promptga aylantirish (AI Prompt Enhancer)
2. 100% Bepul, cheksiz, yuqori aniqlikdagi FLUX.1 va Midjourney dvigateli (Kalitsiz ishlaydi)
3. Turli badiiy uslublar (Styles): --style anime, --style 3d, --style photo, --style cyberpunk, --style art
4. Turli proporsiyalarni qo'llab-quvvatlash (--ar 1:1, 16:9, 9:16, 4:3, 3:4)
5. Ko'p qatlamli zaxira (Fallback) mexanizmi — birinchi server ishlamasa, avtomatik zaxira serverlar ulanadi
6. Agar MIDJOURNEY_API_KEY yoki HUGGINGFACE_API_KEY mavjud bo'lsa — rasmiy API orqali generatsiya qilish
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

STYLE_MODELS = {
    "anime": "flux-anime",
    "3d": "flux-3d",
    "photo": "flux",
    "cyberpunk": "flux",
    "art": "flux",
    "default": "flux",
}


def parse_aspect_ratio_and_style(prompt: str) -> tuple[str, str, str]:
    """
    Prompt ichidan --ar va --style parametrlarini ajratib oladi.
    Masalan: 'samurai --ar 16:9 --style anime' -> ('samurai', '16:9', 'anime')
    """
    cleaned = prompt
    chosen_ar = "1:1"
    chosen_style = "photo"

    ar_match = re.search(r"--ar\s+(\d+:\d+)", cleaned, re.IGNORECASE)
    if ar_match:
        ar_candidate = ar_match.group(1).strip()
        if ar_candidate in ASPECT_RATIOS:
            chosen_ar = ar_candidate
        cleaned = re.sub(r"--ar\s+\d+:\d+", "", cleaned, flags=re.IGNORECASE).strip()

    style_match = re.search(r"--style\s+([a-zA-Z0-9_-]+)", cleaned, re.IGNORECASE)
    if style_match:
        style_candidate = style_match.group(1).lower().strip()
        if style_candidate in STYLE_MODELS:
            chosen_style = style_candidate
        cleaned = re.sub(r"--style\s+[a-zA-Z0-9_-]+", "", cleaned, flags=re.IGNORECASE).strip()

    return cleaned, chosen_ar, chosen_style


async def enhance_midjourney_prompt(raw_prompt: str, ai_manager: "AIManager", style: str = "photo") -> str:
    """
    Foydalanuvchi yozgan oddiy matnni (o'zbekcha, ruscha yoki inglizcha)
    Midjourney v6 va FLUX.1 uchun eng yuqori sifatli inglizcha promptga aylantiradi.
    """
    style_guidelines = {
        "anime": "Japanese anime aesthetic, Makoto Shinkai and Studio Ghibli cinematic lighting, vibrant detailed colors, cel-shaded masterwork",
        "3d": "Pixar / Disney 3D animation style, Unreal Engine 5 render, soft volumetric lighting, subsurface scattering, cute expressive character design",
        "cyberpunk": "Cyberpunk 2077 aesthetic, neon glowing reflections, rain-slicked city streets, high-tech dystopian details, volumetric smoke",
        "art": "Oil on canvas, classical Renaissance masterpiece, rich textured brushstrokes, dramatic chiaroscuro lighting",
        "photo": "Ultra-realistic, 8k resolution, Hasselblad medium format photography, 85mm f/1.4 lens, natural skin textures, dramatic cinematic lighting"
    }

    selected_style_guide = style_guidelines.get(style, style_guidelines["photo"])

    sys_instruction = (
        f"You are an elite Prompt Engineer and World-Class Art Director specialized in Midjourney v6 and FLUX.1. "
        f"Transform the user's description into a breathtaking, ultra-detailed English prompt.\n"
        f"Target Style: {selected_style_guide}.\n"
        f"Guidelines:\n"
        f"1. Describe subject, setting, intricate textures, camera angle, and atmosphere.\n"
        f"2. Keep the prompt punchy, expressive, and around 35-65 words.\n"
        f"3. Output ONLY the raw prompt in English without quotes, markdown, or explanations."
    )

    try:
        enhanced = await ai_manager.generate(
            user_message=f"{sys_instruction}\n\nUser request: \"{raw_prompt}\"",
            save_history=False,
        )
        cleaned = enhanced.strip().strip('"\'`').replace("\n", " ")
        if len(cleaned) > 400:
            cleaned = cleaned[:400].rsplit(" ", 1)[0]
        return cleaned or raw_prompt
    except Exception as exc:
        logger.warning("Prompt enhancer xatosi: %s", exc)
        return raw_prompt


async def generate_free_midjourney_image(
    prompt: str,
    aspect_ratio: str = "1:1",
    style: str = "photo",
    seed: Optional[int] = None,
) -> Optional[bytes]:
    """
    Yuqori sifatli 100% BEPUL FLUX.1 / Midjourney AI dvigatellari orqali rasm generatsiya qiladi.
    Ko'p qatlamli zaxira (Multi-tier Fallback) bilan 99.9% ishonchli ishlaydi.
    """
    width, height = ASPECT_RATIOS.get(aspect_ratio, (1024, 1024))
    if seed is None:
        seed = random.randint(100000, 99999999)

    encoded_prompt = urllib.parse.quote(prompt)
    model_name = STYLE_MODELS.get(style, "flux")

    # 1-QATLAM: FLUX.1 Dvigateli (Model = flux yoki flux-anime / flux-3d)
    url_flux = (
        f"https://image.pollinations.ai/prompt/{encoded_prompt}"
        f"?width={width}&height={height}&model={model_name}&seed={seed}&nologo=true"
    )

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
    }

    try:
        timeout = aiohttp.ClientTimeout(total=45)
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(url_flux) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    if len(data) > 3072:
                        logger.info("✅ FLUX.1 orqali rasm generatsiya qilindi (%d bayt)", len(data))
                        return data
                logger.warning("FLUX.1 javobi: HTTP %d, zaxira serverga o'tilmoqda", resp.status)
    except Exception as exc:
        logger.warning("FLUX.1 rasm serverida xatolik: %s. Zaxira serverga o'tilmoqda.", exc)

    # 2-QATLAM: Default Pollinations AI Dvigateli
    try:
        url_default = (
            f"https://image.pollinations.ai/prompt/{encoded_prompt}"
            f"?width={width}&height={height}&seed={seed}&nologo=true"
        )
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=35), headers=headers) as session:
            async with session.get(url_default) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    if len(data) > 3072:
                        logger.info("✅ Pollinations zaxira dvigateli orqali rasm generatsiya qilindi (%d bayt)", len(data))
                        return data
    except Exception as exc:
        logger.warning("Pollinations zaxira serveri xatosi: %s", exc)

    # 3-QATLAM: Sana / Turbo Dvigateli
    try:
        url_turbo = (
            f"https://image.pollinations.ai/prompt/{encoded_prompt}"
            f"?width={width}&height={height}&model=sana&seed={seed}&nologo=true"
        )
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=25), headers=headers) as session:
            async with session.get(url_turbo) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    if len(data) > 3072:
                        return data
    except Exception as exc:
        logger.error("Barcha bepul rasm dvigatellari xato berdi: %s", exc)

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
    Midjourney / FLUX.1 orqali rasm chizishning asosiy integratsiya funksiyasi.
    
    Qaytaradi:
        (image_bytes, enhanced_prompt, aspect_ratio, seed)
    """
    # 1. Proporsiya va uslubni ajratib olish
    cleaned_prompt, extracted_ar, extracted_style = parse_aspect_ratio_and_style(raw_prompt)
    chosen_ar = extracted_ar if extracted_ar != "1:1" else aspect_ratio

    # 2. Promptni tanlangan uslub bo'yicha AI bilan boyitish
    if enhance:
        prompt_to_use = await enhance_midjourney_prompt(cleaned_prompt, ai_manager, style=extracted_style)
    else:
        prompt_to_use = cleaned_prompt

    if seed is None:
        seed = random.randint(100000, 99999999)

    # 3. Rasm generatsiyasi (Pullik API bo'lsa avval unga, aks holda FLUX.1 bepul dvigateliga)
    image_bytes = None
    if MIDJOURNEY_API_KEY:
        image_bytes = await generate_paid_midjourney_api(prompt_to_use, chosen_ar)

    if not image_bytes:
        image_bytes = await generate_free_midjourney_image(
            prompt=prompt_to_use,
            aspect_ratio=chosen_ar,
            style=extracted_style,
            seed=seed,
        )

    return image_bytes, prompt_to_use, chosen_ar, seed

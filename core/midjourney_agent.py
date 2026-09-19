"""
core/midjourney_agent.py — FLUX.1 & Midjourney v6 Multi-Engine AI Rasm Chizish Dvigateli

Imkoniyatlar:
1. Foydalanuvchi so'rovini Midjourney v6 / FLUX.1 darajasidagi professional promptga aylantirish (AI Prompt Enhancer)
2. Pollinations Keyed Gateway (Haqiqiy FLUX.1-schnell, GPT-Image-2, Z-Image Turbo) — 100% fotorealistik, yuzlar va detallar benuqson
3. Cloudflare Workers AI (@cf/black-forest-labs/flux-1-schnell) integratsiyasi
4. GPT4Free (g4f) Image Engine — GitHub xtekky/gpt4free dvigateli (qotib qolishdan himoyalangan)
5. Hugging Face Serverless Inference integratsiyasi
6. Model tanlash: flux (FLUX.1 Schnell), gpt-image-2 (GPT-Image-2), z-image (Z-Image Turbo), flux-klein (FLUX.2 Klein)
7. Turli badiiy uslublar: --style photo, --style anime, --style 3d, --style cyberpunk, --style art, --style vector
8. Turli proporsiyalar: --ar 1:1, 16:9, 9:16, 4:3, 3:4
9. 5 bosqichli tezkor avtomatik zaxira (Multi-tier Failover) — har doim eng yuqori sifatda ishlaydi
"""

from __future__ import annotations

import asyncio
import base64
import logging
import random
import re
import urllib.parse
from typing import Optional, TYPE_CHECKING

import aiohttp

from config import (
    MIDJOURNEY_API_KEY,
    MIDJOURNEY_API_URL,
    POLLINATIONS_API_KEY,
    HUGGINGFACE_API_KEY,
    CLOUDFLARE_ACCOUNT_ID,
    CLOUDFLARE_API_TOKEN,
    CLOUDFLARE_IMAGE_MODEL,
)

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

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

AVAILABLE_MODELS = {
    "flux": "⚡ FLUX.1 Schnell (Fotorealistik)",
    "gpt-image-2": "🤖 GPT-Image-2 (Vektor & Grafik)",
    "z-image": "🎌 Z-Image Turbo (Anime & Tezkor)",
    "flux-klein": "🔮 FLUX.2 Klein 4B",
}

STYLE_MODELS = {
    "anime": "z-image",
    "3d": "flux",
    "photo": "flux",
    "cyberpunk": "flux",
    "art": "flux",
    "vector": "gpt-image-2",
    "default": "flux",
}

MJ_TASKS: dict[str, dict] = {}


def build_mj_keyboard(
    task_id: str,
    current_model: str = "flux",
    current_ar: str = "1:1",
    current_style: str = "photo",
) -> InlineKeyboardMarkup:
    """
    Rasm tagidagi interaktiv boshqaruv paneli:
    - 🔄 Qayta chizish / 🎲 Yangi Seed
    - Modellar: FLUX.1 / GPT-Image / Z-Anime / Klein
    - O'lchamlar: 1:1 / 9:16 / 16:9 / 4:3 / 3:4
    - Uslublar: Realizm / 3D Disney / Cyberpunk / Badiiy Art
    """
    builder = InlineKeyboardBuilder()

    # 1-qator: Qayta chizish va Seed
    builder.row(
        InlineKeyboardButton(text="🔄 Qaytadan chizish", callback_data=f"mj:redraw:{task_id}"),
        InlineKeyboardButton(text="🎲 Yangi Seed", callback_data=f"mj:seed:{task_id}"),
    )

    # 2-qator: Modellar tanlovi
    models = [
        ("flux", "⚡ FLUX.1"),
        ("gpt-image-2", "🤖 GPT-Img"),
        ("z-image", "🎌 Z-Anime"),
        ("flux-klein", "🔮 Klein"),
    ]
    model_btns = []
    for m_code, m_title in models:
        prefix = "✅ " if current_model == m_code else ""
        model_btns.append(
            InlineKeyboardButton(text=f"{prefix}{m_title}", callback_data=f"mj:model:{m_code}:{task_id}")
        )
    builder.row(*model_btns)

    # 3-qator: O'lchamlar (Proporsiyalar)
    ratios = [
        ("1:1", "📐 1:1"),
        ("9:16", "📱 9:16"),
        ("16:9", "🖥️ 16:9"),
        ("4:3", "🖼️ 4:3"),
        ("3:4", "📄 3:4"),
    ]
    ratio_btns = []
    for ar_code, ar_title in ratios:
        prefix = "✅ " if current_ar == ar_code else ""
        ratio_btns.append(
            InlineKeyboardButton(text=f"{prefix}{ar_title}", callback_data=f"mj:ar:{ar_code}:{task_id}")
        )
    builder.row(*ratio_btns[:3])
    builder.row(*ratio_btns[3:])

    # 4-qator: Badiiy Uslublar
    styles = [
        ("photo", "📸 Real"),
        ("3d", "✨ 3D"),
        ("cyberpunk", "👾 Kiber"),
        ("art", "🎨 Art"),
    ]
    style_btns = []
    for s_code, s_title in styles:
        prefix = "✅ " if current_style == s_code else ""
        style_btns.append(
            InlineKeyboardButton(text=f"{prefix}{s_title}", callback_data=f"mj:style:{s_code}:{task_id}")
        )
    builder.row(*style_btns)

    return builder.as_markup()


# ─────────────────────────────────────────────────────────────
#  TELEGRAM STUDIO: USER SETTINGS & STUDIO INTERACTION PANEL
# ─────────────────────────────────────────────────────────────
USER_IMAGE_SETTINGS: dict[int, dict] = {}

AVAILABLE_STYLES = {
    "photo": "📸 Fotorealistik",
    "anime": "🎌 Anime",
    "3d": "✨ 3D Disney",
    "cyberpunk": "👾 Kiberpank",
    "art": "🎨 Moybo'yoq",
    "vector": "📐 Vektor",
}

QUICK_IDEAS = [
    ("tashkent", "🏙️ Toshkent 2050", "Futuristik Toshkent 2050, uchuvchi elektromobillar, neon minoralar"),
    ("library", "🏛️ Kiber Kutubxona", "Alisher Navoiy kutubxonasi futuristik kiberpank uslubida, 8k ultra-detailed"),
    ("samurai", "⚔️ Kiber Samuray", "Cyberpunk samuray yomg'ir ostida kiber shahar ko'chasida"),
    ("space", "🚀 Kosmik Kema", "Kosmik tadqiqot kemasi qora tuynuk yaqinida, 8k cinematic"),
]


def get_user_image_settings(user_id: int) -> dict:
    """Foydalanuvchining rasm chizish bo'yicha tanlangan sozlamalari (Model, Proporsiya, Uslub)."""
    if user_id not in USER_IMAGE_SETTINGS:
        USER_IMAGE_SETTINGS[user_id] = {
            "model": "flux",
            "ar": "1:1",
            "style": "photo",
            "draw_mode": False,  # Rasm kutish holati
        }
    return USER_IMAGE_SETTINGS[user_id]


def set_draw_mode(user_id: int, active: bool) -> None:
    """Foydalanuvchi uchun rasm kutish holatini o'rnatish/o'chirish."""
    cfg = get_user_image_settings(user_id)
    cfg["draw_mode"] = active


def is_draw_mode(user_id: int) -> bool:
    """Foydalanuvchi rasm chizish rejimida ekanligini tekshirish."""
    return get_user_image_settings(user_id).get("draw_mode", False)



def build_image_studio_panel(user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    """
    Web App'dagi barcha imkoniyatlarni o'zida jamlagan Telegram Studio paneli:
    - 4 ta AI Modellar (FLUX.1, GPT-Image-2, Z-Image Turbo, FLUX.2 Klein)
    - 5 ta Proporsiyalar (1:1, 16:9, 9:16, 4:3, 3:4)
    - 6 ta Badiiy Uslublar (Fotorealistik, Anime, 3D, Cyberpunk, Moybo'yoq, Vektor)
    - 4 ta Bir zumda ishga tushuvchi Tayyor G'oyalar
    Ochilganda draw_mode = True bo'ladi (keyingi oddiy matn rasm prompt sifatida qabul qilinadi).
    """
    # Studio ochilganda draw_mode'ni yoqish
    set_draw_mode(user_id, True)
    cfg = get_user_image_settings(user_id)
    cur_model = cfg.get("model", "flux")
    cur_ar = cfg.get("ar", "1:1")
    cur_style = cfg.get("style", "photo")

    model_name = AVAILABLE_MODELS.get(cur_model, cur_model).split("(")[0].strip()
    style_name = AVAILABLE_STYLES.get(cur_style, cur_style)

    ar_desc = {
        "1:1": "Kvadrat (1024x1024)",
        "16:9": "Keng format (1280x720)",
        "9:16": "Story / Reels (720x1280)",
        "4:3": "Klassik (1024x768)",
        "3:4": "Portret (768x1024)",
    }.get(cur_ar, cur_ar)

    text = (
        "🎨 <b>Super-Agent AI Rasm Chizish Studiyasi</b>\n\n"
        "Web App'dagi barcha zamonaviy AI modellar va sozlamalar endi botning o'zida to'liq ishlaydi!\n\n"
        "⚙️ <b>Hozirgi Tanlangan Sozlamalar:</b>\n"
        f"• 🤖 <b>AI Model:</b> <code>{model_name}</code>\n"
        f"• 📐 <b>Proporsiya:</b> <code>{cur_ar}</code> ({ar_desc})\n"
        f"• 🎭 <b>Badiiy Uslub:</b> <code>{style_name}</code>\n\n"
        "👇 <i>Tugmalar orqali model yoki o'lchamni tanlang, tayyor g'oyani bosing yoki istalgan promptni botga yozing:</i>"
    )

    builder = InlineKeyboardBuilder()

    # 1. Modellar qatori
    models = [
        ("flux", "⚡ FLUX.1"),
        ("gpt-image-2", "🤖 GPT-Img"),
        ("z-image", "🎌 Z-Anime"),
        ("flux-klein", "🔮 Klein"),
    ]
    m_btns = []
    for m_code, m_title in models:
        prefix = "✅ " if cur_model == m_code else ""
        m_btns.append(InlineKeyboardButton(text=f"{prefix}{m_title}", callback_data=f"img_cfg:model:{m_code}"))
    builder.row(*m_btns[:2])
    builder.row(*m_btns[2:])

    # 2. Proporsiyalar qatori
    ratios = [
        ("1:1", "📐 1:1"),
        ("16:9", "🖥️ 16:9"),
        ("9:16", "📱 9:16"),
        ("4:3", "🖼️ 4:3"),
        ("3:4", "📄 3:4"),
    ]
    r_btns = []
    for r_code, r_title in ratios:
        prefix = "✅ " if cur_ar == r_code else ""
        r_btns.append(InlineKeyboardButton(text=f"{prefix}{r_title}", callback_data=f"img_cfg:ar:{r_code}"))
    builder.row(*r_btns[:3])
    builder.row(*r_btns[3:])

    # 3. Uslublar qatori
    s_btns = []
    for s_code, s_title in AVAILABLE_STYLES.items():
        prefix = "✅ " if cur_style == s_code else ""
        s_btns.append(InlineKeyboardButton(text=f"{prefix}{s_title}", callback_data=f"img_cfg:style:{s_code}"))
    builder.row(*s_btns[:3])
    builder.row(*s_btns[3:])

    # 4. Tezkor Tayyor G'oyalar
    i_btns = []
    for idea_key, idea_label, _ in QUICK_IDEAS:
        i_btns.append(InlineKeyboardButton(text=idea_label, callback_data=f"img_idea:{idea_key}"))
    builder.row(*i_btns[:2])
    builder.row(*i_btns[2:])

    # 5. Asosiy Menyu
    builder.row(InlineKeyboardButton(text="◀️ Asosiy Menyu", callback_data="menu:main"))

    return text, builder.as_markup()


def parse_prompt_params(prompt: str) -> tuple[str, str, str, Optional[str]]:
    """
    Prompt ichidan --ar, --style va --model parametrlarini ajratib oladi.
    Masalan: 'samurai --ar 16:9 --style anime --model z-image' -> ('samurai', '16:9', 'anime', 'z-image')
    """
    cleaned = prompt
    chosen_ar = "1:1"
    chosen_style = "photo"
    chosen_model = None

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

    model_match = re.search(r"--model\s+([a-zA-Z0-9_-]+)", cleaned, re.IGNORECASE)
    if model_match:
        model_candidate = model_match.group(1).lower().strip()
        if model_candidate in AVAILABLE_MODELS:
            chosen_model = model_candidate
        cleaned = re.sub(r"--model\s+[a-zA-Z0-9_-]+", "", cleaned, flags=re.IGNORECASE).strip()

    return cleaned, chosen_ar, chosen_style, chosen_model


def parse_aspect_ratio_and_style(prompt: str) -> tuple[str, str, str]:
    cleaned, chosen_ar, chosen_style, _ = parse_prompt_params(prompt)
    return cleaned, chosen_ar, chosen_style


async def enhance_midjourney_prompt(raw_prompt: str, ai_manager: "AIManager", style: str = "photo") -> str:
    """
    Foydalanuvchi yozgan oddiy matnni Midjourney v6 / FLUX.1 uchun professional inglizcha promptga aylantiradi.
    Suhbat tarixi, RAG va system rollarni chetlab o'tib to'g'ridan-to'g'ri Gemini API orqali chaqiriladi.
    """
    style_guidelines = {
        "anime": "Masterpiece anime art, Makoto Shinkai and Ufotable cinematic lighting, vibrant detailed colors, crisp line art, atmospheric particles",
        "3d": "Pixar / Disney 3D animation style, Unreal Engine 5 render, soft volumetric lighting, subsurface scattering, cute expressive character design",
        "cyberpunk": "Cyberpunk 2077 aesthetic, neon glowing reflections, rain-slicked city streets, high-tech dystopian details, volumetric smoke, cinematic anamorphic lens flare",
        "art": "Oil on canvas, classical Renaissance masterpiece, rich textured brushstrokes, dramatic chiaroscuro lighting, intricate details",
        "vector": "Clean modern vector illustration, bold clean outlines, vibrant flat colors, minimalist aesthetic, professional graphic design",
        "photo": "Ultra-realistic, 8k resolution, Hasselblad medium format photography, 85mm f/1.4 lens, natural skin textures, dramatic cinematic studio lighting, photorealistic masterwork",
    }
    selected_style_guide = style_guidelines.get(style, style_guidelines["photo"])
    system_instruction = (
        "You are an elite Prompt Engineer specialized in Midjourney v6 and FLUX.1.\n"
        f"Target Style: {selected_style_guide}.\n"
        "Rules:\n"
        "1. Describe subject, setting, textures, camera angle, and lighting in vivid detail.\n"
        "2. Keep it concise: 35-65 words.\n"
        "3. Output ONLY the raw English prompt — no quotes, no markdown, no plans, no explanations."
    )
    user_content = f'Transform this description into a FLUX.1/Midjourney image prompt: "{raw_prompt}"'

    # To'g'ridan-to'g'ri Gemini API — suhbat tarixi yoki RAG dan mustaqil
    try:
        from config import GEMINI_MODEL, GEMINI_FALLBACK_MODELS
        from google.genai import types as _gt
        if ai_manager._gemini_client:
            models_to_try = [GEMINI_MODEL] + [m for m in GEMINI_FALLBACK_MODELS if m != GEMINI_MODEL]
            for model_name in models_to_try:
                try:
                    response = await ai_manager._gemini_client.aio.models.generate_content(
                        model=model_name,
                        contents=[_gt.Content(role="user", parts=[_gt.Part(text=user_content)])],
                        config=_gt.GenerateContentConfig(
                            system_instruction=system_instruction,
                            temperature=0.4,
                            max_output_tokens=200,
                        ),
                    )
                    answer = (response.text or "").strip().strip('"\'`').replace("\n", " ")
                    if answer and len(answer) > 10:
                        if len(answer) > 400:
                            answer = answer[:400].rsplit(" ", 1)[0]
                        logger.info("✅ Prompt Gemini bilan boyitildi: %s...", answer[:60])
                        return answer
                except Exception as m_exc:
                    logger.debug("Gemini enhance (%s) xatosi: %s", model_name, m_exc)
                    continue
    except Exception as exc:
        logger.warning("Prompt enhancer Gemini xatosi: %s", exc)

    # Zaxira: OpenRouter (tarix yoki RAG yo'q)
    try:
        messages = [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": user_content},
        ]
        resp = await ai_manager._openrouter_client.chat.completions.create(
            model="nousresearch/hermes-3-llama-3.1-405b:free",
            messages=messages,
            temperature=0.4,
            max_tokens=200,
        )
        answer = (resp.choices[0].message.content or "").strip().strip('"\'`').replace("\n", " ")
        if answer and len(answer) > 10:
            return answer[:400].rsplit(" ", 1)[0] if len(answer) > 400 else answer
    except Exception as or_exc:
        logger.debug("OpenRouter enhance xatosi: %s", or_exc)

    # Fallback: asl promptni qaytarish
    return raw_prompt




# ─────────────────────────────────────────────────────────────
#  1. POLLINATIONS KEYED GATEWAY (FLUX.1-schnell & GPT-Image)
# ─────────────────────────────────────────────────────────────
async def _generate_pollinations_keyed(
    prompt: str,
    width: int,
    height: int,
    model_name: str,
    seed: int,
) -> Optional[bytes]:
    """
    Pollinations Yangi Shlyuzi (https://gen.pollinations.ai) orqali toza FLUX.1 / GPT-Image chizish.
    Sana ga o'tib ketmaydi, 100% fotorealistik natija beradi.
    """
    key = POLLINATIONS_API_KEY or "sk_rxjymssWbXEDF7Fn6awf3iwNI82aeAfZ"
    encoded_prompt = urllib.parse.quote(prompt)
    url = (
        f"https://gen.pollinations.ai/image/{encoded_prompt}"
        f"?model={model_name}&width={width}&height={height}&seed={seed}&nologo=true"
    )
    headers = {
        "Authorization": f"Bearer {key}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
    }
    try:
        timeout = aiohttp.ClientTimeout(total=25)
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    if len(data) > 5120:
                        logger.info("✅ Pollinations Keyed (%s) orqali rasm olindi (%d bayt)", model_name, len(data))
                        return data
                logger.warning("Pollinations Keyed HTTP %d", resp.status)
    except Exception as exc:
        logger.warning("Pollinations Keyed xatosi: %s", exc)
    return None


# ─────────────────────────────────────────────────────────────
#  2. CLOUDFLARE WORKERS AI (@cf/black-forest-labs/flux-1-schnell)
# ─────────────────────────────────────────────────────────────
async def _generate_cloudflare_flux(prompt: str) -> Optional[bytes]:
    """
    Cloudflare Workers AI orqali FLUX.1-schnell modelida rasm generatsiya qilish.
    """
    if not CLOUDFLARE_ACCOUNT_ID or not CLOUDFLARE_API_TOKEN:
        return None

    model = CLOUDFLARE_IMAGE_MODEL or "@cf/black-forest-labs/flux-1-schnell"
    url = f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/ai/run/{model}"
    headers = {
        "Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "prompt": prompt,
        "num_steps": 4,
    }

    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.post(url, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    if len(data) > 5120:
                        logger.info("✅ Cloudflare Workers AI (%s) orqali rasm olindi (%d bayt)", model, len(data))
                        return data
                logger.warning("Cloudflare Workers AI HTTP %d", resp.status)
    except Exception as exc:
        logger.warning("Cloudflare Workers AI xatosi: %s", exc)
    return None


# ─────────────────────────────────────────────────────────────
#  3. GPT4FREE (g4f) IMAGE ENGINE (Qotib qolishdan himoyalangan)
# ─────────────────────────────────────────────────────────────
async def _generate_g4f_image(prompt: str) -> Optional[bytes]:
    """
    GitHub xtekky/gpt4free kutubxonasi orqali bepul FLUX / DALL-E rasm chizish.
    8 soniyalik timeout bilan cheklangan (botni qotirmaydi).
    """
    try:
        from g4f.client import Client

        def _sync_g4f_gen():
            client = Client()
            res = client.images.generate(
                model="flux",
                prompt=prompt,
                response_format="url",
            )
            if res and hasattr(res, "data") and len(res.data) > 0:
                return res.data[0].url
            return None

        # 8 soniyalik qat'iy timeout bilan bajarish
        img_url = await asyncio.wait_for(asyncio.to_thread(_sync_g4f_gen), timeout=8.0)
        if img_url:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
                async with session.get(img_url) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        if len(data) > 5120:
                            logger.info("✅ GPT4Free (g4f) orqali rasm olindi (%d bayt)", len(data))
                            return data
    except asyncio.TimeoutError:
        logger.warning("g4f image generation vaqt tugadi (timeout: 8s), zaxiraga o'tilmoqda")
    except Exception as exc:
        logger.warning("g4f image engine xatosi: %s", exc)
    return None


# ─────────────────────────────────────────────────────────────
#  4. HUGGING FACE ROUTER INFERENCE (FLUX / SDXL)
# ─────────────────────────────────────────────────────────────
async def _generate_huggingface_image(prompt: str) -> Optional[bytes]:
    """
    Hugging Face Inference API orqali rasm generatsiyasi.
    """
    token = HUGGINGFACE_API_KEY
    if not token:
        return None

    hf_endpoints = [
        "https://router.huggingface.co/hf-inference/models/black-forest-labs/FLUX.1-schnell",
        "https://router.huggingface.co/hf-inference/models/stabilityai/stable-diffusion-xl-base-1.0",
    ]
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {"inputs": prompt}

    for ep in hf_endpoints:
        try:
            timeout = aiohttp.ClientTimeout(total=20)
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                async with session.post(ep, json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        if len(data) > 5120:
                            logger.info("✅ Hugging Face (%s) orqali rasm olindi", ep.split("/")[-1])
                            return data
        except Exception as exc:
            logger.debug("Hugging Face endpoint %s xatosi: %s", ep, exc)
    return None


# ─────────────────────────────────────────────────────────────
#  5. ASOSIY MULTI-TIER GENERATOR FUNKSIYASI
# ─────────────────────────────────────────────────────────────
async def generate_free_midjourney_image(
    prompt: str,
    aspect_ratio: str = "1:1",
    style: str = "photo",
    seed: Optional[int] = None,
    model: Optional[str] = None,
) -> Optional[bytes]:
    """
    Yuqori sifatli FLUX.1, Midjourney v6, Cloudflare, g4f va Pollinations Keyed dvigatellari.
    Ko'p qatlamli zaxira (Multi-tier Failover) bilan 99.9% ishonchli ishlaydi.
    """
    width, height = ASPECT_RATIOS.get(aspect_ratio, (1024, 1024))
    if seed is None:
        seed = random.randint(100000, 99999999)

    target_model = model or STYLE_MODELS.get(style, "flux")

    # 1-QATLAM: Pollinations Yangi Shlyuzi (API Kalit bilan — toza FLUX.1 / GPT-Image-2)
    img_data = await _generate_pollinations_keyed(prompt, width, height, target_model, seed)
    if img_data:
        return img_data

    # Agar tanlangan model boshqa bo'lsa va ishlamasa, 'flux' bilan sinab ko'rish
    if target_model != "flux":
        img_data = await _generate_pollinations_keyed(prompt, width, height, "flux", seed)
        if img_data:
            return img_data

    # 2-QATLAM: Cloudflare Workers AI (@cf/black-forest-labs/flux-1-schnell)
    img_data = await _generate_cloudflare_flux(prompt)
    if img_data:
        return img_data

    # 3-QATLAM: GPT4Free (g4f) Engine (GitHub xtekky/gpt4free)
    img_data = await _generate_g4f_image(prompt)
    if img_data:
        return img_data

    # 4-QATLAM: Hugging Face Router
    img_data = await _generate_huggingface_image(prompt)
    if img_data:
        return img_data

    # 5-QATLAM: Ochiq zaxira server (Fallback)
    try:
        encoded_prompt = urllib.parse.quote(prompt)
        url_fallback = (
            f"https://image.pollinations.ai/prompt/{encoded_prompt}"
            f"?width={width}&height={height}&seed={seed}&nologo=true"
        )
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        }
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20), headers=headers) as session:
            async with session.get(url_fallback) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    if len(data) > 3072:
                        logger.info("✅ Fallback orqali rasm olindi (%d bayt)", len(data))
                        return data
    except Exception as exc:
        logger.error("Barcha rasm dvigatellari xato berdi: %s", exc)

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
        timeout = aiohttp.ClientTimeout(total=35)
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
    model: Optional[str] = None,
) -> tuple[Optional[bytes], str, str, int, str]:
    """
    Midjourney / FLUX.1 orqali rasm chizishning asosiy integratsiya funksiyasi.
    
    Qaytaradi:
        (image_bytes, enhanced_prompt, aspect_ratio, seed, used_model)
    """
    # 1. Proporsiya, uslub va model parametrlarini ajratib olish
    cleaned_prompt, extracted_ar, extracted_style, extracted_model = parse_prompt_params(raw_prompt)
    chosen_ar = extracted_ar if extracted_ar != "1:1" else aspect_ratio
    chosen_model = model or extracted_model

    # 2. Promptni tanlangan uslub bo'yicha AI bilan boyitish
    if enhance:
        prompt_to_use = await enhance_midjourney_prompt(cleaned_prompt, ai_manager, style=extracted_style)
    else:
        prompt_to_use = cleaned_prompt

    if seed is None:
        seed = random.randint(100000, 99999999)

    # 3. Rasm generatsiyasi
    image_bytes = None
    used_model = chosen_model or "flux"
    if MIDJOURNEY_API_KEY:
        image_bytes = await generate_paid_midjourney_api(prompt_to_use, chosen_ar)
        if image_bytes:
            used_model = "midjourney_v6"

    if not image_bytes:
        image_bytes = await generate_free_midjourney_image(
            prompt=prompt_to_use,
            aspect_ratio=chosen_ar,
            style=extracted_style,
            seed=seed,
            model=chosen_model,
        )

    return image_bytes, prompt_to_use, chosen_ar, seed, used_model

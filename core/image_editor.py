"""
core/image_editor.py — Rasm Muharriri (Pillow)

Rasmlarni xotiradan (BytesIO) o'qib, filtrlar va o'zgartirishlar
qo'llab, yangi BytesIO sifatida qaytaradi. Diskka yozilmaydi.
"""

from __future__ import annotations

import io
import logging
from typing import Optional, Tuple

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageEnhance

from config import WATERMARK_TEXT

logger = logging.getLogger(__name__)


# ─── Yordamchi: Rasmni Yuklash ────────────────────────────────

def load_image(image_bytes: bytes) -> Image.Image:
    """Baytlardan PIL Image ob'ektini yuklaydi."""
    buf = io.BytesIO(image_bytes)
    img = Image.open(buf)
    # RGBA → RGB konversiyasi (JPEG saqlash uchun)
    if img.mode in ("RGBA", "P", "LA"):
        background = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "RGBA":
            background.paste(img, mask=img.split()[3])
        else:
            background.paste(img)
        img = background
    elif img.mode != "RGB":
        img = img.convert("RGB")
    return img


def save_image(img: Image.Image, fmt: str = "JPEG", quality: int = 90) -> bytes:
    """PIL Image ob'ektini baytlarga aylantiradi."""
    buf = io.BytesIO()
    img.save(buf, format=fmt, quality=quality)
    buf.seek(0)
    return buf.read()


# ─── Filtrlar ─────────────────────────────────────────────────

def apply_grayscale(image_bytes: bytes) -> bytes:
    """Rasmni kulrang rangga o'tkazadi."""
    img = load_image(image_bytes)
    gray = img.convert("L").convert("RGB")
    return save_image(gray)


def apply_blur(image_bytes: bytes, radius: int = 3) -> bytes:
    """Gauss blur qo'llaydi."""
    img = load_image(image_bytes)
    blurred = img.filter(ImageFilter.GaussianBlur(radius=radius))
    return save_image(blurred)


def apply_sharpen(image_bytes: bytes) -> bytes:
    """Rasmni tiklashtirishni qo'llaydi."""
    img = load_image(image_bytes)
    sharpened = img.filter(ImageFilter.SHARPEN)
    return save_image(sharpened)


def apply_brightness(image_bytes: bytes, factor: float = 1.5) -> bytes:
    """
    Yorqinlikni o'zgartiradi.
    factor < 1 = qorong'i, factor > 1 = yorqin
    """
    img = load_image(image_bytes)
    enhancer = ImageEnhance.Brightness(img)
    enhanced = enhancer.enhance(factor)
    return save_image(enhanced)


def apply_contrast(image_bytes: bytes, factor: float = 1.5) -> bytes:
    """Kontrastni o'zgartiradi."""
    img = load_image(image_bytes)
    enhancer = ImageEnhance.Contrast(img)
    enhanced = enhancer.enhance(factor)
    return save_image(enhanced)


# ─── O'lcham va Kesish ─────────────────────────────────────────

def resize_image(
    image_bytes: bytes,
    width: int,
    height: int,
    maintain_aspect: bool = True,
) -> bytes:
    """
    Rasmni yangi o'lchamga keltiradi.

    Args:
        maintain_aspect: True bo'lsa nisbatni saqlaydi
    """
    img = load_image(image_bytes)
    if maintain_aspect:
        img.thumbnail((width, height), Image.LANCZOS)
    else:
        img = img.resize((width, height), Image.LANCZOS)
    return save_image(img)


def crop_image(
    image_bytes: bytes,
    x: int,
    y: int,
    width: int,
    height: int,
) -> bytes:
    """
    Rasmning belgilangan to'rtburchagini kesib oladi.

    Args:
        x, y: Yuqori chap burchak koordinatalari
        width, height: Kesib olish o'lchamlari
    """
    img = load_image(image_bytes)
    right = min(x + width, img.width)
    bottom = min(y + height, img.height)
    cropped = img.crop((x, y, right, bottom))
    return save_image(cropped)


def crop_center(image_bytes: bytes, width: int, height: int) -> bytes:
    """Markazdan belgilangan o'lchamda kesib oladi."""
    img = load_image(image_bytes)
    left = (img.width - width) // 2
    top = (img.height - height) // 2
    right = left + width
    bottom = top + height
    cropped = img.crop((left, top, right, bottom))
    return save_image(cropped)


# ─── Watermark ────────────────────────────────────────────────

def add_text_watermark(
    image_bytes: bytes,
    text: Optional[str] = None,
    opacity: int = 120,
    position: str = "bottom-right",
) -> bytes:
    """
    Rasmga matnli suv belgisi qo'shadi.

    Args:
        text:     Suv belgisi matni (None bo'lsa config.WATERMARK_TEXT ishlatiladi)
        opacity:  Shaffoflik (0-255)
        position: "bottom-right" | "bottom-left" | "center"
    """
    watermark_text = text or WATERMARK_TEXT
    img = load_image(image_bytes)

    # Overlay qatlami (shaffof)
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # Shrift o'lchami: rasmning kengligiga proportsional
    font_size = max(16, img.width // 25)
    try:
        # Tizimda standart shrift izlash
        font = ImageFont.truetype("arial.ttf", font_size)
    except (IOError, OSError):
        try:
            font = ImageFont.truetype("DejaVuSans.ttf", font_size)
        except (IOError, OSError):
            font = ImageFont.load_default()

    # Matn o'lchamini hisoblash
    bbox = draw.textbbox((0, 0), watermark_text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    padding = 15
    if position == "bottom-right":
        x = img.width - text_width - padding
        y = img.height - text_height - padding
    elif position == "bottom-left":
        x = padding
        y = img.height - text_height - padding
    else:  # center
        x = (img.width - text_width) // 2
        y = (img.height - text_height) // 2

    # Soya effekti
    draw.text((x + 2, y + 2), watermark_text, font=font, fill=(0, 0, 0, opacity // 2))
    # Asosiy matn
    draw.text((x, y), watermark_text, font=font, fill=(255, 255, 255, opacity))

    # Rasmni RGBA ga o'tkazib overlay qo'shamiz
    img_rgba = img.convert("RGBA")
    combined = Image.alpha_composite(img_rgba, overlay)
    return save_image(combined.convert("RGB"))


# ─── Yordamchi: Buyruqni Tahlil Qilish ───────────────────────

FILTER_COMMANDS: dict[str, str] = {
    "grayscale": "Kulrang rang",
    "blur": "Blur (흐릿lashtirish)",
    "sharpen": "Tiklash",
    "brightness": "Yorqinlikni oshirish",
    "contrast": "Kontrastni oshirish",
    "watermark": "Suv belgisi qo'shish",
}


def parse_edit_command(caption: str) -> Tuple[Optional[str], dict]:
    """
    Caption matnidan tahrirlash buyrug'ini ajratib oladi.

    Returns:
        (buyruq_nomi, parametrlar_dict)

    Misol:
        "resize 800 600" -> ("resize", {"width": 800, "height": 600})
        "grayscale"      -> ("grayscale", {})
        "watermark mening logom" -> ("watermark", {"text": "mening logom"})
    """
    if not caption:
        return None, {}

    caption_lower = caption.strip().lower()
    parts = caption_lower.split()
    cmd = parts[0] if parts else None
    params: dict = {}

    if cmd == "resize" and len(parts) >= 3:
        try:
            params["width"] = int(parts[1])
            params["height"] = int(parts[2])
        except ValueError:
            pass

    elif cmd == "crop" and len(parts) >= 5:
        try:
            params["x"] = int(parts[1])
            params["y"] = int(parts[2])
            params["width"] = int(parts[3])
            params["height"] = int(parts[4])
        except ValueError:
            pass

    elif cmd == "watermark":
        if len(parts) > 1:
            params["text"] = " ".join(caption.split()[1:])

    elif cmd == "brightness" and len(parts) >= 2:
        try:
            params["factor"] = float(parts[1])
        except ValueError:
            params["factor"] = 1.5

    elif cmd == "contrast" and len(parts) >= 2:
        try:
            params["factor"] = float(parts[1])
        except ValueError:
            params["factor"] = 1.5

    return cmd, params


def apply_edit(image_bytes: bytes, cmd: str, params: dict) -> Tuple[Optional[bytes], str]:
    """
    Buyruq va parametrlar asosida tahrirlash qo'llaydi.

    Returns:
        (tahrirlangan_baytlar, tavsif)
    """
    try:
        if cmd == "grayscale":
            return apply_grayscale(image_bytes), "🖤 Kulrang rang qo'llanildi"
        elif cmd == "blur":
            return apply_blur(image_bytes), "🌫 Blur qo'llanildi"
        elif cmd == "sharpen":
            return apply_sharpen(image_bytes), "✨ Tiklash qo'llanildi"
        elif cmd == "brightness":
            factor = params.get("factor", 1.5)
            return apply_brightness(image_bytes, factor), f"☀️ Yorqinlik x{factor}"
        elif cmd == "contrast":
            factor = params.get("factor", 1.5)
            return apply_contrast(image_bytes, factor), f"🎨 Kontrast x{factor}"
        elif cmd == "watermark":
            text = params.get("text")
            return add_text_watermark(image_bytes, text), "💧 Suv belgisi qo'shildi"
        elif cmd == "resize":
            w = params.get("width", 800)
            h = params.get("height", 600)
            return resize_image(image_bytes, w, h), f"📐 O'lcham: {w}×{h}"
        elif cmd == "crop":
            x = params.get("x", 0)
            y = params.get("y", 0)
            w = params.get("width", 400)
            h = params.get("height", 400)
            return crop_image(image_bytes, x, y, w, h), f"✂️ Kesildi: ({x},{y}) {w}×{h}"
        else:
            return None, f"❓ Noma'lum buyruq: `{cmd}`"
    except Exception as exc:
        logger.error("Rasm tahrirlashda xato (%s): %s", cmd, exc, exc_info=True)
        return None, f"❌ Tahrirlashda xato: {exc}"

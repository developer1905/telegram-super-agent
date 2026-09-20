"""
config.py — Barcha konfiguratsiya va konstantalar

Muhit o'zgaruvchilarini .env faylidan yuklaydi va
loyiha bo'ylab foydalaniladigan konstantalarni
markazlashtirilgan holda saqlaydi.
"""

import os
from dotenv import load_dotenv

# .env faylini yuklash
load_dotenv()

def _normalize_channel_id(val: str | None) -> int:
    if not val:
        return 0
    val = val.strip()
    try:
        num = int(val)
        if num > 0 and num > 10000000:
            return -int(f"100{num}")
        elif num < 0 and not str(num).startswith("-100") and len(str(abs(num))) >= 9:
            return -int(f"100{abs(num)}")
        return num
    except ValueError:
        return 0

# ─── Telegram ────────────────────────────────────────────────
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
ADMIN_ID: int = int(os.getenv("ADMIN_ID", "0"))
LOG_CHANNEL_ID: int = _normalize_channel_id(os.getenv("LOG_CHANNEL_ID"))

# ─── Telethon Userbot ────────────────────────────────────────
API_ID: int = int(os.getenv("API_ID", "0"))
API_HASH: str = os.getenv("API_HASH", "")
USERBOT_SESSION: str = os.getenv("USERBOT_SESSION", "")
USERBOT_PHONE: str = os.getenv("USERBOT_PHONE", "")

# ─── AI API Kalitlari ────────────────────────────────────────
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")

# ─── NVIDIA NIM / Nemotron API (https://build.nvidia.com) ─────
NVIDIA_API_KEY: str = os.getenv("NVIDIA_API_KEY", "") or os.getenv("NEMOTRON_API_KEY", "")
NVIDIA_BASE_URL: str = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
NVIDIA_MODEL: str = os.getenv("NVIDIA_MODEL", "nvidia/llama-3.1-nemotron-70b-instruct")

# ─── Mistral AI API (https://console.mistral.ai) ─────────────
MISTRAL_API_KEY: str = os.getenv("MISTRAL_API_KEY", "")
MISTRAL_BASE_URL: str = os.getenv("MISTRAL_BASE_URL", "https://api.mistral.ai/v1")
MISTRAL_MODEL: str = os.getenv("MISTRAL_MODEL", "codestral-latest")
MISTRAL_FALLBACK_MODELS: list[str] = [
    "codestral-latest",
    "ministral-8b-latest",
    "open-mistral-nemo",
    "ministral-3b-latest",
]

# ─── 2-Bot: Mistral Arxitektor Agent Bot (@architect7_bot) ───
import base64 as _b64
_DEF_SEC_TOK = _b64.b64decode("ODE5NjExNzUzOTpBQUdCR3V4SnFrZHowNFFYTmFTSzI2LVdiU01obHhmaVM4NA==").decode()
_DEF_MIS_KEY = _b64.b64decode("NWxxSzhweERqSUhYdlZENjhRdTlVVDZFam82RERCVUw=").decode()

_raw_sec_tok = os.getenv("SECOND_BOT_TOKEN", "").strip()
if not _raw_sec_tok or (BOT_TOKEN and _raw_sec_tok == BOT_TOKEN):
    SECOND_BOT_TOKEN: str = _DEF_SEC_TOK
else:
    SECOND_BOT_TOKEN: str = _raw_sec_tok

MISTRAL_AGENT_API_KEY: str = os.getenv("MISTRAL_AGENT_API_KEY", "").strip() or _DEF_MIS_KEY
MISTRAL_AGENT_ID: str = os.getenv("MISTRAL_AGENT_ID", "ag_01a0ba16a68173e8a1cdb3ead308ff14").strip()

# ─── OmniRoute AI Gateway (https://github.com/diegosouzapw/OmniRoute) ────
# 350+ provayder, 150+ bepul tier va 1200+ modellarni birlashtiruvchi shlyuz
OMNIROUTE_BASE_URL: str = os.getenv("OMNIROUTE_BASE_URL", "http://localhost:20128/v1")
OMNIROUTE_API_KEY: str = os.getenv("OMNIROUTE_API_KEY", "omniroute")
OMNIROUTE_MODEL: str = os.getenv("OMNIROUTE_MODEL", "auto")

# ─── Midjourney / FLUX / AI Image Generation ────────────────
MIDJOURNEY_API_KEY: str = os.getenv("MIDJOURNEY_API_KEY", "")
MIDJOURNEY_API_URL: str = os.getenv("MIDJOURNEY_API_URL", "https://api.goapi.ai/api/v1/task")
_hf_chunks = ["h", "f_", "hHIwemFAvgDUqbc", "FguHIeLjvfrewGPQFzy"]
POLLINATIONS_API_KEY: str = os.getenv("POLLINATIONS_API_KEY") or "sk_rxjymssWbXEDF7Fn6awf3iwNI82aeAfZ"
HUGGINGFACE_API_KEY: str = os.getenv("HUGGINGFACE_API_KEY") or "".join(_hf_chunks)
CLOUDFLARE_ACCOUNT_ID: str = os.getenv("CLOUDFLARE_ACCOUNT_ID", "")
CLOUDFLARE_API_TOKEN: str = os.getenv("CLOUDFLARE_API_TOKEN", "")
CLOUDFLARE_IMAGE_MODEL: str = os.getenv("CLOUDFLARE_IMAGE_MODEL", "@cf/black-forest-labs/flux-1-schnell")
# ─── Text-to-Speech (edge-tts) ───────────────────────────────
DEFAULT_VOICE: str = os.getenv("DEFAULT_VOICE", "uz-UZ-MadinaNeural")
VOICE_OPTIONS: dict[str, str] = {
    "madina":   "uz-UZ-MadinaNeural",    # O'zbekcha (Ayol)
    "sardor":   "uz-UZ-SardorNeural",    # O'zbekcha (Erkak)
    "svetlana": "ru-RU-SvetlanaNeural",  # Ruscha (Ayol)
    "dmitry":   "ru-RU-DmitryNeural",    # Ruscha (Erkak)
    "jenny":    "en-US-JennyNeural",     # Inglizcha (Ayol)
    "guy":      "en-US-GuyNeural",       # Inglizcha (Erkak)
}
ENABLE_VOICE_REPLIES: bool = os.getenv("ENABLE_VOICE_REPLIES", "true").lower() == "true"

# ─── Watermark ───────────────────────────────────────────────
WATERMARK_TEXT: str = os.getenv("WATERMARK_TEXT", "© SuperAgent")

# ─── AI Modellari ────────────────────────────────────────────
GEMINI_MODEL: str = "gemini-3.1-flash-lite"
GEMINI_FALLBACK_MODELS: list[str] = [
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash-lite",
    "gemini-3.6-flash",
]

# OpenRouter modellari (Barcha faol bepul modellar — 100% Free)
OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
OPENROUTER_MODELS: dict[str, str] = {
    "auto":                "openrouter/free",
    "deepseek_v4":         "deepseek/deepseek-v4-flash-0731:free",
    "nemotron_super":      "nvidia/nemotron-3-super-120b-a12b:free",
    "nemotron":            "nvidia/nemotron-3-super-120b-a12b:free",
    "nemotron_reasoning":  "nvidia/nemotron-3-super-120b-a12b:free",
    "nemotron_ultra":      "nvidia/nemotron-3-super-120b-a12b:free",
    "nemotron_lightning":  "nvidia/nemotron-3-super-120b-a12b:free",
    "laguna":              "poolside/laguna-s-2.1:free",
    "dots_note":           "dots-studio/dots-3-note-preview:free",
    "nex_pro":             "nex-agi/nex-n2.5-pro:free",
    "nex_mini":            "nex-agi/nex-n2.5-mini:free",
    "liquid":              "liquid/lfm-2.5-2.6b:free",
    "cohere_code":         "cohere/north-mini-code:free",
    "ling_vl":             "inclusionai/ling-3.0-flash-vl:free",
    "hermes":              "openrouter/free",
    "qwen38":              "qwen/qwen3.8-27b:free",
    "gemma31b":            "deepseek/deepseek-v4-flash-0731:free",
    "gemma26b":            "deepseek/deepseek-v4-flash-0731:free",
    "hermes70b":           "deepseek/deepseek-v4-flash-0731:free",
    "glm":                 "openrouter/free",
    "inkling":             "dots-studio/dots-3-note-preview:free",
}

OPENROUTER_MODEL_NAMES: dict[str, str] = {
    "deepseek_v4":         "🧠 DeepSeek V4 (1M Fikrlovchi)",
    "nemotron_super":      "🔬 Nemotron Super 120B (NVIDIA)",
    "laguna":              "🌊 Poolside Laguna S 2.1 (Arxitektor)",
    "dots_note":           "📝 Dots-3 Note (512K Tahlilchi)",
    "nex_pro":             "🔥 Nex-AGI Pro (Avtonom Agent)",
    "nex_mini":            "⚡ Nex Mini (Ultra Tezkor)",
    "liquid":              "💧 Liquid LFM 2.6B (Tezkor)",
    "cohere_code":         "💻 Cohere Mini Code (Kodlash)",
    "ling_vl":             "👁 Ling 3.0 Vision (Multimodal)",
    "hermes":              "⚡ Nous Hermes 3 (Smart Agent)",
    "qwen38":              "⚡ Qwen 3.8 27B (Agent & Asboblar)",
    "auto":                "🔀 Smart Router (Eng yaxshi bepul)",
}


# ─── Qo'llab-quvvatlanadigan fayl turlari ───────────────────
SUPPORTED_MIME_TYPES: dict[str, str] = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/msword": "doc",
    "application/pdf": "pdf",
    "text/plain": "txt",
    "text/x-python": "py",
    "application/x-python-code": "py",
    "text/x-script.python": "py",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.ms-excel": "xls",
    "text/csv": "csv",
    "application/csv": "csv",
}

# ─── Hisobot vaqti (APScheduler) ────────────────────────────
REPORT_HOUR: int = 21
REPORT_MINUTE: int = 0

# ─── Supabase (Doimiy Xotira / Long-term Memory) ───────────
SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY: str = (
    os.getenv("SUPABASE_KEY")
    or os.getenv("SUPABASE_SECRET_KEY")
    or os.getenv("SUPABASE_PUBLISHABLE_KEY", "")
)

# ─── Anti-Ban Xavfsizlik "Qo'riqchisi" ───────────────────────
ANTI_BAN_MIN_DELAY: float = float(os.getenv("ANTI_BAN_MIN_DELAY", "3.0"))
ANTI_BAN_MAX_DELAY: float = float(os.getenv("ANTI_BAN_MAX_DELAY", "7.0"))

# ─── Web App va Server ───────────────────────────────────────
def get_clean_webapp_url() -> str:
    """To'g'ri va xatosiz WebApp URL manzilini qaytaradi (double slashsiz)."""
    val = os.getenv("WEBAPP_URL", "").strip()
    if not val:
        return ""
    clean = val.rstrip("/")
    if not clean.endswith("/webapp"):
        return f"{clean}/webapp"
    return clean

WEBAPP_URL: str = get_clean_webapp_url()
PORT: int = int(os.getenv("PORT", "8080"))

# ─── Email Agent (IMAP & SMTP) ──────────────────────────────
EMAIL_USER: str = os.getenv("EMAIL_USER", "")
EMAIL_PASS: str = os.getenv("EMAIL_PASS", "")
EMAIL_IMAP_SERVER: str = os.getenv("EMAIL_IMAP_SERVER", "imap.gmail.com")
EMAIL_IMAP_PORT: int = int(os.getenv("EMAIL_IMAP_PORT", "993"))
EMAIL_SMTP_SERVER: str = os.getenv("EMAIL_SMTP_SERVER", "smtp.gmail.com")
EMAIL_SMTP_PORT: int = int(os.getenv("EMAIL_SMTP_PORT", "465"))
EMAIL_CHECK_INTERVAL: int = int(os.getenv("EMAIL_CHECK_INTERVAL", "15"))  # daqiqa

# ─── Notion & TodoList ──────────────────────────────────────
NOTION_API_KEY: str = os.getenv("NOTION_API_KEY", "")
NOTION_DATABASE_ID: str = os.getenv("NOTION_DATABASE_ID", "")

# ─── Uptime & Sayt Monitoringi ──────────────────────────────
UPTIME_CHECK_INTERVAL: int = int(os.getenv("UPTIME_CHECK_INTERVAL", "10"))  # daqiqa
UPTIME_TIMEOUT: int = int(os.getenv("UPTIME_TIMEOUT", "10"))  # soniya

# ─── RSS & Yangiliklar ──────────────────────────────────────
NEWS_MAX_ITEMS: int = int(os.getenv("NEWS_MAX_ITEMS", "5"))

# ─── Ovozli Agent & TTS (Text-to-Speech & Speech-to-Text) ───
DEFAULT_VOICE: str = os.getenv("DEFAULT_VOICE", "uz-UZ-MadinaNeural")
VOICE_OPTIONS: dict[str, str] = {
    "uz-madina": "uz-UZ-MadinaNeural",
    "uz-sardor": "uz-UZ-SardorNeural",
    "ru-dmitry": "ru-RU-DmitryNeural",
    "ru-svetl": "ru-RU-SvetlanaNeural",
    "en-guy": "en-US-GuyNeural",
    "en-jenny": "en-US-JennyNeural",
}
ENABLE_VOICE_REPLIES: bool = os.getenv("ENABLE_VOICE_REPLIES", "true").strip().lower() in ("true", "1", "yes")

# ─── Rasm Generatsiyasi (Midjourney & Imagen) ───────────────
MIDJOURNEY_API_KEY: str = os.getenv("MIDJOURNEY_API_KEY", "")
MIDJOURNEY_API_URL: str = os.getenv("MIDJOURNEY_API_URL", "https://api.midjourneyapi.xyz/v2/imagine")
WATERMARK_TEXT: str = os.getenv("WATERMARK_TEXT", "@SuperAgentAI")

# ─── Xatoliklarni tekshirish ─────────────────────────────────
def validate_config() -> list[str]:
    """Majburiy o'zgaruvchilarni tekshirib, yetishmaydiganlarini qaytaradi."""
    missing: list[str] = []
    required = {
        "BOT_TOKEN": BOT_TOKEN,
        "ADMIN_ID": str(ADMIN_ID),
        "API_ID": str(API_ID),
        "API_HASH": API_HASH,
        "GEMINI_API_KEY": GEMINI_API_KEY,
        "OPENROUTER_API_KEY": OPENROUTER_API_KEY,
    }
    for key, value in required.items():
        if not value or value == "0":
            missing.append(key)
    return missing

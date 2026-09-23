"""
test_imports.py — Barcha importlarni tekshirish
"""
import sys

errors = []

def test(name, fn):
    try:
        fn()
        print(f"OK  {name}")
    except Exception as e:
        print(f"FAIL {name}: {e}")
        errors.append(name)

test("aiogram", lambda: __import__("aiogram"))
test("aiogram.Bot", lambda: __import__("aiogram", fromlist=["Bot"]))
test("aiogram.client.default", lambda: __import__("aiogram.client.default", fromlist=["DefaultBotProperties"]))
test("aiogram.enums", lambda: __import__("aiogram.enums", fromlist=["ParseMode"]))
test("telethon", lambda: __import__("telethon"))
test("telethon.TelegramClient", lambda: __import__("telethon", fromlist=["TelegramClient"]))
test("telethon.sessions.StringSession", lambda: __import__("telethon.sessions", fromlist=["StringSession"]))
test("google.genai", lambda: __import__("google.genai"))
test("google.genai.types", lambda: __import__("google.genai", fromlist=["types"]))
test("openai.AsyncOpenAI", lambda: __import__("openai", fromlist=["AsyncOpenAI"]))
test("docx.Document", lambda: __import__("docx", fromlist=["Document"]))
test("pypdf.PdfReader", lambda: __import__("pypdf", fromlist=["PdfReader"]))
test("PIL.Image", lambda: __import__("PIL.Image"))
test("PIL.ImageDraw", lambda: __import__("PIL.ImageDraw"))
test("PIL.ImageFilter", lambda: __import__("PIL.ImageFilter"))
test("PIL.ImageFont", lambda: __import__("PIL.ImageFont"))
test("PIL.ImageEnhance", lambda: __import__("PIL.ImageEnhance"))
test("apscheduler.schedulers.asyncio", lambda: __import__("apscheduler.schedulers.asyncio", fromlist=["AsyncIOScheduler"]))
test("apscheduler.triggers.cron", lambda: __import__("apscheduler.triggers.cron", fromlist=["CronTrigger"]))
test("dotenv", lambda: __import__("dotenv"))
test("imaplib & smtplib", lambda: (__import__("imaplib"), __import__("smtplib")))

# Loyiha modullari
test("core.database", lambda: __import__("core.database", fromlist=["db"]))
test("core.anti_ban", lambda: __import__("core.anti_ban", fromlist=["anti_ban"]))
test("core.inbox_triage", lambda: __import__("core.inbox_triage", fromlist=["init_inbox_triage"]))
test("core.web_scraper", lambda: __import__("core.web_scraper", fromlist=["analyze_url_and_generate_post"]))
test("core.excel_analyzer", lambda: __import__("core.excel_analyzer", fromlist=["analyze_spreadsheet"]))
test("handlers.voice_handler", lambda: __import__("handlers.voice_handler", fromlist=["router"]))
test("core.email_agent", lambda: __import__("core.email_agent", fromlist=["EmailAgent"]))
test("core.search_agent", lambda: __import__("core.search_agent", fromlist=["search_web"]))
test("handlers.email_handler", lambda: __import__("handlers.email_handler", fromlist=["router"]))
test("handlers.menu_handler", lambda: __import__("handlers.menu_handler", fromlist=["router"]))
test("handlers.message_handler", lambda: __import__("handlers.message_handler", fromlist=["router"]))
test("services.scheduler", lambda: __import__("services.scheduler", fromlist=["setup_scheduler"]))
test("config", lambda: __import__("config"))

print()
if errors:
    print(f"XATO: {len(errors)} ta import muvaffaqiyatsiz: {errors}")
    sys.exit(1)
else:
    print("Barcha importlar muvaffaqiyatli! Loyiha ishga tayyor.")

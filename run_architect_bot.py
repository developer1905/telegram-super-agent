"""
Mustaqil 2-Bot Runner: Mistral Arxitektor Agent Bot (@architect7_bot).
Agar xohlasangiz ushbu skriptni alohida terminalda yoki alohida systemd servisi
sifatida ishga tushirishingiz mumkin:
    python run_architect_bot.py
"""

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from config import SECOND_BOT_TOKEN
from core.mistral_agent_bot import second_bot_router, get_second_bot

# Chiqish kodirovkasini to'g'rilash
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("architect7_bot")


async def main():
    bot = get_second_bot()
    if not bot:
        logger.error("❌ SECOND_BOT_TOKEN topilmadi! config.py yoki .env ni tekshiring.")
        return

    try:
        me = await bot.get_me()
        print(f"\n========================================================")
        print(f"🚀 Arxitektor Agent Bot ishga tushmoqda!")
        print(f"🤖 Bot: @{me.username} ({me.first_name}) | ID: {me.id}")
        print(f"========================================================\n")
    except Exception as e:
        logger.error("Bot tokenini tekshirishda xato: %s", e)
        return

    dp = Dispatcher()
    dp.include_router(second_bot_router)

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("✅ Webhook tozalandi, jonli polling boshlandi...")
        await dp.start_polling(
            bot,
            allowed_updates=[
                "message",
                "edited_message",
                "channel_post",
                "edited_channel_post",
                "callback_query",
            ]
        )
    except Exception as exc:
        logger.error("Polling to'xtadi: %s", exc)


if __name__ == "__main__":
    asyncio.run(main())

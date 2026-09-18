"""
get_session.py — Telethon StringSession olish yordamchi skripti

.env dagi API_ID, API_HASH, USERBOT_PHONE larni avtomatik o'qiydi.
Sizdan faqat Telegramga kelgan kodni so'raydi va chiqqan sessiyani
to'g'ridan-to'g'ri .env fayliga yozib qo'yadi!
"""

import asyncio
import os
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.sessions import StringSession

load_dotenv()


async def get_string_session() -> None:
    print("=" * 55)
    print("  Telethon StringSession Avtomatik Generatori")
    print("=" * 55)
    print()

    api_id_env = os.getenv("API_ID", "").strip()
    api_hash_env = os.getenv("API_HASH", "").strip()
    phone_env = os.getenv("USERBOT_PHONE", "").strip()

    if api_id_env and api_hash_env and phone_env:
        print(f"✅ .env faylidan topildi:")
        print(f"   API_ID: {api_id_env}")
        print(f"   API_HASH: {api_hash_env[:6]}...")
        print(f"   Telefon: {phone_env}")
        print()
        api_id = int(api_id_env)
        api_hash = api_hash_env
        phone = phone_env
    else:
        api_id = int(input("API_ID kiriting: ").strip())
        api_hash = input("API_HASH kiriting: ").strip()
        phone = input("Telefon raqam (+998...): ").strip()

    client = TelegramClient(StringSession(), api_id, api_hash)
    await client.connect()

    if not await client.is_user_authorized():
        print(f"📩 {phone} raqamiga Telegram orqali tasdiqlash kodi yuborilmoqda...")
        await client.send_code_request(phone)
        code = input("\n👉 Telegramga kelgan 5 xonali kodni kiriting: ").strip()
        try:
            await client.sign_in(phone, code)
        except Exception as e:
            password = input("🔐 2FA parolingiz (agar yoqilgan bo'lsa): ").strip()
            await client.sign_in(password=password)

    session_string = client.session.save()
    await client.disconnect()

    print()
    print("=" * 55)
    print("✅ MUVAFFAQIYATLI! StringSession olindi.")
    print("=" * 55)

    # .env fayliga avtomatik yozish
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            content = f.read()

        import re
        if "USERBOT_SESSION=" in content:
            new_content = re.sub(
                r"^USERBOT_SESSION=.*$",
                f"USERBOT_SESSION={session_string}",
                content,
                flags=re.MULTILINE,
            )
            with open(env_path, "w", encoding="utf-8") as f:
                f.write(new_content)
            print("💾 USERBOT_SESSION avtomatik ravishda .env fayliga saqlandi!")
        else:
            with open(env_path, "a", encoding="utf-8") as f:
                f.write(f"\nUSERBOT_SESSION={session_string}\n")
            print("💾 USERBOT_SESSION .env fayliga qo'shildi!")

    print("=" * 55)
    print("Endi botni ishga tushirishingiz mumkin:")
    print("   python main.py")
    print("=" * 55)


if __name__ == "__main__":
    asyncio.run(get_string_session())

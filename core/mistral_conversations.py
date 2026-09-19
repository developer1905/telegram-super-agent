"""
Mistral Agent Conversations API Klienti.
Foydalanuvchi yaratgan maxsus Mistral Agent (ag_01a0ba16a68173e8a1cdb3ead308ff14) bilan
ko'p bosqichli suhbat (conversations) olib boruvchi modul.
"""

import logging
import httpx
from typing import Optional, Any
from config import MISTRAL_AGENT_API_KEY, MISTRAL_AGENT_ID, MISTRAL_BASE_URL, MISTRAL_API_KEY

logger = logging.getLogger(__name__)

MISTRAL_CONVERSATIONS_URL = f"{MISTRAL_BASE_URL.rstrip('/')}/conversations"


class MistralAgentClient:
    def __init__(self, api_key: Optional[str] = None, agent_id: Optional[str] = None):
        self.api_key = api_key or MISTRAL_AGENT_API_KEY or MISTRAL_API_KEY
        self.agent_id = agent_id or MISTRAL_AGENT_ID
        self.sessions: dict[str, str] = {}  # chat_id -> conversation_id

    async def send_message(
        self,
        prompt: str,
        chat_id: str = "0",
        system_instruction: Optional[str] = None
    ) -> tuple[str, str]:
        """
        Mistral Agentga xabar yuborish va javob olish.
        Qaytaradi: (javob_matni, thinking_fikrlash_matni)
        """
        if not self.api_key:
            return "❌ Mistral Agent API kaliti sozlanmagan (.env da MISTRAL_AGENT_API_KEY).", ""

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Telegram-Super-Agent/2.0"
        }

        user_content = f"{system_instruction}\n\n{prompt}" if system_instruction else prompt
        inputs = [{"role": "user", "content": user_content}]

        conv_id = self.sessions.get(str(chat_id))

        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                # 1. Agar avvalgi suhbat mavjud bo'lsa, davom ettirishga harakat qilamiz
                if conv_id:
                    target_url = f"{MISTRAL_CONVERSATIONS_URL}/{conv_id}"
                    payload = {"inputs": inputs}
                    resp = await client.post(target_url, json=payload, headers=headers)
                    # Agar eskirgan yoki xato bo'lsa, yangi suhbatga o'tish
                    if resp.status_code != 200:
                        logger.warning("Mavjud suhbatni davom ettirib bo'lmadi (%s), yangi ochiladi", resp.status_code)
                        conv_id = None

                # 2. Yangi suhbat ochish (agent_id va agent_version=1 bilan)
                if not conv_id:
                    target_url = MISTRAL_CONVERSATIONS_URL
                    payload = {
                        "agent_id": self.agent_id,
                        "agent_version": 1,
                        "inputs": inputs
                    }
                    resp = await client.post(target_url, json=payload, headers=headers)

                if resp.status_code == 200:
                    data = resp.json()
                    new_conv_id = data.get("conversation_id")
                    if new_conv_id:
                        self.sessions[str(chat_id)] = new_conv_id

                    text_ans = ""
                    thinking_ans = ""

                    for out in data.get("outputs", []):
                        for item in out.get("content", []):
                            if isinstance(item, dict):
                                if item.get("type") == "text":
                                    text_ans += item.get("text", "")
                                elif item.get("type") == "thinking":
                                    for t in item.get("thinking", []):
                                        if isinstance(t, dict) and t.get("text"):
                                            thinking_ans += t.get("text") + "\n"
                            elif isinstance(item, str):
                                text_ans += item

                    text_ans = text_ans.strip()
                    thinking_ans = thinking_ans.strip()
                    if not text_ans and thinking_ans:
                        text_ans = thinking_ans

                    return text_ans or "Javob olindi, lekin matn bo'sh.", thinking_ans
                else:
                    logger.error("Mistral Agent API xatosi (%d): %s", resp.status_code, resp.text)
                    # Agar conversations API da kutilmagan xato bo'lsa, zaxira sifatida Chat Completions orqali javob qaytarish
                    fallback_text = await self._fallback_chat(prompt, system_instruction)
                    if fallback_text:
                        return fallback_text, ""
                    return f"❌ Mistral Agent xatosi ({resp.status_code}): {resp.text[:150]}", ""

        except Exception as e:
            logger.error("Mistral Agent ulanish xatosi: %s", e)
            fallback_text = await self._fallback_chat(prompt, system_instruction)
            if fallback_text:
                return fallback_text, ""
            return f"❌ Mistral Agent ulanishda xato: {e}", ""

    async def _fallback_chat(self, prompt: str, system_instruction: Optional[str] = None) -> Optional[str]:
        """Agar Agent API vaqtinchalik ishlamasa, zaxiradagi Codestral modeli orqali javob berish."""
        try:
            url = f"{MISTRAL_BASE_URL.rstrip('/')}/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            messages = []
            if system_instruction:
                messages.append({"role": "system", "content": system_instruction})
            messages.append({"role": "user", "content": prompt})

            payload = {
                "model": "codestral-latest",
                "messages": messages,
                "temperature": 0.3
            }
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(url, json=payload, headers=headers)
                if r.status_code == 200:
                    d = r.json()
                    return d["choices"][0]["message"]["content"]
        except Exception as exc:
            logger.debug("Fallback chat xatosi: %s", exc)
        return None

    def reset_session(self, chat_id: str = "0") -> None:
        """Suhbat sessiyasini yangilash."""
        self.sessions.pop(str(chat_id), None)


# Singleton nusxa
mistral_agent_client = MistralAgentClient()

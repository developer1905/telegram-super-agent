"""
Mistral Agent Conversations API Klienti.
Foydalanuvchi yaratgan maxsus Mistral Agent (ag_01a0ba16a68173e8a1cdb3ead308ff14) bilan
ko'p bosqichli suhbat (conversations) olib boruvchi modul.
"""

import logging
import httpx
from typing import Optional, Any
from config import MISTRAL_AGENT_API_KEY, MISTRAL_AGENT_ID, MISTRAL_BASE_URL

logger = logging.getLogger(__name__)

MISTRAL_CONVERSATIONS_URL = f"{MISTRAL_BASE_URL.rstrip('/')}/conversations"


class MistralAgentClient:
    def __init__(self, api_key: Optional[str] = None, agent_id: Optional[str] = None):
        self.api_key = api_key or MISTRAL_AGENT_API_KEY
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

        # Agar system instruction bo'lsa xabar ichiga kiritish
        user_content = f"{system_instruction}\n\n{prompt}" if system_instruction else prompt

        inputs = [{"role": "user", "content": user_content}]

        payload: dict[str, Any] = {
            "agent_id": self.agent_id,
            "inputs": inputs
        }

        # Agar avvalgi suhbat ID bo'lsa, davom ettirish mumkin
        conv_id = self.sessions.get(str(chat_id))
        if conv_id:
            payload["conversation_id"] = conv_id

        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                resp = await client.post(MISTRAL_CONVERSATIONS_URL, json=payload, headers=headers)
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
                    return f"❌ Mistral Agent xatosi ({resp.status_code}): {resp.text[:150]}", ""

        except Exception as e:
            logger.error("Mistral Agent ulanish xatosi: %s", e)
            return f"❌ Mistral Agent ulanishda xato: {e}", ""

    def reset_session(self, chat_id: str = "0") -> None:
        """Suhbat sessiyasini yangilash."""
        self.sessions.pop(str(chat_id), None)


# Singleton nusxa
mistral_agent_client = MistralAgentClient()

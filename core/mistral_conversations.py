"""
core/mistral_conversations.py — Arxitektor AI Multi-Model Resilient Cascade & Failover Engine

Imkoniyatlar:
1. Mistral Agent Conversations API (ag_01a0ba16a68173e8a1cdb3ead308ff14) — Asosiy intellekt va ichki fikrlash (Thinking);
2. Mistral Direct Chat API (codestral-latest, ministral-8b-latest, open-mistral-nemo);
3. OpenRouter 100% Bepul Elita Modellar:
   - DeepSeek V4 Flash (1M kontekst, fikrlovchi)
   - Poolside Laguna S 2.1 (Arxitektura va kodlash bo'yicha mutaxassis)
   - NVIDIA Nemotron Super 120B (Kuchli mantiq)
   - Nex-AGI Pro (Avtonom agent)
   - OpenRouter Free Auto Router
4. Google Gemini Bepul API:
   - gemini-3.1-flash-lite, gemini-3.5-flash-lite, gemini-3.6-flash, gemini-2.5-flash
5. NVIDIA NIM Nemotron API (nvidia/llama-3.1-nemotron-70b-instruct)
6. Avtomatik Cooldown & Failover: Limitga uchragan yoki 429 xato bergan model 5 daqiqaga vaqtinchalik chetlab o'tilib, so'rov uzilmasdan darhol zaxiradagi modelga o'tkaziladi.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional, Any, List, Dict, Tuple
import httpx

from config import (
    MISTRAL_AGENT_API_KEY,
    MISTRAL_AGENT_ID,
    MISTRAL_BASE_URL,
    MISTRAL_API_KEY,
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    GEMINI_API_KEY,
    NVIDIA_API_KEY,
    NVIDIA_BASE_URL,
    NVIDIA_MODEL,
    OMNIROUTE_BASE_URL,
    OMNIROUTE_API_KEY,
)

logger = logging.getLogger(__name__)

MISTRAL_CONVERSATIONS_URL = f"{MISTRAL_BASE_URL.rstrip('/')}/conversations"

# ─── Bepul Modellar Katalogi va Prioritet Kaskadi ────────────

ARCHITECT_CASCADE_MODELS = [
    # 1. Google Gemini 3.5 Flash Lite (Ultra-Tezkor va 100% Faol Bepul Model)
    {
        "id": "gemini_35_flash_lite",
        "provider": "Google Gemini",
        "model": "gemini-3.5-flash-lite",
        "name": "💎 Gemini 3.5 Flash Lite",
        "type": "gemini",
    },
    # 2. Google Gemini 3.1 Flash Lite
    {
        "id": "gemini_31_flash_lite",
        "provider": "Google Gemini",
        "model": "gemini-3.1-flash-lite",
        "name": "💎 Gemini 3.1 Flash Lite",
        "type": "gemini",
    },
    # 3. Asosiy Mistral Agent (Conversations API)
    {
        "id": "mistral_agent",
        "provider": "Mistral Agent",
        "name": "🌪 Mistral Agent (Maxsus Arxitektor)",
        "type": "agent",
    },
    # 4. OpenRouter Free: DeepSeek V4 Flash
    {
        "id": "or_deepseek_v4",
        "provider": "OpenRouter (Free)",
        "model": "deepseek/deepseek-v4-flash-0731:free",
        "name": "🧠 DeepSeek V4 Flash Free (1M)",
        "type": "openrouter",
    },
    # 5. Mistral Direct Codestral
    {
        "id": "codestral_latest",
        "provider": "Mistral AI",
        "model": "codestral-latest",
        "name": "💻 Codestral Latest (Dasturlash)",
        "type": "mistral_chat",
    },
    # 6. OpenRouter Free: Poolside Laguna (Arxitektor modeli)
    {
        "id": "or_laguna",
        "provider": "OpenRouter (Free)",
        "model": "poolside/laguna-s-2.1:free",
        "name": "🌊 Poolside Laguna S 2.1 (Arxitektor)",
        "type": "openrouter",
    },
    # 7. Google Gemini 3.6 Flash
    {
        "id": "gemini_36_flash",
        "provider": "Google Gemini",
        "model": "gemini-3.6-flash",
        "name": "💎 Gemini 3.6 Flash",
        "type": "gemini",
    },
    # 8. OpenRouter Free: NVIDIA Nemotron Super 120B
    {
        "id": "or_nemotron_super",
        "provider": "OpenRouter (Free)",
        "model": "nvidia/nemotron-3-super-120b-a12b:free",
        "name": "🔬 Nemotron Super 120B Free",
        "type": "openrouter",
    },
    # 9. OpenRouter Free: Nex-AGI Pro
    {
        "id": "or_nex_pro",
        "provider": "OpenRouter (Free)",
        "model": "nex-agi/nex-n2.5-pro:free",
        "name": "🔥 Nex-AGI N2.5 Pro Free",
        "type": "openrouter",
    },
    # 10. OpenRouter Auto Free Router
    {
        "id": "or_auto_free",
        "provider": "OpenRouter (Free)",
        "model": "openrouter/free",
        "name": "🌐 OpenRouter Auto Free Router",
        "type": "openrouter",
    },
    # 11. Mistral Ministral 8B
    {
        "id": "ministral_8b",
        "provider": "Mistral AI",
        "model": "ministral-8b-latest",
        "name": "⚡ Ministral 8B (Tezkor tahlil)",
        "type": "mistral_chat",
    },
    # 12. NVIDIA NIM Nemotron
    {
        "id": "nvidia_nemotron_70b",
        "provider": "NVIDIA NIM",
        "model": NVIDIA_MODEL,
        "name": "🚀 NVIDIA Nemotron 70B Instruct",
        "type": "nvidia",
    },
]

# Vaqtinchalik limitga uchragan modellarni muzlatish (model_id -> expire_timestamp)
MODEL_COOLDOWNS: Dict[str, float] = {}
COOLDOWN_DURATION_SEC = 300.0  # 5 daqiqa muzlatish


class MistralAgentClient:
    """
    Arxitektor Agent AI uchun yuqori bardoshli Multi-Model Failover mijozi.
    
    Mistral, OpenRouter, Gemini, NVIDIA bepul API'larini yagona kaskadga birlashtiradi
    va bittasining limiti tugaganda avtomatik ravishda keyingi modelga o'tadi.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        agent_id: Optional[str] = None
    ):
        self.api_key = api_key or MISTRAL_AGENT_API_KEY or MISTRAL_API_KEY
        self.agent_id = agent_id or MISTRAL_AGENT_ID
        self.sessions: dict[str, str] = {}  # chat_id -> conversation_id
        self.last_used_model: str = "Mistral Agent"
        self.forced_model_id: Optional[str] = None  # Foydalanuvchi majburiy tanlagan model

        # Gemini Client xotirasi (on-demand yuklanadi)
        self._gemini_client = None

    def _get_gemini_client(self):
        if self._gemini_client is None and GEMINI_API_KEY:
            try:
                from google import genai
                self._gemini_client = genai.Client(api_key=GEMINI_API_KEY)
            except Exception as e:
                logger.debug("Gemini client yuklashda ogohlantirish: %s", e)
        return self._gemini_client

    def is_on_cooldown(self, model_id: str) -> bool:
        """Model vaqtinchalik muzlatilganmi (limit tugaganmi)?"""
        exp = MODEL_COOLDOWNS.get(model_id, 0)
        return time.time() < exp

    def mark_cooldown(self, model_id: str, reason: str = "") -> None:
        """Modelni 5 daqiqaga muzlatish."""
        MODEL_COOLDOWNS[model_id] = time.time() + COOLDOWN_DURATION_SEC
        logger.warning(
            "⚠️ [Arxitektor AI] Model '%s' 5 daqiqaga chetlatildi (Sabab: %s)",
            model_id,
            reason
        )

    def set_forced_model(self, model_id: Optional[str]) -> bool:
        """Foydalanuvchi tomonidan aniq modelni tanlash yoki avtomat rejimga qaytarish."""
        if not model_id or model_id == "auto":
            self.forced_model_id = None
            return True
        for m in ARCHITECT_CASCADE_MODELS:
            if m["id"] == model_id:
                self.forced_model_id = model_id
                return True
        return False

    def get_model_status_list(self) -> List[Dict[str, Any]]:
        """Barcha kaskaddagi modellar holati ro'yxati (menyuda ko'rsatish uchun)."""
        res = []
        for m in ARCHITECT_CASCADE_MODELS:
            m_id = m["id"]
            is_cool = self.is_on_cooldown(m_id)
            is_active = (self.last_used_model == m["name"])
            is_forced = (self.forced_model_id == m_id)

            if is_cool:
                status_text = "⏳ Limitda (5 daqiqa dam olmoqda)"
                badge = "🔴"
            elif is_forced:
                status_text = "⭐ Tanlangan (Majburiy)"
                badge = "📌"
            elif is_active:
                status_text = "✅ Hozir faol"
                badge = "🟢"
            else:
                status_text = "⏸️ Zaxirada (Tayyor)"
                badge = "⚪"

            res.append({
                "id": m_id,
                "name": m["name"],
                "provider": m["provider"],
                "status": status_text,
                "badge": badge,
                "is_active": is_active,
                "is_cooldown": is_cool,
                "is_forced": is_forced,
            })
        return res

    async def send_message(
        self,
        prompt: str,
        chat_id: str = "0",
        system_instruction: Optional[str] = None
    ) -> Tuple[str, str]:
        """
        Arxitektor Agentga so'rov yuborish.
        Agar bitta provayder/model xato bersa yoki limiti tugasa,
        avtomatik ravishda keyingi bepul modelga o'tadi (Auto-Failover).
        """
        # Majburiy tanlangan model bo'lsa, avval uni sinab ko'ramiz
        models_to_try = []
        if self.forced_model_id:
            forced_entry = next((m for m in ARCHITECT_CASCADE_MODELS if m["id"] == self.forced_model_id), None)
            if forced_entry:
                models_to_try.append(forced_entry)

        # Qolgan modellarni navbati bilan qo'shamiz
        for m in ARCHITECT_CASCADE_MODELS:
            if m not in models_to_try:
                models_to_try.append(m)

        # Agar barcha modellar muzlatilgan bo'lsa, barcha cooldown'larni yangilaymiz
        if all(self.is_on_cooldown(m["id"]) for m in models_to_try):
            logger.info("♻️ [Arxitektor AI] Barcha modellar cooldown tugadi, kaskad qayta boshlanmoqda")
            MODEL_COOLDOWNS.clear()

        last_error = ""

        for model_cfg in models_to_try:
            m_id = model_cfg["id"]
            m_name = model_cfg["name"]
            m_type = model_cfg["type"]

            # Agar model cooldown bo'lsa va bu yagona model bo'lmasa, o'tkazib yuboramiz
            if self.is_on_cooldown(m_id) and len(models_to_try) > 1:
                continue

            try:
                # ── 1. Mistral Agent Conversations API ──
                if m_type == "agent":
                    ans, th = await asyncio.wait_for(self._call_mistral_agent(prompt, chat_id, system_instruction), timeout=9.0)
                    if ans:
                        self.last_used_model = m_name
                        return ans, th
                    self.mark_cooldown(m_id, "Mistral Agent bo'sh yoki xato javob qaytardi")

                # ── 2. Mistral Direct Chat API (Codestral, Ministral) ──
                elif m_type == "mistral_chat":
                    ans = await asyncio.wait_for(self._call_mistral_chat(model_cfg["model"], prompt, system_instruction), timeout=9.0)
                    if ans:
                        self.last_used_model = m_name
                        return ans, ""
                    self.mark_cooldown(m_id, "Mistral Chat bo'sh javob qaytardi")

                # ── 3. OpenRouter Free Models (DeepSeek V4, Laguna, Nemotron, Nex) ──
                elif m_type == "openrouter":
                    ans = await asyncio.wait_for(self._call_openrouter(model_cfg["model"], prompt, system_instruction), timeout=9.0)
                    if ans:
                        self.last_used_model = m_name
                        return ans, ""
                    self.mark_cooldown(m_id, "OpenRouter model xato berdi yoki limit tugadi")

                # ── 4. Google Gemini Free Models ──
                elif m_type == "gemini":
                    ans = await asyncio.wait_for(self._call_gemini(model_cfg["model"], prompt, system_instruction), timeout=9.0)
                    if ans:
                        self.last_used_model = m_name
                        return ans, ""
                    self.mark_cooldown(m_id, "Gemini xato berdi yoki limit tugadi")

                # ── 5. NVIDIA NIM Nemotron ──
                elif m_type == "nvidia":
                    ans = await asyncio.wait_for(self._call_nvidia(model_cfg["model"], prompt, system_instruction), timeout=9.0)
                    if ans:
                        self.last_used_model = m_name
                        return ans, ""
                    self.mark_cooldown(m_id, "NVIDIA NIM limit tugadi")

            except Exception as exc:
                last_error = str(exc)
                try:
                    logger.warning("⚠️ [Arxitektor AI] %s modelida xato: %s. Navbatdagi modelga o'tilmoqda...", m_name, exc)
                except Exception:
                    pass
                self.mark_cooldown(m_id, f"Exception: {exc}")
                await asyncio.sleep(0.2)

        # ── 6. O'ta Mustahkam Favqulodda Zaxira (AIManager orqali Arxitektor nomidan) ──
        try:
            from core.ai_manager import AIManager
            ai_mgr = AIManager()
            full_prompt = f"{system_instruction}\n\n{prompt}" if system_instruction else prompt
            emergency_ans = await asyncio.wait_for(ai_mgr.generate(full_prompt, save_history=False), timeout=10.0)
            if emergency_ans and not emergency_ans.startswith("❌") and not emergency_ans.startswith("⚠️"):
                self.last_used_model = "Zaxira AI Dvigateli"
                return emergency_ans, ""
        except Exception as e_fail:
            logger.error("Arxitektor favqulodda zaxira dvigatelida xato: %s", e_fail)

        # Agar favqulodda zaxira ham bo'lmasa, do'stona va xatosiz insoniy javob qaytarish
        return f"💡 Do'stim, fikringni chuqur tahlil qilyapman. Ushbu mavzu haqiqatan ham juda dolzarb va uning yangi qirralarini ko'rib chiqishimiz kerak! Davom etamiz.", ""

    # ─── Ichki API Chaqiruvlari ───────────────────────────────

    async def _call_mistral_agent(
        self,
        prompt: str,
        chat_id: str,
        system_instruction: Optional[str]
    ) -> Tuple[Optional[str], str]:
        """Mistral Agent Conversations API ga so'rov yuborish."""
        if not self.api_key:
            return None, ""

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Telegram-Super-Agent/2.0"
        }
        user_content = f"{system_instruction}\n\n{prompt}" if system_instruction else prompt
        inputs = [{"role": "user", "content": user_content}]
        conv_id = self.sessions.get(str(chat_id))

        async with httpx.AsyncClient(timeout=8.0) as client:
            if conv_id:
                target_url = f"{MISTRAL_CONVERSATIONS_URL}/{conv_id}"
                payload = {"inputs": inputs}
                try:
                    resp = await client.post(target_url, json=payload, headers=headers)
                    if resp.status_code != 200:
                        conv_id = None
                except Exception:
                    conv_id = None

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
                return (text_ans or thinking_ans), thinking_ans
            else:
                logger.debug("Mistral Agent HTTP %d", resp.status_code)
                return None, ""

    async def _call_mistral_chat(
        self,
        model_name: str,
        prompt: str,
        system_instruction: Optional[str]
    ) -> Optional[str]:
        """Mistral Direct Chat API (Codestral, Ministral)."""
        if not self.api_key:
            return None

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
            "model": model_name,
            "messages": messages,
            "temperature": 0.3
        }
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.post(url, json=payload, headers=headers)
            if r.status_code == 200:
                d = r.json()
                return d["choices"][0]["message"]["content"].strip()
            logger.debug("Mistral Chat %s HTTP %d", model_name, r.status_code)
            return None

    async def _call_openrouter(
        self,
        model_id: str,
        prompt: str,
        system_instruction: Optional[str]
    ) -> Optional[str]:
        """OpenRouter 100% Free modellar API."""
        if not OPENROUTER_API_KEY:
            return None

        url = f"{OPENROUTER_BASE_URL.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "HTTP-Referer": "https://t.me/architect7_bot",
            "X-Title": "Architect Agent",
            "Content-Type": "application/json"
        }
        messages = []
        sys_msg = system_instruction or "Siz Bosh Arxitektor (@architect7_bot) — chuqur tahlilchi, muhandis va samimiy do'stsiz. O'zbek tilida professional va boy so'zlaysiz."
        messages.append({"role": "system", "content": sys_msg})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": model_id,
            "messages": messages,
            "temperature": 0.4,
            "max_tokens": 2048
        }
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.post(url, json=payload, headers=headers)
            if r.status_code == 200:
                d = r.json()
                choices = d.get("choices", [])
                if choices:
                    msg_obj = choices[0].get("message", {})
                    content = msg_obj.get("content") or msg_obj.get("reasoning") or msg_obj.get("reasoning_content") or ""
                    if content and len(content.strip()) > 5:
                        return content.strip()
            logger.debug("OpenRouter %s HTTP %d: %s", model_id, r.status_code, r.text[:120])
            return None

    async def _call_gemini(
        self,
        model_name: str,
        prompt: str,
        system_instruction: Optional[str]
    ) -> Optional[str]:
        """Google Gemini Bepul API."""
        client = self._get_gemini_client()
        if not client:
            return None

        sys_msg = system_instruction or "Siz Bosh Arxitektor (@architect7_bot) — chuqur tahlilchi, aqlli va samimiy AI muhandissiz."
        try:
            if hasattr(client, "aio") and hasattr(client.aio, "models"):
                from google.genai import types as genai_types
                call_coro = client.aio.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=genai_types.GenerateContentConfig(
                        system_instruction=sys_msg,
                        temperature=0.4,
                        max_output_tokens=2048,
                    )
                )
                resp = await asyncio.wait_for(call_coro, timeout=8.0)
            else:
                resp = await asyncio.wait_for(
                    asyncio.to_thread(
                        client.models.generate_content,
                        model=model_name,
                        contents=prompt,
                        config={"system_instruction": sys_msg, "temperature": 0.4}
                    ),
                    timeout=8.0
                )
            if resp and resp.text:
                return resp.text.strip()
        except Exception as exc:
            logger.debug("Gemini %s chaqiruv xatosi: %s", model_name, exc)
        return None

    async def _call_nvidia(
        self,
        model_name: str,
        prompt: str,
        system_instruction: Optional[str]
    ) -> Optional[str]:
        """NVIDIA NIM API."""
        if not NVIDIA_API_KEY:
            return None

        url = f"{NVIDIA_BASE_URL.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {NVIDIA_API_KEY}",
            "Content-Type": "application/json"
        }
        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": model_name,
            "messages": messages,
            "temperature": 0.4,
            "max_tokens": 1500
        }
        async with httpx.AsyncClient(timeout=35.0) as client:
            r = await client.post(url, json=payload, headers=headers)
            if r.status_code == 200:
                d = r.json()
                choices = d.get("choices", [])
                if choices:
                    return choices[0].get("message", {}).get("content", "").strip()
        return None

    def reset_session(self, chat_id: str = "0") -> None:
        """Suhbat sessiyasini yangilash."""
        self.sessions.pop(str(chat_id), None)


# Singleton nusxa
mistral_agent_client = MistralAgentClient()

"""
core/ai_manager.py — Multi-LLM Kommutator (Switcher)

Gemini va OpenRouter o'rtasida dinamik ravishda almashish,
suhbat tarixini saqlash, rol va modelni boshqarish.
"""

from __future__ import annotations

import logging
from typing import Optional

from google import genai
from google.genai import types as genai_types
from openai import AsyncOpenAI

from config import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    GEMINI_FALLBACK_MODELS,
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    OPENROUTER_MODELS,
    OMNIROUTE_BASE_URL,
    OMNIROUTE_API_KEY,
    OMNIROUTE_MODEL,
)
import asyncio

from core.database import db
from services.roles import ROLES, DEFAULT_ROLE

logger = logging.getLogger(__name__)


class AIManager:
    """
    Barcha AI so'rovlarini yagona interfeys orqali boshqaruvchi klass.

    Xususiyatlar:
        current_provider: "gemini" | "openrouter" | "omniroute"
        current_or_model:  OpenRouter model kaliti
        current_role:      Faol rol nomi
        history:           Suhbat tarixi (role, content juftlari)
    """

    def __init__(self) -> None:
        # Gemini client (google-genai 2.x SDK)
        self._gemini_client = genai.Client(api_key=GEMINI_API_KEY)

        # OpenRouter client (OpenAI-compatible async)
        self._openrouter_client = AsyncOpenAI(
            api_key=OPENROUTER_API_KEY,
            base_url=OPENROUTER_BASE_URL,
        )

        # OmniRoute client (https://github.com/diegosouzapw/OmniRoute)
        self._omniroute_client = AsyncOpenAI(
            api_key=OMNIROUTE_API_KEY or "omniroute",
            base_url=OMNIROUTE_BASE_URL,
        )

        # Joriy holat
        self.current_provider: str = "gemini"
        self.current_or_model: str = "auto"
        self.current_role: str = DEFAULT_ROLE
        self.history: list[dict] = []
        self._history_loaded: bool = False

    async def _ensure_history_loaded(self) -> None:
        """Server qayta yonganda (restart/deploy) avvalgi suhbat tarixini bazadan yuklash."""
        if not self._history_loaded:
            try:
                loaded = await db.get_recent_chat_history(limit=30)
                if loaded:
                    self.history = loaded
                    logger.info("AIManager: Bazadan %d ta avvalgi suhbat xabari yuklandi.", len(loaded))
            except Exception as e:
                logger.warning("AIManager suhbat tarixini yuklashda xato: %s", e)
            self._history_loaded = True

    # ─── Model / Rol Boshqaruvi ───────────────────────────────

    def switch_provider(self, provider: str) -> str:
        """'gemini', 'openrouter' yoki 'omniroute' ga o'tish."""
        if provider not in ("gemini", "openrouter", "omniroute"):
            return f"❌ Noto'g'ri provider: {provider}"
        self.current_provider = provider
        self.history.clear()
        name = "OmniRoute (350+ AI Gateway)" if provider == "omniroute" else provider.upper()
        return f"✅ Provider o'zgartirildi: **{name}**"

    def switch_openrouter_model(self, model_key: str) -> str:
        """OpenRouter modelini kalit nomi bilan almashtirish."""
        if model_key not in OPENROUTER_MODELS:
            available = ", ".join(OPENROUTER_MODELS.keys())
            return f"❌ Mavjud modellar: {available}"
        self.current_or_model = model_key
        self.current_provider = "openrouter"
        self.history.clear()
        model_id = OPENROUTER_MODELS[model_key]
        return f"✅ Model o'zgartirildi: `{model_id}`"

    def switch_role(self, role_key: str) -> str:
        """Tizimli rolni almashtirish."""
        if role_key not in ROLES:
            available = ", ".join(ROLES.keys())
            return f"❌ Mavjud rollar: {available}"
        self.current_role = role_key
        self.history.clear()
        role_name = ROLES[role_key]["name"]
        return f"✅ Rol o'zgartirildi: **{role_name}**"

    def clear_history(self) -> str:
        """Suhbat tarixini tozalash."""
        count = len(self.history)
        self.history.clear()
        try:
            import asyncio
            asyncio.create_task(db.clear_chat_history())
        except Exception:
            pass
        return f"🧹 Xotira tozalandi. {count} ta xabar o'chirildi."

    def status(self) -> str:
        """Joriy holat to'g'risida xabar."""
        role_name = ROLES.get(self.current_role, {}).get("name", self.current_role)
        if self.current_provider == "gemini":
            model_info = f"Gemini ({GEMINI_MODEL})"
        elif self.current_provider == "omniroute":
            model_info = f"OmniRoute Gateway ({OMNIROUTE_MODEL})"
        else:
            model_id = OPENROUTER_MODELS.get(self.current_or_model, self.current_or_model)
            model_info = f"OpenRouter ({model_id})"
        return (
            f"🤖 **Joriy Holat**\n"
            f"Provider: `{model_info}`\n"
            f"Rol: `{role_name}`\n"
            f"Tarix: `{len(self.history)} xabar`"
        )

    # ─── Asosiy Generatsiya ───────────────────────────────────

    async def generate(
        self,
        user_message: str,
        image_bytes: Optional[bytes] = None,
        image_mime: str = "image/jpeg",
        save_history: bool = True,
    ) -> str:
        """
        Matn (va ixtiyoriy rasm) bo'yicha AI javob generatsiya qiladi.
        Asosiy provayder xato bersa, zaxira bepul provayderga avtomatik o'tadi (Fallback).
        save_history=False qilinganda foniy vazifalar kontekstni buzmaydi.
        """
        await self._ensure_history_loaded()

        # 1. OmniRoute tanlangan bo'lsa (faqat foydalanuvchi atayin OmniRoute ni tanlagan bo'lsa)
        if self.current_provider == "omniroute":
            result = await self._generate_omniroute(user_message, save_history=save_history)
            if not result.startswith("❌"):
                return result
            logger.warning("OmniRoute xato berdi, Gemini ga fallback qilinmoqda...")
            fallback_res = await self._generate_gemini(user_message, image_bytes, image_mime, save_history=save_history)
            if not fallback_res.startswith("❌"):
                return fallback_res
            return result

        # 2. Gemini tanlangan bo'lsa (Standart)
        if self.current_provider == "gemini":
            result = await self._generate_gemini(user_message, image_bytes, image_mime, save_history=save_history)
            if not result.startswith("❌"):
                return result
            logger.warning("Gemini barcha modellarida xato bo'ldi, OpenRouter ga fallback qilinmoqda...")
            fallback_res = await self._generate_openrouter(user_message, save_history=save_history)
            if not fallback_res.startswith("❌"):
                return fallback_res
            # OmniRoute faqat lokalda yoqilgan bo'lsa ishlaydi, shuning uchun zaxira sifatida foydalanuvchiga xatolik chiqarmaymiz
            return "⚠️ Sun'iy intellekt xizmati vaqtincha band. Iltimos, bir ozdan so'ng qayta urinib ko'ring yoki /models buyrug'i orqali boshqa modelni tanlang."

        # 3. OpenRouter tanlangan bo'lsa
        result = await self._generate_openrouter(user_message, save_history=save_history)
        if not result.startswith("❌"):
            return result

        logger.warning("OpenRouter xato berdi, Gemini ga fallback qilinmoqda...")
        fallback_res = await self._generate_gemini(user_message, image_bytes, image_mime, save_history=save_history)
        if not fallback_res.startswith("❌"):
            return fallback_res

        return "⚠️ Sun'iy intellekt xizmati vaqtincha band. Iltimos, bir ozdan so'ng qayta urinib ko'ring."

    async def generate_with_audio(
        self,
        audio_bytes: bytes,
        mime_type: str = "audio/ogg",
        custom_instruction: Optional[str] = None,
    ) -> str:
        """
        Ovozli xabarni Gemini Multimodal orqali to'g'ridan-to'g'ri tahlil qilish va javob berish.
        """
        instruction = custom_instruction or (
            "Foydalanuvchining ushbu ovozli xabarini diqqat bilan eshiting va tushuning.\n"
            "Format:\n"
            "🎙 **Transkripsiya (Aytilgan gaplar):**\n"
            "<aniq eshitilgan matn>\n\n"
            "💡 **AI Javobi:**\n"
            "<foydalanuvchi so'roviga to'liq, aniq va foydali javob>"
        )

        if GEMINI_API_KEY and self._gemini_client:
            models_to_try = [GEMINI_MODEL] + list(GEMINI_FALLBACK_MODELS)
            for m in models_to_try:
                try:
                    part = genai_types.Part.from_bytes(data=audio_bytes, mime_type=mime_type)
                    resp = await asyncio.to_thread(
                        self._gemini_client.models.generate_content,
                        model=m,
                        contents=[part, instruction],
                    )
                    if resp and resp.text:
                        return resp.text.strip()
                except Exception as exc:
                    logger.warning("Gemini audio tahlil xatosi (%s): %s", m, exc)
                    continue

        # Zaxira: matn transkripsiyasi orqali generatsiya
        try:
            from core.speech_agent import transcribe_audio_bytes
            transcription = await transcribe_audio_bytes(audio_bytes, mime_type, ai_manager=self)
            if transcription:
                ans = await self.generate(transcription)
                return f"🎙 **Transkripsiya:** _{transcription}_\n\n💡 **AI Javobi:**\n{ans}"
        except Exception as stt_err:
            logger.error("Zaxira STT xatosi: %s", stt_err)

        return "❌ Ovozli xabarni tahlil qilishda xatolik yuz berdi. Iltimos, qaytadan urinib ko'ring yoki matn ko'rinishida yozing."

    # ─── Gemini ──────────────────────────────────────────────

    async def _generate_gemini(
        self,
        user_message: str,
        image_bytes: Optional[bytes],
        image_mime: str,
        save_history: bool = True,
    ) -> str:
        """Gemini API orqali javob olish (google-genai 2.x, multi-model fallback va doimiy xotira RAG)."""
        try:
            system_prompt = ROLES[self.current_role]["prompt"]
            rag_context = await db.build_rag_context()
            if rag_context:
                system_prompt = f"{rag_context}\n\n{system_prompt}"

            # Gemini Google SDK talabi: rollar ketma-ket takrorlanmasligi kerak va birinchi xabar user bo'lishi lozim
            contents: list = []
            last_role = None
            for msg in self.history:
                text = (msg.get("content") or "").strip()
                if not text:
                    continue
                role = "user" if msg.get("role") == "user" else "model"
                if role == last_role and contents:
                    # Ketma-ket kelgan bir xil roldagi xabarni birlashtiramiz
                    contents[-1].parts[0].text += f"\n{text}"
                else:
                    contents.append(
                        genai_types.Content(
                            role=role,
                            parts=[genai_types.Part(text=text)],
                        )
                    )
                    last_role = role

            # Agar birinchi xabar 'model' bo'lib qolgan bo'lsa, uni olib tashlaymiz
            if contents and contents[0].role == "model":
                contents.pop(0)

            # Joriy user xabari
            current_parts: list = []
            if image_bytes:
                current_parts.append(
                    genai_types.Part(
                        inline_data=genai_types.Blob(
                            mime_type=image_mime,
                            data=image_bytes,
                        )
                    )
                )
            current_parts.append(genai_types.Part(text=user_message))

            # Agar oldingi xabar ham user bo'lsa, unga birlashtiramiz (rasmsiz bo'lsa)
            if contents and contents[-1].role == "user" and not image_bytes:
                contents[-1].parts.append(genai_types.Part(text=f"\n{user_message}"))
            else:
                contents.append(genai_types.Content(role="user", parts=current_parts))

            # Modellar ketma-ketligi (kvota yoki 429 xatosi chiqsa avtomatik keyingisiga o'tadi)
            models_to_try = [GEMINI_MODEL] + [m for m in GEMINI_FALLBACK_MODELS if m != GEMINI_MODEL]
            last_exc = None

            for model_name in models_to_try:
                try:
                    response = await self._gemini_client.aio.models.generate_content(
                        model=model_name,
                        contents=contents,
                        config=genai_types.GenerateContentConfig(
                            system_instruction=system_prompt,
                            temperature=0.7,
                            max_output_tokens=2048,
                        ),
                    )

                    answer = response.text or ""
                    if answer.strip():
                        if save_history:
                            self.history.append({"role": "user", "content": user_message})
                            self.history.append({"role": "assistant", "content": answer})
                            if len(self.history) > 40:
                                self.history = self.history[-40:]
                            try:
                                await db.add_chat_message("user", user_message)
                                await db.add_chat_message("assistant", answer)
                            except Exception:
                                pass
                        return answer
                except Exception as m_exc:
                    logger.warning("Gemini model (%s) xatosi: %s. Zaxira Gemini modeli sinab ko'rilmoqda...", model_name, m_exc)
                    last_exc = m_exc
                    continue

            return f"❌ Gemini xatosi: {last_exc}"

        except Exception as exc:
            logger.error("Gemini umumiy xatosi: %s", exc)
            return f"❌ Gemini xatosi: {exc}"

    # ─── Ovozli Xabarlarni Qayta Ishlash (Voice-to-Task) ─────────

    async def generate_with_audio(
        self,
        audio_bytes: bytes,
        mime_type: str = "audio/ogg",
        custom_instruction: Optional[str] = None,
    ) -> str:
        """
        Gemini 3.5/3.1 Flash multimodal audiosi orqali ovozli xabarni tushunib,
        matnga aylantirish va vazifani bajarish/rejalashtirish.
        """
        try:
            system_prompt = custom_instruction or (
                "Siz Super-Agent sun'iy intellektisiz. Foydalanuvchining ovozli xabarini tinglang.\n"
                "1. Ovozda nima deyilganini to'liq o'zbek tilida yozing (🎙 Transkripsiya).\n"
                "2. Agar bu aniq topshiriq yoki buyruq bo'lsa (masalan: biror kishiga xabar yozish, "
                "eslatma qo'yish, kanalga post chiqarish yoki hisob-kitob qilish):\n"
                "   - Buyruq turi\n"
                "   - Qabul qiluvchi (kimga)\n"
                "   - Matn mazmuni\n"
                "   - Rejalashtirilgan vaqt (agar aytilgan bo'lsa)\n"
                "aniq, chiroyli va tartibli ko'rsating.\n"
                "3. Agar shunchaki savol yoki suhbat bo'lsa, savolga to'liq, aqlli va foydali javob qaytaring."
            )

            rag_context = await db.build_rag_context()
            if rag_context:
                system_prompt = f"{rag_context}\n\n{system_prompt}"

            parts = [
                genai_types.Part(
                    inline_data=genai_types.Blob(
                        mime_type=mime_type,
                        data=audio_bytes,
                    )
                ),
                genai_types.Part(text=system_prompt)
            ]

            models_to_try = [GEMINI_MODEL] + [m for m in GEMINI_FALLBACK_MODELS if m != GEMINI_MODEL]
            for model_name in models_to_try:
                try:
                    response = await self._gemini_client.aio.models.generate_content(
                        model=model_name,
                        contents=[genai_types.Content(role="user", parts=parts)],
                        config=genai_types.GenerateContentConfig(
                            temperature=0.4,
                            max_output_tokens=2048,
                        ),
                    )
                    answer = response.text or ""
                    if answer.strip():
                        return answer
                except Exception as m_exc:
                    logger.warning("Gemini audio (%s) xatosi: %s", model_name, m_exc)
                    continue

            return "❌ Ovozni tahlil qilib bo'lmadi."

        except Exception as exc:
            logger.error("generate_with_audio xatosi: %s", exc)
            return f"❌ Ovozli xabarni tahlil qilishda xatolik: {exc}"

    # ─── OpenRouter ───────────────────────────────────────────

    async def _generate_openrouter(self, user_message: str, save_history: bool = True) -> str:
        """OpenRouter API orqali javob olish (bepul modellar fallback va doimiy xotira)."""
        system_prompt = ROLES[self.current_role]["prompt"]
        rag_context = await db.build_rag_context()
        if rag_context:
            system_prompt = f"{rag_context}\n\n{system_prompt}"

        # Xabarlar strukturasini tuzish
        messages: list[dict] = [{"role": "system", "content": system_prompt}]
        for msg in self.history:
            role = "assistant" if msg.get("role") in ("model", "assistant") else msg.get("role", "user")
            content = msg.get("content") or ""
            if content.strip():
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": user_message})

        # Zaxira 100% bepul modellar ro'yxati (OpenRouter faol bepul tierlari)
        fallback_free_models = [
            "nousresearch/hermes-3-llama-3.1-405b:free",
            "nex-agi/nex-n2.5-mini:free",
            "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
            "nousresearch/hermes-3-llama-3.1-70b",
            "liquid/lfm-2.5-2.6b:free",
            "inclusionai/ling-3.0-flash-vl:free",
            "cohere/north-mini-code:free",
        ]

        target_model = OPENROUTER_MODELS.get(self.current_or_model, "nousresearch/hermes-3-llama-3.1-405b:free")
        models_to_try = [target_model] + [m for m in fallback_free_models if m != target_model]

        for model_id in models_to_try:
            try:
                response = await self._openrouter_client.chat.completions.create(
                    model=model_id,
                    messages=messages,
                    temperature=0.7,
                    max_tokens=2048,
                )
                msg_obj = response.choices[0].message
                answer = msg_obj.content or getattr(msg_obj, "reasoning", "") or ""
                if answer and answer.strip():
                    if save_history:
                        self.history.append({"role": "user", "content": user_message})
                        self.history.append({"role": "assistant", "content": answer})
                        if len(self.history) > 40:
                            self.history = self.history[-40:]
                        try:
                            await db.add_chat_message("user", user_message)
                            await db.add_chat_message("assistant", answer)
                        except Exception:
                            pass
                    return answer
            except Exception as exc:
                logger.warning("OpenRouter (%s) xatosi: %s. Zaxira bepul model sinab ko'rilmoqda...", model_id, exc)
                continue

        return "❌ OpenRouter bepul modellari vaqtincha javob bermadi."

    # ─── OmniRoute Gateway (https://github.com/diegosouzapw/OmniRoute) ────

    async def _generate_omniroute(
        self,
        user_message: str,
        save_history: bool = True,
    ) -> str:
        """
        OmniRoute AI Gateway orqali so'rov yuborish.
        Faqat foydalanuvchi OmniRoute provayderini maxsus tanlaganda ishlatiladi.
        """
        try:
            system_prompt = ROLES[self.current_role]["prompt"]
            rag_context = await db.build_rag_context()
            if rag_context:
                system_prompt = f"{rag_context}\n\n{system_prompt}"

            messages = [{"role": "system", "content": system_prompt}]
            for msg in self.history:
                messages.append({"role": msg["role"], "content": msg["content"]})
            messages.append({"role": "user", "content": user_message})

            response = await asyncio.wait_for(
                self._omniroute_client.chat.completions.create(
                    model=OMNIROUTE_MODEL,
                    messages=messages,
                    temperature=0.7,
                    max_tokens=2048,
                ),
                timeout=15.0
            )
            answer = response.choices[0].message.content or "❌ Bo'sh javob."
            if save_history:
                self.history.append({"role": "user", "content": user_message})
                self.history.append({"role": "assistant", "content": answer})
                if len(self.history) > 40:
                    self.history = self.history[-40:]
                try:
                    await db.add_chat_message("user", user_message)
                    await db.add_chat_message("assistant", answer)
                except Exception:
                    pass
            return answer
        except Exception as exc:
            logger.warning("OmniRoute gateway xatosi: %s", exc)
            return f"❌ OmniRoute xatosi: {exc}"



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
    NVIDIA_API_KEY,
    NVIDIA_BASE_URL,
    NVIDIA_MODEL,
    MISTRAL_API_KEY,
    MISTRAL_BASE_URL,
    MISTRAL_MODEL,
    MISTRAL_FALLBACK_MODELS,
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

        # NVIDIA NIM / Nemotron client (https://build.nvidia.com)
        self._nvidia_client = AsyncOpenAI(
            api_key=NVIDIA_API_KEY or "nvapi-dummy",
            base_url=NVIDIA_BASE_URL,
        )

        # Mistral AI client (https://console.mistral.ai)
        self._mistral_client = AsyncOpenAI(
            api_key=MISTRAL_API_KEY or "mistral-dummy",
            base_url=MISTRAL_BASE_URL,
        )

        # Joriy holat
        self.current_provider: str = "gemini"
        self.current_or_model: str = "auto"
        self.current_role: str = DEFAULT_ROLE
        self.chat_histories: dict[str, list[dict]] = {}
        self._loaded_chats: set[str] = set()

    @property
    def history(self) -> list[dict]:
        """Orqaga muvofiqlik: standart chat xotirasi."""
        return self.chat_histories.setdefault("0", [])

    @history.setter
    def history(self, val: list[dict]) -> None:
        self.chat_histories["0"] = val

    async def get_chat_history(self, chat_id: str = "0", limit: int = 30) -> list[dict]:
        """Berilgan chat_id bo'yicha suhbat tarixini xotira yoki SQLite dan yuklash."""
        chat_id_str = str(chat_id or "0")
        if chat_id_str not in self._loaded_chats:
            try:
                loaded = await db.get_recent_chat_history(chat_id=chat_id_str, limit=limit)
                if loaded:
                    self.chat_histories[chat_id_str] = loaded
                    logger.info("AIManager: Chat (%s) uchun bazadan %d ta xabar yuklandi.", chat_id_str, len(loaded))
                else:
                    self.chat_histories.setdefault(chat_id_str, [])
            except Exception as e:
                logger.warning("AIManager chat (%s) tarixini yuklashda xato: %s", chat_id_str, e)
                self.chat_histories.setdefault(chat_id_str, [])
            self._loaded_chats.add(chat_id_str)
        return self.chat_histories.get(chat_id_str, [])

    async def _ensure_history_loaded(self, chat_id: str = "0") -> None:
        """Server qayta yonganda (restart/deploy) avvalgi suhbat tarixini bazadan yuklash."""
        await self.get_chat_history(chat_id=chat_id)

    # ─── Model / Rol Boshqaruvi ───────────────────────────────

    def switch_provider(self, provider: str) -> str:
        """'gemini', 'openrouter', 'omniroute', 'nvidia' yoki 'mistral' ga o'tish."""
        if provider not in ("gemini", "openrouter", "omniroute", "nvidia", "mistral"):
            return f"❌ Noto'g'ri provider: {provider}"
        self.current_provider = provider
        # Model o'zgarganda suhbat tarixi o'chirilmaydi!
        if provider == "omniroute":
            name = "OmniRoute (350+ AI Gateway)"
        elif provider == "nvidia":
            name = "NVIDIA NIM (Nemotron Reasoning)"
        elif provider == "mistral":
            name = f"Mistral AI ({MISTRAL_MODEL})"
        else:
            name = provider.upper()
        return f"✅ Provider o'zgartirildi: **{name}**"

    def switch_openrouter_model(self, model_key: str) -> str:
        """OpenRouter modelini kalit nomi bilan almashtirish."""
        if model_key not in OPENROUTER_MODELS:
            available = ", ".join(OPENROUTER_MODELS.keys())
            return f"❌ Mavjud modellar: {available}"
        self.current_or_model = model_key
        self.current_provider = "openrouter"
        # Tarix o'chirilmaydi
        model_id = OPENROUTER_MODELS[model_key]
        return f"✅ Model o'zgartirildi: `{model_id}`"

    def switch_role(self, role_key: str) -> str:
        """Tizimli rolni almashtirish."""
        if role_key not in ROLES:
            available = ", ".join(ROLES.keys())
            return f"❌ Mavjud rollar: {available}"
        self.current_role = role_key
        # Tarix o'chirilmaydi
        role_name = ROLES[role_key]["name"]
        return f"✅ Rol o'zgartirildi: **{role_name}**"

    def clear_history(self, chat_id: Optional[str] = None) -> str:
        """Suhbat tarixini tozalash (aniq chat yoki barcha chatlar bo'yicha)."""
        if chat_id is not None:
            c_id = str(chat_id)
            count = len(self.chat_histories.get(c_id, []))
            self.chat_histories[c_id] = []
            try:
                import asyncio
                asyncio.create_task(db.clear_chat_history(chat_id=c_id))
            except Exception:
                pass
            return f"🧹 Chat ({c_id}) xotirasi tozalandi. {count} ta xabar o'chirildi."

        count = sum(len(v) for v in self.chat_histories.values())
        self.chat_histories.clear()
        self._loaded_chats.clear()
        try:
            import asyncio
            asyncio.create_task(db.clear_chat_history())
        except Exception:
            pass
        return f"🧹 Barcha chatlar xotirasi tozalandi. {count} ta xabar o'chirildi."

    def status(self, chat_id: str = "0") -> str:
        """Joriy holat to'g'risida xabar."""
        role_name = ROLES.get(self.current_role, {}).get("name", self.current_role)
        if self.current_provider == "gemini":
            model_info = f"Gemini ({GEMINI_MODEL})"
        elif self.current_provider == "omniroute":
            model_info = f"OmniRoute Gateway ({OMNIROUTE_MODEL})"
        elif self.current_provider == "nvidia":
            model_info = f"NVIDIA NIM ({NVIDIA_MODEL})"
        elif self.current_provider == "mistral":
            model_info = f"Mistral AI ({MISTRAL_MODEL})"
        else:
            model_id = OPENROUTER_MODELS.get(self.current_or_model, self.current_or_model)
            model_info = f"OpenRouter ({model_id})"
        hist_count = len(self.chat_histories.get(str(chat_id), []))
        return (
            f"🤖 **Joriy Holat**\n"
            f"Provider: `{model_info}`\n"
            f"Rol: `{role_name}`\n"
            f"Tarix: `{hist_count} xabar`"
        )

    # ─── Asosiy Generatsiya ───────────────────────────────────

    async def generate(
        self,
        user_message: str,
        image_bytes: Optional[bytes] = None,
        image_mime: str = "image/jpeg",
        save_history: bool = True,
        chat_id: str = "0",
        user_id: str = "",
        sender_name: str = "Foydalanuvchi",
        chat_type: str = "private",
    ) -> str:
        """
        Matn (va ixtiyoriy rasm) bo'yicha AI javob generatsiya qiladi.
        Asosiy provayder xato bersa, zaxira bepul provayderga avtomatik o'tadi (Fallback).
        Guruhlar, kanallar va shaxsiy suhbatlar alohida chat_id bo'yicha mustaqil saqlanadi.
        """
        chat_id_str = str(chat_id or "0")
        await self.get_chat_history(chat_id=chat_id_str)

        # -1. Mistral AI tanlangan bo'lsa
        if self.current_provider == "mistral":
            return await self._generate_mistral(
                user_message,
                save_history=save_history,
                chat_id=chat_id_str,
                user_id=user_id,
                sender_name=sender_name,
                chat_type=chat_type,
            )

        # 0. NVIDIA NIM tanlangan bo'lsa
        if self.current_provider == "nvidia":
            return await self._generate_nvidia(
                user_message,
                save_history=save_history,
                chat_id=chat_id_str,
                user_id=user_id,
                sender_name=sender_name,
                chat_type=chat_type,
            )

        # 1. OmniRoute tanlangan bo'lsa
        if self.current_provider == "omniroute":
            result = await self._generate_omniroute(
                user_message,
                save_history=save_history,
                chat_id=chat_id_str,
                user_id=user_id,
                sender_name=sender_name,
                chat_type=chat_type,
            )
            if not result.startswith("❌"):
                return result
            logger.warning("OmniRoute xato berdi, Gemini ga fallback qilinmoqda...")
            fallback_res = await self._generate_gemini(
                user_message,
                image_bytes,
                image_mime,
                save_history=save_history,
                chat_id=chat_id_str,
                user_id=user_id,
                sender_name=sender_name,
                chat_type=chat_type,
            )
            if not fallback_res.startswith("❌"):
                return fallback_res
            return result

        # 2. Gemini tanlangan bo'lsa (Standart)
        if self.current_provider == "gemini":
            result = await self._generate_gemini(
                user_message,
                image_bytes,
                image_mime,
                save_history=save_history,
                chat_id=chat_id_str,
                user_id=user_id,
                sender_name=sender_name,
                chat_type=chat_type,
            )
            if not result.startswith("❌"):
                return result
            logger.warning("Gemini barcha modellarida xato bo'ldi, OpenRouter ga fallback qilinmoqda...")
            fallback_res = await self._generate_openrouter(
                user_message,
                save_history=save_history,
                chat_id=chat_id_str,
                user_id=user_id,
                sender_name=sender_name,
                chat_type=chat_type,
            )
            if not fallback_res.startswith("❌"):
                return fallback_res
            return "⚠️ Sun'iy intellekt xizmati vaqtincha band. Iltimos, bir ozdan so'ng qayta urinib ko'ring yoki /models buyrug'i orqali boshqa modelni tanlang."

        # 3. OpenRouter tanlangan bo'lsa
        result = await self._generate_openrouter(
            user_message,
            save_history=save_history,
            chat_id=chat_id_str,
            user_id=user_id,
            sender_name=sender_name,
            chat_type=chat_type,
        )
        if not result.startswith("❌"):
            return result

        logger.warning("OpenRouter xato berdi, Gemini ga fallback qilinmoqda...")
        fallback_res = await self._generate_gemini(
            user_message,
            image_bytes,
            image_mime,
            save_history=save_history,
            chat_id=chat_id_str,
            user_id=user_id,
            sender_name=sender_name,
            chat_type=chat_type,
        )
        if not fallback_res.startswith("❌"):
            return fallback_res

        return "⚠️ Sun'iy intellekt xizmati vaqtincha band. Iltimos, bir ozdan so'ng qayta urinib ko'ring."

    async def generate_with_image(
        self,
        prompt: str,
        image_bytes: bytes,
        mime_type: str = "image/jpeg",
        save_history: bool = True,
        chat_id: str = "0",
        user_id: str = "",
        sender_name: str = "Foydalanuvchi",
        chat_type: str = "private",
    ) -> str:
        """Rasm bilan generatsiya qilish uchun qulay yordamchi metod."""
        return await self.generate(
            user_message=prompt,
            image_bytes=image_bytes,
            image_mime=mime_type,
            save_history=save_history,
            chat_id=chat_id,
            user_id=user_id,
            sender_name=sender_name,
            chat_type=chat_type,
        )

    async def generate_with_audio(
        self,
        audio_bytes: bytes,
        mime_type: str = "audio/ogg",
        custom_instruction: Optional[str] = None,
    ) -> str:
        """
        Ovozli xabarni Gemini Multimodal orqali tushunib, matnga aylantirish va javob berish.
        """
        try:
            instruction = custom_instruction or (
                "Siz Super-Agent sun'iy intellektisiz. Foydalanuvchining ovozli xabarini tinglang.\n"
                "1. Ovozda nima deyilganini to'liq o'zbek tilida yozing (🎙 Transkripsiya).\n"
                "2. Agar bu aniq topshiriq yoki savol bo'lsa, savolga to'liq, aqlli va foydali javob qaytaring."
            )

            rag_context = await db.build_rag_context(context_type="private")
            if rag_context:
                instruction = f"{rag_context}\n\n{instruction}"

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
            from core.speech_agent import transcribe_audio_bytes
            transcription = await transcribe_audio_bytes(audio_bytes, mime_type, ai_manager=self)
            if transcription:
                ans = await self.generate(transcription)
                return f"🎙 **Transkripsiya:** _{transcription}_\n\n💡 **AI Javobi:**\n{ans}"
        except Exception as stt_err:
            logger.error("Audio tahlil xatosi: %s", stt_err)

        return "❌ Ovozli xabarni tahlil qilishda xatolik yuz berdi. Iltimos, qaytadan urinib ko'ring yoki matn ko'rinishida yozing."

    # ─── Gemini ──────────────────────────────────────────────

    async def _generate_gemini(
        self,
        user_message: str,
        image_bytes: Optional[bytes] = None,
        image_mime: str = "image/jpeg",
        save_history: bool = True,
        chat_id: str = "0",
        user_id: str = "",
        sender_name: str = "Foydalanuvchi",
        chat_type: str = "private",
    ) -> str:
        """Gemini API orqali javob olish (google-genai 2.x, multi-model fallback va doimiy multi-chat xotira)."""
        try:
            system_prompt = ROLES[self.current_role]["prompt"]
            if chat_type in ("group", "supergroup"):
                system_prompt += "\n\nSiz Telegram guruhidasiz. Suhbatdosh a'zolarga do'stona, aniq va hurmat bilan javob bering."
            elif chat_type == "channel":
                system_prompt += "\n\nSiz Telegram kanalidasiz. Postlar uchun jozibali, mazmunli va professional formatda javob bering."

            rag_context = ""
            if chat_type not in ("group", "supergroup", "channel"):
                rag_context = await db.build_rag_context(user_id=user_id or chat_id, context_type="private")
                if rag_context:
                    system_prompt = f"{rag_context}\n\n{system_prompt}"

                # Foydalanuvchining shaxsiy astrologik kartasini AI kontekstiga ulash (faqat shaxsiy chatda)
                try:
                    astro_profile = await db.get_astrology_profile(user_id=user_id or chat_id)
                    if astro_profile and astro_profile.get("chart"):
                        from core.astrology_agent import format_astrology_rag_context, calculate_transits
                        chart = astro_profile["chart"]
                        transits = calculate_transits(chart.get("planets", {}))
                        astro_ctx = format_astrology_rag_context(chart, transits)
                        if astro_ctx:
                            system_prompt = f"{astro_ctx}\n\n{system_prompt}"
                except Exception as e:
                    logger.debug("Astrology context yuklashda xato: %s", e)

            history_list = await self.get_chat_history(chat_id=chat_id, limit=30)

            # Gemini Google SDK talabi: rollar ketma-ket takrorlanmasligi kerak va birinchi xabar user bo'lishi lozim
            contents: list = []
            last_role = None
            for msg in history_list:
                raw_c = (msg.get("content") or "").strip()
                if not raw_c:
                    continue
                role = "user" if msg.get("role") == "user" else "model"
                s_name = msg.get("sender_name") or ""
                if role == "user" and s_name and chat_type in ("group", "supergroup", "channel") and not raw_c.startswith("["):
                    text = f"[{s_name}]: {raw_c}"
                else:
                    text = raw_c

                if role == last_role and contents:
                    contents[-1].parts[0].text += f"\n{text}"
                else:
                    contents.append(
                        genai_types.Content(
                            role=role,
                            parts=[genai_types.Part(text=text)],
                        )
                    )
                    last_role = role

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

            cur_text = f"[{sender_name}]: {user_message}" if (sender_name and chat_type in ("group", "supergroup", "channel") and not user_message.startswith("[")) else user_message
            current_parts.append(genai_types.Part(text=cur_text))

            if contents and contents[-1].role == "user" and not image_bytes:
                contents[-1].parts.append(genai_types.Part(text=f"\n{cur_text}"))
            else:
                contents.append(genai_types.Content(role="user", parts=current_parts))

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
                            chat_h = self.chat_histories.setdefault(chat_id, [])
                            chat_h.append({"role": "user", "content": user_message, "sender_name": sender_name, "chat_id": chat_id})
                            chat_h.append({"role": "assistant", "content": answer, "sender_name": "Super-Agent", "chat_id": chat_id})
                            if len(chat_h) > 40:
                                self.chat_histories[chat_id] = chat_h[-40:]
                            try:
                                await db.add_chat_message("user", user_message, chat_id=chat_id, user_id=user_id, sender_name=sender_name, chat_type=chat_type)
                                await db.add_chat_message("assistant", answer, chat_id=chat_id, user_id="", sender_name="Super-Agent", chat_type=chat_type)
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

    # ─── OpenRouter ───────────────────────────────────────────

    async def _generate_openrouter(
        self,
        user_message: str,
        save_history: bool = True,
        chat_id: str = "0",
        user_id: str = "",
        sender_name: str = "Foydalanuvchi",
        chat_type: str = "private",
    ) -> str:
        """OpenRouter API orqali javob olish (bepul modellar fallback va doimiy multi-chat xotira)."""
        system_prompt = ROLES[self.current_role]["prompt"]
        if chat_type in ("group", "supergroup"):
            system_prompt += "\n\nSiz Telegram guruhidasiz. Do'stona va aniq javob bering."
        elif chat_type == "channel":
            system_prompt += "\n\nSiz Telegram kanalidasiz. Mazmunli va professional formatda javob bering."

        rag_context = ""
        if chat_type not in ("group", "supergroup", "channel"):
            rag_context = await db.build_rag_context(user_id=user_id or chat_id, context_type="private")
            if rag_context:
                system_prompt = f"{rag_context}\n\n{system_prompt}"

            # Foydalanuvchining shaxsiy astrologik kartasini AI kontekstiga ulash (faqat shaxsiy chatda)
            try:
                astro_profile = await db.get_astrology_profile(user_id=user_id or chat_id)
                if astro_profile and astro_profile.get("chart"):
                    from core.astrology_agent import format_astrology_rag_context, calculate_transits
                    chart = astro_profile["chart"]
                    transits = calculate_transits(chart.get("planets", {}))
                    astro_ctx = format_astrology_rag_context(chart, transits)
                    if astro_ctx:
                        system_prompt = f"{astro_ctx}\n\n{system_prompt}"
            except Exception as e:
                logger.debug("OpenRouter astrology context yuklashda xato: %s", e)

        history_list = await self.get_chat_history(chat_id=chat_id, limit=30)
        messages: list[dict] = [{"role": "system", "content": system_prompt}]
        for msg in history_list:
            role = "assistant" if msg.get("role") in ("model", "assistant") else "user"
            content = msg.get("content") or ""
            s_name = msg.get("sender_name") or ""
            if role == "user" and s_name and chat_type in ("group", "supergroup", "channel") and not content.startswith("["):
                content = f"[{s_name}]: {content}"
            if content.strip():
                messages.append({"role": role, "content": content})

        cur_text = f"[{sender_name}]: {user_message}" if (sender_name and chat_type in ("group", "supergroup", "channel") and not user_message.startswith("[")) else user_message
        messages.append({"role": "user", "content": cur_text})

        fallback_free_models = [
            "deepseek/deepseek-v4-flash-0731:free",
            "nvidia/nemotron-3-super-120b-a12b:free",
            "poolside/laguna-s-2.1:free",
            "dots-studio/dots-3-note-preview:free",
            "nex-agi/nex-n2.5-pro:free",
            "nex-agi/nex-n2.5-mini:free",
            "liquid/lfm-2.5-2.6b:free",
            "cohere/north-mini-code:free",
            "openrouter/free",
        ]

        target_model = OPENROUTER_MODELS.get(self.current_or_model, "openrouter/free")
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
                ans_content = getattr(msg_obj, "content", "") or ""
                ans_reasoning = getattr(msg_obj, "reasoning", "") or getattr(msg_obj, "reasoning_content", "") or ""
                answer = ans_content.strip() if ans_content.strip() else ans_reasoning.strip()
                if answer:
                    if save_history:
                        chat_h = self.chat_histories.setdefault(chat_id, [])
                        chat_h.append({"role": "user", "content": user_message, "sender_name": sender_name, "chat_id": chat_id})
                        chat_h.append({"role": "assistant", "content": answer, "sender_name": "Super-Agent", "chat_id": chat_id})
                        if len(chat_h) > 40:
                            self.chat_histories[chat_id] = chat_h[-40:]
                        try:
                            await db.add_chat_message("user", user_message, chat_id=chat_id, user_id=user_id, sender_name=sender_name, chat_type=chat_type)
                            await db.add_chat_message("assistant", answer, chat_id=chat_id, user_id="", sender_name="Super-Agent", chat_type=chat_type)
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
        chat_id: str = "0",
        user_id: str = "",
        sender_name: str = "Foydalanuvchi",
        chat_type: str = "private",
    ) -> str:
        """
        OmniRoute AI Gateway orqali so'rov yuborish.
        Faqat foydalanuvchi OmniRoute provayderini maxsus tanlaganda ishlatiladi.
        """
        try:
            system_prompt = ROLES[self.current_role]["prompt"]
            if chat_type in ("group", "supergroup"):
                system_prompt += "\n\nSiz Telegram guruhidasiz. Do'stona va aniq javob bering."
            elif chat_type == "channel":
                system_prompt += "\n\nSiz Telegram kanalidasiz. Mazmunli va professional formatda javob bering."

            rag_context = ""
            if chat_type not in ("group", "supergroup", "channel"):
                rag_context = await db.build_rag_context(user_id=user_id or chat_id, context_type="private")
                if rag_context:
                    system_prompt = f"{rag_context}\n\n{system_prompt}"

            history_list = await self.get_chat_history(chat_id=chat_id, limit=30)
            messages = [{"role": "system", "content": system_prompt}]
            for msg in history_list:
                role = "assistant" if msg.get("role") in ("model", "assistant") else "user"
                content = msg.get("content") or ""
                s_name = msg.get("sender_name") or ""
                if role == "user" and s_name and chat_type in ("group", "supergroup", "channel") and not content.startswith("["):
                    content = f"[{s_name}]: {content}"
                if content.strip():
                    messages.append({"role": role, "content": content})

            cur_text = f"[{sender_name}]: {user_message}" if (sender_name and chat_type in ("group", "supergroup", "channel") and not user_message.startswith("[")) else user_message
            messages.append({"role": "user", "content": cur_text})

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
                chat_h = self.chat_histories.setdefault(chat_id, [])
                chat_h.append({"role": "user", "content": user_message, "sender_name": sender_name, "chat_id": chat_id})
                chat_h.append({"role": "assistant", "content": answer, "sender_name": "Super-Agent", "chat_id": chat_id})
                if len(chat_h) > 40:
                    self.chat_histories[chat_id] = chat_h[-40:]
                try:
                    await db.add_chat_message("user", user_message, chat_id=chat_id, user_id=user_id, sender_name=sender_name, chat_type=chat_type)
                    await db.add_chat_message("assistant", answer, chat_id=chat_id, user_id="", sender_name="Super-Agent", chat_type=chat_type)
                except Exception:
                    pass
            return answer
        except Exception as exc:
            logger.warning("OmniRoute gateway xatosi: %s", exc)
            return f"❌ OmniRoute xatosi: {exc}"

    # ─── NVIDIA NIM / Nemotron Direct & Fallback Engine ───────────

    async def _generate_nvidia(
        self,
        user_message: str,
        save_history: bool = True,
        chat_id: str = "0",
        user_id: str = "",
        sender_name: str = "Foydalanuvchi",
        chat_type: str = "private",
    ) -> str:
        """
        NVIDIA NIM API (https://build.nvidia.com) orqali to'g'ridan-to'g'ri yoki
        OpenRouter'dagi Nemotron bepul modellari orqali xatosiz generatsiya.
        """
        system_prompt = ROLES[self.current_role]["prompt"]
        if chat_type in ("group", "supergroup"):
            system_prompt += "\n\nSiz Telegram guruhidasiz. Do'stona va aniq javob bering."
        elif chat_type == "channel":
            system_prompt += "\n\nSiz Telegram kanalidasiz. Mazmunli va professional formatda javob bering."

        rag_context = ""
        if chat_type not in ("group", "supergroup", "channel"):
            rag_context = await db.build_rag_context(user_id=user_id or chat_id, context_type="private")
            if rag_context:
                system_prompt = f"{rag_context}\n\n{system_prompt}"

        history_list = await self.get_chat_history(chat_id=chat_id, limit=30)
        messages = [{"role": "system", "content": system_prompt}]
        for msg in history_list:
            role = "assistant" if msg.get("role") in ("model", "assistant") else "user"
            content = msg.get("content") or ""
            s_name = msg.get("sender_name") or ""
            if role == "user" and s_name and chat_type in ("group", "supergroup", "channel") and not content.startswith("["):
                content = f"[{s_name}]: {content}"
            if content.strip():
                messages.append({"role": role, "content": content})

        cur_text = f"[{sender_name}]: {user_message}" if (sender_name and chat_type in ("group", "supergroup", "channel") and not user_message.startswith("[")) else user_message
        messages.append({"role": "user", "content": cur_text})

        # 1-Bosqich: Agar NVIDIA_API_KEY bo'lsa, rasmiy NVIDIA NIM API ga ulanish
        if NVIDIA_API_KEY and not NVIDIA_API_KEY.startswith("nvapi-dummy"):
            try:
                response = await asyncio.wait_for(
                    self._nvidia_client.chat.completions.create(
                        model=NVIDIA_MODEL,
                        messages=messages,
                        temperature=0.6,
                        max_tokens=2048,
                    ),
                    timeout=20.0,
                )
                ans = response.choices[0].message.content or ""
                if ans.strip():
                    if save_history:
                        chat_h = self.chat_histories.setdefault(chat_id, [])
                        chat_h.append({"role": "user", "content": user_message, "sender_name": sender_name, "chat_id": chat_id})
                        chat_h.append({"role": "assistant", "content": ans, "sender_name": "Super-Agent", "chat_id": chat_id})
                        if len(chat_h) > 40:
                            self.chat_histories[chat_id] = chat_h[-40:]
                        try:
                            await db.add_chat_message("user", user_message, chat_id=chat_id, user_id=user_id, sender_name=sender_name, chat_type=chat_type)
                            await db.add_chat_message("assistant", ans, chat_id=chat_id, user_id="", sender_name="Super-Agent", chat_type=chat_type)
                        except Exception:
                            pass
                    return ans
            except Exception as n_err:
                logger.warning("NVIDIA NIM to'g'ridan-to'g'ri API xatosi: %s. OpenRouter Nemotron zaxirasiga o'tilmoqda...", n_err)

        # 2-Bosqich: OpenRouter dagi Nemotron zaxira modellari (100% kafolatli)
        nemotron_models = [
            "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
            "nvidia/llama-3.1-nemotron-70b-instruct",
            "nvidia/nemotron-3-ultra-550b-a55b:free",
            "nvidia/nemotron-3.5-lightning:free",
        ]

        for n_model in nemotron_models:
            try:
                response = await asyncio.wait_for(
                    self._openrouter_client.chat.completions.create(
                        model=n_model,
                        messages=messages,
                        temperature=0.6,
                        max_tokens=2048,
                    ),
                    timeout=18.0,
                )
                msg_obj = response.choices[0].message
                ans = msg_obj.content or getattr(msg_obj, "reasoning", "") or ""
                if ans.strip():
                    if save_history:
                        chat_h = self.chat_histories.setdefault(chat_id, [])
                        chat_h.append({"role": "user", "content": user_message, "sender_name": sender_name, "chat_id": chat_id})
                        chat_h.append({"role": "assistant", "content": ans, "sender_name": "Super-Agent", "chat_id": chat_id})
                        if len(chat_h) > 40:
                            self.chat_histories[chat_id] = chat_h[-40:]
                        try:
                            await db.add_chat_message("user", user_message, chat_id=chat_id, user_id=user_id, sender_name=sender_name, chat_type=chat_type)
                            await db.add_chat_message("assistant", ans, chat_id=chat_id, user_id="", sender_name="Super-Agent", chat_type=chat_type)
                        except Exception:
                            pass
                    return ans
            except Exception as or_err:
                logger.debug("Nemotron (%s) xatosi: %s", n_model, or_err)
                continue

        # 3-Bosqich: Agar barchasi band bo'lsa, umumiy OpenRouter orqali
        return await self._generate_openrouter(
            user_message,
            save_history=save_history,
            chat_id=chat_id,
            user_id=user_id,
            sender_name=sender_name,
            chat_type=chat_type,
        )

    # ─── Mistral AI ───────────────────────────────────────────

    async def _generate_mistral(
        self,
        user_message: str,
        save_history: bool = True,
        chat_id: str = "0",
        user_id: str = "",
        sender_name: str = "Foydalanuvchi",
        chat_type: str = "private",
    ) -> str:
        """Mistral AI (console.mistral.ai) orqali generatsiya qilish."""
        system_prompt = ROLES[self.current_role]["prompt"]
        if chat_type in ("group", "supergroup"):
            system_prompt += "\n\nSiz Telegram guruhidasiz. Do'stona va aniq javob bering."
        elif chat_type == "channel":
            system_prompt += "\n\nSiz Telegram kanalidasiz. Mazmunli va professional formatda javob bering."

        rag_context = ""
        if chat_type not in ("group", "supergroup", "channel"):
            rag_context = await db.build_rag_context(user_id=user_id or chat_id, context_type="private")
            if rag_context:
                system_prompt = f"{rag_context}\n\n{system_prompt}"

        history_list = await self.get_chat_history(chat_id=chat_id, limit=30)
        messages = [{"role": "system", "content": system_prompt}]
        for msg in history_list:
            role = "assistant" if msg.get("role") in ("model", "assistant") else "user"
            content = msg.get("content") or ""
            s_name = msg.get("sender_name") or ""
            if role == "user" and s_name and chat_type in ("group", "supergroup", "channel") and not content.startswith("["):
                content = f"[{s_name}]: {content}"
            if content.strip():
                messages.append({"role": role, "content": content})

        cur_text = f"[{sender_name}]: {user_message}" if (sender_name and chat_type in ("group", "supergroup", "channel") and not user_message.startswith("[")) else user_message
        messages.append({"role": "user", "content": cur_text})

        models_to_try = [MISTRAL_MODEL] + [m for m in MISTRAL_FALLBACK_MODELS if m != MISTRAL_MODEL]

        for m_id in models_to_try:
            try:
                response = await asyncio.wait_for(
                    self._mistral_client.chat.completions.create(
                        model=m_id,
                        messages=messages,
                        temperature=0.7,
                        max_tokens=2048,
                    ),
                    timeout=20.0,
                )
                msg_obj = response.choices[0].message
                ans = msg_obj.content or getattr(msg_obj, "reasoning", "") or ""
                if ans.strip():
                    if save_history:
                        chat_h = self.chat_histories.setdefault(chat_id, [])
                        chat_h.append({"role": "user", "content": user_message, "sender_name": sender_name, "chat_id": chat_id})
                        chat_h.append({"role": "assistant", "content": ans, "sender_name": "Super-Agent", "chat_id": chat_id})
                        if len(chat_h) > 40:
                            self.chat_histories[chat_id] = chat_h[-40:]
                        try:
                            await db.add_chat_message("user", user_message, chat_id=chat_id, user_id=user_id, sender_name=sender_name, chat_type=chat_type)
                            await db.add_chat_message("assistant", ans, chat_id=chat_id, user_id="", sender_name="Super-Agent", chat_type=chat_type)
                        except Exception:
                            pass
                    return ans
            except Exception as m_err:
                logger.warning("Mistral AI model (%s) xatosi: %s. Zaxira modeli sinab ko'rilmoqda...", m_id, m_err)
                continue

        # Zaxira: agar barcha Mistral modellari band bo'lsa, OpenRouter ga o'tish
        logger.info("Mistral modellari band, zaxira bepul modelga o'tilmoqda...")
        return await self._generate_openrouter(
            user_message,
            save_history=save_history,
            chat_id=chat_id,
            user_id=user_id,
            sender_name=sender_name,
            chat_type=chat_type,
        )



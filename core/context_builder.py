"""
core/context_builder.py — Maxfiy Xotira va Kontekst Izolyatsiyasi (Phase 5)

Talablar:
- Shaxsiy foydalanuvchi xotirasi (faktlar, eslatmalar, shaxsiy profillar) HECH QACHON
  guruhlarga, kanallarga yoki boshqa foydalanuvchilar kontekstiga sizib chiqmasligi kerak.
- Kontekst turlari:
  1. PRIVATE_CONTEXT: Shaxsiy chat — xususiy xotiraga to'liq ruxsat.
  2. GROUP_CONTEXT: Guruh chati — xususiy xotira QAT'IYAN TAQIQLANGAN.
  3. CHANNEL_CONTEXT: Kanal — xususiy xotira TAQIQLANGAN.
  4. AGENT_CONTEXT: Agentlararo hamkorlik — faqat ochiq belgilangan ma'lumotlar.
  5. TASK_CONTEXT: Avtonom vazifa — faqat vazifaga tegishli xotira.
  6. SYSTEM_CONTEXT: Tizim konteksti — operatsion metama'lumotlar.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


class ContextType(str, Enum):
    PRIVATE_CONTEXT = "private"
    GROUP_CONTEXT = "group"
    CHANNEL_CONTEXT = "channel"
    AGENT_CONTEXT = "agent"
    TASK_CONTEXT = "task"
    SYSTEM_CONTEXT = "system"


class ContextPolicyError(Exception):
    """Kontekst siyosati yoki maxfiylik qoidasi buzilganda chaqiriladi."""
    pass


class ContextBuilder:
    """
    Turli muhitlar (shaxsiy, guruh, kanal, agent) uchun AI prompt kontekstini
    qattiq maxfiylik va izolyatsiya qoidalariga rioya qilgan holda shakllantiradi.
    """

    def __init__(self, admin_id: int = 0):
        self.admin_id = admin_id

    def build_context(
        self,
        user_id: int,
        chat_id: int,
        context_type: ContextType | str,
        task_id: Optional[str] = None,
        permissions: Optional[list[str]] = None,
        user_facts: Optional[list[dict[str, Any]]] = None,
        memories: Optional[list[dict[str, Any]]] = None,
        shared_knowledge: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """
        Xavfsiz kontekst obyektini quradi.
        
        Qoidalar:
        - GROUP_CONTEXT / CHANNEL_CONTEXT: user_facts va memories bloklanadi.
        - PRIVATE_CONTEXT: faqat ushbu user_id ga tegishli xotira qo'shiladi.
        - AGENT_CONTEXT / TASK_CONTEXT: faqat shared_knowledge yoki task_id ga oid xotira.
        """
        if isinstance(context_type, str):
            try:
                context_type = ContextType(context_type.lower())
            except ValueError:
                context_type = ContextType.SYSTEM_CONTEXT

        permissions = permissions or []
        allowed_memories: list[dict[str, Any]] = []
        allowed_facts: list[dict[str, Any]] = []
        sanitized_shared: list[str] = list(shared_knowledge or [])

        # 1. GURUH VA KANAL XAVFSIZLIGI (CRITICAL ISOLATION)
        if context_type in (ContextType.GROUP_CONTEXT, ContextType.CHANNEL_CONTEXT):
            # Guruhlarda shaxsiy xotira qat'iyan taqiqlangan!
            allowed_memories = []
            allowed_facts = []
            privacy_mode = "STRICT_GROUP_ISOLATION"
            logger.debug(
                "ContextBuilder: Guruh/Kanal kontekstida shaxsiy xotira bloklandi. user_id=%s, chat_id=%s",
                user_id, chat_id
            )

        # 2. SHAXSIY CHAT (PRIVATE_CONTEXT)
        elif context_type == ContextType.PRIVATE_CONTEXT:
            privacy_mode = "PRIVATE_ALLOWED"
            # Faqat shu user_id ga tegishli faktlarni qabul qilamiz
            if user_facts:
                for f in user_facts:
                    fact_owner = f.get("user_id") or f.get("owner_id")
                    # Agar fact_owner ko'rsatilgan bo'lsa va boshqa userga tegishli bo'lsa — tashlab yuboramiz
                    if fact_owner is not None and int(fact_owner) != int(user_id):
                        continue
                    allowed_facts.append(f)

            if memories:
                for m in memories:
                    mem_owner = m.get("user_id") or m.get("owner_id")
                    if mem_owner is not None and int(mem_owner) != int(user_id):
                        continue
                    allowed_memories.append(m)

        # 3. AGENTLARARO HAMKORLIK (AGENT_CONTEXT)
        elif context_type == ContextType.AGENT_CONTEXT:
            privacy_mode = "TASK_SHARED_ONLY"
            # Shaxsiy xotira berilmaydi, faqat vazifaga tegishli ochiq ma'lumotlar
            allowed_memories = []
            allowed_facts = []

        # 4. AVTONOM VAZIFA (TASK_CONTEXT)
        elif context_type == ContextType.TASK_CONTEXT:
            privacy_mode = "TASK_SCOPED"
            allowed_memories = []
            allowed_facts = []

        else:
            privacy_mode = "SYSTEM_RESTRICTED"
            allowed_memories = []
            allowed_facts = []

        # Tizim prompti uchun matnli blok hosil qilamiz
        prompt_sections: list[str] = []

        if allowed_facts:
            facts_text = "\n".join(
                f"• {f.get('key', 'fakt')}: {f.get('content', '')}"
                for f in allowed_facts[:10]  # Butun bazani to'kib tashlamaymiz
            )
            prompt_sections.append(f"[SHAXSIY DOIMIY XOTIRA (Foydalanuvchi ID: {user_id})]:\n{facts_text}")

        if allowed_memories:
            mem_text = "\n".join(
                f"- {m.get('text', '')}" for m in allowed_memories[:5]
            )
            prompt_sections.append(f"[KONTEKST XOTIRASI]:\n{mem_text}")

        if sanitized_shared:
            shared_text = "\n".join(f"• {item}" for item in sanitized_shared[:5])
            prompt_sections.append(f"[VAZIFA MA'LUMOTLARI]:\n{shared_text}")

        system_injected_prompt = "\n\n".join(prompt_sections)

        return {
            "user_id": user_id,
            "chat_id": chat_id,
            "context_type": context_type.value,
            "privacy_mode": privacy_mode,
            "task_id": task_id,
            "injected_prompt": system_injected_prompt,
            "facts_count": len(allowed_facts),
            "memories_count": len(allowed_memories),
            "shared_count": len(sanitized_shared),
            "is_private_allowed": (context_type == ContextType.PRIVATE_CONTEXT),
        }


# Global yagona nusxa
context_builder = ContextBuilder()

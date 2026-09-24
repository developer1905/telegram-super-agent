"""
tests/test_memory_isolation.py — Xususiy Xotira va Guruh Izolyatsiyasi Testlari (Phase 5).

Tekshiruvlar:
1. User A ning faktlari va xotirasi User B ning kontekstiga tushmasligi kerak.
2. GROUP_CONTEXT da hech qanday shaxsiy xotira (facts, memories) AI promptiga qo'shilmasligi kerak.
3. CHANNEL_CONTEXT da shaxsiy xotira qat'iyan bloklanishi kerak.
4. PRIVATE_CONTEXT da faqat o'sha foydalanuvchining o'z xotirasi qo'shilishi kerak.
"""

import pytest
from core.context_builder import ContextBuilder, ContextType


def test_private_memory_not_leaked_to_other_users():
    """User A ga tegishli faktlar User B ning shaxsiy chatiga sizib chiqmasligi kerak."""
    builder = ContextBuilder(admin_id=1097265609)

    user_a_id = 111111
    user_b_id = 222222

    user_facts = [
        {"user_id": user_a_id, "key": "secret_project", "content": "Project Apollo"},
        {"user_id": user_b_id, "key": "hobby", "content": "Chess"},
    ]

    # User B uchun kontekst quramiz
    ctx_b = builder.build_context(
        user_id=user_b_id,
        chat_id=user_b_id,
        context_type=ContextType.PRIVATE_CONTEXT,
        user_facts=user_facts,
    )

    injected = ctx_b["injected_prompt"]
    # User B o'z xobbisini ko'rishi kerak
    assert "Chess" in injected
    # Lekin User A ning maxfiy loyihasini KO'RMASLIGI KERAK!
    assert "Project Apollo" not in injected
    assert ctx_b["facts_count"] == 1


def test_group_context_strictly_blocks_all_private_memory():
    """Guruh kontekstida (GROUP_CONTEXT) har qanday shaxsiy xotira 100% bloklanishi kerak."""
    builder = ContextBuilder(admin_id=1097265609)

    user_id = 12345
    group_chat_id = -100987654321

    facts = [
        {"user_id": user_id, "key": "bank_pin", "content": "1234"},
        {"user_id": user_id, "key": "home_address", "content": "Tashkent"},
    ]
    memories = [
        {"user_id": user_id, "text": "Kecha soat 20:00 da admin bilan uchrashuv bo'ldi"}
    ]

    ctx_group = builder.build_context(
        user_id=user_id,
        chat_id=group_chat_id,
        context_type=ContextType.GROUP_CONTEXT,
        user_facts=facts,
        memories=memories,
    )

    injected = ctx_group["injected_prompt"]
    # Guruhga birorta ham shaxsiy fakt yoki xotira kirmasligi shart!
    assert "bank_pin" not in injected
    assert "1234" not in injected
    assert "Tashkent" not in injected
    assert "uchrashuv" not in injected
    assert ctx_group["facts_count"] == 0
    assert ctx_group["memories_count"] == 0
    assert ctx_group["privacy_mode"] == "STRICT_GROUP_ISOLATION"


def test_channel_context_blocks_private_memory():
    """Kanal kontekstida (CHANNEL_CONTEXT) shaxsiy xotira bloklanishi kerak."""
    builder = ContextBuilder()

    ctx_channel = builder.build_context(
        user_id=12345,
        chat_id=-100111222333,
        context_type=ContextType.CHANNEL_CONTEXT,
        user_facts=[{"key": "private_note", "content": "confidential"}],
    )

    assert "confidential" not in ctx_channel["injected_prompt"]
    assert ctx_channel["facts_count"] == 0


def test_agent_context_only_allows_shared_task_knowledge():
    """Agentlararo hamkorlikda shaxsiy faktlar emas, faqat vazifa ma'lumotlari uzatiladi."""
    builder = ContextBuilder()

    ctx_agent = builder.build_context(
        user_id=12345,
        chat_id=12345,
        context_type=ContextType.AGENT_CONTEXT,
        task_id="collab_999",
        user_facts=[{"key": "my_salary", "content": "$5000"}],
        shared_knowledge=["Python backend arxitekturasi tahlili", "API endpointlar ro'yxati"],
    )

    injected = ctx_agent["injected_prompt"]
    assert "my_salary" not in injected
    assert "$5000" not in injected
    assert "Python backend arxitekturasi tahlili" in injected
    assert ctx_agent["privacy_mode"] == "TASK_SHARED_ONLY"

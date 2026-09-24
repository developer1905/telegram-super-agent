"""
tests/test_tool_permission.py — Vositalar Xavfsizligi va Ruxsatlar Qatlami Testlari (Phase 16 & 25).

Tekshiruvlar:
1. LOW darajadagi vositalar (CSV o'qish, qidiruv) oddiy foydalanuvchilar uchun ochiq.
2. HIGH darajadagi vositalar (kod bajarish, email) oddiy foydalanuvchi uchun bloklanadi.
3. HIGH va CRITICAL vositalar faqat admin yoki maxsus ruxsatli foydalanuvchiga ruxsat beriladi.
4. Ruxsat berilmagan kontekstda (masalan, guruhda email yuborish) vosita bloklanadi.
5. Noma'lum vositalar sukut bo'yicha rad etiladi.
"""

import pytest
from security.tool_permission import ToolPermissionManager, RiskLevel, ToolDefinition


def test_low_risk_tool_allowed_for_any_user():
    """LOW darajadagi vositalar (web_search, read_csv) har qanday foydalanuvchiga ruxsat etiladi."""
    manager = ToolPermissionManager(admin_id=1097265609)

    allowed, reason = manager.can_execute(
        tool_name="web_search",
        user_id=999999,
        context_type="private"
    )
    assert allowed is True
    assert reason is None

    allowed, reason = manager.can_execute(
        tool_name="read_csv",
        user_id=999999,
        context_type="group"
    )
    assert allowed is True


def test_high_risk_tool_denied_for_unauthorized_user():
    """HIGH darajadagi vosita (kod bajarish) ruxsatsiz oddiy foydalanuvchiga bloklanadi."""
    manager = ToolPermissionManager(admin_id=1097265609)

    allowed, reason = manager.can_execute(
        tool_name="execute_code",
        user_id=888888,  # oddiy user
        context_type="private",
        user_permissions=[]
    )
    assert allowed is False
    assert "yuqori xavfli (HIGH)" in reason


def test_high_risk_tool_allowed_with_permission_or_admin():
    """Admin yoki maxsus ruxsatli foydalanuvchi execute_code va send_email dan foydalana oladi."""
    admin_id = 1097265609
    manager = ToolPermissionManager(admin_id=admin_id)

    # 1. Admin uchun
    allowed, reason = manager.can_execute(
        tool_name="execute_code",
        user_id=admin_id,
        context_type="private",
    )
    assert allowed is True

    # 2. Maxsus ruxsatli foydalanuvchi uchun
    allowed, reason = manager.can_execute(
        tool_name="send_email",
        user_id=777777,
        context_type="private",
        user_permissions=["can_send_email"]
    )
    assert allowed is True


def test_critical_risk_tool_strictly_requires_admin():
    """CRITICAL darajadagi vosita (delete_database_records) FAQAT adminga ruxsat beriladi."""
    admin_id = 1097265609
    manager = ToolPermissionManager(admin_id=admin_id)

    # Oddiy user, hatto qo'shimcha ruxsatlari bo'lsa ham:
    allowed, reason = manager.can_execute(
        tool_name="delete_database_records",
        user_id=555555,
        context_type="private",
        user_permissions=["can_edit", "power_user"]
    )
    assert allowed is False
    assert "CRITICAL" in reason

    # Faqat haqiqiy admin:
    allowed, reason = manager.can_execute(
        tool_name="delete_database_records",
        user_id=admin_id,
        context_type="private",
        is_admin=True
    )
    assert allowed is True


def test_context_restriction_enforcement():
    """Guruhda send_email kabi shaxsiy vosita chaqirilsa, kontekst sababli rad etiladi."""
    manager = ToolPermissionManager(admin_id=1097265609)

    # send_email faqat private kontekstda ruxsat etilgan
    allowed, reason = manager.can_execute(
        tool_name="send_email",
        user_id=1097265609,
        context_type="group",  # guruhda chaqirildi!
        is_admin=True
    )
    assert allowed is False
    assert "ushbu kontekstda (group) ishlatilishi taqiqlangan" in reason


def test_unknown_tool_rejected():
    """Ro'yxatda yo'q, noma'lum vosita avtomatik bloklanadi."""
    manager = ToolPermissionManager(admin_id=1097265609)

    allowed, reason = manager.can_execute(
        tool_name="rm_rf_root",
        user_id=1097265609,
        is_admin=True
    )
    assert allowed is False
    assert "Noma'lum vosita" in reason

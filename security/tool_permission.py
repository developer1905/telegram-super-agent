"""
security/tool_permission.py — Vositalar Xavfsizligi va Ruxsatlar Qatlami (Phase 16)

Qoidalar:
- Har bir AI vositasi (Tool) xavf darajasini deklaratsiya qiladi: LOW, MEDIUM, HIGH, CRITICAL.
- HIGH va CRITICAL darajadagi vositalar (kod bajarish, email jo'natish, ma'lumot o'chirish)
  foydalanuvchi yoki adminning qat'iy ruxsatisiz avtomatik bajarilishi TAQIQLANADI.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ToolPermissionDenied(Exception):
    """Vositani bajarish uchun ruxsat yetarli bo'lmaganda chaqiriladi."""
    pass


@dataclass
class ToolDefinition:
    name: str
    risk_level: RiskLevel
    description: str
    required_permissions: list[str] = field(default_factory=list)
    allowed_contexts: list[str] = field(default_factory=lambda: ["private", "group", "task"])
    timeout_seconds: int = 30
    network_access: bool = False
    filesystem_access: bool = False


class ToolPermissionManager:
    """Barcha vositalarning xavfsizlik darajasini tekshiruvchi yagona nazorat qatlami."""

    def __init__(self, admin_id: int = 0):
        self.admin_id = admin_id
        self._tools: dict[str, ToolDefinition] = {}
        self._register_default_tools()

    def register_tool(self, tool: ToolDefinition) -> None:
        self._tools[tool.name] = tool
        logger.debug("Tool ro'yxatga olindi: %s (Risk: %s)", tool.name, tool.risk_level.value)

    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        return self._tools.get(name)

    def get_risk_level(self, name: str) -> Optional[RiskLevel]:
        """Vositaning risk darajasini qaytaradi."""
        tool = self._tools.get(name)
        return tool.risk_level if tool else None

    def is_tool_allowed(
        self,
        name: str,
        user_id: int = 0,
        context_type: str = "private",
        is_admin: bool = False,
    ) -> bool:
        """Vositaga ruxsat berilganligini sodda boolean shaklda qaytaradi."""
        allowed, _ = self.can_execute(name, user_id=user_id, context_type=context_type, is_admin=is_admin)
        return allowed

    def can_execute(
        self,
        tool_name: str,
        user_id: int,
        context_type: str = "private",
        user_permissions: Optional[list[str]] = None,
        is_admin: bool = False,
    ) -> tuple[bool, Optional[str]]:
        """
        Vositani bajarishga ruxsat borligini tekshiradi.
        
        Returns:
            (is_allowed: bool, reason: str | None)
        """
        tool = self._tools.get(tool_name)
        if not tool:
            # Noma'lum vositalar sukut bo'yicha bloklanadi
            return False, f"Noma'lum vosita: '{tool_name}'"

        # 1. Kontekst tekshiruvi
        if context_type not in tool.allowed_contexts:
            return False, f"'{tool_name}' vositasi ushbu kontekstda ({context_type}) ishlatilishi taqiqlangan"

        # 2. Xavf darajasiga ko'ra tekshiruv
        if tool.risk_level == RiskLevel.LOW:
            return True, None

        if tool.risk_level == RiskLevel.MEDIUM:
            # Medium daraja shaxsiy chatda yoki guruhda ruxsat berilgan
            return True, None

        # 3. HIGH va CRITICAL darajadagi vositalar
        effective_admin = is_admin or (self.admin_id and int(user_id) == int(self.admin_id))
        user_perms = set(user_permissions or [])

        if tool.risk_level == RiskLevel.HIGH:
            # Kod bajarish yoki email jo'natish — faqat admin yoki maxsus ruxsatli user
            if effective_admin or any(p in user_perms for p in tool.required_permissions):
                return True, None
            return False, f"'{tool_name}' vositasi yuqori xavfli (HIGH). Ishlatish uchun admin ruxsati zarur."

        if tool.risk_level == RiskLevel.CRITICAL:
            # Ma'lumotlarni o'chirish / serverni tozalash — QAT'IY FAQAT ADMIN
            if effective_admin:
                return True, None
            return False, f"'{tool_name}' vositasi o'ta xavfli (CRITICAL). Faqat tizim administratori bajara oladi."

        return False, "Noma'lum ruxsat xatosi"

    def _register_default_tools(self) -> None:
        """Standart Super-Agent vositalarini xavfsizlik darajasi bilan ro'yxatga oladi."""
        # LOW RISK (O'qish, tahlil qilish, hisoblash)
        self.register_tool(ToolDefinition(
            name="read_csv",
            risk_level=RiskLevel.LOW,
            description="CSV yoki Excel jadval ma'lumotlarini o'qish",
            filesystem_access=True,
        ))
        self.register_tool(ToolDefinition(
            name="web_search",
            risk_level=RiskLevel.LOW,
            description="Internetdan umumiy ma'lumot qidirish",
            network_access=True,
        ))
        self.register_tool(ToolDefinition(
            name="calculate_astrology",
            risk_level=RiskLevel.LOW,
            description="Natal kartani hisoblash",
        ))

        # MEDIUM RISK (Xabar jo'natish, media generatsiya)
        self.register_tool(ToolDefinition(
            name="send_telegram_message",
            risk_level=RiskLevel.MEDIUM,
            description="Telegram chatiga xabar yuborish",
            network_access=True,
        ))
        self.register_tool(ToolDefinition(
            name="generate_image",
            risk_level=RiskLevel.MEDIUM,
            description="FLUX.1 orqali rasm generatsiya qilish",
            network_access=True,
        ))
        self.register_tool(ToolDefinition(
            name="download_media",
            risk_level=RiskLevel.MEDIUM,
            description="YouTube/Instagram media yuklash",
            network_access=True,
            filesystem_access=True,
        ))

        # HIGH RISK (Kod bajarish, email jo'natish)
        self.register_tool(ToolDefinition(
            name="execute_code",
            risk_level=RiskLevel.HIGH,
            description="Docker sandbox ichida kod bajarish",
            required_permissions=["can_execute_code"],
            allowed_contexts=["private", "task"],
            timeout_seconds=15,
        ))
        self.register_tool(ToolDefinition(
            name="send_email",
            risk_level=RiskLevel.HIGH,
            description="SMTP orqali elektron xat yuborish",
            required_permissions=["can_send_email"],
            allowed_contexts=["private"],
            network_access=True,
        ))

        # CRITICAL RISK (O'chirish, tizim tozalash)
        self.register_tool(ToolDefinition(
            name="delete_database_records",
            risk_level=RiskLevel.CRITICAL,
            description="Baza yozuvlarini butunlay o'chirish",
            required_permissions=["admin"],
            allowed_contexts=["private"],
        ))
        self.register_tool(ToolDefinition(
            name="clean_server_storage",
            risk_level=RiskLevel.CRITICAL,
            description="Server diskidagi keshlarni tozalash",
            required_permissions=["admin"],
            allowed_contexts=["private"],
            filesystem_access=True,
        ))


# Global yagona nusxa
tool_permission_manager = ToolPermissionManager()

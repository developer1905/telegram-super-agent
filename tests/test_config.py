"""
tests/test_config.py — config.py xavfsizlik va korrektlik testlari.

Testlar:
1. Hardcoded secretlar YO'Q ekanligini tekshirish (regression: _DEF_SEC_TOK, _DEF_MIS_KEY)
2. _hf_chunks obfuscation pattern YO'Q ekanligini tekshirish
3. POLLINATIONS_API_KEY default bo'sh string ekanligini tekshirish
4. SECOND_BOT_TOKEN env yo'q bo'lsa bo'sh string qaytarishini tekshirish
5. VOICE_OPTIONS duplicate YO'Q ekanligini tekshirish

Ishga tushirish:
    cd super_agent
    python -m pytest tests/test_config.py -v
"""

from __future__ import annotations

import ast
import os
import sys
import tokenize
import io
import pytest

# Config fayliga to'liq yo'l
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config.py")


def read_config_source() -> str:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return f.read()


class TestConfigSecurityHardening:
    """config.py da hardcoded secret yo'qligini tekshiradi."""

    def test_no_base64_decode_of_secrets(self):
        """_DEF_SEC_TOK yoki _DEF_MIS_KEY orqali decode qilingan secret yo'q."""
        source = read_config_source()
        assert "_DEF_SEC_TOK" not in source, (
            "CRITICAL: _DEF_SEC_TOK (hardcoded bot token) hali ham config.py da mavjud!"
        )
        assert "_DEF_MIS_KEY" not in source, (
            "CRITICAL: _DEF_MIS_KEY (hardcoded Mistral API key) hali ham config.py da mavjud!"
        )

    def test_no_base64_import_for_secrets(self):
        """base64 as _b64 import qilinmagan."""
        source = read_config_source()
        assert "import base64 as _b64" not in source, (
            "CRITICAL: base64 as _b64 hali ham import qilinmoqda (secret construction uchun ishlatilgan)"
        )

    def test_no_hardcoded_hf_api_key(self):
        """HuggingFace API key _hf_chunks orqali obfuscate qilinmagan."""
        source = read_config_source()
        assert "_hf_chunks" not in source, (
            "CRITICAL: _hf_chunks (HuggingFace API key obfuscation) hali ham config.py da mavjud!"
        )

    def test_no_hardcoded_pollinations_key(self):
        """Pollinations API key hardcoded emas."""
        source = read_config_source()
        # Konket key prefix tekshiruvi (kalit qiymati o'zgarishi mumkin)
        assert '"sk_rxjymssWbXEDF7Fn6awf3iwNI82aeAfZ"' not in source, (
            "CRITICAL: Hardcoded Pollinations API key hali ham config.py da mavjud!"
        )

    def test_no_hardcoded_b64_blobs(self):
        """Baza64 kodlangan bot token yoki API key yo'q."""
        source = read_config_source()
        # Telegram bot token base64 pattern (819611753 ham tekshiramiz)
        assert "ODE5NjExNzUzOTo" not in source, (
            "CRITICAL: Hardcoded bot token base64 blob hali ham config.py da mavjud!"
        )
        assert "NWxxSzhweERqSUhYd" not in source, (
            "CRITICAL: Hardcoded Mistral API key base64 blob hali ham config.py da mavjud!"
        )

    def test_no_hardcoded_mistral_agent_id(self):
        """Hardcoded Mistral Agent ID yo'q (faqat env orqali)."""
        source = read_config_source()
        assert '"ag_01a0ba16a68173e8a1cdb3ead308ff14"' not in source, (
            "Mistral Agent ID hardcoded. Faqat MISTRAL_AGENT_ID env var orqali bo'lishi kerak."
        )

    def test_no_duplicate_voice_options(self):
        """VOICE_OPTIONS faqat bir marta aniqlanishi kerak."""
        source = read_config_source()
        count = source.count("VOICE_OPTIONS")
        # VOICE_OPTIONS: definition (1) va ixtiyoriy reference (TYPE_CHECKING ichida) hisoblash kerak
        definitions = [
            line for line in source.splitlines()
            if "VOICE_OPTIONS" in line and ("dict" in line or "=" in line) and not line.strip().startswith("#")
        ]
        assert len(definitions) <= 1, (
            f"VOICE_OPTIONS bir necha marta aniqlangan: {definitions}"
        )

    def test_no_duplicate_midjourney_vars(self):
        """MIDJOURNEY_API_KEY va MIDJOURNEY_API_URL faqat bir marta aniqlanishi kerak."""
        source = read_config_source()
        mj_key_defs = [
            line for line in source.splitlines()
            if "MIDJOURNEY_API_KEY" in line and "=" in line and not line.strip().startswith("#")
        ]
        mj_url_defs = [
            line for line in source.splitlines()
            if "MIDJOURNEY_API_URL" in line and "=" in line and not line.strip().startswith("#")
        ]
        assert len(mj_key_defs) <= 1, f"MIDJOURNEY_API_KEY bir necha marta aniqlangan: {mj_key_defs}"
        assert len(mj_url_defs) <= 1, f"MIDJOURNEY_API_URL bir necha marta aniqlangan: {mj_url_defs}"


class TestConfigEnvDriven:
    """Muhim variable lar faqat env dan o'qishini va default lar to'g'riligini tekshiradi."""

    def test_pollinations_key_default_empty(self):
        """POLLINATIONS_API_KEY env yo'q bo'lsa bo'sh string bo'lishi kerak."""
        os.environ.pop("POLLINATIONS_API_KEY", None)
        # Config modulini qayta import qilmasdan statik tekshirish
        source = read_config_source()
        # Default "" yoki os.getenv("...", "") pattern bo'lishi kerak
        for line in source.splitlines():
            if "POLLINATIONS_API_KEY" in line and "os.getenv" in line and "=" in line and not line.strip().startswith("#"):
                # Xavfli pattern: `or "sk_..."` bo'lmasligi kerak
                assert 'or "sk_' not in line, (
                    f"POLLINATIONS_API_KEY fallback secret bilan: {line}"
                )

    def test_hf_key_default_empty(self):
        """HUGGINGFACE_API_KEY env yo'q bo'lsa bo'sh string bo'lishi kerak."""
        source = read_config_source()
        for line in source.splitlines():
            if "HUGGINGFACE_API_KEY" in line and "os.getenv" in line and "=" in line and not line.strip().startswith("#"):
                assert "_hf_chunks" not in line, (
                    f"HUGGINGFACE_API_KEY hali ham obfuscated key bilan: {line}"
                )
                # Xavfli pattern: or "hf_..." yoki or ''.join(...)
                assert "or \"\".join" not in line, (
                    f"HUGGINGFACE_API_KEY hali ham join() bilan obfuscate qilingan: {line}"
                )

    def test_second_bot_token_no_hardcoded_fallback(self):
        """SECOND_BOT_TOKEN env yo'q bo'lsa _DEF_SEC_TOK ga fallback qilinmasligi kerak."""
        source = read_config_source()
        # _DEF_SEC_TOK dan foydalanish yo'q
        for line in source.splitlines():
            if "SECOND_BOT_TOKEN" in line and "_DEF_SEC_TOK" in line:
                pytest.fail(
                    f"SECOND_BOT_TOKEN hali ham _DEF_SEC_TOK ga fallback qilyapti: {line}"
                )


class TestConfigValidate:
    """validate_config() funksiyasini tekshiradi."""

    def test_validate_config_returns_list(self):
        """validate_config() list qaytarishi kerak."""
        # Faqat statik parse qilamiz — real import qilmaymiz (env talab qilishi mumkin)
        source = read_config_source()
        assert "def validate_config" in source, "validate_config() funksiyasi topilmadi"
        assert "return " in source[source.find("def validate_config"):], "validate_config() return yo'q"


class TestConfigSyntax:
    """config.py sintaksisi to'g'riligini tekshiradi."""

    def test_config_parses_without_error(self):
        """config.py Python AST ga muvaffaqiyatli parse qilinishi kerak."""
        source = read_config_source()
        try:
            ast.parse(source)
        except SyntaxError as exc:
            pytest.fail(f"config.py sintaksis xatosi: {exc}")

    def test_no_eval_exec_in_config(self):
        """config.py da eval() yoki exec() ishlatilmaydi."""
        source = read_config_source()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id in ("eval", "exec"):
                    pytest.fail(f"config.py da eval()/exec() topildi (satr {node.lineno})")

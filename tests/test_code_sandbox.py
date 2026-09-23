"""
tests/test_code_sandbox.py — code_sandbox.py xavfsizlik va korrektlik testlari.

Testlar:
1. extract_python_code — markdown blok ajratish
2. _basic_safety_precheck — uzun kod rad etilishi
3. execute_python_code — Docker yo'q bo'lsa "unavailable" qaytarishi
4. format_sandbox_result_for_telegram — success va error formatlash
5. Docker available bo'lsa oddiy kod ishga tushishi

Ishga tushirish:
    cd super_agent
    python -m pytest tests/test_code_sandbox.py -v
"""

from __future__ import annotations

import asyncio
import pytest

try:
    from core.code_sandbox import (
        extract_python_code,
        _basic_safety_precheck,
        execute_python_code,
        format_sandbox_result_for_telegram,
    )
    SANDBOX_AVAILABLE = True
except ImportError:
    SANDBOX_AVAILABLE = False


@pytest.mark.skipif(not SANDBOX_AVAILABLE, reason="code_sandbox import qilinmadi")
class TestExtractPythonCode:
    """extract_python_code funksiyasi testlari."""

    def test_extracts_python_code_block(self):
        text = "```python\nprint('hello')\n```"
        assert extract_python_code(text) == "print('hello')"

    def test_extracts_bare_code_block(self):
        text = "```\nx = 1 + 2\n```"
        assert extract_python_code(text) == "x = 1 + 2"

    def test_returns_raw_if_no_code_block(self):
        text = "print('hello')"
        assert extract_python_code(text) == "print('hello')"

    def test_strips_whitespace(self):
        text = "```python\n  x = 1  \n```"
        assert extract_python_code(text).strip() == "x = 1"


@pytest.mark.skipif(not SANDBOX_AVAILABLE, reason="code_sandbox import qilinmadi")
class TestBasicSafetyPrecheck:
    """_basic_safety_precheck funksiyasi testlari."""

    def test_normal_code_passes(self):
        ok, err = _basic_safety_precheck("print('hello')")
        assert ok is True
        assert err is None

    def test_too_long_code_rejected(self):
        code = "x = 1\n" * 10_000  # >50KB
        ok, err = _basic_safety_precheck(code)
        assert ok is False
        assert err is not None

    def test_empty_code_rejected(self):
        ok, err = _basic_safety_precheck("")
        assert ok is False
        assert err is not None

    def test_whitespace_only_rejected(self):
        ok, err = _basic_safety_precheck("   \n\t  ")
        assert ok is False
        assert err is not None


@pytest.mark.skipif(not SANDBOX_AVAILABLE, reason="code_sandbox import qilinmadi")
class TestExecutePythonCode:
    """execute_python_code async funksiyasi testlari."""

    def test_no_docker_returns_unavailable(self):
        """Docker yo'q bo'lsa 'unavailable' sandbox_type qaytarishi kerak."""
        import core.code_sandbox as cs_module
        original = cs_module._DOCKER_AVAILABLE

        try:
            # Docker yo'q deb simulyatsiya qilamiz
            cs_module._DOCKER_AVAILABLE = False

            async def _run():
                return await execute_python_code("print('test')")

            result = asyncio.run(_run())
            assert result["success"] is False
            assert result["sandbox_type"] == "unavailable"
            assert "Docker" in result.get("stderr", "")
        finally:
            cs_module._DOCKER_AVAILABLE = original

    def test_too_long_code_returns_rejected(self):
        """Juda uzun kod 'rejected' sandbox_type qaytarishi kerak."""
        long_code = "x = 1\n" * 10_000

        async def _run():
            return await execute_python_code(long_code)

        result = asyncio.run(_run())
        assert result["success"] is False
        assert result["sandbox_type"] == "rejected"


@pytest.mark.skipif(not SANDBOX_AVAILABLE, reason="code_sandbox import qilinmadi")
class TestFormatSandboxResult:
    """format_sandbox_result_for_telegram funksiyasi testlari."""

    def test_formats_success_result(self):
        res = {
            "success": True,
            "stdout": "Hello, World!",
            "stderr": "",
            "returncode": 0,
            "duration": 0.5,
            "sandbox_type": "docker",
        }
        output = format_sandbox_result_for_telegram(res)
        assert "MUVAFFAQIYATLI" in output
        assert "Hello, World!" in output
        assert "Docker" in output

    def test_formats_error_result(self):
        res = {
            "success": False,
            "stdout": "",
            "stderr": "NameError: name 'x' is not defined",
            "returncode": 1,
            "duration": 0.1,
            "sandbox_type": "docker",
        }
        output = format_sandbox_result_for_telegram(res)
        assert "XATOLIK" in output
        assert "NameError" in output

    def test_formats_unavailable_result(self):
        res = {
            "success": False,
            "stdout": "",
            "stderr": "Docker sandbox mavjud emas.",
            "returncode": -1,
            "duration": 0.0,
            "sandbox_type": "unavailable",
        }
        output = format_sandbox_result_for_telegram(res)
        assert "Mavjud Emas" in output or "mavjud emas" in output.lower()

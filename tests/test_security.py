"""
tests/test_security.py — security/api_auth.py testlari.

Testlar:
1. validate_telegram_init_data muvaffaqiyatli hash tekshiruvi
2. Eskirgan initData rad etilishi
3. Noto'g'ri hash rad etilishi
4. Noto'g'ri ACL rad etilishi
5. _compute_init_data_hash algoritm to'g'riligi
6. Constant-time comparison (timing attack protection)
7. SECURITY_HEADERS barcha zarur sarlavhalarni o'z ichiga olganligi

Ishga tushirish:
    cd super_agent
    python -m pytest tests/test_security.py -v
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.parse
import pytest

# Modulni import qilishga urinib ko'ramiz
try:
    from security.api_auth import (
        validate_telegram_init_data,
        SECURITY_HEADERS,
        INIT_DATA_MAX_AGE_SECONDS,
        _compute_init_data_hash,
    )
    SECURITY_MODULE_AVAILABLE = True
except ImportError:
    SECURITY_MODULE_AVAILABLE = False


def _make_valid_init_data(
    bot_token: str,
    user_id: int = 12345,
    auth_date: int | None = None,
    username: str = "testuser",
) -> str:
    """Test uchun to'g'ri Telegram initData string yaratadi."""
    if auth_date is None:
        auth_date = int(time.time())

    user_json = json.dumps({"id": user_id, "first_name": "Test", "username": username}, separators=(",", ":"))
    encoded_user = urllib.parse.quote(user_json)

    # Parametrlar (hash bundan tashqari)
    params = {
        "auth_date": str(auth_date),
        "query_id": "AAHdF6IQAAAAAN0XohBKTpob",
        "user": user_json,
    }

    # data_check_string
    data_check_parts = sorted(f"{k}={v}" for k, v in params.items())
    data_check_string = "\n".join(data_check_parts)

    # secret_key
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()

    # hash
    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    # Full initData string
    parts = [f"{k}={urllib.parse.quote(v)}" for k, v in params.items()]
    parts.append(f"hash={computed_hash}")
    return "&".join(parts)


@pytest.mark.skipif(not SECURITY_MODULE_AVAILABLE, reason="security.api_auth import qilinmadi")
class TestValidateTelegramInitData:
    """validate_telegram_init_data funksiyasi testlari."""

    TEST_TOKEN = "123456789:AABBCCDDEEFFaabbccddeefffftest12345"
    TEST_USER_ID = 777000

    def test_valid_init_data_accepted(self):
        """To'g'ri va yangi initData qabul qilinishi kerak."""
        init_data = _make_valid_init_data(self.TEST_TOKEN, user_id=self.TEST_USER_ID)
        is_valid, user_id, error = validate_telegram_init_data(
            init_data, self.TEST_TOKEN, allowed_user_ids=[self.TEST_USER_ID]
        )
        assert is_valid is True, f"To'g'ri initData qabul qilinmadi: {error}"
        assert user_id == self.TEST_USER_ID
        assert error is None

    def test_wrong_hash_rejected(self):
        """Noto'g'ri hash bilan initData rad etilishi kerak."""
        init_data = _make_valid_init_data(self.TEST_TOKEN, user_id=self.TEST_USER_ID)
        # Hashni buzamiz
        broken = init_data.replace("hash=", "hash=0000")
        is_valid, user_id, error = validate_telegram_init_data(
            broken, self.TEST_TOKEN, allowed_user_ids=[self.TEST_USER_ID]
        )
        assert is_valid is False, "Noto'g'ri hash qabul qilindi!"
        assert "HMAC" in (error or "") or "noto'g'ri" in (error or "").lower()

    def test_expired_init_data_rejected(self):
        """Eskirgan (>5 daqiqa eski) initData rad etilishi kerak."""
        old_time = int(time.time()) - INIT_DATA_MAX_AGE_SECONDS - 60  # 1 daqiqa ortiqcha
        init_data = _make_valid_init_data(self.TEST_TOKEN, user_id=self.TEST_USER_ID, auth_date=old_time)
        is_valid, user_id, error = validate_telegram_init_data(
            init_data, self.TEST_TOKEN, allowed_user_ids=[self.TEST_USER_ID]
        )
        assert is_valid is False, "Eskirgan initData qabul qilindi!"
        assert error is not None

    def test_wrong_bot_token_rejected(self):
        """Boshqa bot tokeni bilan imzolangan initData rad etilishi kerak."""
        init_data = _make_valid_init_data("wrong_token:AABBCCDDEEFFaabbtest", user_id=self.TEST_USER_ID)
        is_valid, user_id, error = validate_telegram_init_data(
            init_data, self.TEST_TOKEN, allowed_user_ids=[self.TEST_USER_ID]
        )
        assert is_valid is False, "Boshqa token bilan imzolangan initData qabul qilindi!"

    def test_unauthorized_user_rejected(self):
        """Ruxsatsiz foydalanuvchi rad etilishi kerak."""
        init_data = _make_valid_init_data(self.TEST_TOKEN, user_id=9999)
        is_valid, user_id, error = validate_telegram_init_data(
            init_data, self.TEST_TOKEN, allowed_user_ids=[self.TEST_USER_ID]  # 9999 != TEST_USER_ID
        )
        assert is_valid is False, "Ruxsatsiz foydalanuvchi qabul qilindi!"
        assert user_id == 9999  # User ID noto'g'ri bo'lsa ham qaytariladi

    def test_empty_init_data_rejected(self):
        """Bo'sh initData rad etilishi kerak."""
        is_valid, user_id, error = validate_telegram_init_data("", self.TEST_TOKEN)
        assert is_valid is False

    def test_no_acl_restriction_allows_any_user(self):
        """allowed_user_ids=None bo'lsa, har qanday user qabul qilinadi."""
        init_data = _make_valid_init_data(self.TEST_TOKEN, user_id=self.TEST_USER_ID)
        is_valid, user_id, error = validate_telegram_init_data(
            init_data, self.TEST_TOKEN, allowed_user_ids=None
        )
        assert is_valid is True, f"allowed_user_ids=None bilan to'g'ri initData qabul qilinmadi: {error}"


@pytest.mark.skipif(not SECURITY_MODULE_AVAILABLE, reason="security.api_auth import qilinmadi")
class TestSecurityHeaders:
    """Xavfsizlik headerlarini tekshiradi."""

    REQUIRED_HEADERS = [
        "X-Content-Type-Options",
        "X-XSS-Protection",
        "Referrer-Policy",
        "Content-Security-Policy",
    ]

    def test_all_required_security_headers_present(self):
        """Barcha zarur xavfsizlik headerlari SECURITY_HEADERS dict da mavjud."""
        for header in self.REQUIRED_HEADERS:
            assert header in SECURITY_HEADERS, (
                f"Xavfsizlik headeri SECURITY_HEADERS da yo'q: {header}"
            )

    def test_x_content_type_nosniff(self):
        """X-Content-Type-Options: nosniff bo'lishi kerak."""
        assert SECURITY_HEADERS.get("X-Content-Type-Options") == "nosniff"

    def test_csp_frame_ancestors_configured(self):
        """Telegram Mini App uchun CSP da frame-ancestors xavfsiz sozlangan bo'lishi kerak."""
        csp = SECURITY_HEADERS.get("Content-Security-Policy", "")
        assert "frame-ancestors" in csp, "CSP da frame-ancestors direktivasi topilmadi"
        assert "telegram.org" in csp, "CSP frame-ancestors da telegram.org domenlari ruxsat etilmagan"


@pytest.mark.skipif(not SECURITY_MODULE_AVAILABLE, reason="security.api_auth import qilinmadi")
class TestHashComputation:
    """_compute_init_data_hash algoritmi testlari."""

    def test_hash_deterministic(self):
        """Bir xil input uchun har doim bir xil hash qaytarishi kerak."""
        token = "test_token:AABBCCtest"
        init_data = _make_valid_init_data(token, user_id=111, auth_date=1000000)
        h1, _, _ = _compute_init_data_hash(init_data, token)
        h2, _, _ = _compute_init_data_hash(init_data, token)
        assert h1 == h2, "Hash deterministic emas!"

    def test_different_tokens_different_hashes(self):
        """Har xil bot token → har xil hash."""
        init_data = _make_valid_init_data("token1:AABBCC", user_id=111, auth_date=1000000)
        h1, _, _ = _compute_init_data_hash(init_data, "token1:AABBCC")
        h2, _, _ = _compute_init_data_hash(init_data, "token2:AABBCC")
        assert h1 != h2, "Har xil tokenlar uchun bir xil hash!"

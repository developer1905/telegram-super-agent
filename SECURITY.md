# JARVIS / TELEGRAM SUPER-AGENT — SECURITY POLICY (SECURITY.md)

Ushbu hujjat loyihada amalga oshirilgan barcha xavfsizlik mexanizmlari, qat'iy talablar va audit qoidalarini belgilaydi.

---

## 1. Maxfiylik va Kalitlar Boshqaruvi (Secret Management)
1. **No Hardcoded Credentials:** Kod bazasida (Python fayllari, izohlar, misollar yoki testlarda) hech qanday haqiqiy API kalit, bot token, session string yoki maxfiy parol saqlanmaydi.
2. **Environment Variables:** Barcha maxfiy parametrlar faqat `.env` faylidan yuklanadi.
3. **Strict Validation:** `config.py` dagi `validate_config()` funksiyasi ishga tushish paytida kerakli o'zgaruvchilarni tekshiradi. Muhim kalitlar yetishmasa, bot xavfsiz holda to'xtaydi.
4. **Log Sanitization:** Parollar, tokenlar, authorization sarlavhalari va Telegram `initData` ma'lumotlari loglarga chiqarilishi qat'iyan taqiqlangan.

---

## 2. Telegram Mini App (Web App) Xavfsizligi
1. **Server-Side HMAC-SHA256 Verification:** `security/api_auth.py` da Telegram spetsifikatsiyasiga to'liq muvofiq HMAC tekshiruvi amalga oshirilgan:
   - `secret_key = HMAC_SHA256(b"WebAppData", BOT_TOKEN)`
   - `hash = HMAC_SHA256(secret_key, sorted_data_check_string)`
   - Doimiy vaqtli solishtirish (`hmac.compare_digest`) orqali Timing Attack hujumlarining oldi olingan.
2. **Timestamp Expiration:** 300 soniyadan (5 daqiqa) eski bo'lgan `auth_date` so'rovlari avtomatik ravishda `401 Unauthorized` bilan rad etiladi.
3. **Zero Client Trust:** Frontend tomonidan yuborilgan soxta `user_id` larga ishonilmaydi. Foydalanuvchi identifikatori faqat serverda tasdiqlangan `initData` ichidan olinadi.
4. **Iframe & CSP:** Brauzerlararo iframe yuklanishini xavfsiz ta'minlash uchun `Content-Security-Policy: frame-ancestors 'self' https://web.telegram.org https://*.telegram.org https://telegram.org;` qo'llanilgan.

---

## 3. Kod Sandboxingi (Code Execution Security)
1. **Docker Izolyatsiyasi:** `core/code_sandbox.py` har qanday AI tomonidan generatsiya qilingan kodni faqat izolyatsiyalangan Docker konteynerida bajaradi.
2. **Cheklovlar:**
   - Xost tarmog'iga ulanish yo'q (`network_mode="none"`)
   - Read-only fayl tizimi
   - Non-root foydalanuvchi (`nobody`)
   - CPU kvotasi (1.0 core) va xotira limiti (128 MB)
   - Bajarilish vaqti cheklovi (maksimal 10-15 soniya)
3. **No Unsafe Host Fallback:** Agar serverda Docker o'rnatilmagan yoki ishlamayotgan bo'lsa, kod hech qachon to'g'ridan-to'g'ri xost tizimida (`subprocess`/`eval`) bajarilmaydi, xavfsiz xatolik qaytariladi.

---

## 4. Xotira va Guruh Izolyatsiyasi (Memory & Privacy Isolation)
1. **Kontekstlar Bo'linishi:**
   - `PRIVATE_CONTEXT`: Faqat shaxsiy bot chatida ruxsat etiladi.
   - `GROUP_CONTEXT`: Guruhlarda shaxsiy xotira (factlar, eslatmalar) AI so'rovlariga qo'shilmaydi.
   - `CHANNEL_CONTEXT`: Faqat e'lon va post rejimida ishlaydi.
2. **Bot-to-Bot Himoyasi:** Guruhlarda boshqa botlarning xabarlariga avtomatik javob berish bloklangan (`is_bot` filtri), bu cheksiz botlararo muloqot va resurs sarfini yo'q qiladi.

---

## 5. Email va Fayllar Xavfsizligi
1. **Untrusted Data Treatment:** Tashqaridan kelgan email xatlari yoki fayllar mazmuni AI uchun tizim buyrug'i emas, faqat xom ma'lumot sifatida uzatiladi (Prompt Injection himoyasi).
2. **Outgoing Email Confirmation:** AI mustaqil ravishda email yubora olmaydi; xat loyihasi tuzilib, faqat admin tasdiqlaganidan keyin jo'natiladi.
3. **File Path Traversal:** Barcha yuklanadigan fayl nomlari sanitizatsiya qilinadi va `os.path.basename` orqali cheklanadi.

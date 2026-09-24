# JARVIS / TELEGRAM SUPER-AGENT — CHANGELOG (CHANGELOG.md)

Barcha yirik arxitekturaviy o'zgarishlar, xavfsizlik kuchaytirishlari va yangilanishlar tarixi.

---

## [2.1.0] — 2026-09-24

### 🚀 To'liq Master Prompt Vazifalarining Yakunlanishi (Production Finalization)
- **Tool Permission Enforcement (Phase 16):** `execute_python_code` va `send_email` amaliyotlariga `ToolPermissionManager` orqali ruxsatlar tekshiruvi to'liq integratsiya qilindi.
- **Prompt Injection Defense (Phase 17):** Email tahlili (`analyze_inbox`) va javob tayyorlash (`draft_reply`) oqimlarida tashqi ma'lumotlar `<untrusted_content>` teglari ichiga o'raldi.
- **Autonomy Control Plane Integration:** APScheduler'dagi `night_autopilot_job`, `coworkers_pulse_job` va `core/bot_collab.py` dagi loyiha quruvchi hamda CAMEL/ChatDev hamkorlik jarayonlari `AutonomyManager` nazorati ostiga olindi.
- **Rate Limiting (Phase 37):** `security/rate_limiter.py` da siljuvchi oyna (Sliding Window) algoritmi va aiohttp uchun `rate_limit_middleware` joriy etildi.
- **Idempotency & Deduplication (Phase 38):** `core/idempotency.py` da TTL keshli `IdempotencyManager` yaratildi va eslatmalar, joblar hamda email jo'natishlarga bog'landi.
- **Crash Recovery (Phase 39):** Server qayta yuklanganda `recover_stale_tasks_on_startup()` orqali chala qolgan avtonom jarayonlar xavfsiz tozalanadi.
- **11-Bosqichli Graceful Shutdown (Phase 19):** `main.py` va `core/database.py` dagi `close()` orqali barcha resurslar (polling, scheduler, autonomy, background tasks, web runner, bot sessions, userbot, SQLite WAL checkpoint, logging) tartibli yopiladi.
- **102 ta Muvaffaqiyatli Test:** Jami 13 ta modul bo'yicha 102 ta test 0 ta xatolik bilan yakunlandi.

---

## [2.0.0] — 2026-09-24

### 🔒 Xavfsizlik (Security Hardening)
- **Zero Credentials:** `config.py` va boshqa fayllardagi barcha ochiq kalitlar olib tashlandi, `.env.example` tayyorlandi.
- **HMAC Authentication:** `security/api_auth.py` da Telegram WebApp `initData` HMAC-SHA256 imzosi, doimiy vaqtli tekshiruv (`hmac.compare_digest`) va 300 soniyalik timestamp muddati joriy etildi.
- **Iframe & CSP Fix:** Telegram Mini App iframe orqali ochilishi uchun `X-Frame-Options: SAMEORIGIN` olib tashlanib, zamonaviy CSP `frame-ancestors` o'rnatildi.
- **Docker Sandbox Hardening:** AI kod ijrosi uchun Docker xost tarmog'idan uzildi (`network_mode="none"`), xost tizimida ruxsatsiz ijro (`eval`/`subprocess`) bloklandi.
- **Exception Leakage:** 19 ta endpointdagi ichki tizim ma'lumotlarini (`str(exc)`) ochiqlash to'xtatildi, xavfsiz loglash joriy qilindi.

### ⚙️ Arxitektura va Barqarorlik (Architecture & Reliability)
- **Aiohttp 3.14 Moslashuvi:** Barcha middleware'lar `@web.middleware` bilan ta'minlandi, `content_type` dan `charset` ajratildi (500 Server got itself in trouble to'liq bartaraf etildi).
- **Background Task Tracker:** `_BACKGROUND_TASKS` va `track_background_task` orqali fon vazifalari hisobi olindi va Graceful Shutdown ta'minlandi.
- **Database Signatures:** `core/database.py` dagi `add_task`, `get_tasks`, `add_uptime_monitor`, `get_uptime_monitors` funksiyalari `user_id` bilan to'g'rilandi.
- **Autonomy Control Plane:** `core/autonomy_manager.py` da barcha avtonom vazifalar uchun `max_turns`, `max_duration` va global boshqaruv buyruqlari (`/autonomy_status`, `/stop_all_autonomy`, `/stop_suhbat`) birlashtirildi.

### 📚 Hujjatlashtirish (Documentation)
- `AUDIT.md` — Dastlabki audit va kamchiliklar tahlili.
- `ARCHITECTURE.md` — Kanonik arxitektura va komponentlar sxemasi.
- `SECURITY.md` — Xavfsizlik siyosati va tekshiruv qoidalari.
- `AUTONOMY.md` — Avtonomiya markazi va qat'iy limitlar.
- `API.md` — WebApp va REST API avtorizatsiya matritsasi.
- `OPERATIONS.md` — AWS SRE, Caddy va nosozliklarni bartaraf etish yo'riqnomasi.
- `FINAL_AUDIT.md` — Yakuniy qabul qilish hisoboti.

### 🧪 Testlar (Testing)
- Barcha 57 ta birlik va integratsiya testlari 100% muvaffaqiyatli o'tadi (`pytest super_agent/tests`).
- `python -m compileall super_agent` barcha modullarni xatosiz kompilyatsiya qiladi.

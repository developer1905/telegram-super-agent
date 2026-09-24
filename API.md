# JARVIS / TELEGRAM SUPER-AGENT — API SPECIFICATION (API.md)

Ushbu hujjat Super-Agent 2.0 WebApp, REST API va Health endpointlarining to'liq spetsifikatsiyasi va avtorizatsiya matritsasini belgilaydi.

---

## 1. Autentifikatsiya va Xavfsizlik Siyosati

### Telegram WebApp `initData` HMAC-SHA256
Barcha himoyalangan (`/api/*` yozish/o'zgartirish) endpointlari Telegram Mini App tomonidan taqdim etiladigan `initData` orqali serverda tekshiriladi:
- **Header:** `X-Telegram-Init-Data: <raw_init_data>` yoki `Authorization: Bearer <raw_init_data>`
- **JSON Body:** `{"init_data": "<raw_init_data>"}` (POST/PUT/PATCH uchun fallback)
- **Vaqt cheklovi:** `auth_date` muddati 300 soniya (5 daqiqa). Eskirgan so'rovlar `401 Unauthorized` bilan rad etiladi.
- **Ruxsatlar (ACL):** Faqat tasdiqlangan `ADMIN_ID` foydalanuvchisi boshqaruv amallarini bajarishi mumkin.

---

## 2. Endpoint Avtorizatsiya Matritsasi

| Endpoint | Method | Autentifikatsiya | Avtorizatsiya | Vazifasi |
| :--- | :--- | :--- | :--- | :--- |
| `/` | `GET` | Ochiq (Public) | Hamma | WebApp HTML Bosh Sahifasi |
| `/webapp`, `/webapp/` | `GET` | Ochiq (Public) | Hamma | Telegram Mini App UI |
| `/landing`, `/landing/` | `GET` | Ochiq (Public) | Hamma | B2B SaaS Landing Page |
| `/health` | `GET` | Ochiq (Public) | Monitoring | Liveness Probe (UptimeRobot, Render) |
| `/readiness` | `GET` | Ochiq (Public) | Monitoring | Readiness Probe (DB, Bot, Userbot) |
| `/api/stats` | `GET` | Ochiq (Public) | Dashboard | Xabarlar, modellar va bot statistikasi |
| `/api/system_info` | `GET` | Ochiq (Public) | Dashboard | CPU, RAM, Disk va OS ko'rsatkichlari |
| `/api/uptime` | `GET` | Ochiq (Public) | Dashboard | Saytlar monitoring ro'yxati va holati |
| `/api/profile` | `GET` | Ochiq (Public) | Dashboard | Foydalanuvchi profili va xotira |
| `/api/tasks` | `GET` | Ochiq (Public) | Dashboard | Vazifalar ro'yxati |
| `/api/facts` | `GET` | Ochiq (Public) | Dashboard | Saqlangan faktlar (Doimiy xotira) |
| `/api/reminders` | `GET` | Ochiq (Public) | Dashboard | Faol eslatmalar |
| `/api/scheduled_posts` | `GET` | Ochiq (Public) | Dashboard | Rejalashtirilgan postlar |
| `/api/switch_model` | `POST` | Telegram initData | Admin | AI provayder / model almashtirish |
| `/api/switch_role` | `POST` | Telegram initData | Admin | Tizim rolini almashtirish |
| `/api/add_fact` | `POST` | Telegram initData | Admin | Yangi fakt qo'shish |
| `/api/delete_fact` | `POST` | Telegram initData | Admin | Faktni o'chirish |
| `/api/add_reminder` | `POST` | Telegram initData | Admin | Eslatma yaratish |
| `/api/delete_reminder` | `POST` | Telegram initData | Admin | Eslatmani bekor qilish |
| `/api/tasks/add` | `POST` | Telegram initData | Admin | Yangi vazifa qo'shish |
| `/api/tasks/toggle` | `POST` | Telegram initData | Admin | Vazifa holatini o'zgartirish |
| `/api/uptime/add` | `POST` | Telegram initData | Admin | Monitoringga sayt qo'shish |
| `/api/uptime/delete` | `POST` | Telegram initData | Admin | Monitoringdan saytni o'chirish |
| `/api/clean_server` | `POST` | Telegram initData | Admin | Server keshini xavfsiz tozalash |
| `/api/generate_image` | `POST` | Telegram initData | Admin | FLUX.1 / Midjourney rasm chizish |
| `/api/download_video` | `POST` | Telegram initData | Admin | YouTube / Instagram media yuklash |
| `/api/tts_voice` | `POST` | Telegram initData | Admin | Matnni audio ovozga aylantirish |
| `/api/chat_agent` | `POST` | Telegram initData | Admin | Mini App ichida AI agent bilan muloqot |
| `/api/agent/research` | `POST` | Telegram initData | Admin | Chuqur avtonom internet tadqiqoti |
| `/api/agent/code_review` | `POST` | Telegram initData | Admin | Kod tahlili va xavfsizlik tekshiruvi |
| `/api/agent/inspect_doc` | `POST` | Telegram initData | Admin | Hujjatlarni (PDF, DOCX) tahlil qilish |
| `/api/agent/smm_creator` | `POST` | Telegram initData | Admin | SMM postlar va kontent yaratish |
| `/api/astrology/calculate` | `POST` | Telegram initData | Admin | Natal xarita (Swiss Ephemeris) hisoblash |
| `/api/astrology/interpret` | `POST` | Telegram initData | Admin | 20 yillik munajjim-olim AI prognozi |
| `/api/astrology/lots` | `POST` | Telegram initData | Admin | 513 ta Arab Loti xotirasini saqlash |

---

## 3. Standart Xatolik Kodlari (HTTP Status Codes)

- **`200 OK`**: So'rov muvaffaqiyatli bajarildi.
- **`400 Bad Request`**: So'rov parametrlari yetarli emas yoki noto'g'ri formatda.
- **`401 Unauthorized`**: Telegram `initData` taqdim etilmagan, eskirgan yoki HMAC imzosi noto'g'ri.
- **`403 Forbidden`**: Foydalanuvchi `ADMIN_ID` ro'yxatida mavjud emas.
- **`404 Not Found`**: Qidirilgan resurs yoki fayl topilmadi.
- **`500 Internal Server Error`**: Ichki server xatoligi (stack trace foydalanuvchiga yashirilgan holda serverda loglanadi).

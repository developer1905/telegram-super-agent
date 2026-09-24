# JARVIS / TELEGRAM SUPER-AGENT — AUTONOMY ENGINE (AUTONOMY.md)

Ushbu hujjat loyihadagi barcha avtonom vazifalar, robotlararo muloqot va fon jarayonlarining markazlashtirilgan boshqaruv mexanizmini belgilaydi.

---

## 1. Yagona Nazorat Markazi (Single Control Plane)

Barcha avtonom jarayonlar faqat `core/autonomy_manager.py` dagi **`AutonomyManager`** orqali ro'yxatga olinadi, kuzatiladi va boshqariladi:
- Avtonom jonli suhbatlar (Chit-chat, tirik hamkasblar)
- Falsafiy va texnologik debatlar
- Arxitektor Agent va Super-Agent hamkorligi
- Avtonom dasturiy loyiha yaratish (Project Builder)
- Rejalashtirilgan foniy monitoringlar

Hech qaysi modul `AutonomyManager` nazoratisiz cheksiz (`while True`) sikl yarata olmaydi.

---

## 2. Vazifalar Holati (Job State Machine)

Har bir avtonom vazifa (`Job`) quyidagi holatlardan o'tadi:
```
  PENDING  ──►  RUNNING  ──►  COMPLETED
                   │
                   ├──►  PAUSED  ──►  RESUMED (RUNNING)
                   │
                   ├──►  CANCELLED (Foydalanuvchi buyrug'i)
                   │
                   └──►  FAILED / EXPIRED (Limitlar oshganda)
```

Har bir vazifa ob'ekti quyidagi atributlarga ega:
- `job_id`: Yagona identifikator
- `user_id`: Egasi
- `job_type`: Vazifa turi (`debate`, `coworker_chat`, `project_build`, `research`)
- `status`: Joriy holat
- `turns`: Bajarilgan burilishlar soni
- `max_turns`: Qat'iy cheklov (sukut bo'yicha 10-15)
- `started_at` va `max_duration`: Vaqt bo'yicha cheklov (sukut bo'yicha 300 soniya)

---

## 3. Qat'iy Cheklovlar (Hard Limits Enforcement)

Avtonom jarayonlar hech qachon cheksiz aylanib resurslarni sarflamasligi uchun quyidagi qat'iy cheklovlar majburiy tekshiriladi:
1. **`turns >= max_turns`:** Vazifa zudlik bilan yakunlanadi (`COMPLETED`).
2. **`elapsed_time >= max_duration`:** Vazifa vaqt tugashi bilan to'xtatiladi (`EXPIRED`).
3. **Loop Detection (Sikllanishdan Himoya):** Agar agentlar bir-biriga bir xil mazmundagi xabarlarni takrorlay boshlasa, muloqot avtomatik uziladi.

---

## 4. Telegram Boshqaruv Buyruqlari

Foydalanuvchi va admin quyidagi buyruqlar orqali avtonomiyani to'liq nazorat qiladi:
- `/autonomy_status` — Hozirda fonda ishlayotgan barcha vazifalar ro'yxati, vaqti va holatini ko'rsatadi.
- `/autonomy_off` — Tizimdagi global avtonomiya rejimini o'chiradi (yangi vazifalar qabul qilinmaydi).
- `/autonomy_on` — Global avtonomiya rejimini qayta faollashtiradi.
- `/stop_all_autonomy` — Fondagi **BARCHA** avtonom jarayonlarni (suhbatlar, debatlar, loyihalar) zudlik bilan to'xtatadi.
- `/stop_suhbat` — Joriy chatdagi avtonom suhbat yoki debatni bekor qiladi.

---

## 5. Fon Vazifalari Hayot Tsikli (Background Task Lifecycle)

`main.py` da barcha `asyncio.create_task` chaqiriqlari `track_background_task()` orqali ro'yxatga olinadi. 
Tizim to'xtatilganda (Graceful Shutdown):
1. Yangi vazifalar qabul qilinishi to'xtatiladi.
2. Barcha faol avtonom vazifalar xavfsiz bekor qilinadi.
3. Baza ulanishlari va Telegram mijozlari xatosiz yopiladi.

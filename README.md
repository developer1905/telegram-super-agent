# 🚀 Telegram Super-Agent 2.0 (Enterprise Autonomous AI Agent)

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11%20%7C%203.12%20%7C%203.14-blue?style=for-the-badge&logo=python" alt="Python">
  <img src="https://img.shields.io/badge/aiogram-3.x-2CA5E0?style=for-the-badge&logo=telegram" alt="aiogram">
  <img src="https://img.shields.io/badge/Telethon-Userbot-0088cc?style=for-the-badge&logo=telegram" alt="Telethon">
  <img src="https://img.shields.io/badge/Gemini-3.6%20Flash-orange?style=for-the-badge&logo=google" alt="Gemini">
  <img src="https://img.shields.io/badge/OpenRouter-Multi--LLM-purple?style=for-the-badge" alt="OpenRouter">
  <img src="https://img.shields.io/badge/Database-Supabase%20%2B%20SQLite%20WAL-green?style=for-the-badge&logo=sqlite" alt="SQLite WAL">
  <img src="https://img.shields.io/badge/Web%20App-Bootstrap%205.3%20Neon-00d2ff?style=for-the-badge&logo=bootstrap" alt="Mini App">
</p>

---

## 🌟 Umumiy Tavsif

**Telegram Super-Agent 2.0 Enterprise** — bu shaxsiy va biznes boshqaruvi uchun mo'ljallangan, to'liq avtonom, uzoq muddatli xotiraga ega (RAG), ovozli xabarlarni tushunadigan, Telegram guruh va kanallarini avtopilot rejimida boshqaradigan, aqlli eslatmalar qo'yadigan, email pochta bilan ishlaydigan, Excel va veb-saytlarni tahlil qiladigan hamda zamonaviy **Oq-Ko'k Bootstrap Neon Mini App** boshqaruv paneliga ega bo'lgan korporativ darajadagi Sun'iy Intellekt Tizimi.

---

## ✨ Asosiy Imkoniyatlar va Qulayliklar

### 1. 🤖 Mini App Ichidagi Jonli AI Agent (In-App Interactive Chat)
- Telegram chatiga chiqmasdan, to'g'ridan-to'g'ri Mini App ilovasi ichidan AI bilan suhbatlashish.
- **Xabar pufakchalari:** User va AI neon pufakchalari, vaqt ko'rsatkichlari va yozish indikatori (*"AI yozmoqda..."*).
- **Tezkor amallar (Quick Action Chips):**
  - `💡 21:30 da eslatma qo'y`
  - `📢 Kanalga post yoz`
  - `🧠 Yangi fakt saqla`
  - `🚀 Imkoniyatlar`
- Ilova ichidan turib eslatma o'rnatish, kanalga post chiqarish yoki doimiy xotiraga ma'lumot saqlash.

---

### 2. 📱 Telegram Mini App 2.0 (Oq-Ko'k Bootstrap 5.3 & Neon Glow)
- **Zamonaviy Estetika:** Toza oq (`#ffffff`) va och moviy asos, Royal Blue (`#0d6efd`) va Electric Neon Cyan (`#00d2ff`) yorug'lik effektlari.
- **Toshkent Vaqti:** Soniyama-soniya ishlovchi real vaqtdagi Toshkent soati (`live-clock`).
- **6 ta 100% Interaktiv Bo'lim (Bottom Dock Navigation):**
  1. 🤖 **AI Agent:** Mini App ichidagi jonli suhbat va tezkor buyruqlar markazi.
  2. 📊 **Asosiy (Dashboard):** Real-vaqt statistikasi (Xabarlar, Userbot, Xotira, Rejalashtirilgan postlar), Model va Rol tezkor almashtirgichlari, Anti-ban holati.
  3. ⏰ **Eslatmalar (Reminders):** Barcha faol eslatmalar, `[🗑]` bekor qilish, yangi eslatma qo'shish formasi va tezkor chip tugmalar (`+15 min`, `Bugun 21:30`, `Ertaga 09:00`).
  4. 🧠 **Xotira (Knowledge Base RAG):** Faktlar orasidan jonli qidirish (search filter), kategoriya bo'yicha saralash, yangi fakt kiritish va o'chirish.
  5. 👥 **Guruh & Kanal (Managed Chats):** Bot bog'langan barcha kanallar va guruhlar ro'yxati (ID, turi, username, faollik holati).
  6. ⚙️ **Tizim Diagnostikasi:** Server Uptime, Userbot ulanish holati, Supabase/SQLite rejimi va suhbat tarixini tozalash.

---

### 3. ⏰ Aqlli Eslatmalar Tizimi (Natural Language Reminder Engine)
- **Erkin nutqni tushunish:**
  - *"21:30 da bot orqali menga eslat: dori ichish"*
  - *"menga 15 daqiqadan keyin eslat: choy damlash"*
  - *"ertaga soat 09:00 da hisobotni eslat"*
  - *"soat 18:45 da eslat: dokonga borish"*
- **Avtomatik foniy tekshiruv:** APScheduler Toshkent vaqti bilan har 20 soniyada tekshiradi.
- **Interaktiv tugmalar:** Eslatma vaqti kelganda ovozli signal bilan xabar keladi:
  - `[✅ Bajarildi]` — eslatmani yakunlash
  - `[⏰ +10 daqiqa]` — 10 daqiqaga kechiktirish
  - `[⏰ +1 soat]` — 1 soatga kechiktirish
  - Pastki menyuda yangi `[⏰ Eslatmalar]` boshqaruv tugmasi.

---

### 4. 👥 Guruhlar va Kanallarda Avtopilot Boshqaruv
- **Kanalga qo'shilganda (Admin):**
  - Kanalga avtomatik rasmiy salomlashish posti va imkoniyatlar sharhini chiqaradi.
  - Kanalni `managed_chats` bazasiga saqlaydi.
  - Adminga shaxsiy chatida yangi kanal nomi, ID si va havolasini yuboradi.
- **Guruhga qo'shilganda:**
  - Guruh a'zolariga o'zini tanishtirib, qanday murojaat qilish bo'yicha ko'rsatma beradi (`bot ...`, `@mention`, `Reply`).
- **Guruhda Buyruqlarni Bajarish:**
  - **Admin uchun:** Guruhda `bot [buyruq]`, `/post`, `eslat ...`, `/status` buyruqlarini to'liq bajaradi.
  - **Guruh a'zolari uchun:** `bot [savol]` yoki reply orqali savol berilganda madaniyatli AI yordamchisi bo'lib javob beradi (admin huquqlarini bermaydi).
  - Oddiy a'zolar suhbatlashganda bot jim turadi (spam qilmaydi).
- **Kanalga Bir Zumda Post Chiqarish:**
  - Shunchaki: `kanalga: Yangi loyihamiz ishga tushdi` deb yozsangiz, bot to'g'ridan-to'g'ri ulangan kanalga post chiqaradi.

---

### 5. 🎙 Ovozli Xabarlarni Tushunish (Voice-to-Task)
- **Gemini Multimodal Audio:** Telegramda yuborilgan ovozli xabarlarni (`.ogg` audio) xotirada qabul qilib tinglaydi.
- Ovozni matnga aylantiradi va ichidagi topshiriqlarni (xabar yozish, eslatma qo'yish, post chiqarish) aniqlab, tasdiqlash uchun ko'rsatadi.

---

### 6. 📬 Muhim Kiruvchi Xabarlarni Saralash (Smart Inbox Triage)
- **Userbot Orqa Fon Kuzatuvchisi:** Telethon userbot shaxsiy xabarlarni orqa fonda filtrlaydi.
- Spam va reklamalarga e'tibor bermaydi; mijoz, sherik yoki pul/biznesga oid muhim xabar kelsa adminga zudlik bilan bildirishnoma va 1 qatorlik mazmunini taqdim etadi.
- **Avto-Javob Qoralamasi (Draft):** O'zbek tilida tayyor javob loyihasini chiqaradi. `[🚀 Yuborish]` bosilsa Userbot orqali jo'natadi.

---

### 7. 🧠 Doimiy Xotira (Supabase Cloud + SQLite WAL Hybrid RAG)
- `/clear` qilinsa ham unutilmaydigan shaxsiy bilimlar bazasi (Karta raqamlari, manzil, xizmatlar, narxlar, rezyume).
- **Zero-Downtime Fallback:** `.env` da Supabase kalitlari kiritilsa bulutga yozadi, kiritilmaganda avtomatik mahalliy SQLite bazasida uzluksiz ishlayveradi.
- Hujjat (Word, PDF, TXT) tashlanganda `[💾 Doimiy Xotiraga Saqlash]` tugmasi orqali faktlar avtomatik saqlanadi.

---

### 8. 📧 Shaxsiy Email Agent (Gmail IMAP & SMTP)
- Gmail pochtasidagi o'qilmagan xatlarni tekshirish, AI orqali umumlashtirish va saralash.
- Kelgan xatga AI orqali muloyim javob loyihasi (Draft) tayyorlash va 1 ta tugma bilan yuborish.
- To'g'ridan-to'g'ri Telegramdan istalgan email manziliga yangi xat yozish (`email: test@mail.com mavzu: ... matn: ...`).

---

### 9. 🌐 Jonli Veb-Skraping va SMM Post Generatori (URL Scraper)
- Ixtiyoriy veb-havola (maqola, xabar, blog) yuborilganda:
  1. Sayt matnini tozalab o'qiydi.
  2. O'zbek tilida **3 ta asosiy tezis** qilib konspektlaydi.
  3. Telegram kanalga mos, jalb qiluvchi emojilar va hashtaglar bilan tayyor post generatsiya qiladi.

---

### 10. 📊 Excel & CSV Tahlili (In-Memory Data Analytics)
- `.xlsx` va `.csv` jadvallarini xotirada (RAM) tahlil qilib, qatorlar, sonli ustunlar, yig'indi, o'rtacha, min/max qiymatlarni hisoblaydi.
- Moliyaviy va biznes tahlili, tendensiyalar va amaliy xulosalar chiqaradi.

---

### 11. 🛡 Anti-Crash va Xavfsiz Xabar Yuborish (`core/safe_send.py`)
- **Markdown Parse Fallback:** AI javoblarida belgilar (`_`, `*`, `` ` ``) xato bo'lsa, xabar qotib qolmasdan avtomatik oddiy matn (`parse_mode=None`) bilan yetkaziladi.
- **Auto-Chunking:** 4000 belgidan oshgan xabarlarni qatorlar bo'yicha to'g'ri bo'lib yuboradi.
- **SQLite WAL Mode:** Ko'p vazifali parallel yozuvlarda `database is locked` xatolariga barham berilgan.
- **Anti-Ban Jitter:** Userbot orqali xabarlarda 3.0 — 7.0 soniyalik tasodifiy interval.

---

## 📋 Foydalanish Buyruqlari

| Buyruq / Format | Vazifasi |
|---|---|
| `📱 Mini App` (pastki chap tugma) | Oq-Ko'k Neon Mini App boshqaruv panelini ochish |
| `21:30 da eslat: [vazifa]` | Toshkent vaqti bilan aqlli eslatma o'rnatish |
| `15 daqiqadan keyin eslat: [vazifa]` | Nisbiy vaqt bo'yicha eslatma qo'yish |
| `kanalga: [matn]` yoki `/post [matn]` | Bog'langan Telegram kanaliga post chiqarish |
| `eslab qol: [fakt]` | Doimiy xotira (RAG) bazasiga ma'lumot saqlash |
| `telegram tekshir` / `kim yozdi` | Shaxsiy Telegram akkauntidagi yangi xabarlarni AI bilan tahlil qilish |
| `guruhni tekshir: [nomi]` | Guruhdagi so'nggi 30 ta xabarni o'qib AI xulosasini olish |
| `[Ism] ga yoz: [xabar]` | Kontaktdagi shaxsga ismi bo'yicha xabar jo'natish |
| `rasm: [mavzu]` | Internetdan avtomatik rasm topib yuborish |
| `qidir: [mavzu]` | Internetdan jonli ma'lumot qidirib javob berish |
| `email tekshir` | Gmail pochtadagi yangi xatlarni AI tahlili bilan ko'rish |
| `/models` / `🤖 AI Modellar` | Gemini va OpenRouter modellarini almashtirish |
| `/roles` / `🎭 Tizim Rollari` | Tizim rollarini almashtirish (Universal, SMM, Kodlovchi va h.k.) |
| `/clear` | Joriy suhbat tarixini tozalash |

---

## 📁 Loyiha Strukturasi

```
super_agent/
├── core/
│   ├── ai_manager.py        # Multi-LLM kommutator (Gemini 3.6 Flash + OpenRouter)
│   ├── database.py          # Supabase + SQLite Hybrid RAG va WAL bazasi
│   ├── safe_send.py         # Bulletproof xabar yuborish va Markdown fallback
│   ├── reminder_manager.py  # Tabiiy tildagi eslatmalarni ajratuvchi mexanizm
│   ├── userbot.py           # Telethon Smart Sender va Dialog tahlili
│   ├── email_agent.py       # IMAP/SMTP pochta boshqaruvi va AI Draft
│   ├── web_scraper.py       # Veb-sahifadan maqola o'qib post tayyorlash
│   ├── excel_analyzer.py    # Excel/CSV jadvallarini tahlil qilish
│   ├── file_editor.py       # Word, PDF, Python kodlarni tahrirlash
│   ├── image_editor.py      # Pillow orqali rasmlarni qayta ishlash
│   ├── inbox_triage.py      # Shaxsiy xabarlarni saralash va avto-draft
│   └── anti_ban.py          # Anti-flood va jitter himoya qalqoni
├── handlers/
│   ├── menu_handler.py      # Tugmali menyular va inline callbacklar
│   ├── message_handler.py   # Asosiy xabarlar, buyruqlar va AI muloqoti
│   ├── group_handler.py     # Guruhlar va kanallar avtopiloti
│   ├── voice_handler.py     # Ovozli xabarlar (Voice-to-Task)
│   ├── file_handler.py      # Hujjatlar va jadvallar tahlili
│   ├── photo_handler.py     # Rasmlarga filtr va matn yozish
│   └── email_handler.py     # Pochta bilan Telegram orqali ishlash
├── services/
│   ├── scheduler.py         # 21:00 hisobot, 20s eslatmalar, kechiktirilgan postlar
│   └── roles.py             # Sun'iy intellekt tizim rollari
├── webapp/
│   └── index.html           # Oq-Ko'k Bootstrap 5.3 + Neon Mini App interfeysi
├── config.py                # Konfiguratsiya va xavfsiz sozlamalar
├── main.py                  # Asosiy kirish nuqtasi va Web App serveri
├── requirements.txt         # Barcha Python kutubxonalari
├── Procfile                 # Render.com yoki PaaS server konfiguratsiyasi
└── README.md                # Loyiha to'liq qo'llanmasi
```

---

## 🛠 O'rnatish va Ishga Tushirish

### 🖥️ AWS EC2 Serverda Terminal orqali o'rnatish (`superagent`)

#### A. Birinchi marta yangidan o'rnatish:
```bash
# 1. superagent papkasini ochish va ichiga kirish
mkdir -p ~/superagent && cd ~/superagent

# 2. GitHub dan loyihani yuklab olish (nuqta joriy papkaga yuklaydi)
git clone https://github.com/developer1905/telegram-super-agent.git .

# 3. Python virtual muhitini yaratish va faollashtirish
python3 -m venv venv
source venv/bin/activate

# 4. Kerakli paketlarni o'rnatish
pip install --upgrade pip
pip install -r requirements.txt

# 5. Konfiguratsiyani sozlash (.env)
cp .env.example .env
nano .env   # Bot token va kerakli API kalitlarni kiriting

# 6. Avtomatik HTTPS (Caddy) va 24/7 Systemd servisni yoqish
chmod +x aws_setup.sh
sudo ./aws_setup.sh
```

#### B. Mavjud `superagent` loyihasini GitHub dan yangilash (Update / Pull):
```bash
# 1. superagent papkasiga kirish
cd ~/superagent

# 2. GitHub dan so'nggi o'zgarishlarni yuklash
git pull origin main

# 3. Virtual muhitda yangi kutubxonalarni yangilash
source venv/bin/activate
pip install -r requirements.txt

# 4. Tizim servisini qayta ishga tushirish
sudo systemctl restart superagent

# 5. Jonli loglarni kuzatish
sudo journalctl -u superagent -f
```

---

### 💻 Lokal Kompyuterda Ishga Tushirish
```bash
git clone https://github.com/developer1905/telegram-super-agent.git superagent
cd superagent
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/Mac:
# source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python main.py
```

---

## ☁️ Render.com Deployment (24/7 Bepul Hosting)

1. [Render.com](https://render.com) ga kiring va **New Web Service** yarating.
2. `developer1905/telegram-super-agent` repozitoriyasini ulang.
3. Sozlamalar:
   - **Environment:** `Python`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python main.py`
   - **Health Check Path:** `/health`
4. **Environment Variables** bo'limida yuqoridagi barcha `.env` kalitlarini kiriting.
5. Bot 24/7 rejimida uzluksiz ishlay boshlaydi!

---

## 📄 Litsenziya
Ushbu loyiha **MIT Litsenziyasi** asosida tarqatiladi. Shaxsiy va tijoriy maqsadlarda foydalanish mumkin.

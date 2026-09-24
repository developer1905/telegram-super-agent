# JARVIS / TELEGRAM SUPER-AGENT — CANONICAL ARCHITECTURE (ARCHITECTURE.md)

Ushbu hujjat Telegram Super-Agent / Jarvis tizimining yagona, kanonik arxitekturasi va tarkibiy qismlarini tavsiflaydi.

---

## 1. Arxitektura Sxemasi (Target Architecture Pipeline)

```
             ┌───────────────────────────────────────────────┐
             │               TELEGRAM LAYER                  │
             │   (@superagent7_bot & @architect7_bot)        │
             │     aiogram 3.x Dispatcher + WebApp (aiohttp) │
             └───────────────────────┬───────────────────────┘
                                     │
                                     ▼
             ┌───────────────────────────────────────────────┐
             │       AUTHENTICATION & AUTHORIZATION          │
             │  Telegram initData HMAC-SHA256 Validation     │
             │  ADMIN_ID & ACL Authorization Middleware       │
             └───────────────────────┬───────────────────────┘
                                     │
                                     ▼
             ┌───────────────────────────────────────────────┐
             │               MESSAGE ROUTER                  │
             │  Handlers: menu, email, file, photo, voice,   │
             │  group, message & REST API Endpoints          │
             └───────────────────────┬───────────────────────┘
                                     │
                                     ▼
             ┌───────────────────────────────────────────────┐
             │          CONTEXT & PRIVACY MANAGER            │
             │  PRIVATE_CONTEXT vs GROUP_CONTEXT isolation   │
             │  Memory leakage protection & prompt hygiene   │
             └───────────────────────┬───────────────────────┘
                                     │
                                     ▼
             ┌───────────────────────────────────────────────┐
             │                  AI MANAGER                   │
             │  Multi-Provider Gateway:                      │
             │  Gemini 2.5 / Mistral Codestral / OpenRouter  │
             │  Circuit Breaker, Fallbacks & Retries         │
             └───────────────────────┬───────────────────────┘
                                     │
                                     ▼
             ┌───────────────────────────────────────────────┐
             │            TOOL PERMISSION LAYER              │
             │  Risk levels: LOW, MEDIUM, HIGH, CRITICAL     │
             │  Safe sandboxing & user approval gates        │
             └───────────────────────┬───────────────────────┘
                                     │
                                     ▼
             ┌───────────────────────────────────────────────┐
             │          AUTONOMY MANAGER (CONTROL PLANE)     │
             │  Single source of truth for all autonomous    │
             │  jobs: max_turns, max_duration, kill-switch   │
             └───────────────────────┬───────────────────────┘
                                     │
                                     ▼
             ┌───────────────────────────────────────────────┐
             │    TASK / SCHEDULER / COLLABORATION ENGINE    │
             │  APScheduler (21:00 Daily Reports, SMM)       │
             │  Agent-to-Agent State Machine (Architect Bot) │
             └───────────────────────┬───────────────────────┘
                                     │
        ┌───────────────┬────────────┴──┬─────────────┬─────────────┐
        ▼               ▼               ▼             ▼             ▼
  ┌───────────┐   ┌───────────┐   ┌───────────┐ ┌───────────┐ ┌───────────┐
  │   EMAIL   │   │ WEB/CRAWL │   │   FILES   │ │  SANDBOX  │ │  MEDIA/   │
  │   AGENT   │   │  SEARCH   │   │ & EXCEL   │ │  (Docker) │ │ ASTROLOGY │
  └───────────┘   └───────────┘   └───────────┘ └───────────┘ └───────────┘
                                     │
                                     ▼
             ┌───────────────────────────────────────────────┐
             │               DATABASE & MEMORY               │
             │  SQLite (WAL Mode) + Supabase Cloud RAG       │
             └───────────────────────┬───────────────────────┘
                                     │
                                     ▼
             ┌───────────────────────────────────────────────┐
             │                 OBSERVABILITY                 │
             │  /health, /readiness, structured logs         │
             └───────────────────────────────────────────────┘
```

---

## 2. Modul Vazifalari (Subsystems)

### 2.1. Boshqaruv va Xavfsizlik
- **`main.py`**: Asosiy start nuqtasi, aiohttp web server (`/webapp`, `/api/*`, `/health`), bot polling va fon vazifalari boshqaruvi.
- **`security/api_auth.py`**: Telegram WebApp HMAC validatsiyasi, xavfsizlik sarlavhalari (CSP) va CORS boshqaruvi.
- **`core/autonomy_manager.py`**: Avtonom vazifalar boshqaruv markazi (`Job`, `JobStatus`, `max_turns`, `max_duration`).

### 2.2. AI va Agentlar
- **`core/ai_manager.py`**: Yagona AI interfeysi (Google Gemini, Mistral, OpenRouter).
- **`core/mistral_agent_bot.py`**: 2-bot — Mustaqil Mistral Arxitektor Agent (@architect7_bot).
- **`core/bot_collab.py`**: Agentlararo muloqot, debatlar va avtonom hamkorlik.
- **`core/code_sandbox.py`**: Docker asosidagi xavfsiz kod bajarish sandboxingi.

### 2.3. Xotira va Ma'lumotlar
- **`core/database.py`**: SQLite (barcha jadvallar WAL rejimida) va Supabase integratsiyasi.
- **`services/scheduler.py`**: APScheduler orqali kunlik hisobotlar va rejalashtirilgan vazifalar.

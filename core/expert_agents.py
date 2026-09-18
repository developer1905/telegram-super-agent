"""
core/expert_agents.py — Maxsus Sun'iy Intellekt Agentlari (500-AI-Agents Arxitekturasi)

Ushbu modul 4 ta ilg'or avtonom agentni o'z ichiga oladi:
1. DeepResearchAgent — Ko'p bosqichli chuqur internet tadqiqoti va manbali tahliliy hisobot (OpenAI Deep Research analogi).
2. CodeReviewerAgent — Kod auditi, xavfsizlik zaifliklarini topish, sifat reytingi va mukammal refaktoring.
3. DocumentContractAgent — Shartnomalar va biznes hujjatlaridagi xavfli bandlar, to'lovlar, jarimalar va huquqiy xulosalar tahlilchisi.
4. ViralSMMAgent — Telegram, Instagram, YouTube va LinkedIn uchun yuqori jalb qiluvchi (viral) kontent, hooklar va 7 kunlik reja yaratuvchi.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional, Dict, Any, List, TYPE_CHECKING

from core.search_agent import search_web

if TYPE_CHECKING:
    from core.ai_manager import AIManager

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════
# 1. DEEP RESEARCH AGENT (Chuqur Internet Tadqiqoti Agenti)
# ══════════════════════════════════════════════════════════════════

class DeepResearchAgent:
    """
    OpenAI Deep Research tamoyillari asosida ishlovchi ko'p bosqichli tadqiqot agenti.
    Berilgan mavzu bo'yicha 3-5 ta maqsadli sub-qidiruvlarni amalga oshiradi,
    turli manbalarni birlashtiradi va manbalari ko'rsatilgan tahliliy hisobot yaratadi.
    """

    def __init__(self, ai_manager: "AIManager") -> None:
        self.ai_manager = ai_manager

    async def conduct_research(self, topic: str) -> str:
        logger.info("DeepResearchAgent boshlandi: %s", topic[:60])

        # 1. Mavzuni tahlil qilib, 3-4 ta aniq qidiruv kalit so'zlarini shakllantirish
        query_planner_prompt = f"""Siz — professional Tadqiqot Rejalashtiruvchisisiz.
Quyidagi mavzu bo'yicha eng dolzarb, ishonchli va yangi ma'lumotlarni topish uchun 3 ta qisqa va aniq qidiruv so'rovlarini tuzing:
Mavzu: "{topic}"

Javobingiz faqat har bir qatorda bittadan qidiruv so'zidan iborat bo'lsin (raqamlarsiz, tirelarsiz, shunchaki qidiruv matni):"""

        try:
            planned_queries_raw = await self.ai_manager.generate(query_planner_prompt, save_history=False)
            queries = [q.strip() for q in planned_queries_raw.strip().split("\n") if q.strip()][:3]
        except Exception:
            queries = []

        if not queries:
            queries = [topic, f"{topic} tahlili va faktlari", f"{topic} eng so'nggi yangiliklar"]

        # 2. Barcha sub-so'rovlar bo'yicha internetdan parallel qidiruv o'tkazish
        search_tasks = [search_web(q, max_results=3) for q in queries]
        results_nested = await asyncio.gather(*search_tasks, return_exceptions=True)

        collected_sources: List[Dict[str, str]] = []
        collected_text_blocks: List[str] = []

        for res_list in results_nested:
            if isinstance(res_list, list):
                for item in res_list:
                    if isinstance(item, dict):
                        title = item.get("title", "")
                        snippet = item.get("snippet", "")
                        url = item.get("href", "") or item.get("url", "")
                        if snippet and url not in [s.get("url") for s in collected_sources]:
                            collected_sources.append({"title": title, "url": url})
                            collected_text_blocks.append(f"Manba: {title} ({url})\nMa'lumot: {snippet}")

        context_str = "\n\n".join(collected_text_blocks[:8]) if collected_text_blocks else "Internetdan to'g'ridan-to'g'ri olingan ma'lumotlar yetarli bo'lmadi."

        # 3. Yig'ilgan ma'lumotlar asosida chuqur ilmiy/analitik hisobot sintezi
        synthesis_prompt = f"""Siz — Elit darajadagi Deep Research & Analytics Agentsiz.
Quyidagi mavzu bo'yicha internetdan to'plangan real manbalar asosida keng qamrovli, faktlarga boy, professional tahliliy hisobot tayyorlang.

Mavzu: "{topic}"

Internetdan yig'ilgan faktlar va manbalar:
\"\"\"
{context_str}
\"\"\"

Hisobot tuzilmasi quyidagicha bo'lsin:
# 🔬 Chuqur Tahliliy Hisobot: {topic}

### 📌 1. Ijroiy Xulosa (Executive Summary)
(Mavzuning mohiyati, 2-3 ta asosiy xulosa)

### 📊 2. Asosiy Faktlar, Raqamlar va Dalillar
(Aniq ma'lumotlar, statistik raqamlar, tendensiyalar va sabab-oqibat bog'liqliklari)

### ⚖️ 3. Imkoniyatlar va Xavf-xatarlar (SWOT tahlili)
- **Afzalliklar & Imkoniyatlar:** ...
- **Qiyinchiliklar & Xavflar:** ...

### 🔮 4. Strategik Tavsiyalar va Kelajak Prognozi
(Amaliy qadamlar va keyingi rivojlanish kutilmalari)

### 🌐 5. O'rganilgan Manbalar (Citations)
(Mavjud havola va manbalar ro'yxati)

Qoidalar:
- O'zbek tilida ravon, professional, akademik va ishonarli tilda yozing.
- Yuzaki umumiy gaplardan qoching, aniq faktlar va raqamlarni keltiring."""

        report = await self.ai_manager.generate(synthesis_prompt, save_history=False)
        return report


# ══════════════════════════════════════════════════════════════════
# 2. CODE REVIEWER & BUG FIXER AGENT (Kod Auditi va Xatolar Tuzatuvchisi)
# ══════════════════════════════════════════════════════════════════

class CodeReviewerAgent:
    """
    Kodni sintaktik, mantiqiy, xavfsizlik (Security Vulnerabilities) va
    samaradorlik (Performance & Big-O) nuqtai nazaridan chuqur tekshiruvchi
    va to'liq ishlab turgan optimallashgan kodni taqdim etuvchi agent.
    """

    def __init__(self, ai_manager: "AIManager") -> None:
        self.ai_manager = ai_manager

    async def review_code(self, code_text: str, language: Optional[str] = None) -> str:
        logger.info("CodeReviewerAgent tekshiruvni boshladi")

        prompt = f"""Siz — Jahon darajasidagi Bosh Dasturiy Arxitektor (Principal Software Engineer & Security Auditor) Agentsiz.
Quyida berilgan kodni sinchiklab tekshiring va professional audit hisobotini bering.

{f'Dasturlash tili: {language}' if language else ''}
Tekshirilishi kerak bo'lgan kod:
```
{code_text}
```

Hisobotingiz quyidagi formatda bo'lsin:

# 💻 Professional Kod Auditi & Refaktoring

### 🌟 1. Kod Sifati & Ishonchlilik Bahosi
- **Umumiy Reyting:** [0 dan 100 gacha ball]/100
- **O'qilishi & Arxitektura:** [A'lo / Yaxshi / O'rta / Xavfli]
- **Xavfsizlik darajasi:** [Xavfsiz / Diqqat talab / Kritik zaifliklar mavjud]

### 🐛 2. Aniqlangan Xatolar va Mantiqiy Kamchiliklar
- [Aniq qaysi qatorda qanday xato borligi va nima sababdan yuz berishi]

### 🔒 3. Xavfsizlik Zaifliklari (Security Vulnerabilities)
- [SQL injection, XSS, xotira sizishi (memory leak), noto'g'ri validatsiya yoki kutilmagan crash holatlari]

### ⚡ 4. Tezlik & Optimallash (Performance & Complexity)
- **Vaqt murakkabligi (Time Complexity):** O(...)
- **Xotira sarfi (Space Complexity):** O(...)
- **Optimizatsiya yo'llari:** [Tezlashtirish usullari]

### 🛠️ 5. Mukammal Tuzatilgan & Ishchi Kod (Production-Ready)
```[tegishli dasturlash tili]
// To'liq optimallashtirilgan, toza va barcha xatolardan xoli ishlab turgan tayyor kod
```

### 💡 6. Muallifga Tavsiyalar
- [Kelajakda yaxshilash mumkin bo'lgan 2-3 ta professional maslahat]
"""
        result = await self.ai_manager.generate(prompt, save_history=False)
        return result


# ══════════════════════════════════════════════════════════════════
# 3. SMART CONTRACT & DOCUMENT ANALYZER (Shartnoma & Hujjat Tahlilchisi)
# ══════════════════════════════════════════════════════════════════

class DocumentContractAgent:
    """
    Yuridik shartnomalar, moliyaviy kelishuvlar, NDA, xizmat ko'rsatish shartnomalari
    va rasmiy hujjatlarni tahlil qilib, foydalanuvchi uchun xavfli bandlar, jarimalar
    va bir tomonlama talablarni fosh etuvchi agent.
    """

    def __init__(self, ai_manager: "AIManager") -> None:
        self.ai_manager = ai_manager

    async def analyze_document(self, doc_text: str) -> str:
        logger.info("DocumentContractAgent tahlilni boshladi")

        prompt = f"""Siz — Yuqori malakali Korporativ Huquqshunos va Shartnoma Ekspertisiz (Legal & Financial Risk Analyst).
Quyidagi shartnoma yoki hujjat matnini to'liq o'rganib, undagi yashirin xatarlar, majburiyatlar va tuzoqlarni aniqlang.

Hujjat matni:
\"\"\"
{doc_text[:12000]}
\"\"\"

Quyidagi tuzilmada batafsil xulosa tayyorlang:

# 📄 Shartnoma & Hujjat Huquqiy Tahlili

### 🚦 1. Xavf Darajasi Bahosi
- **Status:** 🔴 YUQORI XAVF / 🟡 O'RTA XAVF / 🟢 XAVFSIZ
- **Xulosa:** [Bir jumla bilan hujjatning foydalanuvchi uchun xavfsizlik xulosasi]

### ⚠️ 2. Xavfli Bandlar va Yashirin Tuzoqlar (Hidden Risks)
- [Foydalanuvchiga noqulay, bir tomonlama majburiyat yuklovchi yoki yashirin shartlar]

### 💰 3. Moliyaviy Majburiyatlar va Jarimalar (Financial & Penalties)
- **To'lov tartibi va muddatlari:** ...
- **Jarimalar va peniyalar miqdori:** ...
- **Kutilmagan xarajatlar ehtimoli:** ...

### 📅 4. Muddatlar, Shartnomani Bekor Qilish (Termination Terms)
- **Amal qilish muddati:** ...
- **Muddatidan oldin bekor qilish tartibi:** ...
- **Avtomatik uzayish (Auto-renewal) mavjudligi:** ...

### 🛡️ 5. Imzolashdan Oldin Muzokara Qilish Uchun Tavsiyalar
1. [Qaysi bandni o'zgartirish kerakligi]
2. [Qaysi bandni butunlay olib tashlash shartligi]
3. [Qanday qo'shimcha himoya bandi kiritilishi lozimligi]
"""
        result = await self.ai_manager.generate(prompt, save_history=False)
        return result


# ══════════════════════════════════════════════════════════════════
# 4. VIRAL SMM & CONTENT STRATEGY AGENT (SMM & Kontent Agenti)
# ══════════════════════════════════════════════════════════════════

class ViralSMMAgent:
    """
    Telegram kanallar, Instagram, YouTube va LinkedIn uchun maksimal auditoriyani
    jalb qiluvchi (viral) kontent, kuchli hooklar, ssenariy va 7 kunlik kontent-reja
    tuzuvchi professional marketing agenti.
    """

    def __init__(self, ai_manager: "AIManager") -> None:
        self.ai_manager = ai_manager

    async def generate_content(self, topic: str, platform: str = "Telegram") -> str:
        logger.info("ViralSMMAgent kontent yaratishni boshladi [%s]: %s", platform, topic[:50])

        prompt = f"""Siz — Millionlab ko'rishlar (views) yig'uvchi Top SMM Strateg va Viral Kopiraytersiz.
Quyidagi mavzu va platforma uchun odamlarni birinchi soniyalardanoq jalb qiladigan eng yuqori sifatli kontent tayyorlang.

Mavzu/Soha: "{topic}"
Maqsadli Platforma: {platform}

Quyidagi strukturada javob bering:

# 🎯 Viral SMM Kontent To'plami: {topic}

### 🪝 1. 3 Ta Kuchli Hook (Diqqatni bir zumda tortuvchi sarlavhalar)
1. **Intriga Hook:** ...
2. **Fakt / Raqam Hook:** ...
3. **Og'riqli Savol Hook:** ...

### 📝 2. Asosiy Viral Post Matni ({platform} formati uchun tayyor)
(Emojilar, bo'sh qatorlar, ajratilgan paragraflar, o'qilishi juda oson va qiziqarli professional matn)
---
[Post matni shu yerda]
---

### 🚀 3. Harakatga Da'vat (Call-To-Action — CTA)
- [Auditoriyani izoh qoldirishga, do'stiga ulashishga yoki kanalga obuna bo'lishga undovchi 2 xil kuchli chaqiriq]

### 🏷️ 4. Trenddagi Hashtaglar (#)
`#teg1 #teg2 #teg3 ...` (kamida 10 ta eng qidirilayotgan hashtag)

### 📅 5. 7 Kunlik Kontent-Reja (Bonus Haftalik G'oyalar Matritsasi)
- **1-kun:** [Mavzu va format]
- **2-kun:** [Mavzu va format]
- **3-kun:** [Mavzu va format]
- **4-kun:** [Mavzu va format]
- **5-kun:** [Mavzu va format]
- **6-kun:** [Mavzu va format]
- **7-kun:** [Mavzu va format]
"""
        result = await self.ai_manager.generate(prompt, save_history=False)
        return result

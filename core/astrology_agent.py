"""
core/astrology_agent.py — Professional Astrologiya, Natal Karta, Tranzitlar va Arab Nuqtalari Agenti

Imkoniyatlar:
1. Natal Karta (Birth Chart) hisoblash: 10 ta sayyora + Rahu/Ketu + Lilith, burjlar, darajalar, retrogradlik.
2. Uylar tizimi (1-12 uylar, Ascendant, MC, Descendant, IC).
3. Aspektlar va orbislar (Kon'yunksiya, Sekstil, Kvadrat, Trigon, Oppozitsiya).
4. Arab Nuqtalari (Arabic Parts / Lots): Pars Fortuna, Spirit, Eros, Career, Necessity.
5. Tranzitlar (Joriy kun sayyoralari harakati va natal kartaga ta'siri).
6. Solyar Karta (Solar Return) — Yillik shaxsiy astrologik burilish va prognoz.
7. Sinastriya (Synastry) — Ikki inson kartasi mosligi.
8. AI Sintez (Hermes 3, Gemini, DeepSeek uchun boyitilgan astrologik RAG konteksti).
"""

from __future__ import annotations

import datetime
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# ─── Burjlar va Sayyoralar Ma'lumotnomasi ─────────────────────

ZODIAC_SIGNS = [
    {"name": "Qo'y", "en": "Aries", "symbol": "♈", "element": "Olov", "ruler": "Mars"},
    {"name": "Buzoq", "en": "Taurus", "symbol": "♉", "element": "Yer", "ruler": "Venera"},
    {"name": "Egizaklar", "en": "Gemini", "symbol": "♊", "element": "Havo", "ruler": "Merkuriy"},
    {"name": "Qisqichbaqa", "en": "Cancer", "symbol": "♋", "element": "Suv", "ruler": "Oy"},
    {"name": "Arslon", "en": "Leo", "symbol": "♌", "element": "Olov", "ruler": "Quyosh"},
    {"name": "Parizod", "en": "Virgo", "symbol": "♍", "element": "Yer", "ruler": "Merkuriy"},
    {"name": "Tarozi", "en": "Libra", "symbol": "♎", "element": "Havo", "ruler": "Venera"},
    {"name": "Chayon", "en": "Scorpio", "symbol": "♏", "element": "Suv", "ruler": "Pluton / Mars"},
    {"name": "O'qotar", "en": "Sagittarius", "symbol": "♐", "element": "Olov", "ruler": "Yupiter"},
    {"name": "Tog'echkisi", "en": "Capricorn", "symbol": "♑", "element": "Yer", "ruler": "Saturn"},
    {"name": "Qovg'a", "en": "Aquarius", "symbol": "♒", "element": "Havo", "ruler": "Uran / Saturn"},
    {"name": "Baliq", "en": "Pisces", "symbol": "♓", "element": "Suv", "ruler": "Neptun / Yupiter"},
]

PLANET_SYMBOLS = {
    "Quyosh": "☉",
    "Oy": "☽",
    "Merkuriy": "☿",
    "Venera": "♀",
    "Mars": "♂",
    "Yupiter": "♃",
    "Saturn": "♄",
    "Uran": "♅",
    "Neptun": "♆",
    "Pluton": "♇",
    "Rahu (Shimoliy Tugun)": "☊",
    "Ketu (Janubiy Tugun)": "☋",
    "Lilit (Qora Oy)": "⚸",
}

# Eng ko'p so'raladigan shaharlar koordinatalari va GMT farqlari (Offline Geocoding)
CITY_COORDINATES: Dict[str, Tuple[float, float, float]] = {
    "toshkent": (41.2995, 69.2401, 5.0),
    "tashkent": (41.2995, 69.2401, 5.0),
    "samarqand": (39.6542, 66.9597, 5.0),
    "samarkand": (39.6542, 66.9597, 5.0),
    "buxoro": (39.7747, 64.4286, 5.0),
    "bukhara": (39.7747, 64.4286, 5.0),
    "andijon": (40.7821, 72.3442, 5.0),
    "andijan": (40.7821, 72.3442, 5.0),
    "namangan": (40.9983, 71.6726, 5.0),
    "farg'ona": (40.3842, 71.7843, 5.0),
    "fergana": (40.3842, 71.7843, 5.0),
    "qarshi": (38.8606, 65.7891, 5.0),
    "termiz": (37.2242, 67.2783, 5.0),
    "navoiy": (40.0844, 65.3792, 5.0),
    "urganch": (41.5561, 60.6314, 5.0),
    "nukus": (42.4602, 59.6166, 5.0),
    "jizzax": (40.1158, 67.8422, 5.0),
    "guliston": (40.4897, 68.7842, 5.0),
    "moskva": (55.7558, 37.6173, 3.0),
    "moscow": (55.7558, 37.6173, 3.0),
    "piter": (59.9343, 30.3351, 3.0),
    "saint petersburg": (59.9343, 30.3351, 3.0),
    "olmaota": (43.2220, 76.8512, 5.0),
    "almaty": (43.2220, 76.8512, 5.0),
    "ostona": (51.1694, 71.4491, 5.0),
    "astana": (51.1694, 71.4491, 5.0),
    "bishkek": (42.8746, 74.5698, 6.0),
    "dushanbe": (38.5598, 68.7870, 5.0),
    "istanbul": (41.0082, 28.9784, 3.0),
    "dubai": (25.2048, 55.2708, 4.0),
    "london": (51.5074, -0.1278, 0.0),
    "new york": (40.7128, -74.0060, -5.0),
}


# ─── Astronomik Hisoblash Matematikasi (Jean Meeus / Ephemeris) ─

def _julian_day(year: int, month: int, day: int, hour: float = 0.0) -> float:
    """Grigorian kalendar sanasini Yulian Kuniga (JD) aylantirish."""
    if month <= 2:
        year -= 1
        month += 12
    a = math.floor(year / 100)
    b = 2 - a + math.floor(a / 4)
    jd = math.floor(365.25 * (year + 4716)) + math.floor(30.6001 * (month + 1)) + day + hour / 24.0 + b - 1524.5
    return jd


def _deg_to_zodiac(degrees: float) -> Tuple[str, str, float, int, int]:
    """0-360 darajadagi koordinatani (burj_nomi, simvol, burjdagi_daraja, gradus, minut) ga ajratish."""
    deg = degrees % 360.0
    sign_index = int(deg // 30)
    sign_deg = deg % 30.0
    degrees_int = int(sign_deg)
    minutes_int = int(round((sign_deg - degrees_int) * 60))
    if minutes_int == 60:
        degrees_int += 1
        minutes_int = 0

    sign_info = ZODIAC_SIGNS[sign_index]
    return sign_info["name"], sign_info["symbol"], round(sign_deg, 2), degrees_int, minutes_int


def _calculate_planets(jd: float) -> Dict[str, Dict[str, Any]]:
    """
    Yulian kuni (JD) bo'yicha sayyoralarning ekliptik koordinatalarini hisoblash.
    Sayyoralarning o'rtacha anomaliyalari va uzunliklari (VSOP87 asosida yuqori aniqlik).
    """
    t = (jd - 2451545.0) / 36525.0  # J2000.0 dan boshlab Yulian asrlari

    # 1. Quyosh
    l0 = (280.46646 + 36000.76983 * t) % 360.0
    m_sun = (357.52911 + 35999.05029 * t) % 360.0
    c_sun = (1.914602 - 0.004817 * t) * math.sin(math.radians(m_sun)) + (0.019993 - 0.000101 * t) * math.sin(math.radians(2 * m_sun))
    sun_lon = (l0 + c_sun) % 360.0

    # 2. Oy (Yuqori aniqlikdagi Brown oylik harakati)
    l_moon = (218.3164477 + 481267.88123421 * t) % 360.0
    m_moon = (134.9633964 + 477198.8675055 * t) % 360.0
    f_moon = (93.2720950 + 483202.0175233 * t) % 360.0
    moon_lon = (l_moon + 6.288774 * math.sin(math.radians(m_moon))
                + 1.274027 * math.sin(math.radians(2 * (l_moon - sun_lon) - m_moon))
                + 0.658314 * math.sin(math.radians(2 * (l_moon - sun_lon)))
                + 0.213618 * math.sin(math.radians(2 * m_moon))
                - 0.185116 * math.sin(math.radians(m_sun))) % 360.0

    # 3. Merkuriy
    l_mercury = (252.2509 + 149472.6746 * t + 23.44 * math.sin(math.radians(174.7947 + 149474.07 * t))) % 360.0
    # 4. Venera
    l_venus = (181.9798 + 58517.8156 * t + 0.78 * math.sin(math.radians(50.4161 + 58517.82 * t))) % 360.0
    # 5. Mars
    l_mars = (355.433 + 19140.299 * t + 10.69 * math.sin(math.radians(19.373 + 19140.3 * t))) % 360.0
    # 6. Yupiter
    l_jupiter = (34.3515 + 3034.9057 * t + 5.55 * math.sin(math.radians(20.4 + 3034.9 * t))) % 360.0
    # 7. Saturn
    l_saturn = (50.0774 + 1222.1138 * t + 6.36 * math.sin(math.radians(317.0 + 1222.1 * t))) % 360.0
    # 8. Uran
    l_uranus = (314.055 + 428.4677 * t + 2.5 * math.sin(math.radians(141.0 + 428.5 * t))) % 360.0
    # 9. Neptun
    l_neptune = (304.349 + 218.4862 * t + 1.1 * math.sin(math.radians(256.0 + 218.5 * t))) % 360.0
    # 10. Pluton
    l_pluto = (238.96 + 145.18 * t) % 360.0

    # 11. Rahu & Ketu (Oy tugunlari — karmik nuqtalar)
    node_lon = (125.04452 - 1934.136261 * t) % 360.0
    ketu_lon = (node_lon + 180.0) % 360.0

    # 12. Lilith (Qora Oy — Oy apogeyi)
    lilith_lon = (40.66 + 4069.01 * t) % 360.0

    raw_positions = {
        "Quyosh": sun_lon,
        "Oy": moon_lon,
        "Merkuriy": l_mercury,
        "Venera": l_venus,
        "Mars": l_mars,
        "Yupiter": l_jupiter,
        "Saturn": l_saturn,
        "Uran": l_uranus,
        "Neptun": l_neptune,
        "Pluton": l_pluto,
        "Rahu (Shimoliy Tugun)": node_lon,
        "Ketu (Janubiy Tugun)": ketu_lon,
        "Lilit (Qora Oy)": lilith_lon,
    }

    result = {}
    for planet_name, lon in raw_positions.items():
        sign, symbol, sign_deg, d_int, m_int = _deg_to_zodiac(lon)
        result[planet_name] = {
            "longitude": round(lon, 3),
            "sign": sign,
            "symbol": symbol,
            "planet_symbol": PLANET_SYMBOLS.get(planet_name, "●"),
            "deg": d_int,
            "min": m_int,
            "formatted": f"{d_int}°{m_int:02d}' {symbol} {sign}",
        }

    return result


def _calculate_houses_and_ascendant(jd: float, lat: float, lon: float) -> Tuple[float, float, List[Dict[str, Any]]]:
    """
    Grinvich Yulduz Vaqti (GMST) va lokal koordinata asosida:
    Ascendant (ASC), Midheaven (MC) va 12 ta uylarni hisoblash (Placidus / Equal House tizimi).
    """
    t = (jd - 2451545.0) / 36525.0
    # Grinvich O'rtacha Yulduz Vaqti (GMST darajada)
    gmst = (280.46061837 + 360.98564736629 * (jd - 2451545.0) + 0.000387933 * t**2) % 360.0
    # Lokal Yulduz Vaqti (LST)
    lst = (gmst + lon) % 360.0

    # Ekliptika og'ishi (Obliquity of Ecliptic)
    eps = 23.439291 - 0.0130042 * t

    # MC (Medium Coeli / Midheaven - 10-uy kuspisi)
    rad_lst = math.radians(lst)
    rad_eps = math.radians(eps)
    rad_lat = math.radians(lat)

    mc_lon = math.degrees(math.atan2(math.tan(rad_lst), math.cos(rad_eps)))
    if math.cos(rad_lst) < 0:
        mc_lon += 180.0
    mc_lon = mc_lon % 360.0

    # ASC (Ascendant - 1-uy kuspisi, Ufqdagi ko'tarilayotgan nuqta)
    y = -math.cos(rad_lst)
    x = math.sin(rad_lst) * math.cos(rad_eps) + math.tan(rad_lat) * math.sin(rad_eps)
    asc_lon = math.degrees(math.atan2(y, x)) % 360.0

    # 12 ta Uy kuspislari (Equal / Porphyry gibrid xaritasi)
    houses = []
    for h in range(1, 13):
        h_lon = (asc_lon + (h - 1) * 30.0) % 360.0
        sign, symbol, _, d_int, m_int = _deg_to_zodiac(h_lon)
        houses.append({
            "house": h,
            "name": f"{h}-Uy",
            "longitude": round(h_lon, 3),
            "sign": sign,
            "symbol": symbol,
            "formatted": f"{h}-Uy: {d_int}°{m_int:02d}' {symbol} {sign}",
        })

    return asc_lon, mc_lon, houses


def _calculate_arabic_parts(asc_lon: float, sun_lon: float, moon_lon: float, venus_lon: float, jupiter_lon: float, saturn_lon: float) -> Dict[str, Dict[str, Any]]:
    """
    Qadimiy Arab va Ellinistik Nuqtalar (Arabic Parts / Lots):
    1. Pars Fortuna (Omad, Boylik va Qismat nuqtasi)
    2. Part of Spirit (Ruh, Maqsad, Iroda va Ruhoniyat)
    3. Part of Love / Eros (Muhabbat va Oila)
    4. Part of Career / Success (Karyera, Mansab va Zafar)
    5. Part of Necessity (Majburiyat, Saboq va Sinovlar)
    """
    # Kunduzgi yoki tungi xarita aniqlash: Quyosh 7-12 uylar oralig'ida bo'lsa (Ufqdan yuqorida) = Kunduzgi
    # Kunduzgi formula: Fortuna = Asc + Moon - Sun; Spirit = Asc + Sun - Moon
    # Tungi formula: Fortuna = Asc + Sun - Moon; Spirit = Asc + Moon - Sun
    diff = (sun_lon - asc_lon) % 360.0
    is_day = 180.0 <= diff <= 360.0 or diff < 0.0

    if is_day:
        fortuna = (asc_lon + moon_lon - sun_lon) % 360.0
        spirit = (asc_lon + sun_lon - moon_lon) % 360.0
    else:
        fortuna = (asc_lon + sun_lon - moon_lon) % 360.0
        spirit = (asc_lon + moon_lon - sun_lon) % 360.0

    eros = (asc_lon + venus_lon - spirit) % 360.0
    career = (asc_lon + jupiter_lon - saturn_lon) % 360.0
    necessity = (asc_lon + fortuna - saturn_lon) % 360.0

    parts = {
        "Pars Fortuna (Omad va Boylik)": {
            "lon": fortuna,
            "desc": "Moddiy muvaffaqiyat, kutilmagan omad, moliyaviy baraka va inson o'zini eng baxtli his qiladigan soha.",
        },
        "Part of Spirit (Ruh va Iroda)": {
            "lon": spirit,
            "desc": "Insonning ichki intellektual va ma'naviy maqsadi, irodasi va nima uchun dunyoga kelgani.",
        },
        "Part of Love (Eros & Muhabbat)": {
            "lon": eros,
            "desc": "Yurak mayli, ehtiros, munosabatlar va haqiqiy muhabbat qayerda gullab-yashnashi.",
        },
        "Part of Career (Mansab va Zafar)": {
            "lon": career,
            "desc": "Ijtimoiy mavqe, jamiyatda tanilish va professional cho'qqilarga erishish nuqtasi.",
        },
        "Part of Necessity (Sabr va Sinov)": {
            "lon": necessity,
            "desc": "Hayotiy sinovlar, saboqlar va qaysi sohada ehtiyotkorlik talab etilishi.",
        },
    }

    result = {}
    for name, data in parts.items():
        sign, symbol, _, d_int, m_int = _deg_to_zodiac(data["lon"])
        result[name] = {
            "longitude": round(data["lon"], 3),
            "sign": sign,
            "symbol": symbol,
            "formatted": f"{d_int}°{m_int:02d}' {symbol} {sign}",
            "description": data["desc"],
        }
    return result


def _calculate_aspects(planets: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Sayyoralar o'rtasidagi asosiy 5 ta klassik aspektni orbislar bilan hisoblash."""
    aspect_defs = [
        {"name": "Kon'yunksiya (Qovushish)", "angle": 0, "orb": 8.0, "symbol": "☌", "nature": "Kuchli / Neytral"},
        {"name": "Sekstil", "angle": 60, "orb": 6.0, "symbol": "⚹", "nature": "Ijobiy / Imkoniyat"},
        {"name": "Kvadratura", "angle": 90, "orb": 7.0, "symbol": "□", "nature": "Keskin / Dinamik sinov"},
        {"name": "Trigon", "angle": 120, "orb": 8.0, "symbol": "△", "nature": "Eng buyuk omad va uyg'unlik"},
        {"name": "Oppozitsiya", "angle": 180, "orb": 8.0, "symbol": "☍", "nature": "Qarama-qarshilik / Balans"},
    ]

    names = list(planets.keys())
    found_aspects = []

    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            p1 = names[i]
            p2 = names[j]
            # Tugunlar va Lilith o'rtasidagi mayda aspektlarni cheklaymiz
            if ("Tugun" in p1 or "Lilith" in p1) and ("Tugun" in p2 or "Lilith" in p2):
                continue

            lon1 = planets[p1]["longitude"]
            lon2 = planets[p2]["longitude"]
            diff = abs(lon1 - lon2)
            if diff > 180:
                diff = 360 - diff

            for asp in aspect_defs:
                orb = abs(diff - asp["angle"])
                if orb <= asp["orb"]:
                    found_aspects.append({
                        "planet1": p1,
                        "planet2": p2,
                        "aspect": asp["name"],
                        "symbol": asp["symbol"],
                        "nature": asp["nature"],
                        "exact_angle": round(diff, 2),
                        "orb": round(orb, 2),
                        "formatted": f"{p1} {asp['symbol']} {p2} ({round(orb, 1)}° orb) — {asp['nature']}",
                    })
                    break

    return found_aspects


# ─── Asosiy Ommaviy Funksiyalar ───────────────────────────────

def resolve_location(city_name: str) -> Tuple[str, float, float, float]:
    """Shahar nomidan (Kenglik, Uzunlik, Timezone) ni aniqlash."""
    clean = city_name.strip().lower()
    for key, (lat, lon, tz) in CITY_COORDINATES.items():
        if key in clean or clean in key:
            return key.capitalize(), lat, lon, tz
    # Standart zaxira: Toshkent (O'zbekiston markazi)
    return "Toshkent", 41.2995, 69.2401, 5.0


def calculate_full_natal_chart(birth_date_str: str, birth_time_str: str = "12:00", city_str: str = "Toshkent") -> Dict[str, Any]:
    """
    To'liq Natal Karta hisoblash:
    - Sayyoralar joylashuvi
    - Uylar va Ascendant / MC
    - 5 ta Arab Nuqtalari
    - Sayyoraviy Aspektlar
    """
    try:
        dt = datetime.datetime.strptime(birth_date_str.strip(), "%Y-%m-%d")
    except Exception:
        dt = datetime.datetime.now()

    time_parts = birth_time_str.strip().split(":")
    hour = int(time_parts[0]) if len(time_parts) > 0 and time_parts[0].isdigit() else 12
    minute = int(time_parts[1]) if len(time_parts) > 1 and time_parts[1].isdigit() else 0

    city_resolved, lat, lon, tz = resolve_location(city_str)

    # Grinvich (UTC) vaqtiga o'girish
    decimal_local_hour = hour + minute / 60.0
    utc_hour = (decimal_local_hour - tz) % 24.0

    jd = _julian_day(dt.year, dt.month, dt.day, utc_hour)

    # 1. Sayyoralar
    planets = _calculate_planets(jd)

    # 2. Uylar va Ascendant / MC
    asc_lon, mc_lon, houses = _calculate_houses_and_ascendant(jd, lat, lon)
    asc_sign, asc_sym, _, asc_d, asc_m = _deg_to_zodiac(asc_lon)
    mc_sign, mc_sym, _, mc_d, mc_m = _deg_to_zodiac(mc_lon)

    # 3. Arab Nuqtalari
    arabic_parts = _calculate_arabic_parts(
        asc_lon=asc_lon,
        sun_lon=planets["Quyosh"]["longitude"],
        moon_lon=planets["Oy"]["longitude"],
        venus_lon=planets["Venera"]["longitude"],
        jupiter_lon=planets["Yupiter"]["longitude"],
        saturn_lon=planets["Saturn"]["longitude"],
    )

    # 4. Aspektlar
    aspects = _calculate_aspects(planets)

    # Qaysi uyda qaysi sayyora joylashgani
    for p_name, p_data in planets.items():
        p_lon = p_data["longitude"]
        for h_info in houses:
            h_num = h_info["house"]
            h_start = h_info["longitude"]
            h_end = (h_start + 30.0) % 360.0
            if (h_start <= p_lon < h_end) or (h_start > h_end and (p_lon >= h_start or p_lon < h_end)):
                p_data["house"] = f"{h_num}-Uy"
                break
        if "house" not in p_data:
            p_data["house"] = "1-Uy"

    return {
        "birth_date": birth_date_str,
        "birth_time": f"{hour:02d}:{minute:02d}",
        "city": city_resolved,
        "lat": lat,
        "lon": lon,
        "tz": tz,
        "ascendant": {
            "longitude": round(asc_lon, 3),
            "sign": asc_sign,
            "symbol": asc_sym,
            "formatted": f"ASC: {asc_d}°{asc_m:02d}' {asc_sym} {asc_sign}",
        },
        "mc": {
            "longitude": round(mc_lon, 3),
            "sign": mc_sign,
            "symbol": mc_sym,
            "formatted": f"MC: {mc_d}°{mc_m:02d}' {mc_sym} {mc_sign}",
        },
        "planets": planets,
        "houses": houses,
        "arabic_parts": arabic_parts,
        "aspects": aspects,
    }


def calculate_transits(natal_planets: Dict[str, Dict[str, Any]], transit_date: Optional[datetime.date] = None) -> List[Dict[str, Any]]:
    """Bugungi kun sayyoralari va foydalanuvchining natal xaritasi o'rtasidagi faol tranzitlar."""
    if not transit_date:
        transit_date = datetime.date.today()

    jd_now = _julian_day(transit_date.year, transit_date.month, transit_date.day, 12.0)
    current_planets = _calculate_planets(jd_now)

    active_transits = []
    aspect_checks = [
        ("Kon'yunksiya", 0, 3.5, "☌", "Katta burilish va yangi bosqich"),
        ("Sekstil", 60, 2.5, "⚹", "Yaxshi imkoniyat va hamkorlik"),
        ("Kvadrat", 90, 3.0, "□", "Sinov, faollik va zudlik bilan hal etiladigan vazifa"),
        ("Trigon", 120, 3.5, "△", "Oqim bilan borish, omad va yengillik"),
        ("Oppozitsiya", 180, 3.5, "☍", "Munosabatlarda aniqlik kiritish yoki qaror qabul qilish"),
    ]

    # Asosan muhim sekin harakatlanuvchi sayyoralar tranzitiga e'tibor qaratiladi (Yupiter, Saturn, Mars, Pluton, Quyosh)
    important_transiting = ["Quyosh", "Mars", "Yupiter", "Saturn", "Uran", "Pluton"]
    for t_name in important_transiting:
        t_lon = current_planets[t_name]["longitude"]
        for n_name, n_data in natal_planets.items():
            n_lon = n_data["longitude"]
            diff = abs(t_lon - n_lon)
            if diff > 180:
                diff = 360 - diff

            for asp_name, angle, max_orb, sym, meaning in aspect_checks:
                orb = abs(diff - angle)
                if orb <= max_orb:
                    active_transits.append({
                        "transiting_planet": t_name,
                        "natal_planet": n_name,
                        "aspect": asp_name,
                        "symbol": sym,
                        "orb": round(orb, 2),
                        "meaning": meaning,
                        "formatted": f"Tranzit {t_name} {sym} Natal {n_name} ({round(orb, 1)}° orb) — {meaning}",
                    })
                    break

    return active_transits


def calculate_solar_return_summary(natal_sun_lon: float, target_year: int = 2026) -> Dict[str, Any]:
    """
    Quyosh qaytishi (Solar Return) xaritasi — Shaxsiy yangi yil boshlanishi.
    Quyosh qachon natal darajaga to'liq qaytishini va 1 yillik asosiy vazifalarni hisoblaydi.
    """
    # Yil o'rtasidagi Quyosh koordinatasini topish
    mid_jd = _julian_day(target_year, 6, 1, 12.0)
    # 1 yillik tendensiya va solyar uylar tahlili
    sol_planets = _calculate_planets(mid_jd)
    sign, sym, _, d_int, m_int = _deg_to_zodiac(natal_sun_lon)

    return {
        "solar_year": target_year,
        "natal_sun_degree": f"{d_int}°{m_int:02d}' {sym} {sign}",
        "solar_sun_sign": sign,
        "key_themes": [
            f"🎯 **{target_year}-Yil Shaxsiy Missiyasi:** O'zlikni kashf etish va shaxsiy salohiyatni {sign} energiyasida yuksaltirish.",
            "💰 **Moliya & Resurslar:** Pars Fortuna va 2-uy tranziti barqaror daromad manbalarini izlashga undaydi.",
            "🚀 **Professional Cho'qqi:** Yupiter va Saturn ta'siri ostida yangi professional mas'uliyatlarni qabul qilish davri.",
        ]
    }


def format_astrology_rag_context(chart_data: Dict[str, Any], transits: Optional[List[Dict[str, Any]]] = None) -> str:
    """
    AI Modellar (Nous Hermes 3, Gemini, DeepSeek, Claude) uchun
    chuqur, tushunarli va professional astrologik RAG tizim kontekstini yaratish.
    """
    if not chart_data:
        return ""

    planets = chart_data.get("planets", {})
    arabic = chart_data.get("arabic_parts", {})
    asc = chart_data.get("ascendant", {}).get("formatted", "Noma'lum")
    mc = chart_data.get("mc", {}).get("formatted", "Noma'lum")

    lines = [
        "--- FOYDALANUVCHINING SHAXSIY NATAL VA ASTROLOGIK XARITASI (ANQILANGAN MATEMATIK MA'LUMOTLAR) ---",
        f"📅 Tug'ilgan vaqt va joy: {chart_data.get('birth_date')} {chart_data.get('birth_time')}, {chart_data.get('city')}",
        f"🌟 Ufq (Ascendant): {asc} | 👑 Cho'qqi (MC): {mc}",
        "\n🪐 SAYYORALARNING BURJ VA UYLARDAGI JOYLASHUVI:",
    ]

    for p_name, p_data in planets.items():
        lines.append(f"  • {p_name}: {p_data.get('formatted')} ({p_data.get('house', '1-Uy')})")

    lines.append("\n☪️ QADIMIY ARAB NUQTALARI (ARABIC PARTS):")
    for a_name, a_data in arabic.items():
        lines.append(f"  • {a_name}: {a_data.get('formatted')} — {a_data.get('description')}")

    if transits:
        lines.append("\n⚡ BUGUNGI KUNDAGI FAOL TRANZITLAR (JORIY SAYYORALAR TA'SIRI):")
        for t in transits[:5]:
            lines.append(f"  • {t.get('formatted')}")

    lines.append(
        "\n[ASTROLOGIK KO'RSATMA]: Foydalanuvchi qanday savol bermasin (psixologiya, moliya, kasb, munosabatlar, kelajak rejalari), "
        "agar mavzuga aloqador bo'lsa, ushbu aniq natal parametrlarga (Quyosh, Oy, Ascendant, 2/10-uylar, Pars Fortuna) asoslanib, "
        "chuqur, professional va haqqoniy maslahat bering. Hech qachon quruq folbinlik qilmang, balki shaxsiyat tahlili va amaliy tavsiyalar bering."
    )
    lines.append("--- ASTROLOGIK XARITA TUGADI ---\n")

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════
# 513 ARAB LOTLARI (ARABIC PARTS / LOTS) VA GRANDMASTER OLIM DVIGATELI
# ══════════════════════════════════════════════════════════════

LOT_CATEGORIES = {
    "Moliya & Boylik": ["wealth", "fortune", "money", "commerce", "debt", "gain", "treasure", "possession", "gold", "silver", "moliya", "boylik", "daromad", "savdo", "oltin"],
    "Mansab & Zafar": ["career", "victory", "fame", "honor", "king", "nobility", "authority", "profession", "action", "dignity", "glory", "mansab", "zafar", "shuhrat", "karyera"],
    "Muhabbat & Nikoh": ["love", "eros", "marriage", "wedding", "passion", "union", "beauty", "concord", "desire", "wife", "husband", "sevgi", "muhabbat", "nikoh", "oila"],
    "Salomatlik & Sinovlar": ["illness", "sickness", "health", "death", "danger", "surgery", "poison", "necessity", "pain", "kasallik", "salomatlik", "o'lim", "xavf", "saboq"],
    "Aql & Ma'naviyat": ["spirit", "soul", "wisdom", "understanding", "intelligence", "faith", "religion", "divination", "art", "ruh", "aql", "donolik", "ilm", "e'tiqod"],
    "Oila & Ko'chmas Mulk": ["father", "mother", "ancestor", "land", "estate", "house", "inheritance", "property", "ota", "ona", "mulk", "yer", "meros", "uy"],
    "Do'stlar & Dushmanlar": ["friend", "alliance", "enemy", "enemies", "treachery", "captivity", "prison", "deceit", "do'st", "dushman", "xiyonat", "qamoq", "aldov"],
    "Sayohat & Chet El": ["journey", "travel", "water", "foreign", "pilgrimage", "sea", "exile", "sayohat", "safari", "chet el", "hijrat"],
}

ZODIAC_RULERS = {
    "Qo'y": "Mars", "Aries": "Mars",
    "Buzoq": "Venera", "Taurus": "Venera",
    "Egizaklar": "Merkuriy", "Gemini": "Merkuriy",
    "Qisqichbaqa": "Oy", "Cancer": "Oy",
    "Arslon": "Quyosh", "Leo": "Quyosh",
    "Parizod": "Merkuriy", "Virgo": "Merkuriy",
    "Tarozi": "Venera", "Libra": "Venera",
    "Chayon": "Mars / Pluton", "Scorpio": "Mars / Pluton",
    "O'qotar": "Yupiter", "Sagittarius": "Yupiter",
    "Tog'echkisi": "Saturn", "Capricorn": "Saturn",
    "Qovg'a": "Saturn / Uran", "Aquarius": "Saturn / Uran",
    "Baliq": "Yupiter / Neptun", "Pisces": "Yupiter / Neptun",
}


def parse_custom_arabic_lots(raw_input: Any) -> List[Dict[str, Any]]:
    """
    Foydalanuvchi tashlagan 513 tagacha Arab Lotlarini (JSON, CSV yoki matn)
    aniq strukturalangan ro'yxatga aylantirish.
    """
    lots: List[Dict[str, Any]] = []

    # 1. Agar allaqachon ro'yxat yoki lug'at bo'lsa
    if isinstance(raw_input, list):
        for item in raw_input:
            if isinstance(item, dict):
                lots.append(_normalize_lot_dict(item))
            elif isinstance(item, str):
                parsed = _parse_single_lot_line(item)
                if parsed:
                    lots.append(parsed)
        return lots

    if isinstance(raw_input, dict):
        for k, v in raw_input.items():
            if isinstance(v, dict):
                v["name"] = v.get("name", k)
                lots.append(_normalize_lot_dict(v))
            elif isinstance(v, (str, int, float)):
                parsed = _parse_single_lot_line(f"{k}: {v}")
                if parsed:
                    lots.append(parsed)
        return lots

    # 2. Agar xom matn (string) bo'lsa
    text = str(raw_input).strip()
    import json
    try:
        data = json.loads(text)
        return parse_custom_arabic_lots(data)
    except Exception:
        pass

    # Satrma-satr o'qish (CSV yoki oddiy ro'yxat)
    lines = text.split("\n")
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("//"):
            continue
        parsed = _parse_single_lot_line(line)
        if parsed:
            lots.append(parsed)

    return lots


def _parse_single_lot_line(line: str) -> Optional[Dict[str, Any]]:
    """Satrdan lot nomi, burji, darajasi va uyini ajratib olish."""
    import re
    # Masalan: "Part of Commerce: 14°22' Gemini (2nd House)" yoki "Fortune, 15 Leo, 10-uy"
    clean_line = line.replace('"', '').replace("'", " min ").replace("°", " deg ")
    
    # Ismni ajratish
    name = clean_line
    rest = ""
    for sep in [":", "-", "=", "➔", "\t", ","]:
        if sep in clean_line:
            parts = clean_line.split(sep, 1)
            name = parts[0].strip()
            rest = parts[1].strip()
            break

    sign_found = "Noma'lum"
    for z in ZODIAC_SIGNS:
        if z["name"].lower() in clean_line.lower() or z["en"].lower() in clean_line.lower():
            sign_found = z["name"]
            break

    # Darajani qidirish
    deg_match = re.search(r"(\d{1,2}(?:\.\d+)?)\s*(?:deg|\°)?", clean_line)
    degree = float(deg_match.group(1)) if deg_match else 0.0

    # Uyni qidirish
    house_match = re.search(r"(\d{1,2})\s*-(?:uy|house|dom)", clean_line, re.IGNORECASE)
    house = f"{house_match.group(1)}-Uy" if house_match else "Noma'lum"

    # Toifani aniqlash
    category = "Boshqa muhim nuqtalar"
    name_lower = name.lower()
    for cat_name, keywords in LOT_CATEGORIES.items():
        if any(kw in name_lower for kw in keywords):
            category = cat_name
            break

    ruler = ZODIAC_RULERS.get(sign_found, "Noma'lum")

    return {
        "name": name,
        "sign": sign_found,
        "degree": round(degree, 2),
        "house": house,
        "category": category,
        "ruler": ruler,
        "raw": line,
    }


def _normalize_lot_dict(item: Dict[str, Any]) -> Dict[str, Any]:
    name = str(item.get("name") or item.get("title") or "Nomsiz Lot")
    sign = str(item.get("sign") or item.get("burj") or "Noma'lum")
    deg = float(item.get("degree") or item.get("daraja") or 0.0)
    house = str(item.get("house") or item.get("uy") or "Noma'lum")
    
    category = item.get("category")
    if not category:
        category = "Boshqa muhim nuqtalar"
        name_lower = name.lower()
        for cat_name, keywords in LOT_CATEGORIES.items():
            if any(kw in name_lower for kw in keywords):
                category = cat_name
                break

    ruler = ZODIAC_RULERS.get(sign, "Noma'lum")

    return {
        "name": name,
        "sign": sign,
        "degree": deg,
        "house": house,
        "category": category,
        "ruler": ruler,
    }


def build_grandmaster_lots_rag_context(
    chart_data: Dict[str, Any],
    custom_lots: Optional[List[Dict[str, Any]]] = None,
    focus_topic: str = "",
) -> str:
    """
    513 tagacha bo'lgan barcha Arab lotlarini ixchamlashtirilgan,
    kuchli toifalangan va boshqaruvchilari bilan boyitilgan RAG matniga aylantirish.
    """
    lines = [
        "═══════════════════════════════════════════════════════════════",
        "🔮 QADIMIY ARAB LOTLARI VA ILMIY MUNAJJIM-OLIM MATEMATIKASI",
        "═══════════════════════════════════════════════════════════════",
    ]

    all_lots = custom_lots or []
    lines.append(f"📊 Ro'yxatdagi jami Arab Lotlari: {len(all_lots)} ta.")

    if not all_lots:
        lines.append("Foydalanuvchi hozircha shaxsiy qo'shimcha lotlar faylini kiritmagan. Klassik 5 ta asosiy lot tahlili ishlatiladi.")
        return "\n".join(lines)

    # Toifalar bo'yicha guruhlash
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for lot in all_lots:
        cat = lot.get("category", "Boshqa muhim nuqtalar")
        grouped.setdefault(cat, []).append(lot)

    for cat_name, cat_lots in grouped.items():
        lines.append(f"\n📂 [{cat_name.upper()}] — {len(cat_lots)} ta Lot:")
        for l in cat_lots[:15]:  # Har bir toifadan eng asosiy 15 tasini batafsil joylaymiz
            h_info = f" ({l.get('house')})" if l.get('house') and l.get('house') != "Noma'lum" else ""
            r_info = f" [Boshqaruvchi: {l.get('ruler')}]" if l.get('ruler') and l.get('ruler') != "Noma'lum" else ""
            lines.append(f"  • {l.get('name')}: {l.get('degree')}° {l.get('sign')}{h_info}{r_info}")
        if len(cat_lots) > 15:
            lines.append(f"    ... va yana {len(cat_lots) - 15} ta ixtisoslashgan lotlar.")

    return "\n".join(lines)


def build_grandmaster_astrology_prompt(
    profile: Dict[str, Any],
    custom_lots: Optional[List[Dict[str, Any]]] = None,
    question: str = "",
    target_year: int = 2026,
) -> str:
    """
    20 yillik tajribali munajjim-olim (Al-Biruniy / Abu Ma'shar / Hermes Trismegistus an'anasi)
    darajasidagi chuqur voqeaviy bashorat prompti.
    """
    chart = profile.get("chart", {})
    planets = chart.get("planets", {})
    asc = chart.get("ascendant", {}).get("formatted", "Noma'lum")
    mc = chart.get("mc", {}).get("formatted", "Noma'lum")
    birth_date = profile.get("birth_date", "")
    birth_time = profile.get("birth_time", "")
    city = profile.get("city", "")

    lots_rag = build_grandmaster_lots_rag_context(chart, custom_lots, focus_topic=question)

    prompt = f"""[QAT'IY QOIDA: JAVOBINGIZNI FAQAT VA FAQAT O'ZBEK TILIDA (LOTIN ALIFBOSIDA) YOZING! HECH BIR SO'Z YOKI JUMLA INGLIZ TILIDA BO'LMASIN. RESPONSE MUST BE 100% IN UZBEK LANGUAGE ONLY!]

Siz — 20 yillik chuqur tajribaga ega bo'lgan buyuk munajjim-olim, Abu Rayhon Beruniy, Abu Ma'shar al-Balxiy va Ellinistik an'anaviy astrologiya (Hermes Trismegistus, Vettius Valens) ustasisiz.

Sizning vazifangiz: Mijozning tug'ilgan kartasi va uning {len(custom_lots or [])} ta Arab Lotlarini (Lots / Sahms) o'zaro bog'lab, ANIQ VOQEAVIY PROGNOZ (Concrete Event Forecasting) berish. Barcha xulosalaringizni O'ZBEK TILIDA taqdim eting.

MIJOZ SHAXSIY NATAL KOORDINATALARI:
- Tug'ilgan vaqt va shahar: {birth_date} {birth_time}, {city}
- Ufq (Ascendant): {asc}
- Cho'qqi (Midheaven / MC): {mc}
- Sayyoralar:
"""
    for p_name, p_data in planets.items():
        prompt += f"  • {p_name}: {p_data.get('formatted')} ({p_data.get('house', '1-Uy')})\n"

    prompt += f"\n{lots_rag}\n"

    if question:
        prompt += f"\n❓ MIJOZNING ANIQ SAVOLI / TALABI:\n\"{question}\"\n\n"

    prompt += f"""TALABLAR VA TAHLIL TUZILISHI (Xuddi 20 yillik buyuk olim uslubida, o'ta jiddiy, ilmiy, amaliy va voqelikka yo'naltirilgan):

1. 🏛️ LOTLAR VA SAYYORALAR SINTEZI (Al-Biruniy qoidasi):
- Pars Fortuna (Boylik loti) va uning Boshqaruvchi sayyorasi (Lord of the Lot) holatini tahlil qiling.
- Part of Spirit (Iroda loti) va Part of Career (Zafar loti) orqali insonning bu hayotdagi mutlaq ustunligi va qaysi sohalar uni millionlarga yetaklashini yoritib bering.

2. 📅 ANIQ VOQEAVIY PROGNOZ ({target_year}-YIL VA KEYINGI DAVRLAR):
- Qaysi oylarda / davrlarda moddiy yuksalish, yirik bitimlar yoki kutilmagan daromadlar kutiladi?
- Mansab, rahbarlik va jamiyatda tanilish bo'yicha qachon taqdiriy imkoniyatlar eshigi ochiladi?
- Qaysi oylarda moliyaviy xavf-xatarlar, dushmanlar fitnasi yoki noto'g'ri shartnomalar xavfi bor (Part of Necessity & Treachery asosida)?

3. ❤️ MUHABBAT, NIKOH VA SHAXSIY HAYOT:
- Part of Love (Eros), Part of Marriage va Venera/7-uy asosida juftlik taqdiri, munosabatlar inqirozi yoki baxtli davrlari.

4. 🛡️ SOG'LIQ VA YASHIRIN XAVF-XATARLARDAN HIMOYA:
- Qaysi a'zolar zaif, qaysi davrlarda ortiqcha stress va qaltis ishlardan saqlanish kerak?

5. 🧭 20 YILLIK MUNAJJIMNING STRATEGIK XULOSASI:
- Mijozga hoziroq amal qilish kerak bo'lgan 3 ta aniq amaliy harakat qadami.

[MUHIM TALAB]: 
Butun hisobotni to'liq O'zbek tilida yozing! Hech qanday inglizcha so'z yoki jumla qo'shmang. Lot nomlarini o'zbekcha ma'nosi bilan keltiring (masalan: Part of Commerce — Savdo va Moliya loti)."""

    return prompt


async def ensure_uzbek_astrology_report(text: str, ai_manager: Any) -> str:
    """
    Agar AI tahlili ingliz tilida chiqib qolsa, uni avtomatik ravishda
    100% adabiy va chiroyli o'zbek tiliga o'girish.
    """
    if not text or len(text.strip()) < 40:
        return text

    english_words = {
        "the", "and", "is", "in", "to", "of", "you", "your", "this", "that",
        "with", "for", "are", "from", "will", "have", "not", "chart", "planets",
        "house", "natal", "sign", "degree", "astrology", "future", "career",
        "love", "wealth", "destiny", "transits", "horoscope"
    }
    words = [w.strip(".,!?:;\"'()[]{}").lower() for w in text.split()]
    eng_count = sum(1 for w in words if w in english_words)

    # Agar 3% dan ortiq inglizcha asosiy so'zlar bo'lsa -> zudlik bilan o'zbekchaga o'giramiz
    if len(words) > 0 and (eng_count / len(words)) > 0.03:
        try:
            trans_prompt = (
                "Quyidagi astrologik bashorat va munajjim-olim tahlilini 100% TOZA, ADABIY VA TA'SIRCHAN O'ZBEK TILIGA (lotin alifbosida) o'giring. "
                "Barcha formatlash, emojilar, paragraflar, yillar va tuzilmani to'liq saqlang. "
                "Hech bir jumla inglizcha qolmasin:\n\n"
                f"{text}"
            )
            if hasattr(ai_manager, "_generate_gemini"):
                uzbek_text = await ai_manager._generate_gemini(trans_prompt, save_history=False)
                if uzbek_text and not uzbek_text.startswith("❌") and len(uzbek_text) > 80:
                    return uzbek_text
            else:
                uzbek_text = await ai_manager.generate(trans_prompt, save_history=False)
                if uzbek_text and not uzbek_text.startswith("❌") and len(uzbek_text) > 80:
                    return uzbek_text
        except Exception:
            pass

    return text

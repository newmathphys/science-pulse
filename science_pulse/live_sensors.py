"""Живая телеметрия Планеты и Космоса: 4 бесключевых научных API.

Никаких ключей, регистраций и платных парсеров. Каждый датчик — один лёгкий
JSON-запрос с таймаутом `TIMEOUT` секунд и **детерминированным офлайн-фоллбэком**
(типовое значение), чтобы публикация и сборка сайта никогда не падали из-за сети.

| Датчик | Источник | Что подставляем в формулу |
|:--|:--|:--|
| `earthquake` | USGS GeoJSON | магнитуда `M` → энергия Гутенберга–Рихтера `lg E = 4.8 + 1.5M` |
| `space_weather` | NOAA SWPC | `Kp`-индекс магнитной бури → класс G1…G5 (Максвелл, Лоренц) |
| `gravitational_waves` | LIGO GWOSC | массы слияния `M₁, M₂, M_f` → `E = Δm c²` и радиус Шварцшильда |
| `iss_orbit` | WhereTheISS.at | высота `h` и скорость `v` → `g(h) = GM⊕/(R⊕+h)²` |

Модуль выключен по умолчанию (`ENABLED = False`) — его включает пайплайн по
конфигу, чтобы юнит-тесты не ходили в сеть.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.request
from typing import Any, Callable, Dict, Optional

LOGGER = logging.getLogger(__name__)

TIMEOUT = 2.5
CACHE_TTL = 600.0          # 10 минут: за сборку сайта датчик опрашивается один раз
SENSORS = ("earthquake", "space_weather", "gravitational_waves", "iss_orbit")

G = 6.67430e-11
M_EARTH = 5.972e24
R_EARTH_KM = 6371.0
M_SUN = 1.98892e30
C_LIGHT = 299792458.0

ENABLED = False
_CACHE: Dict[str, Any] = {"ts": 0.0, "data": {}}


def enable(flag: bool) -> None:
    """Включает/выключает живые датчики (тесты по умолчанию выключены)."""
    global ENABLED
    ENABLED = bool(flag)


def _default_http(url: str) -> Optional[Dict[str, Any]]:
    """Реальный HTTP: `urllib` без внешних зависимостей, таймаут 2.5 секунды."""
    request = urllib.request.Request(url, headers={"User-Agent": "SciencePulse/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8", "ignore"))
    except Exception as exc:  # pragma: no cover - сеть/таймаут
        LOGGER.info("датчик недоступен (%s): %s", url.split("/")[2], exc)
        return None


def _fetch(url: str, http: Optional[Callable[[str], Any]] = None) -> Optional[Any]:
    client = http or _default_http
    try:
        return client(url)
    except Exception as exc:  # pragma: no cover - защитный контур
        LOGGER.info("датчик бросил исключение: %s", exc)
        return None


def _cached(name: str, builder: Callable[[], Dict[str, Any]]) -> Dict[str, Any]:
    """Кэш на `CACHE_TTL`: за один прогон датчик опрашивается не чаще раза в 10 минут."""
    now = time.time()
    if now - float(_CACHE["ts"]) > CACHE_TTL:
        _CACHE["data"] = {}
        _CACHE["ts"] = now
    if name not in _CACHE["data"]:
        _CACHE["data"][name] = builder()
    return dict(_CACHE["data"][name])


def _kp_class(kp: float) -> str:
    if kp >= 9:
        return "G5 (экстремальная)"
    if kp >= 8:
        return "G4 (сильная)"
    if kp >= 7:
        return "G3 (сильная)"
    if kp >= 6:
        return "G2 (умеренная)"
    if kp >= 5:
        return "G1 (слабая)"
    return "спокойная магнитосфера"


def _build_earthquake(http: Optional[Callable[[str], Any]] = None) -> Dict[str, Any]:
    """Энергия последнего землетрясения по логарифмическому закону Рихтера."""
    url = "https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson&limit=1&orderby=time"
    payload = _fetch(url, http)
    features = (payload or {}).get("features") or []
    if not features:
        return dict(FALLBACKS["earthquake"])
    properties = features[0].get("properties") or {}
    coordinates = (features[0].get("geometry") or {}).get("coordinates") or []
    magnitude = float(properties.get("mag") or 0.0)
    depth = float(coordinates[2]) if len(coordinates) > 2 else 10.0
    # Триангуляция P/S: для станции над эпицентром путь ≈ глубине очага,
    # поэтому запаздывание S-волны Δt = d·(1/v_S − 1/v_P) при v_P = 6, v_S = 3.5 км/с.
    delay = depth * (1.0 / 3.5 - 1.0 / 6.0)
    return {
        "sensor": "earthquake",
        "live": True,
        "magnitude": round(magnitude, 2),
        "depth_km": round(depth, 1),
        "place": str(properties.get("place") or "—"),
        "energy_j": 10 ** (4.8 + 1.5 * magnitude),
        "p_s_delay_s": round(delay, 2),
        "p_s_distance_km": round(delay * (6.0 * 3.5) / (6.0 - 3.5), 1),
        "formula": "lg E = 4.8 + 1.5·M;  d = Δt·v_P·v_S/(v_P − v_S)",
        "source": "USGS Earthquakes GeoJSON",
    }


def _build_space_weather(http: Optional[Callable[[str], Any]] = None) -> Dict[str, Any]:
    """Текущий Kp-индекс геомагнитной активности (NOAA SWPC) + вектор Bz."""
    payload = _fetch("https://services.swpc.noaa.gov/json/planetary_k_index_1m.json", http)
    if not isinstance(payload, list) or not payload:
        return dict(FALLBACKS["space_weather"])
    last = payload[-1] or {}
    kp = float(last.get("estimated_kp") or last.get("kp_index") or 0.0)
    # Вектор межпланетного магнитного поля: Bz < 0 → магнитная буря эффективнее.
    # Последние строки часто пустые, поэтому ищем с конца первую с числом.
    bz = None
    mag = _fetch("https://services.swpc.noaa.gov/products/solar-wind/mag-1-day.json", http)
    if isinstance(mag, list) and len(mag) > 1:
        for row in reversed(mag[1:]):
            try:
                bz = float(row[3])
            except (IndexError, TypeError, ValueError):
                continue
            break
    return {
        "sensor": "space_weather",
        "live": True,
        "kp": round(kp, 2),
        "level": _kp_class(kp),
        "time_tag": str(last.get("time_tag") or ""),
        "bz_nt": bz,
        "formula": "F = q(v × B)",
        "source": "NOAA SWPC planetary_k_index_1m",
    }


def _build_gravitational_waves(http: Optional[Callable[[str], Any]] = None) -> Dict[str, Any]:
    """Массы последнего слияния чёрных дыр: энергия `E = Δm·c²` и радиус `r_s`."""
    payload = _fetch("https://gwosc.org/eventapi/json/allevents/", http)
    events = (payload or {}).get("events") or {}
    best: Optional[Dict[str, Any]] = None
    for value in events.values():
        if not isinstance(value, dict) or not value.get("mass_1_source") or not value.get("mass_2_source"):
            continue
        if best is None or float(value.get("GPS") or 0) > float(best.get("GPS") or 0):
            best = value
    if not best:
        return dict(FALLBACKS["gravitational_waves"])
    mass_1 = float(best.get("mass_1_source") or 0.0)
    mass_2 = float(best.get("mass_2_source") or 0.0)
    final = float(best.get("final_mass_source") or (mass_1 + mass_2))
    radiated = max(0.0, mass_1 + mass_2 - final)
    return {
        "sensor": "gravitational_waves",
        "live": True,
        "name": str(best.get("commonName") or "—"),
        "mass_1": round(mass_1, 1),
        "mass_2": round(mass_2, 1),
        "final_mass": round(final, 1),
        "radiated_m_sun": round(radiated, 2),
        "energy_j": radiated * M_SUN * C_LIGHT ** 2,
        "schwarzschild_km": 2 * G * final * M_SUN / C_LIGHT ** 2 / 1000.0,
        "formula": "E = Δm·c²,  r_s = 2GM/c²",
        "source": "LIGO/Virgo GWOSC eventapi",
    }


def _build_iss_orbit(http: Optional[Callable[[str], Any]] = None) -> Dict[str, Any]:
    """Текущая высота и скорость МКС → ускорение свободного падения на орбите."""
    payload = _fetch("https://api.wheretheiss.at/v1/satellites/25544", http)
    if not isinstance(payload, dict) or not payload.get("altitude"):
        return dict(FALLBACKS["iss_orbit"])
    altitude = float(payload.get("altitude") or 0.0)
    velocity = float(payload.get("velocity") or 0.0) / 3600.0  # км/ч → км/с
    radius = R_EARTH_KM + altitude
    return {
        "sensor": "iss_orbit",
        "live": True,
        "altitude_km": round(altitude, 1),
        "velocity_km_s": round(velocity, 2),
        "gravity": G * M_EARTH / (radius * 1000.0) ** 2,
        "formula": "g(h) = G·M⊕/(R⊕+h)²",
        "source": "WhereTheISS.at",
    }


FALLBACKS: Dict[str, Dict[str, Any]] = {
    "earthquake": {
        "sensor": "earthquake", "live": False, "magnitude": 5.0, "depth_km": 10.0,
        "place": "типовое значение (офлайн)", "energy_j": 10 ** (4.8 + 1.5 * 5.0),
        "formula": "lg E = 4.8 + 1.5·M", "source": "офлайн-фоллбэк",
    },
    "space_weather": {
        "sensor": "space_weather", "live": False, "kp": 3.0, "level": _kp_class(3.0),
        "time_tag": "", "formula": "F = q(v × B)", "source": "офлайн-фоллбэк",
    },
    "gravitational_waves": {
        "sensor": "gravitational_waves", "live": False, "name": "GW150914",
        "mass_1": 36.0, "mass_2": 29.0, "final_mass": 62.0, "radiated_m_sun": 3.0,
        "energy_j": 3.0 * M_SUN * C_LIGHT ** 2,
        "schwarzschild_km": 2 * G * 62.0 * M_SUN / C_LIGHT ** 2 / 1000.0,
        "formula": "E = Δm·c²,  r_s = 2GM/c²", "source": "офлайн-фоллбэк",
    },
    "iss_orbit": {
        "sensor": "iss_orbit", "live": False, "altitude_km": 420.0, "velocity_km_s": 7.66,
        "gravity": G * M_EARTH / ((R_EARTH_KM + 420.0) * 1000.0) ** 2,
        "formula": "g(h) = G·M⊕/(R⊕+h)²", "source": "офлайн-фоллбэк",
    },
}

BUILDERS: Dict[str, Callable[..., Dict[str, Any]]] = {
    "earthquake": _build_earthquake,
    "space_weather": _build_space_weather,
    "gravitational_waves": _build_gravitational_waves,
    "iss_orbit": _build_iss_orbit,
}


def sensor(name: str, http: Optional[Callable[[str], Any]] = None, use_cache: bool = True) -> Dict[str, Any]:
    """Значение одного датчика (с кэшем и офлайн-фоллбэком)."""
    builder = BUILDERS.get(str(name))
    if not builder:
        return {}
    if not use_cache:
        return builder(http)
    return _cached(str(name), lambda: builder(http))


def all_sensors(http: Optional[Callable[[str], Any]] = None) -> Dict[str, Dict[str, Any]]:
    """Все четыре датчика — для `/doctor`, `cli sensors` и демо."""
    return {name: sensor(name, http=http) for name in SENSORS}


# Правила маршрутизации: сопоставление идёт ТОЛЬКО по заголовку и формуле.
# Опыт: поиск по всему тексту давал ложные срабатывания — «Бином Ньютона»
# ловился на «ньютон», «быстрая сортировка» на «слияние» (merge sort), а
# «нормальное распределение» на «орбиту». Заголовок — точный индикатор темы.
TOPIC_RULES = (
    {
        "sensor": "earthquake",
        "any": ("рихтер", "землетряс", "сейсм", "гутенберг", "магнитуд", "логарифм", "logar"),
        "exclude": (),
    },
    {
        "sensor": "space_weather",
        "any": ("максвелл", "геомагнит", "магнитосфер", "ионосфер", "солнечный ветер",
                "солнечн", "сила лоренца"),
        "exclude": (),
    },
    {
        "sensor": "gravitational_waves",
        "any": ("шварцшильд", "чёрн", "черн", "ligo", "гравитационные волн",
                "гравитационных волн", "горизонт событий"),
        "exclude": (),
    },
    {
        "sensor": "iss_orbit",
        "any": ("тяготен", "орбит", "мкс", "баллист", "падени", "первая космическ"),
        "exclude": ("бином", "комбинаторик", "многочлен", "треугольник паскаля"),
    },
)


def sensor_for_post(post: Any) -> str:
    """Выбирает живой датчик по теме поста (или пустую строку).

    Смотрим только заголовок и формулу: текст разбора слишком «шумный» и давал
    ложные совпадения. Дополнительно работает `exclude`-защита.
    """
    text = " ".join(str(value or "") for value in (
        getattr(post, "title", ""),
        getattr(post, "formula_plain", ""),
        getattr(post, "formula_latex", ""),
    )).lower()
    for rule in TOPIC_RULES:
        if any(word in text for word in rule["exclude"]):
            continue
        if any(word in text for word in rule["any"]):
            return rule["sensor"]
    return ""


def live_line(post: Any, http: Optional[Callable[[str], Any]] = None) -> str:
    """Строка с живым числом датчика для блока «Верификация» подписи.

    Возвращает пустую строку, если датчики выключены или тема поста не подходит.
    """
    if not ENABLED:
        return ""
    name = sensor_for_post(post)
    if not name:
        return ""
    data = sensor(name, http=http)
    if not data:
        return ""
    mark = "" if data.get("live") else "(офлайн) "
    if name == "earthquake":
        return (f"{mark}сегодня M = {data['magnitude']} на глубине {data['depth_km']} км → "
                f"E = 10^(4.8+1.5·M) ≈ {data['energy_j']:.2e} Дж; "
                f"Δt(S−P) ≈ {data.get('p_s_delay_s', 0):.1f} с")
    if name == "space_weather":
        bz = data.get("bz_nt")
        tail = f", Bz = {bz:.1f} нТл" if isinstance(bz, (int, float)) else ""
        return f"{mark}Kp = {data['kp']} — {data['level']}{tail} (сила Лоренца F = q(v × B))"
    if name == "gravitational_waves":
        return (f"{mark}{data['name']}: M₁ = {data['mass_1']} M☉, M₂ = {data['mass_2']} M☉ → "
                f"E = Δm·c² ≈ {data['energy_j']:.2e} Дж, r_s ≈ {data['schwarzschild_km']:.0f} км")
    return (f"{mark}МКС: h = {data['altitude_km']} км, v = {data['velocity_km_s']} км/с → "
            f"g(h) = {data['gravity']:.3f} м/с²")



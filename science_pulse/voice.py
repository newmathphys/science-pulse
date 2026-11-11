"""Озвучка постов: детерминированный синтез речи (без LLM).

Движки:
- `edge` — Microsoft Edge TTS (онлайн, бесплатно, без ключей). Проверенный
  рабочий русский голос: `ru-RU-SvetlanaNeural`;
- `piper` — локальный нейросинтез (офлайн, в духе офлайн-бункера), включается,
  если установлен пакет `piper` и задана ONNX-модель.

Форматы публикации:
- `voice` — OGG/OPUS (голосовое сообщение Telegram, `sendVoice`);
- `audio` — MP3 (аудио-подкаст, `sendAudio` с обложкой-карточкой).

Текст для речи — чистый Unicode: LaTeX, код, HTML и эмодзи удаляются,
формулы разворачиваются в читаемые символы. Полный разбор поста озвучивается
целиком (до `voice.max_chars`), включая строку «Где работает сегодня».
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import subprocess
import sys
import tempfile
import time

import requests
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config import Config
from .models import Post
from .text import clean_latex_for_telegram, formula_to_unicode, strip_html

LOGGER = logging.getLogger(__name__)

# Проверенный на живом синтезе набор голосов (Dmitry/Aria в 2026 не отдают аудио).
EDGE_VOICES = ("ru-RU-SvetlanaNeural", "ru-RU-DmitryNeural", "en-US-AriaNeural")
DEFAULT_VOICE = "ru-RU-SvetlanaNeural"
ENGINE_PRIORITY = ("edge", "piper", "google_tts", "espeak", "sonification")
ENGINE_LABELS = {
    "edge": "Edge TTS (Светлана)",
    "piper": "Piper (офлайн)",
    "google_tts": "Google TTS",
    "espeak": "espeak-ng",
    "sonification": "сонификация",
}
# Последняя ошибка движка: нужна для классификации лимитов/сети/пустого аудио.
_LAST_ERRORS: Dict[str, str] = {}


def _which(binary: str) -> Optional[str]:
    found = shutil.which(binary)
    if found:
        return found
    for base in (Path(sys.executable).parent, Path.cwd() / ".venv" / "bin",
                 Path(__file__).resolve().parent.parent / ".venv" / "bin"):
        local = base / binary
        if local.is_file():
            return str(local)
    return None


# ---------------------------------------------------------------------------
# Адаптивные движки: circuit breaker для бесплатных облачных TTS.
# ---------------------------------------------------------------------------

def _health_defaults() -> Dict[str, Any]:
    return {
        "failures": 0,
        "blocked_until": 0.0,
        "last_error": "",
        "last_ok": 0.0,
        "last_kind": "",
    }


def _health_path(config: Config, path: Path | None = None) -> Path:
    return Path(path) if path else config.data_dir / "audio" / "voice_health.json"


def _read_health_file(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _load_health(config: Config, engine: str, path: Path | None = None) -> Dict[str, Any]:
    """Состояние движка из JSON (переживает перезапуски и CI)."""
    data = _health_defaults()
    loaded = _read_health_file(_health_path(config, path)).get(engine)
    if isinstance(loaded, dict):
        data.update(loaded)
    return data


def _save_health(config: Config, engine: str, data: Dict[str, Any], path: Path | None = None) -> None:
    target = _health_path(config, path)
    all_data = _read_health_file(target)
    all_data[engine] = data
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_suffix(".tmp")
        temp.write_text(json.dumps(all_data, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(target)
    except OSError as exc:
        LOGGER.debug("voice health write %s: %s", engine, exc)


def _classify_error(error: str) -> str:
    text = (error or "").lower()
    if any(token in text for token in ("429", "too many", "rate limit", "quota", "limit exceeded")):
        return "rate_limit"
    if any(token in text for token in ("timeout", "timed out", "connection", "network", "dns", "unreachable")):
        return "network"
    if any(token in text for token in ("not installed", "no module", "missing", "not found", "model")):
        return "missing"
    if any(token in text for token in ("empty", "too small", "no audio", "пуст")):
        return "empty"
    return "error"


def _cooldown_seconds(settings: Dict[str, Any], engine: str, kind: str, failures: int) -> int:
    if kind == "rate_limit":
        base = int(settings.get(f"{engine}_cooldown_minutes", 60)) * 60
        cap = int(settings.get(f"{engine}_max_cooldown_minutes", 360)) * 60
        threshold = 1
        return min(cap, base * (2 ** max(0, failures - threshold)))
    if kind == "network":
        return 10 * 60
    if kind == "empty":
        return 10 * 60
    return 5 * 60


def _record_success(config: Config, engine: str, path: Path | None = None) -> None:
    data = _load_health(config, engine, path)
    data.update({
        "failures": 0,
        "blocked_until": 0.0,
        "last_error": "",
        "last_ok": time.time(),
        "last_kind": "ok",
    })
    _save_health(config, engine, data, path)


def _record_failure(config: Config, engine: str, error: str, settings: Dict[str, Any], path: Path | None = None) -> None:
    data = _load_health(config, engine, path)
    kind = _classify_error(error)
    failures = int(data.get("failures") or 0) + 1
    threshold = 1 if kind == "rate_limit" else int(settings.get(f"{engine}_failure_threshold", 2))
    blocked_until = float(data.get("blocked_until") or 0.0)
    if kind != "missing" and failures >= threshold:
        blocked_until = max(blocked_until, time.time() + _cooldown_seconds(settings, engine, kind, failures))
    data.update({
        "failures": failures,
        "blocked_until": blocked_until,
        "last_error": (error or kind)[:240],
        "last_kind": kind,
    })
    _save_health(config, engine, data, path)
    LOGGER.warning("voice %s: %s (%s), failures=%s", engine, data["last_error"], kind, failures)


def _engine_blocked(config: Config, engine: str, path: Path | None = None) -> bool:
    data = _load_health(config, engine, path)
    return float(data.get("blocked_until") or 0.0) > time.time()


def _engine_ready(config: Config, engine: str, settings: Dict[str, Any]) -> bool:
    if engine == "edge":
        import importlib.util

        return importlib.util.find_spec("edge_tts") is not None
    if engine == "piper":
        model = str(settings.get("piper_model") or "")
        return bool(_which("piper") and model and Path(model).is_file())
    if engine == "google_tts":
        return bool(settings.get("google_fallback")) and bool(_which("ffmpeg"))
    if engine == "espeak":
        return bool(settings.get("espeak_enabled", True)) and bool(_which("espeak-ng") or _which("espeak"))
    if engine == "sonification":
        return True
    return False


def voice_engine_status(config: Config) -> List[Dict[str, Any]]:
    """Состояние цепочки движков для /doctor и `voice --engines`."""
    settings = voice_settings(config)
    now = time.time()
    result: List[Dict[str, Any]] = []
    for engine in settings.get("priority") or ENGINE_PRIORITY:
        health = _load_health(config, engine)
        blocked_for = max(0.0, float(health.get("blocked_until") or 0.0) - now)
        ready = _engine_ready(config, engine, settings)
        if not ready:
            state = "missing"
        elif blocked_for > 0:
            state = "cooldown"
        else:
            state = "ok"
        result.append({
            "engine": engine,
            "label": ENGINE_LABELS.get(engine, engine),
            "state": state,
            "ready": ready,
            "blocked_for_s": int(blocked_for),
            "last_error": str(health.get("last_error") or ""),
            "failures": int(health.get("failures") or 0),
        })
    return result


def format_voice_engines(config: Config) -> str:
    lines: List[str] = []
    for item in voice_engine_status(config):
        icon = {"ok": "🟢", "cooldown": "🟡", "missing": "⚪"}.get(item["state"], "⚪")
        detail = item["label"]
        if item["state"] == "cooldown":
            minutes = max(1, item["blocked_for_s"] // 60)
            detail += f" · лимит, ещё ~{minutes} мин"
        elif item["state"] == "missing":
            detail += " · недоступен"
        elif item["last_error"]:
            detail += f" · последняя ошибка: {item['last_error'][:60]}"
        lines.append(f"{icon} {detail}")
    return "\n".join(lines)


def voice_settings(config: Config) -> Dict[str, Any]:
    """Секция `voice:` из config.yaml с разумными значениями по умолчанию."""
    raw = dict(config.raw.get("voice") or {})
    return {
        "enabled": bool(raw.get("enabled", False)),
        "engine": str(raw.get("engine", "auto")),
        "voice": str(raw.get("voice", DEFAULT_VOICE)),
        "rate": str(raw.get("rate", "+0%")),
        "max_chars": int(raw.get("max_chars", 900)),
        "publish": str(raw.get("publish", "voice")),
        "piper_model": str(raw.get("piper_model", "")),
        "piper_voice": str(raw.get("piper_voice", "dmitri")),
        "google_fallback": bool(raw.get("google_fallback", False)),
        "priority": list(raw.get("priority") or ENGINE_PRIORITY),
        "edge_failure_threshold": int((raw.get("edge") or {}).get("failure_threshold", 2)),
        "edge_cooldown_minutes": int((raw.get("edge") or {}).get("cooldown_minutes", 60)),
        "edge_max_cooldown_minutes": int((raw.get("edge") or {}).get("max_cooldown_minutes", 360)),
        "google_failure_threshold": int((raw.get("google") or {}).get("failure_threshold", 1)),
        "google_cooldown_minutes": int((raw.get("google") or {}).get("cooldown_minutes", 120)),
        "google_max_cooldown_minutes": int((raw.get("google") or {}).get("max_cooldown_minutes", 360)),
        "espeak_enabled": bool((raw.get("espeak") or {}).get("enabled", True)),
        "espeak_voice": str((raw.get("espeak") or {}).get("voice", "ru")),
        "espeak_speed": int((raw.get("espeak") or {}).get("speed", 150)),
    }


def _speech_clean(value: str) -> str:
    """Убирает HTML, LaTeX, код, эмодзи и лишние пробелы — текст для диктора."""
    text = strip_html(value or "")
    text = re.sub(r"\$[^$]*\$", " ", text)
    text = re.sub(r"\\\[.*?\\\]", " ", text, flags=re.S)
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"`[^`]*`", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = formula_to_unicode(text, 600)
    # эмодзи и пиктограммы не читаются вслух
    text = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F]", " ", text)
    text = re.sub(r"[#*_>|]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return normalize_russian_for_tts(text.strip())


_ORDINALS = {
    1: ("первый", "первого", "первом"), 2: ("второй", "второго", "втором"),
    3: ("третий", "третьего", "третьем"), 4: ("четвёртый", "четвёртого", "четвёртом"),
    5: ("пятый", "пятого", "пятом"), 6: ("шестой", "шестого", "шестом"),
    7: ("седьмой", "седьмого", "седьмом"), 8: ("восьмой", "восьмого", "восьмом"),
    9: ("девятый", "девятого", "девятом"), 10: ("десятый", "десятого", "десятом"),
    11: ("одиннадцатый", "одиннадцатого", "одиннадцатом"),
    12: ("двенадцатый", "двенадцатого", "двенадцатом"),
    13: ("тринадцатый", "тринадцатого", "тринадцатом"),
    14: ("четырнадцатый", "четырнадцатого", "четырнадцатом"),
    15: ("пятнадцатый", "пятнадцатого", "пятнадцатом"),
    16: ("шестнадцатый", "шестнадцатого", "шестнадцатом"),
    17: ("семнадцатый", "семнадцатого", "семнадцатом"),
    18: ("восемнадцатый", "восемнадцатого", "восемнадцатом"),
    19: ("девятнадцатый", "девятнадцатого", "девятнадцатом"),
    20: ("двадцатый", "двадцатого", "двадцатом"),
    21: ("двадцать первый", "двадцать первого", "двадцать первом"),
}
_ROMAN = {"I":1,"II":2,"III":3,"IV":4,"V":5,"VI":6,"VII":7,"VIII":8,"IX":9,"X":10,
          "XI":11,"XII":12,"XIII":13,"XIV":14,"XV":15,"XVI":16,"XVII":17,"XVIII":18,
          "XIX":19,"XX":20,"XXI":21}


def normalize_russian_for_tts(text: str) -> str:
    """Разворачивает сокращения, чтобы TTS не читал «даэнэ» и «г.». """
    value = str(text or "")
    value = re.sub(r"\bдо\s*н\.\s*э\.", "до нашей эры", value, flags=re.I)
    value = re.sub(r"\bн\.\s*э\.", "нашей эры", value, flags=re.I)
    value = re.sub(r"\b(\d{1,4})\s*г\.", r"\1 года", value)
    value = re.sub(r"\b3D\b", "три-дэ", value)
    value = re.sub(r"\bL2\b", "эль-два", value)
    value = re.sub(r"\bGPS\b", "джи-пи-эс", value)

    def century(match: re.Match[str]) -> str:
        raw, suffix = match.group(1), match.group(2).lower()
        number = _ROMAN.get(raw.upper())
        if number is None:
            try:
                number = int(raw)
            except ValueError:
                return match.group(0)
        forms = _ORDINALS.get(number)
        if not forms:
            return match.group(0)
        if suffix.startswith("веке"):
            return f"{forms[2]} веке"
        if suffix.startswith("века"):
            return f"{forms[1]} века"
        return f"{forms[0]} век"

    value = re.sub(r"\b(I|II|III|IV|V|VI|VII|VIII|IX|X|XI|XII|XIII|XIV|XV|XVI|XVII|XVIII|XIX|XX|XXI|\d{1,2})\s*(век[ае]?|в\.)\b", century, value, flags=re.I)
    return value


# Фонетический словарь формул: печатный текст не меняется, меняется только речь.
# Порядок важен: длинные конструкции заменяются раньше коротких.
_SPOKEN_RULES: tuple = (
    # разделители в метаданных («1738 года • Базель») — не читаем как символ
    (r"•", ","),
    # сложность алгоритмов
    (r"O\s*\(\s*[Nn]\s*[·*]?\s*log\s*[Nn]\s*\)", "о большое от эн логарифм эн"),
    (r"O\s*\(\s*[Nn]\s*\^\s*2\s*\)", "о большое от эн квадрат"),
    (r"O\s*\(\s*[Nn]²\s*\)", "о большое от эн квадрат"),
    (r"O\s*\(\s*[Nn]\s*\^\s*3\s*\)", "о большое от эн куб"),
    (r"O\s*\(\s*[Nn]³\s*\)", "о большое от эн куб"),
    (r"O\s*\(\s*log\s*[Nn]\s*\)", "о большое от логарифм эн"),
    (r"O\s*\(\s*[Nn]\s*\)", "о большое от эн"),
    (r"O\s*\(\s*1\s*\)", "о от единицы"),
    # приращения и греческие символы
    (r"Δφ", "дельта фи"),
    (r"Δx", "дельта икс"),
    (r"Δt", "дельта тэ"),
    (r"Δ", "дельта"),
    (r"[Ψψ]", "пси"),
    (r"[Φφ]", "фи"),
    (r"λ", "лямбда"),
    (r"[ℏħ]", "аш с чертой"),
    (r"π", "пи"),
    (r"θ", "тета"),
    (r"σ", "сигма"),
    (r"ε", "эпсилон"),
    (r"α", "альфа"),
    (r"β", "бета"),
    (r"γ", "гамма"),
    (r"ω", "омега"),
    (r"μ", "мю"),
    (r"∂", "частная производная"),
    (r"∫", "интеграл"),
    (r"∑", "сумма"),
    (r"√", "корень из "),
    (r"∇", "набла"),
    (r"→", " стремится к "),
    # степени и сравнения
    (r"c²", "це в квадрате"),
    (r"c\^2", "це в квадрате"),
    (r"²", " в квадрате"),
    (r"³", " в кубе"),
    (r"≥", " больше либо равно "),
    (r"≤", " меньше либо равно "),
    (r"≈", " приближённо равно "),
    (r"≠", " не равно "),
    (r"±", " плюс-минус "),
    (r"[·×⋅]", " умножить на "),
    (r"÷", " делить на "),
    (r"∞", "бесконечность"),
    (r"∈", " принадлежит "),
    (r"∀", "для всех"),
    (r"∃", "существует"),
    # индексы
    (r"r_s", "эр эс"),
    (r"k_B", "ка бэ"),
    (r"₀", " нулевое"),
    (r"₁", " первое"),
    (r"₂", " второе"),
    (r"ᵢ", " и"),
    (r"ₙ", " эн"),
    (r"ₖ", " ка"),
)


def math_to_spoken_russian(text: str) -> str:
    """Превращает математические конструкции в живую речь лектора (для TTS).

    Печатный текст поста НЕ меняется — нормализуется только копия для диктора:
    `O(N log N)` → «о большое от эн логарифм эн», `Δφ` → «дельта фи»,
    `ℏ` → «аш с чертой», `c²` → «це в квадрате», `≥` → «больше либо равно».
    """
    result = str(text or "")
    for pattern, spoken in _SPOKEN_RULES:
        result = re.sub(pattern, f" {spoken} ", result)
    result = re.sub(r"\s{2,}", " ", result)
    result = re.sub(r"\s+([,.;:!?])", r"\1", result)
    return result.strip()


def _strip_links_tags(value: str) -> str:
    """Убирает URL, #хэштеги, @упоминания и технические пометки из речи."""
    text = re.sub(r"https?://\S+", " ", value or "")
    text = re.sub(r"#[\wа-яё]+", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"@[\w_]+", " ", text)
    text = re.sub(r"\[\s*\]|\(\s*\)", " ", text)
    return re.sub(r"\s{2,}", " ", text).strip()


def _approximate_segments(text: str, duration: float, max_words: int = 12) -> List[Any]:
    """Приблизительные таймкоды (когда нет boundaries): время ∝ длине фразы."""
    sentences = [part.strip() for part in re.split(r"(?<=[.!?…])\s+", text or "") if part.strip()]
    chunks: List[str] = []
    for sentence in sentences:
        words = sentence.split()
        while len(words) > max_words:
            chunks.append(" ".join(words[:max_words]))
            words = words[max_words:]
        if words:
            chunks.append(" ".join(words))
    if not chunks:
        return []
    total = sum(len(chunk) for chunk in chunks) or 1
    segments: List[Any] = []
    cursor = 0.0
    for chunk in chunks:
        span = max(0.5, duration * (len(chunk) / total))
        segments.append((cursor, min(duration, cursor + span), chunk))
        cursor += span
    return segments


def _canon_titles(ids: List[str]) -> List[str]:
    """Читаемые названия узлов канона по их id (для моста «опирается на …»)."""
    try:
        from .sources.foundation import CANON

        table = {str(item["id"]): str(item.get("title") or item["id"]) for item in CANON}
    except Exception:
        table = {}
    titles: List[str] = []
    for item in ids[:3]:
        name = table.get(str(item), str(item))
        titles.append((name.split(":")[0].split("—")[0].strip() or str(item)))
    return titles


def build_lecture_script(post: Post, max_chars: int = 900, closing: str = "post") -> str:
    """Естественный рассказ для диктора: без меток, без чтения формулы.

    Диктор говорит только связным текстом: учёный/эпоха/заголовок, вопрос,
    суть, проверенный числовой пример, применение и мост к следующей теме.
    Формула остаётся на экране/в карточке, но голосом не читается.
    """
    meta = getattr(post, "meta", {}) or {}
    scientist = _strip_links_tags(_speech_clean(str(meta.get("scientist") or post.source_name or "учёный")))
    era = _strip_links_tags(_speech_clean(str(meta.get("era") or "")))
    title = _strip_links_tags(_speech_clean(post.title))
    hook = _strip_links_tags(_speech_clean(post.hook or ""))
    body = _strip_links_tags(_speech_clean(post.body or ""))
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", body) if part.strip()]
    first = sentences[0] if sentences else ""
    rest = " ".join(sentences[1:]) if len(sentences) > 1 else ""

    parts: List[str] = []
    intro = " ".join(part for part in (
        f"{scientist}." if scientist else "",
        f"{era}." if era else "",
        f"{title}." if title else "",
    ) if part)
    if intro:
        parts.append(intro)
    if hook or first:
        parts.append(" ".join(part for part in (hook, first) if part))
    if rest:
        parts.append(rest)

    example = verified_example(post)
    if example:
        parts.append(f"На числах это даёт: {example}")

    application = _strip_links_tags(_speech_clean(str(meta.get("modern_application") or "")))
    if application:
        parts.append(f"Сегодня это работает: {application}.")

    prereqs = _canon_titles([str(item) for item in (meta.get("prereq_ids") or [])])
    unlocks = [str(item) for item in (meta.get("unlocks_concepts") or [])][:3]
    bridge: List[str] = []
    if prereqs:
        bridge.append(f"Это опирается на труды: {', '.join(prereqs)}")
    if unlocks:
        bridge.append(f"и открывает путь к теме: {', '.join(unlocks)}")
    if bridge:
        parts.append(" ".join(bridge) + ".")

    try:
        from .challenge import build_challenge
        from .post_modes import shows_challenge

        if shows_challenge(str(meta.get("post_mode") or "")):
            question = _strip_links_tags(_speech_clean(str(build_challenge(post).get("question") or "")))
            if question:
                parts.append(f"Попробуйте сами: {question}")
    except Exception:
        pass

    ending = "Эфир продолжается." if str(closing) == "radio" else "Разбор завершён."
    parts.append(ending)
    parts = [math_to_spoken_russian(part) for part in parts if part]
    text = " ".join(parts)
    budget = max(80, int(max_chars))
    if len(text) > budget:
        try:
            from .signal_engine import ShannonTextCompressor

            compressed = ShannonTextCompressor().compress(text, budget)
            if compressed and len(compressed) <= budget:
                text = compressed
        except Exception:
            pass
    if len(text) > budget:
        cut = text[:budget]
        for stop in (". ", "! ", "? "):
            index = cut.rfind(stop)
            if index > budget * 0.6:
                cut = cut[: index + 1]
                break
        else:
            space = cut.rfind(" ")
            cut = (cut[:space] if space > 0 else cut).rstrip(" ,;:—") + "."
        text = cut.rstrip()
    return text


def _boundaries_to_segments(boundaries: List[Any], max_words: int = 12) -> List[Any]:
    """Собирает фразы субтитров из таймкодов edge-tts.

    Поддерживает и слова (`WordBoundary`), и готовые предложения
    (`SentenceBoundary` — их отдаёт русский голос).
    """
    segments: List[Any] = []
    current: List[str] = []
    start = end = 0.0
    for offset, duration, word in boundaries:
        begin = offset / 10_000_000.0
        finish = (offset + duration) / 10_000_000.0
        text = str(word or "").strip()
        if not text:
            continue
        if " " in text:  # готовая фраза целиком
            if current:
                segments.append((start, end, " ".join(current)))
                current = []
            segments.append((begin, finish, text))
            continue
        if not current:
            start = begin
        current.append(text)
        end = finish
        if text.endswith((".", "!", "?", "…")) or len(current) >= max_words:
            segments.append((start, end, " ".join(current)))
            current = []
    if current:
        segments.append((start, end, " ".join(current)))
    return segments


def _timestamp(seconds: float, comma: bool = False) -> str:
    ms = int(round(max(0.0, seconds) * 1000))
    hours, remainder = divmod(ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    separator = "," if comma else "."
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{millis:03d}"


def _words_from_boundaries(boundaries: List[Any]) -> List[Any]:
    """Слово-таймкоды edge-tts: (start_s, end_s, word).

    Русский голос часто отдаёт SentenceBoundary целой фразой — тогда делим
    интервал фразы между словами пропорционально длине.
    """
    words: List[Any] = []
    for offset, duration, text in boundaries:
        token = str(text or "").strip()
        if not token:
            continue
        start = float(offset) / 10_000_000.0
        end = max(start, float(offset + duration) / 10_000_000.0)
        parts = token.split()
        if len(parts) <= 1:
            words.append((start, end, token))
            continue
        total = sum(max(1, len(part)) for part in parts)
        cursor = start
        span = max(0.02, end - start)
        for part in parts:
            piece = span * max(1, len(part)) / max(1, total)
            words.append((cursor, min(end, cursor + piece), part))
            cursor += piece
    return words


def _approximate_words(text: str, duration: float) -> List[Any]:
    """Равномерные таймкоды слов, если движок не отдал boundaries."""
    tokens = [token for token in str(text or "").split() if token]
    if not tokens:
        return []
    total = sum(max(1, len(token)) for token in tokens)
    cursor = 0.0
    words: List[Any] = []
    for token in tokens:
        span = max(0.08, duration * max(1, len(token)) / max(1, total))
        words.append((cursor, min(duration, cursor + span), token))
        cursor += span
    return words


def write_subtitles(segments: List[Any], base_path: str | Path) -> Dict[str, str]:
    """Пишет синхронные субтитры `.vtt` и `.srt` рядом с аудио."""
    base = Path(base_path)
    if not segments:
        return {}
    vtt_lines = ["WEBVTT", ""]
    srt_lines: List[str] = []
    for index, (start, end, text) in enumerate(segments, start=1):
        vtt_lines += [f"{_timestamp(start)} --> {_timestamp(end)}", text, ""]
        srt_lines += [str(index), f"{_timestamp(start, True)} --> {_timestamp(end, True)}", text, ""]
    vtt_path = base.with_suffix(".vtt")
    srt_path = base.with_suffix(".srt")
    vtt_path.write_text("\n".join(vtt_lines), encoding="utf-8")
    srt_path.write_text("\n".join(srt_lines), encoding="utf-8")
    return {"vtt": str(vtt_path), "srt": str(srt_path)}


def verified_example(post: Post) -> str:
    """Только проверенный числовой пример; без случайных чисел из текста."""
    meta = getattr(post, "meta", {}) or {}
    canon_id = str(meta.get("canon_id") or meta.get("foundation_id") or "")
    if canon_id == "pythagoras":
        return "Если катеты равны трём и четырём, то гипотенуза равна пяти."
    if canon_id == "euclid_gcd":
        return "Для чисел 1071 и 462 наибольший общий делитель равен 21."
    if canon_id == "newton_gravity":
        return "Если увеличить расстояние в три раза, сила уменьшится в девять раз."
    if canon_id == "bernoulli_flow":
        return ("При скорости воды два метра в секунду и высоте пять метров "
                "полное давление равно примерно ста пятидесяти двум тысячам паскалей.")
    if canon_id == "lovelace":
        return "Четвёртое число Бернулли равно минус одной тридцатой."
    try:
        from .challenge import build_challenge

        data = build_challenge(post) or {}
        if data.get("verified") and data.get("answer"):
            return f"{data.get('question', '')} {data['answer']}".strip()
    except Exception:
        pass
    return ""


def _body_sentences(post: Post) -> List[str]:
    body = _strip_links_tags(_speech_clean(post.body or ""))
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", body) if part.strip()]


def build_film_blocks(post: Post) -> List[str]:
    """5 естественных блоков речи без казённых меток и без чтения формул."""
    meta = getattr(post, "meta", {}) or {}
    scientist = str(meta.get("scientist") or post.source_name or "учёный").strip()
    era = _strip_links_tags(_speech_clean(str(meta.get("era") or "")))
    title = _strip_links_tags(_speech_clean(post.title))
    hook = _strip_links_tags(_speech_clean(post.hook or ""))
    sentences = _body_sentences(post)
    first = sentences[0] if sentences else ""
    second = sentences[1] if len(sentences) > 1 else ""
    example = verified_example(post)
    application = _strip_links_tags(_speech_clean(str(meta.get("modern_application") or "")))
    unlocks = [str(item) for item in (meta.get("unlocks_concepts") or [])][:2]

    block1 = " ".join(part for part in (
        f"{scientist}." if scientist else "",
        f"{era}." if era else "",
        f"{title}." if title else "",
    ) if part)
    block2 = f"{hook} {first}".strip()
    block3 = second or "Формула связывает величины, которые разобраны в тексте."
    block4 = example or (sentences[2] if len(sentences) > 2 else "")
    block5 = f"Сегодня это применяется: {application}." if application else ""
    if unlocks:
        block5 += f" Дальше — {', '.join(unlocks)}."
    return [block1, block2, block3, block4, block5]

def build_film_script(post: Post) -> str:
    return " ".join(block for block in build_film_blocks(post) if block)


def speech_text(post: Post, max_chars: int = 900) -> str:
    """Текст для озвучки: лекционный сценарий диктора (см. build_lecture_script)."""
    return build_lecture_script(post, max_chars)


def _legacy_speech_text(post: Post, max_chars: int = 900) -> str:
    """Текст для озвучки: заголовок → хук → полный разбор → где работает сегодня."""
    meta = getattr(post, "meta", {}) or {}
    parts = [f"{post.label}. {_speech_clean(post.title)}"]
    hook = _speech_clean(post.hook or "")
    if hook:
        parts.append(hook)
    body = _speech_clean(post.body or "")
    if body:
        parts.append(body)
    application = _speech_clean(str(meta.get("modern_application") or ""))
    if application:
        parts.append(f"Где это работает сегодня: {application}.")
    if post.formula_plain:
        parts.append(f"Формула: {_speech_clean(post.formula_plain)}")
    text = " ".join(part for part in parts if part)
    if len(text) > max_chars:
        cut = text[:max_chars]
        for stop in (". ", "! ", "? "):
            index = cut.rfind(stop)
            if index > max_chars * 0.6:
                cut = cut[: index + 1]
                break
        else:  # не нашли границу предложения — режем по слову и ставим точку
            space = cut.rfind(" ")
            cut = (cut[:space] if space > 0 else cut).rstrip(" ,;:—") + "."
        text = cut.rstrip()
    return math_to_spoken_russian(text)


@dataclass
class VoiceArtifact:
    """Готовые аудиофайлы озвучки поста."""

    post_id: str
    text: str
    mp3_path: str
    ogg_path: str = ""
    duration_s: float = 0.0
    engine: str = ""
    voice: str = ""
    vtt_path: str = ""
    srt_path: str = ""
    segments: List[Any] = field(default_factory=list)
    words: List[Any] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "post_id": self.post_id,
            "engine": self.engine,
            "voice": self.voice,
            "duration_s": round(self.duration_s, 2),
            "mp3": self.mp3_path,
            "ogg": self.ogg_path,
            "vtt": self.vtt_path,
            "chars": len(self.text),
            "segments": len(self.segments),
            "words": len(self.words),
        }


def _duration_seconds(path: Path) -> float:
    """Длительность аудио через ffprobe (0.0, если ffprobe недоступен)."""
    if not _which("ffprobe"):
        return 0.0
    try:
        output = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=30, check=False,
        )
        return float((output.stdout or "0").strip() or 0.0)
    except Exception:
        return 0.0


def _to_voice_ogg(mp3_path: Path, ogg_path: Path) -> bool:
    """MP3 → OGG/OPUS (формат голосового сообщения Telegram)."""
    if not _which("ffmpeg"):
        return False
    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3_path),
             "-c:a", "libopus", "-b:a", "32k", "-ar", "48000", "-ac", "1", str(ogg_path)],
            capture_output=True, text=True, timeout=180, check=False,
        )
        if result.returncode != 0:
            LOGGER.warning("ffmpeg ogg: %s", (result.stderr or "")[:200])
            return False
        return ogg_path.is_file() and ogg_path.stat().st_size > 0
    except Exception as exc:
        LOGGER.warning("ffmpeg ogg: %s", exc)
        return False


def _tts_chunks(text: str, limit: int = 260) -> List[str]:
    """Режет длинную речь на короткие куски для стабильного edge-tts."""
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text or "") if part.strip()]
    chunks: List[str] = []
    current = ""
    for sentence in sentences:
        if len(sentence) > limit:
            if current:
                chunks.append(current)
                current = ""
            words = sentence.split()
            buffer = ""
            for word in words:
                candidate = f"{buffer} {word}".strip()
                if len(candidate) <= limit:
                    buffer = candidate
                else:
                    if buffer:
                        chunks.append(buffer)
                    buffer = word
            if buffer:
                chunks.append(buffer)
            continue
        candidate = f"{current} {sentence}".strip()
        if len(candidate) <= limit:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = sentence
    if current:
        chunks.append(current)
    return chunks or [text[:limit]]


def _synthesize_edge(text: str, out_mp3: Path, voice: str, rate: str = "+0%") -> Tuple[str, List[Any]]:
    """Онлайн-синтез Edge TTS с таймкодами слов (для субтитров).

    Длинный текст режется на куски ≤260 символов: edge-tts нестабилен на
    больших запросах и иногда отдаёт обрезанный файл. Куски склеиваются
    ffmpeg, а таймкоды сдвигаются на длительность предыдущих.
    """
    try:
        import asyncio

        import edge_tts
    except ImportError:
        _LAST_ERRORS["edge"] = "edge_tts not installed"
        return "", []

    candidates = [voice] + [item for item in EDGE_VOICES if item != voice]
    chunks = _tts_chunks(text)
    if not chunks:
        return "", []

    async def synth_chunk(candidate: str, chunk: str, path: Path) -> List[Any]:
        communicate = edge_tts.Communicate(chunk, candidate, rate=rate)
        boundaries: List[Any] = []
        with open(path, "wb") as handle:
            async for message in communicate.stream():
                if message.get("type") == "audio":
                    handle.write(message["data"])
                elif message.get("type") in ("WordBoundary", "SentenceBoundary"):
                    boundaries.append(
                        (message.get("offset", 0), message.get("duration", 0), message.get("text", ""))
                    )
        return boundaries

    for candidate in candidates:
        with tempfile.TemporaryDirectory(prefix="sp_edge_") as tmp:
            work = Path(tmp)
            paths: List[Path] = []
            all_boundaries: List[Any] = []
            offset_100ns = 0
            failed = False
            for index, chunk in enumerate(chunks):
                path = work / f"chunk_{index:03d}.mp3"
                boundaries: List[Any] = []
                for attempt in range(5):
                    try:
                        boundaries = asyncio.run(synth_chunk(candidate, chunk, path))
                    except Exception as exc:
                        _LAST_ERRORS["edge"] = f"{type(exc).__name__}: {exc}"[:240]
                        LOGGER.warning(
                            "edge-tts %s chunk %s attempt %s: %s",
                            candidate, index, attempt + 1, str(exc)[:90],
                        )
                        boundaries = []
                    if path.is_file() and path.stat().st_size >= 1000:
                        break
                    time.sleep(1.2)
                if not path.is_file() or path.stat().st_size < 1000:
                    failed = True
                    break
                duration = _duration_seconds(path)
                for boundary_offset, boundary_duration, boundary_text in boundaries:
                    all_boundaries.append(
                        (int(boundary_offset) + offset_100ns, boundary_duration, boundary_text)
                    )
                offset_100ns += int((duration or 0.0) * 10_000_000)
                paths.append(path)
            if failed:
                continue
            if len(paths) == 1:
                shutil.copyfile(paths[0], out_mp3)
            else:
                list_file = work / "list.txt"
                list_file.write_text(
                    "".join(f"file '{path.as_posix()}'\n" for path in paths),
                    encoding="utf-8",
                )
                if not _which("ffmpeg"):
                    continue
                result = subprocess.run(
                    ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                     "-i", str(list_file), "-c", "copy", str(out_mp3)],
                    capture_output=True, text=True, timeout=180, check=False,
                )
                if result.returncode != 0 or not out_mp3.is_file():
                    LOGGER.warning("edge-tts concat: %s", (result.stderr or "")[:160])
                    continue
            if out_mp3.is_file() and out_mp3.stat().st_size > 1000:
                _LAST_ERRORS.pop("edge", None)
                return candidate, all_boundaries
    _LAST_ERRORS.setdefault("edge", "empty audio from all Edge voices")
    return "", []


def _synthesize_google(text: str, out_mp3: Path, lang: str = "ru") -> bool:
    """Резервный TTS без ключей: Google Translate TTS, куски ≤180 символов."""
    if not _which("ffmpeg"):
        _LAST_ERRORS["google_tts"] = "ffmpeg missing"
        return False
    chunks = _tts_chunks(text, limit=180)
    if not chunks:
        _LAST_ERRORS["google_tts"] = "empty text"
        return False
    with tempfile.TemporaryDirectory(prefix="sp_gtts_") as tmp:
        work = Path(tmp)
        paths: List[Path] = []
        for index, chunk in enumerate(chunks):
            path = work / f"chunk_{index:03d}.mp3"
            ok = False
            for _attempt in range(2):
                try:
                    response = requests.get(
                        "https://translate.google.com/translate_tts",
                        params={"ie": "UTF-8", "client": "tw-ob", "tl": lang, "q": chunk},
                        headers={"User-Agent": "Mozilla/5.0"},
                        timeout=30,
                    )
                    if response.status_code == 200 and len(response.content) > 1000:
                        path.write_bytes(response.content)
                        ok = True
                        break
                    if response.status_code == 429:
                        _LAST_ERRORS["google_tts"] = "HTTP 429 rate limit"
                    else:
                        _LAST_ERRORS["google_tts"] = f"HTTP {response.status_code} / empty audio"
                except Exception as exc:
                    _LAST_ERRORS["google_tts"] = f"{type(exc).__name__}: {exc}"[:240]
                    continue
            if not ok:
                return False
            paths.append(path)
        if len(paths) == 1:
            shutil.copyfile(paths[0], out_mp3)
        else:
            list_file = work / "list.txt"
            list_file.write_text(
                "".join(f"file '{path.as_posix()}'\n" for path in paths),
                encoding="utf-8",
            )
            result = subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                 "-i", str(list_file), "-c", "copy", str(out_mp3)],
                capture_output=True, text=True, timeout=180, check=False,
            )
            if result.returncode != 0:
                _LAST_ERRORS["google_tts"] = f"ffmpeg concat: {(result.stderr or '')[:120]}"
                return False
    ok = out_mp3.is_file() and out_mp3.stat().st_size > 1000
    if ok:
        _LAST_ERRORS.pop("google_tts", None)
    else:
        _LAST_ERRORS.setdefault("google_tts", "empty audio")
    return ok


def _synthesize_piper(text: str, out_wav: Path, model: str) -> bool:
    """Офлайн-синтез Piper (нужны бинарь `piper` и ONNX-модель)."""
    piper = _which("piper")
    if not piper:
        _LAST_ERRORS["piper"] = "piper not installed"
        return False
    if not model or not Path(model).is_file():
        _LAST_ERRORS["piper"] = "piper model missing"
        return False
    try:
        result = subprocess.run(
            [piper, "--model", model, "--output_file", str(out_wav)],
            input=text.encode("utf-8"), capture_output=True, timeout=300, check=False,
        )
        ok = result.returncode == 0 and out_wav.is_file() and out_wav.stat().st_size > 1000
        if ok:
            _LAST_ERRORS.pop("piper", None)
        else:
            _LAST_ERRORS["piper"] = (result.stderr or b"empty audio").decode("utf-8", "replace")[:240]
        return ok
    except Exception as exc:
        _LAST_ERRORS["piper"] = f"{type(exc).__name__}: {exc}"[:240]
        LOGGER.warning("piper: %s", exc)
        return False


def _synthesize_espeak(text: str, out_wav: Path, voice: str = "ru", speed: int = 150) -> bool:
    """Rule-based TTS без нейросети: espeak-ng/espeak, офлайн."""
    binary = _which("espeak-ng") or _which("espeak")
    if not binary:
        _LAST_ERRORS["espeak"] = "espeak-ng not installed"
        return False
    try:
        result = subprocess.run(
            [binary, "-v", voice, "-s", str(speed), "-w", str(out_wav)],
            input=text.encode("utf-8"), capture_output=True, timeout=180, check=False,
        )
        ok = result.returncode == 0 and out_wav.is_file() and out_wav.stat().st_size > 1000
        if ok:
            _LAST_ERRORS.pop("espeak", None)
        else:
            _LAST_ERRORS["espeak"] = (result.stderr or b"empty audio").decode("utf-8", "replace")[:240]
        return ok
    except Exception as exc:
        _LAST_ERRORS["espeak"] = f"{type(exc).__name__}: {exc}"[:240]
        LOGGER.warning("espeak: %s", exc)
        return False


def voice_available(config: Config) -> bool:
    """Доступен ли хоть один движок озвучки (для светофора /doctor)."""
    settings = voice_settings(config)
    engines = _candidate_engines(settings)
    return any(engine != "sonification" and _engine_ready(config, engine, settings) for engine in engines)


def _candidate_engines(settings: Dict[str, Any]) -> List[str]:
    """Порядок движков: явный engine → приоритет; sonification всегда последний."""
    configured = str(settings.get("engine", "auto") or "auto")
    priority = [str(item) for item in (settings.get("priority") or ENGINE_PRIORITY)]
    if configured != "auto":
        ordered = [configured, "sonification"]
    else:
        ordered = priority
    if "sonification" not in ordered:
        ordered.append("sonification")
    return ordered


def _cache_key(text: str, settings: Dict[str, Any], engine: str) -> str:
    payload = f"{text}|{engine}|{settings.get('voice', '')}|{settings.get('rate', '')}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def _engine_paths(out_dir: Path, post_id: str, engine: str) -> Tuple[Path, Path]:
    return out_dir / f"{post_id}.{engine}.mp3", out_dir / f"{post_id}.{engine}.key"


def mix_voice_with_pad(
    mp3_path: str | Path, pad_wav: str | Path, out_path: str | Path, volume: float = 0.12
) -> bool:
    """Двухслойное сведение: речь диктора + гармонический пад (ffmpeg).

    ``[1:a]volume=0.12[p];[0:a][p]amix=inputs=2:duration=first:dropout_transition=2``
    При любой ошибке возвращает False — вызывающий остаётся с чистым ``speech.mp3``.
    """
    if not _which("ffmpeg"):
        return False
    command = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", str(mp3_path), "-i", str(pad_wav),
        "-filter_complex",
        f"[1:a]volume={volume}[p];[0:a][p]amix=inputs=2:duration=first:dropout_transition=2",
        str(out_path),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=180, check=False)
    except Exception:
        return False
    return result.returncode == 0 and Path(out_path).is_file()


def _wav_to_mp3(wav_path: Path, mp3_path: Path) -> bool:
    if not _which("ffmpeg"):
        return False
    result = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav_path),
         "-b:a", "96k", str(mp3_path)],
        capture_output=True, text=True, timeout=180, check=False,
    )
    return result.returncode == 0 and mp3_path.is_file() and mp3_path.stat().st_size > 1000


def synthesize(
    text: str,
    out_dir: str | Path,
    post_id: str,
    config: Config,
    settings: Optional[Dict[str, Any]] = None,
    use_cache: bool = True,
    post: Any = None,
) -> Optional[VoiceArtifact]:
    """Синтезирует речь с адаптивной цепочкой движков и circuit breaker.

    Порядок: edge → piper → google_tts → espeak → sonification.
    Кэш хранится по движку, поэтому возврат качественного движка после
    лимита автоматически вытесняет низкокачественный fallback.
    """
    settings = settings or voice_settings(config)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    mp3_path = out_dir / f"{post_id}.mp3"
    ogg_path = out_dir / f"{post_id}.ogg"
    key_path = out_dir / f"{post_id}.key"

    engines = _candidate_engines(settings)
    engine_used = voice_used = ""
    boundaries: List[Any] = []
    ok = False

    for engine in engines:
        if engine == "sonification":
            break
        if not _engine_ready(config, engine, settings):
            continue
        cache_mp3, cache_key_path = _engine_paths(out_dir, post_id, engine)
        key = _cache_key(text, settings, engine)
        if use_cache and cache_mp3.is_file() and cache_key_path.is_file():
            try:
                if cache_key_path.read_text(encoding="utf-8") == key:
                    shutil.copyfile(cache_mp3, mp3_path)
                    engine_used = engine
                    voice_used = (
                        str(settings.get("voice") or DEFAULT_VOICE) if engine == "edge"
                        else f"piper-{settings.get('piper_voice', 'dmitri')}" if engine == "piper"
                        else "google-ru" if engine == "google_tts"
                        else f"espeak-{settings.get('espeak_voice', 'ru')}"
                    )
                    ok = True
                    break
            except OSError:
                pass
        health_path = out_dir / "voice_health.json"
        if _engine_blocked(config, engine, health_path):
            LOGGER.info("voice %s: пропуск, cooldown", engine)
            continue

        tmp_mp3 = out_dir / f".{post_id}.{engine}.tmp.mp3"
        tmp_wav = out_dir / f".{post_id}.{engine}.tmp.wav"
        try:
            if engine == "edge":
                voice_used, boundaries = _synthesize_edge(
                    text, tmp_mp3, str(settings.get("voice") or DEFAULT_VOICE),
                    str(settings.get("rate") or "+0%"),
                )
                ok = bool(voice_used)
            elif engine == "piper":
                ok = _synthesize_piper(text, tmp_wav, str(settings.get("piper_model") or ""))
                if ok:
                    ok = _wav_to_mp3(tmp_wav, tmp_mp3)
                voice_used = f"piper-{settings.get('piper_voice', 'dmitri')}" if ok else ""
            elif engine == "google_tts":
                ok = _synthesize_google(text, tmp_mp3)
                voice_used = "google-ru" if ok else ""
            elif engine == "espeak":
                ok = _synthesize_espeak(
                    text, tmp_wav, str(settings.get("espeak_voice") or "ru"),
                    int(settings.get("espeak_speed") or 150),
                )
                if ok:
                    ok = _wav_to_mp3(tmp_wav, tmp_mp3)
                voice_used = f"espeak-{settings.get('espeak_voice', 'ru')}" if ok else ""
            if ok and tmp_mp3.is_file() and tmp_mp3.stat().st_size > 1000:
                shutil.copyfile(tmp_mp3, mp3_path)
                shutil.copyfile(tmp_mp3, cache_mp3)
                cache_key_path.write_text(key, encoding="utf-8")
                _record_success(config, engine, health_path)
                engine_used = engine
                break
            error = _LAST_ERRORS.get(engine, "no audio")
            _record_failure(config, engine, error, settings, health_path)
        finally:
            for temp in (tmp_mp3, tmp_wav):
                try:
                    temp.unlink()
                except OSError:
                    pass

    if not ok and post is not None:
        # Эшелон 3: офлайн-сонификация (без TTS) → mp3/ogg.
        fallback_wav = out_dir / f"{post_id}.sonify.wav"
        try:
            from .sound import synthesize_scientific_audio_wav

            if synthesize_scientific_audio_wav(post, fallback_wav) and _which("ffmpeg"):
                convert = subprocess.run(
                    ["ffmpeg", "-y", "-loglevel", "error", "-i", str(fallback_wav),
                     "-b:a", "96k", str(mp3_path)],
                    capture_output=True, text=True, timeout=180, check=False,
                )
                ok = convert.returncode == 0 and mp3_path.is_file()
                if ok:
                    engine_used, voice_used = "sonification_fallback", "sonification"
        except Exception as exc:
            LOGGER.warning("Сонификация не удалась для %s: %s", post_id, exc)
        finally:
            try:
                fallback_wav.unlink()
            except OSError:
                pass

    if not ok:
        LOGGER.warning("Озвучка не удалась для %s (движки: %s)", post_id, ", ".join(engines))
        return None

    # Двухслойное сведение: речь + гармонический пад (при ошибке — чистый mp3).
    if post is not None and engine_used != "sonification_fallback":
        pad_wav = out_dir / f"{post_id}.pad.wav"
        mixed_mp3 = out_dir / f"{post_id}.mixed.mp3"
        try:
            from .sound import synthesize_scientific_audio_wav

            if synthesize_scientific_audio_wav(post, pad_wav) and mix_voice_with_pad(mp3_path, pad_wav, mixed_mp3):
                mp3_path.write_bytes(mixed_mp3.read_bytes())
        except Exception as exc:
            LOGGER.debug("Микс с падом пропущен для %s: %s", post_id, exc)
        finally:
            for temp in (pad_wav, mixed_mp3):
                try:
                    temp.unlink()
                except OSError:
                    pass

    _to_voice_ogg(mp3_path, ogg_path)
    if engine_used == "sonification_fallback":
        # Фоллбэк НЕ кэшируем: иначе сонификация остаётся под ключом настоящей
        # речи и заглушает голос после восстановления TTS.
        try:
            key_path.unlink()
        except OSError:
            pass
    else:
        key_path.write_text(_cache_key(text, settings, engine_used), encoding="utf-8")

    duration = _duration_seconds(mp3_path)
    segments = _boundaries_to_segments(boundaries) if boundaries else _approximate_segments(text, duration or 10.0)
    subtitles = write_subtitles(segments, mp3_path)
    words = _words_from_boundaries(boundaries) if boundaries else _approximate_words(text, duration or 10.0)
    return VoiceArtifact(
        post_id=post_id, text=text, mp3_path=str(mp3_path),
        ogg_path=str(ogg_path) if ogg_path.is_file() else "",
        duration_s=duration, engine=engine_used, voice=voice_used,
        vtt_path=subtitles.get("vtt", ""), srt_path=subtitles.get("srt", ""),
        segments=segments, words=words,
    )


def _hex_to_ffmpeg(color: str) -> str:
    """#1E3A8A → 0x1E3A8A (формат цвета в фильтрах ffmpeg)."""
    value = str(color or "").strip().lstrip("#")
    return f"0x{value}" if value else "0x1E3A8A"


def build_audiogram_mp4(
    card_png_path: str | Path,
    audio_mp3_path: str | Path,
    out_mp4_path: str | Path,
    wave: bool = True,
    wave_color: str = "#1E3A8A",
    post: Any = None,
    animate_frames: int = 0,
) -> bool:
    """Склеивает карточку 1080×1080 и голос в MP4, добавляя живую осциллограмму.

    Нужно для соцсетей, которые не принимают «голые» `.ogg`/`.mp3`
    (Threads, Bluesky, VK): в ленте видно книжную страницу и слышен диктор.
    Фильтр `showwaves` рисует бегущую звуковую волну прямо над колонтитулом,
    поэтому ролик сразу читается как «видео со звуком». Если фильтр недоступен —
    мягкий fallback на статичную картинку.
    """
    if not _which("ffmpeg"):
        return False
    card_png_path, audio_mp3_path, out_mp4_path = Path(card_png_path), Path(audio_mp3_path), Path(out_mp4_path)
    if not card_png_path.is_file() or not audio_mp3_path.is_file():
        return False
    out_mp4_path.parent.mkdir(parents=True, exist_ok=True)

    tail = ["-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", str(out_mp4_path)]

    # Живой чертёж: вместо статичной карточки — кадры анимации, растянутые на голос.
    video_input = ["-loop", "1", "-i", str(card_png_path)]
    animation_dir = None
    if post is not None and animate_frames > 1:
        try:
            import tempfile

            from .video import _render_frames

            animation_dir = tempfile.TemporaryDirectory(prefix="sp_anim_")
            frames_path = Path(animation_dir.name)
            written = _render_frames(post, frames_path, frames=animate_frames)
            if written > 1:
                duration = _duration_seconds(Path(audio_mp3_path)) or 10.0
                fps = animate_frames / max(duration, 1.0)
                video_input = ["-framerate", f"{fps:.4f}", "-i", str(frames_path / "frame_%03d.png")]
        except Exception as exc:
            LOGGER.warning("animate frames: %s", exc)
            video_input = ["-loop", "1", "-i", str(card_png_path)]

    try:
        if wave:
            color = _hex_to_ffmpeg(wave_color)
            filter_complex = (
                f"[1:a]showwaves=s=936x56:mode=cline:colors={color}@0.85[w];"
                f"[0:v][w]overlay=72:940:shortest=1,format=yuv420p[v]"
            )
            result = subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", *video_input,
                 "-i", str(audio_mp3_path), "-filter_complex", filter_complex,
                 "-map", "[v]", "-map", "1:a", *tail],
                capture_output=True, text=True, timeout=600, check=False,
            )
            if result.returncode == 0 and out_mp4_path.is_file() and out_mp4_path.stat().st_size > 1000:
                return True
            LOGGER.warning("showwaves недоступен (%s), fallback на статичную картинку",
                           (result.stderr or "")[:160])

        result = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", *video_input,
             "-i", str(audio_mp3_path), *tail],
            capture_output=True, text=True, timeout=600, check=False,
        )
        if result.returncode != 0:
            LOGGER.warning("audiogram: %s", (result.stderr or "")[:200])
            return False
        return out_mp4_path.is_file() and out_mp4_path.stat().st_size > 1000
    except Exception as exc:
        LOGGER.warning("audiogram: %s", exc)
        return False
    finally:
        if animation_dir is not None:
            animation_dir.cleanup()


WAVE_COLORS = {"math": "#1E3A8A", "physics": "#9F1239", "cs": "#B45309"}
# Сколько кадров «ожившего чертежа» рисовать для видео-аудиограммы.
ANIMATED_FRAMES = 36


def audiogram_for_post(post: Post, config: Config, card_path: str | Path | None = None,
                       out_dir: str | Path | None = None, animate: bool = True) -> Optional[Path]:
    """Видео-аудиограмма поста (живой чертёж + голос) с кэшем в `data/audiogram/`."""
    directory = Path(out_dir) if out_dir else config.data_dir / "audiogram"
    target = directory / f"{post.id}.mp4"
    key_path = directory / f"{post.id}.key"
    if card_path:
        card = Path(card_path)
    elif post.card_path and Path(post.card_path).is_file():
        card = Path(post.card_path)
    else:
        card = config.cards_dir / f"{post.id}.png"
    if not card.is_file():
        return None
    artifact = voice_for_post(post, config)
    if artifact is None:
        return None
    wave_color = WAVE_COLORS.get(getattr(post, "domain", "math"), WAVE_COLORS["math"])
    text_hash = hashlib.sha1((artifact.text or "").encode("utf-8")).hexdigest()[:12]
    key = f"{card}:{artifact.mp3_path}:{text_hash}:{artifact.engine}:{artifact.voice}:{wave_color}:{animate}"
    if target.is_file() and key_path.is_file() and key_path.read_text(encoding="utf-8") == key:
        return target
    if not build_audiogram_mp4(
        card, artifact.mp3_path, target, wave_color=wave_color,
        post=post if animate else None,
        animate_frames=ANIMATED_FRAMES if animate else 0,
    ):
        return None
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_text(key, encoding="utf-8")
    return target


def film_voice_for_post(post: Post, config: Config, out_dir: str | Path | None = None,
                        max_chars: int = 520) -> Optional[VoiceArtifact]:
    """Короткая озвучка для book-фильма: 5 актов по 5–7 секунд."""
    settings = voice_settings(config)
    settings = dict(settings)
    settings["max_chars"] = int(max_chars)
    directory = Path(out_dir) if out_dir else config.data_dir / "audio"
    text = build_film_script(post)
    if len(text) < 40:
        return None
    return synthesize(text, directory, f"{post.id}_film", config, settings, post=post)


def voice_for_post(post: Post, config: Config, out_dir: str | Path | None = None) -> Optional[VoiceArtifact]:
    """Озвучка поста с кэшем в `data/audio/<id>.mp3` (детерминированно)."""
    settings = voice_settings(config)
    directory = Path(out_dir) if out_dir else config.data_dir / "audio"
    text = speech_text(post, settings["max_chars"])
    if len(text) < 40:
        return None
    return synthesize(text, directory, post.id, config, settings, post=post)
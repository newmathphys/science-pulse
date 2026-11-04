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
import logging
import re
import shutil
import subprocess
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


def _which(binary: str) -> Optional[str]:
    return shutil.which(binary)


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
    return text.strip()


# Фонетический словарь формул: печатный текст не меняется, меняется только речь.
# Порядок важен: длинные конструкции заменяются раньше коротких.
_SPOKEN_RULES: tuple = (
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


def build_lecture_script(post: Post, max_chars: int = 900) -> str:
    """Пятиблочный лекционный сценарий для диктора (без URL, тегов и эмодзи).

    Блоки:
    1) **дисциплина, эпоха и первоисточник**: «Раздел Физика. Параграф 5.1.
       1926, Цюрих. Эрвин Шрёдингер. Первоисточник: …»;
    2) **проблема-крючок**: «Фундаментальный вопрос: …»;
    3) **математическое решение словами**: суть + фонетика формулы + «где: …»;
    4) **связь времён**: «Применение сегодня: …»;
    5) **мост к следующему уровню**: «опирается на … и открывает дорогу к …».
    """
    meta = getattr(post, "meta", {}) or {}
    parts: List[str] = []

    domain_label = {"math": "Математика", "physics": "Физика", "cs": "Информатика"}.get(
        getattr(post, "domain", "math"), "Наука")

    # --- Блок 1: дисциплина, эпоха, первоисточник --------------------------
    block_one = [f"Раздел {domain_label}."]
    section = _strip_links_tags(str(meta.get("section_num") or ""))
    if section:
        block_one.append(f"Параграф {section}.")
    era = _strip_links_tags(str(meta.get("era") or ""))
    scientist = _strip_links_tags(str(meta.get("scientist") or ""))
    context = ". ".join(part for part in (era, scientist) if part)
    if context:
        block_one.append(f"{context}.")
    lineage = meta.get("source_lineage") if isinstance(meta.get("source_lineage"), dict) else {}
    primary = _strip_links_tags(str((lineage or {}).get("primary_work") or ""))
    if primary:
        block_one.append(f"Первоисточник: {primary}.")
    title = _strip_links_tags(_speech_clean(post.title))
    if title:
        block_one.append(f"{title}.")
    parts.append(" ".join(block_one))

    # --- Блок 2: проблема-крючок -------------------------------------------
    hook = _strip_links_tags(_speech_clean(post.hook or ""))
    if hook:
        parts.append(f"Фундаментальный вопрос: {hook}")

    # --- Блок 3: математическое решение словами ---------------------------
    block_three: List[str] = []
    body = _strip_links_tags(_speech_clean(post.body or ""))
    if body:
        block_three.append(body)
    variables = _strip_links_tags(_speech_clean(str(meta.get("formula_vars") or "")))
    if variables:
        block_three.append(f"где: {variables}.")
    if block_three:
        parts.append(" ".join(block_three))

    # --- Блок 4: связь времён ----------------------------------------------
    application = _strip_links_tags(_speech_clean(str(meta.get("modern_application") or "")))
    if application:
        parts.append(f"Применение сегодня: {application}.")

    # --- Блок 5: задача слушателю и мост к следующему уровню ----------------
    challenge_question = ""
    try:
        from .challenge import build_challenge

        challenge_question = _strip_links_tags(
            _speech_clean(str(build_challenge(post).get("question") or ""))
        )
    except Exception:  # pragma: no cover - защитный контур
        challenge_question = ""
    if challenge_question:
        parts.append(f"Задача слушателю: {challenge_question} Ответ проверите на тренажёре сайта.")

    prereqs = _canon_titles([str(item) for item in (meta.get("prereq_ids") or [])])
    unlocks = [str(item) for item in (meta.get("unlocks_concepts") or [])][:3]
    bridge: List[str] = []
    if prereqs:
        bridge.append(f"Это знание опирается на {', '.join(prereqs)}")
    if unlocks:
        bridge.append(f"и открывает дорогу к теме: {', '.join(unlocks)}")
    if bridge:
        parts.append(" ".join(bridge) + ". Эфир продолжается.")

    formula = _strip_links_tags(_speech_clean(post.formula_plain or ""))
    formula_spoken = math_to_spoken_russian(formula) if formula else ""
    formula_part = f" Формула: {formula_spoken}." if formula_spoken else ""
    budget = max(80, max_chars - len(formula_part))

    # Нормализуем формулы в слова ДО расчёта лимита, иначе длина «поедет».
    parts = [math_to_spoken_russian(part) for part in parts if part]
    text = " ".join(parts)
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
    return f"{text}{formula_part}".strip()



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


def _synthesize_edge(text: str, out_mp3: Path, voice: str, rate: str = "+0%") -> Tuple[str, List[Any]]:
    """Онлайн-синтез Edge TTS с таймкодами слов (для субтитров).

    Возвращает `(голос, boundaries)`: имя рабочего голоса и список
    `(offset, duration, word)` в 100-нс единицах edge-tts.
    """
    try:
        import asyncio

        import edge_tts
    except ImportError:
        return "", []

    candidates = [voice] + [item for item in EDGE_VOICES if item != voice]

    async def run(candidate: str) -> List[Any]:
        communicate = edge_tts.Communicate(text, candidate, rate=rate)
        boundaries: List[Any] = []
        with open(out_mp3, "wb") as handle:
            async for chunk in communicate.stream():
                if chunk.get("type") == "audio":
                    handle.write(chunk["data"])
                elif chunk.get("type") in ("WordBoundary", "SentenceBoundary"):
                    boundaries.append((chunk.get("offset", 0), chunk.get("duration", 0), chunk.get("text", "")))
        if out_mp3.is_file() and out_mp3.stat().st_size > 1000:
            return boundaries
        return []

    for candidate in candidates:
        try:
            boundaries = asyncio.run(run(candidate))
        except Exception as exc:
            LOGGER.warning("edge-tts %s: %s", candidate, str(exc)[:120])
            boundaries = []
        if boundaries:
            return candidate, boundaries
        if out_mp3.is_file() and out_mp3.stat().st_size > 1000:
            return candidate, []
        try:
            out_mp3.unlink()
        except OSError:
            pass
    return "", []


def _synthesize_piper(text: str, out_wav: Path, model: str) -> bool:
    """Офлайн-синтез Piper (нужны бинарь `piper` и ONNX-модель)."""
    piper = _which("piper")
    if not piper or not model or not Path(model).is_file():
        return False
    try:
        result = subprocess.run(
            [piper, "--model", model, "--output_file", str(out_wav)],
            input=text.encode("utf-8"), capture_output=True, timeout=300, check=False,
        )
        return result.returncode == 0 and out_wav.is_file() and out_wav.stat().st_size > 1000
    except Exception as exc:
        LOGGER.warning("piper: %s", exc)
        return False


def voice_available(config: Config) -> bool:
    """Доступен ли хоть один движок озвучки (для светофора /doctor)."""
    settings = voice_settings(config)
    engine = settings["engine"]
    if engine in ("edge", "auto"):
        import importlib.util

        if importlib.util.find_spec("edge_tts") is not None:
            return True
    if engine in ("piper", "auto"):
        if _which("piper") and settings["piper_model"]:
            return True
    return False


def _cache_key(text: str, settings: Dict[str, Any]) -> str:
    payload = f"{text}|{settings['engine']}|{settings['voice']}|{settings['rate']}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


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


def synthesize(
    text: str,
    out_dir: str | Path,
    post_id: str,
    config: Config,
    settings: Optional[Dict[str, Any]] = None,
    use_cache: bool = True,
    post: Any = None,
) -> Optional[VoiceArtifact]:
    """Синтезирует речь и возвращает `VoiceArtifact` (или None при неудаче)."""
    settings = settings or voice_settings(config)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    mp3_path = out_dir / f"{post_id}.mp3"
    ogg_path = out_dir / f"{post_id}.ogg"
    key_path = out_dir / f"{post_id}.key"
    key = _cache_key(text, settings)

    if use_cache and mp3_path.is_file() and key_path.is_file() and key_path.read_text(encoding="utf-8") == key:
        if not ogg_path.is_file():
            _to_voice_ogg(mp3_path, ogg_path)
        duration = _duration_seconds(mp3_path)
        vtt_path = mp3_path.with_suffix(".vtt")
        if not vtt_path.is_file():
            # Кэш без таймкодов: строим приблизительные субтитры по тексту.
            write_subtitles(_approximate_segments(text, duration or 10.0), mp3_path)
        return VoiceArtifact(post_id=post_id, text=text, mp3_path=str(mp3_path),
                             ogg_path=str(ogg_path) if ogg_path.is_file() else "",
                             duration_s=duration,
                             engine=settings["engine"], voice=settings["voice"],
                             vtt_path=str(vtt_path) if vtt_path.is_file() else "",
                             srt_path=str(mp3_path.with_suffix(".srt")) if mp3_path.with_suffix(".srt").is_file() else "")

    engine = settings["engine"]
    engine_used = voice_used = ""
    boundaries: List[Any] = []
    ok = False
    if engine in ("edge", "auto"):
        voice_used, boundaries = _synthesize_edge(text, mp3_path, settings["voice"], settings["rate"])
        ok = bool(voice_used)
        engine_used = "edge" if ok else ""
    if not ok and engine in ("piper", "auto"):
        wav_path = out_dir / f"{post_id}.wav"
        if _synthesize_piper(text, wav_path, settings["piper_model"]) and _which("ffmpeg"):
            convert = subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav_path), "-b:a", "96k", str(mp3_path)],
                capture_output=True, text=True, timeout=180, check=False,
            )
            ok = convert.returncode == 0 and mp3_path.is_file()
            engine_used, voice_used = ("piper", "piper") if ok else ("", "")
        try:
            wav_path.unlink()
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
        LOGGER.warning("Озвучка не удалась для %s (движок %s)", post_id, engine)
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
    key_path.write_text(key, encoding="utf-8")
    duration = _duration_seconds(mp3_path)
    segments = _boundaries_to_segments(boundaries) if boundaries else _approximate_segments(text, duration or 10.0)
    subtitles = write_subtitles(segments, mp3_path)
    return VoiceArtifact(
        post_id=post_id, text=text, mp3_path=str(mp3_path),
        ogg_path=str(ogg_path) if ogg_path.is_file() else "",
        duration_s=duration, engine=engine_used, voice=voice_used,
        vtt_path=subtitles.get("vtt", ""), srt_path=subtitles.get("srt", ""),
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
    card = Path(card_path) if card_path else (Path(post.card_path) if post.card_path else config.cards_dir / f"{post.id}.png")
    if not card.is_file():
        return None
    artifact = voice_for_post(post, config)
    if artifact is None:
        return None
    wave_color = WAVE_COLORS.get(getattr(post, "domain", "math"), WAVE_COLORS["math"])
    key = f"{card}:{artifact.mp3_path}:{artifact.engine}:{artifact.voice}:{wave_color}:{animate}"
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


def voice_for_post(post: Post, config: Config, out_dir: str | Path | None = None) -> Optional[VoiceArtifact]:
    """Озвучка поста с кэшем в `data/audio/<id>.mp3` (детерминированно)."""
    settings = voice_settings(config)
    directory = Path(out_dir) if out_dir else config.data_dir / "audio"
    text = speech_text(post, settings["max_chars"])
    if len(text) < 40:
        return None
    return synthesize(text, directory, post.id, config, settings, post=post)
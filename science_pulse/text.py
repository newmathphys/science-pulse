from __future__ import annotations

import hashlib
import html
import re
import threading
import time
from typing import Iterable, List, Sequence, Tuple

PROTECTED_RE = re.compile(
    r"```.*?```"
    r"|\$\$.*?\$\$"
    r"|\\\[.*?\\\]"
    r"|\\\(.*?\\\)"
    r"|\$[^$\n]{1,240}\$"
    r"|`[^`\n]{1,240}`",
    re.DOTALL,
)

HTML_TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"[ \t\u00a0]+")
MULTI_NEWLINE_RE = re.compile(r"\n{3,}")

SUPERSCRIPT = str.maketrans(
    {
        "0": "⁰",
        "1": "¹",
        "2": "²",
        "3": "³",
        "4": "⁴",
        "5": "⁵",
        "6": "⁶",
        "7": "⁷",
        "8": "⁸",
        "9": "⁹",
        "+": "⁺",
        "-": "⁻",
        "=": "⁼",
        "(": "⁽",
        ")": "⁾",
        "n": "ⁿ",
    }
)

SUBSCRIPTS = str.maketrans(
    {
        "0": "₀",
        "1": "₁",
        "2": "₂",
        "3": "₃",
        "4": "₄",
        "5": "₅",
        "6": "₆",
        "7": "₇",
        "8": "₈",
        "9": "₉",
        "+": "₊",
        "-": "₋",
        "=": "₌",
        "(": "₍",
        ")": "₎",
        "i": "ᵢ",
        "j": "ⱼ",
        "k": "ₖ",
        "n": "ₙ",
        "m": "ₘ",
    }
)

MATH_GREEK = {
    r"\alpha": "α",
    r"\beta": "β",
    r"\gamma": "γ",
    r"\delta": "δ",
    r"\epsilon": "ε",
    r"\theta": "θ",
    r"\lambda": "λ",
    r"\mu": "μ",
    r"\pi": "π",
    r"\rho": "ρ",
    r"\sigma": "σ",
    r"\tau": "τ",
    r"\phi": "φ",
    r"\varphi": "φ",
    r"\omega": "ω",
    r"\Delta": "Δ",
    r"\Omega": "Ω",
    r"\hbar": "ℏ",
    r"\sum": "Σ",
    r"\prod": "∏",
    r"\int": "∫",
    r"\oint": "∮",
    r"\infty": "∞",
    r"\partial": "∂",
    r"\nabla": "∇",
    r"\pm": "±",
    r"\mp": "∓",
    r"\times": "×",
    r"\cdot": "·",
    r"\le": "≤",
    r"\ge": "≥",
    r"\ne": "≠",
    r"\approx": "≈",
    r"\to": "→",
    r"\rightarrow": "→",
    r"\Rightarrow": "⇒",
    r"\iff": "⇔",
    r"\forall": "∀",
    r"\exists": "∃",
    r"\in": "∈",
    r"\notin": "∉",
    r"\subset": "⊂",
    r"\cup": "∪",
    r"\cap": "∩",
    r"\log": "log",
    r"\ln": "ln",
    r"\sin": "sin",
    r"\cos": "cos",
    r"\tan": "tan",
    r"\exp": "exp",
}


def strip_html(value: str) -> str:
    if not value:
        return ""
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", value)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p\s*>", "\n\n", text)
    text = HTML_TAG_RE.sub(" ", text)
    return html.unescape(text)


def normalize_whitespace(value: str) -> str:
    if not value:
        return ""
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    text = SPACE_RE.sub(" ", text)
    text = MULTI_NEWLINE_RE.sub("\n\n", text)
    return "\n".join(line.strip() for line in text.splitlines()).strip()


def clean_text(value: str, max_len: int | None = None) -> str:
    text = normalize_whitespace(strip_html(value or ""))
    if max_len and len(text) > max_len:
        cut = text[:max_len]
        for sep in (". ", "! ", "? ", "; ", " "):
            idx = cut.rfind(sep)
            if idx > max_len * 0.6:
                return cut[: idx + len(sep)].strip()
        return cut.rstrip() + "…"
    return text


def mask_protected(text: str) -> Tuple[str, List[str]]:
    """Прячет формулы и код от переводчика/нарезчика."""
    saved: List[str] = []

    def repl(match: re.Match[str]) -> str:
        saved.append(match.group(0))
        return f"ZZZP{len(saved) - 1}ZZZ"

    return PROTECTED_RE.sub(repl, text or ""), saved


def unmask_protected(text: str, saved: Sequence[str]) -> str:
    result = text or ""
    for index, original in enumerate(saved):
        result = result.replace(f"ZZZP{index}ZZZ", original)
    return result


def _looks_russian(text: str) -> bool:
    letters = re.findall(r"[A-Za-zА-Яа-яЁё]", text or "")
    if not letters:
        return False
    cyrillic = sum(1 for char in letters if "А" <= char <= "я" or char in "Ёё")
    return cyrillic / len(letters) > 0.35


def _translate_chunks(translator, text: str, chunk_size: int) -> str:
    chunks: List[str] = []
    current = ""
    for piece in re.split(r"(?<=[.!?])\s+", text):
        if len(piece) > chunk_size:
            if current:
                chunks.append(current)
                current = ""
            words = piece.split()
            word_buffer = ""
            for word in words:
                candidate = f"{word_buffer} {word}".strip() if word_buffer else word
                if len(candidate) <= chunk_size:
                    word_buffer = candidate
                else:
                    if word_buffer:
                        chunks.append(word_buffer)
                    word_buffer = word
            if word_buffer:
                chunks.append(word_buffer)
            continue
        if len(current) + len(piece) + 1 > chunk_size:
            if current:
                chunks.append(current)
            current = piece
        else:
            current = f"{current} {piece}".strip()
    if current:
        chunks.append(current)

    translated = []
    for chunk in chunks:
        try:
            translated.append(translator.translate(chunk) or chunk)
        except Exception:
            translated.append(chunk)
    return " ".join(translated)


_GTX_LOCK = threading.Lock()
_GTX_LAST = [0.0]
_GTX_BLOCK_UNTIL = [0.0]
GTX_MIN_INTERVAL = 0.7  # сек между запросами (мягкий троттлинг против 429)
GTX_COOLDOWN = 300.0    # сек «карантина» после упорного 429


def translate_via_gtx(text: str, sl: str = "en", tl: str = "ru", retries: int = 3) -> str:
    """Google JSON-эндпоинт (client=gtx): без внешних зависимостей и без лимита слов.

    Работает на стандартной библиотеке (`urllib`), не парсит HTML-страницу,
    поэтому не получает `TooManyRequests` как `deep_translator.GoogleTranslator`.
    Защищён троттлингом и backoff; при упорном HTTP 429 уходит в «карантин»
    (`GTX_COOLDOWN`), чтобы не тормозить пакетную обработку.
    """
    import json
    import urllib.error
    import urllib.parse
    import urllib.request

    if time.time() < _GTX_BLOCK_UNTIL[0]:
        raise RuntimeError("gtx: cooldown after HTTP 429")

    url = (
        "https://translate.googleapis.com/translate_a/single"
        f"?client=gtx&sl={sl}&tl={tl}&dt=t&q={urllib.parse.quote(text)}"
    )
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})

    for attempt in range(max(1, retries)):
        with _GTX_LOCK:
            wait = GTX_MIN_INTERVAL - (time.time() - _GTX_LAST[0])
            if wait > 0:
                time.sleep(wait)
            try:
                with urllib.request.urlopen(request, timeout=8) as response:
                    data = json.loads(response.read().decode("utf-8"))
                _GTX_LAST[0] = time.time()
                return "".join(part[0] for part in (data[0] or []) if part and part[0])
            except urllib.error.HTTPError as exc:
                _GTX_LAST[0] = time.time()
                if exc.code == 429:
                    if attempt < retries - 1:
                        time.sleep(2.0 * (attempt + 1))
                        continue
                    _GTX_BLOCK_UNTIL[0] = time.time() + GTX_COOLDOWN
                raise
    return ""


_MYMEM_LOCK = threading.Lock()
_MYMEM_LAST = [0.0]
MYMEM_MIN_INTERVAL = 0.5


def translate_via_mymemory(text: str, sl: str = "en", tl: str = "ru") -> str:
    """MyMemory HTTP API (без deep-translator): бесплатно, ~1000 слов/сутки без ключа."""
    import json
    import urllib.parse
    import urllib.request

    langpair = f"{sl}|{tl}"
    url = (
        "https://api.mymemory.translated.net/get"
        f"?q={urllib.parse.quote(text)}&langpair={urllib.parse.quote(langpair)}"
    )
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with _MYMEM_LOCK:
        wait = MYMEM_MIN_INTERVAL - (time.time() - _MYMEM_LAST[0])
        if wait > 0:
            time.sleep(wait)
        with urllib.request.urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
        _MYMEM_LAST[0] = time.time()
    result = (data.get("responseData") or {}).get("translatedText") or ""
    if "MYMEMORY WARNING" in result or "QUERY LENGTH LIMIT" in result:
        return ""
    return result


class _CallableTranslator:
    """Адаптер функции-переводчика под интерфейс `_translate_chunks`."""

    def __init__(self, func):
        self._func = func

    def translate(self, chunk: str) -> str:
        return self._func(chunk)


def translate_text(text: str, target: str = "ru", source: str = "en") -> str:
    """Перевод без LLM, эшелоны провайдеров.

    1. **gtx** — JSON-эндпоинт Google (`translate.googleapis.com`), без внешних
       зависимостей и без лимита слов (работает даже без `deep-translator`).
    2. **MyMemory HTTP** (`api.mymemory.translated.net`) — без зависимостей,
       ~1000 слов/сутки без ключа.
    3. **deep-translator** — `GoogleTranslator`, затем `MyMemoryTranslator`
       (если пакет установлен).

    Если все недоступны — возвращается исходный текст (публикация не блокируется).
    """
    if not text or _looks_russian(text):
        return text

    # 1) gtx (основной канал, без зависимостей)
    try:
        gtx = _CallableTranslator(lambda chunk: translate_via_gtx(chunk, source, target))
        result = _translate_chunks(gtx, text, 4000)
        if result and result != text and (target != "ru" or _looks_russian(result)):
            return result
    except Exception:
        pass

    # 2) MyMemory HTTP (без зависимостей)
    try:
        mymem = _CallableTranslator(lambda chunk: translate_via_mymemory(chunk, source, target))
        result = _translate_chunks(mymem, text, 450)
        if result and (target != "ru" or _looks_russian(result)):
            return result
    except Exception:
        pass

    try:
        from deep_translator import GoogleTranslator, MyMemoryTranslator  # type: ignore
    except Exception:
        return text

    # 2) deep-translator: Google
    try:
        translator = GoogleTranslator(source=source, target=target)
        result = _translate_chunks(translator, text, 4200)
        if result and result != text and (target != "ru" or _looks_russian(result)):
            return result
    except Exception:
        pass

    # 3) deep-translator: MyMemory
    try:
        source_code = "en-GB" if source == "en" else source
        target_code = "ru-RU" if target == "ru" else target
        translator = MyMemoryTranslator(source=source_code, target=target_code)
        result = _translate_chunks(translator, text, 450)
        if result and (target != "ru" or _looks_russian(result)):
            return result
    except Exception:
        pass
    return text


def translate_preserving_latex(text: str, target: str = "ru") -> str:
    masked, saved = mask_protected(text)
    translated = translate_text(masked, target=target)
    return unmask_protected(translated, saved)


def _tokens(text: str) -> List[str]:
    words = re.findall(r"[\wа-яА-ЯёЁ]{3,}", (text or "").lower())
    stop = {
        "это",
        "как",
        "для",
        "что",
        "или",
        "the",
        "and",
        "with",
        "from",
        "this",
        "that",
        "are",
        "was",
        "were",
        "will",
        "can",
        "not",
        "you",
        "your",
    }
    return [word for word in words if word not in stop]


def simhash64(text: str) -> int:
    vector = [0] * 64
    words = _tokens(text)
    if not words:
        words = [str(len(text or ""))]
    shingles = words if len(words) < 4 else [" ".join(words[i : i + 3]) for i in range(len(words) - 2)]
    for shingle in shingles:
        digest = hashlib.blake2b(shingle.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "big")
        for bit in range(64):
            vector[bit] += 1 if (value >> bit) & 1 else -1
    result = 0
    for bit, weight in enumerate(vector):
        if weight > 0:
            result |= 1 << bit
    return result


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def fingerprint(post: object) -> str:
    title = getattr(post, "title", "")
    body = getattr(post, "body", "")
    formula = getattr(post, "formula_plain", "") or getattr(post, "formula_latex", "")
    raw = f"{title.lower().strip()}|{body[:220].lower().strip()}|{formula.lower().strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def is_near_duplicate(hash_a: int, hash_b: int, threshold: int = 6) -> bool:
    return hamming(hash_a, hash_b) <= threshold


# Уровни высоты столбика в левой колонке символа Брайля (точки 7,3,2,1).
BRAILLE_LEVELS = (0x00, 0x40, 0x44, 0x46, 0x47)


def braille_sparkline(values: Iterable[float], width: int = 16) -> str:
    """Мини-осциллограмма текстом: значения → строка символов Брайля.

    Каждый символ ``U+2800 + уровень`` кодирует столбик высоты 0..4 точками
    левой колонки (как в ``btop``/``htop``). Если значений больше ``width``,
    они усредняются по корзинам; пустой вход → пустая строка.
    """
    data = [float(value) for value in (values or [])]
    if not data or width <= 0:
        return ""
    if len(data) > width:
        step = len(data) / width
        buckets: List[float] = []
        for index in range(width):
            start = int(index * step)
            end = max(start + 1, int((index + 1) * step))
            chunk = data[start:end]
            buckets.append(sum(chunk) / len(chunk) if chunk else 0.0)
        data = buckets
    low, high = min(data), max(data)
    span = (high - low) or 1.0
    chars: List[str] = []
    for value in data:
        level = int(round((value - low) / span * 4))
        chars.append(chr(0x2800 + BRAILLE_LEVELS[max(0, min(4, level))]))
    return "".join(chars)


def split_text(text: str, limit: int = 500) -> List[str]:
    """Режет текст по границам предложений/слов, не разрывая формулы."""
    if limit < 40:
        raise ValueError("limit слишком мал")
    if not text:
        return [""]

    masked, saved = mask_protected(text)

    def visible(value: str) -> str:
        return unmask_protected(value, saved)

    def visible_len(value: str) -> int:
        return len(visible(value))

    units = [unit.strip() for unit in re.split(r"(?<=[.!?])\s+|\n{2,}", masked) if unit.strip()]
    pieces: List[str] = []
    current = ""

    for unit in units:
        candidate = f"{current} {unit}".strip() if current else unit
        if visible_len(candidate) <= limit:
            current = candidate
            continue
        if current:
            pieces.append(current)
            current = ""
        if visible_len(unit) <= limit:
            current = unit
            continue

        words = unit.split()
        for word in words:
            candidate_word = f"{current} {word}".strip() if current else word
            if visible_len(candidate_word) <= limit:
                current = candidate_word
            else:
                if current:
                    pieces.append(current)
                current = word
    if current:
        pieces.append(current)

    return [visible(piece) for piece in pieces if piece]


def truncate(text: str, limit: int, suffix: str = "…") -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    if limit <= len(suffix):
        return text[:limit]
    return text[: limit - len(suffix)].rstrip() + suffix


def _brace_content(text: str, start: int) -> tuple[str | None, int]:
    if start >= len(text) or text[start] != "{":
        return None, start
    depth = 0
    for index in range(start, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1 : index], index + 1
    return None, start


def _latex_to_plain(text: str) -> str:
    result: List[str] = []
    index = 0
    wrappers = ("\\textrm", "\\text", "\\mathrm", "\\mathbf", "\\mathit")
    while index < len(text):
        if text.startswith("\\frac", index):
            numerator, end = _brace_content(text, index + 5)
            if numerator is not None:
                denominator, end2 = _brace_content(text, end)
                if denominator is not None:
                    result.append(f"({_latex_to_plain(numerator)})/({_latex_to_plain(denominator)})")
                    index = end2
                    continue
        if text.startswith("\\sqrt", index):
            content, end = _brace_content(text, index + 5)
            if content is not None:
                result.append(f"√({_latex_to_plain(content)})")
                index = end
                continue
        matched_wrapper = next((wrapper for wrapper in wrappers if text.startswith(wrapper, index)), None)
        if matched_wrapper:
            content, end = _brace_content(text, index + len(matched_wrapper))
            if content is not None:
                result.append(_latex_to_plain(content))
                index = end
                continue
        result.append(text[index])
        index += 1

    plain = "".join(result)
    plain = re.sub(r"\\mathbb\{R\}", "ℝ", plain)
    plain = re.sub(r"\\mathbb\{N\}", "ℕ", plain)
    plain = re.sub(r"\\mathbb\{Z\}", "ℤ", plain)
    plain = re.sub(r"\\mathbb\{C\}", "ℂ", plain)
    plain = re.sub(r"\\mathcal\{O\}", "O", plain)
    plain = plain.replace("\\left", "").replace("\\right", "")
    for spacing in ("\\,", "\\;", "\\:", "\\quad", "\\qquad"):
        plain = plain.replace(spacing, " ")
    plain = plain.replace("\\!", "")
    for latex, unicode_value in MATH_GREEK.items():
        plain = re.sub(re.escape(latex) + r"(?![A-Za-z])", unicode_value, plain)
    plain = re.sub(r"\^\{([0-9n+\-=()]+)\}", lambda m: m.group(1).translate(SUPERSCRIPT), plain)
    plain = re.sub(r"\^([0-9n])", lambda m: m.group(1).translate(SUPERSCRIPT), plain)
    plain = re.sub(r"_\{([0-9ijknm+\-=()]+)\}", lambda m: m.group(1).translate(SUBSCRIPTS), plain)
    plain = re.sub(r"_([0-9ijknm])", lambda m: m.group(1).translate(SUBSCRIPTS), plain)
    plain = re.sub(r"\\[a-zA-Z]+", "", plain)
    plain = plain.replace("{", "").replace("}", "").replace("$", "")
    return plain


def clean_latex_for_telegram(text: str) -> str:
    """Чистый текст без LaTeX-мусора для Telegram/карточек."""
    return normalize_whitespace(_latex_to_plain(text or ""))


def lead_sentence(text: str, max_len: int = 190) -> str:
    """Первый содержательный анонс: не короткий вопрос и не обрывок."""
    clean = clean_latex_for_telegram(text)
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", clean) if part.strip()]
    chosen: List[str] = []
    for sentence in sentences:
        if len(sentence) < 45 and sentence.endswith("?"):
            continue
        if len(sentence) < 30:
            continue
        chosen.append(sentence)
        if sum(len(item) for item in chosen) >= min(120, max_len // 2):
            break
    if not chosen:
        return smart_sentence_truncate(clean, 40, max_len)
    return smart_sentence_truncate(" ".join(chosen), 60, max_len)


def smart_sentence_truncate(text: str, min_chars: int = 420, max_chars: int = 760) -> str:
    """Обрезка строго по границе предложения, без обрыва слова."""
    clean = clean_latex_for_telegram(text)
    if len(clean) <= max_chars:
        return clean
    chunk = clean[:max_chars]
    cut = max(chunk.rfind(". "), chunk.rfind("! "), chunk.rfind("? "), chunk.rfind(".\n"))
    if cut >= min_chars // 2:
        return chunk[: cut + 1].strip()
    cut = chunk.rfind(" ")
    if cut > 0:
        return chunk[:cut].rstrip(" ,;:") + "…"
    return chunk[: max_chars - 1].rstrip() + "…"


_CODE_MARKERS = (
    "def ", "class ", "import ", "from ", "return ", "self", "(self",
    "==", "!=", "->", "print(", "print ", ";\n", "__",
)

_PROSE_RE = re.compile(
    r"\b(the|and|of|that|is|are|for|with|this|was|were|как|что|это|для|или)\b",
    re.IGNORECASE,
)


def formula_kind(value: str) -> str:
    """Классификация поля «формула»: `math` | `code` | `text` | `empty`.

    Нужна, чтобы код и прозу не прогонять через LaTeX→Unicode (это их калечит)
    и не рендерить как математику в mathtext.
    """
    raw = (value or "").strip()
    if not raw:
        return "empty"
    if "\\" in raw or "$" in raw:
        return "math"
    if len(raw.split()) >= 6 and _PROSE_RE.search(raw):
        return "text"
    if any(marker in raw for marker in _CODE_MARKERS):
        return "code"
    if "'" in raw or '"' in raw or raw.endswith(":"):
        return "code"
    if re.search(r"[\^_]", raw):
        return "math"
    if re.search(r"[A-Za-z0-9)\]]\s*=\s*[A-Za-z0-9(\[\\]", raw):
        return "math"
    return "text"


def looks_like_math(value: str) -> bool:
    return formula_kind(value) == "math"


def formula_to_unicode(formula: str, max_len: int = 160) -> str:
    raw = (formula or "").strip()
    if formula_kind(raw) != "math":
        # Код и прозу не трогаем: Unicode-подстановки их калечат
        # (`def __init__` → `def _ᵢnit__`, `^*` → `^·`).
        return truncate(normalize_whitespace(raw), max_len)
    text = _latex_to_plain(raw)
    text = text.replace("**", "^")
    # `*` → `·` только как знак умножения между операндами (не `^*` в регулярках)
    text = re.sub(r"(?<=[\w)\]])[*](?=[\w(\[])", "·", text)
    return truncate(normalize_whitespace(text), max_len)


def escape_html(value: str) -> str:
    return html.escape(value or "", quote=True)


def keywords(text: str, limit: int = 8) -> List[str]:
    counts: dict[str, int] = {}
    for token in _tokens(text):
        counts[token] = counts.get(token, 0) + 1
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [word for word, _ in ordered[:limit]]


def ensure_sentence(text: str, max_len: int = 480) -> str:
    text = normalize_whitespace(text)
    if len(text) <= max_len:
        return text
    cut = text[:max_len]
    for sep in (". ", "! ", "? ", "; "):
        idx = cut.rfind(sep)
        if idx > max_len * 0.5:
            return cut[: idx + 1].strip()
    return truncate(text, max_len)


def unique_preserve(items: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    result: List[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result

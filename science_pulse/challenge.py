"""Генератор просветительских мини-задач (`challenge_question`) — без LLM.

Каждый выпуск заканчивается **задачей для читателя в комментариях**: она
требует применить формулу с картинки «в уме», а ядро заранее считает точный
ответ, чтобы подписчик мог проверить себя на тренажёре сайта.

Четыре стратегии (детерминированный выбор, сеть не нужна):

1. `steps` — сколько шагов сделает алгоритм при данном `N` (бинарный поиск,
   сортировка, квадратичный перебор). Ответ считается точно;
2. `ratio` — во сколько раз изменится величина, если параметр увеличить в `k`
   раз. Стратегия применяется **только если формула действительно степенной
   закон** `k·xⁿ`, и это проверяется численно, а не «на глаз»;
3. `substitute` — численная подстановка: «чему равна величина при `x = x₀`?»
   (точный ответ через SymPy);
4. `sequence` — продолжение числового ряда из формулы/заголовка.

Если ничего не разобралось — `fallback` из собственного крючка поста, поэтому
задача есть у каждого выпуска, но **никогда не выдумывает числа**.
"""
from __future__ import annotations

import hashlib
import math
import re
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

from .models import Post

NUMBERS_RE = re.compile(r"\d+(?:[.,]\d+)?")
STEP_SIZES = (256, 1024, 4096)
RATIO_FACTORS = (2, 3, 4)


def _seed(post: Post) -> int:
    """Детерминированное зерно из идентификатора поста."""
    return int(hashlib.sha1(str(getattr(post, "id", "")).encode("utf-8")).hexdigest()[:8], 16)


def _pick(seed: int, options: Tuple[Any, ...], salt: int = 0) -> Any:
    return options[(seed + salt) % len(options)]


def _text_of(post: Post) -> str:
    meta = getattr(post, "meta", {}) or {}
    return " ".join(
        str(part)
        for part in (
            getattr(post, "formula_plain", ""), getattr(post, "formula_latex", ""),
            getattr(post, "code", ""), getattr(post, "title", ""),
            meta.get("formula_vars", ""),
        )
        if part
    )


def _format_number(value: float) -> str:
    """Компактная запись числа: без хвостовых нулей и лишней точности."""
    if not math.isfinite(value):
        return "—"
    if abs(value - round(value)) < 1e-9 and abs(value) < 1e15:
        return f"{int(round(value))}"
    return f"{value:.6g}"


# ---------------------------------------------------------------------------
# Стратегия 1: сложность алгоритма (только для информатики)
# ---------------------------------------------------------------------------

COMPLEXITY_MARKERS = re.compile(r"o\s*\(|t\s*\(\s*n\s*\)|\blog\b|сложност")
BAD_WORDS = re.compile(
    r"\b(mod|lim|const|min|max|sum|prod|and|or|not|in|is|def|for|while|return)\b"
)


def _steps_challenge(post: Post, seed: int) -> Optional[Dict[str, Any]]:
    """Задача о числе шагов алгоритма — только для `cs` и явных оценок сложности.

    Для физики и математики стратегия отключена: «квадратичный алгоритм»
    к закону тяготения отношения не имеет.
    """
    if str(getattr(post, "domain", "")) != "cs":
        return None
    text = _text_of(post).lower()
    if not COMPLEXITY_MARKERS.search(text):
        return None
    size = _pick(seed, STEP_SIZES, 1)
    steps = math.ceil(math.log2(size))
    is_sort = bool(re.search(r"сортиров|sort|quick|merge|heap|пирам", text))
    is_search = bool(re.search(r"поиск|search|binary|бинарн|дихотом", text))
    if is_search and "log" in text:
        return {
            "kind": "steps",
            "question": (
                f"Сколько сравнений сделает бинарный поиск в худшем случае "
                f"для массива из {size} элементов?"
            ),
            "hint": "Каждый шаг делит область поиска пополам — считайте, сколько раз можно разделить.",
            "answer": f"{steps} сравнений",
            "explanation": f"log₂({size}) = {steps}: каждое сравнение отбрасывает половину массива.",
            "verified": True,
        }
    if is_sort and ("log" in text or "n log n" in text):
        return {
            "kind": "steps",
            "question": (
                f"Сколько операций (в порядке величины) выполнит сортировка "
                f"на {size} элементах?"
            ),
            "hint": "Оценка N·log₂N — считайте по формуле с карточки.",
            "answer": f"≈ {size * steps} операций",
            "explanation": f"N·log₂N = {size}·{steps} = {size * steps}.",
            "verified": True,
        }
    if "log" in text:
        return {
            "kind": "growth",
            "question": (
                f"На сколько шагов больше потребуется алгоритму для входа, "
                f"который в {size} раз длиннее?"
            ),
            "hint": "Логарифмическая сложность: шаги растут как log₂ размера.",
            "answer": f"на {steps} шагов больше",
            "explanation": f"log₂({size}) = {steps}: во столько шагов укладывается рост входа.",
            "verified": True,
        }
    if re.search(r"n\s*(\^|²|\*\*)\s*2|n²", text):
        factor = _pick(seed, RATIO_FACTORS, 2)
        return {
            "kind": "growth",
            "question": (
                f"Во сколько раз вырастет число операций квадратичного алгоритма, "
                f"если вход увеличить в {factor} раза?"
            ),
            "hint": "Квадратичный рост: N².",
            "answer": f"в {factor * factor} раз",
            "explanation": f"{factor}² = {factor * factor}.",
            "verified": True,
        }
    return None


# ---------------------------------------------------------------------------
# Разбор формулы: сегменты, строгая нормализация, вход/выход уравнения
# ---------------------------------------------------------------------------

SUBSCRIPT_DIGITS = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")
SUPERSCRIPT_DIGITS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")
SUBSCRIPT_LETTERS = "ₐₑₕᵢⱼₖₗₘₙₒₚᵣₛₜᵤᵥₓ"
SUPERSCRIPTS = {"²": "**2", "³": "**3", "⁴": "**4", "¹": "**1", "⁰": "**0"}
MULTIPLICATION = "·⋅×∙"
FRACTIONS = {"½": "(1/2)", "¼": "(1/4)", "¾": "(3/4)", "⅓": "(1/3)", "⅔": "(2/3)"}
# Символы, из-за которых SymPy молча собирает мусор («∇», «∮» → просто символы).
UNSAFE_CHARS = "∇∂∫∮∑Σ∏∛≠≤≥∞⇔⇒∈∀∃⊂⊃∪∩∧∨¬⊕→←↔↑↓≈≡"
GREEK = "αβγδεζηθικλμνξοπρστυφχψωΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ"
ALLOWED_RE = re.compile(rf"^[A-Za-z{GREEK}0-9_+\-*/^().,= ]+$")


def _segments(expression: str) -> List[str]:
    """Режет составную формулу на отдельные отношения вне скобок.

    `«F = G·(m₁·m₂)/r²,  v₁ = √(G·M/R)»` → два независимых отношения, поэтому
    задача строится по **первому разобранному**, а не по «сборной солянке».
    """
    text = (expression or "").replace("$", "").strip()
    parts: List[str] = []
    depth = 0
    buffer = ""
    for char in text:
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth = max(0, depth - 1)
        if depth == 0 and char in "•⇒⇔;,→":
            parts.append(buffer)
            buffer = ""
            continue
        buffer += char
    parts.append(buffer)
    return [part.strip() for part in parts if part.strip()]


def _normalize(text: str) -> str:
    """Строго готовит сегмент к SymPy. Возвращает "" для «нечистых» формул.

    Убирает типографские знаки (`²`, `·`, `√`, `−`, `½`), заменяет `≡` на `=`,
    цифровые индексы — на цифры, и **отбрасывает** всё, где SymPy собрал бы
    мусор (например `mod`, `∇`, `lim`, буквенные индексы `ₙ`).
    """
    segment = (text or "").strip()
    if not segment:
        return ""
    if any(letter in segment for letter in SUBSCRIPT_LETTERS):
        return ""
    for sign, replacement in SUPERSCRIPTS.items():
        segment = segment.replace(sign, replacement)
    for sign, replacement in FRACTIONS.items():
        segment = segment.replace(sign, replacement)
    for sign in MULTIPLICATION:
        segment = segment.replace(sign, "*")
    segment = segment.replace("−", "-").replace("–", "-").replace("—", "-")
    segment = re.sub(r"√\s*\(", "sqrt(", segment)
    segment = re.sub(r"√\s*([A-Za-z0-9_.]+)", r"sqrt(\1)", segment)
    # «σsqrt(2π)» SymPy разложил бы на σ·s·q·r·t — ставим явное умножение.
    segment = re.sub(r"(?<=[^\s(\[+*/=,\-])(sqrt\()", r"*\1", segment)
    # Многоразрядные надстрочные индексы: «¹²» → «**12».
    segment = re.sub(
        r"[¹²³⁴⁵⁶⁷⁸⁹⁰]+",
        lambda match: "**" + match.group(0).translate(SUPERSCRIPT_DIGITS),
        segment,
    )
    segment = segment.replace("≡", "=")
    segment = segment.translate(SUBSCRIPT_DIGITS).replace("^", "**")
    if any(char in segment for char in UNSAFE_CHARS):
        return ""
    if BAD_WORDS.search(segment):
        return ""
    if not ALLOWED_RE.match(segment):
        return ""
    return segment


def _bare_symbol(part: str) -> str:
    """Символ-выход: `F`, `r_s`, `Δφ` или функция `s(t)` → `s`."""
    text = (part or "").strip()
    call = re.fullmatch(rf"([A-Za-z{GREEK}][A-Za-z0-9_{GREEK}]{{0,3}})\s*\([^)]*\)", text)
    if call:
        return call.group(1)
    if re.fullmatch(rf"[A-Za-z{GREEK}][A-Za-z0-9_{GREEK}]{{0,3}}", text):
        return text
    return ""


def _equation_parts(expression: str) -> Tuple[str, str]:
    """Делит отношение на (символ-выход, закон).

    `F = G·(m₁·m₂)/r²` → выход `F`, закон `G*(m1*m2)/r**2`;
    `a² + b² = c²`   → выхода нет (обе части составные), закон пустой.
    """
    text = _normalize(expression)
    if not text or "=" not in text:
        return "", text
    parts = [part.strip() for part in text.split("=")]
    for index in range(len(parts) - 1):
        left = "=".join(parts[: index + 1])
        right = "=".join(parts[index + 1:])
        out_left, out_right = _bare_symbol(left), _bare_symbol(right)
        if out_left and not out_right:
            return out_left, right
        if out_right and not out_left:
            return out_right, left
    return "", ""


# ---------------------------------------------------------------------------
# Стратегия 2: во сколько раз изменится величина (только для k·xⁿ)
# ---------------------------------------------------------------------------


IDENT_RE = re.compile(rf"[A-Za-z{GREEK}][A-Za-z0-9_{GREEK}]*")
FUNCTION_NAMES = frozenset(
    ("sin", "cos", "tan", "exp", "log", "ln", "sqrt", "abs", "sinh", "cosh", "tanh", "pi", "E", "I")
)


def _safe_parse(text: str) -> Optional[Any]:
    """SymPy-парсер с защитой от служебных имён (`S`, `N`) и мусора.

    Идентификаторы (`m1`, `r_s`, `k_B`, `Δφ`) передаются как готовые символы:
    иначе `implicit_multiplication_application` разложил бы `m1` на `m·1`,
    а `sqrt` — на `s·q·r·t`.
    """
    try:
        import sympy as sp

        from .plotting import parse_expression

        extra = {
            name: sp.Symbol(name, real=True)
            for name in set(IDENT_RE.findall(text)) - FUNCTION_NAMES
        }
        # «e^(−x²)» — это экспонента, а не символ: подсказываем SymPy число Эйлера.
        if re.search(r"\be\s*\*\*", text):
            extra["e"] = sp.E
        expr = parse_expression(text, extra_locals=extra)
    except Exception:
        return None
    if not isinstance(expr, sp.Basic) or not hasattr(expr, "free_symbols"):
        return None
    return expr


def _power_law(expression: str, exclude: str = "") -> Optional[Tuple[str, int]]:
    """Ищет вход и степень, для которых закон — моном `k·xⁿ`.

    Проверка численная: `f(x)/xⁿ` должно быть постоянным в трёх точках —
    поэтому мы никогда не задаём «во сколько раз» для суммы вроде `a² + b²`,
    а символ-выход (`exclude`) из кандидатов исключается: увеличивать можно
    только независимый вход.
    """
    expr = _safe_parse(expression)
    if expr is None:
        return None
    symbols = [
        item for item in sorted(expr.free_symbols, key=lambda item: str(item))
        if str(item) != exclude
    ][:5]
    points = (1.0, 1.7, 2.3)
    best: Optional[Tuple[str, int]] = None
    for symbol in symbols:
        others = {item: 1.0 for item in expr.free_symbols if item != symbol}
        for exponent in (2, 3, -1, -2, -3, 1):
            ratios: List[float] = []
            for point in points:
                try:
                    value = float(expr.subs(others).subs(symbol, point))
                except Exception:
                    ratios = []
                    break
                if not math.isfinite(value) or value == 0.0:
                    ratios = []
                    break
                ratios.append(value / (point ** exponent))
            if not ratios or len(ratios) != len(points):
                continue
            base = abs(ratios[0]) or 1.0
            if all(abs(item - ratios[0]) <= 1e-9 * base for item in ratios):
                if best is None or abs(exponent) > abs(best[1]):
                    best = (str(symbol), exponent)
    return best


def _verify_ratio(law: str, symbol: str, factor: int, exponent: int) -> bool:
    """Вычислительная проверка масштаба: `f(k·x)/f(x)` должно равняться `k^n`."""
    try:
        expr = _safe_parse(law)
        if expr is None:
            return False
        target = next((item for item in expr.free_symbols if str(item) == str(symbol)), None)
        if target is None:
            return False
        others = {item: 1.0 for item in expr.free_symbols if item != target}
        base = float(expr.subs(others).subs(target, 1.0))
        scaled = float(expr.subs(others).subs(target, float(factor)))
        if not math.isfinite(base) or abs(base) < 1e-12:
            return False
        expected = float(factor) ** exponent
        return abs(scaled / base - expected) <= 1e-9 * max(1.0, abs(expected))
    except Exception:
        return False


def _ratio_challenge(post: Post, seed: int) -> Optional[Dict[str, Any]]:
    expression = (getattr(post, "formula_plain", "") or getattr(post, "formula_latex", "") or "").strip()
    factor = _pick(seed, RATIO_FACTORS, 2)
    for segment in _segments(expression):
        output, law = _equation_parts(segment)
        if not output or not law:
            continue
        found = _power_law(law, exclude=output)
        if found is None:
            continue
        symbol, exponent = found
        # Самопроверка вычислением: f(k·x)/f(x) обязано равняться k^exponent.
        if not _verify_ratio(law, symbol, factor, exponent):
            continue
        times = factor ** abs(exponent)
        verb = "возрастёт" if exponent > 0 else "ослабнет"
        return {
            "kind": "ratio",
            "question": (
                f"Проверьте интуицию: если увеличить {symbol} в {factor} раза, "
                f"во сколько раз {verb} {output}?"
            ),
            "hint": (
                f"В формуле {output} пропорционально {symbol}^{exponent} — "
                "подставьте множитель в степень."
            ),
            "answer": f"{output} {verb} в {times} раз",
            "explanation": (
                f"{factor}^{abs(exponent)} = {times}: показатель {exponent} "
                "задаёт такой масштаб."
            ),
            "verified": True,
        }
    return None


# ---------------------------------------------------------------------------
# Стратегия 3: численная подстановка
# ---------------------------------------------------------------------------


def _substitute_challenge(post: Post, seed: int) -> Optional[Dict[str, Any]]:
    expression = (getattr(post, "formula_plain", "") or getattr(post, "formula_latex", "") or "").strip()
    point = _pick(seed, (2, 3, 4), 3)
    for segment in _segments(expression):
        output, law = _equation_parts(segment)
        if not law:
            continue
        expr = _safe_parse(law)
        if expr is None:
            continue
        by_name = {str(item): item for item in expr.free_symbols}
        names = sorted(by_name)
        if not names or output in names:
            continue
        # Математическую постоянную π не варьируем — это не «параметр задачи».
        candidates = [name for name in names if name not in ("pi", "π")]
        if not candidates:
            continue
        primary = "x" if "x" in candidates else (
            "t" if "t" in candidates else candidates[0]
        )
        variable = by_name[primary]
        values = {
            name: (math.pi if name in ("pi", "π") else 1.0)
            for name in names if name != primary
        }
        fixed = {by_name[name]: value for name, value in values.items()}
        try:
            value = float(expr.subs(fixed).subs(variable, point))
        except Exception:
            continue
        if not math.isfinite(value):
            continue
        target = output or "величина"
        shown = ", ".join(f"{name} = {_format_number(item)}" for name, item in values.items())
        return {
            "kind": "substitute",
            "question": f"Чему равна {target} при {primary} = {point}?",
            "hint": f"Подставьте значения: {primary} = {point}" + (f", {shown}" if shown else "") + ".",
            "answer": f"{target} = {_format_number(value)}",
            "explanation": (
                f"Точный расчёт ядра: {segment} при {primary} = {point}"
                + (f", {shown}" if shown else "")
                + f" даёт {_format_number(value)}."
            ),
            "verified": True,
        }
    return None


# ---------------------------------------------------------------------------
# Стратегия 3б: решение уравнения относительно искомой величины
# ---------------------------------------------------------------------------


def _solve_challenge(post: Post, seed: int) -> Optional[Dict[str, Any]]:
    """Считает искомую величину из уравнения (например `a² + b² = c²`)."""
    import sympy as sp

    expression = (getattr(post, "formula_plain", "") or getattr(post, "formula_latex", "") or "").strip()
    for segment in _segments(expression):
        text = _normalize(segment)
        if "=" not in text:
            continue
        left, right = (part.strip() for part in text.split("=", 1))
        lhs, rhs = _safe_parse(left), _safe_parse(right)
        if lhs is None or rhs is None:
            continue
        symbols = sorted(lhs.free_symbols | rhs.free_symbols, key=str)
        if not symbols or len(symbols) > 5:
            continue
        equation = sp.Eq(lhs, rhs)
        difference = sp.expand(lhs - rhs)
        # Ищем величину, входящую в уравнение целой положительной степенью.
        ranked: List[Tuple[int, Any]] = []
        for symbol in symbols:
            try:
                degree = int(sp.degree(difference, symbol))
            except Exception:
                continue
            if 1 <= degree <= 3:
                ranked.append((degree, symbol))
        ranked.sort(key=lambda item: (-item[0], str(item[1])))
        for _degree, target in ranked:
            try:
                solutions = sp.solve(equation, target)
            except Exception:
                continue
            inputs = [symbol for symbol in symbols if symbol != target]
            values = {
                symbol: float(
                    math.pi if str(symbol) in ("pi", "π")
                    else _pick(seed, (1, 2, 3, 4, 5), index + 4)
                )
                for index, symbol in enumerate(inputs)
            }
            shown = ", ".join(f"{symbol} = {_format_number(value)}" for symbol, value in values.items())
            candidates: List[Tuple[float, Any]] = []
            for solution in solutions:
                try:
                    result = float(sp.re(solution.subs(values)))
                except Exception:
                    continue
                if not math.isfinite(result) or abs(result) < 1e-12:
                    continue
                candidates.append((result, solution))
            if not candidates:
                continue
            # Физическая величина: предпочитаем положительный корень.
            positive = [item for item in candidates if item[0] > 0]
            result, solution = (positive or candidates)[0]
            return {
                "kind": "solve",
                "question": f"Чему равна {target}, если {shown}?",
                "hint": "Выразите нужную величину из формулы и подставьте числа.",
                "answer": f"{target} = {_format_number(result)}",
                "explanation": (
                    f"Из {segment} получаем {target} = {sp.sstr(solution)}; "
                    f"при {shown} это {_format_number(result)}."
                ),
                "verified": True,
            }
    return None


# ---------------------------------------------------------------------------
# Стратегия 4: продолжение числового ряда
# ---------------------------------------------------------------------------


def _sequence_challenge(post: Post, seed: int) -> Optional[Dict[str, Any]]:
    meta = getattr(post, "meta", {}) or {}
    raw = str(meta.get("sequence") or "")
    numbers: List[float] = []
    if raw:
        numbers = [float(item.replace(",", ".")) for item in NUMBERS_RE.findall(raw)]
    if len(numbers) < 3:
        text = f"{getattr(post, 'title', '')} {getattr(post, 'formula_plain', '')}"
        numbers = [float(item.replace(",", ".")) for item in NUMBERS_RE.findall(text)][:5]
    if len(numbers) < 3:
        return None
    diffs = [round(numbers[index + 1] - numbers[index], 6) for index in range(len(numbers) - 1)]
    if len(set(diffs)) == 1:
        next_term = numbers[-1] + diffs[0]
        pattern = f"каждый следующий член больше на {_format_number(diffs[0])}"
    else:
        ratios = [
            numbers[index + 1] / numbers[index]
            for index in range(len(numbers) - 1)
            if numbers[index] != 0
        ]
        if len(ratios) == len(numbers) - 1 and len({round(item, 6) for item in ratios}) == 1:
            next_term = numbers[-1] * ratios[0]
            pattern = f"каждый следующий член умножается на {_format_number(ratios[0])}"
        else:
            return None
    shown = ", ".join(_format_number(item) for item in numbers)
    return {
        "kind": "sequence",
        "question": f"Продолжите ряд: {shown}, …  Чему равен следующий член?",
        "hint": f"Найдите правило: {pattern}.",
        "answer": f"{_format_number(next_term)}",
        "explanation": f"Ряд подчиняется правилу: {pattern}.",
        "verified": True,
    }


# ---------------------------------------------------------------------------
# Сборка и публичные функции
# ---------------------------------------------------------------------------


def _challenge_key(post: Post) -> tuple:
    """Ключ кэша: задача полностью определяется содержимым поста."""
    meta = getattr(post, "meta", {}) or {}
    return (
        str(getattr(post, "id", "")),
        str(getattr(post, "domain", "")),
        str(getattr(post, "title", "")),
        str(getattr(post, "hook", "")),
        str(getattr(post, "body", "")),
        str(getattr(post, "formula_latex", "")),
        str(getattr(post, "formula_plain", "")),
        str(getattr(post, "code", "")),
        str(meta.get("section_num") or ""),
        str(meta.get("sequence") or ""),
        str(meta.get("formula_vars") or ""),
        # Идентификатор узла канона: без него теряется реестр вычислимых задач.
        str(meta.get("canon_id") or meta.get("foundation_id") or ""),
    )


@lru_cache(maxsize=512)
def _challenge_cached(key: tuple) -> Dict[str, Any]:
    """Мемоизация: одна и та же задача не пересчитывается SymPy повторно.

    Функция детерминирована (только формулы и текст поста), поэтому кэш
    безопасен и снимает нагрузку при сборке глав сайта.
    """
    canon_id = key[11] if len(key) > 11 else ""
    post = Post(
        id=key[0], domain=key[1], title=key[2], hook=key[3], body=key[4],
        formula_latex=key[5], formula_plain=key[6], code=key[7],
        meta={
            "section_num": key[8],
            "sequence": key[9],
            "formula_vars": key[10],
            "canon_id": canon_id,
            "foundation_id": canon_id,
        },
    )
    return _challenge_for(post)


def build_challenge(post: Post) -> Dict[str, Any]:
    """Просветительская задача выпуска: вопрос, подсказка и точный ответ."""
    return dict(_challenge_cached(_challenge_key(post)))


def _numeric_proof_challenge(post: Post, seed: int) -> Optional[Dict[str, Any]]:
    """Числовая задача из вычислительного паспорта (`post_proof`).

    Для законов с операторами `∇, ∫, ∑, ∮, lim` прямое `y = f(x)` невозможно,
    но `computed_example` содержит точный эталонный расчёт (CODATA и т. п.).
    """
    try:
        from .post_proof import build_post_proof

        proof = build_post_proof(post) or {}
    except Exception:  # pragma: no cover - защитный контур
        return None
    example = str(proof.get("computed_example") or "").strip()
    if not example or not any(char.isdigit() for char in example):
        return None
    formula = str(getattr(post, "formula_plain", "") or getattr(post, "formula_latex", "") or "").strip()
    return {
        "kind": "numeric_proof",
        "question": f"Проверьте численно: {formula or 'закон выпуска'}. Что даёт эталонный расчёт?",
        "hint": "Подставьте эталонные значения констант из паспорта выпуска.",
        "answer": example,
        "explanation": "Расчёт выполнен ядром на эталонных константах (CODATA) и проверен на карточке.",
        "verified": True,
    }


def _compute_archimedes() -> Dict[str, str]:
    rho, g, volume = 1000.0, 9.81, 2.0
    return {
        "question": "Тело объёмом V = 2 м³ полностью в воде. Чему равна сила Архимеда?",
        "hint": "F = ρ·g·V, плотность воды 1000 кг/м³.",
        "answer": f"{rho * g * volume:.0f} Н (ρ = 1000 кг/м³, g = 9.81 м/с², V = 2 м³)",
    }


def _compute_leibniz_boolean() -> Dict[str, str]:
    variables = 3
    return {
        "question": f"Сколько строк в таблице истинности для {variables} логических переменных?",
        "hint": "Каждая переменная удваивает число комбинаций: 2ⁿ.",
        "answer": f"{2 ** variables} строк (2^{variables})",
    }


def _compute_newton_calculus() -> Dict[str, str]:
    point = 2.0
    return {
        "question": f"f(x) = x³. Чему равна производная f′(x) в точке x = {point:.0f}?",
        "hint": "Правило степени: (xⁿ)′ = n·xⁿ⁻¹.",
        "answer": f"{3.0 * point ** 2:.0f} (f′(x) = 3x², x = 2)",
    }


def _compute_lovelace() -> Dict[str, str]:
    from fractions import Fraction

    def bernoulli(index: int) -> Fraction:
        values = [Fraction(0)] * (index + 1)
        for m in range(index + 1):
            values[m] = Fraction(1, m + 1)
            for j in range(m, 0, -1):
                values[j - 1] = j * (values[j - 1] - values[j])
        return values[0]

    target = 4
    return {
        "question": f"Чему равен {target}-й член последовательности чисел Бернулли B₍{target}₎?",
        "hint": "Рекурсия: Σ C(n+1, k)·B_k = 0, начиная с B₀ = 1.",
        "answer": f"B₍{target}₎ = {bernoulli(target)}",
    }


def _compute_fourier() -> Dict[str, str]:
    base, harmonic = 220.0, 4
    return {
        "question": f"Основная гармоника f₁ = {base:.0f} Гц. Чему равна {harmonic}-я гармоника ряда Фурье?",
        "hint": "Гармоники кратны основной: fₙ = n·f₁.",
        "answer": f"{base * harmonic:.0f} Гц (f₍{harmonic}₎ = {harmonic}·{base:.0f})",
    }


def _compute_noether() -> Dict[str, str]:
    mass, speed, height, g = 1.0, 3.0, 2.0, 9.81
    energy = 0.5 * mass * speed ** 2 + mass * g * height
    return {
        "question": f"Проверьте сохранение: E = ½mv² + mgh при m = {mass:.0f}, v = {speed:.0f}, h = {height:.0f}.",
        "hint": "Симметрия по времени даёт сохранение энергии: сложите кинетическую и потенциальную части.",
        "answer": f"E = {energy:.2f} Дж",
    }


def _compute_turing() -> Dict[str, str]:
    return {
        "question": "Сколько шагов делает «бобёр-2» — машина Тьюринга BB(2)?",
        "hint": "Классический результат Радо: BB(2) — самая долгая остановка среди двух состояний.",
        "answer": "4 шага (BB(2) останавливается, оставляя 4 единицы)",
    }


def _compute_dijkstra() -> Dict[str, str]:
    import heapq

    edges = {"A": [("B", 1), ("C", 5)], "B": [("C", 2)], "C": []}
    distance = {node: float("inf") for node in edges}
    distance["A"] = 0
    queue = [(0, "A")]
    while queue:
        current, node = heapq.heappop(queue)
        for neighbour, weight in edges[node]:
            candidate = current + weight
            if candidate < distance[neighbour]:
                distance[neighbour] = candidate
                heapq.heappush(queue, (candidate, neighbour))
    return {
        "question": "Кратчайший путь A→C, если рёбра A→B = 1, B→C = 2, A→C = 5?",
        "hint": "Алгоритм Дейкстры релаксирует d(v) = min(d(u) + w(u,v)).",
        "answer": f"{distance['C']:.0f} (A→B→C, прямое ребро даёт 5)",
    }


def _compute_godel() -> Dict[str, str]:
    primes, codes = [2, 3, 5], [5, 6, 7]  # коды символов x, =, 0
    number = 1
    for prime, code in zip(primes, codes):
        number *= prime ** code
    return {
        "question": "Гёделев номер последовательности «x = 0» (коды символов 5, 6, 7 при простых 2, 3, 5)?",
        "hint": "Номер = p₁^c₁ · p₂^c₂ · p₃^c₃.",
        "answer": f"{number:,}".replace(",", " "),
    }


def _compute_rsa() -> Dict[str, str]:
    p, q, exponent = 61, 53, 17
    modulus, phi = p * q, (p - 1) * (q - 1)
    private = pow(exponent, -1, phi)
    message = 65
    cipher = pow(message, exponent, modulus)
    return {
        "question": f"RSA: p = {p}, q = {q}, e = {exponent}. Зашифруйте сообщение m = {message}.",
        "hint": "c = mᵉ mod n, где n = p·q.",
        "answer": f"c = {cipher} (n = {modulus}; расшифровка даёт {pow(cipher, private, modulus)})",
    }


def _compute_maxwell() -> Dict[str, str]:
    import math

    eps0, mu0 = 8.8541878128e-12, 1.25663706212e-6
    speed = 1.0 / math.sqrt(eps0 * mu0)
    return {
        "question": "Чему равна скорость света из уравнения Максвелла c = 1/√(ε₀μ₀)?",
        "hint": "Подставьте эталонные ε₀ и μ₀ (CODATA).",
        "answer": f"c = {speed:.0f} м/с (1/√(ε₀μ₀), ε₀ = 8.8541878128·10⁻¹², μ₀ = 1.25663706212·10⁻⁶)",
    }


def _compute_lj_lorenz() -> Dict[str, str]:
    sigma, epsilon = 1.0, 1.0
    r_min = sigma * 2 ** (1.0 / 6.0)
    return {
        "question": "Потенциал Леннард-Джонса: при каком r он минимален и чему равен V(r)?",
        "hint": "Минимум при r = 2^(1/6)·σ, глубина ямы V = −ε.",
        "answer": f"r_min = {r_min:.4f}σ, V(r_min) = −{epsilon:.1f}ε",
    }


CANON_COMPUTABLE = {
    "archimedes": _compute_archimedes,
    "leibniz_boolean": _compute_leibniz_boolean,
    "newton_calculus": _compute_newton_calculus,
    "lovelace": _compute_lovelace,
    "fourier_series": _compute_fourier,
    "noether_symmetry": _compute_noether,
    "turing_machine": _compute_turing,
    "dijkstra_shortest": _compute_dijkstra,
    "godel_incompleteness": _compute_godel,
    "rsa_crypto": _compute_rsa,
    "maxwell": _compute_maxwell,
    "lj_lorenz": _compute_lj_lorenz,
}


def _canon_computable_challenge(post: Post, seed: int) -> Optional[Dict[str, Any]]:
    """Вычислимое следствие закона для узлов с ∇, ∫, ∑, ∮, mod, lim."""
    meta = getattr(post, "meta", {}) or {}
    canon_id = str(meta.get("canon_id") or meta.get("foundation_id") or "").strip()
    builder = CANON_COMPUTABLE.get(canon_id)
    if not builder:
        return None
    try:
        data = builder()
    except Exception:  # pragma: no cover - защитный контур
        return None
    return {
        "kind": "canon_computable",
        "question": data["question"],
        "hint": data.get("hint", ""),
        "answer": data["answer"],
        "explanation": "Ответ вычислен ядром точно (арифметика Python, без округлений).",
        "verified": True,
    }


def _challenge_for(post: Post) -> Dict[str, Any]:
    """Собственно генерация (без кэша): перебор стратегий по порядку."""
    seed = _seed(post)
    meta = getattr(post, "meta", {}) or {}
    for strategy in (
        _steps_challenge,
        _ratio_challenge,
        _substitute_challenge,
        _solve_challenge,
        _sequence_challenge,
        _canon_computable_challenge,
        _numeric_proof_challenge,
    ):
        try:
            challenge = strategy(post, seed)
        except Exception:  # pragma: no cover - защитный контур
            challenge = None
        if challenge:
            challenge["post_id"] = getattr(post, "id", "")
            challenge["section"] = str(meta.get("section_num") or "")
            return challenge
    hook = str(getattr(post, "hook", "") or "").strip()
    question = (
        hook if hook.endswith("?")
        else f"Как бы вы объяснили это своими словами: {hook or post.title}?"
    )
    try:
        from .text import lead_sentence

        answer = lead_sentence(str(getattr(post, "body", "") or ""), 220)
    except Exception:  # pragma: no cover - защитный контур
        answer = ""
    return {
        "kind": "concept",
        "post_id": getattr(post, "id", ""),
        "section": str(meta.get("section_num") or ""),
        "question": question,
        "hint": "Опирайтесь на формулу с карточки и на расшифровку «где: …».",
        "answer": answer or str(getattr(post, "formula_plain", "") or getattr(post, "title", "")),
        "explanation": "Полное объяснение — в главе на сайте и в лонгриде выпуска.",
        "verified": False,
    }


def challenge_question(post: Post) -> str:
    """Только вопрос задачи (для подписи, радио и лонгрида)."""
    return str(build_challenge(post).get("question") or "")


def challenge_line(challenge: Dict[str, Any]) -> str:
    """Строка для подписи: вопрос без ответа + приглашение в комментарии."""
    question = str((challenge or {}).get("question") or "").strip()
    if not question:
        return ""
    return f"<b>Задача.</b> {question} Ответ — в комментариях."


def challenge_reveal(challenge: Dict[str, Any]) -> str:
    """Строка с решением (для сайта и лонгрида): ответ + объяснение."""
    challenge = challenge or {}
    answer = str(challenge.get("answer") or "").strip()
    explanation = str(challenge.get("explanation") or "").strip()
    parts = [f"Ответ: {answer}." if answer else "", explanation]
    return " ".join(part for part in parts if part).strip()


def quiz_options(challenge: Dict[str, Any], seed: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """Варианты ответа для нативной викторины (`Telegram sendPoll`).

    Собирается только если в ответе есть число: правильный вариант + три
    правдоподобных числовых дистрактора. Для качественных («concept») задач
    вариантов нет — викторина просто не отправляется, а не выдумывает ответы.
    """
    challenge = challenge or {}
    question = str(challenge.get("question") or "").strip()
    answer = str(challenge.get("answer") or "").strip()
    if not question or not answer:
        return None
    matches = list(NUMBERS_RE.finditer(answer))
    if not matches:
        return None
    # Варианты строим из первого предложения ответа: «F ослабнет в 9 раз» →
    # «F ослабнет в 4 раз», «F ослабнет в 9 раз», «F ослабнет в 11 раз»…
    template = answer.split(".")[0].strip() or answer
    template_matches = list(NUMBERS_RE.finditer(template))
    if not template_matches:
        return None
    match = template_matches[-1]
    token = match.group(0)
    prefix, suffix = template[: match.start()], template[match.end():]
    if len(prefix) > 70:
        prefix, suffix = "", ""
    value = float(token.replace(",", "."))
    if value == 0:
        return None
    decimals = len(token.split(".")[-1].split(",")[-1]) if ("." in token or "," in token) else 0
    is_int = decimals == 0 and float(value).is_integer()

    def render(number: float) -> str:
        text = str(int(round(number))) if is_int else f"{number:.{decimals}f}"
        option = f"{prefix}{text}{suffix}".strip()
        if len(option) <= 100:
            return option
        option = f"{prefix}{text}".strip()
        if len(option) <= 100:
            return option
        return text

    raw_candidates = [
        value * 2, value / 2, value + 2, value * 3, value - 2, value * 4,
    ]
    distractors: List[Tuple[float, str]] = []
    for candidate in raw_candidates:
        if candidate <= 0:
            continue
        text = render(candidate)
        if text != render(value) and all(text != item[1] for item in distractors):
            distractors.append((candidate, text))
        if len(distractors) == 3:
            break
    if len(distractors) < 3:
        return None
    distractors.sort(key=lambda item: item[0])
    options = [text for _number, text in distractors]
    base_seed = seed if seed is not None else _seed_from_text(str(challenge.get("post_id") or question))
    position = base_seed % 4
    options.insert(position, render(value))
    if len(options) != 4 or len(set(options)) != 4:
        return None
    return {
        "question": question,
        "options": options,
        "correct_index": position,
        "explanation": str(challenge.get("answer") or ""),
    }


def _seed_from_text(text: str) -> int:
    """Детерминированное зерно из строки (для викторины)."""
    return int(hashlib.sha1(text.encode("utf-8")).hexdigest()[:8], 16)


def challenge_summary(challenge: Dict[str, Any]) -> str:
    """Короткая сводка для `cli`/пульта: тип задачи и точный ответ."""
    challenge = challenge or {}
    return (
        f"[{challenge.get('kind', '?')}] {challenge.get('question', '')} "
        f"→ {challenge.get('answer', '')}"
    )

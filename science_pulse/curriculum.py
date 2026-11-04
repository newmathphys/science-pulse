"""Бесконечная лестница сложности: порядок выхода от фундамента к сложному.

Каждому посту присваивается `complexity_tier` (1..100):

* **1..10** — узлы фундаментального канона: tier = номер ступени, поэтому они
  ВСЕГДА выходят первыми, строго по порядку 1 → 2 → 3 …;
* **11..100** — всё остальное (Wikipedia, OEIS, Rosetta, StackExchange, бункер):
  tier считается по сложности формулы, кода и глубине понятий, чтобы и после
  канона канал шёл от простых понятий к сложным, а не вразнобой.

Порядок очереди: `foundation → tier → created_at` (стабильно и детерминированно).
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Tuple

# Признаки «глубоких» понятий: чем больше, тем выше tier.
DEEP_MARKERS: Tuple[str, ...] = (
    "тензор", "tensor", "многообразие", "manifold", "тополог", "тополог",
    "квантов", "quantum", "шрёдингер", "schrodinger", "гильберт", "hilbert",
    "функционал", "вариац", "лагранж", "гамильтон", "ковариант", "геодезич",
    "хромодинамик", "ренорм", "перенорм", "стохаст", "мартингал", "итō", "ито",
    "нейросет", "обратн", "градиентн", "байес", "энтроп", "фрактал", "хаос",
    "криптограф", "эллипт", "гипербол", "комплексн", "риман", "гёдель", "гедель",
    "неразрешим", "np-полн", "асимптот", "лемма", "теорема", "доказательств",
)

# Признаки «простого»: базовые операции и понятия.
SIMPLE_MARKERS: Tuple[str, ...] = (
    "сумма", "произведен", "площадь", "периметр", "число", "делен", "остаток",
    "простое", "чётн", "нечётн", "треугольник", "прямоугольник", "скорост",
    "сила", "масса", "равновеси", "двоичн", "алгоритм", "сортировк", "поиск",
)


def _formula_complexity(formula: str) -> int:
    """Сложность формулы: длина, вложенность, интегралы, тензоры."""
    text = formula or ""
    score = 0
    score += min(len(text) // 12, 12)
    for marker, weight in (
        (r"\\int|∫", 6), (r"\\sum|∑", 3), (r"\\prod", 3), (r"\\nabla|∇", 4),
        (r"\\partial|∂", 4), (r"\\frac|/", 2), (r"\^|²|³|\*\*", 1),
        (r"\\sqrt|√", 2), (r"\\infty|∞", 2), (r"\\hbar|ℏ", 3),
        (r"\\mathbb|\\mathcal|\\otimes|⊗", 5),
    ):
        score += weight * len(re.findall(marker, text))
    return score


def _text_complexity(text: str) -> int:
    """Сложность текста: глубина понятий минус простота формулировок."""
    low = (text or "").lower()
    score = 0
    for marker in DEEP_MARKERS:
        if marker in low:
            score += 3
    for marker in SIMPLE_MARKERS:
        if marker in low:
            score -= 1
    return score


def complexity_tier(post: Any) -> int:
    """Уровень сложности поста (1..100). Узлы канона получают 1..10 по ступени."""
    meta = getattr(post, "meta", {}) or {}
    step = meta.get("step")
    if step:
        try:
            return max(1, min(10, int(step)))
        except (TypeError, ValueError):
            pass
    base = 20
    formula = f"{getattr(post, 'formula_latex', '') or ''} {getattr(post, 'formula_plain', '') or ''}"
    body = f"{getattr(post, 'title', '')} {getattr(post, 'hook', '')} {getattr(post, 'body', '')}"
    score = _formula_complexity(formula) + _text_complexity(body)
    if getattr(post, "code", ""):
        score += min(len(post.code) // 60, 5)
    if getattr(post, "tier", "") in ("offline", "foundation"):
        score -= 2
    return max(11, min(100, base + score))


def is_foundation(post: Any) -> bool:
    """Узел фундаментального канона (выходит первым)."""
    meta = getattr(post, "meta", {}) or {}
    return bool(meta.get("step")) or getattr(post, "tier", "") == "foundation"


def sort_key(post: Any) -> Tuple[int, int, str]:
    """Ключ сортировки: фундамент → ступень/tier → время создания."""
    foundation_rank = 0 if is_foundation(post) else 1
    return (foundation_rank, complexity_tier(post), str(getattr(post, "created_at", "")))


def order_posts(posts: Iterable[Any]) -> List[Any]:
    """Стабильный порядок: фундамент по ступеням, затем остальное по сложности."""
    return sorted(posts, key=sort_key)


def annotate(post: Any) -> Any:
    """Записывает вычисленный tier в meta (для отчётов и /queue)."""
    meta = getattr(post, "meta", None)
    if isinstance(meta, dict):
        meta["complexity_tier"] = complexity_tier(post)
    return post


def format_curriculum(posts: Iterable[Any], limit: int = 10) -> List[Dict[str, Any]]:
    """Краткая сводка порядка выхода (для `cli status` / отчётов)."""
    rows: List[Dict[str, Any]] = []
    for index, post in enumerate(order_posts(posts)[:limit], start=1):
        meta = getattr(post, "meta", {}) or {}
        rows.append({
            "position": index,
            "id": getattr(post, "id", ""),
            "title": getattr(post, "title", ""),
            "domain": getattr(post, "domain", ""),
            "foundation": is_foundation(post),
            "step": meta.get("step"),
            "tier": complexity_tier(post),
        })
    return rows
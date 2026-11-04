"""Реестр фундаментальных физических констант (CODATA, СИ) для сайта и книги.

Значения берутся из `scipy.constants` — то же семейство, что и офлайн-бункер
(SciPy CODATA). Реестр используется для:

- страницы «Словарь констант» на сайте (`dist/constants.html`);
- предметного указателя в PDF-книге (`science_pulse/book.py`);
- связки «константа → посты» через `post.meta["constants_used"]`.
"""
from __future__ import annotations

import math
import re
from typing import Any, Dict, List

from scipy import constants as sc

# symbol: (название, обозначение LaTeX, значение, единица)
CONSTANTS: List[Dict[str, Any]] = [
    {"symbol": "c", "name": "Скорость света в вакууме", "tex": "c", "value": sc.c, "unit": "м/с"},
    {"symbol": "G", "name": "Гравитационная постоянная", "tex": "G", "value": sc.G, "unit": "м³/(кг·с²)"},
    {"symbol": "hbar", "name": "Постоянная Дирака", "tex": r"\hbar", "value": sc.hbar, "unit": "Дж·с"},
    {"symbol": "h", "name": "Постоянная Планка", "tex": "h", "value": sc.h, "unit": "Дж·с"},
    {"symbol": "e", "name": "Элементарный электрический заряд", "tex": "e", "value": sc.e, "unit": "Кл"},
    {"symbol": "k_B", "name": "Постоянная Больцмана", "tex": "k_B", "value": sc.k, "unit": "Дж/К"},
    {"symbol": "N_A", "name": "Постоянная Авогадро", "tex": "N_A", "value": sc.N_A, "unit": "1/моль"},
    {"symbol": "epsilon_0", "name": "Электрическая постоянная", "tex": r"\varepsilon_0", "value": sc.epsilon_0, "unit": "Ф/м"},
    {"symbol": "mu_0", "name": "Магнитная постоянная", "tex": r"\mu_0", "value": sc.mu_0, "unit": "Гн/м"},
    {"symbol": "alpha", "name": "Постоянная тонкой структуры", "tex": r"\alpha", "value": sc.alpha, "unit": "—"},
    {"symbol": "m_e", "name": "Масса электрона", "tex": "m_e", "value": sc.m_e, "unit": "кг"},
    {"symbol": "g", "name": "Ускорение свободного падения (стандартное)", "tex": "g", "value": sc.g, "unit": "м/с²"},
    {"symbol": "pi", "name": "Число π", "tex": r"\pi", "value": math.pi, "unit": "—"},
]

_BY_SYMBOL = {item["symbol"]: item for item in CONSTANTS}

# Токены в формулах, по которым константа считается «использованной» в посте.
_FORMULA_TOKENS = {
    "hbar": re.compile(r"\\hbar|\u210f|hbar"),
    "k_B": re.compile(r"k_B|k_{B}|k\\\\_B"),
    "N_A": re.compile(r"N_A|N_{A}"),
    "G": re.compile(r"\bG\b|\\,G"),
    "c": re.compile(r"\bc\^?2|\bc\\,|\\,c\b"),
    "epsilon_0": re.compile(r"\\varepsilon_0|ε₀|epsilon_0"),
    "mu_0": re.compile(r"\\mu_0|µ₀|mu_0"),
}


def format_value(value: float) -> str:
    """Точное значение в стиле CODATA: 12 значащих цифр, экспонента при необходимости."""
    text = f"{value:.12g}"
    return text.replace("e+", "·10^").replace("e-", "·10^−").replace("e", "·10^")


def constants_used_by(posts: Any) -> Dict[str, List[Any]]:
    """Связка «константа → посты»: явный `constants_used` + упоминания в формулах."""
    usage: Dict[str, List[Any]] = {symbol: [] for symbol in _BY_SYMBOL}
    for post in posts:
        meta = getattr(post, "meta", {}) or {}
        declared = {str(symbol) for symbol in (meta.get("constants_used") or [])}
        haystack = " ".join(
            [getattr(post, "formula_latex", "") or "", getattr(post, "formula_plain", "") or ""]
        )
        for symbol, pattern in _FORMULA_TOKENS.items():
            if symbol not in declared and pattern.search(haystack):
                declared.add(symbol)
        for symbol in declared:
            if symbol in usage and post not in usage[symbol]:
                usage[symbol].append(post)
    return {symbol: posts_using for symbol, posts_using in usage.items() if posts_using}
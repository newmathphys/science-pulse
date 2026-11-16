"""Единый визуальный язык SCM: цвет переменной, легенда, цветная формула.

Без LLM и без случайности: один и тот же символ получает один и тот же цвет
в формуле, на сайте, в карточке и в book_film.
"""
from __future__ import annotations

import html
import re
from typing import Any, Dict, List, Tuple

from .models import Post

PALETTE: Tuple[str, ...] = (
    "#1E3A8A",  # синий
    "#9F1239",  # терракота
    "#065F46",  # зелёный
    "#B45309",  # охра
    "#6D28D9",  # фиолетовый
    "#0E7490",  # бирюза
    "#7C2D12",  # коричневый
    "#374151",  # графит
)

SEMANTIC: Dict[str, str] = {
    "x": PALETTE[0], "y": PALETTE[2], "z": PALETTE[4],
    "t": PALETTE[1], "n": PALETTE[5], "k": PALETTE[3],
    "r": PALETTE[1], "R": PALETTE[1], "F": PALETTE[1],
    "E": PALETTE[3], "m": PALETTE[2], "G": PALETTE[6],
    "A": PALETTE[0], "B": PALETTE[2], "C": PALETTE[4],
    "p": PALETTE[5], "q": PALETTE[5], "h": PALETTE[6],
    "ℏ": PALETTE[6], "ρ": PALETTE[6], "φ": PALETTE[4],
}

_STOP = {
    "sin", "cos", "tan", "log", "ln", "exp", "lim", "max", "min", "mod",
    "det", "sup", "inf", "const", "frac", "sqrt", "sum", "prod", "int",
    "quad", "cdot", "times", "left", "right", "text", "mathbf", "mathrm",
    "begin", "end", "lambda", "mu", "nu", "pi", "theta", "alpha", "beta",
}


def _explicit_symbols(post: Post) -> List[str]:
    raw = (post.meta or {}).get("symbols")
    if isinstance(raw, dict):
        return [str(key) for key in raw if str(key).strip()]
    if isinstance(raw, (list, tuple)):
        return [str(item) for item in raw if str(item).strip()]
    if isinstance(raw, str):
        return [item.strip() for item in re.split(r"[,;·\s]+", raw) if item.strip()]
    return []


def symbols_for_post(post: Post, limit: int = 6) -> List[str]:
    explicit = _explicit_symbols(post)
    if explicit:
        return list(dict.fromkeys(explicit))[:limit]
    formula = f"{post.formula_plain or ''} {post.formula_latex or ''}"
    formula = re.sub(r"\\[a-zA-Z]+", " ", formula)
    tokens = re.findall(r"[A-Za-zА-Яа-яЁёℏρφ][A-Za-zА-Яа-яЁё0-9₀-₉]*", formula)
    result: List[str] = []
    for token in tokens:
        if token.lower() in _STOP or token in result:
            continue
        if len(token) == 1 or token in SEMANTIC:
            result.append(token)
        if len(result) >= limit:
            break
    return result


def symbol_colors(post: Post) -> Dict[str, str]:
    colors: Dict[str, str] = {}
    for index, symbol in enumerate(symbols_for_post(post)):
        colors[symbol] = SEMANTIC.get(symbol, PALETTE[index % len(PALETTE)])
    return colors


def colorized_formula_html(post: Post) -> str:
    formula = (post.formula_plain or post.formula_latex or "").strip()
    if not formula:
        return ""
    colors = symbol_colors(post)
    if not colors:
        return f'<span class="sym-formula">{html.escape(formula)}</span>'
    parts = re.split(r"([A-Za-zА-Яа-яЁёℏρφ][A-Za-zА-Яа-яЁё0-9₀-₉]*)", formula)
    out: List[str] = []
    for part in parts:
        color = colors.get(part)
        if color:
            out.append(
                f'<span class="sym" style="--sym-color:{color}" title="{html.escape(part)}">'
                f'{html.escape(part)}</span>'
            )
        else:
            out.append(html.escape(part))
    return "".join(out)


def legend_html(post: Post) -> str:
    colors = symbol_colors(post)
    if not colors:
        return ""
    chips = "".join(
        f'<span class="sym-chip" style="--sym-color:{color}"><b>{html.escape(symbol)}</b></span>'
        for symbol, color in colors.items()
    )
    return f'<div class="sym-legend" aria-label="Цвета переменных">{chips}</div>'


def card_chips(post: Post, limit: int = 5) -> List[Tuple[str, str]]:
    return list(symbol_colors(post).items())[:limit]


def css() -> str:
    return """
.sym-formula { font-family: var(--mono); font-size: 15px; line-height: 1.7; }
.sym { color: var(--sym-color); font-weight: 700; }
.sym-legend { display: flex; gap: 8px; flex-wrap: wrap; margin: 10px 0 0; }
.sym-chip { display: inline-flex; align-items: center; gap: 5px; border: 1px solid var(--rule); border-radius: 999px; padding: 2px 9px; font-family: var(--mono); font-size: 12px; color: var(--ink-2); background: var(--paper-2); }
.sym-chip::before { content: ""; width: 9px; height: 9px; border-radius: 50%; background: var(--sym-color); display: inline-block; }
.sym-chip b { color: var(--sym-color); font-weight: 700; }
.color-formula { background: var(--paper-3); border: 1px solid var(--rule); border-left: 4px solid var(--accent); border-radius: 4px; padding: 12px 16px; margin: 14px 0 0; overflow-x: auto; }
.pg-tabs { display: flex; gap: 6px; margin: 4px 0 12px; }
.pg-tab { background: var(--paper-2); border: 1px solid var(--rule); color: var(--ink-2); border-radius: 4px; padding: 6px 12px; cursor: pointer; font-family: var(--mono); font-size: 12px; }
.pg-tab.active { background: var(--ink); border-color: var(--ink); color: var(--paper); }
.pg-panel[hidden] { display: none; }
.pg-note { color: var(--ink-2); font-size: 14px; font-style: italic; }
.pg-logic { display: flex; gap: 18px; flex-wrap: wrap; align-items: center; font-family: var(--mono); font-size: 14px; }
.pg-logic label { display: inline-flex; gap: 6px; align-items: center; }
.pg-logic output { color: var(--cs); font-weight: 700; }
.pg-code span { display: block; padding: 0 6px; border-left: 3px solid transparent; }
.pg-code span.active { background: rgba(30, 58, 138, .10); border-left-color: var(--math); }
.pg-code label { display: block; margin-top: 10px; font-family: var(--mono); font-size: 13px; }
.pg-code input[type=range] { width: 220px; }
"""

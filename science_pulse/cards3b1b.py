from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .models import CardArtifact, Post
from .text import formula_kind, formula_to_unicode

LOGGER = logging.getLogger(__name__)

# Фирменная палитра 3Blue1Brown (Manim Community).
C_BG = "#090C12"
C_PANEL = "#111622"
C_GRID_MINOR = "#151E2E"
C_GRID_MAJOR = "#223047"
C_BLUE = "#58C4DD"    # функция / волна
C_YELLOW = "#FACC15"  # производная / вектор
C_GREEN = "#83C167"   # интеграл / оптимальный алгоритм
C_RED = "#FC6255"     # экстремум / деградация

DOMAIN_BADGES = {
    "math": ("МАТЕМАТИКА • АНАЛИЗ И ГЕОМЕТРИЯ", C_BLUE),
    "physics": ("ФИЗИКА • ФАЗОВОЕ ПРОСТРАНСТВО И ПОЛЯ", "#38BDF8"),
    "cs": ("ИНФОРМАТИКА • АЛГОРИТМЫ И СЛОЖНОСТЬ", C_YELLOW),
}


def _extract_sequence(post: Post) -> List[int]:
    """Достаёт числовую последовательность из текста поста (для сюжетного графика).

    Ищет не менее 6 подряд идущих чисел через запятую в hook/body/formula.
    """
    pattern = re.compile(r"-?\d+(?:\s*,\s*-?\d+){5,}")
    for text in (getattr(post, "hook", ""), getattr(post, "body", ""), getattr(post, "formula_plain", "")):
        match = pattern.search(text or "")
        if not match:
            continue
        try:
            values = [int(part.strip()) for part in match.group(0).split(",") if part.strip()]
        except ValueError:
            continue
        tail = (text or "")[match.end():match.end() + 1]
        if tail in ("?", "…") and len(values) > 6:
            values = values[:-1]
        if len(values) >= 6:
            return values[:26]
    return []


def typst_available() -> bool:
    import importlib.util

    return importlib.util.find_spec("typst") is not None


# ----------------------------------------------------------------------
# Сюжетные семейства графиков: выбор по СОДЕРЖАНИЮ поста (формула, смысл,
# visual_type), а не по дисциплине — иначе все физические карточки совпадают.
# ----------------------------------------------------------------------

_PLOT_RULES: Tuple[Tuple[str, str], ...] = (
    ("orbit", r"орбит|orbit|тягот|gravit|планет|kepler|кеплер|n-?body|н-?тел"),
    ("decay", r"распад|decay|полураспад|half-life|затухан|damping|охлажд|cooling"),
    ("pendulum", r"маятник|pendulum|колебан|oscill"),
    ("heat", r"тепл|heat|диффузи|diffusion|энтроп|entropy|броун"),
    ("prob", r"вероятн|probab|распределен|distribution|гаусс|gauss|нормальн|статистик"),
    ("wave", r"волн|wave|квант|quant|шрёдингер|schrodinger|интерфер|фотон|аттосекунд|спектр"),
    ("cells", r"конвей|conway|game of life|клеточн|automaton|автомат|игра «жизнь»"),
    ("sort", r"сортиров|sort|сложност|complexit|алгоритм|algorithm|big-o|o\(n|o\(log|хеш"),
    ("graph", r"\bграф(?:ов|ы|е|а|у|ам|ами)?\b|network|вершин|рёбр|ребер|маршрут"),
    ("growth", r"фибоначч|fibonacci|последовательн|sequence|oeis|прогресси|рекуррент"),
)


def _plot_family(post: Post) -> str:
    """Семейство графика по содержанию поста (формула → ключевые слова → visual_type)."""
    meta = getattr(post, "meta", {}) or {}
    haystack = " ".join([
        str(getattr(post, "title", "")),
        str(getattr(post, "hook", "")),
        str(getattr(post, "body", ""))[:400],
        str(getattr(post, "formula_plain", "")),
        str(getattr(post, "formula_latex", "")),
        str(meta.get("visual_type") or ""),
        str(meta.get("concept") or ""),
    ]).lower()
    for family, pattern in _PLOT_RULES:
        if re.search(pattern, haystack, re.IGNORECASE):
            return family
    return "formula"


def _seed_of(post: Post) -> int:
    return sum(ord(char) for char in (getattr(post, "id", "") or "3b1b"))


def _scaled(values, peak: float, span: float = 1.2):
    array = np.asarray(values, dtype=float)
    if not peak or not np.isfinite(peak):
        return array * 0.0
    return span * array / peak


def _draw_formula(ax, post: Post, xs):
    """График НАСТОЯЩЕЙ формулы поста: f(x), f′(x) и экстремум."""
    from .plotting import ExpressionError, evaluate_curve

    expression = (getattr(post, "formula_plain", "") or getattr(post, "formula_latex", "") or "").strip()
    if not expression:
        raise ExpressionError("нет формулы")
    curve = evaluate_curve(expression, x_min=-3.1, x_max=3.1, points=600)
    x = np.asarray(curve["x"], dtype=float)
    re_y = np.asarray(curve["re_y"], dtype=float)
    peak = float(np.nanmax(np.abs(re_y))) if re_y.size else 0.0
    if peak < 1e-6 or not np.isfinite(peak):
        raise ExpressionError("формула вырождена (константа)")
    ax.fill_between(x, _scaled(re_y, peak), 0, color=C_BLUE, alpha=0.15, zorder=3)
    ax.plot(x, _scaled(re_y, peak), color=C_BLUE, lw=3.0, zorder=5)
    legend = [(C_BLUE, f"f(x) = {curve['plain'][:34]}")]
    if curve.get("der_y") is not None:
        der = np.asarray(curve["der_y"], dtype=float)
        dpeak = float(np.nanmax(np.abs(der))) if der.size else 0.0
        if dpeak > 1e-9:
            ax.plot(x, _scaled(der, dpeak), color=C_YELLOW, lw=2.2, linestyle="--", zorder=4)
            legend.append((C_YELLOW, "f′(x) — скорость изменения"))
    if curve.get("has_imaginary"):
        im = np.asarray(curve["im_y"], dtype=float)
        ipeak = float(np.nanmax(np.abs(im))) if im.size else 0.0
        if ipeak > 1e-9:
            ax.plot(x, _scaled(im, ipeak), color=C_RED, lw=2.0, linestyle=":", zorder=4)
            legend.append((C_RED, "Im f(x)"))
    poi_x, poi_y = curve.get("poi") or (0.0, 0.0)
    ax.scatter([float(poi_x)], [_scaled([poi_y], peak)[0]], color=C_GREEN, edgecolor="#000", s=70, zorder=7)
    legend.append((C_GREEN, "Экстремум"))
    return legend


def _draw_orbit(ax, post: Post, xs):
    """Орбита Кеплера: траектория, фокус, тело, вектор скорости."""
    a, b = 2.4, 1.35
    theta = np.linspace(0, 2 * np.pi, 400)
    ax.plot(a * np.cos(theta), b * np.sin(theta), color=C_BLUE, lw=2.0, alpha=0.85, zorder=4)
    focus = float(np.sqrt(a**2 - b**2))
    ax.scatter([focus], [0], color=C_YELLOW, s=130, zorder=6)
    index = int(len(theta) * 0.18)
    body_x, body_y = float(a * np.cos(theta[index])), float(b * np.sin(theta[index]))
    ax.annotate("", xy=(focus, 0), xytext=(body_x, body_y),
                arrowprops=dict(arrowstyle="-", color="#64748B", lw=1.1, linestyle="--"), zorder=3)
    ax.scatter([body_x], [body_y], color=C_GREEN, s=95, edgecolor="#000", zorder=7)
    ax.annotate("", xy=(body_x - 0.85, body_y + 0.5), xytext=(body_x, body_y),
                arrowprops=dict(arrowstyle="->", color=C_RED, lw=2.4), zorder=6)
    return [(C_BLUE, "Траектория"), (C_YELLOW, "Фокус (центр масс)"),
            (C_GREEN, "Тело"), (C_RED, "Вектор скорости")]


def _draw_decay(ax, post: Post, xs):
    """Экспоненциальный распад с отметками полураспада."""
    tau = 0.6
    ys = np.exp(-np.clip(xs, 0.0, None) / tau)
    ax.fill_between(xs, ys, 0, color=C_BLUE, alpha=0.15, zorder=3)
    ax.plot(xs, ys, color=C_BLUE, lw=3.0, zorder=5)
    for k in (1, 2):
        xk = tau * float(np.log(2)) * k
        ax.plot([xk, xk], [0, 0.5 ** k], color=C_RED, linestyle=":", lw=1.6, zorder=4)
        ax.scatter([xk], [0.5 ** k], color=C_YELLOW, s=65, zorder=6)
    return [(C_BLUE, "N(t) = N₀·e^(−t/τ)"), (C_YELLOW, "Полураспад T½"), (C_RED, "Отметки T½")]


def _draw_pendulum(ax, post: Post, xs):
    """Маятник: затухающие угол θ(t) и скорость ω(t)."""
    t = np.linspace(0, 12.0, 700)
    decay = np.exp(-0.16 * t)
    ax.plot(t - 3.0, 1.35 * decay * np.cos(3.2 * t), color=C_BLUE, lw=2.6, zorder=5)
    ax.plot(t - 3.0, 1.35 * decay * np.sin(3.2 * t), color=C_YELLOW, lw=1.9, linestyle="--", zorder=4)
    return [(C_BLUE, "Угол θ(t)"), (C_YELLOW, "Скорость ω(t)"), (C_GREEN, "Затухание ∝ e^(−γt)")]


def _draw_heat(ax, post: Post, xs):
    """Диффузия: гауссианы, расплывающиеся со временем."""
    legend = []
    for index, (sigma, color) in enumerate(((0.35, C_RED), (0.7, C_YELLOW), (1.1, C_GREEN))):
        ys = 1.25 * np.exp(-(xs**2) / (2 * sigma**2))
        ax.plot(xs, ys, color=color, lw=2.4, alpha=0.92, zorder=5 - index)
        legend.append((color, f"t{index + 1} · σ={sigma}"))
    return legend


def _draw_prob(ax, post: Post, xs):
    """Нормальное распределение с полосами ±σ."""
    ys = 1.35 * np.exp(-(xs**2) / 2.0)
    ax.fill_between(xs, ys, 0, color=C_BLUE, alpha=0.15, zorder=3)
    ax.plot(xs, ys, color=C_BLUE, lw=3.0, zorder=5)
    for sigma, color in ((1.0, C_GREEN), (2.0, C_YELLOW)):
        mask = np.abs(xs) <= sigma
        ax.fill_between(xs[mask], ys[mask], 0, color=color, alpha=0.18, zorder=4)
    ax.axvline(0, color=C_RED, linestyle=":", lw=1.6, zorder=6)
    return [(C_BLUE, "Плотность вероятности"), (C_GREEN, "±1σ"), (C_YELLOW, "±2σ"), (C_RED, "Среднее μ")]


def _draw_wave(ax, post: Post, xs):
    """Волновой пакет (квантовая механика / поля)."""
    seed = _seed_of(post)
    grid_x, grid_y = np.meshgrid(np.linspace(-3.0, 3.0, 15), np.linspace(-1.3, 1.3, 8))
    ax.quiver(grid_x, grid_y, grid_y, -np.sin(grid_x) - 0.3 * grid_y,
              color="#334155", alpha=0.55, scale=22, width=0.003, zorder=2)
    freq = 2.4 + (seed % 3) * 0.5
    envelope = 1.25 * np.exp(-0.22 * xs**2)
    wave = envelope * np.cos(freq * xs)
    ax.plot(xs, envelope, color=C_RED, linestyle="--", lw=1.8, alpha=0.85, zorder=4)
    ax.plot(xs, -envelope, color=C_RED, linestyle="--", lw=1.8, alpha=0.85, zorder=4)
    ax.fill_between(xs, wave, 0, color=C_BLUE, alpha=0.18, zorder=3)
    ax.plot(xs, wave, color=C_BLUE, lw=3.0, zorder=5)
    return [(C_BLUE, "Волновая функция Ψ(x)"), (C_RED, "Огибающая ±|Ψ|"), (C_YELLOW, "Фазовый градиент ∇Ψ")]


def _draw_cells(ax, post: Post, xs):
    """Клеточный автомат: решётка живых клеток (Game of Life и подобные)."""
    rng = np.random.default_rng(_seed_of(post) % (2**32))
    cols, rows = 24, 9
    alive = rng.random((rows, cols)) < 0.4
    step_x, step_y = 6.0 / (cols - 1), 2.6 / (rows - 1)
    for col in range(cols):
        ax.axvline(-3.0 + col * step_x, color="#141d2e", lw=0.6, zorder=2)
    for row in range(rows):
        ax.axhline(-1.3 + row * step_y, color="#141d2e", lw=0.6, zorder=2)
    gx, gy = [], []
    for row in range(rows):
        for col in range(cols):
            if alive[row, col]:
                gx.append(-3.0 + col * step_x)
                gy.append(-1.3 + row * step_y)
    ax.scatter(gx, gy, marker="s", s=72, color=C_GREEN, zorder=5)
    return [(C_GREEN, "Живые клетки"), ("#334155", "Решётка")]


def _draw_sort(ax, post: Post, xs):
    """Сложность алгоритмов: O(log N) → O(N log N) → O(N²)."""
    n = np.linspace(1.0, 40.0, 240)
    log2_n, n_log_n, n_sq = np.log2(n), n * np.log2(n), n ** 2
    scale = float(np.log2(1.0 + n_sq[-1]))
    y_log = -1.35 + 2.7 * np.log2(1.0 + log2_n) / scale
    y_nlog = -1.35 + 2.7 * np.log2(1.0 + n_log_n) / scale
    y_nsq = -1.35 + 2.7 * np.log2(1.0 + n_sq) / scale
    x = -2.7 + (n - n[0]) / (n[-1] - n[0]) * 5.4
    ax.fill_between(x, y_nlog, 0.0, color=C_GREEN, alpha=0.18, zorder=3)
    ax.plot(x, y_nsq, color=C_RED, lw=2.6, linestyle="--", zorder=4)
    ax.plot(x, y_nlog, color=C_GREEN, lw=3.2, zorder=5)
    ax.plot(x, y_log, color=C_BLUE, lw=2.8, zorder=5)
    marks = [60, 120, 180, 230]
    ax.scatter(x[marks], y_nlog[marks], color=C_YELLOW, edgecolor="#000", s=70, zorder=6)
    return [(C_BLUE, "Бинарный поиск O(log N)"), (C_GREEN, "Оптимум O(N log N)"), (C_RED, "Перебор O(N²)")]


def _draw_graph(ax, post: Post, xs):
    """Небольшая сеть: узлы и связи (детерминированно по id поста)."""
    rng = np.random.default_rng(_seed_of(post) % (2**32))
    count = 7
    angles = np.linspace(0, 2 * np.pi, count, endpoint=False)
    radius = 0.85 + 0.35 * rng.random(count)
    px, py = 2.7 * np.cos(angles) * radius, 1.25 * np.sin(angles) * radius
    for index in range(count):
        other = (index + 1) % count
        ax.plot([px[index], px[other]], [py[index], py[other]], color="#334155", lw=1.4, zorder=3)
    ax.plot([px[0], px[count // 2]], [py[0], py[count // 2]], color="#334155", lw=1.2, zorder=3)
    ax.scatter(px, py, color=C_BLUE, s=95, zorder=6)
    ax.scatter([px[0]], [py[0]], color=C_GREEN, s=155, zorder=7)
    return [(C_BLUE, "Узлы"), (C_GREEN, "Корень"), ("#334155", "Связи")]


def _draw_growth(ax, post: Post, xs):
    """Рост последовательности a(n) с трендом (OEIS / рекуррентности)."""
    sequence = _extract_sequence(post)
    if not sequence:
        raise ValueError("нет последовательности")
    values = np.array(sequence, dtype=float)
    use_log = (values.max() - values.min()) > 40 and values.min() >= 0
    work = np.log10(values + 1.0) if use_log else values
    low, high = float(work.min()), float(work.max())
    span = max(high - low, 1e-9)
    norm = -1.15 + 2.3 * (work - low) / span
    index = np.arange(len(values))
    xpos = -2.8 + (index / max(len(values) - 1, 1)) * 5.6
    ax.vlines(xpos, -1.15, norm, color=C_BLUE, alpha=0.55, lw=1.6, zorder=4)
    ax.plot(xpos, norm, color=C_BLUE, lw=2.0, alpha=0.85, zorder=5)
    ax.scatter(xpos, norm, color=C_GREEN, s=42, zorder=6)
    if len(values) >= 3:
        slope, intercept = np.polyfit(index, work, 1)
        trend = slope * index + intercept
        ax.plot(xpos, -1.15 + 2.3 * (trend - low) / span, color=C_YELLOW, lw=2.4, linestyle="--", zorder=7)
    ax.set_yticks([])
    ax.text(-3.25, 1.42, f"a(n), n = 1…{len(values)}" + ("   (лог-шкала)" if use_log else ""),
            color="#64748B", fontsize=9.5, ha="left", va="top")
    return [(C_GREEN, "Члены a(n)"), (C_BLUE, "Профиль роста"), (C_YELLOW, "Тренд роста (лог-шкала)")]


def _draw_sine(ax, post: Post, xs):
    """Резерв: профиль f(x) с касательной и площадью."""
    freq = 1.4 + (_seed_of(post) % 4) * 0.25
    ys = 1.15 * np.sin(freq * xs + 0.4) * np.exp(-0.15 * xs**2)
    dys = np.gradient(ys, xs)
    rx = np.linspace(-2.2, 1.8, 22)
    ry = 1.15 * np.sin(freq * rx + 0.4) * np.exp(-0.15 * rx**2)
    ax.bar(rx, ry, width=(rx[1] - rx[0]) * 0.86, color=C_GREEN, alpha=0.25,
           edgecolor=C_GREEN, linewidth=0.9, zorder=3)
    ax.plot(xs, ys, color=C_BLUE, lw=3.2, zorder=5)
    index = 340
    tangent_x, tangent_y, slope = float(xs[index]), float(ys[index]), float(dys[index])
    delta = 0.75
    ax.annotate("", xy=(tangent_x + delta, tangent_y + slope * delta),
                xytext=(tangent_x - delta * 0.5, tangent_y - slope * delta * 0.5),
                arrowprops=dict(arrowstyle="->", color=C_YELLOW, lw=2.6), zorder=6)
    ax.plot([tangent_x, tangent_x], [0, tangent_y], color=C_RED, linestyle=":", lw=1.8, zorder=4)
    ax.scatter([tangent_x], [tangent_y], color=C_RED, edgecolor="#FFFFFF", s=80, lw=2.0, zorder=7)
    return [(C_BLUE, "Профиль f(x)"), (C_YELLOW, "Касательный вектор df/dx"), (C_GREEN, "Площадь ∫f(x)dx")]


_DRAWERS = {
    "formula": _draw_formula,
    "orbit": _draw_orbit,
    "decay": _draw_decay,
    "pendulum": _draw_pendulum,
    "heat": _draw_heat,
    "prob": _draw_prob,
    "wave": _draw_wave,
    "sort": _draw_sort,
    "graph": _draw_graph,
    "cells": _draw_cells,
    "growth": _draw_growth,
    "sine": _draw_sine,
}

_DOMAIN_FALLBACK = {"physics": "wave", "cs": "sort", "math": "growth"}


def render_3b1b_plot(post: Post, out_png: str | Path) -> Dict[str, Any]:
    """Чертёж в стиле 3Blue1Brown: NumberPlane, оси через центр, цветовые смыслы.

    Возвращает `{"plot_path", "legend": [(color, label), ...]}`.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    domain = getattr(post, "domain", "math")
    seed = sum(ord(char) for char in (getattr(post, "id", "") or "3b1b"))
    plt.rcParams["mathtext.fontset"] = "cm"

    fig, ax = plt.subplots(figsize=(9.2, 4.5), dpi=200, facecolor=C_BG)
    ax.set_facecolor(C_BG)
    ax.set_xlim(-3.4, 3.4)
    ax.set_ylim(-1.6, 1.6)

    for value in np.arange(-3.0, 3.5, 0.25):
        ax.axvline(value, color=C_GRID_MINOR, lw=0.6, zorder=1)
    for value in np.arange(-1.5, 1.6, 0.25):
        ax.axhline(value, color=C_GRID_MINOR, lw=0.6, zorder=1)
    for value in range(-3, 4):
        ax.axvline(value, color=C_GRID_MAJOR, lw=1.1, zorder=2)
    for value in (-1, 0, 1):
        ax.axhline(value, color=C_GRID_MAJOR, lw=1.1, zorder=2)

    ax.annotate("", xy=(3.35, 0), xytext=(-3.35, 0),
                arrowprops=dict(arrowstyle="->", color="#94A3B8", lw=1.8), zorder=3)
    ax.annotate("", xy=(0, 1.55), xytext=(0, -1.55),
                arrowprops=dict(arrowstyle="->", color="#94A3B8", lw=1.8), zorder=3)

    xs = np.linspace(-3.1, 3.1, 600)

    # График выбирается по СОДЕРЖАНИЮ поста (формула → смысл → visual_type),
    # а не по дисциплине: иначе все карточки одной дисциплины совпадают.
    legend: Optional[List[Tuple[str, str]]] = None
    for candidate in (_plot_family(post), "formula", _DOMAIN_FALLBACK.get(domain, "growth"), "sine"):
        drawer = _DRAWERS.get(candidate)
        if drawer is None:
            continue
        try:
            legend = drawer(ax, post, xs)
            break
        except Exception as exc:  # семейство не подошло — пробуем следующее
            LOGGER.debug("График %s не подошёл для %s: %s", candidate, getattr(post, "id", "?"), exc)
    if legend is None:
        legend = _draw_wave(ax, post, xs)

    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(colors="#64748B", labelsize=9)
    fig.tight_layout(pad=0.3)
    out_png = Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=200, facecolor=C_BG)
    plt.close(fig)
    return {"plot_path": str(out_png), "legend": legend}



def _esc_typst(value: Any) -> str:
    text = str(value or "")
    for char in ("\\", "#", "$", "*", "_", "`", "@", "<", ">", "[", "]"):
        text = text.replace(char, "\\" + char)
    return text


def _strip_inline_math(value: Any) -> str:
    import re

    return re.sub(r"\$(.+?)\$", r"\1", str(value or ""))


def _mathtext_normalize(expr: str) -> str:
    """Приводит LaTeX к подмножеству, которое понимает matplotlib mathtext."""
    import re

    text = expr.strip()
    if len(text) > 2 and text.startswith("$") and text.endswith("$"):
        text = text[1:-1]
    text = re.sub(r"\\text\{([^{}]*)\}", r"\\mathrm{\1}", text)
    text = re.sub(r"\\mathbb\s+([A-Za-z])", r"\\mathbb{\1}", text)
    text = re.sub(r"\\mathcal\s+([A-Za-z])", r"\\mathcal{\1}", text)
    # Логические связки: у mathtext другие имена команд.
    text = text.replace(r"\land", r"\wedge")
    text = text.replace(r"\lor", r"\vee")
    text = text.replace(r"\lnot", r"\neg")
    # Импликации и эквивалентности.
    for source, target in (
        (r"\implies", r"\Rightarrow"),
        (r"\impliedby", r"\Leftarrow"),
        (r"\iff", r"\Leftrightarrow"),
        (r"\Longleftrightarrow", r"\Leftrightarrow"),
        (r"\longrightarrow", r"\to"),
        (r"\bigcup", r"\cup"),
        (r"\bigcap", r"\cap"),
    ):
        text = text.replace(source, target)
    # Модульная арифметика: `\pmod{n}` → `(mod n)`, `\bmod` → `mod`.
    text = re.sub(r"\\pmod\s*\{([^{}]*)\}", r"\\ (\\mathrm{mod}\\ \1)", text)
    text = text.replace(r"\bmod", r"\ \mathrm{mod}\ ")
    text = re.sub(r"\\quad|\\qquad|\\,|\\;|\\:", r"\\ ", text)
    return text


def _typst_string(value: Any) -> str:
    """Строковый литерал Typst (экранирование совпадает с JSON)."""
    return json.dumps(str(value or ""), ensure_ascii=False)


def render_formula_image(post: Post, out_png: str | Path, color: str = C_BLUE) -> bool:
    """Рендерит формулу настоящим математическим движком (matplotlib mathtext).

    Возвращает True, если картинка создана (иначе — вызывающий код покажет текст).
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    raw = (getattr(post, "formula_latex", "") or getattr(post, "formula_plain", "") or "").strip()
    if formula_kind(raw) != "math":
        return False
    expr = f"${_mathtext_normalize(raw)}$"
    size = 30 if len(raw) <= 34 else (24 if len(raw) <= 52 else 19)
    try:
        plt.rcParams["mathtext.fontset"] = "stixsans"
        fig = plt.figure(figsize=(7.6, 1.5), dpi=300)
        fig.patch.set_alpha(0.0)
        fig.text(0.5, 0.5, expr, ha="center", va="center", color=color, fontsize=size)
        out_png = Path(out_png)
        out_png.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out_png, transparent=True, bbox_inches="tight", pad_inches=0.05)
        plt.close(fig)
        return True
    except Exception as exc:  # невалидный LaTeX → покажем Unicode-текст
        LOGGER.warning("Формула не отрендерилась (%s), fallback на Unicode", exc)
        return False


def _typst_source(post: Post, info: Dict[str, Any], plot_name: str, badge: str, accent: str) -> str:
    title = _esc_typst(_strip_inline_math(getattr(post, "title", "")))
    lead_raw = _strip_inline_math(getattr(post, "hook", "") or getattr(post, "body", ""))
    lead = _esc_typst(lead_raw[:190] + ("…" if len(lead_raw) > 190 else ""))
    source = _esc_typst((getattr(post, "source_name", "") or "Science Pulse").upper())
    legend = info["legend"]
    kind = info.get("formula_kind", "math")
    formula_image = info.get("formula_image")
    formula_text = info.get("formula_text") or _esc_typst("f(x)")
    formula_code = info.get("formula_code") or ""
    if kind == "math":
        header = "▸ АНАЛИТИЧЕСКОЕ СООТНОШЕНИЕ И ЦВЕТОВОЙ КЛЮЧ ГЕОМЕТРИИ:"
        chart_height = 345
    elif kind == "code":
        header = "▸ ЭТАЛОННЫЙ КОД НА PYTHON (подсветка синтаксиса):"
        chart_height = 262
    else:
        header = "▸ ФОРМУЛИРОВКА В ОДНУ СТРОКУ:"
        chart_height = 345
    if kind == "math" and formula_image:
        formula_block = (
            f'#block(width: 100%, height: 52pt)[#align(center + horizon)'
            f'[#image("{formula_image}", height: 100%, fit: "contain")]]'
        )
    elif kind == "code":
        lines = [line[:44] for line in (info.get("formula_code") or "").splitlines() if line.strip()][:9]
        numbers = "\\\n".join(f"{index:02d}" for index in range(1, len(lines) + 1))
        code_text = "\n".join(lines)
        formula_block = (
            '#block(fill: rgb("#0B0F17"), radius: 6pt, inset: 10pt, width: 100%)[\n'
            '#grid(columns: (auto, 1fr), gutter: 12pt, align: (right, left),\n'
            f'text(font: "DejaVu Sans Mono", size: 10pt, fill: rgb("#64748B"))[{numbers}],\n'
            f'text(fill: rgb("#83C167"))[#raw({_typst_string(code_text)}, lang: "python", block: true)],\n'
            ')]'
        )
    else:
        formula_block = (
            f'#block(width: 100%)[#align(center)[#text(font: "DejaVu Sans Mono", '
            f'size: 17pt, weight: "bold", fill: rgb("{accent}"))[{formula_text}]]]'
        )
    items = ",\n".join(
        '  rect(fill: rgb("#0B0F17"), radius: 6pt, inset: 7pt, width: 100%)['
        f'#text(size: 11.5pt, weight: "bold", fill: rgb("{color}"))[■ {_esc_typst(label)}]]'
        for color, label in legend
    )
    return f"""
#set page(width: 810pt, height: 810pt, fill: rgb("#07090E"), margin: 24pt)
#set text(font: ("DejaVu Sans", "Liberation Sans", "Arial"), fill: rgb("#F8FAFC"), lang: "ru")

#rect(
  width: 100%, height: 100%,
  fill: rgb("#0C1018"),
  stroke: 1.5pt + rgb("#223047"),
  radius: 16pt,
  inset: 26pt,
  [
    #grid(
      columns: (1fr, auto),
      align(left)[#text(font: "DejaVu Sans Mono", size: 13pt, weight: "bold", fill: rgb("{accent}"))[● {badge}]],
      align(right)[#text(font: "DejaVu Sans Mono", size: 11.5pt, fill: rgb("#94A3B8"))[SOURCE: {source}]]
    )
    #v(4pt)
    #line(length: 100%, stroke: 1pt + rgb("#1E293B"))
    #v(6pt)

    #text(size: 25pt, weight: "bold", fill: white)[{title}]
    #v(4pt)
    #text(size: 14.5pt, fill: rgb("#CBD5E1"))[{lead}]
    #v(10pt)

    #rect(
      width: 100%, height: {chart_height}pt,
      fill: rgb("#090C12"), stroke: 1.2pt + rgb("#1E293B"), radius: 10pt, inset: 4pt,
      align(center + horizon)[#image("{plot_name}", width: 100%, height: 100%, fit: "contain")]
    )
    #v(10pt)

    #rect(
      width: 100%, fill: rgb("#111724"), stroke: 1.5pt + rgb("{accent}"), radius: 12pt, inset: 14pt,
      [
        #text(font: "DejaVu Sans Mono", size: 11pt, weight: "bold", fill: rgb("#94A3B8"))[{header}]
        #v(6pt)
        {formula_block}
        #v(8pt)
        #grid(
          columns: (1fr, 1fr, 1fr),
          gutter: 8pt,
{items}
        )
      ]
    )
    #v(6pt)
    #grid(
      columns: (1fr, auto),
      text(font: "DejaVu Sans Mono", size: 11pt, fill: rgb("#64748B"))[newmathphys.com • \\@newmathphys],
      text(font: "DejaVu Sans Mono", size: 11pt, fill: rgb("#83C167"))[3B1B color-coded pedagogy]
    )
  ]
)
"""


def render_studio_card(post: Post, out_path: str | Path, size: int = 1080) -> Optional[CardArtifact]:
    """Студийная карточка 3Blue1Brown: Typst-вёрстка + 3B1B-чертёж.

    Возвращает `CardArtifact` (PNG ровно `size×size`, RGB) или `None`, если
    `typst` недоступен/сборка не удалась (тогда вызывающий код падает на Pillow).
    """
    if not typst_available():
        return None
    import typst
    from PIL import Image

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    work = out_path.parent
    plot_png = work / f"_b1b_{post.id}.png"
    formula_png = work / f"_formula_{post.id}.png"
    typ_file = work / f"_card_{post.id}.typ"
    raw_png = work / f"_raw_{post.id}.png"

    try:
        info = render_3b1b_plot(post, plot_png)
        badge, accent = DOMAIN_BADGES.get(getattr(post, "domain", "math"), DOMAIN_BADGES["math"])
        raw_formula = (getattr(post, "formula_latex", "") or getattr(post, "formula_plain", "") or "").strip()
        kind = formula_kind(raw_formula)
        info["formula_kind"] = kind
        info["formula_image"] = None
        info["formula_text"] = ""
        info["formula_code"] = ""
        if kind == "math":
            if render_formula_image(post, formula_png, accent):
                info["formula_image"] = formula_png.name
            else:  # LaTeX не понял mathtext → читаемый Unicode
                info["formula_text"] = _esc_typst(formula_to_unicode(raw_formula, 60))
        elif kind == "code":
            snippet = (getattr(post, "code", "") or raw_formula).strip()
            info["formula_code"] = snippet
        else:
            info["formula_kind"] = "text"
            info["formula_text"] = _esc_typst(_strip_inline_math(raw_formula)[:160] or "Science Pulse")
        typ_file.write_text(_typst_source(post, info, plot_png.name, badge, accent), encoding="utf-8")
        typst.compile(str(typ_file), output=str(raw_png), format="png", ppi=96.0)
        with Image.open(raw_png) as image:
            final = image.convert("RGB").resize((size, size), Image.Resampling.LANCZOS)
            final.save(out_path, format="PNG", optimize=True)
    except Exception as exc:  # любая ошибка → fallback на Pillow
        LOGGER.warning("Студийная карточка не собралась (%s), fallback на Pillow", exc)
        return None
    finally:
        for temp in (plot_png, typ_file, raw_png, formula_png):
            try:
                temp.unlink()
            except OSError:
                pass

    data = out_path.read_bytes()
    return CardArtifact(path=str(out_path), data=data, width=size, height=size)

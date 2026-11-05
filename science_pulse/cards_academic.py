"""Книжный движок карточек Science Pulse (академическая серия).

Стиль: бумага `#FAF8F4`, тушь `#111827`, текст — DejaVu Serif, формулы —
Computer Modern (matplotlib mathtext), потоковая верстка с курсором `y_cursor`.
Визуальный архетип чертежа выбирается по `post.meta["visual_type"]`
(или по содержимому поста):

- `standard_plot`     — классический график f(x) и производной f'(x);
- `code_booktabs`     — книжный листинг «Алгоритм 1.» между линиями booktabs;
- `diptych_insar`     — двухпанельный диптих «Физика и математика кадра»
                        (2D-поле слева: интерферограмма/геодезические/|ψ|²/Лоренц,
                        1D-разрез справа);
- `cheatsheet_table`  — карточка-шпаргалка / сводная таблица формул;
- `timeline_evolution` — инфографика «Эволюция идеи» (шкала времени с вехами).

Все физические поля генерируются детерминированно в `science_pulse.simulate`
(NumPy/SciPy): InSAR, NDVI, метрика Шварцшильда, туннелирование,
потенциал Леннард-Джонса, аттрактор Лоренца.
"""
from __future__ import annotations

import logging
import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

import numpy as np

from .models import CardArtifact, Post, DOMAIN_LABELS

LOGGER = logging.getLogger(__name__)

# Книжная палитра
PAPER = (250, 248, 244)   # #FAF8F4
INK = (17, 24, 39)        # #111827
MUTED = (107, 100, 88)
ACCENT = (139, 38, 53)    # бордо
RULE = (176, 170, 158)
PANEL = (240, 236, 228)

ARCHETYPES = (
    "standard_plot",
    "code_booktabs",
    "diptych_insar",
    "cheatsheet_table",
    "timeline_evolution",
    "logic_proof",
    "number_sequence",
    "matrix_grid",
    "prob_tree",
)
SIMULATIONS = ("insar", "ndvi", "geodesics", "tunneling", "lorenz", "lj",
               "cern_dimuon", "ligo_chirp", "voronoi_laplacian", "sat_tsp", "sparse_cg", "seismic_ps")

_FONT_DIRS = [
    "/usr/share/fonts/TTF",
    "/usr/share/fonts/truetype/dejavu",
    "/usr/share/fonts/truetype/liberation",
    str(Path.home() / ".fonts"),
]


def _serif_path(names: Tuple[str, ...]) -> Optional[str]:
    for directory in _FONT_DIRS:
        for name in names:
            candidate = Path(directory) / name
            if candidate.exists():
                return str(candidate)
    return None


def _serif_font(size: int, bold: bool = False, italic: bool = False, mono: bool = False) -> ImageFont.FreeTypeFont:
    if mono:
        names = ("DejaVuSansMono.ttf", "LiberationMono-Regular.ttf")
    elif bold and italic:
        names = ("DejaVuSerif-BoldItalic.ttf", "DejaVuSerif-Italic.ttf", "DejaVuSerif.ttf")
    elif bold:
        names = ("DejaVuSerif-Bold.ttf", "DejaVuSerif.ttf", "LiberationSerif-Bold.ttf")
    elif italic:
        names = ("DejaVuSerif-Italic.ttf", "DejaVuSerif.ttf", "LiberationSerif-Italic.ttf")
    else:
        names = ("DejaVuSerif.ttf", "LiberationSerif-Regular.ttf")
    path = _serif_path(names)
    if path:
        try:
            return ImageFont.truetype(path, size)
        except Exception as exc:  # pragma: no cover
            LOGGER.debug("Шрифт %s не загрузился: %s", path, exc)
    try:
        return ImageFont.load_default(size=size)  # type: ignore[call-arg]
    except TypeError:
        return ImageFont.load_default()


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> List[str]:
    lines: List[str] = []
    current = ""
    for word in (text or "").split():
        candidate = f"{current} {word}".strip()
        if current and draw.textlength(candidate, font=font) > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _fit(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    start_size: int,
    min_size: int,
    max_lines: int,
    bold: bool = False,
    italic: bool = False,
) -> Tuple[ImageFont.FreeTypeFont, List[str]]:
    size = start_size
    while size > min_size:
        font = _serif_font(size, bold=bold, italic=italic)
        lines = _wrap(draw, text, font, max_width)
        if len(lines) <= max_lines:
            return font, lines
        size -= 4
    font = _serif_font(min_size, bold=bold, italic=italic)
    return font, _wrap(draw, text, font, max_width)[:max_lines]


def _mathtext_normalize(expr: str) -> str:
    """Приводит LaTeX к подмножеству matplotlib mathtext (см. cards3b1b)."""
    from .cards3b1b import _mathtext_normalize as normalize

    return normalize(expr)


def render_formula_png(
    formula: str,
    out_png: str | Path,
    color: Tuple[int, int, int] = INK,
    fontset: str = "cm",
    dpi: int = 300,
) -> bool:
    """Рендерит формулу настоящим математическим движком (Computer Modern)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    raw = (formula or "").strip()
    if not raw:
        return False
    if len(raw) > 2 and raw.startswith("$") and raw.endswith("$"):
        raw = raw[1:-1]
    expr = f"${_mathtext_normalize(raw)}$"
    hex_color = "#{:02X}{:02X}{:02X}".format(*color)
    size = 30 if len(raw) <= 34 else (25 if len(raw) <= 56 else 20)
    try:
        plt.rcParams["mathtext.fontset"] = fontset
        fig = plt.figure(figsize=(8.2, 1.5), dpi=dpi)
        fig.patch.set_alpha(0.0)
        fig.text(0.5, 0.5, expr, ha="center", va="center", color=hex_color, fontsize=size)
        out_png = Path(out_png)
        out_png.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out_png, transparent=True, bbox_inches="tight", pad_inches=0.06)
        plt.close(fig)
        return True
    except Exception as exc:
        LOGGER.warning("Формула не отрендерилась (%s): %s", raw[:60], exc)
        return False


def _paper_style() -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update(
        {
            "font.family": "serif",
            "font.serif": ["DejaVu Serif", "Liberation Serif"],
            "mathtext.fontset": "cm",
            "text.color": "#111827",
            "axes.edgecolor": "#B0AA9E",
            "axes.labelcolor": "#111827",
            "xtick.color": "#6B6458",
            "ytick.color": "#6B6458",
            "axes.linewidth": 0.9,
            "figure.facecolor": "#FAF8F4",
            "axes.facecolor": "#FAF8F4",
            "savefig.facecolor": "#FAF8F4",
        }
    )


def _curve_from_post(post: Post) -> Any:
    """Безопасная функция f(x) из формулы поста (белый список SymPy) или образец."""
    import numpy as np

    raw = (getattr(post, "formula_latex", "") or getattr(post, "formula_plain", "") or "").strip()
    if raw and "x" in raw:
        try:
            from .plotting import parse_expression

            expr = parse_expression(raw)
            if expr is not None:
                import sympy as sp

                x = sp.Symbol("x")
                func = sp.lambdify(x, expr, modules=["numpy"])
                probe = func(np.linspace(-3, 3, 32))
                if np.all(np.isfinite(probe)):
                    return func
        except Exception:
            pass

    def default(x: Any) -> Any:
        return np.sin(1.6 * x) * np.exp(-(x**2) / 12.0)

    return default


def _chart_standard(post: Post, out_png: str | Path) -> None:
    """Классический книжный график: f(x) и производная f'(x)."""
    import numpy as np

    _paper_style()
    import matplotlib.pyplot as plt

    xs = np.linspace(-3.2, 3.2, 420)
    func = _curve_from_post(post)
    ys = np.asarray(func(xs), dtype=float)
    dys = np.gradient(ys, xs)

    fig, ax = plt.subplots(figsize=(8.6, 3.6), dpi=180)
    ax.axhline(0.0, color="#B0AA9E", lw=0.8)
    ax.axvline(0.0, color="#B0AA9E", lw=0.8)
    ax.plot(xs, ys, color="#8B2635", lw=2.6, label=r"$f(x)$")
    ax.plot(xs, dys, color="#2F4B7C", lw=2.0, label=r"$f'(x)$", linestyle="--")
    ax.fill_between(xs, ys, 0.0, color="#8B2635", alpha=0.10)
    ax.set_xlim(-3.2, 3.2)
    ax.legend(frameon=False, fontsize=13)
    ax.set_xlabel(r"$x$", fontsize=13)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(pad=0.4)
    out_png = Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png)
    plt.close(fig)


def _diptych_insar(out_left: Path, out_right: Path) -> Tuple[str, str]:
    import numpy as np

    from . import simulate

    import matplotlib.pyplot as plt

    data = simulate.insar_interferogram()
    fig, ax = plt.subplots(figsize=(4.3, 3.9), dpi=180)
    image = ax.imshow(data["phase"], cmap="twilight", vmin=-np.pi, vmax=np.pi, extent=data["extent"], origin="lower")
    ax.contour(data["axis"], data["axis"], data["phase"], levels=9, colors="#111827", linewidths=0.4, alpha=0.5)
    ax.set_title(r"$\Delta\phi(x,\,y)$: фазовые кольца InSAR", fontsize=11)
    fig.colorbar(image, ax=ax, fraction=0.046, ticks=[-np.pi, 0, np.pi])
    fig.tight_layout(pad=0.4)
    fig.savefig(out_left)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(4.3, 3.9), dpi=180)
    ax.plot(data["axis"], data["profile"], color="#2F4B7C", lw=1.8)
    ax.set_title("Разрез Δφ по центру кадра", fontsize=11)
    ax.set_xlabel(r"$x$", fontsize=11)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(pad=0.4)
    fig.savefig(out_right)
    plt.close(fig)
    return ("Δφ(x, y) — разность фаз радара", "1D-разрез профиля фазы")


def _diptych_ndvi(out_left: Path, out_right: Path) -> Tuple[str, str]:
    from . import simulate

    import matplotlib.pyplot as plt

    data = simulate.ndvi_map()
    fig, ax = plt.subplots(figsize=(4.3, 3.9), dpi=180)
    image = ax.imshow(data["ndvi"], cmap="YlGn", vmin=-0.2, vmax=0.85, extent=data["extent"], origin="lower")
    ax.set_title("NDVI = (NIR − Red)/(NIR + Red)", fontsize=11)
    fig.colorbar(image, ax=ax, fraction=0.046)
    fig.tight_layout(pad=0.4)
    fig.savefig(out_left)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(4.3, 3.9), dpi=180)
    ax.plot(data["axis"], data["nir"], color="#2E7D32", lw=1.8, label="NIR")
    ax.plot(data["axis"], data["red"], color="#B23A2E", lw=1.6, label="Red", linestyle="--")
    ax.legend(frameon=False, fontsize=11)
    ax.set_title("Спектральные полосы вдоль разреза", fontsize=11)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(pad=0.4)
    fig.savefig(out_right)
    plt.close(fig)
    return ("Карта растительности NDVI", "Полосы NIR и Red")


def _diptych_geodesics(out_left: Path, out_right: Path) -> Tuple[str, str]:
    import math

    import numpy as np

    from . import simulate

    import matplotlib.pyplot as plt

    rays = simulate.schwarzschild_rays()
    fig, ax = plt.subplots(figsize=(4.3, 3.9), dpi=180)
    for ray in rays:
        ax.plot(ray["x"], ray["y"], color="#2F4B7C", lw=1.1, alpha=0.85)
    ax.add_patch(plt.Circle((0.0, 0.0), 1.0, color="#111827", zorder=5))
    ax.add_patch(plt.Circle((0.0, 0.0), 1.5, fill=False, color="#8B2635", linestyle="--", lw=1.2, zorder=6))
    ax.set_xlim(-10.0, 10.0)
    ax.set_ylim(-8.5, 8.5)
    ax.set_aspect("equal")
    ax.set_title("Геодезические лучи у горизонта событий", fontsize=11)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(pad=0.4)
    fig.savefig(out_left)
    plt.close(fig)

    impact, deflection = [], []
    for ray in rays:
        x, y = ray["x"], ray["y"]
        slope_in = (y[2] - y[0]) / max(float(x[2] - x[0]), 1e-9)
        slope_out = (y[-1] - y[-3]) / max(float(x[-1] - x[-3]), 1e-9)
        impact.append(float(ray["b"][0]))
        deflection.append(abs(math.atan(slope_out) - math.atan(slope_in)))
    fig, ax = plt.subplots(figsize=(4.3, 3.9), dpi=180)
    ax.plot(impact, np.degrees(deflection), "o-", color="#8B2635", lw=1.8, ms=5)
    ax.set_title("Угол отклонения света α(b)", fontsize=11)
    ax.set_xlabel("прицельный параметр b", fontsize=11)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(pad=0.4)
    fig.savefig(out_right)
    plt.close(fig)
    return ("Лучи света в метрике Шварцшильда", "Отклонение α(b)")


def _diptych_tunneling(out_left: Path, out_right: Path) -> Tuple[str, str]:
    from . import simulate

    import matplotlib.pyplot as plt

    data = simulate.tunneling_profiles()
    fig, ax = plt.subplots(figsize=(4.3, 3.9), dpi=180)
    ax.fill_between(data["x"], data["barrier"] * 0.9, color="#B0AA9E", alpha=0.35, label="Барьер V₀")
    for label, color, key in (("t = 0", "#2F4B7C", "before"), ("на барьере", "#8B2635", "during"), ("после", "#2E7D32", "after")):
        ax.plot(data["x"], data["psi2"][key], color=color, lw=1.8, label=f"|ψ|², {label}")
    ax.set_xlim(-8, 8)
    ax.legend(frameon=False, fontsize=9)
    ax.set_title("Волновой пакет сквозь барьер", fontsize=11)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(pad=0.4)
    fig.savefig(out_left)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(4.3, 3.9), dpi=180)
    ax.plot(data["e_grid"], data["t_curve"], color="#8B2635", lw=2.2)
    ax.axvline(data["energy"], color="#2F4B7C", linestyle="--", lw=1.4)
    ax.set_title(f"Коэффициент прохождения T(E) ≈ {data['T']:.3f}", fontsize=11)
    ax.set_xlabel("E / V₀", fontsize=11)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(pad=0.4)
    fig.savefig(out_right)
    plt.close(fig)
    return ("|ψ(x,t)|²: туннелирование", "Коэффициент прохождения T(E)")


def _diptych_lorenz(out_left: Path, out_right: Path) -> Tuple[str, str]:
    from . import simulate

    import matplotlib.pyplot as plt

    data = simulate.lorenz_attractor()
    fig = plt.figure(figsize=(4.3, 3.9), dpi=180)
    ax = fig.add_subplot(projection="3d")
    ax.plot(data["x"], data["y"], data["z"], color="#2F4B7C", lw=0.5)
    ax.set_title("Аттрактор Лоренца (x, y, z)", fontsize=11)
    ax.set_axis_off()
    fig.tight_layout(pad=0.4)
    fig.savefig(out_left)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(4.3, 3.9), dpi=180)
    ax.plot(data["t"][:700], data["z"][:700], color="#8B2635", lw=1.2)
    ax.set_title("Осцилляция z(t): чувствительность к условиям", fontsize=10)
    ax.set_xlabel("t", fontsize=11)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(pad=0.4)
    fig.savefig(out_right)
    plt.close(fig)
    return ("Фазовый портрет хаоса", "Временной ряд z(t)")


def _diptych_lj(out_left: Path, out_right: Path) -> Tuple[str, str]:
    import numpy as np

    from . import simulate

    import matplotlib.pyplot as plt

    data = simulate.lennard_jones()
    fig, ax = plt.subplots(figsize=(4.3, 3.9), dpi=180)
    ax.plot(data["r"], data["V"], color="#8B2635", lw=2.2, label=r"$V(r)$")
    ax.plot(data["r"], data["F"], color="#2F4B7C", lw=1.6, linestyle="--", label=r"$F(r)$")
    ax.scatter(data["r_min"], data["v_min"], color="#111827", zorder=5)
    ax.annotate(r"$-\varepsilon$ при $2^{1/6}\sigma$",
                (float(data["r_min"][0]), float(data["v_min"][0])),
                textcoords="offset points", xytext=(10, 14), fontsize=10)
    ax.axhline(0.0, color="#B0AA9E", lw=0.8)
    ax.legend(frameon=False, fontsize=11)
    ax.set_title("Потенциал Леннард-Джонса", fontsize=11)
    ax.set_xlabel(r"$r/\sigma$", fontsize=11)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(pad=0.4)
    fig.savefig(out_left)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(4.3, 3.9), dpi=180)
    force = np.abs(np.gradient(data["V"], data["r"]))
    ax.fill_between(data["r"], data["V"], 0.0, color="#8B2635", alpha=0.12)
    ax.plot(data["r"], force, color="#2E7D32", lw=1.8, label=r"$|dV/dr|$")
    ax.axhline(0.0, color="#B0AA9E", lw=0.8)
    ax.legend(frameon=False, fontsize=11)
    ax.set_title("Сила взаимодействия вдоль r", fontsize=11)
    ax.set_xlabel(r"$r/\sigma$", fontsize=11)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(pad=0.4)
    fig.savefig(out_right)
    plt.close(fig)
    return ("Межатомный потенциал V(r)", "Профиль силы")


def _chart_diptych(post: Post, out_left: str | Path, out_right: str | Path) -> Tuple[str, str]:
    """Диптих «Физика и математика кадра»: 2D-поле слева, 1D-разрез справа."""
    _paper_style()
    out_left, out_right = Path(out_left), Path(out_right)
    out_left.parent.mkdir(parents=True, exist_ok=True)
    kind = str((getattr(post, "meta", {}) or {}).get("simulation") or "insar")
    if kind == "geodesics":
        return _diptych_geodesics(out_left, out_right)
    if kind == "tunneling":
        return _diptych_tunneling(out_left, out_right)
    if kind == "lorenz":
        return _diptych_lorenz(out_left, out_right)
    if kind == "lj":
        return _diptych_lj(out_left, out_right)
    if kind == "ndvi":
        return _diptych_ndvi(out_left, out_right)
    if kind == "cern_dimuon":
        return _diptych_cern(out_left, out_right)
    if kind == "ligo_chirp":
        return _diptych_ligo(out_left, out_right)
    if kind == "voronoi_laplacian":
        return _diptych_voronoi(out_left, out_right)
    if kind == "sat_tsp":
        return _diptych_sat_tsp(out_left, out_right)
    if kind == "sparse_cg":
        return _diptych_sparse_cg(out_left, out_right)
    if kind == "seismic_ps":
        return _diptych_seismic(out_left, out_right)
    return _diptych_insar(out_left, out_right)


def _diptych_pair(out_left: Path, out_right: Path, left: Any, right: Any,
                  title_left: str, title_right: str) -> Tuple[str, str]:
    """Общий каркас диптиха: две панели 4.3×3.9 дюйма с одинаковым оформлением."""
    import matplotlib.pyplot as plt

    for draw, target in ((left, out_left), (right, out_right)):
        fig, ax = plt.subplots(figsize=(4.3, 3.9), dpi=180)
        draw(fig, ax)
        fig.tight_layout(pad=0.4)
        fig.savefig(target)
        plt.close(fig)
    return title_left, title_right


def _diptych_cern(out_left: Path, out_right: Path) -> Tuple[str, str]:
    from . import simulate

    data = simulate.cern_dimuon_peak()

    def left(fig: Any, ax: Any) -> None:
        ax.step(data["centers"], data["hist"], where="mid", color="#2F4858", lw=1.4, label="события")
        ax.plot(data["centers"], data["breit_wigner"], color="#B23A2E", lw=2.0,
                label="Брейт — Вигнер")
        ax.axvline(data["true_mass"], color="#6B7280", ls=":", lw=1.2)
        ax.set_xlabel("инвариантная масса, ГэВ")
        ax.set_ylabel("число событий")
        ax.set_title("Пик Z-бозона из фона", fontsize=11)
        ax.legend(frameon=False, fontsize=10)
        ax.spines[["top", "right"]].set_visible(False)

    def right(fig: Any, ax: Any) -> None:
        window = data["window"]
        ax.errorbar(data["centers"][window], data["hist"][window],
                    yerr=np.sqrt(np.maximum(data["hist"][window], 1.0)),
                    fmt="o", ms=3.0, color="#2F4858", lw=1.0, label="данные")
        ax.plot(data["centers"][window], data["breit_wigner"][window], color="#B23A2E", lw=2.0,
                label=f"BW: m₀ = {data['true_mass']:.1f} ГэВ, Γ = {data['width_gev']} ГэВ")
        ax.set_xlabel("масса, ГэВ")
        ax.set_title("Резонанс крупным планом", fontsize=11)
        ax.legend(frameon=False, fontsize=10)
        ax.spines[["top", "right"]].set_visible(False)

    return _diptych_pair(out_left, out_right, left, right, "Инвариантная масса димюонов", "Резонанс Брейта — Вигнера")


def _diptych_ligo(out_left: Path, out_right: Path) -> Tuple[str, str]:
    from . import simulate

    data = simulate.ligo_chirp()

    def left(fig: Any, ax: Any) -> None:
        ax.plot(data["t"], data["raw"], color="#9AA5B1", lw=0.7, label="шум + сигнал")
        ax.plot(data["t"], data["filtered"], color="#1D3557", lw=1.3, label="фильтр Баттерворта")
        ax.set_xlabel("время, с")
        ax.set_ylabel("деформация h(t)")
        ax.set_title(f"GW150914: {data['m1']:.0f} + {data['m2']:.0f} M⊙", fontsize=11)
        ax.legend(frameon=False, fontsize=10)
        ax.spines[["top", "right"]].set_visible(False)

    def right(fig: Any, ax: Any) -> None:
        spec = data["spectrogram"]
        if spec:
            ax.pcolormesh(spec["time"], spec["freq"], 10 * np.log10(spec["power"] + 1e-12),
                          shading="auto", cmap="magma")
            ax.set_ylim(0, data["f_end"] * 1.6)
            ax.set_ylabel("частота, Гц")
        else:
            ax.plot(data["t"], data["frequency"], color="#B23A2E", lw=2.0)
        ax.set_xlabel("время, с")
        ax.set_title("Чирп: разгон частоты", fontsize=11)

    return _diptych_pair(out_left, out_right, left, right, "Сигнал слияния и фильтр", "Спектрограмма чирпа")


def _diptych_voronoi(out_left: Path, out_right: Path) -> Tuple[str, str]:
    from . import simulate

    data = simulate.voronoi_delaunay_laplacian()

    def left(fig: Any, ax: Any) -> None:
        for segment in data["segments"]:
            ax.plot(segment[:, 0], segment[:, 1], color="#9AA5B1", lw=0.8)
        ax.triplot(data["points"][:, 0], data["points"][:, 1], data["simplices"],
                   color="#1D3557", lw=1.0)
        ax.plot(data["points"][:, 0], data["points"][:, 1], "o", ms=4.0, color="#B23A2E")
        ax.set_title("Вороной + Делоне", fontsize=11)
        ax.set_xticks([])
        ax.set_yticks([])

    def right(fig: Any, ax: Any) -> None:
        values = data["eigenvalues"]
        ax.plot(np.arange(values.size), values, "o-", ms=4.0, color="#1D3557")
        ax.axhline(data["fiedler"], color="#B23A2E", ls="--", lw=1.4,
                   label=f"λ₂ (Фидлер) = {data['fiedler']:.3f}")
        ax.set_xlabel("номер собственного значения")
        ax.set_ylabel("λ")
        ax.set_title("Спектр лапласиана L = D − A", fontsize=11)
        ax.legend(frameon=False, fontsize=10)
        ax.spines[["top", "right"]].set_visible(False)

    return _diptych_pair(out_left, out_right, left, right, "Диаграмма Вороного и Делоне", "Связность графа λ₂")


def _diptych_sat_tsp(out_left: Path, out_right: Path) -> Tuple[str, str]:
    from . import simulate

    data = simulate.sat_phase_transition()
    route = simulate.tsp_route()

    def left(fig: Any, ax: Any) -> None:
        ax.plot(data["alpha"], data["satisfiable"], "o-", color="#1D3557", ms=4.0,
                label="доля выполнимых")
        ax.axvline(data["alpha_critical"], color="#B23A2E", ls="--", lw=1.4,
                   label=f"α_c ≈ {data['alpha_critical']}")
        twin = ax.twinx()
        twin.plot(data["alpha"], data["effort"], "s--", color="#9AA5B1", ms=3.0, label="усилия DPLL")
        twin.set_ylabel("узлы поиска", color="#6B7280")
        ax.set_xlabel("α = m/n")
        ax.set_ylabel("доля выполнимых")
        ax.set_title("Фазовый переход 3-SAT", fontsize=11)
        ax.legend(frameon=False, fontsize=9, loc="lower left")
        ax.spines[["top"]].set_visible(False)

    def right(fig: Any, ax: Any) -> None:
        cities = route["cities"]
        tour = route["order"]
        ax.plot(cities[tour, 0], cities[tour, 1], "-", color="#1D3557", lw=1.4)
        ax.plot(cities[:, 0], cities[:, 1], "o", ms=4.0, color="#B23A2E")
        ax.set_title(f"TSP: {route['length']:.2f} (жадно {route['initial_length']:.2f})", fontsize=11)
        ax.set_xticks([])
        ax.set_yticks([])

    return _diptych_pair(out_left, out_right, left, right, "Порог выполнимости α ≈ 4.26", "Маршрут коммивояжёра")


def _diptych_sparse_cg(out_left: Path, out_right: Path) -> Tuple[str, str]:
    from . import simulate

    data = simulate.sparse_cg_convergence()

    def left(fig: Any, ax: Any) -> None:
        ax.plot(data["cols"], data["rows"], ",", color="#1D3557")
        ax.invert_yaxis()
        ax.set_xlabel("столбец")
        ax.set_ylabel("строка")
        ax.set_title(f"CSR: nnz = {data['nnz']} ({data['density'] * 100:.2f}%)", fontsize=11)

    def right(fig: Any, ax: Any) -> None:
        ax.semilogy(np.arange(1, data["cg_residual"].size + 1), data["cg_residual"],
                    color="#1D3557", lw=1.6, label="сопряжённые градиенты")
        ax.semilogy(np.arange(1, data["gradient_residual"].size + 1), data["gradient_residual"],
                    color="#B23A2E", lw=1.4, ls="--", label="градиентный спуск")
        ax.set_xlabel("итерация")
        ax.set_ylabel("‖Ax − b‖₂")
        ax.set_title("Сходимость решателей", fontsize=11)
        ax.legend(frameon=False, fontsize=10)
        ax.spines[["top", "right"]].set_visible(False)

    return _diptych_pair(out_left, out_right, left, right, "Структура разреженной матрицы", "CG против градиентного спуска")


def _diptych_seismic(out_left: Path, out_right: Path) -> Tuple[str, str]:
    from . import simulate

    data = simulate.seismic_triangulation()

    def left(fig: Any, ax: Any) -> None:
        ax.plot(data["delays"], data["distance_km"], "o-", color="#1D3557", ms=4.0)
        for delay, distance in zip(data["delays"], data["distance_km"]):
            ax.annotate(f"{distance:.0f} км", (delay, distance), textcoords="offset points",
                        xytext=(4, -8), fontsize=8, color="#6B7280")
        ax.set_xlabel("Δt между S- и P-волнами, с")
        ax.set_ylabel("расстояние до эпицентра, км")
        ax.set_title(data["formula"], fontsize=10)
        ax.spines[["top", "right"]].set_visible(False)

    def right(fig: Any, ax: Any) -> None:
        t = np.linspace(0.0, 30.0, 400)
        p_km_s, s_km_s = data["p_km_s"], data["s_km_s"]
        ax.plot(t, t * p_km_s, color="#1D3557", lw=1.6, label=f"P-волна {p_km_s:.1f} км/с")
        ax.plot(t, t * s_km_s, color="#B23A2E", lw=1.6, label=f"S-волна {s_km_s:.1f} км/с")
        ax.set_xlabel("время, с")
        ax.set_ylabel("пройденный путь, км")
        ax.set_title("Обгон P-волной S-волны", fontsize=11)
        ax.legend(frameon=False, fontsize=10)
        ax.spines[["top", "right"]].set_visible(False)

    return _diptych_pair(out_left, out_right, left, right, "Триангуляция по P/S-волнам", "Разные скорости волн")


def _chart_timeline(post: Post, out_png: str | Path) -> List[Dict[str, Any]]:
    """Инфографика «Эволюция идеи»: горизонтальная шкала времени с вехами."""
    import matplotlib.pyplot as plt

    meta = getattr(post, "meta", {}) or {}
    raw_items = meta.get("timeline") or []
    items: List[Dict[str, Any]] = []
    for entry in raw_items:
        try:
            items.append({"year": float(entry["year"]), "label": str(entry["label"])[:26]})
        except (TypeError, ValueError, KeyError):
            continue
    if len(items) < 2:
        items = [
            {"year": 1687, "label": "Ньютон"},
            {"year": 1822, "label": "Фурье"},
            {"year": 1865, "label": "Максвелл"},
            {"year": 1926, "label": "Шрёдингер"},
            {"year": 1948, "label": "Шеннон"},
        ]
    items = sorted(items, key=lambda item: item["year"])[:7]
    n_items = len(items)

    fig, ax = plt.subplots(figsize=(8.6, 3.2), dpi=180)
    ax.axhline(0.0, color="#111827", lw=2.2, zorder=2)
    positions = list(range(n_items))
    for index, item in enumerate(items):
        side = 1 if index % 2 == 0 else -1
        ax.scatter([index], [0.0], s=90, color="#8B2635", zorder=4)
        ax.vlines(index, 0.0, 0.22 * side, color="#B0AA9E", lw=1.2, zorder=3)
        ax.text(index, 0.28 * side, item["label"], ha="center",
                va="bottom" if side > 0 else "top", fontsize=10.5)
        ax.text(index, 0.12 * side, f"{item['year']:.0f}", ha="center",
                va="bottom" if side > 0 else "top", fontsize=8.5, color="#6B6458")
        if index + 1 < n_items:
            span = items[index + 1]["year"] - item["year"]
            ax.annotate("", xy=(index + 1, -0.05), xytext=(index, -0.05),
                        arrowprops=dict(arrowstyle="->", color="#2F4B7C", lw=1.4))
            ax.text(index + 0.5, -0.16, f"Δ = {span:.0f} лет", ha="center", fontsize=8.5, color="#2F4B7C")
    ax.set_xlim(-0.6, n_items - 0.4)
    ax.set_ylim(-0.55, 0.55)
    ax.set_xticks(positions)
    ax.set_xticklabels([])
    ax.get_yaxis().set_visible(False)
    for spine in ("top", "left", "right"):
        ax.spines[spine].set_visible(False)
    ax.spines["bottom"].set_visible(False)
    ax.set_title("Эволюция идеи: хронология ключевых вех", fontsize=12)
    fig.tight_layout(pad=0.4)
    out_png = Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png)
    plt.close(fig)
    return items


def _table_data(post: Post) -> Tuple[List[str], List[List[str]]]:
    """Строки шпаргалки: из `post.meta["table"]` или содержательный образец."""
    meta = getattr(post, "meta", {}) or {}
    table = meta.get("table") or {}
    columns = [str(col) for col in (table.get("columns") or [])]
    rows = [[str(cell) for cell in row] for row in (table.get("rows") or [])]
    if len(columns) >= 2 and rows:
        return columns[:4], [row[: len(columns)] for row in rows[:5]]
    return (
        ["Теория", "Ключевая формула", "Где работает"],
        [
            ["Классическая механика", "F = ma", "Механика, астрономия"],
            ["Относительность", "E = mc²", "GPS, гравитационные волны"],
            ["Квантовая механика", "iħ·∂Ψ/∂t = ĤΨ", "Лазеры, полупроводники"],
        ],
    )


NON_ARITHMETIC_RE = re.compile(
    r"∇|\\nabla|∫|\\int|∮|\\oint|∑|\\sum|∏|\\prod|\blim\b|\bmod\b|\\pmod"
)


def _is_plottable(post: Post) -> bool:
    """Можно ли построить честный график y = f(x) по формуле поста."""
    expression = str(getattr(post, "formula_plain", "") or getattr(post, "formula_latex", "") or "")
    if not expression.strip():
        return False
    try:
        from .plotting import parse_expression

        parse_expression(expression)
        return True
    except Exception:
        return False


def pick_visual_type(post: Post) -> str:
    """Выбирает визуальный архетип: явный `meta["visual_type"]` или эвристика."""
    meta = getattr(post, "meta", {}) or {}
    declared = str(meta.get("visual_type") or "").strip()
    if declared in ARCHETYPES:
        return declared
    if str(meta.get("simulation") or "") in SIMULATIONS:
        return "diptych_insar"
    if meta.get("timeline"):
        return "timeline_evolution"
    if meta.get("table"):
        return "cheatsheet_table"
    text = f"{getattr(post, 'title', '')} {getattr(post, 'body', '')} {getattr(post, 'hook', '')}".lower()
    code = getattr(post, "code", "") or ""
    formula_text = (
        f"{getattr(post, 'formula_latex', '')} {getattr(post, 'formula_plain', '')}".lower()
    )
    has_formula = bool(formula_text.strip())
    # 6-й архетип: логика, аксиомы, теоремы (логические символы и нет переменной x).
    logic_symbols = ("∀", "∃", "¬", "∧", "∨", "⇒", "\\forall", "\\exists", "\\neg", "\\implies", "provable")
    if any(symbol.lower() in formula_text for symbol in logic_symbols) and not re.search(r"\bx\b", formula_text):
        return "logic_proof"
    # 7-й архетип: числовые ряды (OEIS, простые числа, Фибоначчи).
    if str(getattr(post, "source_name", "")).lower().startswith("oeis") or _sequence_values(post, minimum=6):
        return "number_sequence"
    # 8-й архетип: линейная алгебра, матрицы, тензоры, квантовые операторы.
    if re.search(r"матриц|matrix|собственн|eigen|линейн|тензор|tensor|оператор|determinant", text):
        return "matrix_grid"
    # 9-й архетип: теория вероятностей, Байес, цепи Маркова.
    if re.search(r"вероятн|probab|байес|bayes|марков|markov|статистик|энтроп", text):
        return "prob_tree"
    # Алгоритмический пост с кодом — книжный листинг «Алгоритм 1.», даже если есть формула
    # (сложность O(...) показывается отдельной строкой под листингом).
    if code and ("алгоритм" in text or "algorithm" in text or ("def " in code and not has_formula)):
        return "code_booktabs"
    if "шпаргал" in text or "сравнен" in text or "таблиц" in text or "против" in text:
        return "cheatsheet_table"
    if re.search(r"\d{3,4}\s*г\.", text) and text.count("г.") >= 2:
        return "timeline_evolution"
    # Неарифметическая формула (∇, ∫, ∮, ∑, ∏, lim, mod) не строится как честный
    # график y = f(x): вместо «случайной» кривой показываем сводную карточку с
    # самой формулой и её членами (детерминированно, без дефолтной синусоиды).
    if has_formula and NON_ARITHMETIC_RE.search(formula_text) and not _is_plottable(post):
        return "cheatsheet_table"
    return "standard_plot"


def _draw_table(canvas: Image.Image, draw: ImageDraw.ImageDraw, post: Post, y: int, margin: int, width: int, scale: int) -> int:
    """Шпаргалка-таблица в духе booktabs: толстые линии сверху/снизу, тонкая под шапкой."""
    columns, rows = _table_data(post)
    n_cols = len(columns)
    col_width = width // n_cols
    header_font = _serif_font(19 * scale, bold=True)
    cell_font = _serif_font(17 * scale)
    row_h = 64 * scale

    draw.line((margin, y, margin + width, y), fill=INK, width=int(2.6 * scale))
    y += 10 * scale
    for index, col in enumerate(columns):
        x = margin + index * col_width
        header_y = y
        for line in _wrap(draw, col, header_font, col_width - 18 * scale)[:2]:
            draw.text((x + 8 * scale, header_y), line, fill=ACCENT, font=header_font)
            header_y += 24 * scale
    y += 32 * scale
    draw.line((margin, y, margin + width, y), fill=INK, width=int(1.1 * scale))
    y += 8 * scale

    for row in rows[:5]:
        row_bottom = y
        for index, cell in enumerate(row[:n_cols]):
            x = margin + index * col_width
            cell_y = y
            for line in _wrap(draw, cell, cell_font, col_width - 18 * scale)[:2]:
                draw.text((x + 8 * scale, cell_y), line, fill=INK, font=cell_font)
                cell_y += 22 * scale
            row_bottom = max(row_bottom, cell_y)
        y = max(y + row_h, row_bottom + 10 * scale)
    draw.line((margin, y, margin + width, y), fill=INK, width=int(2.6 * scale))
    return y + 14 * scale


def _draw_code_listing(canvas: Image.Image, draw: ImageDraw.ImageDraw, post: Post, y: int, margin: int, width: int, scale: int) -> int:
    """Книжный листинг «Алгоритм 1.» между линиями booktabs."""
    caption_font = _serif_font(21 * scale, bold=True)
    code_font = _serif_font(17 * scale, mono=True)
    number_font = _serif_font(15 * scale, mono=True)

    title = getattr(post, "title", "") or "Алгоритм"
    caption = f"Алгоритм 1.  {title[:70]}"
    for line in _wrap(draw, caption, caption_font, width)[:2]:
        draw.text((margin, y), line, fill=INK, font=caption_font)
        y += 27 * scale

    draw.line((margin, y, margin + width, y), fill=INK, width=int(2.2 * scale))
    y += 10 * scale

    code = (getattr(post, "code", "") or "").strip()
    lines = [line for line in code.splitlines() if line.strip()][:9]
    if not lines:
        lines = ["def solve():", "    return 'детерминированный результат'"]
    for index, line in enumerate(lines, start=1):
        number = f"{index:02d}"
        draw.text((margin, y), number, fill=RULE, font=number_font)
        draw.text((margin + 34 * scale, y), line[:58], fill=INK, font=code_font)
        y += 23 * scale

    draw.line((margin, y, margin + width, y), fill=INK, width=int(2.2 * scale))
    y += 10 * scale
    match = re.search(r"O\([^)]+\)", code + " " + getattr(post, "body", ""))
    if match:
        draw.text((margin, y), f"Вычислительная сложность: {match.group(0)}", fill=ACCENT, font=_serif_font(17 * scale, italic=True))
        y += 26 * scale
    return y + 8 * scale


def _paste_fitted(canvas: Image.Image, img_path: Path, y: int, center_x: int, max_w: int, max_h: int) -> int:
    """Вклеивает картинку с сохранением пропорций; возвращает нижнюю границу."""
    with Image.open(img_path) as image:
        img = image.convert("RGB")
        ratio = min(max_w / img.width, max_h / img.height)
        new_size = (max(1, int(img.width * ratio)), max(1, int(img.height * ratio)))
        img = img.resize(new_size, Image.Resampling.LANCZOS)
    canvas.paste(img, (center_x - img.width // 2, y))
    return y + img.height


def _sequence_values(post: Post, minimum: int = 6) -> List[int]:
    """Достаёт числовую последовательность (≥ ``minimum`` чисел через запятую)."""
    pattern = re.compile(r"-?\d+(?:\s*,\s*-?\d+){%d,}" % (minimum - 1))
    for text in (getattr(post, "hook", ""), getattr(post, "body", ""), getattr(post, "formula_plain", "")):
        match = pattern.search(text or "")
        if not match:
            continue
        try:
            values = [int(part.strip()) for part in match.group(0).split(",") if part.strip()]
        except ValueError:
            continue
        if len(values) >= minimum:
            return values[:12]
    return []


def _in_finder(row: int, col: int, size: int) -> bool:
    return (
        (row < 7 and col < 7)
        or (row < 7 and col >= size - 7)
        or (row >= size - 7 and col < 7)
    )


def _stamp_finder(matrix: List[List[bool]], top: int, left: int, size: int) -> None:
    for r in range(7):
        for c in range(7):
            rr, cc = top + r, left + c
            if 0 <= rr < size and 0 <= cc < size:
                edge = r in (0, 6) or c in (0, 6)
                center = 2 <= r <= 4 and 2 <= c <= 4
                matrix[rr][cc] = edge or center


def _qr_matrix(text: str, size: int = 21) -> List[List[bool]]:
    """Детерминированная битовая матрица из sha256 (fallback без пакета `qrcode`)."""
    import hashlib

    matrix = [[False] * size for _ in range(size)]
    for row in range(size):
        for col in range(size):
            if _in_finder(row, col, size):
                continue
            digest = hashlib.sha256(f"{text}|{row}|{col}".encode("utf-8")).digest()
            matrix[row][col] = bool(digest[0] & 1)
    for top, left in ((0, 0), (0, size - 7), (size - 7, 0)):
        _stamp_finder(matrix, top, left, size)
    return matrix


def qr_image(text: str, px: int = 68) -> Optional[Image.Image]:
    """QR-код ссылки: пакет `qrcode`, иначе детерминированная матрица 21×21."""
    if not text:
        return None
    try:
        import qrcode  # type: ignore

        code = qrcode.QRCode(border=0, box_size=4)
        code.add_data(text)
        code.make(fit=True)
        return code.make_image(fill_color="#111827", back_color="#FAF8F4").convert("RGB").resize(
            (px, px), Image.Resampling.NEAREST
        )
    except Exception:
        pass
    size = 21
    module = max(1, px // size)
    real = module * size
    image = Image.new("RGB", (real, real), PAPER)
    draw = ImageDraw.Draw(image)
    matrix = _qr_matrix(text, size)
    for row in range(size):
        for col in range(size):
            if matrix[row][col]:
                draw.rectangle(
                    [col * module, row * module, (col + 1) * module - 1, (row + 1) * module - 1],
                    fill=INK,
                )
    return image.resize((px, px), Image.Resampling.NEAREST) if real != px else image


def _draw_logic_proof(
    image: Image.Image, draw: ImageDraw.ImageDraw, post: Post, y: int, margin: int, width: int, scale: int
) -> int:
    """3 академических блока (посылка → формальный переход → следствие) + таблица истинности."""
    body = (getattr(post, "body", "") or "").strip()
    first_sentence = re.split(r"(?<=[.!?])\s+", body)[0] if body else ""
    formula = (getattr(post, "formula_plain", "") or getattr(post, "formula_latex", "") or "").strip()
    blocks = [
        ("I. АКСИОМА / ИСХОДНАЯ ПОСЫЛКА", getattr(post, "hook", "") or ""),
        ("II. ФОРМАЛЬНЫЙ ПЕРЕХОД", formula or "⊢ P ⇒ Q"),
        ("III. ДОКАЗАННОЕ СЛЕДСТВИЕ", first_sentence or "Q доказано"),
    ]
    table_w = 232 * scale
    box_w = width - table_w - 24 * scale
    box_h = 84 * scale
    start_y = y
    for index, (head, text) in enumerate(blocks):
        top = y
        draw.rectangle([margin, top, margin + box_w, top + box_h], fill=PANEL, outline=INK, width=scale)
        draw.rectangle([margin, top, margin + 6 * scale, top + box_h], fill=ACCENT)
        draw.text((margin + 18 * scale, top + 8 * scale), head, fill=ACCENT,
                  font=_serif_font(15 * scale, bold=True, mono=True))
        font, lines = _fit(draw, text[:220], box_w - 36 * scale, 20 * scale, 14 * scale, 2)
        ty = top + 32 * scale
        for line in lines[:2]:
            draw.text((margin + 18 * scale, ty), line, fill=INK, font=font)
            ty += int(getattr(font, "size", 20 * scale) * 1.25)
        y = top + box_h
        if index < len(blocks) - 1:
            cx = margin + box_w // 2
            draw.polygon([(cx, y + 5 * scale), (cx - 8 * scale, y + 19 * scale), (cx + 8 * scale, y + 19 * scale)], fill=INK)
            y += 30 * scale
    tx = margin + box_w + 24 * scale
    draw.text((tx, start_y), "ТАБЛИЦА ИСТИННОСТИ", fill=MUTED, font=_serif_font(13 * scale, bold=True, mono=True))
    rows = [("A", "B", "A ⇒ B"), ("0", "0", "1"), ("0", "1", "1"), ("1", "0", "1"), ("1", "1", "1")]
    row_h = 30 * scale
    ty = start_y + 24 * scale
    for index, row in enumerate(rows):
        draw.rectangle([tx, ty, tx + table_w, ty + row_h], fill=PANEL if index % 2 == 0 else PAPER,
                       outline=RULE, width=scale)
        for col, cell in enumerate(row):
            draw.text((tx + 12 * scale + col * (table_w // 3), ty + 6 * scale), cell, fill=INK,
                      font=_serif_font(16 * scale, mono=index > 0))
        ty += row_h
    return max(y, ty) + 10 * scale


def _draw_number_sequence(
    image: Image.Image, draw: ImageDraw.ImageDraw, post: Post, y: int, margin: int, width: int, scale: int
) -> int:
    """Ряд ячеек a₁…aₙ с разностями Δ и дискретный stem-plot."""
    values = (_sequence_values(post, minimum=4) or [1, 1, 2, 3, 5, 8, 13, 21])[:8]
    cells = len(values)
    gap = 10 * scale
    cell_w = (width - gap * (cells - 1)) // cells
    cell_h = 64 * scale
    for index, value in enumerate(values):
        left = margin + index * (cell_w + gap)
        draw.rectangle([left, y, left + cell_w, y + cell_h], fill=PANEL, outline=INK, width=scale)
        draw.text((left + 10 * scale, y + 7 * scale), f"a{index + 1}", fill=MUTED,
                  font=_serif_font(13 * scale, mono=True))
        draw.text((left + 10 * scale, y + 26 * scale), str(value), fill=INK,
                  font=_serif_font(24 * scale, bold=True, mono=True))
        if index < cells - 1:
            draw.text((left + cell_w + gap // 4, y + 22 * scale), "→", fill=ACCENT,
                      font=_serif_font(18 * scale, bold=True))
            draw.text((left + cell_w + 2 * scale, y + cell_h + 6 * scale),
                      f"Δ={values[index + 1] - value:+d}", fill=ACCENT, font=_serif_font(12 * scale, mono=True))
    y += cell_h + 34 * scale
    plot_h = 170 * scale
    base = y + plot_h
    draw.line([margin, base, margin + width, base], fill=RULE, width=scale)
    peak = max((abs(value) for value in values), default=1) or 1
    step = width // max(len(values) - 1, 1)
    for index, value in enumerate(values):
        px = margin + index * step
        ph = int(plot_h * (abs(value) / peak))
        draw.line([px, base, px, base - ph], fill=ACCENT, width=2 * scale)
        draw.ellipse([px - 5 * scale, base - ph - 5 * scale, px + 5 * scale, base - ph + 5 * scale], fill=INK)
        draw.text((px - 14 * scale, base - ph - 26 * scale), str(value), fill=INK,
                  font=_serif_font(14 * scale, mono=True))
    return base + 18 * scale


def _draw_matrix_grid(
    image: Image.Image, draw: ImageDraw.ImageDraw, post: Post, y: int, margin: int, width: int, scale: int
) -> int:
    """Матричная решётка 3×3: элементы, собственные значения и вектор преобразования."""
    import numpy as np

    size = 72 * scale
    gap = 8 * scale
    origin_x = margin + 20 * scale
    seed = sum(ord(char) for char in (getattr(post, "id", "") or "matrix"))
    rng = np.random.default_rng(seed % (2 ** 32))
    matrix = rng.integers(-3, 4, size=(3, 3)).astype(float)
    for row in range(3):
        for col in range(3):
            left = origin_x + col * (size + gap)
            top = y + row * (size + gap)
            draw.rectangle([left, top, left + size, top + size], fill=PANEL, outline=RULE, width=scale)
            draw.text((left + size // 2 - 12 * scale, top + size // 2 - 14 * scale),
                      f"{int(matrix[row][col]):+d}", fill=INK, font=_serif_font(20 * scale, mono=True))
    info_x = origin_x + 3 * (size + gap) + 24 * scale
    draw.text((info_x, y + 12 * scale), "СОБСТВЕННЫЕ ЗНАЧЕНИЯ", fill=ACCENT,
              font=_serif_font(14 * scale, bold=True, mono=True))
    values = np.linalg.eigvals(matrix)
    text = ", ".join(
        f"{value.real:+.2f}" + (f"{value.imag:+.2f}i" if abs(value.imag) > 1e-9 else "")
        for value in values
    )
    draw.text((info_x, y + 38 * scale), text[:36], fill=INK, font=_serif_font(16 * scale, mono=True))
    draw.text((info_x, y + 66 * scale), "M · v = λ · v", fill=MUTED, font=_serif_font(16 * scale, italic=True))
    draw.text((info_x, y + 94 * scale), "det M ≠ 0 → обратимое преобразование", fill=MUTED,
              font=_serif_font(14 * scale))
    return y + 3 * size + 2 * gap + 18 * scale


def _draw_prob_tree(
    image: Image.Image, draw: ImageDraw.ImageDraw, post: Post, y: int, margin: int, width: int, scale: int
) -> int:
    """Дерево исходов: ветви с весами P(A|B), суммы по уровням равны единице."""
    root = (margin + 30 * scale, y + 96 * scale)
    first = [(margin + 250 * scale, y + 34 * scale), (margin + 250 * scale, y + 158 * scale)]
    second = [
        (margin + 490 * scale, y + 12 * scale),
        (margin + 490 * scale, y + 74 * scale),
        (margin + 490 * scale, y + 136 * scale),
        (margin + 490 * scale, y + 198 * scale),
    ]
    edges = [
        (root, first[0], "0.6"), (root, first[1], "0.4"),
        (first[0], second[0], "0.7"), (first[0], second[1], "0.3"),
        (first[1], second[2], "0.5"), (first[1], second[3], "0.5"),
    ]
    for source, target, weight in edges:
        draw.line([source, target], fill=RULE, width=2 * scale)
        mid_x = (source[0] + target[0]) // 2
        mid_y = (source[1] + target[1]) // 2
        draw.text((mid_x - 22 * scale, mid_y - 22 * scale), f"P={weight}", fill=ACCENT,
                  font=_serif_font(13 * scale, mono=True))
    for point in [root] + first + second:
        draw.ellipse([point[0] - 9 * scale, point[1] - 9 * scale, point[0] + 9 * scale, point[1] + 9 * scale],
                     fill=PAPER, outline=INK, width=2 * scale)
    draw.text((margin + 530 * scale, y + 90 * scale), "Σ P(ветвь) = 1", fill=MUTED,
              font=_serif_font(16 * scale, italic=True))
    return y + 216 * scale


def _draw_mini_dag(draw: ImageDraw.ImageDraw, post: Post, x: int, y: int, scale: int) -> int:
    """Миниатюра локального графа: ``[§ пред.] → [● § тек.] → [§ след.]``."""
    from .sources.foundation import CANON, default_prereqs, section_of

    meta = getattr(post, "meta", {}) or {}
    canon_id = str(meta.get("foundation_id") or "")
    section = str(meta.get("section_num") or "").strip()
    if not canon_id:
        return x
    parents = default_prereqs(canon_id)
    before = section_of(parents[0]) if parents else ""
    after = ""
    for item in CANON:
        if canon_id in default_prereqs(item["id"]):
            after = section_of(item["id"])
            break
    boxes = [((f"§ {before}" if before else "аксиома"), MUTED), (f"● § {section}", INK)]
    if after:
        boxes.append((f"§ {after}", MUTED))
    cursor = x
    font = _serif_font(13 * scale, mono=True)
    for index, (label, colour) in enumerate(boxes):
        box_w = int(draw.textlength(label, font=font)) + 18 * scale
        draw.rectangle([cursor, y, cursor + box_w, y + 26 * scale], fill=PANEL, outline=RULE, width=scale)
        draw.text((cursor + 9 * scale, y + 6 * scale), label, fill=colour, font=font)
        cursor += box_w + 6 * scale
        if index < len(boxes) - 1:
            draw.text((cursor, y + 4 * scale), "→", fill=ACCENT, font=_serif_font(15 * scale, bold=True))
            cursor += 20 * scale
    return cursor


def render_academic_card(post: Post, out_path: str | Path, size: int = 1080) -> Optional[CardArtifact]:
    """Книжная карточка академической серии (бумага, тушь, DejaVu Serif, CM-формулы).

    Возвращает `CardArtifact` (PNG ровно `size×size`, RGB) или `None`, если
    сборка не удалась (тогда вызывающий код падает на другой движок).
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    work = out_path.parent
    scale = 2
    canvas_size = size * scale
    margin = 84 * scale
    width = canvas_size - 2 * margin
    center_x = canvas_size // 2

    try:
        visual = pick_visual_type(post)
        chart_wide = work / f"_acad_wide_{post.id}.png"
        chart_left = work / f"_acad_left_{post.id}.png"
        chart_right = work / f"_acad_right_{post.id}.png"
        formula_png = work / f"_acad_formula_{post.id}.png"

        image = Image.new("RGB", (canvas_size, canvas_size), PAPER)
        draw = ImageDraw.Draw(image)
        y_cursor = 64 * scale

        # ── Шапка книжной серии ─────────────────────────────────────────
        badge = f"SCIENCE PULSE · КНИЖНАЯ СЕРИЯ · {DOMAIN_LABELS.get(post.domain, post.domain.upper())}"
        draw.text((margin, y_cursor), badge, fill=ACCENT, font=_serif_font(19 * scale, bold=True, mono=True))
        section = str((getattr(post, "meta", {}) or {}).get("section_num") or "").strip()
        if section:
            draw.text((margin + width - 150 * scale, y_cursor), f"§ {section}", fill=INK,
                      font=_serif_font(20 * scale, bold=True, mono=True))
        y_cursor += 32 * scale
        draw.line((margin, y_cursor, margin + width, y_cursor), fill=RULE, width=scale)
        y_cursor += 16 * scale

        # ── Эпоха и учёный («Тройная связь времени») ─────────────────────
        meta = getattr(post, "meta", {}) or {}
        era_line = " · ".join(part for part in (str(meta.get("era", "")).upper(), str(meta.get("scientist", ""))) if part)
        if era_line:
            draw.text((margin, y_cursor), era_line[:120], fill=MUTED, font=_serif_font(21 * scale, italic=True))
            y_cursor += 34 * scale

        # ── Заголовок и лид ────────────────────────────────────────────
        title_font, title_lines = _fit(draw, post.plain_title, width, 46 * scale, 26 * scale, 3, bold=True)
        title_step = int(getattr(title_font, "size", 46 * scale) * 1.16)
        for line in title_lines[:3]:
            draw.text((margin, y_cursor), line, fill=INK, font=title_font)
            y_cursor += title_step
        y_cursor += 10 * scale

        from .text import lead_sentence

        lead_raw = post.plain_hook or lead_sentence(post.body, 190)
        if lead_raw:
            lead_font, lead_lines = _fit(draw, lead_raw, width, 24 * scale, 18 * scale, 3, italic=True)
            lead_step = int(getattr(lead_font, "size", 24 * scale) * 1.32)
            for line in lead_lines[:3]:
                draw.text((margin, y_cursor), line, fill=MUTED, font=lead_font)
                y_cursor += lead_step
            y_cursor += 14 * scale

        # ── Визуальный блок (архетип чертежа) ───────────────────────────
        if visual == "diptych_insar":
            caption_left, caption_right = _chart_diptych(post, chart_left, chart_right)
            panel_w = (width - 24 * scale) // 2
            panel_h = 330 * scale
            left_bottom = _paste_fitted(image, chart_left, y_cursor, margin + panel_w // 2, panel_w, panel_h)
            right_bottom = _paste_fitted(image, chart_right, y_cursor,
                                         margin + panel_w + 24 * scale + panel_w // 2, panel_w, panel_h)
            caption_y = max(left_bottom, right_bottom) + 8 * scale
            caption_font = _serif_font(16 * scale, mono=True)
            draw.text((margin, caption_y), caption_left[:52], fill=MUTED, font=caption_font)
            draw.text((margin + panel_w + 24 * scale, caption_y), caption_right[:52], fill=MUTED, font=caption_font)
            y_cursor = caption_y + 34 * scale
        elif visual == "timeline_evolution":
            _chart_timeline(post, chart_wide)
            y_cursor = _paste_fitted(image, chart_wide, y_cursor, center_x, width, 340 * scale) + 18 * scale
        elif visual == "cheatsheet_table":
            draw.text((margin, y_cursor), "СВОДНАЯ ТАБЛИЦА · ШПАРГАЛКА", fill=ACCENT,
                      font=_serif_font(17 * scale, bold=True, mono=True))
            y_cursor += 30 * scale
            y_cursor = _draw_table(image, draw, post, y_cursor, margin, width, scale)
        elif visual == "code_booktabs":
            y_cursor = _draw_code_listing(image, draw, post, y_cursor, margin, width, scale)
        elif visual == "logic_proof":
            y_cursor = _draw_logic_proof(image, draw, post, y_cursor, margin, width, scale)
        elif visual == "number_sequence":
            y_cursor = _draw_number_sequence(image, draw, post, y_cursor, margin, width, scale)
        elif visual == "matrix_grid":
            y_cursor = _draw_matrix_grid(image, draw, post, y_cursor, margin, width, scale)
        elif visual == "prob_tree":
            y_cursor = _draw_prob_tree(image, draw, post, y_cursor, margin, width, scale)
        else:  # standard_plot
            _chart_standard(post, chart_wide)
            y_cursor = _paste_fitted(image, chart_wide, y_cursor, center_x, width, 360 * scale) + 16 * scale

        # ── Блок формулы (Computer Modern) ──────────────────────────────
        formula = (getattr(post, "formula_latex", "") or getattr(post, "formula_plain", "") or "").strip()
        if formula and visual != "code_booktabs":
            draw.line((margin, y_cursor, margin + width, y_cursor), fill=RULE, width=scale)
            y_cursor += 12 * scale
            if render_formula_png(formula, formula_png, color=INK, fontset="cm"):
                y_cursor = _paste_fitted(image, formula_png, y_cursor, center_x, width - 40 * scale, 110 * scale)
            else:
                from .text import formula_to_unicode

                draw.text((margin, y_cursor), formula_to_unicode(formula, 120), fill=INK,
                          font=_serif_font(22 * scale))
                y_cursor += 30 * scale
            y_cursor += 12 * scale
            draw.line((margin, y_cursor, margin + width, y_cursor), fill=RULE, width=scale)
            y_cursor += 16 * scale

        # ── Экспликация «где: …» под формулой ───────────────────────────
        where = str(meta.get("formula_vars") or "").strip()
        if not where:
            used = [str(symbol) for symbol in (meta.get("constants_used") or [])]
            if used:
                where = "где: " + ", ".join(used[:5])
        if where:
            where_font, where_lines = _fit(draw, where, width, 18 * scale, 13 * scale, 2, italic=True)
            for line in where_lines[:2]:
                draw.text((margin, y_cursor), line, fill=MUTED, font=where_font)
                y_cursor += int(getattr(where_font, "size", 18 * scale) * 1.3)
            y_cursor += 8 * scale

        # ── Тройная связь времени: где работает сегодня ─────────────────
        application = str(meta.get("modern_application") or "").strip()
        if application:
            app_font, app_lines = _fit(draw, f"ГДЕ РАБОТАЕТ СЕГОДНЯ: {application}", width, 19 * scale, 15 * scale, 2)
            for line in app_lines[:2]:
                draw.text((margin, y_cursor), line, fill=ACCENT, font=app_font)
                y_cursor += int(getattr(app_font, "size", 19 * scale) * 1.3)
            y_cursor += 8 * scale

        # ── Подвал ─────────────────────────────────────────────────────
        footer_y = canvas_size - 78 * scale
        _draw_mini_dag(draw, post, margin, footer_y - 42 * scale, scale)
        draw.line((margin, footer_y, margin + width, footer_y), fill=RULE, width=scale)
        source = (getattr(post, "source_name", "") or "Science Pulse")[:60]
        draw.text((margin, footer_y + 14 * scale), source, fill=MUTED, font=_serif_font(16 * scale, mono=True))
        draw.text((margin + width - 430 * scale, footer_y + 14 * scale),
                  "детерминированный рендер · без LLM", fill=MUTED, font=_serif_font(16 * scale, mono=True))
        # ── QR-код ссылки на разбор (правый нижний угол) ────────────────
        import os

        site_url = (os.getenv("SP_SITE_BASE_URL") or str(meta.get("site_url") or "")).rstrip("/")
        link = f"{site_url}/post/{post.id}.html" if site_url else f"post/{post.id}.html"
        qr = qr_image(link, 68 * scale)
        if qr is not None:
            image.paste(qr, (margin + width - 72 * scale, footer_y - 84 * scale))

        final = image.resize((size, size), Image.Resampling.LANCZOS)
        final.save(out_path, format="PNG", optimize=True)
        data = out_path.read_bytes()
        return CardArtifact(path=str(out_path), data=data, width=size, height=size)
    except Exception as exc:
        LOGGER.warning("Книжная карточка не собралась (%s)", exc)
        return None
    finally:
        for temp in (work / f"_acad_wide_{post.id}.png", work / f"_acad_left_{post.id}.png",
                     work / f"_acad_right_{post.id}.png", work / f"_acad_formula_{post.id}.png"):
            try:
                temp.unlink()
            except OSError:
                pass
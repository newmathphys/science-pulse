from __future__ import annotations

import io
import logging
import math
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFont

from .abtest import variant_style
from .models import CardArtifact, Post
from .plotting import evaluate_curve
from .text import formula_to_unicode, lead_sentence, smart_sentence_truncate, truncate

LOGGER = logging.getLogger(__name__)

THEMES: Dict[str, Dict[str, Any]] = {
    "math": {
        "bg": (7, 9, 15),
        "panel": (16, 22, 34),
        "accent": (0, 245, 212),
        "secondary": (123, 44, 191),
        "text": (236, 242, 255),
        "muted": (138, 148, 166),
        "label": "MATHEMATICS // SYMPY",
    },
    "physics": {
        "bg": (9, 6, 14),
        "panel": (24, 16, 34),
        "accent": (255, 0, 127),
        "secondary": (0, 187, 249),
        "text": (245, 240, 255),
        "muted": (160, 150, 175),
        "label": "PHYSICS // COMPLEX FIELD",
    },
    "cs": {
        "bg": (8, 10, 12),
        "panel": (20, 24, 28),
        "accent": (254, 228, 64),
        "secondary": (0, 245, 212),
        "text": (240, 245, 250),
        "muted": (150, 160, 170),
        "label": "COMPUTER SCIENCE // AST",
    },
}

try:
    import matplotlib

    MPL_TTF_DIR = str(Path(matplotlib.get_data_path()) / "fonts" / "ttf")
except Exception:  # pragma: no cover
    MPL_TTF_DIR = ""

FONT_DIRS = [
    MPL_TTF_DIR,
    "/usr/share/fonts/TTF",
    "/usr/share/fonts/truetype/dejavu",
    "/usr/share/fonts/truetype/liberation",
    "/usr/share/fonts/opentype/noto",
    "/usr/local/share/fonts",
    str(Path.home() / ".fonts"),
    "",
]


def _font_path(names: Sequence[str]) -> Optional[str]:
    for directory in FONT_DIRS:
        for name in names:
            candidate = os.path.join(directory, name) if directory else name
            if os.path.exists(candidate):
                return candidate
    return None


def load_font(size: int, bold: bool = False, mono: bool = False) -> ImageFont.FreeTypeFont:
    if mono:
        names = ["DejaVuSansMono.ttf", "LiberationMono-Regular.ttf", "NotoSansMono-Regular.ttf"]
    elif bold:
        names = ["DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf", "NotoSans-Bold.ttf"]
    else:
        names = ["DejaVuSans.ttf", "LiberationSans-Regular.ttf", "NotoSans-Regular.ttf"]
    path = _font_path(names)
    if path:
        try:
            return ImageFont.truetype(path, size)
        except Exception as exc:
            LOGGER.debug("Не удалось загрузить шрифт %s: %s", path, exc)
    try:
        return ImageFont.load_default(size=size)  # type: ignore[call-arg]
    except TypeError:
        return ImageFont.load_default()


def _split_long_word(draw: ImageDraw.ImageDraw, word: str, font: ImageFont.ImageFont, max_width: int) -> List[str]:
    chunks: List[str] = []
    current = ""
    for char in word:
        candidate = current + char
        if current and draw.textlength(candidate, font=font) > max_width:
            chunks.append(current)
            current = char
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> List[str]:
    raw_words = (text or "").split()
    if not raw_words:
        return []
    words: List[str] = []
    for word in raw_words:
        if draw.textlength(word, font=font) > max_width:
            words.extend(_split_long_word(draw, word, font, max_width))
        else:
            words.append(word)
    lines: List[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def fit_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    max_height: int,
    start: int,
    bold: bool = True,
    min_size: int = 18,
    max_lines: int | None = None,
) -> tuple[ImageFont.ImageFont, List[str]]:
    size = start
    while size >= min_size:
        font = load_font(size, bold=bold)
        lines = wrap_text(draw, text, font, max_width)
        line_height = int(size * 1.16)
        if (max_lines is None or len(lines) <= max_lines) and len(lines) * line_height <= max_height:
            return font, lines
        size -= 2
    font = load_font(min_size, bold=bold)
    return font, wrap_text(draw, text, font, max_width)


def _draw_grid(draw: ImageDraw.ImageDraw, rect: tuple[int, int, int, int], color: tuple[int, int, int], width: int) -> None:
    left, top, right, bottom = rect
    for index in range(1, 7):
        x = left + (right - left) * index / 7
        draw.line([(x, top), (x, bottom)], fill=color, width=width)
    for index in range(1, 5):
        y = top + (bottom - top) * index / 5
        draw.line([(left, y), (right, y)], fill=color, width=width)


def _curve_points(
    x_values: Sequence[float],
    y_values: Sequence[float],
    rect: tuple[int, int, int, int],
    x_min: float,
    x_max: float,
    y_min: float,
    y_max: float,
) -> List[Tuple[float, float]]:
    left, top, right, bottom = rect
    span_x = max(1e-9, x_max - x_min)
    span_y = max(1e-9, y_max - y_min)
    points: List[Tuple[float, float]] = []
    for x, y in zip(x_values, y_values):
        px = left + ((x - x_min) / span_x) * (right - left)
        py = bottom - ((y - y_min) / span_y) * (bottom - top)
        points.append((px, py))
    return points


def _mix(color_a: tuple[int, int, int], color_b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    return tuple(int(color_a[index] * (1 - t) + color_b[index] * t) for index in range(3))


def extract_sequence(post: Post) -> List[int]:
    stored = (post.meta or {}).get("sequence")
    if isinstance(stored, list) and len(stored) >= 6:
        try:
            return [int(value) for value in stored[:24]]
        except (TypeError, ValueError):
            pass
    text = f"{post.body or ''} {post.formula_plain or ''} {post.formula_latex or ''}"
    match = re.search(r"(-?\d+(?:\s*,\s*-?\d+){5,20})", text)
    if not match:
        return []
    values: List[int] = []
    for part in match.group(1).split(","):
        try:
            value = int(part.strip())
        except ValueError:
            continue
        if abs(value) < 10**9:
            values.append(value)
    return values if len(values) >= 6 else []


def _draw_sequence_plot(
    draw: ImageDraw.ImageDraw,
    values: List[int],
    rect: tuple[int, int, int, int],
    theme: Dict[str, Any],
    scale: float,
) -> None:
    left, top, right, bottom = rect
    y_min = min(0, min(values))
    y_max = max(0, max(values))
    span = max(1, y_max - y_min)
    y_min -= int(span * 0.12)
    y_max += int(span * 0.22)
    span = max(1, y_max - y_min)
    baseline = bottom - ((0 - y_min) / span) * (bottom - top)
    step = (right - left) / max(1, len(values) - 1) if len(values) > 1 else 0
    font = load_font(max(11, int(16 * scale)), mono=True)
    points = []
    for index, value in enumerate(values):
        px = left + int(20 * scale) + index * step * 0.92
        py = bottom - ((value - y_min) / span) * (bottom - top)
        points.append((px, py))
        draw.line([(px, baseline), (px, py)], fill=_mix(theme["accent"], theme["panel"], 0.55), width=max(2, int(4 * scale)))
        radius = max(3, int(5 * scale))
        draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=(255, 255, 255), outline=theme["accent"], width=max(1, int(2 * scale)))
        if index < 12:
            draw.text((px - int(8 * scale), py - int(24 * scale)), str(value), fill=theme["text"], font=font)
    if len(points) > 1:
        draw.line(points, fill=_mix(theme["accent"], theme["panel"], 0.65), width=max(1, int(2 * scale)))
    draw.text((left + int(10 * scale), top + int(8 * scale)), "a(n)", fill=theme["muted"], font=font)
    draw.text((left + int(10 * scale), bottom - int(24 * scale)), "n = 1 …", fill=theme["muted"], font=font)


def _draw_theorem_sheet(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    post: Post,
    rect: tuple[int, int, int, int],
    theme: Dict[str, Any],
    scale: float,
) -> None:
    left, top, right, bottom = rect
    font_label = load_font(max(12, int(18 * scale)), bold=True, mono=True)
    font_text = load_font(max(13, int(21 * scale)), mono=False)
    draw.text((left + int(18 * scale), top + int(14 * scale)), "НАУЧНЫЙ ПАСПОРТ / THEOREM SHEET", fill=theme["accent"], font=font_label)

    formula = post.formula_latex or post.formula_plain
    if formula:
        formula_image = _render_formula_image(
            formula,
            right - left - int(50 * scale),
            int(190 * scale),
            theme["accent"],
        )
        if formula_image:
            image.paste(
                formula_image,
                (
                    left + (right - left - formula_image.width) // 2,
                    top + int(62 * scale),
                ),
                formula_image,
            )

    rows = [
        ("Дисциплина", post.label),
        ("Источник", post.source_name or "Science Pulse"),
        ("Тип узла", "закон / теорема / константа"),
    ]
    meta = post.meta or {}
    if meta.get("codata_key"):
        rows.append(("CODATA", f"{meta.get('codata_key')} = {meta.get('codata_value')} {meta.get('codata_unit')}"))
    y = top + int(270 * scale)
    for label, value in rows:
        draw.text((left + int(18 * scale), y), f"{label}:", fill=theme["muted"], font=font_label)
        _, lines = fit_font(draw, str(value), right - left - int(170 * scale), int(48 * scale), int(21 * scale), bold=False, min_size=int(14 * scale), max_lines=2)
        for line in lines:
            draw.text((left + int(150 * scale), y), line, fill=theme["text"], font=font_text)
            y += int(25 * scale)
        y += int(6 * scale)


def _draw_plot(
    draw: ImageDraw.ImageDraw,
    post: Post,
    rect: tuple[int, int, int, int],
    theme: Dict[str, Any],
    scale: float,
) -> bool:
    expression = str(post.meta.get("plot_expr") or post.formula_plain or "").strip()
    if not expression or not re.search(r"\b[xt]\b", expression):
        return False
    try:
        curve = evaluate_curve(expression, x_min=-6.0, x_max=6.0, points=520)
        x_values = curve["x"]
        re_values = curve["re_y"]
        im_values = curve["im_y"]
    except Exception:
        return False

    finite = [float(value) for value in re_values if math.isfinite(float(value))]
    if not finite:
        return False
    y_min = min(finite)
    y_max = max(finite)
    if math.isclose(y_min, y_max):
        y_min -= 1.0
        y_max += 1.0
    padding = (y_max - y_min) * 0.12
    y_min -= padding
    y_max += padding

    points = _curve_points(x_values, re_values, rect, -6.0, 6.0, y_min, y_max)
    baseline = rect[3] - ((0.0 - y_min) / max(1e-9, y_max - y_min)) * (rect[3] - rect[1])
    baseline = max(rect[1] + 1, min(rect[3] - 1, baseline))

    if len(points) > 1:
        fill_color = _mix(theme["accent"], theme["panel"], 0.82)
        polygon = points + [(points[-1][0], baseline), (points[0][0], baseline)]
        draw.polygon(polygon, fill=fill_color)

        draw.line(points, fill=theme["secondary"], width=max(2, int(13 * scale)), joint="curve")
        draw.line(points, fill=theme["accent"], width=max(1, int(5 * scale)), joint="curve")

        derivative = curve.get("der_y") if "curve" in locals() else None
        if derivative is not None:
            max_derivative = max((abs(float(value)) for value in derivative), default=0.0)
            max_main = max((abs(float(value)) for value in re_values), default=0.0)
            if max_derivative > 1e-6 and max_main > 1e-6:
                factor = (max_main / max_derivative) * 0.65
                scaled = [float(value) * factor for value in derivative]
                derivative_points = _curve_points(x_values, scaled, rect, -6.0, 6.0, y_min, y_max)
                for index in range(0, len(derivative_points) - 1, 6):
                    draw.line(derivative_points[index : index + 4], fill=theme["secondary"], width=max(1, int(3 * scale)))

    if im_values is not None and max(abs(float(v)) for v in im_values) > 1e-3:
        im_points = _curve_points(x_values, im_values, rect, -6.0, 6.0, y_min, y_max)
        for index in range(0, len(im_points) - 1, 8):
            draw.line(im_points[index : index + 3], fill=theme["secondary"], width=max(1, int(2 * scale)))

    point_x, point_y = curve["poi"] if "curve" in locals() else (0.0, 0.0)
    px = rect[0] + ((point_x + 6.0) / 12.0) * (rect[2] - rect[0])
    py = rect[3] - ((point_y - y_min) / max(1e-9, y_max - y_min)) * (rect[3] - rect[1])
    radius = max(3, int(6 * scale))
    draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=(255, 255, 255))
    draw.line([(px - radius * 2, py), (px + radius * 2, py)], fill=theme["accent"], width=max(1, int(2 * scale)))
    draw.line([(px, py - radius * 2), (px, py + radius * 2)], fill=theme["accent"], width=max(1, int(2 * scale)))

    axis_font = load_font(max(12, int(17 * scale)), mono=True)
    draw.text((rect[0] + int(8 * scale), rect[1] + int(6 * scale)), "y", fill=theme["muted"], font=axis_font)
    draw.text((rect[2] - int(24 * scale), rect[3] - int(26 * scale)), "x", fill=theme["muted"], font=axis_font)
    draw.text((px + int(10 * scale), py - int(28 * scale)), "MAX", fill=theme["text"], font=axis_font)
    return True


def _draw_code_window(
    draw: ImageDraw.ImageDraw,
    post: Post,
    code: str,
    rect: tuple[int, int, int, int],
    theme: Dict[str, Any],
    scale: float,
) -> None:
    left, top, right, bottom = rect
    header_h = max(28, int(44 * scale))
    draw.rounded_rectangle(
        (left, top, right, top + header_h),
        radius=max(8, int(12 * scale)),
        fill=_mix(theme["panel"], theme["bg"], 0.35),
    )
    dot_radius = max(3, int(5 * scale))
    for index, color in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        cx = left + int(26 * scale) + index * int(22 * scale)
        cy = top + header_h // 2
        draw.ellipse((cx - dot_radius, cy - dot_radius, cx + dot_radius, cy + dot_radius), fill=color)
    title_font = load_font(max(12, int(17 * scale)), mono=True)
    draw.text((left + int(100 * scale), top + int(11 * scale)), "main.py  ·  verified snippet", fill=theme["muted"], font=title_font)

    code_top = top + header_h + int(16 * scale)
    font = load_font(max(13, int(19 * scale)), mono=True)
    line_height = int(font.size * 1.38) if hasattr(font, "size") else int(24 * scale)
    max_lines = max(1, (bottom - code_top - int(56 * scale)) // line_height)
    keywords = {
        "def", "return", "for", "while", "if", "elif", "else", "class",
        "import", "from", "in", "as", "with", "try", "except", "lambda",
        "yield", "print", "True", "False", "None", "not", "and", "or",
    }
    token_re = re.compile(r"(#.*$|\".*?\"|'.*?'|\b\w+\b|\s+|.)")
    x0 = left + int(66 * scale)
    max_text_width = right - x0 - int(18 * scale)
    for line_index, raw in enumerate((code or "").splitlines()[:max_lines], start=1):
        y = code_top + (line_index - 1) * line_height
        draw.text((left + int(16 * scale), y), f"{line_index:02d}", fill=theme["muted"], font=font)
        x = x0
        for token in token_re.findall(raw):
            if x >= x0 + max_text_width:
                break
            if token.startswith("#"):
                color = theme["muted"]
            elif token.startswith(("'", '"')):
                color = theme["secondary"]
            elif token.strip() in keywords:
                color = theme["accent"]
            elif token.isdigit():
                color = theme["text"]
            else:
                color = theme["text"]
            draw.text((x, y), token, fill=color, font=font)
            x += draw.textlength(token, font=font)

    complexity = re.search(r"O\([^)]{1,24}\)", post.formula_plain or post.formula_latex or code or "")
    badge = f"TIME: {complexity.group(0) if complexity else 'O(N)'}"
    badge_font = load_font(max(12, int(16 * scale)), mono=True)
    badge_w = int(draw.textlength(badge, font=badge_font)) + int(22 * scale)
    badge_h = int(32 * scale)
    bx = right - badge_w - int(16 * scale)
    by = bottom - badge_h - int(12 * scale)
    draw.rounded_rectangle((bx, by, bx + badge_w, by + badge_h), radius=int(8 * scale), fill=_mix(theme["accent"], theme["panel"], 0.82), outline=theme["accent"], width=max(1, int(2 * scale)))
    draw.text((bx + int(11 * scale), by + int(7 * scale)), badge, fill=theme["accent"], font=badge_font)


def _render_formula_image(formula: str, width: int, height: int, color: tuple[int, int, int]) -> Optional[Image.Image]:
    if not formula:
        return None
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        matplotlib.rcParams["mathtext.fontset"] = "stixsans"
        fig = plt.figure(figsize=(width / 100, height / 100), dpi=100)
        fig.patch.set_alpha(0)
        text = formula if formula.startswith("$") else f"${formula}$"
        font_size = 64 if len(formula) < 30 else (48 if len(formula) < 60 else 34)
        fig.text(0.5, 0.5, text, ha="center", va="center", color=tuple(c / 255 for c in color), fontsize=font_size)
        buffer = io.BytesIO()
        fig.savefig(buffer, format="png", transparent=True, bbox_inches="tight", pad_inches=0.05)
        plt.close(fig)
        buffer.seek(0)
        image = Image.open(buffer).convert("RGBA")
        if image.width > width or image.height > height:
            ratio = min(width / max(1, image.width), height / max(1, image.height))
            image = image.resize(
                (max(1, int(image.width * ratio)), max(1, int(image.height * ratio))),
                Image.Resampling.LANCZOS,
            )
        return image
    except Exception:
        return None


def _draw_code(
    draw: ImageDraw.ImageDraw,
    code: str,
    rect: tuple[int, int, int, int],
    theme: Dict[str, Any],
    scale: float,
) -> None:
    left, top, right, bottom = rect
    font = load_font(max(14, int(20 * scale)), mono=True)
    line_height = int(font.size * 1.35) if hasattr(font, "size") else int(24 * scale)
    max_lines = max(1, (bottom - top) // line_height)
    lines: List[str] = []
    for raw in (code or "").splitlines():
        if not raw.strip():
            continue
        while len(raw) > 62:
            lines.append(raw[:62])
            raw = raw[62:]
        lines.append(raw)
        if len(lines) >= max_lines:
            break
    y = top
    for line in lines[:max_lines]:
        color = theme["accent"] if line.lstrip().startswith(("#", "//")) else theme["text"]
        draw.text((left, y), truncate(line, 62), fill=color, font=font)
        y += line_height


def render_card(
    post: Post,
    out_path: str | Path | None = None,
    size: int = 1080,
    ssaa: int = 2,
    theme_name: str = "neon",
    variant: str | None = None,
    engine: str = "auto",
) -> CardArtifact:
    target = Path(out_path) if out_path else Path(f"card_{post.id}.png")
    # Книжный движок (академическая серия): явно или по meta["visual_type"]/["simulation"].
    if engine in ("auto", "academic", "book"):
        want_academic = (
            engine in ("academic", "book")
            or bool(getattr(post, "meta", {}).get("visual_type"))
            or bool(getattr(post, "meta", {}).get("simulation"))
        )
        if want_academic:
            try:
                from .cards_academic import render_academic_card

                academic = render_academic_card(post, target, size=size)
            except Exception as exc:  # pragma: no cover - защитный контур
                LOGGER.warning("Книжный движок недоступен (%s), fallback", exc)
                academic = None
            if academic:
                return academic
    if engine in ("auto", "typst"):
        try:
            from .cards3b1b import render_studio_card

            studio = render_studio_card(post, target, size=size)
        except Exception as exc:  # pragma: no cover - защитный контур
            LOGGER.warning("Студийный движок недоступен (%s), fallback на Pillow", exc)
            studio = None
        if studio:
            return studio

    theme = dict(THEMES.get(post.domain, THEMES["math"]))
    style = variant_style(variant)
    scale = 1.0
    canvas_size = max(size, 320) * max(1, ssaa)
    image = Image.new("RGB", (canvas_size, canvas_size), theme["bg"])
    draw = ImageDraw.Draw(image)

    margin = int(canvas_size * 0.062)
    width = canvas_size - 2 * margin
    badge_font = load_font(max(16, int(20 * scale * ssaa)), bold=True, mono=True)
    draw.text((margin, int(canvas_size * 0.045)), f"● SCIENCE PULSE // {theme['label']}", fill=theme["accent"], font=badge_font)

    # Заголовок
    title_start = int(canvas_size * 0.095)
    title_font, title_lines = fit_font(
        draw,
        post.plain_title,
        width,
        int(canvas_size * 0.17 * style["title_scale"]),
        int(54 * ssaa),
        bold=True,
        min_size=int(24 * ssaa),
        max_lines=int(style["title_max_lines"]),
    )
    y = title_start
    line_height = int(title_font.size * 1.14) if hasattr(title_font, "size") else int(60 * ssaa)
    for line in title_lines[: int(style["title_max_lines"])]:
        draw.text((margin, y), line, fill=theme["text"], font=title_font)
        y += line_height

    # Крючок
    hook = post.plain_hook
    if not hook or hook.lower() == post.plain_title.lower() or (post.body or "").startswith(post.hook or ""):
        hook = lead_sentence(post.body, 190)
    if hook and style["show_hook"]:
        hook_font, hook_lines = fit_font(
            draw,
            hook,
            width,
            int(canvas_size * 0.075),
            int(27 * ssaa),
            bold=False,
            min_size=int(16 * ssaa),
            max_lines=2,
        )
        y += int(canvas_size * 0.012)
        for line in hook_lines[:2]:
            draw.text((margin, y), line, fill=theme["muted"], font=hook_font)
            y += int(hook_font.size * 1.3) if hasattr(hook_font, "size") else int(34 * ssaa)

    plot_top = max(y + int(canvas_size * 0.02), int(canvas_size * 0.34))
    plot_bottom = int(canvas_size * 0.68)
    plot_rect = (margin, plot_top, margin + width, plot_bottom)
    draw.rounded_rectangle(
        (plot_rect[0] - int(12 * ssaa), plot_rect[1] - int(12 * ssaa), plot_rect[2] + int(12 * ssaa), plot_rect[3] + int(12 * ssaa)),
        radius=int(18 * ssaa),
        fill=theme["panel"],
        outline=(34, 42, 58),
        width=max(1, int(2 * ssaa)),
    )
    sequence = extract_sequence(post)
    mode = "theorem"
    if post.code and post.domain == "cs":
        mode = "code"
        _draw_code_window(draw, post, post.code, plot_rect, theme, ssaa)
    elif sequence:
        mode = "sequence"
        _draw_grid(draw, plot_rect, (26, 32, 48), max(1, int(1.5 * ssaa)))
        _draw_sequence_plot(draw, sequence, plot_rect, theme, ssaa)
    else:
        _draw_grid(draw, plot_rect, (26, 32, 48), max(1, int(1.5 * ssaa)))
        plotted = _draw_plot(draw, post, plot_rect, theme, ssaa)
        if plotted:
            mode = "analytic"
        else:
            _draw_theorem_sheet(image, draw, post, plot_rect, theme, ssaa)

    # Блок формулы
    box_top = int(canvas_size * 0.72)
    box_bottom = int(canvas_size * 0.885)
    draw.rounded_rectangle(
        (margin, box_top, margin + width, box_bottom),
        radius=int(18 * ssaa),
        fill=theme["panel"],
        outline=theme["accent"],
        width=max(1, int(3 * ssaa)),
    )
    formula = "" if mode == "theorem" else (post.formula_latex or post.formula_plain)
    if formula:
        formula_image = _render_formula_image(
            formula,
            width - int(36 * ssaa),
            box_bottom - box_top - int(24 * ssaa),
            theme["accent"],
        )
        if formula_image:
            x = margin + (width - formula_image.width) // 2
            y = box_top + (box_bottom - box_top - formula_image.height) // 2
            image.paste(formula_image, (x, y), formula_image)
        else:
            formula_font, formula_lines = fit_font(
                draw,
                formula_to_unicode(formula, 140),
                width - int(36 * ssaa),
                box_bottom - box_top - int(20 * ssaa),
                int(34 * ssaa),
                bold=False,
                min_size=int(15 * ssaa),
                max_lines=3,
            )
            y = box_top + int(18 * ssaa)
            for line in formula_lines[:3]:
                draw.text((margin + int(18 * ssaa), y), line, fill=theme["accent"], font=formula_font)
                y += int(formula_font.size * 1.25) if hasattr(formula_font, "size") else int(36 * ssaa)
    else:
        body_font, body_lines = fit_font(
            draw,
            lead_sentence(post.body, 220),
            width - int(36 * ssaa),
            box_bottom - box_top - int(20 * ssaa),
            int(26 * ssaa),
            bold=False,
            min_size=int(14 * ssaa),
            max_lines=4,
        )
        y = box_top + int(18 * ssaa)
        for line in body_lines[:4]:
            draw.text((margin + int(18 * ssaa), y), line, fill=theme["text"], font=body_font)
            y += int(body_font.size * 1.28) if hasattr(body_font, "size") else int(30 * ssaa)

    # Подвал
    footer_font = load_font(max(12, int(17 * ssaa)), mono=True)
    source = truncate(post.source_name or "Science Pulse", 58)
    footer = f"{source}  ·  {post.label}"
    draw.text((margin, int(canvas_size * 0.925)), footer, fill=theme["muted"], font=footer_font)
    draw.text(
        (margin, int(canvas_size * 0.955)),
        "verified sources · deterministic render · no LLM",
        fill=theme["muted"],
        font=footer_font,
    )

    final = image.resize((size, size), Image.Resampling.LANCZOS)
    output = Path(out_path) if out_path else Path(f"card_{post.id}.png")
    output.parent.mkdir(parents=True, exist_ok=True)
    final.save(output, format="PNG", optimize=True)
    data = output.read_bytes()
    return CardArtifact(path=str(output), data=data, width=size, height=size)


def render_post_card_studio(post: Post, output_path: str) -> str:
    """Совместимый вход для внешних вызовов: студийная карточка 1080×1080."""
    return render_card(post, out_path=output_path).path

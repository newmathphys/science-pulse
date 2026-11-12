"""Академический book-фильм: ожившая страница учебника под голос лектора.

Отдельный видео-движок рядом с тёмным 3D ``moku_film``. Стиль:

* бумага ``#FAF8F4``, тушь ``#111827``, поля и линейки книги;
* DejaVu Serif для текста, Computer Modern для формул;
* верх — колонтитул, заголовок и теорема/формула;
* центр — только реальные данные поста: ряд a(n), f(x)/f'(x), листинг кода
  или лаборатория ``simulate.py``; никаких декоративных волн;
* низ — текущая строка лекции, слова подсвечиваются по таймкодам голоса;
* форматы ``1:1`` 1080×1080 и ``9:16`` 1080×1920.
"""
from __future__ import annotations

import logging
import math
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image, ImageDraw

from .cards import extract_sequence
from .cards_academic import (
    ACCENT,
    INK,
    MUTED,
    PAPER,
    RULE,
    _fit,
    _serif_font,
    _wrap,
    render_formula_png,
)
from .models import Post
from .plotting import evaluate_curve
from .voice import VoiceArtifact, build_film_blocks, build_lecture_script, film_voice_for_post, verified_example, voice_for_post

LOGGER = logging.getLogger(__name__)

FPS = 24
SIZE = 1080
MAX_FRAMES = 1800
MIN_SECONDS = 3.0
ACT_ROMAN = ("I", "II", "III", "IV", "V")
SCENE_NAMES = ("Паспорт открытия", "Живой чертёж", "Формула и величины", "Вычислительная проверка", "Применение и мост")


def book_film_available() -> bool:
    return bool(shutil.which("ffmpeg"))


def book_film_settings(config: Any = None, aspect: Optional[str] = None) -> Dict[str, Any]:
    raw = dict((getattr(config, "raw", {}) or {}).get("book_film") or {}) if config else {}
    # Единый стандарт: только 1080×1080, без вертикальных вариантов.
    width = height = int(raw.get("size", SIZE))
    return {
        "aspect": "1:1",
        "width": width,
        "height": height,
        "fps": int(raw.get("fps", FPS)),
        "max_frames": int(raw.get("max_frames", MAX_FRAMES)),
    }


def _section(post: Post) -> str:
    meta = getattr(post, "meta", {}) or {}
    section = str(meta.get("section_num") or "").strip()
    return f"§ {section}" if section else "§ —"


def _era(post: Post) -> str:
    meta = getattr(post, "meta", {}) or {}
    return str(meta.get("era") or "").split("•")[0].strip()


def _approx_words(text: str, duration: float) -> List[Tuple[float, float, str]]:
    tokens = [token for token in (text or "").split() if token]
    if not tokens:
        return []
    total = sum(max(1, len(token)) for token in tokens)
    cursor = 0.0
    words: List[Tuple[float, float, str]] = []
    for token in tokens:
        span = max(0.08, duration * max(1, len(token)) / max(1, total))
        words.append((cursor, min(duration, cursor + span), token))
        cursor += span
    return words


def _draw_word_line(
    draw: ImageDraw.ImageDraw,
    words: Sequence[Tuple[float, float, str]],
    time_s: float,
    x: int,
    y: int,
    width: int,
    font: Any,
    line_height: int,
    max_lines: int = 3,
) -> int:
    """Рисует слова с подсветкой: прошлое — тушь, текущее — акцент, будущее — серое."""
    if not words:
        return y
    current = 0
    for index, (start, end, _token) in enumerate(words):
        if time_s >= start:
            current = index
    start = current
    while start > 0:
        previous = str(words[start - 1][2]).strip()
        if previous.endswith((".", "!", "?", ":")):
            break
        start -= 1
    window = list(words[start: start + 42])
    cursor_x = x
    line = 0
    for start, end, token in window:
        token_width = draw.textlength(token, font=font)
        if cursor_x + token_width > x + width and cursor_x > x:
            cursor_x = x
            line += 1
            if line >= max_lines:
                break
        if end <= time_s:
            color = INK
        elif start <= time_s <= end:
            color = ACCENT
        else:
            color = MUTED
        draw.text((cursor_x, y + line * line_height), token, fill=color, font=font)
        cursor_x += token_width + draw.textlength(" ", font=font)
    return y + max_lines * line_height


def _draw_stem_plot(draw: ImageDraw.ImageDraw, values: Sequence[int], box: Tuple[int, int, int, int], scale: float, progress: float = 1.0) -> None:
    left, top, right, bottom = box
    if not values:
        return
    y_min = min(0, min(values))
    y_max = max(0, max(values))
    span = max(1, y_max - y_min)
    baseline = bottom - ((0 - y_min) / span) * (bottom - top)
    step = (right - left) / max(1, len(values) - 1)
    font = _serif_font(max(12, int(16 * scale)))
    visible = max(1, int(len(values[:24]) * max(0.0, min(1.0, progress))))
    for index, value in enumerate(values[:visible]):
        px = left + index * step
        py = bottom - ((value - y_min) / span) * (bottom - top)
        draw.line([(px, baseline), (px, py)], fill=RULE, width=max(1, int(2 * scale)))
        radius = max(2, int(4 * scale))
        draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=INK)
        if index < 10:
            draw.text((px - int(6 * scale), py - int(22 * scale)), str(value), fill=INK, font=font)
    draw.text((left, top), "a(n)", fill=MUTED, font=font)
    draw.text((left, bottom - int(18 * scale)), "n = 1 …", fill=MUTED, font=font)


def _draw_curve(draw: ImageDraw.ImageDraw, curve: Dict[str, Any], box: Tuple[int, int, int, int], scale: float, progress: float = 1.0) -> None:
    left, top, right, bottom = box
    xs = curve["x"]
    ys = curve["re_y"]
    finite = [float(value) for value in ys if math.isfinite(float(value))]
    if not finite:
        return
    y_min, y_max = min(finite), max(finite)
    if math.isclose(y_min, y_max):
        y_min -= 1
        y_max += 1
    pad = (y_max - y_min) * 0.12
    y_min -= pad
    y_max += pad
    x_min, x_max = float(min(xs)), float(max(xs))

    def point(xv: float, yv: float) -> Tuple[float, float]:
        px = left + (xv - x_min) / max(1e-9, x_max - x_min) * (right - left)
        py = bottom - (yv - y_min) / max(1e-9, y_max - y_min) * (bottom - top)
        return px, py

    baseline = point(x_min, 0.0)[1]
    baseline = max(top, min(bottom, baseline))
    draw.line([(left, baseline), (right, baseline)], fill=RULE, width=max(1, int(1.5 * scale)))
    points = [point(xv, float(yv)) for xv, yv in zip(xs, ys)]
    visible = max(2, int(len(points) * max(0.0, min(1.0, progress))))
    points = points[:visible]
    draw.polygon(points + [(points[-1][0], baseline), (points[0][0], baseline)], fill=(238, 233, 223))
    draw.line(points, fill=INK, width=max(2, int(3 * scale)), joint="curve")
    derivative = curve.get("der_y")
    if derivative is not None:
        max_der = max((abs(float(value)) for value in derivative), default=0.0)
        max_main = max((abs(float(value)) for value in ys), default=0.0)
        if max_der > 1e-6 and max_main > 1e-6:
            factor = max_main / max_der * 0.6
            d_points = [point(xv, float(dv) * factor) for xv, dv in zip(xs, derivative)][:visible]
            for index in range(0, len(d_points) - 1, 4):
                draw.line(d_points[index:index + 4], fill=ACCENT, width=max(1, int(2 * scale)))
    font = _serif_font(max(12, int(16 * scale)))
    draw.text((left, top), "f(x)", fill=INK, font=font)
    draw.text((left, bottom - int(18 * scale)), "x", fill=MUTED, font=font)


def _draw_equation_parts(draw: ImageDraw.ImageDraw, box: Tuple[int, int, int, int], scale: float, formula: str) -> None:
    """Разбирает уравнение на три смысловые части со стрелками."""
    left, top, right, bottom = box
    if "Ψ" in formula or "psi" in formula.lower():
        parts = ("iħ", "∂Ψ/∂t", "ĤΨ")
    else:
        clean = (formula or "").replace("$", "")
        parts = (clean[:14] or "f(x)", "=", clean[-14:] or "const")
    width = (right - left - int(60 * scale)) // 3
    font = _serif_font(max(18, int(28 * scale)), bold=True)
    small = _serif_font(max(12, int(16 * scale)))
    y0 = top + int(40 * scale)
    y1 = bottom - int(40 * scale)
    centers = []
    for index, part in enumerate(parts):
        x0 = left + int(12 * scale) + index * (width + int(18 * scale))
        draw.rounded_rectangle(
            (x0, y0, x0 + width, y1),
            radius=int(14 * scale), fill=(240, 236, 228), outline=RULE, width=max(1, int(2 * scale)),
        )
        text = part if len(part) <= 12 else part[:11] + "…"
        tw = draw.textlength(text, font=font)
        draw.text((x0 + (width - tw) / 2, (y0 + y1) / 2 - int(18 * scale)), text, fill=INK, font=font)
        centers.append((x0 + width, x0 + width + int(18 * scale)))
    for start_x, end_x in centers[:2]:
        draw.line([(start_x + int(2 * scale), (y0 + y1) / 2), (end_x - int(2 * scale), (y0 + y1) / 2)],
                  fill=ACCENT, width=max(2, int(3 * scale)))
        draw.polygon([
            (end_x - int(2 * scale), (y0 + y1) / 2),
            (end_x - int(10 * scale), (y0 + y1) / 2 - int(5 * scale)),
            (end_x - int(10 * scale), (y0 + y1) / 2 + int(5 * scale)),
        ], fill=ACCENT)
    draw.text((left + int(12 * scale), top + int(8 * scale)), "смысловые части уравнения", fill=MUTED, font=small)


def _draw_tunneling(draw: ImageDraw.ImageDraw, box: Tuple[int, int, int, int], progress: float, scale: float) -> None:
    """Реальный опыт: туннелирование волнового пакета сквозь барьер."""
    try:
        from .simulate import tunneling_profiles

        data = tunneling_profiles(n=180, steps=120)
    except Exception:
        return
    left, top, right, bottom = box
    xs = data["x"]
    barrier = data["barrier"]
    key = "before" if progress < 0.33 else ("during" if progress < 0.66 else "after")
    values = data["psi2"][key]
    max_value = max(float(np.max(values)), 1e-9)
    mid = (top + bottom) / 2
    amp = (bottom - top) * 0.34
    def px(xv: float) -> float:
        return left + (float(xv) + 8.0) / 16.0 * (right - left)
    def py(yv: float) -> float:
        return mid - (float(yv) / max_value) * amp
    # барьер
    barrier_points = [(px(xv), py(float(bv) * max_value * 0.65)) for xv, bv in zip(xs, barrier)]
    if len(barrier_points) > 1:
        draw.line(barrier_points, fill=RULE, width=max(2, int(3 * scale)))
    points = [(px(xv), py(float(yv))) for xv, yv in zip(xs, values)]
    draw.polygon(points + [(points[-1][0], mid), (points[0][0], mid)], fill=(238, 233, 223))
    draw.line(points, fill=INK, width=max(2, int(3 * scale)), joint="curve")
    font = _serif_font(max(12, int(16 * scale)))
    draw.text((left + int(10 * scale), top + int(8 * scale)), f"|Ψ|² · {key}", fill=INK, font=font)
    draw.text((right - int(170 * scale), top + int(8 * scale)), f"T ≈ {data['T']:.2f}", fill=ACCENT, font=font)


def _draw_invariant(image: Image.Image, draw: ImageDraw.ImageDraw, formula: Optional[Image.Image],
                    box: Tuple[int, int, int, int], scale: float) -> None:
    left, top, right, bottom = box
    if formula is not None:
        image.paste(formula, (left + (right - left - formula.width) // 2,
                              top + (bottom - top - formula.height) // 2 - int(30 * scale)), formula)
    font = _serif_font(max(48, int(88 * scale)), bold=True)
    draw.text(((left + right) / 2 - int(20 * scale), bottom - int(130 * scale)), "?", fill=ACCENT, font=font)
    small = _serif_font(max(12, int(16 * scale)))
    draw.text((left + int(12 * scale), top + int(8 * scale)), "инвариант / проверка", fill=MUTED, font=small)


def _draw_wave_packet(draw: ImageDraw.ImageDraw, box: Tuple[int, int, int, int], progress: float, scale: float) -> None:
    """Реальный волновой пакет: огибающая и фаза движутся во времени."""
    left, top, right, bottom = box
    xs = np.linspace(-3.6, 3.6, 420)
    center = -2.8 + 5.6 * max(0.0, min(1.0, progress))
    packet = np.exp(-((xs - center) ** 2) / 1.0) * np.cos(6.0 * (xs - center))
    envelope = np.exp(-((xs - center) ** 2) / 1.0)
    mid = (top + bottom) / 2
    amp = (bottom - top) * 0.34
    def points(values: Any) -> List[Tuple[float, float]]:
        return [(left + (xv + 3.6) / 7.2 * (right - left), mid - float(yv) * amp) for xv, yv in zip(xs, values)]
    main = points(packet)
    draw.line(points(envelope), fill=RULE, width=max(1, int(2 * scale)))
    draw.line(points(-envelope), fill=RULE, width=max(1, int(2 * scale)))
    draw.line([(left, mid), (right, mid)], fill=RULE, width=max(1, int(1.2 * scale)))
    draw.line(main, fill=INK, width=max(2, int(3 * scale)), joint="curve")
    font = _serif_font(max(12, int(16 * scale)))
    draw.text((left, top), "Re Ψ(x,t)", fill=INK, font=font)
    draw.text((right - int(100 * scale), top), f"t/T = {progress:.2f}", fill=MUTED, font=font)


def _draw_timeline(draw: ImageDraw.ImageDraw, timeline: Sequence[Dict[str, Any]], box: Tuple[int, int, int, int], progress: float, scale: float) -> None:
    """Реальная хронология открытий из meta["timeline"]."""
    left, top, right, bottom = box
    items = [item for item in timeline if isinstance(item, dict) and item.get("year") is not None]
    if not items:
        return
    years = [float(item["year"]) for item in items]
    y_min, y_max = min(years), max(years)
    span = max(1.0, y_max - y_min)
    line_y = (top + bottom) / 2
    draw.line([(left + int(20 * scale), line_y), (right - int(20 * scale), line_y)], fill=RULE, width=max(2, int(3 * scale)))
    font = _serif_font(max(12, int(16 * scale)))
    current_year = y_min + span * max(0.0, min(1.0, progress))
    step = (right - left - int(40 * scale)) / max(1, len(items) - 1)
    for index, item in enumerate(items):
        year = float(item["year"])
        px = left + int(20 * scale) + index * step
        active = year <= current_year + span * 0.02
        radius = max(4, int(7 * scale))
        draw.ellipse([px - radius, line_y - radius, px + radius, line_y + radius], fill=ACCENT if active else PAPER, outline=ACCENT if active else RULE, width=max(1, int(2 * scale)))
        label = str(item.get("label") or "")
        year_text = f"{int(year)}" if year >= 0 else f"{abs(int(year))} до н.э."
        year_w = draw.textlength(year_text, font=font)
        label_w = draw.textlength(label[:14], font=font)
        year_x = min(px - int(8 * scale), right - year_w - int(6 * scale))
        label_x = min(px - int(8 * scale), right - label_w - int(6 * scale))
        draw.text((max(left + int(4 * scale), year_x), line_y - int(42 * scale)), year_text, fill=INK if active else MUTED, font=font)
        draw.text((max(left + int(4 * scale), label_x), line_y + int(16 * scale)), label[:14], fill=INK if active else MUTED, font=font)


def _draw_complex_phase(draw: ImageDraw.ImageDraw, box: Tuple[int, int, int, int], progress: float, scale: float, full_turn: bool = False) -> None:
    """Реальная фазовая диаграмма комплексной экспоненты e^{iφ}."""
    left, top, right, bottom = box
    cx = (left + right) / 2
    cy = (top + bottom) / 2
    radius = min(right - left, bottom - top) * 0.34
    draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], outline=RULE, width=max(1, int(2 * scale)))
    draw.line([(cx - radius * 1.25, cy), (cx + radius * 1.25, cy)], fill=RULE, width=max(1, int(1.4 * scale)))
    draw.line([(cx, cy - radius * 1.25), (cx, cy + radius * 1.25)], fill=RULE, width=max(1, int(1.4 * scale)))
    angle = (2 * math.pi if full_turn else math.pi) * max(0.0, min(1.0, progress))
    px = cx + radius * math.cos(angle)
    py = cy - radius * math.sin(angle)
    draw.line([(cx, cy), (px, py)], fill=ACCENT, width=max(2, int(3 * scale)))
    point_radius = max(4, int(7 * scale))
    draw.ellipse([px - point_radius, py - point_radius, px + point_radius, py + point_radius], fill=INK)
    font = _serif_font(max(12, int(17 * scale)))
    draw.text((cx + radius * 1.27, cy - int(10 * scale)), "Re", fill=MUTED, font=font)
    draw.text((cx + int(8 * scale), cy - radius * 1.27), "Im", fill=MUTED, font=font)
    draw.text((px + int(10 * scale), py - int(22 * scale)), "e^(iφ)", fill=ACCENT, font=font)
    draw.text((cx + int(12 * scale), cy - int(22 * scale)), f"φ = {angle:.2f}", fill=INK, font=font)


def _draw_code(draw: ImageDraw.ImageDraw, post: Post, box: Tuple[int, int, int, int], progress: float, scale: float) -> None:
    left, top, right, bottom = box
    lines = [line for line in (post.code or "").splitlines() if line.strip()][:10]
    if not lines:
        return
    font = _serif_font(max(12, int(16 * scale)), mono=True)
    number_font = _serif_font(max(10, int(13 * scale)), mono=True)
    line_height = max(18, int(24 * scale))
    active = min(len(lines) - 1, int(progress * len(lines)))
    draw.rectangle([left - int(8 * scale), top + active * line_height - 2,
                    right, top + (active + 1) * line_height + 2], fill=(232, 226, 214))
    for index, line in enumerate(lines):
        y = top + index * line_height
        draw.text((left, y), f"{index + 1:02d}", fill=RULE, font=number_font)
        draw.text((left + int(30 * scale), y), line[:58], fill=INK, font=font)


def _formula_image(post: Post, temp_dir: Path, scale: float) -> Optional[Image.Image]:
    formula = post.formula_latex or post.formula_plain
    if not formula:
        return None
    path = temp_dir / f"formula_{post.id}.png"
    if not render_formula_png(formula, path, color=INK, fontset="cm"):
        return None
    image = Image.open(path).convert("RGBA")
    target_width = int(760 * scale)
    if image.width > target_width:
        ratio = target_width / image.width
        image = image.resize((target_width, max(1, int(image.height * ratio))), Image.Resampling.LANCZOS)
    return image


def _act_times(text: str, words: Sequence[Tuple[float, float, str]], duration: float) -> List[float]:
    """Границы пяти блоков лекции по маркерам сценария."""
    markers = ("Раздел ", "Фундаментальный вопрос:", "Применение сегодня:", "Задача слушателю:", "Разбор завершён.")
    clean = str(text or "")
    times: List[float] = [0.0]
    for marker in markers[1:]:
        position = clean.find(marker)
        if position < 0:
            continue
        word_index = len(clean[:position].split())
        if words and word_index < len(words):
            times.append(float(words[word_index][0]))
        else:
            times.append(duration * position / max(1, len(clean)))
    times = sorted(set(round(value, 3) for value in times))
    if len(times) < 5:
        if words:
            times = [
                round(float(words[min(len(words) - 1, int(len(words) * index / 5))][0]), 3)
                for index in range(5)
            ]
        else:
            times = [round(duration * index / 5.0, 3) for index in range(5)]
    return times[:5]


def _sentences(post: Post) -> List[str]:
    body = str(getattr(post, "body", "") or "")
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", body) if part.strip()]


def _draw_text_block(draw: ImageDraw.ImageDraw, text: str, x: int, y: int, width: int,
                     size: int, color: Any = INK, bold: bool = False,
                     line_gap: int = 8, max_lines: int = 5) -> int:
    font = _serif_font(size, bold=bold)
    lines = _wrap(draw, str(text or ""), font, width)[:max_lines]
    for index, line in enumerate(lines):
        draw.text((x, y + index * (size + line_gap)), line, fill=color, font=font)
    return y + len(lines) * (size + line_gap)


def _block_times(blocks: Sequence[str], words: Sequence[Tuple[float, float, str]], duration: float) -> List[float]:
    """Границы 5 блоков по словам: точная синхронизация сцены и речи."""
    counts = [max(1, len(str(block).split())) for block in blocks]
    total = sum(counts)
    times: List[float] = []
    consumed = 0
    for count in counts:
        if words:
            index = min(len(words) - 1, consumed)
            times.append(round(float(words[index][0]), 3))
        else:
            times.append(round(duration * consumed / max(1, total), 3))
        consumed += count
    times[0] = 0.0
    return sorted(set(times))[:5]


class BookFilmScene:
    """Один пост → кадры книжной страницы с реальной геометрией поста."""

    def __init__(self, post: Post, width: int, height: int, artifact: Optional[VoiceArtifact] = None):
        self.post = post
        self.width = width
        self.height = height
        self.scale = min(width, height) / 1080.0
        self.artifact = artifact
        self.duration = max(MIN_SECONDS, float(getattr(artifact, "duration_s", 0.0) or 8.0))
        self.blocks = build_film_blocks(post)
        self.text = str(getattr(artifact, "text", "") or " ".join(self.blocks))
        self.words = list(getattr(artifact, "words", []) or _approx_words(self.text, self.duration))
        self.act_times = _block_times(self.blocks, self.words, self.duration)
        self.sequence = extract_sequence(post)
        self.curve = None
        expression = post.meta.get("plot_expr") or post.formula_plain or ""
        if expression and re.search(r"\bx\b", str(expression)):
            try:
                self.curve = evaluate_curve(str(expression))
            except Exception:
                self.curve = None
        self.temp_dir = Path(tempfile.mkdtemp(prefix="sp_book_scene_"))
        self.formula = _formula_image(post, self.temp_dir, self.scale)

    def close(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def act_at(self, time_s: float) -> int:
        index = 0
        for position, start in enumerate(self.act_times):
            if time_s >= start:
                index = position
        return min(4, index)

    def render(self, time_s: float) -> Image.Image:
        image = Image.new("RGB", (self.width, self.height), PAPER)
        draw = ImageDraw.Draw(image)
        s = self.scale
        margin = int(72 * s)
        width = self.width - 2 * margin
        meta = getattr(self.post, "meta", {}) or {}

        # Полиграфическая рамка.
        draw.rectangle([32 * s, 32 * s, self.width - 32 * s, self.height - 32 * s],
                       outline=RULE, width=max(1, int(2 * s)))

        # ЗОНА 1 — только рубрика и крупный заголовок.
        section = str(meta.get("section_num") or "").strip()
        era = str(meta.get("era") or "").strip()
        rubric = " · ".join(part for part in (
            f"§ {section}" if section else "", self.post.label.upper(), era.upper()
        ) if part)
        accent = {"math": (30, 58, 138), "physics": (159, 18, 57), "cs": (6, 95, 70)}.get(self.post.domain, ACCENT)
        draw.text((margin, int(64 * s)), rubric, fill=accent, font=_serif_font(max(12, int(20 * s)), bold=True, mono=True))
        draw.line((margin, int(106 * s), margin + width, int(106 * s)), fill=INK, width=max(1, int(2 * s)))
        title_font, title_lines = _fit(draw, self.post.plain_title, width, int(40 * s), int(30 * s), 2, bold=True)
        y = int(124 * s)
        for line in title_lines[:2]:
            draw.text((margin, y), line, fill=INK, font=title_font)
            y += int(getattr(title_font, "size", 40 * s) * 1.16)

        # ЗОНА 2 — одно окно контекста, меняется по 5 блокам речи.
        box = (margin, int(235 * s), margin + width, int(825 * s))
        draw.rectangle(box, outline=RULE, width=max(1, int(1.5 * s)))
        content = (box[0] + int(18 * s), box[1] + int(18 * s), box[2] - int(18 * s), box[3] - int(18 * s))
        act = self.act_at(time_s)
        act_start = self.act_times[act]
        act_end = self.act_times[act + 1] if act + 1 < len(self.act_times) else self.duration
        progress = min(1.0, max(0.0, (time_s - act_start) / max(1e-6, act_end - act_start)))
        if act == 0:
            self._draw_passport(draw, content, s, meta)
        elif act == 1:
            self._draw_live_chart(draw, content, s, progress)
        elif act == 2:
            self._draw_formula_scene(image, draw, content, s, meta)
        elif act == 3:
            self._draw_computation(draw, content, s, progress, meta)
        else:
            self._draw_application(draw, content, s, meta)

        # ЗОНА 3 — неподвижная формула.
        formula_box = (margin, int(845 * s), margin + width, int(1000 * s))
        draw.rectangle(formula_box, fill=(243, 240, 234))
        draw.rectangle((formula_box[0], formula_box[1], formula_box[0] + int(6 * s), formula_box[3]), fill=accent)
        if self.formula is not None:
            fx = (formula_box[0] + formula_box[2] - self.formula.width) // 2
            fy = (formula_box[1] + formula_box[3] - self.formula.height) // 2
            image.paste(self.formula, (fx, fy), self.formula)
        else:
            formula = self.post.formula_plain or self.post.formula_latex or ""
            if formula:
                draw.text((formula_box[0] + int(24 * s), formula_box[1] + int(48 * s)),
                          formula[:80], fill=INK, font=_serif_font(max(16, int(30 * s)), bold=True))

        # Подвал: глава + сайт, без караоке и мусора.
        footer_font = _serif_font(max(10, int(14 * s)), mono=True)
        chapter = f"Часть {act + 1} из 5 · {SCENE_NAMES[act]}"
        draw.text((margin, int(1012 * s)), chapter, fill=MUTED, font=footer_font)
        site = "newmathphys.com · @newmathphys"
        draw.text((margin + width - draw.textlength(site, font=footer_font), int(1012 * s)), site, fill=MUTED, font=footer_font)
        return image

    def _draw_passport(self, draw: ImageDraw.ImageDraw, box: Tuple[int, int, int, int], s: float, meta: Dict[str, Any]) -> None:
        left, top, right, bottom = box
        scientist = str(meta.get("scientist") or self.post.source_name or "Учёный")
        era = str(meta.get("era") or "")
        year_match = re.search(r"(\d{1,4})", era)
        year = year_match.group(1) if year_match else era[:8]
        era_label = era.replace(year, "", 1).strip(" •·") if year_match else ""
        draw.text((left, top + int(18 * s)), "ПАСПОРТ ОТКРЫТИЯ", fill=MUTED, font=_serif_font(max(12, int(20 * s)), bold=True, mono=True))
        draw.text((left, top + int(50 * s)), year, fill=ACCENT, font=_serif_font(max(32, int(56 * s)), bold=True))
        if era_label:
            draw.text((left, top + int(116 * s)), era_label[:40], fill=MUTED, font=_serif_font(max(12, int(22 * s))))
        draw.text((left, top + int(150 * s)), scientist, fill=INK, font=_serif_font(max(20, int(38 * s)), bold=True))
        source = str(self.post.source_name or "")
        draw.text((left, top + int(190 * s)), source[:70], fill=MUTED, font=_serif_font(max(12, int(24 * s))))
        prereqs = [str(item) for item in (meta.get("prereq_ids") or [])][:2]
        if prereqs:
            draw.text((left, top + int(240 * s)), f"Опирается на: {', '.join(prereqs)}", fill=ACCENT,
                      font=_serif_font(max(12, int(22 * s))))

    def _draw_live_chart(self, draw: ImageDraw.ImageDraw, box: Tuple[int, int, int, int], s: float, progress: float) -> None:
        timeline = (self.post.meta or {}).get("timeline")
        formula_text = f"{self.post.formula_latex} {self.post.formula_plain}"
        wave_like = ("Ψ" in formula_text or "psi" in formula_text.lower()
                     or str((self.post.meta or {}).get("canon_id") or "") in ("schrodinger", "tunneling", "heisenberg"))
        canon_id = str((self.post.meta or {}).get("canon_id") or (self.post.meta or {}).get("foundation_id") or "")
        if canon_id == "pythagoras" or "a² + b² = c²" in str(self.post.formula_plain or ""):
            self._draw_triangle(draw, box, s)
        elif wave_like:
            _draw_wave_packet(draw, box, progress, s)
        elif self.sequence:
            _draw_stem_plot(draw, self.sequence, box, s, progress)
        elif self.curve is not None:
            _draw_curve(draw, self.curve, box, s, progress)
        elif isinstance(timeline, list):
            _draw_timeline(draw, timeline, box, progress, s)
        else:
            self._draw_concept_cards(draw, box, s, progress)

    def _draw_concept_cards(self, draw: ImageDraw.ImageDraw, box: Tuple[int, int, int, int],
                            s: float, progress: float) -> None:
        left, top, right, bottom = box
        sentences = _sentences(self.post)
        cards = [
            ("I. ПОСТАНОВКА", self.post.hook or self.post.title),
            ("II. СУТЬ", sentences[0] if sentences else self.post.body[:180]),
            ("III. ПРИМЕНЕНИЕ", str((self.post.meta or {}).get("modern_application") or "Наука и инженерия")),
        ]
        card_h = int((bottom - top - 40 * s) / 3) - int(12 * s)
        y = top + int(10 * s)
        for index, (head, body) in enumerate(cards):
            if progress < index / 3.0:
                break
            draw.rounded_rectangle((left + int(12 * s), y, right - int(12 * s), y + card_h),
                                   radius=int(10 * s), outline=RULE, width=max(1, int(2 * s)))
            draw.text((left + int(26 * s), y + int(10 * s)), head, fill=ACCENT,
                      font=_serif_font(max(12, int(20 * s)), bold=True, mono=True))
            _draw_text_block(draw, str(body), left + int(26 * s), y + int(38 * s),
                             right - left - int(52 * s), int(22 * s), INK, False, int(5 * s), 3)
            if index < 2:
                draw.line((left + int(30 * s), y + card_h, left + int(30 * s), y + card_h + int(12 * s)),
                          fill=ACCENT, width=max(1, int(2 * s)))
            y += card_h + int(12 * s)

    def _draw_triangle(self, draw: ImageDraw.ImageDraw, box: Tuple[int, int, int, int], s: float) -> None:
        left, top, right, bottom = box
        ax, ay = left + int(70 * s), bottom - int(60 * s)
        bx, by = right - int(90 * s), bottom - int(60 * s)
        cx, cy = left + int(70 * s), top + int(70 * s)
        draw.line((ax, ay, bx, by), fill=INK, width=max(2, int(3 * s)))
        draw.line((bx, by, cx, cy), fill=ACCENT, width=max(2, int(4 * s)))
        draw.line((cx, cy, ax, ay), fill=INK, width=max(2, int(3 * s)))
        draw.rectangle((ax, ay - int(26 * s), ax + int(26 * s), ay), outline=RULE, width=max(1, int(2 * s)))
        font = _serif_font(max(16, int(34 * s)), bold=True)
        draw.text((ax - int(10 * s), ay + int(10 * s)), "a", fill=INK, font=font)
        draw.text((bx + int(8 * s), by + int(10 * s)), "b", fill=INK, font=font)
        draw.text(((cx + bx) // 2 + int(8 * s), (cy + by) // 2), "c", fill=ACCENT, font=font)
        draw.text((left + int(20 * s), top + int(18 * s)), "a² + b² = c²", fill=MUTED,
                  font=_serif_font(max(14, int(26 * s)), mono=True))

    def _draw_simple_curve(self, draw: ImageDraw.ImageDraw, box: Tuple[int, int, int, int],
                           s: float, progress: float) -> None:
        """Чистый график по формуле: для r — обратная квадратичная, иначе f(x)."""
        left, top, right, bottom = box
        formula = f"{self.post.formula_plain} {self.post.formula_latex}".lower()
        xs = np.linspace(0.35, 3.6, 160)
        if "r" in formula or "r²" in formula or "r^2" in formula:
            ys = 1.0 / (xs ** 2)
            label = "F(r) ~ 1/r²"
        else:
            ys = 0.55 + 0.35 * np.sin(xs * 1.8)
            label = "f(x)"
        peak = float(np.max(np.abs(ys))) or 1.0
        ys = ys / peak
        x0, x1 = left + int(60 * s), right - int(50 * s)
        y0, y1 = top + int(30 * s), bottom - int(50 * s)
        mid = (y0 + y1) // 2
        draw.line((x0, mid, x1, mid), fill=RULE, width=max(1, int(1.5 * s)))
        draw.line((x0, y0, x0, y1), fill=RULE, width=max(1, int(1.5 * s)))
        points = []
        visible = max(2, int(len(xs) * max(0.05, min(1.0, progress))))
        for index in range(visible):
            px = x0 + (xs[index] - xs[0]) / (xs[-1] - xs[0]) * (x1 - x0)
            py = mid - float(ys[index]) * (y1 - y0) * 0.45
            points.append((px, py))
        if len(points) > 1:
            draw.line(points, fill=ACCENT, width=max(2, int(3.2 * s)), joint="curve")
        if points:
            draw.ellipse((points[-1][0] - 6 * s, points[-1][1] - 6 * s,
                          points[-1][0] + 6 * s, points[-1][1] + 6 * s), fill=ACCENT)
        draw.text((left + int(24 * s), top + int(18 * s)), label, fill=INK,
                  font=_serif_font(max(12, int(22 * s)), bold=True, mono=True))

    def _draw_formula_scene(self, image: Image.Image, draw: ImageDraw.ImageDraw, box: Tuple[int, int, int, int],
                            s: float, meta: Dict[str, Any]) -> None:
        left, top, right, bottom = box
        draw.text((left, top + int(18 * s)), "СМЫСЛ ФОРМУЛЫ", fill=MUTED,
                  font=_serif_font(max(12, int(20 * s)), bold=True, mono=True))
        canon_id = str(meta.get("canon_id") or meta.get("foundation_id") or "")
        known = {
            "pythagoras": "a, b — катеты прямоугольного треугольника; c — гипотенуза; xᵢ — координаты вектора.",
            "euclid_gcd": "a, b — целые числа; gcd — наибольший общий делитель; O(log n) — число шагов.",
            "newton_gravity": "F — сила; G — гравитационная постоянная; m₁, m₂ — массы; r — расстояние; v₁ — первая космическая скорость.",
        }
        variables = str(meta.get("formula_vars") or "").strip() or known.get(canon_id, "")
        if not variables:
            _draw_text_block(draw, "Подробный смысл величин — в тексте под видео.",
                             left + int(20 * s), top + int(70 * s), right - left - int(40 * s),
                             int(24 * s), MUTED, False, int(6 * s), 3)
            return
        _draw_text_block(draw, variables, left + int(20 * s), top + int(70 * s),
                         right - left - int(40 * s), int(26 * s), INK, False, int(8 * s), 3)
        lower = (left + int(20 * s), top + int(210 * s), right - int(20 * s), bottom - int(10 * s))
        if canon_id == "pythagoras" or "a² + b² = c²" in str(self.post.formula_plain or ""):
            self._draw_triangle(draw, lower, s * 0.8)
        else:
            self._draw_simple_curve(draw, lower, s * 0.8, 1.0)

    def _draw_computation(self, draw: ImageDraw.ImageDraw, box: Tuple[int, int, int, int],
                          s: float, progress: float, meta: Dict[str, Any]) -> None:
        left, top, right, bottom = box
        if self.post.code:
            _draw_code(draw, self.post, box, progress, s)
            return
        example = verified_example(self.post)
        draw.text((left, top + int(18 * s)), "ЧИСЛОВОЙ ПРИМЕР", fill=MUTED,
                  font=_serif_font(max(12, int(20 * s)), bold=True, mono=True))
        if example:
            _draw_text_block(draw, example, left + int(10 * s), top + int(65 * s),
                             right - left - int(20 * s), int(30 * s), INK, True, int(10 * s), 3)
        else:
            _draw_text_block(draw, "Точный числовой пример — в тексте под видео.",
                             left + int(10 * s), top + int(65 * s),
                             right - left - int(20 * s), int(24 * s), MUTED, False, int(6 * s), 2)
        lower = (left + int(20 * s), top + int(220 * s), right - int(20 * s), bottom - int(10 * s))
        canon_id = str(meta.get("canon_id") or meta.get("foundation_id") or "")
        if canon_id == "pythagoras" or "a² + b² = c²" in str(self.post.formula_plain or ""):
            self._draw_triangle(draw, lower, s * 0.8)
        else:
            self._draw_simple_curve(draw, lower, s * 0.8, 1.0)

    def _draw_application(self, draw: ImageDraw.ImageDraw, box: Tuple[int, int, int, int],
                          s: float, meta: Dict[str, Any]) -> None:
        left, top, right, bottom = box
        application = str(meta.get("modern_application") or "Применение в науке и инженерии")
        unlocks = [str(item) for item in (meta.get("unlocks_concepts") or [])][:3]
        draw.text((left, top + int(18 * s)), "ГДЕ РАБОТАЕТ СЕГОДНЯ", fill=MUTED,
                  font=_serif_font(max(12, int(20 * s)), bold=True, mono=True))
        _draw_text_block(draw, application, left, top + int(60 * s), right - left,
                         int(32 * s), INK, True, int(8 * s), 4)
        if unlocks:
            draw.text((left, top + int(190 * s)), "Открывает путь к:", fill=ACCENT,
                      font=_serif_font(max(12, int(22 * s)), bold=True))
            _draw_text_block(draw, ", ".join(unlocks), left, top + int(220 * s), right - left,
                             int(22 * s), MUTED, False, int(6 * s), 2)
        lower = (left + int(20 * s), top + int(280 * s), right - int(20 * s), bottom - int(10 * s))
        canon_id = str(meta.get("canon_id") or meta.get("foundation_id") or "")
        if canon_id == "pythagoras" or "a² + b² = c²" in str(self.post.formula_plain or ""):
            self._draw_triangle(draw, lower, s * 0.8)
        else:
            self._draw_simple_curve(draw, lower, s * 0.8, 1.0)

def _mux(frames_dir: Path, audio_path: Optional[Path], out_path: Path, fps: float) -> bool:
    if not book_film_available():
        return False
    args = ["ffmpeg", "-y", "-loglevel", "error", "-framerate", f"{fps:.4f}",
            "-i", str(frames_dir / "frame_%05d.png")]
    if audio_path and audio_path.is_file():
        args += [
            "-i", str(audio_path), "-c:a", "aac", "-b:a", "128k",
            "-ar", "48000", "-ac", "2", "-shortest",
        ]
    args += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out_path)]
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=600, check=False)
        if result.returncode != 0:
            LOGGER.warning("book_film ffmpeg: %s", (result.stderr or "")[:300])
            return False
    except Exception as exc:
        LOGGER.warning("book_film ffmpeg: %s", exc)
        return False
    return out_path.is_file() and out_path.stat().st_size > 1000


def render_book_film(
    post: Post,
    out_path: str | Path,
    config: Any,
    aspect: Optional[str] = None,
    artifact: Optional[VoiceArtifact] = None,
    max_seconds: Optional[float] = None,
) -> Optional[Path]:
    """Собирает книжный фильм поста. Без ffmpeg возвращает None."""
    if not book_film_available():
        return None
    settings = book_film_settings(config, aspect)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    artifact = artifact or film_voice_for_post(post, config)
    scene = BookFilmScene(post, settings["width"], settings["height"], artifact)
    duration = min(float(max_seconds or scene.duration), 180.0)
    frames = max(2, min(settings["max_frames"], int(duration * settings["fps"])))
    audio_path = Path(artifact.mp3_path) if artifact and artifact.mp3_path and Path(artifact.mp3_path).is_file() else None
    if audio_path is None:
        try:
            from .sound import sonify

            audio_path = out_path.with_suffix(".wav")
            sonify(post, audio_path, seconds=duration)
        except Exception:
            audio_path = None
    with tempfile.TemporaryDirectory(prefix="sp_book_film_") as tmp:
        frames_dir = Path(tmp)
        for index in range(frames):
            time_s = duration * index / max(1, frames - 1)
            scene.render(time_s).save(frames_dir / f"frame_{index:05d}.png")
        ok = _mux(frames_dir, audio_path, out_path, frames / max(1e-6, duration))
    scene.close()
    if audio_path and audio_path.suffix == ".wav":
        try:
            audio_path.unlink()
        except OSError:
            pass
    return out_path if ok else None


def book_film_for_post(post: Post, config: Any, aspect: Optional[str] = None,
                       out_dir: str | Path | None = None) -> Optional[Path]:
    settings = book_film_settings(config, aspect)
    directory = Path(out_dir) if out_dir else config.data_dir / "book_films"
    target = directory / f"{post.id}_{settings['aspect'].replace(':', 'x')}.mp4"
    key_path = directory / f"{post.id}_{settings['aspect'].replace(':', 'x')}.key"
    key = f"{post.id}|{post.title}|{post.formula_plain}|{settings['aspect']}|{settings['fps']}"
    if target.is_file() and key_path.is_file() and key_path.read_text(encoding="utf-8") == key:
        return target
    produced = render_book_film(post, target, config, aspect=aspect)
    if produced is None:
        return None
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_text(key, encoding="utf-8")
    return produced

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
from .voice import VoiceArtifact, build_lecture_script, voice_for_post

LOGGER = logging.getLogger(__name__)

FPS = 24
SIZE = 1080
MAX_FRAMES = 1800
MIN_SECONDS = 3.0
ACT_ROMAN = ("I", "II", "III", "IV", "V")


def book_film_available() -> bool:
    return bool(shutil.which("ffmpeg"))


def book_film_settings(config: Any = None, aspect: Optional[str] = None) -> Dict[str, Any]:
    raw = dict((getattr(config, "raw", {}) or {}).get("book_film") or {}) if config else {}
    value = str(aspect or raw.get("aspect", "1:1")).replace(" ", "")
    if value in ("9:16", "916", "vertical", "portrait"):
        width, height = 1080, 1920
    else:
        width, height = int(raw.get("size", SIZE)), int(raw.get("size", SIZE))
    return {
        "aspect": "9:16" if height > width else "1:1",
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


class BookFilmScene:
    """Один пост → кадры книжной страницы с реальной геометрией поста."""

    def __init__(self, post: Post, width: int, height: int, artifact: Optional[VoiceArtifact] = None):
        self.post = post
        self.width = width
        self.height = height
        self.scale = min(width, height) / 1080.0
        self.artifact = artifact
        self.duration = max(MIN_SECONDS, float(getattr(artifact, "duration_s", 0.0) or 8.0))
        self.text = str(getattr(artifact, "text", "") or build_lecture_script(post, max_chars=900))
        self.words = list(getattr(artifact, "words", []) or _approx_words(self.text, self.duration))
        self.act_times = _act_times(self.text, self.words, self.duration)
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
        margin = int(64 * s)
        width = self.width - 2 * margin

        # Верх: книжный колонтитул, заголовок, теорема.
        header = f"{_section(self.post)} · {self.post.label} · {_era(self.post)}".strip(" ·")
        font_small = _serif_font(max(12, int(18 * s)), bold=True)
        draw.text((margin, int(42 * s)), header.upper(), fill=ACCENT, font=font_small)
        draw.line((margin, int(74 * s), margin + width, int(74 * s)), fill=RULE, width=max(1, int(1.5 * s)))

        title_font, title_lines = _fit(draw, self.post.plain_title if hasattr(self.post, "plain_title") else self.post.title,
                                       width, int(38 * s), int(22 * s), 2, bold=True)
        y = int(94 * s)
        for line in title_lines:
            draw.text((margin, y), line, fill=INK, font=title_font)
            y += int(44 * s)

        if self.formula is not None:
            y += int(10 * s)
            image.paste(self.formula, (margin + (width - self.formula.width) // 2, y), self.formula)
            y += self.formula.height + int(8 * s)
        draw.line((margin, y, margin + width, y), fill=RULE, width=max(1, int(1.5 * s)))

        # Центр: только реальные данные.
        box = (margin + int(16 * s), y + int(24 * s), margin + width - int(16 * s), int(self.height * 0.88))
        draw.rectangle([box[0] - int(8 * s), box[1] - int(8 * s), box[2] + int(8 * s), box[3] + int(8 * s)],
                       outline=RULE, width=max(1, int(1.2 * s)))
        progress = min(1.0, max(0.0, time_s / max(1e-6, self.duration)))
        timeline = (self.post.meta or {}).get("timeline")
        visual_type = str((self.post.meta or {}).get("visual_type") or "")
        formula_text = f"{self.post.formula_latex} {self.post.formula_plain}"
        canon_id = str((self.post.meta or {}).get("canon_id") or "")
        wave_like = ("Ψ" in formula_text or "psi" in formula_text.lower()
                     or canon_id in ("schrodinger", "tunneling", "heisenberg"))
        act_index = self.act_at(time_s)
        draw.text(
            (margin + width - int(120 * s), int(44 * s)),
            f"АКТ {ACT_ROMAN[act_index]} / V",
            fill=MUTED,
            font=font_small,
        )
        if self.post.code and self.post.domain == "cs":
            _draw_code(draw, self.post, box, progress, s)
        elif wave_like and act_index in (1, 2):
            _draw_wave_packet(draw, box, progress, s)
        elif wave_like and act_index == 4 and re.search(r"e\^\{?i|e\^i", formula_text):
            _draw_complex_phase(draw, box, progress, s, full_turn=False)
        elif visual_type == "timeline_evolution" and isinstance(timeline, list) and act_index in (0, 3):
            _draw_timeline(draw, timeline, box, progress, s)
        elif wave_like:
            _draw_wave_packet(draw, box, progress, s)
        elif self.sequence:
            _draw_stem_plot(draw, self.sequence, box, s, progress)
        elif self.curve is not None:
            _draw_curve(draw, self.curve, box, s, progress)
        elif re.search(r"e\^\{?i|e\^i", formula_text):
            _draw_complex_phase(draw, box, progress, s, full_turn=False)
        else:
            # Честная книжная плашка: без выдуманного графика.
            font = _serif_font(max(14, int(20 * s)))
            lines = [
                f"Дисциплина: {self.post.label}",
                f"Источник: {self.post.source_name or 'Science Pulse'}",
                "Формула — в верхнем блоке; график не подменяется декором.",
            ]
            yy = box[1] + int(28 * s)
            for line in lines:
                for wrapped in _wrap(draw, line, font, box[2] - box[0] - int(24 * s))[:2]:
                    draw.text((box[0] + int(16 * s), yy), wrapped, fill=INK, font=font)
                    yy += int(28 * s)

        footer_font = _serif_font(max(10, int(14 * s)))
        draw.text((margin, self.height - int(34 * s)), "Science Pulse · академический разбор · без LLM",
                  fill=MUTED, font=footer_font)
        return image


def _mux(frames_dir: Path, audio_path: Optional[Path], out_path: Path, fps: float) -> bool:
    if not book_film_available():
        return False
    args = ["ffmpeg", "-y", "-loglevel", "error", "-framerate", f"{fps:.4f}",
            "-i", str(frames_dir / "frame_%05d.png")]
    if audio_path and audio_path.is_file():
        args += ["-i", str(audio_path), "-c:a", "aac", "-b:a", "128k", "-shortest"]
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
    artifact = artifact or voice_for_post(post, config)
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

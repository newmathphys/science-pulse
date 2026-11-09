"""Инфографический explainer-фильм в стиле «Закон Амдала».

Чистый код: Pillow + NumPy + ffmpeg. Без видео-нейросетей и без LLM.
Пять сцен, HUD с прогрессом, бегущий счётчик формулы, waffle-grid 5×8,
крупные караоке-субтитры с цветной плашкой.

Вход — обычный Post из очереди. Выход — MP4 9:16 или 1:1.
"""
from __future__ import annotations

import hashlib
import math
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFont

from .models import Post
from .voice import VoiceArtifact, synthesize, voice_settings

BG = "#0B1021"
GRID = "#162038"
ACCENT = "#EAB308"
BLUE = "#1D4ED8"
INK = "#F8FAFC"
MUTED = "#94A3B8"
ORANGE = "#F97316"
FPS = 24
MAX_FRAMES = 2400
MAX_SECONDS = 90.0
SCENES = (
    "01 / откуда закон",
    "02 / паспорт открытия",
    "03 / формула в действии",
    "04 / наглядный расчёт",
    "05 / узкое место и вывод",
)
FONT_REGULAR = "/usr/share/fonts/TTF/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"


def explainer_film_available() -> bool:
    return bool(shutil.which("ffmpeg"))


def explainer_settings(config: Any = None, aspect: Optional[str] = None) -> Dict[str, Any]:
    raw = dict((getattr(config, "raw", {}) or {}).get("explainer") or {}) if config else {}
    value = str(aspect or raw.get("aspect", "9:16")).replace(" ", "")
    if value in ("1:1", "11", "square"):
        width = height = int(raw.get("size", 1080))
    else:
        width, height = int(raw.get("width", 1080)), int(raw.get("height", 1920))
    return {
        "aspect": "1:1" if width == height else "9:16",
        "width": width,
        "height": height,
        "fps": int(raw.get("fps", FPS)),
        "max_frames": int(raw.get("max_frames", MAX_FRAMES)),
    }


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = FONT_BOLD if bold else FONT_REGULAR
    try:
        return ImageFont.truetype(path, max(8, int(size)))
    except OSError:
        return ImageFont.load_default()


def _wrap(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> List[str]:
    words = str(text or "").split()
    lines: List[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and font.getlength(candidate) > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines or [""]


def _draw_text_block(draw: ImageDraw.ImageDraw, text: str, x: int, y: int, width: int,
                     size: int, color: str = INK, bold: bool = False,
                     line_gap: int = 8, max_lines: int = 6) -> int:
    font = _font(size, bold)
    lines = _wrap(text, font, width)[:max_lines]
    for index, line in enumerate(lines):
        draw.text((x, y + index * (size + line_gap)), line, font=font, fill=color)
    return y + len(lines) * (size + line_gap)


def build_explainer_script(post: Post) -> str:
    """Короткий сценарий ровно под 5 сцен: по одному смысловому блоку."""
    meta = getattr(post, "meta", {}) or {}
    scientist = str(meta.get("scientist") or post.source_name or "учёный")
    era = str(meta.get("era") or "").strip()
    year_match = re.search(r"\b(1[0-9]{3}|20[0-9]{2})\b", era)
    year = year_match.group(1) if year_match else era
    formula = (post.formula_plain or post.formula_latex or "формула").replace("\n", " ")
    application = str(meta.get("modern_application") or "применение в науке и инженерии")
    hook = post.hook or post.title
    parts = [
        f"Парадокс: {hook}",
        f"Паспорт открытия: {scientist}, {year}.",
        f"Формула: {formula}. Считаем, как меняется результат.",
        "Наглядный расчёт: сорок часов сжимаются, узкое место видно на сетке.",
        f"Вывод: {application}.",
    ]
    return " ".join(part.strip() for part in parts if part.strip())[:900]


def _explainer_voice(post: Post, config: Any) -> Optional[VoiceArtifact]:
    settings = dict(voice_settings(config))
    settings["max_chars"] = 420
    text = build_explainer_script(post)
    if len(text) < 40:
        return None
    return synthesize(text, config.data_dir / "audio", f"{post.id}_explainer",
                      config, settings, post=post)


def _numbers(text: str) -> List[float]:
    found = re.findall(r"\d+(?:[.,]\d+)?", text or "")
    values: List[float] = []
    for item in found:
        try:
            value = float(item.replace(",", "."))
        except ValueError:
            continue
        if 0 < value < 1_000_000:
            values.append(value)
    return values


def _counter_series(post: Post) -> List[float]:
    """Детерминированный ряд множителя из формулы/чисел поста."""
    formula = f"{post.formula_plain or ''} {post.formula_latex or ''}"
    if re.search(r"\b[PNn]\b", formula) and ("1/" in formula or "1 /" in formula or "P" in formula):
        p = 0.9
        values = [1.0 / ((1.0 - p) + p / n) for n in (2, 4, 8, 16)]
        values.append(1.0 / (1.0 - p))
        return values
    nums = _numbers(f"{formula} {post.title} {post.hook}")[:4]
    if len(nums) >= 2:
        peak = max(nums) or 1.0
        return [1.0 + 3.0 * (value / peak) for value in nums]
    return [1.0, 1.5, 2.2, 3.0]


def _speedup(post: Post) -> float:
    return max(1.01, _counter_series(post)[-1])


def _category_palette(post: Post) -> List[str]:
    if post.domain == "cs":
        return ["код", "ревью", "созвон", "тест", "сборка"]
    if post.domain == "physics":
        return ["теория", "эксперимент", "расчёт", "ревью", "публикация"]
    return ["идея", "доказательство", "вычисление", "ревью", "сборка"]


def _waffle(post: Post) -> List[str]:
    palette = _category_palette(post)
    seed = sum(ord(char) for char in (post.id or post.title))
    return [palette[(seed + index * 7) % len(palette)] for index in range(40)]


def _draw_background(draw: ImageDraw.ImageDraw, width: int, height: int) -> None:
    draw.rectangle((0, 0, width, height), fill=BG)
    step = max(36, width // 18)
    for x in range(0, width, step):
        draw.line((x, 0, x, height), fill=GRID, width=1)
    for y in range(0, height, step):
        draw.line((0, y, width, y), fill=GRID, width=1)
    cx, cy = width // 2, height // 2
    for radius in (int(width * 0.18), int(width * 0.32), int(width * 0.46)):
        draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline=GRID, width=2)
    draw.line((cx - 18, cy, cx + 18, cy), fill=ACCENT, width=2)
    draw.line((cx, cy - 18, cx, cy + 18), fill=ACCENT, width=2)


def _draw_hud(draw: ImageDraw.ImageDraw, width: int, height: int, scene: int,
              progress: float, multiplier: float) -> None:
    margin = int(width * 0.06)
    bar_y = int(height * 0.045)
    bar_w = width - 2 * margin
    draw.rounded_rectangle((margin, bar_y, margin + bar_w, bar_y + 8), radius=4, fill=GRID)
    draw.rounded_rectangle((margin, bar_y, margin + int(bar_w * progress), bar_y + 8), radius=4, fill=ACCENT)
    label = _font(int(width * 0.026), bold=True)
    draw.text((margin, bar_y + 22), SCENES[scene], font=label, fill=INK)
    value = f"×{multiplier:.1f}".replace(".", ",")
    font = _font(int(width * 0.05), bold=True)
    tw = font.getlength(value)
    draw.text((width - margin - tw, bar_y + 16), value, font=font, fill=ACCENT)


def _draw_scene_paradox(draw: ImageDraw.ImageDraw, post: Post, width: int, height: int, p: float) -> None:
    margin = int(width * 0.07)
    y = int(height * 0.14)
    y = _draw_text_block(draw, post.title, margin, y, width - 2 * margin, int(width * 0.075), INK, True, 10, 3)
    y = _draw_text_block(draw, post.hook or "Что здесь не сходится?", margin, y + 24,
                         width - 2 * margin, int(width * 0.038), MUTED, False, 8, 3)
    block_y = int(height * 0.44)
    block_w = int((width - 2 * margin) / 10) - 6
    block_h = int(height * 0.035)
    for index in range(10):
        x = margin + index * (block_w + 6)
        color = ORANGE if index < 3 else BLUE
        draw.rounded_rectangle((x, block_y, x + block_w, block_y + block_h), radius=6, fill=color)
        draw.text((x + block_w // 2 - 5, block_y + 8), str(index + 1), font=_font(int(width * 0.02), True), fill=INK)
    arrow_y = block_y + block_h + 30
    draw.line((margin, arrow_y, width - margin, arrow_y), fill=MUTED, width=3)
    draw.polygon([(width - margin, arrow_y), (width - margin - 16, arrow_y - 8),
                  (width - margin - 16, arrow_y + 8)], fill=ACCENT)
    draw.text((margin, arrow_y + 18), "последовательная часть → узкое место", font=_font(int(width * 0.03), True), fill=ACCENT)
    # Пульсирующий акцент на «узком месте».
    pulse = 0.5 + 0.5 * math.sin(p * math.pi * 4)
    draw.ellipse((width - margin - 70, block_y - 22, width - margin + 10, block_y + block_h + 22),
                 outline=ACCENT, width=max(2, int(2 + pulse * 3)))


def _draw_scene_passport(draw: ImageDraw.ImageDraw, post: Post, width: int, height: int, p: float) -> None:
    meta = getattr(post, "meta", {}) or {}
    scientist = str(meta.get("scientist") or post.source_name or "Наука")
    era = str(meta.get("era") or "")
    year_match = re.search(r"\b(1[0-9]{3}|20[0-9]{2})\b", era)
    year = year_match.group(1) if year_match else "—"
    margin = int(width * 0.08)
    y = int(height * 0.16)
    draw.text((margin, y), "ПАСПОРТ ОТКРЫТИЯ", font=_font(int(width * 0.026), True), fill=ACCENT)
    draw.text((margin, y + int(height * 0.05)), year, font=_font(int(width * 0.22), True), fill=ACCENT)
    _draw_text_block(draw, scientist, margin, y + int(height * 0.25), width - 2 * margin,
                     int(width * 0.07), INK, True, 10, 2)
    card_y = int(height * 0.58)
    draw.rounded_rectangle((margin, card_y, width - margin, card_y + int(height * 0.12)),
                           radius=18, fill="#111A31", outline=GRID, width=2)
    _draw_text_block(draw, post.source_name or "Первоисточник", margin + 24, card_y + 18,
                     width - 2 * margin - 48, int(width * 0.032), MUTED, False, 6, 2)
    if post.source_url:
        draw.text((margin + 24, card_y + int(height * 0.075)), post.source_url[:64],
                  font=_font(int(width * 0.022)), fill=BLUE)


def _draw_scene_formula(draw: ImageDraw.ImageDraw, post: Post, width: int, height: int, p: float) -> None:
    margin = int(width * 0.07)
    y = int(height * 0.15)
    draw.text((margin, y), "ФОРМУЛА В ДЕЙСТВИИ", font=_font(int(width * 0.026), True), fill=ACCENT)
    formula = post.formula_plain or post.formula_latex or "f(x)"
    _draw_text_block(draw, formula, margin, y + int(height * 0.05), width - 2 * margin,
                     int(width * 0.06), INK, True, 10, 3)
    values = _counter_series(post)
    index = min(len(values) - 1, int(p * len(values)))
    current = values[index]
    big = f"×{current:.1f}".replace(".", ",")
    draw.text((margin, y + int(height * 0.18)), big, font=_font(int(width * 0.20), True), fill=ACCENT)
    draw.text((margin, y + int(height * 0.34)), "ускорение при выбранном параметре",
              font=_font(int(width * 0.025)), fill=MUTED)
    block_y = int(height * 0.55)
    block_w = int((width - 2 * margin) / 10) - 6
    for i in range(10):
        x = margin + i * (block_w + 6)
        color = ORANGE if i < 3 else BLUE
        active = i <= int(p * 9)
        draw.rounded_rectangle((x, block_y, x + block_w, block_y + int(height * 0.03)),
                               radius=6, fill=color if active else GRID)
    for i, value in enumerate(values):
        x = margin + i * int((width - 2 * margin) / max(1, len(values) - 1))
        draw.ellipse((x - 7, block_y - 28, x + 7, block_y - 14), fill=ACCENT if i <= index else GRID)


def _draw_scene_waffle(draw: ImageDraw.ImageDraw, post: Post, width: int, height: int, p: float) -> None:
    margin = int(width * 0.07)
    y = int(height * 0.15)
    draw.text((margin, y), "НАГЛЯДНЫЙ РАСЧЁТ", font=_font(int(width * 0.026), True), fill=ACCENT)
    speed = _speedup(post)
    after = 40.0 / speed
    counter = f"40 Ч → {after:.1f} Ч".replace(".", ",")
    draw.text((margin, y + int(height * 0.05)), counter, font=_font(int(width * 0.075), True), fill=INK)
    cells = _waffle(post)
    palette = _category_palette(post)
    bottleneck = palette[0]
    grid_x, grid_y = margin, int(height * 0.30)
    cell_w = int((width - 2 * margin) / 8)
    cell_h = int(height * 0.075)
    for index, category in enumerate(cells):
        row, col = divmod(index, 8)
        x = grid_x + col * cell_w
        y0 = grid_y + row * cell_h
        shrink = 1.0
        if category == bottleneck:
            shrink = max(0.35, 1.0 - 0.65 * p)
        w = int((cell_w - 8) * shrink)
        h = int((cell_h - 8) * shrink)
        color = ACCENT if category == bottleneck else (BLUE if index % 3 else "#334155")
        draw.rounded_rectangle((x + (cell_w - w) // 2, y0 + (cell_h - h) // 2,
                                x + (cell_w + w) // 2, y0 + (cell_h + h) // 2),
                               radius=5, fill=color)
        if shrink > 0.55:
            draw.text((x + 10, y0 + 10), category[:7], font=_font(int(width * 0.017)), fill=INK)
    legend_y = grid_y + 5 * cell_h + 22
    draw.text((margin, legend_y), f"жёлтые: {bottleneck} · синие: параллельная часть",
              font=_font(int(width * 0.022)), fill=MUTED)


def _draw_scene_summary(draw: ImageDraw.ImageDraw, post: Post, width: int, height: int, p: float) -> None:
    margin = int(width * 0.07)
    y = int(height * 0.15)
    draw.text((margin, y), "УЗКОЕ МЕСТО И ВЫВОД", font=_font(int(width * 0.026), True), fill=ACCENT)
    values = _counter_series(post)[:4]
    peak = max(values) or 1.0
    base_y = int(height * 0.50)
    bar_w = int(width * 0.06)
    gap = int(width * 0.04)
    for index, value in enumerate(values):
        x = margin + index * (bar_w + gap)
        h = int((height * 0.24) * (value / peak))
        draw.rounded_rectangle((x, base_y - h, x + bar_w, base_y), radius=6, fill=ACCENT if index == len(values) - 1 else BLUE)
        draw.text((x, base_y + 12), f"+{int(100 * value / peak)}%", font=_font(int(width * 0.025), True), fill=INK)
    summary = [
        post.hook or post.title,
        str((getattr(post, "meta", {}) or {}).get("modern_application") or "Применение в науке и инженерии."),
        "Источник и формула проверяемы: без LLM и без генерации кадров нейросетью.",
    ]
    y2 = int(height * 0.55)
    for index, line in enumerate(summary):
        _draw_text_block(draw, f"{index + 1}. {line}", margin, y2 + index * int(height * 0.06),
                         width - 2 * margin, int(width * 0.026), INK if index == 0 else MUTED, index == 0, 5, 2)


def _approximate_words(text: str, duration: float) -> List[Tuple[float, float, str]]:
    tokens = [token for token in (text or "").split() if token]
    if not tokens:
        return []
    total = sum(max(1, len(token)) for token in tokens)
    cursor = 0.0
    result: List[Tuple[float, float, str]] = []
    for token in tokens:
        span = max(0.08, duration * max(1, len(token)) / max(1, total))
        result.append((cursor, min(duration, cursor + span), token))
        cursor += span
    return result


def _draw_karaoke(draw: ImageDraw.ImageDraw, width: int, height: int,
                  words: Sequence[Tuple[float, float, str]], time_s: float) -> None:
    if not words:
        return
    current = 0
    for index, (start, end, _token) in enumerate(words):
        if time_s >= start:
            current = index
    group: List[Tuple[float, float, str]] = []
    line_start = 0
    size = int(width * 0.055)
    font = _font(size, True)
    for group_size in (3, 2):
        line_start = (current // group_size) * group_size
        group = list(words[line_start:line_start + group_size])
        if not group:
            continue
        size = int(width * 0.055)
        font = _font(size, True)
        while size > 22:
            total = sum(font.getlength(str(item[2]).upper()) for item in group) + (len(group) - 1) * size * 0.3
            if total <= width * 0.9:
                break
            size -= 2
            font = _font(size, True)
        total = sum(font.getlength(str(item[2]).upper()) for item in group) + (len(group) - 1) * size * 0.3
        if total <= width * 0.9:
            break
    if not group:
        return
    y = int(height * 0.78)
    total = sum(font.getlength(str(item[2]).upper()) for item in group) + (len(group) - 1) * size * 0.3
    x = (width - total) / 2
    for index, (start, end, token) in enumerate(group):
        word = str(token).upper()
        tw = font.getlength(word)
        if line_start + index == current:
            draw.rounded_rectangle((x - 8, y - 6, x + tw + 8, y + size + 10),
                                   radius=8, fill=BLUE)
        draw.text((x, y), word, font=font, fill=INK)
        x += tw + size * 0.3


class ExplainerScene:
    def __init__(self, post: Post, width: int, height: int, artifact: Optional[VoiceArtifact] = None):
        self.post = post
        self.width = width
        self.height = height
        self.artifact = artifact
        self.duration = max(12.0, float(getattr(artifact, "duration_s", 0) or 24.0))
        self.words = list(getattr(artifact, "words", []) or []) if artifact else []
        if not self.words:
            text = str(getattr(artifact, "text", "") or post.body or post.hook or "")
            self.words = _approximate_words(text, self.duration)

    def render(self, time_s: float) -> Image.Image:
        image = Image.new("RGB", (self.width, self.height), BG)
        draw = ImageDraw.Draw(image)
        progress = max(0.0, min(1.0, time_s / max(1e-6, self.duration)))
        scene = min(4, int(progress * 5))
        local = (progress * 5) - scene
        _draw_background(draw, self.width, self.height)
        values = _counter_series(self.post)
        multiplier = values[min(len(values) - 1, int(local * len(values)))]
        _draw_hud(draw, self.width, self.height, scene, progress, multiplier)
        if scene == 0:
            _draw_scene_paradox(draw, self.post, self.width, self.height, local)
        elif scene == 1:
            _draw_scene_passport(draw, self.post, self.width, self.height, local)
        elif scene == 2:
            _draw_scene_formula(draw, self.post, self.width, self.height, local)
        elif scene == 3:
            _draw_scene_waffle(draw, self.post, self.width, self.height, local)
        else:
            _draw_scene_summary(draw, self.post, self.width, self.height, local)
        _draw_karaoke(draw, self.width, self.height, self.words, time_s)
        return image


def _mux(frames_dir: Path, audio_path: Optional[Path], out_path: Path, fps: float) -> bool:
    args = ["ffmpeg", "-y", "-loglevel", "error", "-framerate", f"{fps:.4f}",
            "-i", str(frames_dir / "frame_%05d.png")]
    if audio_path and audio_path.is_file():
        args += ["-i", str(audio_path), "-c:a", "aac", "-b:a", "128k", "-shortest"]
    args += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out_path)]
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=600, check=False)
        if result.returncode != 0:
            return False
    except Exception:
        return False
    return out_path.is_file() and out_path.stat().st_size > 1000


def render_explainer_film(post: Post, out_path: str | Path, config: Any,
                          aspect: Optional[str] = None,
                          artifact: Optional[VoiceArtifact] = None,
                          max_seconds: Optional[float] = None) -> Optional[Path]:
    if not explainer_film_available():
        return None
    settings = explainer_settings(config, aspect)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    artifact = artifact or _explainer_voice(post, config)
    scene = ExplainerScene(post, settings["width"], settings["height"], artifact)
    duration = min(float(max_seconds or scene.duration), MAX_SECONDS)
    scene.duration = duration
    frames = max(2, min(settings["max_frames"], int(duration * settings["fps"])))
    audio_path = Path(artifact.mp3_path) if artifact and artifact.mp3_path and Path(artifact.mp3_path).is_file() else None
    if audio_path is None:
        try:
            from .sound import sonify

            audio_path = out_path.with_suffix(".wav")
            sonify(post, audio_path, seconds=duration)
        except Exception:
            audio_path = None
    with tempfile.TemporaryDirectory(prefix="sp_explainer_") as tmp:
        frames_dir = Path(tmp)
        for index in range(frames):
            time_s = duration * index / max(1, frames - 1)
            scene.render(time_s).save(frames_dir / f"frame_{index:05d}.png")
        ok = _mux(frames_dir, audio_path, out_path, frames / max(1e-6, duration))
    if audio_path and audio_path.suffix == ".wav":
        try:
            audio_path.unlink()
        except OSError:
            pass
    return out_path if ok else None


def explainer_film_for_post(post: Post, config: Any, aspect: Optional[str] = None,
                            out_dir: str | Path | None = None) -> Optional[Path]:
    settings = explainer_settings(config, aspect)
    directory = Path(out_dir) if out_dir else config.data_dir / "explainer_films"
    target = directory / f"{post.id}_{settings['aspect'].replace(':', 'x')}.mp4"
    key_path = directory / f"{post.id}_{settings['aspect'].replace(':', 'x')}.key"
    import hashlib
    script_hash = hashlib.sha1(build_explainer_script(post).encode("utf-8")).hexdigest()[:12]
    key = f"{post.id}|{post.title}|{post.formula_plain}|{settings['aspect']}|{settings['fps']}|{script_hash}"
    if target.is_file() and key_path.is_file() and key_path.read_text(encoding="utf-8") == key:
        return target
    produced = render_explainer_film(post, target, config, aspect=aspect)
    if produced is None:
        return None
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_text(key, encoding="utf-8")
    return produced

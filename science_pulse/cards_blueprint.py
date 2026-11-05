"""Дизайн `blueprint`: инженерная синяя миллиметровка со штампом ГОСТ/IEEE.

Реализован как детерминированная перекраска книжной вёрстки
(`cards_academic`): светлая бумага → глубокий синий, тушь → светлая линия,
поверх — миллиметровая сетка и технический штамп. Никакой новой вёрстки:
текст, формула и чертёж остаются теми же, меняется только «печать».
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from PIL import Image, ImageDraw, ImageFont

from .models import CardArtifact, Post

LOGGER = logging.getLogger(__name__)

BG = (10, 25, 47)          # #0A192F — глубокая инженерная синь
GRID_FINE = (20, 42, 72)   # миллиметровая сетка
GRID_MAJOR = (30, 58, 95)  # #1E3A5F — основная сетка
INK = (236, 242, 250)      # светлая «белая тушь»
GOLD = (212, 175, 55)      # штамп
MUTED = (126, 158, 200)


def _lerp(a: tuple, b: tuple, t: float) -> tuple:
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def _font(size: int, bold: bool = False) -> Any:
    try:
        import matplotlib

        name = "DejaVuSansMono-Bold.ttf" if bold else "DejaVuSansMono.ttf"
        path = Path(matplotlib.get_data_path()) / "fonts" / "ttf" / name
        if path.exists():
            return ImageFont.truetype(str(path), size)
    except Exception:  # pragma: no cover - шрифт всегда есть в matplotlib
        pass
    return ImageFont.load_default()


def _tone_map(image: Image.Image) -> Image.Image:
    """Светлая бумага → синий, тёмная тушь → светлая линия (через LUT)."""
    gray = image.convert("L")
    table = []
    for channel in range(3):
        for value in range(256):
            t = value / 255.0
            table.append(_lerp(INK, BG, t)[channel])
    return gray.convert("RGB").point(table)


def _draw_grid(draw: ImageDraw.ImageDraw, size: int, step: int = 27) -> None:
    for x in range(0, size + 1, step):
        draw.line([(x, 0), (x, size)], fill=GRID_FINE, width=1)
    for y in range(0, size + 1, step):
        draw.line([(0, y), (size, y)], fill=GRID_FINE, width=1)
    for x in range(0, size + 1, step * 4):
        draw.line([(x, 0), (x, size)], fill=GRID_MAJOR, width=1)
    for y in range(0, size + 1, step * 4):
        draw.line([(0, y), (size, y)], fill=GRID_MAJOR, width=1)


def _draw_stamp(draw: ImageDraw.ImageDraw, size: int, label: str) -> None:
    """Компактный штамп в свободной зоне справа (не задевает подвал и колонтитул)."""
    pad = int(size * 0.028)
    font = _font(max(11, int(size * 0.015)), bold=True)
    text = label[:32]
    width = int(draw.textlength(text, font=font)) + 22
    height = int(size * 0.042)
    top = int(size * 0.098)
    box = [size - pad - width, top, size - pad, top + height]
    draw.rectangle(box, outline=GOLD, width=2)
    draw.text((box[0] + 11, box[1] + int(height * 0.26)), text, fill=GOLD, font=font)


def apply_blueprint(image: Image.Image, *, label: str = "ГОСТ/IEEE · ЧЕРТЁЖ") -> Image.Image:
    """Перекрашивает светлую книжную страницу в инженерную миллиметровку."""
    size = image.size[0]
    base = _tone_map(image.convert("RGB"))
    draw = ImageDraw.Draw(base)
    _draw_grid(draw, size)
    _draw_stamp(draw, size, label)
    return base


def render_blueprint_card(post: Post, out_path: str | Path, size: int = 1080) -> Optional[CardArtifact]:
    """Книжная вёрстка → перекраска в `blueprint`. None, если движок недоступен."""
    try:
        from .cards_academic import render_academic_card

        target = Path(out_path)
        artifact = render_academic_card(post, target, size=size)
        if not artifact:
            return None
        with Image.open(artifact.path) as source:
            recolored = apply_blueprint(source)
        recolored.save(artifact.path, format="PNG", optimize=True)
        data = Path(artifact.path).read_bytes()
        return CardArtifact(path=str(artifact.path), data=data, width=size, height=size)
    except Exception as exc:  # pragma: no cover - защитный контур
        LOGGER.warning("blueprint недоступен (%s)", exc)
        return None

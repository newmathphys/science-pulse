"""Озвученные микро-видео: оживший книжный чертёж + сонификация формулы.

Рендер 30 кадров в академическом стиле (бумага `#FAF8F4`, DejaVu Serif,
формула Computer Modern) и склейка со звуком (`science_pulse.sound`) через
системный `ffmpeg`:

- `math`    — сложение гармоник Фурье (частичные суммы сходятся к кривой);
- `physics` — движение волнового пакета во времени;
- `cs`      — шаги сортировки массива (столбики меняются местами).

Кодек: `libx264` + `yuv420p` + `aac` + `+faststart` (совместимо с Telegram
`sendVideo`). Если libx264 недоступен — fallback на анимированный `.gif`.
"""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import Post
from .sound import DEFAULT_SECONDS, sonify

LOGGER = logging.getLogger(__name__)

PAPER = "#FAF8F4"
INK = "#111827"
ACCENT = "#8B2635"
FRAME_COUNT = 108
CANVAS = 1080


def video_available() -> bool:
    """Есть ли ffmpeg для сборки MP4/GIF."""
    return bool(shutil.which("ffmpeg"))


def _paper_style() -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({
        "font.family": "serif",
        "font.serif": ["DejaVu Serif", "Liberation Serif"],
        "mathtext.fontset": "cm",
        "text.color": INK,
        "figure.facecolor": PAPER,
        "axes.facecolor": PAPER,
        "savefig.facecolor": PAPER,
    })


def _title_lines(post: Post, width: int = 34) -> str:
    text = (getattr(post, "title", "") or "Science Pulse").strip()
    words, lines, current = text.split(), [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > width and current:
            lines.append(current)
            current = word
        else:
            current = candidate
        if len(lines) == 2:
            break
    if current and len(lines) < 2:
        lines.append(current)
    return "\n".join(lines)


def _formula_mathtext(post: Post) -> str:
    from .cards3b1b import _mathtext_normalize

    raw = (getattr(post, "formula_latex", "") or getattr(post, "formula_plain", "") or "").strip()
    if not raw:
        return ""
    if len(raw) > 2 and raw.startswith("$") and raw.endswith("$"):
        raw = raw[1:-1]
    return f"${_mathtext_normalize(raw)}$"


def _notes(post: Post) -> List[int]:
    numbers = [int(match) for match in re.findall(r"\d+", f"{post.title} {post.formula_plain}")][:5]
    return numbers or [1, 2, 3, 5, 8]


def _draw_frame(ax: Any, post: Post, progress: float, xs: Any) -> None:
    """Рисует содержимое кадра для домена поста (0 ≤ progress ≤ 1)."""
    import numpy as np

    domain = getattr(post, "domain", "math")
    ax.spines[["top", "right"]].set_visible(False)
    ax.axhline(0.0, color="#B0AA9E", lw=0.8)
    ax.set_xticks([])
    ax.set_yticks([])

    if domain == "physics":
        # волновой пакет бежит слева направо, огибающая гауссова
        center = -2.6 + 5.2 * progress
        packet = np.exp(-((xs - center) ** 2) / 1.1) * np.cos(6.0 * (xs - center))
        ax.fill_between(xs, np.abs(packet), -np.abs(packet), color="#8B2635", alpha=0.10)
        ax.plot(xs, packet, color="#2F4B7C", lw=2.4)
        ax.plot(xs, np.abs(packet), color="#B0AA9E", lw=1.0, linestyle="--")
        ax.plot(xs, -np.abs(packet), color="#B0AA9E", lw=1.0, linestyle="--")
        ax.set_ylim(-1.25, 1.25)
        ax.text(-3.1, 1.02, f"ψ(x, t), t = {progress * 100:.0f}%", fontsize=11, color="#6B6458")
        return

    if domain == "cs":
        values = _notes(post)
        work = list(values)
        steps = 0
        for i in range(1, len(work)):
            j = i
            while j > 0 and work[j - 1] > work[j]:
                work[j - 1], work[j] = work[j], work[j - 1]
                j -= 1
        total_steps = max(1, len(work) * (len(work) - 1) // 2)
        target = int(progress * total_steps)
        # воспроизводим сортировку вставками до нужного шага
        state = list(values)
        active = 0
        counter = 0
        for i in range(1, len(state)):
            j = i
            while j > 0 and state[j - 1] > state[j]:
                state[j - 1], state[j] = state[j], state[j - 1]
                counter += 1
                if counter >= target:
                    active = j
                    break
                j -= 1
            if counter >= target:
                break
        positions = np.arange(len(state))
        colors = [ACCENT if index == active else "#2F4B7C" for index in range(len(state))]
        ax.bar(positions, state, color=colors, width=0.6)
        ax.set_xticks(positions)
        ax.set_xticklabels([str(value) for value in state], fontsize=11)
        ax.set_ylim(0, max(values) + 2)
        ax.text(-0.6, max(values) + 1.2, f"сортировка: шаг {target}/{total_steps}", fontsize=11, color="#6B6458")
        return

    # math: сложение гармоник Фурье — частичные суммы сходятся к пилообразной кривой
    order = 1 + int(progress * 7)
    target = np.zeros_like(xs)
    for k in range(1, order + 1):
        harmonic = np.sin(k * xs) / k
        ax.plot(xs, harmonic * 0.45, color="#B0AA9E", lw=0.8, alpha=0.7)
        target += harmonic
    ax.plot(xs, target * 0.45, color=ACCENT, lw=2.6)
    ax.set_ylim(-0.95, 0.95)
    ax.text(-3.1, 0.78, f"ряд Фурье: {order} гармоник", fontsize=11, color="#6B6458")


def _render_frames(post: Post, out_dir: Path, frames: int = FRAME_COUNT) -> int:
    """Сохраняет `frames` PNG-кадров книжной страницы, возвращает их число."""
    import numpy as np

    _paper_style()
    import matplotlib.pyplot as plt

    xs = np.linspace(-3.2, 3.2, 400)
    fig = plt.figure(figsize=(CANVAS / 100.0, CANVAS / 100.0), dpi=100)
    fig.text(0.5, 0.955, _title_lines(post), ha="center", va="top",
             fontsize=22, fontweight="bold", linespacing=1.3)
    ax = fig.add_axes([0.09, 0.30, 0.82, 0.53])
    formula = _formula_mathtext(post)
    if formula:
        fig.text(0.5, 0.17, formula, ha="center", va="center", fontsize=28, color=INK)
    fig.text(0.5, 0.055, "newmathphys.com · @newmathphys",
             ha="center", fontsize=12, color="#6B6458")

    written = 0
    for index in range(frames):
        progress = index / max(frames - 1, 1)
        ax.clear()
        ax.set_facecolor(PAPER)
        _draw_frame(ax, post, progress, xs)
        fig.savefig(out_dir / f"frame_{index:03d}.png")
        written += 1
    plt.close(fig)
    return written


def _run_ffmpeg(args: List[str], timeout: int = 300) -> bool:
    try:
        result = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args],
                                capture_output=True, text=True, timeout=timeout, check=False)
        if result.returncode != 0:
            LOGGER.warning("ffmpeg: %s", (result.stderr or "")[:300])
            return False
        return True
    except Exception as exc:
        LOGGER.warning("ffmpeg: %s", exc)
        return False


def _mux_mp4(frames_dir: Path, wav_path: Optional[Path], out_mp4: Path, fps: float) -> bool:
    """Склейка кадров + звука в MP4 (H.264 yuv420p + AAC + faststart)."""
    args = ["-framerate", f"{fps:.4f}", "-i", str(frames_dir / "frame_%03d.png")]
    if wav_path and wav_path.is_file():
        args += ["-i", str(wav_path), "-c:a", "aac", "-b:a", "128k", "-shortest"]
    args += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out_mp4)]
    return _run_ffmpeg(args) and out_mp4.is_file() and out_mp4.stat().st_size > 1000


def _mux_gif(frames_dir: Path, out_gif: Path, fps: float) -> bool:
    """Fallback: анимированный GIF (если libx264 недоступен)."""
    palette = out_gif.with_suffix(".palette.png")
    ok = _run_ffmpeg(["-framerate", f"{fps:.4f}", "-i", str(frames_dir / "frame_%03d.png"),
                      "-vf", "palettegen", str(palette)])
    ok = ok and _run_ffmpeg(["-framerate", f"{fps:.4f}", "-i", str(frames_dir / "frame_%03d.png"),
                             "-i", str(palette), "-lavfi", "paletteuse", str(out_gif)])
    try:
        palette.unlink()
    except OSError:
        pass
    return ok and out_gif.is_file() and out_gif.stat().st_size > 1000


def render_video(post: Post, out_path: str | Path, seconds: float = DEFAULT_SECONDS,
                 frames: int = FRAME_COUNT, with_sound: bool = True) -> Optional[Path]:
    """Собирает озвученное микро-видео поста. Возвращает путь (или None)."""
    if not video_available():
        LOGGER.warning("ffmpeg не найден — видео недоступно")
        return None
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fps = frames / max(seconds, 0.1)
    with tempfile.TemporaryDirectory(prefix="sp_video_") as tmp:
        work = Path(tmp)
        written = _render_frames(post, work, frames=frames)
        if written < 2:
            return None
        wav_path = None
        if with_sound:
            wav_path = work / "sound.wav"
            sonify(post, wav_path, seconds=seconds)
        if _mux_mp4(work, wav_path, out_path, fps):
            return out_path
        LOGGER.warning("MP4 не собрался, fallback на GIF")
        gif_path = out_path.with_suffix(".gif")
        if _mux_gif(work, gif_path, fps):
            return gif_path
    return None


def video_settings(config: Any) -> Dict[str, Any]:
    raw = dict((getattr(config, "raw", {}) or {}).get("video") or {})
    return {
        "enabled": bool(raw.get("enabled", False)),
        "every_nth_post": int(raw.get("every_nth_post", 3)),
        "seconds": float(raw.get("seconds", DEFAULT_SECONDS)),
        "frames": int(raw.get("frames", FRAME_COUNT)),
        "with_sound": bool(raw.get("with_sound", True)),
    }


def video_for_post(post: Post, config: Any, out_dir: str | Path | None = None) -> Optional[Path]:
    """Видео поста с кэшем в `data/video/<id>.mp4` (детерминированно)."""
    settings = video_settings(config)
    directory = Path(out_dir) if out_dir else config.data_dir / "video"
    target = directory / f"{post.id}.mp4"
    key_path = directory / f"{post.id}.key"
    key = f"{post.domain}|{post.title}|{post.formula_plain}|{settings['seconds']}|{settings['frames']}|{settings['with_sound']}"
    if target.is_file() and key_path.is_file() and key_path.read_text(encoding="utf-8") == key:
        return target
    produced = render_video(post, target, seconds=settings["seconds"],
                            frames=settings["frames"], with_sound=settings["with_sound"])
    if produced is None:
        return None
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_text(key, encoding="utf-8")
    return produced
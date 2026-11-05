"""Moku3D — 5-актовый короткометражный математический фильм.

Референс: серия `Moku3D` на `mokujiro.com` — «One equation per study, made
visible as a short film». Каждый акт длится `SECONDS_PER_ACT` секунд и несёт
**ровно одну короткую строку смысла** внизу кадра плюс одно движение камеры.
В центре — только вычисляемая геометрия (гравитация, волны, гармоники,
решётка алгоритма) с перспективной проекцией и сортировкой по глубине.
"""
from __future__ import annotations

import logging
import math
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .models import Post

LOGGER = logging.getLogger(__name__)

BG = (8, 10, 15)          # #080A0F — кино-фон
INK = (232, 238, 246)
MUTED = (118, 132, 150)
ACCENT = (88, 196, 221)   # основная кривая
GOLD = (250, 204, 21)     # вектор/производная
GREEN = (131, 193, 103)   # инвариант/оптимум
RED = (252, 98, 85)       # деградация/критическая точка

ACTS = 5
ACT_ROMAN = ("I", "II", "III", "IV", "V")
SECONDS_PER_ACT = 6.0  # × 5 актов = 30 секунд
FPS = 24
SIZE = 720
LINE_LIMIT = 84


def film_available() -> bool:
    """Есть ли `ffmpeg` для сборки `.mp4`."""
    return shutil.which("ffmpeg") is not None


def moku3d_settings(config: Any = None) -> Dict[str, Any]:
    raw = dict((getattr(config, "raw", {}) or {}).get("moku3d") or {}) if config else {}
    return {
        "size": int(raw.get("size", SIZE)),
        "fps": int(raw.get("fps", FPS)),
        "seconds_per_act": float(raw.get("seconds_per_act", SECONDS_PER_ACT)),
        "audio": bool(raw.get("audio", True)),
    }


def _lerp(a: Tuple[int, int, int], b: Tuple[int, int, int], t: float) -> Tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def _font(size: int, bold: bool = True, mono: bool = False) -> Any:
    try:
        import matplotlib

        name = "DejaVuSansMono-Bold.ttf" if mono else ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")
        path = Path(matplotlib.get_data_path()) / "fonts" / "ttf" / name
        if path.exists():
            return ImageFont.truetype(str(path), size)
    except Exception:  # pragma: no cover - шрифты matplotlib всегда на месте
        pass
    return ImageFont.load_default()


def _one_line(value: Any, limit: int = LINE_LIMIT) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    dot = cut.rfind(". ")
    return (cut[: dot + 1] if dot > limit * 0.5 else cut.rstrip() + "…")


def storyboard(post: Post) -> List[Dict[str, Any]]:
    """Раскадровка из 5 актов: у каждого — заголовок и РОВНО одна строка текста."""
    meta = getattr(post, "meta", {}) or {}
    hook = _one_line(getattr(post, "hook", "") or "", 78)
    formula = _one_line(
        getattr(post, "formula_plain", "") or getattr(post, "formula_latex", "") or "", 70
    )
    example = ""
    try:
        from .post_proof import build_post_proof

        example = _one_line((build_post_proof(post) or {}).get("computed_example") or "", 78)
    except Exception:
        example = ""
    question = ""
    try:
        from .challenge import build_challenge

        question = _one_line((build_challenge(post) or {}).get("question") or "", 78)
    except Exception:
        question = ""
    concept = _one_line(meta.get("concept") or "", 30)

    acts = [
        {"act": 1, "roman": ACT_ROMAN[0], "title": "Постановка",
         "line": hook or f"Одна формула: {formula}" or "Одна формула — один фильм."},
        {"act": 2, "roman": ACT_ROMAN[1], "title": "Закон в действии",
         "line": f"Закон включается: {formula}" if formula else "Закон включается — система приходит в движение."},
        {"act": 3, "roman": ACT_ROMAN[2], "title": "Смена ракурса",
         "line": f"Поворот камеры открывает структуру: {concept}" if concept
                 else "Поворот камеры открывает скрытую структуру."},
        {"act": 4, "roman": ACT_ROMAN[3], "title": "Точный расчёт",
         "line": example or "Меняем параметр — форма мгновенно перестраивается."},
        {"act": 5, "roman": ACT_ROMAN[4], "title": "Инвариант и задача",
         "line": question or "Инвариант сохраняется при любом повороте камеры."},
    ]
    return acts


def _seed(post: Post) -> int:
    return sum(ord(char) for char in (getattr(post, "id", "") or "moku3d")) % 10_000


def _rotation(theta: float, phi: float) -> np.ndarray:
    """Матрица камеры: азимут `theta` и наклон `phi`."""
    ct, st = math.cos(theta), math.sin(theta)
    cp, sp = math.cos(phi), math.sin(phi)
    rz = np.array([[ct, -st, 0.0], [st, ct, 0.0], [0.0, 0.0, 1.0]])
    rx = np.array([[1.0, 0.0, 0.0], [0.0, cp, -sp], [0.0, sp, cp]])
    return rx @ rz


class Scene3D:
    """Детерминированная 3D-геометрия фильма: считается один раз на пост.

    `physics` — задача трёх тел (гравитация Ньютона);
    `math`    — 3D-кривая Фурье, число гармоник меняется в Акте IV (n=1→3);
    `cs`      — решётка 3×3×3 и трассируемый путь алгоритма (порядок меняется).
    """

    def __init__(self, post: Post):
        self.post = post
        self.seed = _seed(post)
        self.kind = "physics" if post.domain == "physics" else ("cs" if post.domain == "cs" else "math")
        if self.kind == "physics":
            self.trajectory, self.trajectory_raw = self._nbody()
        elif self.kind == "cs":
            self.nodes, self.path_a, self.path_b = self._lattice()
        else:
            self.curve_n1 = self._harmonics(1)
            self.curve_n3 = self._harmonics(3)

    # ── физика: три тела ──────────────────────────────────────────────────
    def _nbody(self, steps: int = 2000, dt: float = 0.003, g: float = 1.0) -> Tuple[np.ndarray, np.ndarray]:
        """Классическая «восьмёрка» трёх тел (Ченсинер–Монтгомери).

        Три равные массы танцуют по одной замкнутой восьмёрке — устойчивое
        периодическое решение, идеальный сюжет для короткометражки. Интегрирование
        — leapfrog (velocity Verlet), чтобы орбита не «расплывалась» за фильм.
        """
        self.dt = dt
        p1 = np.array([0.97000436, -0.24308753, 0.0])
        v3 = np.array([-0.93240737, -0.86473146, 0.0])
        pos = np.stack([p1, -p1, np.zeros(3)])
        vel = np.stack([-v3 / 2.0, -v3 / 2.0, v3])
        mass = np.ones(3)

        def accel(current: np.ndarray) -> np.ndarray:
            diff = current[None, :, :] - current[:, None, :]
            dist = np.sqrt((diff ** 2).sum(-1) + 1e-6)
            return (g * mass[None, :, None] * diff / dist[..., None] ** 3).sum(1)

        out = np.zeros((steps, 3, 3))
        acceleration = accel(pos)
        for step in range(steps):
            vel = vel + 0.5 * acceleration * dt
            pos = pos + vel * dt
            acceleration = accel(pos)
            vel = vel + 0.5 * acceleration * dt
            out[step] = pos
        out -= out.mean(axis=1, keepdims=True)  # центр масс — в начале координат
        # Наклон плоскости «восьмёрки»: 3D-камера всегда видит объём, а не линию.
        tilt = 0.62
        ct, st = math.cos(tilt), math.sin(tilt)
        out = out @ np.array([[1.0, 0.0, 0.0], [0.0, ct, -st], [0.0, st, ct]]).T
        span = float(np.percentile(np.abs(out), 97)) or 1.0
        raw = out.copy()
        return out / max(span, 1e-6), raw


    # ── математика: 3D-кривая Фурье ───────────────────────────────────────
    def _harmonics(self, n: int, points: int = 620) -> np.ndarray:
        t = np.linspace(0.0, 2.0 * math.pi, points)
        x = np.zeros_like(t)
        y = np.zeros_like(t)
        z = np.zeros_like(t)
        for k in range(1, n + 1):
            x += np.cos(k * t) / k
            y += np.sin(k * t) / k
            z += np.sin((k * t) / 2.0) / k
        return np.stack([x, y, z], axis=1) * 0.62

    # ── информатика: решётка и путь ───────────────────────────────────────
    def _lattice(self) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        rng = np.random.default_rng(self.seed)
        grid = np.array([[x, y, z] for x in (-1, 0, 1) for y in (-1, 0, 1) for z in (-1, 0, 1)], dtype=float)
        values = rng.random(len(grid))
        path_a = np.argsort(values)
        path_b = np.argsort(values * 0.6 + np.abs(grid).sum(1) * 0.4)
        return grid * 0.72, path_a, path_b

    # ── кадр ──────────────────────────────────────────────────────────────
    def frame(self, act: int, act_progress: float, global_progress: float) -> Dict[str, Any]:
        data: Dict[str, Any] = {"kind": self.kind, "trails": [], "points": None, "accent": ACCENT, "counter": ""}
        if self.kind == "physics":
            steps = len(self.trajectory)
            index = max(1, int(global_progress * (steps - 1)))
            data["points"] = self.trajectory[index]
            trail_len = max(120, int(400 + 700 * act_progress))
            for body in range(3):
                start = max(0, index - trail_len)
                data["trails"].append(self.trajectory[start : index + 1, body, :])
            data["accent"] = ACCENT
            raw = self.trajectory_raw
            velocity = (raw[min(steps - 1, index + 1)] - raw[index]) / getattr(self, "dt", 0.003)
            data["counter"] = f"t = {index * getattr(self, 'dt', 0.003):.2f} с · |v| = {np.linalg.norm(velocity):.3f}"
        elif self.kind == "cs":
            path = self.path_a if act <= 3 else self.path_b
            total = len(path)
            traced = max(2, int(act_progress * total) if act <= 3 else int((act_progress + 0.2) * total))
            traced = min(total, traced)
            order = path[:traced]
            data["points"] = self.nodes
            data["trails"] = [self.nodes[order]]
            data["accent"] = GREEN
            data["counter"] = f"шаг = {traced}/{total} · порядок {'A' if act <= 3 else 'B'}"
        else:
            curve = self.curve_n1 if act <= 3 else self.curve_n3
            index = max(1, int(global_progress * (len(curve) - 1)))
            data["points"] = curve
            data["trails"] = [curve[: index + 1]]
            data["accent"] = GOLD
            data["counter"] = f"n = {1 if act <= 3 else 3} · t = {global_progress * 2.0 * math.pi:.2f}"
        return data


def _project(points: np.ndarray, rotation: np.ndarray, size: int, scale: float = 0.34) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Перспективная проекция 3D → 2D с глубиной (для Z-буфера яркости)."""
    rotated = np.asarray(points, dtype=float) @ rotation.T
    depth = rotated[:, 2]
    focal = 3.2
    factor = focal / (focal - np.clip(depth, -1.8, 1.8))
    xs = size / 2 + rotated[:, 0] * factor * size * scale
    ys = size / 2 - rotated[:, 1] * factor * size * scale
    return xs, ys, depth


def _camera(act: int, act_progress: float, global_progress: float) -> np.ndarray:
    """Камера: в Акте III — плавный облёт, в остальных актах — медленный дрейф."""
    theta = 0.45 + global_progress * 0.55
    if act == 3:
        theta += act_progress * 2.0 * math.pi
    phi = 0.34 + 0.26 * math.sin(global_progress * math.pi)
    return _rotation(theta, phi)


def _fade(act_progress: float, edge: float = 0.14) -> float:
    """Плавное появление/угасание строки акта (alpha fade)."""
    if act_progress < edge:
        return act_progress / edge
    if act_progress > 1.0 - edge:
        return max(0.0, (1.0 - act_progress) / edge)
    return 1.0


def _fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: float,
    base_size: int,
    bold: bool = True,
    mono: bool = False,
    min_size: int = 12,
) -> Tuple[Any, str]:
    """Подбирает кегль так, чтобы строка гарантированно влезла в кадр."""
    value = str(text or "")
    if not value:
        return _font(base_size, bold=bold, mono=mono), ""
    size = max(min_size, base_size)
    while size > min_size:
        font = _font(size, bold=bold, mono=mono)
        if draw.textlength(value, font=font) <= max_width:
            return font, value
        size -= 1
    font = _font(min_size, bold=bold, mono=mono)
    while value and draw.textlength(value + "…", font=font) > max_width:
        value = value[:-1]
    return font, (value.rstrip() + "…") if value else ""



def _draw_geometry(draw: ImageDraw.ImageDraw, data: Dict[str, Any], rotation: np.ndarray, size: int) -> None:
    accent = data["accent"]
    for trail in data.get("trails") or []:
        if len(trail) < 2:
            continue
        xs, ys, depth = _project(trail, rotation, size)
        mean_depth = float(np.mean(depth))
        brightness = 0.55 + 0.45 * (mean_depth + 1.6) / 3.2
        width = 3 if mean_depth > 0.3 else (2 if mean_depth > -0.5 else 1)
        draw.line(list(zip(xs.tolist(), ys.tolist())), fill=_lerp(BG, accent, min(1.0, brightness)),
                  width=width, joint="curve")
    points3d = data.get("points")
    if points3d is None:
        return
    xs, ys, depth = _project(points3d, rotation, size)
    radius_base = max(2, int(size * 0.0055))
    for index in np.argsort(depth):  # дальние — раньше (Z-буфер)
        near = (float(depth[index]) + 1.6) / 3.2
        radius = radius_base + int(round(radius_base * 1.6 * near))
        draw.ellipse(
            [xs[index] - radius, ys[index] - radius, xs[index] + radius, ys[index] + radius],
            fill=_lerp(BG, accent, 0.35 + 0.65 * min(1.0, near)),
        )


def _draw_hud(draw: ImageDraw.ImageDraw, post: Post, act_info: Dict[str, Any], data: Dict[str, Any], size: int) -> None:
    """Технический штамп: `STUDY § X.Y`, уравнение и счётчик (без наложений)."""
    pad = int(size * 0.035)
    mono_size = max(11, int(size * 0.017))
    section = str((getattr(post, "meta", {}) or {}).get("section_num") or "").strip()
    stamp = f"STUDY § {section} · ТОЧНАЯ ЧИСЛЕННАЯ МОДЕЛЬ" if section else "STUDY · ТОЧНАЯ ЧИСЛЕННАЯ МОДЕЛЬ"
    formula = _one_line(getattr(post, "formula_plain", "") or getattr(post, "formula_latex", "") or "", 60)

    act_label = f"АКТ {act_info['roman']} · {act_info['title']}"
    _, act_text = _fit_text(draw, act_label, size * 0.42, mono_size, mono=True, min_size=9)
    act_font = _font(max(9, mono_size - 2), bold=True, mono=True)
    act_width = draw.textlength(act_text, font=act_font)
    avail = max(size * 0.30, size - 2 * pad - act_width - pad)

    font, stamp_text = _fit_text(draw, stamp, avail, mono_size, mono=True, min_size=9)
    draw.text((pad, pad), stamp_text, fill=MUTED, font=font)
    if formula:
        formula_font, formula_text = _fit_text(draw, formula, avail, mono_size, mono=True, min_size=9)
        draw.text(
            (pad, pad + int(size * 0.026)),
            formula_text,
            fill=_lerp(BG, data["accent"], 0.75),
            font=formula_font,
        )
    counter_font, counter_text = _fit_text(
        draw, data.get("counter") or "", avail, mono_size, mono=True, min_size=9
    )
    draw.text((pad, pad + int(size * 0.052)), counter_text, fill=MUTED, font=counter_font)
    draw.text((size - pad - act_width, pad), act_text, fill=_lerp(BG, INK, 0.6), font=act_font)


def _draw_act_line(draw: ImageDraw.ImageDraw, text: str, alpha: float, size: int) -> None:
    """Ровно ОДНА строка смысла текущего акта внизу кадра (кегль подгоняется)."""
    if not text:
        return
    pad = int(size * 0.035)
    font, fitted = _fit_text(
        draw, text, size - 2 * pad, max(15, int(size * 0.036)), bold=True, min_size=13
    )
    rule_y = int(size * 0.845)
    draw.line([(pad, rule_y), (size - pad, rule_y)], fill=_lerp(BG, MUTED, 0.55 * alpha), width=2)
    draw.text((pad, rule_y + int(size * 0.022)), fitted, fill=_lerp(BG, INK, alpha), font=font)


def render_frames(post: Post, out_dir: Path, settings: Optional[Dict[str, Any]] = None) -> int:
    """Рендерит все кадры фильма в `out_dir` (PNG `frame_00000.png` …)."""
    conf = settings or moku3d_settings(None)
    size = int(conf["size"])
    fps = int(conf["fps"])
    spa = float(conf["seconds_per_act"])
    total_seconds = spa * ACTS
    frames = max(ACTS, int(round(total_seconds * fps)))
    scene = Scene3D(post)
    acts = storyboard(post)
    out_dir.mkdir(parents=True, exist_ok=True)
    for index in range(frames):
        global_time = index / fps
        global_progress = global_time / total_seconds
        act = min(ACTS - 1, int(global_time / spa))
        act_progress = (global_time - act * spa) / spa
        act_info = acts[act]
        data = scene.frame(act + 1, act_progress, global_progress)
        image = Image.new("RGB", (size, size), BG)
        draw = ImageDraw.Draw(image)
        _draw_geometry(draw, data, _camera(act + 1, act_progress, global_progress), size)
        _draw_hud(draw, post, act_info, data, size)
        _draw_act_line(draw, act_info["line"], _fade(act_progress), size)
        image.save(out_dir / f"frame_{index:05d}.png", format="PNG")
    return frames


def _mux_mp4(frames_dir: Path, wav_path: Optional[Path], out_mp4: Path, fps: int, timeout: int = 600) -> bool:
    args = ["ffmpeg", "-y", "-framerate", str(fps), "-i", str(frames_dir / "frame_%05d.png")]
    has_audio = bool(wav_path and Path(wav_path).exists())
    if has_audio:
        args += ["-i", str(wav_path)]
    args += [
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast",
        "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-movflags", "+faststart",
    ]
    if has_audio:
        args += ["-c:a", "aac", "-b:a", "128k", "-shortest"]
    args.append(str(out_mp4))
    try:
        proc = subprocess.run(args, capture_output=True, timeout=timeout)
    except Exception as exc:  # pragma: no cover - сбой внешнего процесса
        LOGGER.warning("Moku3D: ffmpeg не сработал (%s)", exc)
        return False
    if proc.returncode != 0:
        LOGGER.warning("Moku3D: ffmpeg код %s: %s", proc.returncode, (proc.stderr or b"")[-300:])
        return False
    return out_mp4.exists() and out_mp4.stat().st_size > 20_000


def render_moku3d_short_film(
    post: Post,
    out_path: str | Path,
    audio_path: Optional[str | Path] = None,
    config: Any = None,
    keep_frames: bool = False,
) -> Optional[Path]:
    """5-актовый фильм Moku3D: 30 секунд, 5 сцен, одна строка текста на акт.

    Возвращает путь к `.mp4` или None, если `ffmpeg` недоступен.
    """
    if not film_available():
        LOGGER.warning("Moku3D: ffmpeg не найден — фильм не собран")
        return None
    settings = moku3d_settings(config)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    work = Path(out).parent / f"_moku3d_{post.id}"
    frames_dir = work / "frames"
    try:
        count = render_frames(post, frames_dir, settings)
        wav = Path(audio_path) if audio_path else None
        if wav is None and settings["audio"]:
            try:
                from .sound import sonify

                target = work / "ambient.wav"
                sonify(post, target, seconds=settings["seconds_per_act"] * ACTS)
                wav = target if target.exists() else None
            except Exception as exc:
                LOGGER.warning("Moku3D: звук недоступен (%s)", exc)
        ok = _mux_mp4(frames_dir, wav, out, settings["fps"])
        if not ok:
            return None
        LOGGER.info("Moku3D: %s кадров → %s", count, out)
        return out
    finally:
        if not keep_frames:
            shutil.rmtree(work, ignore_errors=True)


def film_for_post(post: Post, config: Any, out_dir: str | Path | None = None) -> Optional[Path]:
    """Кэшированный фильм поста: `data/films/<id>.mp4`."""
    base = Path(out_dir) if out_dir else (Path(getattr(config, "data_dir", "data")) / "films")
    target = base / f"{post.id}.mp4"
    if target.exists() and target.stat().st_size > 20_000:
        return target
    return render_moku3d_short_film(post, target, config=config)



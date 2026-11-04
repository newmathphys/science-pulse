"""Акустическая сонификация формул и алгоритмов (детерминированный звук).

Синтез на стандартном `wave` + NumPy: никаких внешних сервисов, чистый расчёт.
Для каждой дисциплины — свой «математический звук»:

- `math`   — сложение гармоник Фурье (основной тон + обертоны);
- `physics`— частотно-модулированный волновой пакет (чирп с гауссовой огибающей);
- `cs`     — звук шагов алгоритма (сортировка: сравнения и обмены как тон-«клики»).

Звук детерминирован: один и тот же пост даёт один и тот же файл (без рандома).
"""
from __future__ import annotations

import logging
import math
import re
import wave
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

LOGGER = logging.getLogger(__name__)

SAMPLE_RATE = 22050
DEFAULT_SECONDS = 3.6
# Гармонический строй: ноты пентатоники до мажор (Гц), звучат «научно» и не режут слух.
HARMONIC_SCALE_HZ = (261.63, 293.66, 329.63, 392.00, 440.00, 523.25, 587.33, 659.25, 783.99, 880.00)


def _envelope(n: int, attack: float = 0.06, release: float = 0.25) -> np.ndarray:
    """Мягкая огибающая (без щелчков на краях)."""
    env = np.ones(n)
    a = max(1, int(n * attack))
    r = max(1, int(n * release))
    env[:a] = np.linspace(0.0, 1.0, a)
    env[-r:] = np.linspace(1.0, 0.0, r)
    return env


def _notes_from_post(post: Any) -> List[float]:
    """Спектр нот из содержимого поста: индексы в гармоническом строе."""
    seed_text = f"{getattr(post, 'title', '')} {getattr(post, 'formula_plain', '')}"
    numbers = [int(match) for match in re.findall(r"\d+", seed_text)][:6]
    if not numbers:
        numbers = [1, 2, 3, 5, 8]
    return [HARMONIC_SCALE_HZ[value % len(HARMONIC_SCALE_HZ)] for value in numbers]


def _sonify_math(t: np.ndarray, post: Any) -> np.ndarray:
    """Сложение гармоник Фурье: основной тон + обертоны с падающей амплитудой."""
    notes = _notes_from_post(post)
    base = notes[0]
    signal = np.zeros_like(t)
    for index in range(1, 6):
        signal += (1.0 / index) * np.sin(2.0 * np.pi * base * index * t)
    return signal / 2.0


def _sonify_physics(t: np.ndarray, post: Any) -> np.ndarray:
    """Частотно-модулированный волновой пакет: чирп со гауссовой огибающей."""
    notes = _notes_from_post(post)
    f0, f1 = notes[0], notes[-1]
    duration = float(t[-1] - t[0]) or DEFAULT_SECONDS
    freq = f0 + (f1 - f0) * (t / duration)
    phase = 2.0 * np.pi * np.cumsum(freq) / SAMPLE_RATE
    center = duration / 2.0
    gauss = np.exp(-((t - center) ** 2) / (2.0 * (duration / 5.0) ** 2))
    return np.sin(phase) * gauss


def _sonify_cs(t: np.ndarray, post: Any) -> np.ndarray:
    """Звук шагов алгоритма: детерминированная последовательность «кликов» сортировки."""
    notes = _notes_from_post(post)
    values = [int(match) for match in re.findall(r"\d+", f"{getattr(post, 'code', '')}")][:8] or [5, 3, 8, 1, 9, 2]
    # детерминированная сортировка вставками: пишем «тон» на каждый обмен
    steps: List[float] = []
    work = list(values)
    for i in range(1, len(work)):
        j = i
        while j > 0 and work[j - 1] > work[j]:
            work[j - 1], work[j] = work[j], work[j - 1]
            steps.append(float(work[j]))
            j -= 1
    if not steps:
        steps = [float(value) for value in values]
    signal = np.zeros_like(t)
    per = max(1, len(t) // max(len(steps), 1))
    for index, value in enumerate(steps):
        start = index * per
        stop = min(len(t), start + per)
        if stop <= start:
            break
        freq = notes[int(value) % len(notes)]
        chunk = np.sin(2.0 * np.pi * freq * t[start:stop])
        signal[start:stop] += chunk * _envelope(stop - start, attack=0.05, release=0.6)
    return signal


SONIFIERS = {"math": _sonify_math, "physics": _sonify_physics, "cs": _sonify_cs}


def sonify(post: Any, out_wav: str | Path, seconds: float = DEFAULT_SECONDS) -> Dict[str, Any]:
    """Сонофицирует пост в WAV (детерминированно). Возвращает описание."""
    domain = getattr(post, "domain", "math")
    sonifier = SONIFIERS.get(domain, _sonify_math)
    n = int(SAMPLE_RATE * seconds)
    t = np.arange(n) / SAMPLE_RATE
    signal = sonifier(t, post)
    signal = signal * _envelope(n)
    peak = float(np.max(np.abs(signal))) or 1.0
    samples = np.int16(np.clip(signal / peak * 0.85, -1.0, 1.0) * 32767)

    out_wav = Path(out_wav)
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out_wav), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(samples.tobytes())
    return {
        "path": str(out_wav),
        "seconds": round(seconds, 2),
        "sample_rate": SAMPLE_RATE,
        "domain": domain,
        "notes_hz": _notes_from_post(post),
    }
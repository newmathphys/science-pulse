"""Пять режимов подачи: лента дышит, а не повторяет один шаблон.

Психология внимания: если в каждом посте требовать решения задачи, читатель
привыкает и перестаёт читать низ поста (habituation). Поэтому «Задача» выходит
дозированно — только в режиме `interactive_challenge` (по умолчанию каждый
4-й выпуск), а основная масса постов — чистое знание.

Режимы:

- `pure_knowledge`        — глубокий разбор без задачи (основной режим);
- `satellite_lab`         — спутниковый/геофизический спецвыпуск (диптих);
- `cheatsheet_save`       — карточка-шпаргалка для «Избранного»;
- `moku3d_film`           — 5-актовый короткометражный фильм;
- `interactive_challenge` — выпуск с задачей и скрытым ответом.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

MODES = (
    "pure_knowledge",
    "satellite_lab",
    "cheatsheet_save",
    "moku3d_film",
    "interactive_challenge",
)
CHALLENGE_MODES = ("interactive_challenge",)
DEFAULT_MODE = "pure_knowledge"
KV_COUNTER = "post_mode_counter"

# Доли режимов при ротации (детерминированно, без случайности).
WEIGHTS: Dict[str, int] = {
    "pure_knowledge": 6,
    "satellite_lab": 2,
    "cheatsheet_save": 1,
    "moku3d_film": 1,
    "interactive_challenge": 1,
}

LABELS = {
    "pure_knowledge": "Чистое знание",
    "satellite_lab": "Спутниковая лаборатория",
    "cheatsheet_save": "Шпаргалка в «Избранное»",
    "moku3d_film": "Фильм Moku3D",
    "interactive_challenge": "Задача выпуска",
}


def settings(config: Any) -> Dict[str, Any]:
    raw = dict((getattr(config, "raw", {}) or {}).get("post_modes") or {})
    weights = dict(WEIGHTS)
    weights.update({key: int(value) for key, value in (raw.get("weights") or {}).items() if key in MODES})
    return {
        "enabled": bool(raw.get("enabled", True)),
        "challenge_every_nth": max(1, int(raw.get("challenge_every_nth", 4))),
        "weights": weights,
    }


def shows_challenge(mode: str) -> bool:
    """Выводить ли блок «Задача» (и скрытый ответ) в этом выпуске."""
    return str(mode or DEFAULT_MODE) in CHALLENGE_MODES


def _rotation(weights: Dict[str, int], index: int) -> str:
    """Детерминированная взвешенная ротация: без random и без сюрпризов."""
    sequence = []
    for name in MODES:
        sequence.extend([name] * max(0, int(weights.get(name, 0))))
    if not sequence:
        return DEFAULT_MODE
    return sequence[index % len(sequence)]


def mode_for_post(storage: Any, config: Any, post: Any, theme: str = "") -> str:
    """Режим выпуска: явный `meta["post_mode"]` важнее всего, далее — эвристика."""
    meta = getattr(post, "meta", {}) or {}
    declared = str(meta.get("post_mode") or "").strip()
    if declared in MODES:
        return declared
    if str(theme or "").strip().lower() == "moku3d":
        return "moku3d_film"
    if meta.get("simulation") or str(meta.get("visual_type") or "") == "diptych_insar":
        return "satellite_lab"
    try:
        from .cards_academic import pick_visual_type

        if pick_visual_type(post) == "cheatsheet_table":
            return "cheatsheet_save"
    except Exception:  # pragma: no cover - защитный контур
        pass
    conf = settings(config)
    if not conf["enabled"]:
        return "interactive_challenge"
    counter = storage.kv_int(KV_COUNTER, 0) + 1 if storage is not None else 1
    if storage is not None:
        storage.kv_set(KV_COUNTER, str(counter))
    if counter % conf["challenge_every_nth"] == 0:
        return "interactive_challenge"
    return _rotation(conf["weights"], counter)


def format_mode_line(mode: str) -> str:
    return f"{LABELS.get(str(mode), mode)}"

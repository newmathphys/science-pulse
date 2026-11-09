"""Реестр визуальных дизайнов и умная A/B-ротация (Бандит Томпсона).

Дизайны (`card.theme` в `config.yaml`):

- ``academic``  — светлая университетская книжная страница LaTeX;
- ``3b1b``      — тёмный чертёж 3Blue1Brown (`NumberPlane`, Typst);
- ``blueprint`` — инженерная синяя миллиметровка со штампом;
- ``moku3d``    — 5-актовый короткометражный фильм (`moku_film.py`).

Режим ``auto``: стиль каждого нового поста выбирает бандит Томпсона по
реальному отклику аудитории (просмотры/реакции/ответы), с правилом
разнообразия — один дизайн не идёт больше `MAX_STREAK` раз подряд на этапе
обучения. Оператор в любой момент может закрепить один стиль командой
`/theme <имя>` в Пульта.
"""
from __future__ import annotations

import json
import random
from typing import Any, Dict, List, Optional, Tuple

THEMES: Tuple[str, ...] = ("academic", "3b1b", "blueprint", "moku3d", "bookfilm", "explainer")
DEFAULT_THEME = "academic"
AUTO = "auto"

# Совместимость со старыми значениями конфига/движка.
ALIASES: Dict[str, str] = {
    "auto": AUTO,
    "neon": "3b1b",
    "book": "academic",
    "typst": "3b1b",
    "pillow": "3b1b",
    "studio": "3b1b",
    "film": "moku3d",
    "book_film": "bookfilm",
    "bookfilm": "bookfilm",
    "infographic": "explainer",
    "explainer": "explainer",
}

KV_ARMS = "theme_arms"
KV_LAST = "theme_last"
KV_STREAK = "theme_streak"
KV_OVERRIDE = "card_theme_override"
MAX_STREAK = 2
PRIOR = 2.0  # a = b = 2 → 50% до накопления статистики

LABELS = {
    "academic": "Книга LaTeX",
    "3b1b": "Тёмный чертёж 3B1B",
    "blueprint": "Инженерный чертёж",
    "moku3d": "5-актовый фильм Moku3D",
    "bookfilm": "Книжный фильм (ожившая страница)",
    "explainer": "Инфографический explainer",
}


def normalize(name: Any) -> str:
    """Приводит любое имя дизайна к каноническому (или к `auto`)."""
    value = str(name or "").strip().lower()
    if value in ALIASES:
        return ALIASES[value]
    return value if value in THEMES else ""


def configured_theme(config: Any) -> str:
    """Тема из `config.yaml` (`card.theme`). По умолчанию — academic."""
    raw = dict((getattr(config, "raw", {}) or {}).get("card") or {})
    name = normalize(raw.get("theme"))
    if name == AUTO:
        return AUTO
    return name or DEFAULT_THEME


def is_auto(config: Any) -> bool:
    return configured_theme(config) == AUTO


# ── Бандит Томпсона по дизайнам ────────────────────────────────────────────

def _arms(storage: Any) -> Dict[str, Dict[str, float]]:
    raw = storage.kv_get(KV_ARMS, "") if storage is not None else ""
    arms: Dict[str, Dict[str, float]] = {}
    if raw:
        try:
            loaded = json.loads(raw)
            if isinstance(loaded, dict):
                arms = {
                    str(key): {"a": float(val.get("a", PRIOR)), "b": float(val.get("b", PRIOR))}
                    for key, val in loaded.items()
                    if isinstance(val, dict)
                }
        except (ValueError, TypeError):
            arms = {}
    for name in THEMES:
        arms.setdefault(name, {"a": PRIOR, "b": PRIOR})
    return arms


def _save_arms(storage: Any, arms: Dict[str, Dict[str, float]]) -> None:
    if storage is None:
        return
    storage.kv_set(KV_ARMS, json.dumps(arms, ensure_ascii=False))


def win_rates(storage: Any) -> Dict[str, float]:
    """Ожидаемая «победная доля» дизайна в бандите (a / (a + b))."""
    arms = _arms(storage)
    return {
        name: round(100.0 * arms[name]["a"] / max(1e-6, arms[name]["a"] + arms[name]["b"]), 1)
        for name in THEMES
    }


def choose_theme(storage: Any, config: Any, rng: Optional[random.Random] = None) -> str:
    """Выбор дизайна для нового поста: фиксация оператора или бандит (`auto`)."""
    fixed = effective_theme(storage, config)
    if fixed != AUTO:
        return fixed or DEFAULT_THEME
    rnd = rng or random
    arms = _arms(storage)
    last = str(storage.kv_get(KV_LAST, "") or "") if storage is not None else ""
    streak = storage.kv_int(KV_STREAK, 0) if storage is not None else 0
    candidates = list(THEMES)
    if streak >= MAX_STREAK and last in candidates and len(candidates) > 1:
        # Правило разнообразия: не повторяем один и тот же стиль подряд.
        candidates = [name for name in candidates if name != last]
    sampled = {
        name: rnd.betavariate(max(1e-6, arms[name]["a"]), max(1e-6, arms[name]["b"]))
        for name in candidates
    }
    chosen = max(sampled, key=sampled.get) if sampled else DEFAULT_THEME
    if storage is not None:
        storage.kv_set(KV_LAST, chosen)
        storage.kv_set(KV_STREAK, str(streak + 1 if chosen == last else 1))
    return chosen


def record_reward(storage: Any, theme: str, success: bool = True, decay: float = 0.98) -> None:
    """Награда дизайну после публикации (успех/провал) — обучение бандита."""
    name = normalize(theme)
    if not name or storage is None:
        return
    arms = _arms(storage)
    for item in arms.values():
        item["a"] = max(1.0, round(item["a"] * decay, 4))
        item["b"] = max(1.0, round(item["b"] * decay, 4))
    if name in arms:
        arms[name]["a" if success else "b"] += 1.0
    _save_arms(storage, arms)


def record_engagement(storage: Any, theme: str, score: float, baseline: float) -> bool:
    """Награда по реальному отклику: выше базовой линии — «победа» дизайна."""
    name = normalize(theme)
    if not name or storage is None or baseline <= 0:
        return False
    record_reward(storage, name, success=score >= baseline)
    return True


# ── Переключение оператором и итоговый выбор ───────────────────────────────

def effective_theme(storage: Any, config: Any) -> str:
    """Тема с учётом ручного переключения оператором (kv имеет приоритет)."""
    override = ""
    if storage is not None:
        override = str(storage.kv_get(KV_OVERRIDE, "") or "").strip()
    if override:
        return normalize(override) or configured_theme(config)
    return configured_theme(config)


def set_theme(storage: Any, name: str) -> Tuple[bool, str]:
    """Закрепить дизайн (или вернуть `auto`). Хранится в kv, не в config.yaml."""
    value = normalize(name)
    if not value and str(name or "").strip().lower() == AUTO:
        value = AUTO
    if not value:
        return False, f"Неизвестный дизайн '{name}'. Доступны: auto, {', '.join(THEMES)}"
    if storage is not None:
        storage.kv_set(KV_OVERRIDE, value)
    return True, f"Дизайн переключён: {value}"


def theme_for_post(storage: Any, config: Any) -> str:
    """Итоговый дизайн нового поста: `auto` → бандит, иначе — фиксация."""
    theme = effective_theme(storage, config)
    if theme == AUTO:
        theme = choose_theme(storage, config)
    return theme or DEFAULT_THEME


# ── Аналитика дизайнов для Пульта ──────────────────────────────────────────

def design_stats(storage: Any) -> List[Dict[str, Any]]:
    """Рейтинг дизайнов: посты, средние просмотры/реакции, индекс и WinRate."""
    if storage is None:
        return []
    posts = storage.list_posts(limit=2000)
    theme_of: Dict[str, str] = {}
    for post in posts:
        variant = (post.meta or {}).get("design_variant") or {}
        theme = ""
        if isinstance(variant, dict):
            theme = normalize(variant.get("theme"))
        if not theme:
            theme = normalize((post.meta or {}).get("style_variant")) or DEFAULT_THEME
        theme_of[post.id] = theme

    def bucket(name: str) -> Dict[str, Any]:
        return {"theme": name, "posts": 0, "views": 0, "likes": 0, "replies": 0, "measured": 0}

    buckets: Dict[str, Dict[str, Any]] = {name: bucket(name) for name in THEMES}
    for post in posts:
        buckets.setdefault(theme_of[post.id], bucket(theme_of[post.id]))["posts"] += 1
    series: Dict[str, List[float]] = {}
    with storage.cursor() as connection:
        rows = connection.execute(
            "SELECT post_id, views, likes, replies FROM metrics ORDER BY id"
        ).fetchall()
    for row in rows:
        theme = theme_of.get(row["post_id"])
        if not theme:
            continue
        item = buckets.setdefault(theme, bucket(theme))
        item["views"] += int(row["views"] or 0)
        item["likes"] += int(row["likes"] or 0)
        item["replies"] += int(row["replies"] or 0)
        item["measured"] += 1
        score = int(row["views"] or 0) + 5 * int(row["likes"] or 0) + 8 * int(row["replies"] or 0)
        series.setdefault(theme, []).append(float(score))

    try:
        from .signal_engine import KalmanFilter

        for theme, values in series.items():
            smoothed = KalmanFilter().smooth(values)
            if theme in buckets:
                buckets[theme]["smoothed_score"] = round(smoothed[-1], 2) if smoothed else 0.0
    except Exception:
        pass

    rates = win_rates(storage)
    scores: List[float] = []
    for item in buckets.values():
        measured = max(1, item["measured"])
        item["avg_views"] = round(item["views"] / measured, 1)
        item["avg_likes"] = round(item["likes"] / measured, 1)
        item["engagement_score"] = round(
            (item["views"] + 5 * item["likes"] + 8 * item["replies"]) / measured, 2
        )
        item["win_rate_pct"] = rates.get(item["theme"], 50.0)
        item.setdefault("smoothed_score", item["engagement_score"])
        scores.append(item["engagement_score"])
    top = max(scores) if scores else 0.0
    for item in buckets.values():
        item["index_pct"] = round(100.0 * item["engagement_score"] / top, 1) if top > 0 else 0.0
    return sorted(
        buckets.values(),
        key=lambda item: (item["engagement_score"], item["posts"]),
        reverse=True,
    )


def format_design_table(storage: Any, config: Any, html: bool = True) -> str:
    """Таблица эффективности дизайнов для Пульта (`/theme`, `/ab`)."""
    current = effective_theme(storage, config)
    mode = "AUTO (умная ротация бандита)" if current == AUTO else f"закреплён {current}"
    lines = ["<b>АНАЛИЗ ЭФФЕКТИВНОСТИ ДИЗАЙНОВ</b>", f"Режим: {mode}", ""]
    for index, item in enumerate(design_stats(storage), start=1):
        leader = " [ЛИДЕР]" if index == 1 and item["engagement_score"] > 0 else ""
        lines.append(
            f"{index}. <b>{item['theme']}</b> — {LABELS.get(item['theme'], '')} · "
            f"постов: {item['posts']} · замеров: {item['measured']} · "
            f"ср. охват: {item['avg_views']:.0f} · реакции: {item['avg_likes']:.0f} · "
            f"индекс: {item['index_pct']:.0f}% · WinRate: {item['win_rate_pct']:.0f}%"
            f" · сглажено: {item.get('smoothed_score', 0):.0f}{leader}"
        )
    lines += ["", "Переключение: <code>/theme auto|academic|3b1b|blueprint|moku3d|bookfilm|explainer</code>"]
    try:
        from .signal_engine import format_signal_report

        lines += ["", format_signal_report(storage, config, html=html)]
    except Exception:
        pass
    text = "\n".join(lines)
    if html:
        return text
    for tag in ("<b>", "</b>", "<code>", "</code>"):
        text = text.replace(tag, "")
    return text


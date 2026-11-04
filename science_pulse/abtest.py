from __future__ import annotations

import hashlib
from typing import Any, Dict, Sequence, Tuple

# Варианты стиля карточки для A/B. Порядок фиксирован — он влияет на выбор.
VARIANTS: Tuple[str, ...] = ("classic", "compact")

# Параметры вёрстки на вариант. classic — текущий вид, compact — плотнее.
STYLES: Dict[str, Dict[str, Any]] = {
    "classic": {"title_max_lines": 3, "title_scale": 1.0, "show_hook": True},
    "compact": {"title_max_lines": 2, "title_scale": 0.9, "show_hook": False},
}


def _abtest_raw(config: Any) -> Dict[str, Any]:
    raw = getattr(config, "raw", {}) or {}
    return dict(raw.get("abtest") or {})


def ab_enabled(config: Any) -> bool:
    return bool(_abtest_raw(config).get("enabled", False))


def variants_from_config(config: Any) -> Tuple[str, ...]:
    configured = tuple(str(item) for item in (_abtest_raw(config).get("variants") or VARIANTS))
    return configured or VARIANTS


def choose_variant(post_id: str, variants: Sequence[str] = VARIANTS) -> str:
    """Детерминированный выбор варианта по id поста (стабилен между запусками)."""
    options = [str(item) for item in variants] or list(VARIANTS)
    digest = hashlib.sha1(str(post_id).encode("utf-8")).hexdigest()
    return options[int(digest, 16) % len(options)]


def variant_style(variant: str | None) -> Dict[str, Any]:
    return dict(STYLES.get(str(variant or "classic"), STYLES["classic"]))

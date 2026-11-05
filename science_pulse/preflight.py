"""Предполётная проверка перед публикацией: карточка, стандарты, звук, видео.

`preflight(pipeline)` собирает отчёт о готовности следующего поста: рендерит
карточку в память, прогоняет `StandardsChecker`, проверяет доступность озвучки
и видео, оценивает запас очереди. Ничего не публикует и не меняет состояние —
это «предстартовый чек-лист».
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .models import Post

LOGGER = logging.getLogger(__name__)


def preflight(pipeline: Any, domain: Optional[str] = None, with_media: bool = True) -> Dict[str, Any]:
    """Полный предполётный отчёт (без публикации и без сети)."""
    from .cards import render_card
    from .publishers.base import build_caption
    from .standards import StandardsChecker

    checks: List[Dict[str, Any]] = []
    config = pipeline.config
    storage = pipeline.storage

    post = pipeline.choose_next(domain)
    checks.append({
        "name": "queue",
        "ok": post is not None,
        "detail": post.title if post else "очередь пуста",
    })
    if post is None:
        return {"ok": False, "checks": checks, "post": None}

    # Карточка (рендер в память, без записи на диск) — тем же размером,
    # которым её рисует публикация (`card.size`), иначе предполётная проверка
    # расходится с реальностью.
    card = None
    card_raw = dict((config.raw.get("card") or {}))
    expected = int(card_raw.get("size", 1080) or 1080)
    try:
        card = render_card(post, out_path=None, size=expected,
                           ssaa=int(card_raw.get("ssaa", 2)),
                           engine=str(card_raw.get("engine", "auto")))
        ok = (card.width, card.height) == (expected, expected) and len(card.data) > 15_000
        checks.append({"name": "card", "ok": ok, "detail": f"{card.width}×{card.height}, {len(card.data) // 1024} КБ"})
    except Exception as exc:
        checks.append({"name": "card", "ok": False, "detail": str(exc)[:120]})

    # Стандарты подписи
    caption = build_caption(post, limit=1020, html=True, site_url=config.site_base_url)
    checker = StandardsChecker.load(storage, config)
    report = checker.check(post, caption, card)
    if not report.ok:
        _post, healed, notes = checker.heal(post, caption)
        healed_report = checker.check(post, healed, card)
        checks.append({
            "name": "standards",
            "ok": healed_report.ok,
            "detail": ("вылечено: " + ", ".join(notes)) if healed_report.ok
                      else "; ".join(f"{v.code}: {v.detail}" for v in healed_report.violations),
        })
    else:
        checks.append({"name": "standards", "ok": True, "detail": f"{report.checked} рубежей пройдено"})

    # Медиа: звук и видео
    if with_media:
        from .video import video_available
        from .voice import voice_available

        checks.append({"name": "voice", "ok": voice_available(config),
                       "detail": "edge-tts/piper готов" if voice_available(config) else "движок не установлен"})
        checks.append({"name": "video", "ok": video_available(),
                       "detail": "ffmpeg готов" if video_available() else "ffmpeg не найден"})

    ok = all(item["ok"] for item in checks)
    return {"ok": ok, "checks": checks, "post": post}


def format_preflight(report: Dict[str, Any]) -> str:
    """Человекочитаемый отчёт предполётной проверки."""
    lines = ["🛫 <b>Предполётная проверка</b>", ""]
    icons = {True: "🟢", False: "🔴"}
    for item in report.get("checks", []):
        lines.append(f"{icons[bool(item['ok'])]} <b>{item['name']}</b>: {item['detail']}")
    post = report.get("post")
    if post is not None:
        lines.append("")
        lines.append(f"Следующий пост: <b>{post.title}</b> [{post.domain}]")
    lines.append("")
    lines.append("Итог: " + ("✅ готов к публикации" if report.get("ok") else "⛔ есть блокеры"))
    return "\n".join(lines)
"""Догоняющая синхронизация: новая соцсеть не теряет начало летописи.

Когда оператор подключает токен площадки позже Telegram (например, Threads или
VK через две недели), наивная публикация начнётся со «свежего» § 2.x и
потеряет самое начало науки. Здесь мы находим уже открытые параграфы канона,
которых нет в `publications` для целевой площадки, и публикуем их **по порядку
§ — строго с § 1.1**.

Идемпотентность обеспечивает `PublisherManager.publish`: он сам пропускает
посты, у которых уже есть успешная публикация на этой площадке.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from .models import Post

LOGGER = logging.getLogger(__name__)


def section_key(post: Post) -> Tuple[int, int, str]:
    """Порядок летописи: § 1.1 → § 1.2 → … → § 10.3 → § 11.1."""
    raw = str((getattr(post, "meta", {}) or {}).get("section_num") or "").strip()
    if not raw:
        return (10 ** 6, 10 ** 6, post.id)
    head, _, tail = raw.partition(".")
    try:
        return (int(head), int(tail or 0), post.id)
    except ValueError:
        return (10 ** 6, 10 ** 6, raw)


def missing_for_platform(storage: Any, platform: str, limit: int = 10,
                         domains: Optional[List[str]] = None) -> List[Post]:
    """Опубликованные в летописи посты, которых ещё нет на целевой площадке."""
    platform = str(platform or "").strip().lower()
    if not platform:
        return []
    allowed = {str(item) for item in (domains or []) if item}
    missing: List[Post] = []
    for post in storage.list_posts(limit=5000):
        if post.status != "published":
            continue
        if allowed and post.domain not in allowed:
            continue
        if storage.publication_exists(post.id, platform):
            continue
        missing.append(post)
    missing.sort(key=section_key)
    return missing[: max(1, int(limit))]


def sync_platform(pipeline: Any, platform: str, limit: int = 5, dry_run: bool = False) -> Dict[str, Any]:
    """Довыгружает пропущенное начало летописи на одну площадку."""
    from .publishers.base import build_caption
    from .themes import record_reward, theme_for_post

    storage, config = pipeline.storage, pipeline.config
    targets = [str(platform).strip().lower()]
    if targets[0] not in pipeline.publishers.publishers:
        return {"ok": False, "error": f"площадка {targets[0]} не включена или не найдена",
                "platform": targets[0], "published": [], "missing": 0}
    missing = missing_for_platform(storage, targets[0], limit=limit)
    plan = [{"id": post.id, "section": (post.meta or {}).get("section_num"),
             "title": post.title, "domain": post.domain} for post in missing]
    if dry_run:
        return {"ok": True, "dry_run": True, "platform": targets[0],
                "missing": len(missing), "published": [], "plan": plan}
    if not missing:
        return {"ok": True, "platform": targets[0], "missing": 0, "published": [], "plan": []}

    published: List[Dict[str, Any]] = []
    for post in missing:
        theme = theme_for_post(storage, config)
        try:
            from .cards import render_card

            card = render_card(
                post,
                out_path=config.cards_dir / f"{post.id}.png",
                size=int(config.card.get("size", 1080)),
                theme=theme,
            )
        except Exception as exc:  # pragma: no cover - защитный контур
            LOGGER.warning("sync: карточка %s не отрисована (%s)", post.id, exc)
            published.append({"id": post.id, "ok": False, "error": f"render: {exc}"[:150]})
            continue
        results = pipeline.publishers.publish(
            post,
            card,
            site_url=config.site_base_url,
            public_card_url=(
                f"{config.site_base_url}/cards/{post.id}.png" if config.site_base_url else ""
            ),
            targets=targets,
        )
        record = results[0] if results else None
        ok = bool(record and record.ok and not record.skipped)
        record_reward(storage, theme, success=ok)
        published.append({
            "id": post.id,
            "section": (post.meta or {}).get("section_num"),
            "title": post.title,
            "theme": theme,
            "ok": ok,
            "skipped": bool(record.skipped) if record else False,
            "url": (record.url if record else None),
            "error": (record.error if record else "нет результата"),
        })
        if not ok:
            break  # не долбим площадку при ошибке токена/лимита
    return {
        "ok": all(item["ok"] for item in published) if published else True,
        "platform": targets[0],
        "missing": len(missing),
        "published": published,
        "plan": plan,
    }


def format_sync_report(result: Dict[str, Any], html: bool = True) -> str:
    """Отчёт оператору: что довыгружено и что осталось."""
    platform = result.get("platform") or "?"
    if not result.get("ok") and result.get("error"):
        return f"Синхронизация {platform}: ошибка — {result['error']}"
    lines = [f"<b>Синхронизация {platform}</b> · пропущено в летописи: {result.get('missing', 0)}"]
    if result.get("dry_run"):
        lines.append("Режим проверки: ничего не публиковалось.")
    for item in result.get("plan", [])[:10] if result.get("dry_run") else result.get("published", []):
        section = item.get("section") or "—"
        mark = "✓" if item.get("ok", True) else "✗"
        note = item.get("url") or item.get("error") or ""
        lines.append(f"{mark} § {section} · {str(item.get('title'))[:60]} {note}".rstrip())
    if not result.get("published") and not result.get("dry_run") and not result.get("missing"):
        lines.append("Всё уже на месте — довыгружать нечего.")
    text = "\n".join(lines)
    if html:
        return text
    for tag in ("<b>", "</b>"):
        text = text.replace(tag, "")
    return text

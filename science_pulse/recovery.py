"""Восстановление состояния базы из публичной ленты канала (`t.me/s/<канал>`).

Если локальный `science.db` и облачная реплика D1 потеряны, статус публикаций
восстанавливается прямо из открытой веб-ленты Telegram: страница читается
обычным `GET` (без токена бота), из разметки берутся `data-post="<канал>/<id>"`
и номер параграфа `§ X.Y`, после чего в базе помечаются `published` и
`external_id` соответствующих постов канона.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Callable, Dict, List, Optional

import requests

LOGGER = logging.getLogger(__name__)

MESSAGE_RE = re.compile(
    r'data-post="(?P<channel>[^"/]+)/(?P<message>\d+)"(?P<body>.*?)(?=data-post="|\Z)',
    re.DOTALL,
)
SECTION_RE = re.compile(r"§\s*(\d+\.\d+)")


def parse_public_feed(html: str) -> List[Dict[str, str]]:
    """Разбирает публичную ленту: ``[{'message_id', 'section'}, …]``."""
    items: List[Dict[str, str]] = []
    for match in MESSAGE_RE.finditer(html or ""):
        section = SECTION_RE.search(match.group("body") or "")
        if section:
            items.append({"message_id": match.group("message"), "section": section.group(1)})
    return items


def recover_from_public_channel(
    storage: Any,
    config: Any,
    http_get: Optional[Callable[..., Any]] = None,
    limit: int = 100,
) -> Dict[str, Any]:
    """Восстанавливает `published`/`external_id` из открытой ленты канала."""
    from .models import PublishResult, make_id
    from .sources.foundation import CANON, section_of

    channel = (getattr(config, "telegram_channel", "") or "").strip()
    username = channel.lstrip("@") if channel.startswith("@") else ""
    if not username:
        return {"ok": False, "error": "нужен @username канала", "recovered": 0}
    getter = http_get or requests.get
    url = f"https://t.me/s/{username}"
    try:
        response = getter(url, timeout=15)
        html = response.text if hasattr(response, "text") else str(response)
    except Exception as exc:
        return {"ok": False, "error": f"сеть: {str(exc)[:120]}", "recovered": 0}

    by_section = {section_of(item["id"]): item["id"] for item in CANON}
    recovered: List[Dict[str, Any]] = []
    seen: set = set()
    for entry in parse_public_feed(html):
        section = entry["section"]
        canon_id = by_section.get(section)
        if not canon_id or canon_id in seen:
            continue
        seen.add(canon_id)
        post_id = make_id("history_canon", canon_id)
        post = storage.get_post(post_id)
        if post is None:
            continue
        if post.status != "published":
            storage.update_post_fields(post_id, {"status": "published"})
        storage.record_publication(
            post_id,
            PublishResult(platform="telegram", ok=True, external_id=entry["message_id"]),
        )
        recovered.append({"section": section, "post_id": post_id, "message_id": entry["message_id"]})
        if len(recovered) >= limit:
            break
    LOGGER.info("Восстановление из ленты %s: %s узлов", username, len(recovered))
    return {"ok": True, "channel": username, "recovered": len(recovered), "items": recovered}

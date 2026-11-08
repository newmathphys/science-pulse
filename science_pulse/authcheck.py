"""Живой тестер ключей: безопасный read-only пинг каждой площадки.

Ничего не публикует. Для каждой соцсети делается один лёгкий запрос:

- Telegram — `getMe` (+ `getChat` и права администратора канала);
- Threads  — `GET /v1.0/me?fields=id,username`;
- Bluesky  — `com.atproto.server.createSession` (проверка app-password);
- VK       — `groups.getById`;
- Mastodon — `GET /api/v1/accounts/verify_credentials`;
- Discord  — `GET` вебхука.

Итог — таблица `🟢 Готово` / `⚪ Ключи не заданы` / `🔴 Ошибка токена`.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Callable, Dict, List, Optional

LOGGER = logging.getLogger(__name__)

PLATFORMS = ("telegram", "threads", "bluesky", "discord", "mastodon", "vk")
STATES = {"ready": "Готово к работе", "no_keys": "Ключи не заданы", "error": "Ошибка токена"}
ICONS = {"ready": "🟢", "no_keys": "⚪", "error": "🔴"}


def _value(config: Any, name: str, default: str = "") -> str:
    raw = (getattr(config, "raw", {}) or {}).get(name)
    return str(os.getenv(name, "") or raw or default).strip()


def _json_http(method: str, url: str, **kwargs: Any) -> Dict[str, Any]:
    """Реальный HTTP: тонкая обёртка над requests (инъекция в тестах)."""
    import requests

    kwargs.setdefault("timeout", 15)
    response = requests.request(method, url, **kwargs)
    try:
        return {"status": response.status_code, "data": response.json()}
    except ValueError:
        return {"status": response.status_code, "data": {"raw": response.text[:200]}}


def _telegram(config: Any, http: Callable[..., Dict[str, Any]]) -> Dict[str, str]:
    token, channel = _value(config, "TG_BOT_TOKEN"), _value(config, "TG_CHANNEL_ID")
    if not token or not channel:
        return {"state": "no_keys", "detail": "нужны TG_BOT_TOKEN и TG_CHANNEL_ID"}
    me = http("GET", f"https://api.telegram.org/bot{token}/getMe")
    data = me.get("data") or {}
    if not data.get("ok"):
        return {"state": "error", "detail": str(data.get("description") or "getMe не ответил")[:120]}
    username = "@" + str((data.get("result") or {}).get("username") or "bot")
    chat = http("GET", f"https://api.telegram.org/bot{token}/getChat", params={"chat_id": channel})
    chat_data = chat.get("data") or {}
    if not chat_data.get("ok"):
        return {"state": "error",
                "detail": f"{username}: канал недоступен ({chat_data.get('description')})"[:120]}
    title = str(((chat_data.get("result") or {}).get("title")) or channel)
    rights = ""
    bot_id = (data.get("result") or {}).get("id")
    if bot_id:
        member = http(
            "GET", f"https://api.telegram.org/bot{token}/getChatMember",
            params={"chat_id": channel, "user_id": bot_id},
        )
        status = str(((member.get("data") or {}).get("result") or {}).get("status") or "")
        rights = " · права админа есть" if status in ("administrator", "creator") else f" · статус: {status or '—'}"
    return {"state": "ready", "detail": f"{username} · {title}{rights}"}


def _threads(config: Any, http: Callable[..., Dict[str, Any]]) -> Dict[str, str]:
    token = _value(config, "TH_ACCESS_TOKEN")
    user_id = _value(config, "TH_USER_ID")
    if not token or not user_id:
        return {"state": "no_keys", "detail": "нужны TH_USER_ID и TH_ACCESS_TOKEN"}
    payload = http(
        "GET", "https://graph.threads.net/v1.0/me",
        params={"fields": "id,username", "access_token": token},
    )
    data = payload.get("data") or {}
    if data.get("error") or not data.get("id"):
        message = str((data.get("error") or {}).get("message") or "нет ответа")[:120]
        return {"state": "error", "detail": message}
    return {"state": "ready", "detail": f"@{data.get('username') or data.get('id')}"}


def _bluesky(config: Any, http: Callable[..., Dict[str, Any]]) -> Dict[str, str]:
    handle, password = _value(config, "BLUESKY_HANDLE"), _value(config, "BLUESKY_APP_PASSWORD")
    if not handle or not password:
        return {"state": "no_keys", "detail": "нужны BLUESKY_HANDLE и BLUESKY_APP_PASSWORD"}
    payload = http(
        "POST", "https://bsky.social/xrpc/com.atproto.server.createSession",
        json={"identifier": handle, "password": password},
    )
    data = payload.get("data") or {}
    if not data.get("did"):
        return {"state": "error", "detail": str(data.get("message") or "сессия не создана")[:120]}
    return {"state": "ready", "detail": f"@{data.get('handle') or handle}"}


def _vk(config: Any, http: Callable[..., Dict[str, Any]]) -> Dict[str, str]:
    token, group = _value(config, "VK_ACCESS_TOKEN"), _value(config, "VK_GROUP_ID")
    if not token or not group:
        return {"state": "no_keys", "detail": "нужны VK_ACCESS_TOKEN и VK_GROUP_ID"}
    payload = http(
        "GET", "https://api.vk.com/method/groups.getById",
        params={"group_id": group.lstrip("-"), "access_token": token, "v": "5.199"},
    )
    data = payload.get("data") or {}
    if data.get("error"):
        return {"state": "error", "detail": str((data.get("error") or {}).get("error_msg") or "ошибка")[:120]}
    groups = (data.get("response") or {}).get("groups") or []
    name = str((groups[0] or {}).get("name")) if groups else group
    return {"state": "ready", "detail": f"{name} (group {group})"}


def _mastodon(config: Any, http: Callable[..., Dict[str, Any]]) -> Dict[str, str]:
    instance = _value(config, "MASTODON_INSTANCE", "https://mathstodon.xyz").rstrip("/")
    token = _value(config, "MASTODON_ACCESS_TOKEN")
    if not token:
        return {"state": "no_keys", "detail": "нужен MASTODON_ACCESS_TOKEN"}
    payload = http(
        "GET", f"{instance}/api/v1/accounts/verify_credentials",
        headers={"Authorization": f"Bearer {token}"},
    )
    data = payload.get("data") or {}
    if not data.get("username"):
        return {"state": "error", "detail": str(data.get("error") or "нет ответа")[:120]}
    return {"state": "ready", "detail": f"@{data.get('username')} на {instance}"}


def _discord(config: Any, http: Callable[..., Dict[str, Any]]) -> Dict[str, str]:
    webhook = _value(config, "DISCORD_WEBHOOK_URL")
    if not webhook:
        return {"state": "no_keys", "detail": "нужен DISCORD_WEBHOOK_URL"}
    payload = http("GET", webhook)
    data = payload.get("data") or {}
    if int(payload.get("status", 200)) >= 400 or not data.get("id"):
        return {"state": "error", "detail": str(data.get("message") or f"HTTP {payload.get('status')}")[:120]}
    return {"state": "ready", "detail": f"вебхук канала «{data.get('name') or data.get('id')}»"}


CHECKERS = {
    "telegram": _telegram,
    "threads": _threads,
    "bluesky": _bluesky,
    "discord": _discord,
    "mastodon": _mastodon,
    "vk": _vk,
}


def check_all(config: Any, http: Optional[Callable[..., Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """Проверяет все 6 площадок. Ничего не публикует — только читает."""
    client = http or _json_http
    rows: List[Dict[str, Any]] = []
    for name in PLATFORMS:
        try:
            result = CHECKERS[name](config, client)
        except Exception as exc:  # pragma: no cover - сеть/среда
            LOGGER.warning("auth-check %s: %s", name, exc)
            result = {"state": "error", "detail": str(exc)[:120]}
        rows.append({"platform": name, **result})
    return rows


def format_auth_table(rows: List[Dict[str, Any]], html: bool = True) -> str:
    """Таблица оператору: что готово, где нет ключей, где битый токен."""
    ready = sum(1 for row in rows if row["state"] == "ready")
    lines = [f"<b>Проверка ключей</b> · готово {ready} из {len(rows)}", ""]
    for row in rows:
        icon = ICONS.get(row["state"], "⚪")
        detail = row.get("detail") or STATES.get(row["state"], "")
        lines.append(f"{icon} <b>{row['platform']}</b>: {detail}")
    text = "\n".join(lines)
    if html:
        return text
    for tag in ("<b>", "</b>"):
        text = text.replace(tag, "")
    return text


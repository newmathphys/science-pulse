"""Мониторинг изменений API площадок.

Раз в неделю SCM проверяет официальные changelog'и и пишет отчёт оператору:
что изменилось в Telegram Bot API, Threads API, Cloudflare Workers и
GitHub Actions. Это не генерация текста и не LLM — только чтение официальных
страниц, хеш и разбор последних записей.

Задача отчёта — заранее показать, что пора обновить лимиты/адаптеры/доки,
а не «починить» пост вслепую.
"""
from __future__ import annotations

import hashlib
import html as html_module
import json
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

LOGGER = logging.getLogger(__name__)

SOURCES: List[Dict[str, str]] = [
    {
        "id": "telegram",
        "name": "Telegram Bot API",
        "url": "https://core.telegram.org/bots/api",
        "kind": "telegram",
        "code": "publishers/telegram.py · models.py PLATFORM_LIMITS",
        "doc": "docs/PLATFORMS.md",
    },
    {
        "id": "threads",
        "name": "Meta Threads API",
        "url": "https://developers.facebook.com/docs/threads/changelog",
        "kind": "threads",
        "code": "publishers/threads.py · config.yaml threads",
        "doc": "docs/INTEGRATIONS.md",
    },
    {
        "id": "cloudflare",
        "name": "Cloudflare Workers",
        "url": "https://developers.cloudflare.com/workers/platform/changelog/",
        "kind": "cloudflare",
        "code": "cloudflare/worker.js · cloudflare/wrangler.toml",
        "doc": "docs/EDGE.md",
    },
    {
        "id": "github_actions",
        "name": "GitHub Actions",
        "url": "https://github.blog/changelog/label/actions/feed/",
        "kind": "rss",
        "code": ".github/workflows/science_pulse.yml",
        "doc": "docs/INTEGRATIONS.md",
    },
]

STATE_NAME = "platform_watch.json"
MAX_ITEMS = 4


def _strip_html(value: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", value or "")
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html_module.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _first(items: List[str], count: int = MAX_ITEMS) -> List[str]:
    seen: List[str] = []
    for item in items:
        item = re.sub(r"\s+", " ", item or "").strip()
        if item and item not in seen:
            seen.append(item)
        if len(seen) >= count:
            break
    return seen


def parse_telegram(page: str) -> Dict[str, Any]:
    text = _strip_html(page)
    start = text.find("Recent changes")
    chunk = text[start:start + 12000] if start >= 0 else text[:12000]
    matches = re.findall(
        r"((?:January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+\d{1,2},\s+20\d{2})\s+Bot API\s+(\d+\.\d+)",
        chunk,
    )
    items = [f"{date} · Bot API {version}" for date, version in matches]
    latest = items[0] if items else ""
    return {"latest": latest, "items": _first(items)}


def _split_entries(text: str, pattern: str, body_limit: int = 180) -> List[str]:
    matches = list(re.finditer(pattern, text))
    items: List[str] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else min(len(text), match.end() + body_limit + 80)
        body = text[match.end():end].strip()
        body = _strip_html(body)[:body_limit]
        items.append(f"{match.group(1)} · {body}".strip(" ·"))
        if len(items) >= MAX_ITEMS:
            break
    return items


def parse_threads(page: str) -> Dict[str, Any]:
    text = _strip_html(page)
    anchor = text.find("Search Changelog")
    if anchor >= 0:
        chunk = text[anchor + len("Search Changelog"):anchor + 30000]
    else:
        start = text.find("Changelog")
        chunk = text[start:start + 30000] if start >= 0 else text[:30000]
    pattern = r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},\s+20\d{2})"
    items = [item for item in _split_entries(chunk, pattern) if "Get notified" not in item and "Search Changelog" not in item]
    latest = items[0] if items else ""
    return {"latest": latest, "items": _first(items)}


def parse_cloudflare(page: str) -> Dict[str, Any]:
    text = _strip_html(page)
    items = _split_entries(text, r"(20\d{2}-\d{2}-\d{2})")
    latest = items[0] if items else ""
    return {"latest": latest, "items": _first(items)}


def parse_rss(xml_text: str) -> Dict[str, Any]:
    try:
        root = ET.fromstring(xml_text)
        items: List[str] = []
        for item in root.findall(".//item"):
            title = (item.findtext("title") or "").strip()
            date = (item.findtext("pubDate") or "").strip()
            if title:
                items.append(f"{date} · {title}" if date else title)
        return {"latest": items[0] if items else "", "items": _first(items)}
    except ET.ParseError:
        return {"latest": "", "items": []}


PARSERS = {
    "telegram": parse_telegram,
    "threads": parse_threads,
    "cloudflare": parse_cloudflare,
    "rss": parse_rss,
}


def _state_path(config: Any, path: Optional[Path] = None) -> Path:
    return Path(path) if path else config.data_dir / STATE_NAME


def _read_state(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_state(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def _fetch(url: str, http_get: Optional[Callable[..., Any]]) -> str:
    if http_get is not None:
        response = http_get(url, timeout=30)
        return str(getattr(response, "text", response))
    import requests

    response = requests.get(url, timeout=30, headers={"User-Agent": "SciencePulseWatch/1.0"})
    response.raise_for_status()
    return response.text


def watch_platforms(
    config: Any,
    http_get: Optional[Callable[..., Any]] = None,
    state_path: Optional[Path] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Проверяет changelog'и и возвращает отчёт об изменениях."""
    path = _state_path(config, state_path)
    state = _read_state(path)
    checked_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    changed: List[str] = []
    sources: List[Dict[str, Any]] = []
    errors: List[str] = []

    for source in SOURCES:
        entry: Dict[str, Any] = {**source, "state": "ok", "changed": False}
        try:
            body = _fetch(source["url"], http_get)
            parsed = PARSERS[source["kind"]](body)
            digest = hashlib.sha256(
                json.dumps(parsed, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest()
            old = state.get(source["id"]) or {}
            is_changed = force or (bool(old.get("hash")) and old.get("hash") != digest)
            baseline = not old.get("hash")
            entry.update({
                "hash": digest,
                "latest": parsed.get("latest", ""),
                "items": parsed.get("items", []),
                "changed": is_changed,
                "baseline": baseline,
                "checked_at": checked_at,
            })
            if is_changed:
                changed.append(source["name"])
            state[source["id"]] = {
                "hash": digest,
                "latest": parsed.get("latest", ""),
                "items": parsed.get("items", []),
                "checked_at": checked_at,
            }
        except Exception as exc:
            LOGGER.warning("platform watch %s: %s", source["id"], exc)
            entry.update({"state": "error", "error": f"{type(exc).__name__}: {exc}"[:160]})
            errors.append(f"{source['name']}: {entry['error']}")
        sources.append(entry)

    _write_state(path, state)
    return {
        "checked_at": checked_at,
        "state_path": str(path),
        "changed": changed,
        "errors": errors,
        "sources": sources,
    }


def _e(value: str) -> str:
    return html_module.escape(str(value or ""))


def format_watch_report(report: Dict[str, Any], html: bool = True) -> str:
    icons = {"ok": "🟢", "error": "🔴"}
    lines = [
        "🔭 <b>Мониторинг API площадок</b>",
        f"Проверено: {_e(report.get('checked_at', ''))}",
        "",
    ]
    if report.get("changed"):
        lines.append("🟡 <b>Изменения:</b> " + _e(", ".join(report["changed"])))
    else:
        lines.append("🟢 Изменений в сохранённом снимке нет")
    if report.get("errors"):
        lines.append("🔴 <b>Ошибки:</b> " + _e("; ".join(report["errors"])))
    lines.append("")

    for source in report.get("sources", []):
        icon = icons.get(source.get("state"), "⚪")
        suffix = " · изменено" if source.get("changed") else (" · baseline" if source.get("baseline") else "")
        lines.append(f"{icon} <b>{_e(source.get('name', ''))}</b>{suffix}")
        if source.get("latest"):
            lines.append(f"   {_e(source['latest'])}")
        for item in source.get("items", [])[:MAX_ITEMS]:
            lines.append(f"   • {_e(item)}")
        if source.get("error"):
            lines.append(f"   ошибка: {_e(source['error'])}")
        lines.append(f"   код: <code>{_e(source.get('code', ''))}</code>")
        lines.append(f"   док: <code>{_e(source.get('doc', ''))}</code>")
        lines.append("")

    if report.get("changed"):
        lines.append("<b>Что делать:</b> проверить лимиты/поля в указанном коде, "
                     "обновить тесты и docs, затем прогнать <code>./sp check</code>.")
    text = "\n".join(lines).strip()
    if html:
        return text
    return re.sub(r"<[^>]+>", "", text)

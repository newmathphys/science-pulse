"""Проверка готовности релиза: Telegram + Threads + Cloudflare.

Ничего не публикует и не меняет. Показывает, что уже готово, чего не хватает
и какой следующий шаг сделать. Секреты не печатаются.
"""
from __future__ import annotations

import os
import shutil
from typing import Any, Callable, Dict, List, Optional

from .authcheck import _json_http, _threads

CF_MARKER = "Science Pulse Edge Active"


def _present(value: str) -> bool:
    return bool(str(value or "").strip())


def check_cloudflare(config: Any, http_get: Optional[Callable[..., Any]] = None) -> Dict[str, Any]:
    """Проверяет Worker: URL, секрет, доступность и маршрут /tg-cdn."""
    url = str(getattr(config, "cf_worker_url", "") or "").rstrip("/")
    secret = str(getattr(config, "ingest_secret", "") or "")
    worker = config.root / "cloudflare" / "worker.js"
    wrangler = shutil.which("wrangler")

    if not url:
        return {
            "state": "no_url",
            "detail": "CF_WORKER_URL не задан",
            "url": "",
            "secret": _present(secret),
            "wrangler": bool(wrangler),
            "worker": worker.is_file(),
            "steps": [
                "cd cloudflare",
                "wrangler d1 create science-pulse",
                "wrangler d1 execute science-pulse --file=schema.sql",
                "wrangler r2 bucket create science-pulse-cards",
                "wrangler secret put TG_BOT_TOKEN",
                "wrangler secret put INGEST_SECRET",
                "wrangler deploy",
                "CF_WORKER_URL=https://science-pulse-edge.<account>.workers.dev",
            ],
        }

    if http_get is None:
        import requests

        def http_get(target: str, timeout: int = 10):
            return requests.get(target, timeout=timeout)

    try:
        response = http_get(url, timeout=10)
        status = int(getattr(response, "status_code", 0) or 0)
        body = str(getattr(response, "text", "") or "")
    except Exception as exc:
        return {
            "state": "error",
            "detail": f"{type(exc).__name__}: {exc}"[:160],
            "url": url,
            "secret": _present(secret),
            "wrangler": bool(wrangler),
            "worker": worker.is_file(),
            "steps": ["проверьте, что Worker задеплоен и URL доступен"],
        }

    if status == 200 and CF_MARKER in body:
        state = "ready"
        detail = "Worker отвечает"
    elif status == 200:
        state = "unknown"
        detail = "URL отвечает, но это не Science Pulse Worker"
    else:
        state = "error"
        detail = f"HTTP {status}"
    steps: List[str] = []
    if not _present(secret):
        steps.append("wrangler secret put INGEST_SECRET; затем INGEST_SECRET=... в .env")
    if state != "ready":
        steps.append("проверьте wrangler deploy и CF_WORKER_URL")
    return {
        "state": state,
        "detail": detail,
        "url": url,
        "secret": _present(secret),
        "wrangler": bool(wrangler),
        "worker": worker.is_file(),
        "steps": steps,
    }


def check_threads(config: Any, http: Optional[Callable[..., Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Проверяет Threads-ключи и режим картинки."""
    from .publishers.threads import ThreadsPublisher

    row = _threads(config, http or _json_http)
    image_mode = ThreadsPublisher(config).image_mode()
    steps: List[str] = []
    if row["state"] == "no_keys":
        steps.extend([
            "developers.facebook.com/apps → Create App → Access the Threads API",
            "Threads API → Add or Remove Threads Testers → добавить свой аккаунт",
            "принять приглашение в приложении Threads",
            "Generate Access Token → TH_ACCESS_TOKEN и TH_USER_ID в .env",
        ])
    elif row["state"] == "ready" and image_mode == "text":
        steps.append("для IMAGE задайте CF_WORKER_URL (Worker /tg-cdn/{file_id}.png)")
    return {**row, "image_mode": image_mode, "steps": steps}


def release_status(config: Any, http: Optional[Callable[..., Dict[str, Any]]] = None,
                   http_get: Optional[Callable[..., Any]] = None) -> Dict[str, Any]:
    return {
        "threads": check_threads(config, http=http),
        "cloudflare": check_cloudflare(config, http_get=http_get),
    }


def format_release(report: Dict[str, Any]) -> str:
    icons = {"ready": "🟢", "no_keys": "⚪", "no_url": "⚪", "error": "🔴", "unknown": "🟡"}
    threads = report.get("threads") or {}
    cloudflare = report.get("cloudflare") or {}
    lines = ["🧭 <b>SCM release check</b>", ""]
    lines.append(f"{icons.get(threads.get('state'), '⚪')} <b>Threads</b>: {threads.get('detail', '—')}")
    lines.append(f"   картинка: <code>{threads.get('image_mode', 'text')}</code>")
    lines.append(f"{icons.get(cloudflare.get('state'), '⚪')} <b>Cloudflare</b>: {cloudflare.get('detail', '—')}")
    if cloudflare.get("url"):
        lines.append(f"   URL: <code>{cloudflare['url']}</code>")
    lines.append(f"   INGEST_SECRET: {'задан' if cloudflare.get('secret') else 'не задан'}")
    steps = list(threads.get("steps") or []) + list(cloudflare.get("steps") or [])
    if steps:
        lines.append("")
        lines.append("<b>Дальше:</b>")
        for index, step in enumerate(steps, 1):
            lines.append(f"{index}. <code>{step}</code>")
    return "\n".join(lines)

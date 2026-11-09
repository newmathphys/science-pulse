"""Аудиторная аналитика SCM: подписчики, просмотры, оформление, посты.

Собирает то, что реально отдают площадки:
- Telegram — `getChatMemberCount` (подписчики канала) + публичные просмотры постов;
- Threads — `followers_count`, если Graph API его отдаёт;
- локальные метрики постов/дизайнов — из SQLite.

Секретов не печатает. Без ключей честно пишет `skipped`.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import requests

from .config import Config
from .growth import AudienceRegistry
from .storage import Storage

LOGGER = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"
THREADS_API = "https://graph.threads.com/v1.0/{user}"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class AudienceSnapshot:
    platform: str
    followers: int = 0
    status: str = "ok"
    detail: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "platform": self.platform,
            "followers": self.followers,
            "status": self.status,
            "detail": self.detail,
        }


class AudienceCollector:
    def __init__(self, config: Config, storage: Storage,
                 registry: Optional[AudienceRegistry] = None,
                 http_get: Optional[Callable[..., Any]] = None):
        self.config = config
        self.storage = storage
        self.registry = registry or AudienceRegistry(config.data_dir / "growth.db")
        self._get = http_get or requests.get

    def collect(self) -> List[AudienceSnapshot]:
        snapshots = [self._telegram(), self._threads()]
        for snapshot in snapshots:
            if snapshot.status == "ok":
                self.registry.add_snapshot(snapshot.platform, followers=snapshot.followers,
                                           meta={"detail": snapshot.detail})
        return snapshots

    def _telegram(self) -> AudienceSnapshot:
        token = self.config.telegram_token
        channel = self.config.telegram_channel
        if not token or not channel:
            return AudienceSnapshot("telegram", status="skipped", detail="нужны TG_BOT_TOKEN и TG_CHANNEL_ID")
        try:
            response = self._get(
                TELEGRAM_API.format(token=token, method="getChatMemberCount"),
                params={"chat_id": channel},
                timeout=15,
            )
            data = response.json() if hasattr(response, "json") else response
            if not data.get("ok"):
                return AudienceSnapshot("telegram", status="error", detail=str(data.get("description") or data)[:160])
            return AudienceSnapshot("telegram", followers=int(data.get("result") or 0), detail=channel)
        except Exception as exc:
            return AudienceSnapshot("telegram", status="error", detail=str(exc)[:160])

    def _threads(self) -> AudienceSnapshot:
        token = self.config.threads_token
        user = self.config.threads_user_id
        if not token or not user:
            return AudienceSnapshot("threads", status="skipped", detail="нужны TH_USER_ID и TH_ACCESS_TOKEN")
        try:
            response = self._get(
                THREADS_API.format(user=user),
                params={"fields": "id,username,followers_count", "access_token": token},
                timeout=15,
            )
            data = response.json() if hasattr(response, "json") else response
            if data.get("error") or data.get("followers_count") is None:
                return AudienceSnapshot("threads", status="skipped",
                                        detail="Graph API не отдал followers_count")
            return AudienceSnapshot("threads", followers=int(data.get("followers_count") or 0),
                                    detail=f"@{data.get('username') or user}")
        except Exception as exc:
            return AudienceSnapshot("threads", status="error", detail=str(exc)[:160])


class AudienceDashboard:
    def __init__(self, config: Config, storage: Storage,
                 registry: Optional[AudienceRegistry] = None):
        self.config = config
        self.storage = storage
        self.registry = registry or AudienceRegistry(config.data_dir / "growth.db")

    def build(self) -> Dict[str, Any]:
        metrics = self.storage.metrics_summary()
        audience = {item["platform"]: int(item.get("followers") or 0) for item in self.registry.latest_snapshots()}
        posts = {
            "ready": self.storage.count("ready"),
            "published": self.storage.count("published"),
            "failed": self.storage.count("failed"),
            "rejected": self.storage.count("rejected"),
        }
        domains: Dict[str, int] = {}
        for post in self.storage.list_posts(status="published", limit=2000):
            domains[post.domain] = domains.get(post.domain, 0) + 1
        top_posts = self._top_posts()
        designs = self._designs()
        recommendations = self._recommendations(audience, metrics, posts, designs)
        return {
            "generated_at": _now(),
            "audience": audience,
            "metrics": metrics,
            "posts": posts,
            "domains": domains,
            "top_posts": top_posts,
            "designs": designs,
            "targets": self.registry.report(),
            "recommendations": recommendations,
        }

    def _top_posts(self) -> List[Dict[str, Any]]:
        with self.storage.cursor() as connection:
            rows = connection.execute(
                """
                SELECT p.id, p.title, p.domain,
                       SUM(m.views) AS views, SUM(m.likes) AS likes, SUM(m.replies) AS replies
                FROM metrics m JOIN posts p ON p.id = m.post_id
                GROUP BY p.id ORDER BY (SUM(m.views) + 5 * SUM(m.likes) + 8 * SUM(m.replies)) DESC
                LIMIT 5
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def _designs(self) -> List[Dict[str, Any]]:
        try:
            from .themes import design_stats

            return design_stats(self.storage)
        except Exception:
            return []

    def _recommendations(self, audience: Dict[str, int], metrics: Dict[str, Any],
                         posts: Dict[str, int], designs: List[Dict[str, Any]]) -> List[str]:
        tips: List[str] = []
        if not audience.get("telegram"):
            tips.append("Telegram: подписчики не собраны — проверьте TG_BOT_TOKEN/канал и запустите growth collect.")
        if not audience.get("threads"):
            tips.append("Threads: вставьте TH_USER_ID и TH_ACCESS_TOKEN, затем growth collect.")
        if not (metrics.get("totals") or {}).get("samples"):
            tips.append("Метрик постов нет: запустите metrics --collect после публикации.")
        if posts.get("ready", 0) < 9:
            tips.append("Очередь ниже 9 постов — запустите harvest/kernel expand.")
        if designs and designs[0].get("engagement_score", 0) > 0:
            tips.append(f"Лидирующий дизайн: {designs[0]['theme']} — держать в ротации.")
        return tips

    def write(self, markdown_path: str | Path | None = None,
              html_path: str | Path | None = None) -> Dict[str, Path]:
        report = self.build()
        data_dir = self.config.data_dir
        md = Path(markdown_path) if markdown_path else data_dir / "growth_report.md"
        html = Path(html_path) if html_path else data_dir / "growth_report.html"
        md.parent.mkdir(parents=True, exist_ok=True)
        html.parent.mkdir(parents=True, exist_ok=True)
        md.write_text(render_markdown(report), encoding="utf-8")
        html.write_text(render_html(report), encoding="utf-8")
        return {"markdown": md, "html": html}


def render_markdown(report: Dict[str, Any]) -> str:
    audience = report.get("audience") or {}
    totals = (report.get("metrics") or {}).get("totals") or {}
    lines = [
        "# SCM Growth Report",
        "",
        f"Собрано: {report.get('generated_at')}",
        "",
        "## Аудитория",
        f"- Telegram: {audience.get('telegram', 0)}",
        f"- Threads: {audience.get('threads', 0)}",
        "",
        "## Контент",
        f"- Постов: published {report['posts']['published']} · ready {report['posts']['ready']} · failed {report['posts']['failed']}",
        f"- Просмотры: {totals.get('views', 0)} · реакции: {totals.get('likes', 0)} · ответы: {totals.get('replies', 0)}",
        f"- Замеров: {totals.get('samples', 0)}",
        "",
        "## Дисциплины",
    ]
    for domain, count in sorted((report.get("domains") or {}).items()):
        lines.append(f"- {domain}: {count}")
    lines += ["", "## Топ постов"]
    for item in report.get("top_posts") or []:
        lines.append(f"- {item['title']} [{item['domain']}] · 👁 {item['views']} · ❤ {item['likes']} · 💬 {item['replies']}")
    lines += ["", "## Дизайны"]
    for item in report.get("designs") or []:
        lines.append(
            f"- {item['theme']}: постов {item['posts']} · ср. охват {item.get('avg_views', 0)} · "
            f"индекс {item.get('index_pct', 0)}%"
        )
    lines += ["", "## Рекомендации"]
    lines += [f"- {tip}" for tip in report.get("recommendations") or []]
    return "\n".join(lines) + "\n"


def render_html(report: Dict[str, Any]) -> str:
    audience = report.get("audience") or {}
    totals = (report.get("metrics") or {}).get("totals") or {}
    rows = "".join(
        f"<tr><td>{item['title']}</td><td>{item['domain']}</td>"
        f"<td>{item['views']}</td><td>{item['likes']}</td><td>{item['replies']}</td></tr>"
        for item in report.get("top_posts") or []
    )
    tips = "".join(f"<li>{tip}</li>" for tip in report.get("recommendations") or [])
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><title>SCM Growth</title>
<style>
body{{background:#07090f;color:#ecf2ff;font-family:system-ui,sans-serif;margin:0;padding:24px}}
h1{{color:#00f5d4}} .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px}}
.card{{background:#101622;border:1px solid #222834;border-radius:14px;padding:16px}}
.big{{font-size:28px;font-weight:700}} table{{width:100%;border-collapse:collapse;margin-top:12px}}
td,th{{border-bottom:1px solid #222834;padding:8px;text-align:left}} small{{color:#8a94a6}}
</style></head><body>
<h1>SCM Growth Report</h1><small>{report.get('generated_at')}</small>
<div class="grid">
<div class="card"><div>Telegram</div><div class="big">{audience.get('telegram',0)}</div><small>подписчиков</small></div>
<div class="card"><div>Threads</div><div class="big">{audience.get('threads',0)}</div><small>подписчиков</small></div>
<div class="card"><div>Просмотры</div><div class="big">{totals.get('views',0)}</div><small>замеров {totals.get('samples',0)}</small></div>
<div class="card"><div>Реакции</div><div class="big">{totals.get('likes',0)}</div><small>ответов {totals.get('replies',0)}</small></div>
<div class="card"><div>Постов</div><div class="big">{report['posts']['published']}</div><small>ready {report['posts']['ready']}</small></div>
</div>
<h2>Топ постов</h2>
<table><tr><th>Пост</th><th>Дисциплина</th><th>👁</th><th>❤</th><th>💬</th></tr>{rows}</table>
<h2>Рекомендации</h2><ul>{tips}</ul>
</body></html>"""

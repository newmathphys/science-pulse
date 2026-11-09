from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence

import requests

from .config import Config
from .storage import Storage

LOGGER = logging.getLogger(__name__)

BLUESKY_BASE = "https://bsky.social/xrpc"
THREADS_BASE = "https://graph.threads.com/v1.0"
VK_API = "https://api.vk.com/method"
VK_VERSION = "5.199"

# Площадки с публичным API статистики, который мы умеем читать.
# Telegram читается через публичный веб-виджет t.me (embed=1).
SUPPORTED_PLATFORMS = ("mastodon", "bluesky", "vk", "threads", "telegram")
# Discord webhook статистику просмотров/реакций не отдаёт.
UNSUPPORTED_PLATFORMS = ("discord",)


def parse_compact_number(text: str) -> int:
    """«1.2K» → 1200, «3.5M» → 3500000, «1 234» → 1234."""
    cleaned = str(text or "").strip().replace("\u00a0", "").replace(" ", "").replace(",", ".")
    match = re.match(r"^([0-9]+(?:\.[0-9]+)?)([KkMm]?)$", cleaned)
    if not match:
        return 0
    value = float(match.group(1))
    suffix = match.group(2).lower()
    if suffix == "k":
        value *= 1_000
    elif suffix == "m":
        value *= 1_000_000
    return int(round(value))


def parse_tg_views(html: str) -> int:
    """Просмотры из виджета t.me: ``tgme_widget_message_views``."""
    match = re.search(r'tgme_widget_message_views[^>]*>([^<]+)<', html or "")
    return parse_compact_number(match.group(1)) if match else 0


@dataclass
class MetricsSample:
    """Один замер площадки по конкретному посту."""

    post_id: str
    platform: str
    views: int = 0
    likes: int = 0
    replies: int = 0
    status: str = "ok"  # ok | skipped | error
    error: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "post_id": self.post_id,
            "platform": self.platform,
            "views": self.views,
            "likes": self.likes,
            "replies": self.replies,
            "status": self.status,
            "error": self.error,
        }


class MetricsCollector:
    """Сборщик метрик площадок поверх таблицы `metrics`.

    Ничего не генерирует и не тратит платных API: читает статистику там, где
    площадка её отдаёт, и складывает снимок в SQLite. HTTP-слой инъектируется,
    поэтому тесты идут без сети.
    """

    def __init__(
        self,
        config: Config,
        storage: Storage,
        http_get: Optional[Callable[..., Any]] = None,
        http_post: Optional[Callable[..., Any]] = None,
    ):
        self.config = config
        self.storage = storage
        self._get = http_get or requests.get
        self._post = http_post or requests.post

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------
    def collect(
        self,
        limit: int = 50,
        platforms: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        targets = self.storage.metrics_targets(limit=limit, platforms=platforms)
        samples: List[MetricsSample] = []
        stored = 0
        for row in targets:
            sample = self._collect_one(row)
            samples.append(sample)
            if sample.status == "ok":
                self.storage.add_metrics(
                    sample.post_id,
                    sample.platform,
                    views=sample.views,
                    likes=sample.likes,
                    replies=sample.replies,
                )
                stored += 1
        summary = {
            "targets": len(targets),
            "stored": stored,
            "skipped": sum(1 for item in samples if item.status == "skipped"),
            "errors": sum(1 for item in samples if item.status == "error"),
            "samples": [item.as_dict() for item in samples],
        }
        try:
            from .signal_engine import FeedbackControllerUOS

            score = sum(
                item.views + 5 * item.likes + 8 * item.replies
                for item in samples if item.status == "ok"
            )
            summary["signal_feedback"] = FeedbackControllerUOS(self.storage, self.config).on_metrics(score)
        except Exception as exc:  # pragma: no cover - движок не должен ломать сбор
            LOGGER.warning("Signal feedback метрик: %s", exc)
        LOGGER.info("Метрики: сохранено %s замеров из %s целей", stored, len(targets))
        return summary

    # ------------------------------------------------------------------
    # Внутреннее: маршрутизация по площадкам
    # ------------------------------------------------------------------
    def _collect_one(self, row: Dict[str, Any]) -> MetricsSample:
        platform = str(row.get("platform") or "")
        post_id = str(row.get("post_id") or "")
        if platform in UNSUPPORTED_PLATFORMS:
            return MetricsSample(
                post_id=post_id,
                platform=platform,
                status="skipped",
                error="площадка не отдаёт метрики через доступный API",
            )
        handler = {
            "mastodon": self._collect_mastodon,
            "bluesky": self._collect_bluesky,
            "vk": self._collect_vk,
            "threads": self._collect_threads,
            "telegram": self._collect_telegram,
        }.get(platform)
        if handler is None:
            return MetricsSample(
                post_id=post_id,
                platform=platform,
                status="skipped",
                error="нет адаптера метрик",
            )
        try:
            return handler(row)
        except Exception as exc:  # защитный контур: одна площадка не рушит сбор
            LOGGER.warning("Метрики %s (%s): %s", platform, post_id, exc)
            return MetricsSample(post_id=post_id, platform=platform, status="error", error=str(exc)[:200])

    def _collect_telegram(self, row: Dict[str, Any]) -> MetricsSample:
        """Просмотры Telegram через публичный виджет ``t.me/<channel>/<id>?embed=1``.

        Токен бота наружу не уходит: читается только публичная страница поста.
        При сетевой ошибке мягко возвращается ``views=0``.
        """
        post_id = str(row["post_id"])
        external_id = str(row.get("external_id") or "").strip()
        channel = (self.config.telegram_channel or "").strip()
        username = channel if channel.startswith("@") else ""
        if not (external_id and username):
            return MetricsSample(
                post_id=post_id, platform="telegram", status="skipped",
                error="нужен @username канала и external_id сообщения",
            )
        url = f"https://t.me/{username.lstrip('@')}/{external_id}?embed=1"
        try:
            response = self._get(url, timeout=10)
            text = response.text if hasattr(response, "text") else str(response)
        except Exception as exc:
            return MetricsSample(post_id=post_id, platform="telegram", views=0,
                                 status="ok", error=f"сеть: {str(exc)[:120]}")
        return MetricsSample(post_id=post_id, platform="telegram", views=parse_tg_views(text))

    def _collect_mastodon(self, row: Dict[str, Any]) -> MetricsSample:
        post_id = str(row["post_id"])
        token = os.getenv("MASTODON_ACCESS_TOKEN", "")
        instance = self.config.mastodon_instance.rstrip("/")
        if not (token and instance):
            return MetricsSample(post_id, "mastodon", status="skipped", error="MASTODON_ACCESS_TOKEN не задан")
        response = self._get(
            f"{instance}/api/v1/statuses/{row['external_id']}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=20,
        )
        data = response.json()
        return MetricsSample(
            post_id,
            "mastodon",
            likes=int(data.get("favourites_count") or 0),
            replies=int(data.get("replies_count") or 0),
        )

    def _collect_bluesky(self, row: Dict[str, Any]) -> MetricsSample:
        post_id = str(row["post_id"])
        response = self._get(
            f"{BLUESKY_BASE}/app.bsky.feed.getPostThread",
            params={"uri": row["external_id"]},
            timeout=20,
        )
        data = response.json()
        post = (data.get("thread") or {}).get("post") or {}
        return MetricsSample(
            post_id,
            "bluesky",
            views=int(post.get("viewCount") or 0),
            likes=int(post.get("likeCount") or 0),
            replies=int(post.get("replyCount") or 0),
        )

    def _collect_vk(self, row: Dict[str, Any]) -> MetricsSample:
        post_id = str(row["post_id"])
        token = os.getenv("VK_ACCESS_TOKEN", "")
        group = self.config.vk_group_id.lstrip("-")
        if not (token and group):
            return MetricsSample(post_id, "vk", status="skipped", error="VK_ACCESS_TOKEN/VK_GROUP_ID не заданы")
        owner, number = self._vk_ids(row, group)
        response = self._get(
            f"{VK_API}/wall.getById",
            params={
                "posts": f"{owner}_{number}",
                "extended": 1,
                "access_token": token,
                "v": VK_VERSION,
            },
            timeout=20,
        )
        data = response.json()
        items = (data.get("response") or {}).get("items") or []
        if not items:
            return MetricsSample(post_id, "vk", status="error", error=str(data)[:200])
        item = items[0]
        return MetricsSample(
            post_id,
            "vk",
            views=int((item.get("views") or {}).get("count") or 0),
            likes=int((item.get("likes") or {}).get("count") or 0),
            replies=int((item.get("comments") or {}).get("count") or 0),
        )

    @staticmethod
    def _vk_ids(row: Dict[str, Any], group: str) -> tuple[str, str]:
        match = re.search(r"wall(-?\d+)_(\d+)", str(row.get("url") or ""))
        if match:
            return match.group(1), match.group(2)
        return f"-{group}", str(row.get("external_id") or "")

    def _collect_threads(self, row: Dict[str, Any]) -> MetricsSample:
        post_id = str(row["post_id"])
        token = self.config.threads_token
        if not token:
            return MetricsSample(post_id, "threads", status="skipped", error="TH_ACCESS_TOKEN не задан")
        response = self._get(
            f"{THREADS_BASE}/{row['external_id']}/insights",
            params={"metric": "views,likes,replies", "access_token": token},
            timeout=20,
        )
        data = response.json()
        values: Dict[str, int] = {}
        for item in data.get("data") or []:
            series = item.get("values") or []
            values[str(item.get("name"))] = int((series[0] or {}).get("value") or 0) if series else 0
        return MetricsSample(
            post_id,
            "threads",
            views=values.get("views", 0),
            likes=values.get("likes", 0),
            replies=values.get("replies", 0),
        )


def format_metrics_summary(summary: Dict[str, Any], html: bool = False) -> str:
    """Текстовый (или HTML для Telegram) отчёт по агрегату метрик."""
    totals = summary.get("totals") or {}
    header = "📊 <b>Метрики площадок</b>" if html else "📊 Метрики площадок"
    lines = [
        header,
        (
            f"Просмотры: {totals.get('views', 0)} · Реакции: {totals.get('likes', 0)} · "
            f"Ответы: {totals.get('replies', 0)} · Замеров: {totals.get('samples', 0)}"
        ),
    ]
    rows = summary.get("by_platform") or []
    for item in rows:
        lines.append(
            f"• {item['platform']}: 👁 {item['views']} · ❤ {item['likes']} · "
            f"💬 {item['replies']} (постов {item['posts']})"
        )
    style_rows = summary.get("by_style") or []
    if len(style_rows) >= 2:
        lines.append("A/B стилей карточки:")
        for item in style_rows:
            lines.append(
                f"  {item['variant']}: 👁 {item['views']} · ❤ {item['likes']} (постов {item['posts']})"
            )
    if not rows:
        lines.append("Данных нет: запустите `metrics --collect` после публикации.")
    return "\n".join(lines)


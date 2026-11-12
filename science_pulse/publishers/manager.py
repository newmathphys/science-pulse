from __future__ import annotations

import logging
from typing import Dict, Iterable, List, Optional

from ..config import Config
from ..models import CardArtifact, Post, PublishResult
from ..storage import Storage
from .base import Publisher, PublishContext
from .bluesky import BlueskyPublisher
from .discord import DiscordPublisher
from .mastodon import MastodonPublisher
from .telegram import TelegramPublisher
from .threads import ThreadsPublisher
from .vk import VKPublisher

LOGGER = logging.getLogger(__name__)

PUBLISHER_CLASSES = {
    "telegram": TelegramPublisher,
    "threads": ThreadsPublisher,
    "bluesky": BlueskyPublisher,
    "discord": DiscordPublisher,
    "mastodon": MastodonPublisher,
    "vk": VKPublisher,
}

ORDER = ["telegram", "threads", "bluesky", "discord", "mastodon", "vk"]


class PublisherManager:
    def __init__(self, config: Config, storage: Storage):
        self.config = config
        self.storage = storage
        self.publishers: Dict[str, Publisher] = {}
        for name in ORDER:
            if not config.platform_enabled(name):
                continue
            cls = PUBLISHER_CLASSES.get(name)
            if not cls:
                continue
            try:
                self.publishers[name] = cls(config)
            except Exception as exc:  # pragma: no cover
                LOGGER.warning("Публикатор %s не инициализирован: %s", name, exc)

    def available_platforms(self) -> List[str]:
        return [name for name, publisher in self.publishers.items() if publisher.available()]

    def publish(
        self,
        post: Post,
        card: CardArtifact,
        site_url: str = "",
        public_card_url: str = "",
        video_url: str = "",
        targets: Optional[Iterable[str]] = None,
        video: bool = False,
    ) -> List[PublishResult]:
        if targets is None:
            selected = list(self.publishers.keys())
        elif isinstance(targets, str):
            selected = [targets]
        else:
            selected = list(targets)
        selected = [name for name in ORDER if name in selected]
        from ..platforms_info import PlatformRules

        rules = PlatformRules.load(self.storage, self.config)
        public_card_url = public_card_url or str((post.meta or {}).get("card_url") or "")
        context = PublishContext(
            site_url=site_url,
            public_card_url=public_card_url,
            video_url=video_url,
            video=video,
            rules=rules,
        )
        results: List[PublishResult] = []

        for name in selected:
            publisher = self.publishers.get(name)
            if not publisher:
                results.append(PublishResult(platform=name, ok=False, skipped=True, error="адаптер не включён"))
                continue
            if not publisher.available():
                results.append(
                    PublishResult(platform=name, ok=False, skipped=True, error="нет токенов/настроек")
                )
                continue
            if self.storage.publication_exists(post.id, name):
                results.append(
                    PublishResult(
                        platform=name,
                        ok=True,
                        skipped=True,
                        error="уже опубликовано",
                        meta={"file_id": post.card_file_id} if name == "telegram" and post.card_file_id else {},
                    )
                )
                continue

            try:
                result = publisher.publish(post, card, context)
            except Exception as exc:
                result = PublishResult(platform=name, ok=False, error=str(exc)[:200])

            results.append(result)
            self.storage.record_publication(post.id, result)

            if name == "threads" and result.ok:
                meta = result.meta or {}
                if meta.get("video_id"):
                    post.meta["threads_video_id"] = str(meta["video_id"])
                    post.meta["threads_video_url"] = str(meta.get("video_url") or "")
                    try:
                        self.storage.set_post_meta(post.id, "threads_video_id", post.meta["threads_video_id"])
                        self.storage.set_post_meta(post.id, "threads_video_url", post.meta["threads_video_url"])
                    except Exception as exc:
                        LOGGER.warning("Threads video meta: %s", exc)

            if name == "telegram" and result.ok:
                file_id = (result.meta or {}).get("file_id")
                if file_id:
                    post.card_file_id = str(file_id)
                    post.meta["card_file_id"] = str(file_id)
                    self.storage.set_card_file_id(post.id, str(file_id))
                worker = self.config.cf_worker_url
                if file_id and worker:
                    context.public_card_url = f"{worker}/tg-cdn/{file_id}.png"
                elif not context.public_card_url and self.config.site_base_url and post.id:
                    context.public_card_url = f"{self.config.site_base_url}/cards/{post.id}.png"

        return results

    def status(self) -> List[Dict[str, object]]:
        return [
            {
                "name": name,
                "enabled": True,
                "available": publisher.available(),
            }
            for name, publisher in self.publishers.items()
        ]

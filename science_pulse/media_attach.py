from __future__ import annotations

import logging
import time
from typing import Optional

import requests

from .config import Config
from .models import Post, PublishResult
from .publishers.base import audiogram_url
from .publishers.threads import ThreadsPublisher
from .storage import Storage
from .voice import audiogram_for_post

LOGGER = logging.getLogger(__name__)


def latest_published(storage: Storage, limit: int = 1) -> list[Post]:
    return storage.list_posts(status="published", limit=max(1, int(limit)), order="published_at DESC")


def prepare_audiogram(post: Post, config: Config) -> Optional[str]:
    """Готовит MP4-аудиограмму до сборки сайта, чтобы она попала в gh-pages."""
    path = audiogram_for_post(post, config)
    return str(path) if path else None


def _wait_public(url: str, timeout_s: int = 120, pause: float = 5.0) -> bool:
    """Ждёт, пока GitHub Pages отдаст аудиограмму (деплой идёт асинхронно)."""
    deadline = time.time() + max(10, int(timeout_s))
    while time.time() < deadline:
        try:
            response = requests.get(url, timeout=20, stream=True)
            if response.status_code == 200 and "text/html" not in response.headers.get("content-type", ""):
                response.close()
                return True
            response.close()
        except Exception as exc:
            LOGGER.debug("ожидание %s: %s", url, exc)
        time.sleep(pause)
    return False


def attach_threads_video(
    post: Post,
    config: Config,
    storage: Storage,
    force: bool = False,
    wait_public_s: int = 300,
) -> PublishResult:
    """Публикует видео-ответ в Threads к уже опубликованному посту."""
    if (post.meta.get("threads_video_reply_id") or post.meta.get("threads_video_id")) and not force:
        return PublishResult(
            platform="threads",
            ok=True,
            external_id=str(post.meta.get("threads_video_reply_id") or post.meta.get("threads_video_id")),
            url=str(post.meta.get("threads_video_permalink") or post.meta.get("threads_video_url") or ""),
            meta={"skipped": "уже прикреплено"},
        )

    publications = storage.publications_for(post.id)
    parent = next(
        (item for item in publications if item.get("platform") == "threads" and item.get("status") == "ok"),
        None,
    )
    if not parent or not parent.get("external_id"):
        return PublishResult(platform="threads", ok=False, error="нет успешной публикации Threads")

    path = prepare_audiogram(post, config)
    if not path:
        return PublishResult(platform="threads", ok=False, error="не удалось собрать аудиограмму")

    url = audiogram_url(post, config.site_base_url)
    if not url:
        return PublishResult(platform="threads", ok=False, error="не задан SP_SITE_BASE_URL")
    if not _wait_public(url, timeout_s=wait_public_s):
        return PublishResult(platform="threads", ok=False, error=f"аудиограмма ещё не опубликована: {url}")

    text = f"Видеоразбор: {post.title}"
    if config.site_base_url:
        text = f"{text}\n\n{config.site_base_url}/post/{post.id}.html"
    publisher = ThreadsPublisher(config)
    result = publisher.publish_video_reply(str(parent["external_id"]), url, text)
    if result.ok:
        storage.set_post_meta(post.id, "threads_video_reply_id", result.external_id)
        storage.set_post_meta(post.id, "threads_video_url", result.url)
        storage.set_post_meta(post.id, "threads_video_source", url)
    return result

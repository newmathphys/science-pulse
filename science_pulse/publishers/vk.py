from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

import requests

from ..config import Config
from ..models import CardArtifact, Post, PublishResult
from ..text import formula_to_unicode, truncate
from .base import Publisher, PublishContext, audio_link, context_rules, result_skipped

API = "https://api.vk.com/method"
VERSION = "5.199"
LOGGER = logging.getLogger(__name__)


def build_message(post: Post, context: PublishContext, rules: Any) -> str:
    """Собирает текст записи VK по правилам площадки (используется и в демо)."""
    message_parts = [
        f"⚡ {truncate(post.plain_title, 220)}",
        f"❓ {truncate(post.plain_hook, 200)}",
        formula_to_unicode(truncate(post.body, 1200), 1200),
    ]
    formula = post.formula_latex or post.formula_plain
    if formula:
        message_parts.append(f"📐 {truncate(formula, 200)}")
    if rules.audio_mode("vk") == "link":
        link = audio_link(post, context.site_url)
        if link:
            message_parts.append(f"🎧 Аудио-разбор: {link}")
    if context.site_url:
        message_parts.append(f"🪐 {context.site_url}")
    message_parts.append(post.hashtags)
    return truncate("\n\n".join(message_parts), rules.limit("vk", "max_caption_chars", 16384))


class VKPublisher(Publisher):
    name = "vk"

    def __init__(self, config: Config):
        self.config = config
        self.group_id = config.vk_group_id.lstrip("-")
        self.token = os.getenv("VK_ACCESS_TOKEN", "")

    def available(self) -> bool:
        return bool(self.group_id and self.token)

    def _params(self) -> Dict[str, str]:
        return {"access_token": self.token, "v": VERSION}

    def _upload_video(self, post: Post) -> str:
        """Прямая загрузка видео-аудиограммы в VK (video.save → upload_url)."""
        from ..voice import audiogram_for_post

        path = audiogram_for_post(post, self.config)
        if path is None:
            return ""
        try:
            saved = requests.get(
                f"{API}/video.save",
                params={**self._params(), "group_id": self.group_id, "name": truncate(post.title, 100)},
                timeout=20,
            ).json()
            response = saved.get("response") or {}
            upload_url, video_id = response.get("upload_url"), response.get("video_id")
            if not upload_url or not video_id:
                LOGGER.warning("VK video.save: %s", str(saved)[:160])
                return ""
            requests.post(
                upload_url,
                files={"video_file": (Path(path).name, Path(path).read_bytes(), "video/mp4")},
                timeout=180,
            )
            return f"video-{self.group_id}_{video_id}"
        except Exception as exc:
            LOGGER.warning("VK video.save: %s", exc)
            return ""

    def publish(self, post: Post, card: CardArtifact, context: PublishContext) -> PublishResult:
        if not self.available():
            return result_skipped(self.name, "VK_GROUP_ID/VK_ACCESS_TOKEN не заданы")
        try:
            upload_server = requests.get(
                f"{API}/photos.getWallUploadServer",
                params={**self._params(), "group_id": self.group_id},
                timeout=20,
            ).json()
            upload_url = (upload_server.get("response") or {}).get("upload_url")
            if not upload_url:
                return PublishResult(platform=self.name, ok=False, error=str(upload_server)[:200])

            uploaded = requests.post(
                upload_url,
                files={"photo": ("card.png", card.data, "image/png")},
                timeout=30,
            ).json()
            saved = requests.post(
                f"{API}/photos.saveWallPhoto",
                data={
                    **self._params(),
                    "group_id": self.group_id,
                    "photo": uploaded.get("photo"),
                    "server": uploaded.get("server"),
                    "hash": uploaded.get("hash"),
                },
                timeout=25,
            ).json()
            photos = saved.get("response") or []
            if not photos:
                return PublishResult(platform=self.name, ok=False, error=str(saved)[:200])
            photo = photos[0]
            attachment = f"photo{photo.get('owner_id')}_{photo.get('id')}"

            message_parts = [build_message(post, context, rules)]

            # Видео-аудиограмма: VK принимает .mp4 напрямую (без сайта).
            video_attachment = ""
            if rules.audio_mode(self.name) == "mp4":
                video_attachment = self._upload_video(post)
            attachments = ",".join(item for item in (attachment, video_attachment) if item)

            wall = requests.post(
                f"{API}/wall.post",
                data={
                    **self._params(),
                    "owner_id": f"-{self.group_id}",
                    "from_group": 1,
                    "message": message_parts[0],
                    "attachments": attachments,
                },
                timeout=25,
            ).json()
            post_id = (wall.get("response") or {}).get("post_id")
            return PublishResult(
                platform=self.name,
                ok=bool(post_id),
                external_id=str(post_id) if post_id else None,
                url=f"https://vk.com/wall-{self.group_id}_{post_id}" if post_id else None,
                error=None if post_id else str(wall)[:200],
            )
        except Exception as exc:
            return PublishResult(platform=self.name, ok=False, error=str(exc)[:200])

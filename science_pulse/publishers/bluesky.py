from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

import requests

from ..config import Config
from ..models import CardArtifact, Post, PublishResult
from ..text import formula_to_unicode, truncate
from .base import Publisher, PublishContext, audio_link, context_rules, result_skipped

BASE = "https://bsky.social/xrpc"
LOGGER = logging.getLogger(__name__)


class BlueskyPublisher(Publisher):
    name = "bluesky"

    def __init__(self, config: Config):
        self.config = config
        self.handle = os.getenv("BLUESKY_HANDLE", "")
        self.password = os.getenv("BLUESKY_APP_PASSWORD", "")

    def available(self) -> bool:
        return bool(self.handle and self.password)

    def publish(self, post: Post, card: CardArtifact, context: PublishContext) -> PublishResult:
        if not self.available():
            return result_skipped(self.name, "BLUESKY_HANDLE/BLUESKY_APP_PASSWORD не заданы")
        try:
            session = requests.post(
                f"{BASE}/com.atproto.server.createSession",
                json={"identifier": self.handle, "password": self.password},
                timeout=20,
            ).json()
            jwt = session.get("accessJwt")
            did = session.get("did")
            if not jwt or not did:
                return PublishResult(platform=self.name, ok=False, error=str(session)[:200])

            headers = {"Authorization": f"Bearer {jwt}"}
            rules = context_rules(context, self.config)
            blob = requests.post(
                f"{BASE}/com.atproto.repo.uploadBlob",
                headers={**headers, "Content-Type": "image/png"},
                data=card.data,
                timeout=25,
            ).json().get("blob")

            text = self._text(post, context, rules)
            record: Dict[str, Any] = {
                "$type": "app.bsky.feed.post",
                "text": text,
                "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            # Видео-аудиограмма: Bluesky принимает .mp4 напрямую (без сайта).
            video_blob = None
            if rules.audio_mode(self.name) == "mp4":
                video_blob = self._upload_video(post, headers)
            if video_blob:
                record["embed"] = {
                    "$type": "app.bsky.embed.video",
                    "video": video_blob,
                    "alt": truncate(post.title, 280),
                }
            elif blob:
                record["embed"] = {
                    "$type": "app.bsky.embed.images",
                    "images": [{"alt": truncate(post.title, 280), "image": blob}],
                }

            response = requests.post(
                f"{BASE}/com.atproto.repo.createRecord",
                headers=headers,
                json={"repo": did, "collection": "app.bsky.feed.post", "record": record},
                timeout=25,
            ).json()
            uri = response.get("uri")
            rkey = uri.rsplit("/", 1)[-1] if uri else ""
            return PublishResult(
                platform=self.name,
                ok=bool(uri),
                external_id=uri,
                url=f"https://bsky.app/profile/{self.handle}/post/{rkey}" if rkey else None,
                meta={"uri": uri},
            )
        except Exception as exc:
            return PublishResult(platform=self.name, ok=False, error=str(exc)[:200])

    def _upload_video(self, post: Post, headers: Dict[str, str]) -> Optional[Dict[str, Any]]:
        """Прямая загрузка видео-аудиограммы в AT Protocol (без публичного URL)."""
        from ..voice import audiogram_for_post

        path = audiogram_for_post(post, self.config)
        if path is None:
            return None
        try:
            payload = requests.post(
                f"{BASE}/com.atproto.repo.uploadBlob",
                headers={**headers, "Content-Type": "video/mp4"},
                data=Path(path).read_bytes(),
                timeout=180,
            ).json()
            return payload.get("blob")
        except Exception as exc:
            LOGGER.warning("Bluesky uploadBlob video: %s", exc)
            return None

    def _text(self, post: Post, context: PublishContext, rules: Any) -> str:
        limit = rules.limit(self.name, "max_caption_chars", 300)
        mode = rules.audio_mode(self.name)
        formula = formula_to_unicode(post.formula_latex or post.formula_plain, 60)
        parts = [f"⚡ {truncate(post.plain_title, 90)}"]
        if post.plain_hook:
            parts.append(f"❓ {truncate(post.plain_hook, 90)}")
        if formula:
            parts.append(f"📐 {formula}")
        # Bluesky не принимает аудиофайлы: доставляем ссылку на аудио-разбор.
        if mode == "link":
            link = audio_link(post, context.site_url)
            if link:
                parts.append(f"🎧 {link}")
        if context.site_url:
            parts.append(f"🪐 {context.site_url}")
        return truncate("\n\n".join(parts), max(60, limit - 2))

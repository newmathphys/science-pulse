from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

import requests

from ..config import Config
from ..models import CardArtifact, Post, PublishResult
from ..text import formula_to_unicode, truncate
from .base import Publisher, PublishContext, audio_link, context_rules, result_skipped


def build_status(post: Post, context: PublishContext, rules: Any) -> str:
    """Собирает текст статуса Mastodon по правилам площадки (и для демо)."""
    limit = rules.limit("mastodon", "max_caption_chars", 500)
    formula = post.formula_latex or post.formula_plain
    text_parts = [f"⚡ {truncate(post.plain_title, 180)}"]
    if post.plain_hook:
        text_parts.append(f"❓ {truncate(post.plain_hook, 180)}")
    text_parts.append(formula_to_unicode(truncate(post.body, 180), 180))
    if formula:
        text_parts.append(f"\\[ {truncate(formula, 140)} \\]")
    if rules.audio_mode("mastodon") == "link":
        link = audio_link(post, context.site_url)
        if link:
            text_parts.append(f"🎧 {link}")
    if context.site_url:
        text_parts.append(f"🪐 {context.site_url}")
    text_parts.append(post.hashtags)
    return truncate("\n\n".join(text_parts), max(80, limit - 5))


class MastodonPublisher(Publisher):
    name = "mastodon"

    def __init__(self, config: Config):
        self.config = config
        self.instance = config.mastodon_instance.rstrip("/")
        self.token = os.getenv("MASTODON_ACCESS_TOKEN", "")

    def available(self) -> bool:
        return bool(self.instance and self.token)

    def publish(self, post: Post, card: CardArtifact, context: PublishContext) -> PublishResult:
        if not self.available():
            return result_skipped(self.name, "MASTODON_ACCESS_TOKEN не задан")

        rules = context_rules(context, self.config)
        limit = rules.limit(self.name, "max_caption_chars", 500)
        headers = {"Authorization": f"Bearer {self.token}"}
        try:
            media_response = requests.post(
                f"{self.instance}/api/v2/media",
                headers=headers,
                files={"file": ("card.png", card.data, "image/png")},
                data={"description": truncate(post.title, 300)},
                timeout=25,
            )
            media = media_response.json()
            media_id = media.get("id")

            status = build_status(post, context, rules)

            media_ids = [media_id] if media_id else []
            # Mastodon нативно играет аудио — прикрепляем mp3 вторым вложением.
            if rules.audio_mode(self.name) == "file":
                from ..voice import voice_for_post

                artifact = voice_for_post(post, self.config)
                if artifact:
                    audio_response = requests.post(
                        f"{self.instance}/api/v2/media",
                        headers=headers,
                        files={"file": ("audio.mp3", Path(artifact.mp3_path).read_bytes(), "audio/mpeg")},
                        data={"description": truncate(post.title, 300)},
                        timeout=90,
                    )
                    audio_media = audio_response.json()
                    if audio_media.get("id"):
                        media_ids.append(audio_media["id"])

            payload: Dict[str, Any] = {"status": status, "visibility": "public"}
            if media_ids:
                payload["media_ids"] = media_ids
            response = requests.post(
                f"{self.instance}/api/v1/statuses",
                headers=headers,
                json=payload,
                timeout=25,
            )
            result = response.json()
            return PublishResult(
                platform=self.name,
                ok=bool(result.get("id")),
                external_id=str(result.get("id")) if result.get("id") else None,
                url=result.get("url"),
                error=None if result.get("id") else str(result)[:200],
            )
        except Exception as exc:
            return PublishResult(platform=self.name, ok=False, error=str(exc)[:200])

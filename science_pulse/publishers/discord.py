from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

import requests

from ..config import Config
from ..models import CardArtifact, Post, PublishResult
from ..text import formula_to_unicode, truncate
from .base import Publisher, PublishContext, context_rules, result_skipped

COLORS = {"math": 0x00F5D4, "physics": 0xFF007F, "cs": 0xFEE440}


def build_embed(post: Post, context: PublishContext, rules: Any) -> Dict[str, Any]:
    """Собирает embed Discord по правилам площадки (используется и в демо)."""
    embed_limit = rules.limit("discord", "max_embed_chars", 4096)
    description = (
        f"**❓ {truncate(post.plain_hook, 200)}**\n\n"
        f"{formula_to_unicode(truncate(post.body, 900), 900)}"
    )
    if post.formula_latex or post.formula_plain:
        description += f"\n\n```\n{truncate(post.formula_latex or post.formula_plain, 300)}\n```"
    if context.site_url:
        description += f"\n\n🪐 [Открыть разбор]({context.site_url})"
    return {
        "title": f"⚡ {truncate(post.plain_title, 240)}",
        "url": context.site_url or None,
        "color": COLORS.get(post.domain, 0x00F5D4),
        "description": truncate(description, max(500, embed_limit - 120)),
        "image": {"url": "attachment://card.png"},
        "footer": {"text": f"Science Pulse • {post.label}"},
    }


class DiscordPublisher(Publisher):
    name = "discord"

    def __init__(self, config: Config):
        self.config = config
        self.webhook = os.getenv("DISCORD_WEBHOOK_URL", "")

    def available(self) -> bool:
        return bool(self.webhook)

    def publish(self, post: Post, card: CardArtifact, context: PublishContext) -> PublishResult:
        if not self.available():
            return result_skipped(self.name, "DISCORD_WEBHOOK_URL не задан")

        rules = context_rules(context, self.config)
        embed = build_embed(post, context, rules)

        payload = {"embeds": [embed]}
        files: Dict[str, Any] = {"file": ("card.png", card.data, "image/png")}
        voice_meta: Dict[str, Any] = {}
        # Discord умеет прикреплять аудио вложением — используем это.
        if rules.audio_mode(self.name) == "file":
            from ..voice import voice_for_post

            artifact = voice_for_post(post, self.config)
            if artifact:
                files["audio"] = ("audio.mp3", Path(artifact.mp3_path).read_bytes(), "audio/mpeg")
                voice_meta = {"voice": "file", "voice_duration": round(artifact.duration_s, 1)}
        try:
            response = requests.post(
                self.webhook,
                data={"payload_json": json.dumps(payload, ensure_ascii=False)},
                files=files,
                timeout=40,
            )
            return PublishResult(
                platform=self.name,
                ok=response.status_code in (200, 204),
                external_id=None,
                meta={"status": response.status_code, **voice_meta},
                error=None if response.status_code in (200, 204) else response.text[:200],
            )
        except Exception as exc:
            return PublishResult(platform=self.name, ok=False, error=str(exc)[:200])

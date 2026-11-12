"""Публичный медиа-архив для соцсетей: GitHub Releases.

Threads/Pinterest не принимают локальный файл — им нужен публичный URL.
Пока R2 не включён, используем месячные GitHub Releases `media-YYYY-MM`.
Локально без `GITHUB_TOKEN` модуль мягко возвращает пустой URL.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import requests

from .config import Config
from .models import Post
from .voice import audiogram_for_post

LOGGER = logging.getLogger(__name__)


def _repo() -> str:
    return os.getenv("GITHUB_REPOSITORY", "").strip()


def _token() -> str:
    return os.getenv("GITHUB_TOKEN", "").strip() or os.getenv("GH_TOKEN", "").strip()


def _month_tag(post: Post) -> str:
    stamp = getattr(post, "created_at", "") or ""
    try:
        moment = datetime.fromisoformat(str(stamp))
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
    except ValueError:
        moment = datetime.now(timezone.utc)
    return f"media-{moment.strftime('%Y-%m')}"


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _ensure_release(repo: str, tag: str, token: str) -> Optional[int]:
    base = f"https://api.github.com/repos/{repo}/releases"
    try:
        found = requests.get(f"{base}/tags/{tag}", headers=_headers(token), timeout=30)
        if found.status_code == 200:
            return int((found.json() or {}).get("id") or 0) or None
        created = requests.post(
            base,
            headers=_headers(token),
            json={
                "tag_name": tag,
                "name": f"Science Pulse media {tag.split('-', 1)[-1]}",
                "body": "Месячный архив карточек, аудио и видео Science Pulse.",
            },
            timeout=30,
        )
        if created.status_code in (200, 201):
            return int((created.json() or {}).get("id") or 0) or None
        LOGGER.warning("media release %s: %s %s", tag, created.status_code, created.text[:160])
    except Exception as exc:
        LOGGER.warning("media release %s: %s", tag, exc)
    return None


def upload_file(post: Post, config: Config, path: str | Path, kind: str) -> str:
    """Загружает произвольный файл в месячный Release и возвращает public URL."""
    token, repo = _token(), _repo()
    if not token or not repo:
        return ""
    source = Path(path)
    if not source.is_file():
        return ""
    tag = _month_tag(post)
    release_id = _ensure_release(repo, tag, token)
    if not release_id:
        return ""
    name = f"{kind}-{post.id}{source.suffix}"
    url = f"https://uploads.github.com/repos/{repo}/releases/{release_id}/assets"
    try:
        with source.open("rb") as handle:
            response = requests.post(
                url,
                headers={**_headers(token), "Content-Type": "application/octet-stream"},
                params={"name": name},
                data=handle,
                timeout=180,
            )
    except Exception as exc:
        LOGGER.warning("media upload %s/%s: %s", kind, post.id, exc)
        return ""
    if response.status_code in (200, 201):
        return str((response.json() or {}).get("browser_download_url") or "")
    if response.status_code == 422:
        return f"https://github.com/{repo}/releases/download/{tag}/{name}"
    LOGGER.warning("media upload %s/%s: %s %s", kind, post.id, response.status_code, response.text[:160])
    return ""


def upload_card(post: Post, config: Config) -> str:
    card = Path(post.card_path) if post.card_path else config.cards_dir / f"{post.id}.png"
    if not card.is_file():
        card = config.cards_dir / f"{post.id}.png"
    return upload_file(post, config, card, "card")


def upload_audio(post: Post, config: Config) -> str:
    from .voice import voice_for_post

    artifact = voice_for_post(post, config)
    if artifact is None:
        return ""
    return upload_file(post, config, artifact.mp3_path, "audio")


def upload_audiogram(post: Post, config: Config) -> str:
    """Готовит MP4 и загружает его в GitHub Release. Возвращает public URL."""
    path = audiogram_for_post(post, config)
    if not path:
        return ""
    return upload_file(post, config, path, "audiogram")


def upload_post_media(post: Post, config: Config) -> dict[str, str]:
    """Карточка + аудио + аудиограмма; пустые значения при отсутствии токена."""
    if not _token() or not _repo():
        return {}
    result = {
        "card_url": upload_card(post, config),
        "audio_url": upload_audio(post, config),
        "audiogram_url": upload_audiogram(post, config),
    }
    return {key: value for key, value in result.items() if value}

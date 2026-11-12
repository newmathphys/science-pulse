from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

import requests

from ..config import Config
from ..models import CardArtifact, Post, PublishResult
from ..growth import ThreadsGrowthEngine, telegram_url
from ..text import split_text, truncate
from .base import (
    Publisher,
    PublishContext,
    audio_link,
    audiogram_url,
    build_short_text,
    context_rules,
    formula_frame,
    result_skipped,
)

LOGGER = logging.getLogger(__name__)


class ThreadsPublisher(Publisher):
    name = "threads"

    def __init__(self, config: Config):
        self.config = config
        self.user_id = config.threads_user_id
        self.token = config.threads_token
        self.api = "https://graph.threads.com/v1.0"
        self.base = f"{self.api}/{self.user_id}"

    def available(self) -> bool:
        return bool(self.user_id and self.token)

    def image_mode(self) -> str:
        """Откуда Threads возьмёт картинку: cloudflare | site | text."""
        if self.config.cf_worker_url:
            return "cloudflare"
        if self.config.site_base_url:
            return "site"
        return "text"

    def publish(self, post: Post, card: CardArtifact, context: PublishContext) -> PublishResult:
        if not self.available():
            return result_skipped(self.name, "TH_USER_ID/TH_ACCESS_TOKEN не заданы")

        rules = context_rules(context, self.config)
        limit = rules.limit(self.name, "max_caption_chars", 500)
        chain_parts = max(1, rules.limit(self.name, "max_chain_parts", 2))
        video_first = bool(context.video_url) and bool(
            (self.config.raw.get("threads") or {}).get("video_first", False)
        )
        if video_first:
            chain_parts = max(2, chain_parts)

        growth = ThreadsGrowthEngine(self.config)
        if growth.enabled:
            chunks = growth.chain(
                post,
                site_url=context.site_url,
                tg_url=telegram_url(self.config),
                limit=max(80, limit - 10),
            )
        else:
            text = build_short_text(post, limit=limit, site_url=context.site_url, include_link=False)
            mode = rules.audio_mode(self.name)
            # В режиме TEXT формулу оборачиваем в мобильную рамку (LaTeX не рендерится).
            if mode in ("text", "link") and mode != "mp4":
                frame = formula_frame(post)
                if frame and len(frame) + 2 <= limit:
                    text = f"{frame}\n\n{truncate(text, max(40, limit - len(frame) - 2))}"
            chunks = split_text(text, max(80, limit - 10))
            mode = rules.audio_mode(self.name)
            # Звук: Threads не принимает .ogg/.mp3 — либо ссылка, либо видео-аудиограмма.
            if mode == "mp4" and not video_first:
                audiogram = audiogram_url(post, context.site_url)
                if audiogram and chunks:
                    chunks[0] = truncate(f"{chunks[0]}\n\nВидеоразбор: {audiogram}", limit)
            elif mode == "link":
                link = audio_link(post, context.site_url)
                if link:
                    chunks[-1] = truncate(f"{chunks[-1]}\n\nСлушать на сайте: {link}", limit)
            if context.site_url:
                chunks[-1] = truncate(f"{chunks[-1]}\n\n{context.site_url}", limit)

            # Ответ на задачу уходит отдельным сообщением цепочки (спойлеров в Threads нет).
            from .base import challenge_answer_line

            answer_line = challenge_answer_line(post)
            if answer_line:
                chunks.append(answer_line)
        if not chunks:
            return PublishResult(platform=self.name, ok=False, error="пустой текст")
        if video_first and context.public_card_url and len(chunks) < 2:
            chunks.append(truncate(post.title, limit))

        first_id: Optional[str] = None
        previous_id: Optional[str] = None
        published: List[str] = []
        video_id = ""
        card_index = 1 if video_first else 0
        for index, chunk in enumerate(chunks[:chain_parts]):
            payload: Dict[str, Any] = {
                "media_type": "TEXT",
                "text": chunk,
                "access_token": self.token,
            }
            if video_first and index == 0:
                payload["media_type"] = "VIDEO"
                payload["video_url"] = context.video_url
            elif index == card_index and context.public_card_url:
                payload["media_type"] = "IMAGE"
                payload["image_url"] = context.public_card_url
            if previous_id:
                payload["reply_to_id"] = previous_id

            creation = self._create_container(payload)
            if not creation.get("id") and video_first and index == 0:
                # Видео не принято — деградируем к прежнему IMAGE/TEXT.
                video_first = False
                card_index = 0
                payload = {"media_type": "TEXT", "text": chunk, "access_token": self.token}
                if context.public_card_url:
                    payload["media_type"] = "IMAGE"
                    payload["image_url"] = context.public_card_url
                creation = self._create_container(payload)
            if not creation.get("id") and index == card_index and context.public_card_url:
                # Картинка не принята — повторяем как текст.
                payload["media_type"] = "TEXT"
                payload.pop("image_url", None)
                creation = self._create_container(payload)
            if not creation.get("id"):
                error = str(creation.get("error") or creation)
                if "expired" in error.lower() or "session has expired" in error.lower():
                    return PublishResult(
                        platform=self.name, ok=False, skipped=True,
                        error="Threads token expired",
                    )
                return PublishResult(
                    platform=self.name,
                    ok=False,
                    error=error[:200],
                )

            is_video = payload.get("media_type") == "VIDEO"
            ready, wait_error = self._wait_container(
                creation["id"],
                attempts=60 if is_video else 15,
                pause=3.0 if is_video else 2.0,
                strict=is_video,
            )
            if not ready and video_first and index == 0:
                video_first = False
                card_index = 0
                payload = {"media_type": "TEXT", "text": chunk, "access_token": self.token}
                if context.public_card_url:
                    payload["media_type"] = "IMAGE"
                    payload["image_url"] = context.public_card_url
                creation = self._create_container(payload)
                if creation.get("id"):
                    ready, wait_error = self._wait_container(creation["id"])
            if not ready and index == card_index and context.public_card_url:
                payload["media_type"] = "TEXT"
                payload.pop("image_url", None)
                creation = self._create_container(payload)
                if creation.get("id"):
                    ready, wait_error = self._wait_container(creation["id"])
            if not ready:
                return PublishResult(
                    platform=self.name, ok=False,
                    error=f"контейнер не готов: {wait_error}"[:200],
                )

            published_id = self._publish_container(creation["id"])
            if not published_id:
                return PublishResult(platform=self.name, ok=False, error="threads_publish не вернул id")
            if payload.get("media_type") == "VIDEO" and not video_id:
                video_id = published_id
            published.append(published_id)
            first_id = first_id or published_id
            previous_id = published_id

        return PublishResult(
            platform=self.name,
            ok=True,
            external_id=first_id,
            url=f"https://www.threads.net/t/{first_id}" if first_id else None,
            meta={
                "published_ids": published,
                "chunks": len(published),
                "video_first": bool(video_id),
                "video_id": video_id,
                "video_url": context.video_url if video_id else "",
            },
        )

    def publish_video_reply(
        self,
        parent_id: str,
        video_url: str,
        text: str = "",
        wait_attempts: int = 60,
    ) -> PublishResult:
        """Публикует VIDEO-ответ в тред: карточка + голос + звуковая волна.

        Threads не принимает «голый» MP3/OGG, поэтому звук доставляется
        видео-аудиограммой. Контейнер видео обрабатывается дольше картинки —
        ждём до ~3 минут, затем публикуем.
        """
        if not self.available():
            return result_skipped(self.name, "TH_USER_ID/TH_ACCESS_TOKEN не заданы")
        if not parent_id:
            return PublishResult(platform=self.name, ok=False, error="нет parent_id для видео-ответа")
        if not video_url:
            return PublishResult(platform=self.name, ok=False, error="нет публичного URL аудиограммы")

        payload: Dict[str, Any] = {
            "media_type": "VIDEO",
            "video_url": video_url,
            "text": truncate(text or "", 500),
            "reply_to_id": str(parent_id),
            "access_token": self.token,
        }
        creation = self._create_container(payload)
        if not creation.get("id"):
            error = str(creation.get("error") or creation)
            if "expired" in error.lower() or "session has expired" in error.lower():
                return PublishResult(
                    platform=self.name, ok=False, skipped=True,
                    error="Threads token expired",
                )
            return PublishResult(platform=self.name, ok=False, error=error[:200])

        ready, wait_error = self._wait_container(
            creation["id"], attempts=max(15, int(wait_attempts)), pause=3.0, strict=True
        )
        if not ready:
            return PublishResult(
                platform=self.name, ok=False,
                error=f"видео-контейнер не готов: {wait_error}"[:200],
            )
        published_id = self._publish_container(creation["id"])
        if not published_id:
            return PublishResult(platform=self.name, ok=False, error="threads_publish не вернул id видео")
        return PublishResult(
            platform=self.name,
            ok=True,
            external_id=published_id,
            url=f"https://www.threads.net/t/{published_id}",
            meta={"reply_to_id": str(parent_id), "video_url": video_url},
        )

    def _wait_container(
        self,
        creation_id: str,
        attempts: int = 15,
        pause: float = 2.0,
        strict: bool = False,
    ) -> tuple[bool, str]:
        """Ждёт обработки контейнера: FINISHED/PUBLISHED, ERROR/EXPIRED.

        Для VIDEO Meta может транскодировать 25–55 секунд, поэтому strict=True
        не публикует контейнер по таймауту, а честно возвращает ошибку.
        """
        last = ""
        for attempt in range(max(1, attempts)):
            try:
                response = requests.get(
                    f"{self.api}/{creation_id}",
                    params={
                        "fields": "status,error_message",
                        "access_token": self.token,
                    },
                    timeout=25,
                )
                payload = response.json()
                status = str(payload.get("status") or "").upper()
                last = status or last
                if status in ("FINISHED", "PUBLISHED"):
                    return True, ""
                if status in ("ERROR", "EXPIRED"):
                    return False, str(payload.get("error_message") or status)
            except Exception as exc:
                last = str(exc)[:120]
            if attempt < attempts - 1:
                time.sleep(pause)
        return (False, last) if strict else (True, last)

    def _create_container(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            response = requests.post(f"{self.base}/threads", data=payload, timeout=25)
            return response.json()
        except Exception as exc:
            LOGGER.warning("Threads create container: %s", exc)
            return {"error": str(exc)}

    def _publish_container(self, creation_id: str) -> Optional[str]:
        for attempt in range(2):
            try:
                response = requests.post(
                    f"{self.base}/threads_publish",
                    data={"creation_id": creation_id, "access_token": self.token},
                    timeout=25,
                )
                payload = response.json()
                if payload.get("id"):
                    return str(payload["id"])
                LOGGER.warning("Threads publish attempt %s: %s", attempt + 1, payload)
            except Exception as exc:
                LOGGER.warning("Threads publish attempt %s: %s", attempt + 1, exc)
            time.sleep(2.0)
        return None

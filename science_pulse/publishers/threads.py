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
            if mode == "mp4":
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

        first_id: Optional[str] = None
        previous_id: Optional[str] = None
        published: List[str] = []
        for index, chunk in enumerate(chunks[:chain_parts]):
            payload: Dict[str, Any] = {
                "media_type": "TEXT",
                "text": chunk,
                "access_token": self.token,
            }
            if index == 0 and context.public_card_url:
                payload["media_type"] = "IMAGE"
                payload["image_url"] = context.public_card_url
            if previous_id:
                payload["reply_to_id"] = previous_id

            creation = self._create_container(payload)
            if not creation.get("id"):
                if index == 0 and context.public_card_url:
                    # Картинка не принята — повторяем первый пост как текст.
                    payload["media_type"] = "TEXT"
                    payload.pop("image_url", None)
                    creation = self._create_container(payload)
                if not creation.get("id"):
                    return PublishResult(
                        platform=self.name,
                        ok=False,
                        error=str(creation.get("error") or creation)[:200],
                    )

            ready, wait_error = self._wait_container(creation["id"])
            if not ready:
                if index == 0 and context.public_card_url:
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
            published.append(published_id)
            first_id = first_id or published_id
            previous_id = published_id

        return PublishResult(
            platform=self.name,
            ok=True,
            external_id=first_id,
            url=f"https://www.threads.net/t/{first_id}" if first_id else None,
            meta={"published_ids": published, "chunks": len(published)},
        )

    def _wait_container(self, creation_id: str, attempts: int = 15, pause: float = 2.0) -> tuple[bool, str]:
        """Ждёт обработки контейнера: FINISHED/PUBLISHED, ERROR/EXPIRED.

        Документация Threads рекомендует подождать ~30 секунд перед
        threads_publish. Если статус не удаётся получить, пробуем публиковать.
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
        return True, last

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

from __future__ import annotations

import io
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

import requests

from ..config import Config
from ..models import CardArtifact, Post, PublishResult
from ..text import truncate
from .base import Publisher, PublishContext, build_caption, build_telegram_text, context_rules, result_skipped

LOGGER = logging.getLogger(__name__)


class TelegramPublisher(Publisher):
    name = "telegram"

    def __init__(self, config: Config):
        self.config = config
        self.token = config.telegram_token
        self.channel = config.telegram_channel
        self.thread_id = config.telegram_thread_id

    def available(self) -> bool:
        return bool(self.token and self.channel)

    def _api(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self.token}/{method}"

    def publish(self, post: Post, card: CardArtifact, context: PublishContext) -> PublishResult:
        if not self.available():
            return result_skipped(self.name, "TG_BOT_TOKEN/TG_CHANNEL_ID не заданы")

        rules = context_rules(context, self.config)
        caption_limit = rules.limit(self.name, "max_caption_chars", 1024)
        message_limit = rules.limit(self.name, "max_message_chars", 4096)
        caption = build_caption(post, limit=max(200, caption_limit - 4), html=True, site_url=context.site_url)
        # Видео-режим: оживлённый чертёж со звуком вместо статичной карточки.
        if context.video:
            video_result = self._publish_video(post, card, context, caption)
            if video_result is not None:
                return video_result

        data: Dict[str, Any] = {
            "chat_id": self.channel,
            "caption": caption,
            "parse_mode": "HTML",
        }
        if self.thread_id:
            data["message_thread_id"] = self.thread_id

        try:
            response = requests.post(
                self._api("sendPhoto"),
                data=data,
                files={"photo": ("card.png", io.BytesIO(card.data), "image/png")},
                timeout=25,
            )
            payload = response.json()
        except Exception as exc:
            return PublishResult(platform=self.name, ok=False, error=str(exc)[:200])

        if not payload.get("ok"):
            error = str(payload.get("description") or payload)[:200]
            LOGGER.warning("Telegram sendPhoto не сработал: %s", error)
            return self._publish_text_fallback(post, context, error)

        result = payload.get("result") or {}
        photos = result.get("photo") or []
        file_id = photos[-1].get("file_id") if photos else None
        message_id = result.get("message_id")

        full_text = build_telegram_text(post, limit=message_limit, site_url=context.site_url)
        if len(full_text) > len(caption) + 80:
            self.send_message(full_text, reply_to=message_id)

        voice_meta = self._maybe_send_voice(post, message_id, rules=rules)

        return PublishResult(
            platform=self.name,
            ok=True,
            external_id=str(message_id) if message_id is not None else None,
            url=f"https://t.me/{str(self.channel).lstrip('@')}" if self.channel else None,
            meta={"message_id": message_id, "file_id": file_id, **voice_meta},
        )

    def _publish_video(self, post: Post, card: CardArtifact, context: PublishContext, caption: str) -> Optional[PublishResult]:
        """Публикует видео выпуска; карточка остаётся для сайта и книги.

        Для дизайна `moku3d` приоритет у 5-актового фильма (`moku_film.py`),
        иначе — у озвученного микро-видео (`video.py`).
        """
        path = None
        design = (getattr(post, "meta", {}) or {}).get("design_variant") or {}
        if isinstance(design, dict) and design.get("theme") == "moku3d":
            try:
                from ..moku_film import film_for_post

                path = film_for_post(post, self.config)
            except Exception as exc:
                LOGGER.warning("Moku3D недоступен: %s", exc)
                path = None
        if not path:
            from ..video import video_for_post

            path = video_for_post(post, self.config)
        if path is None:
            return None  # мягкий fallback на статичную карточку
        if not self.send_video(path, caption):
            return None
        full_text = build_telegram_text(post, limit=3900, site_url=context.site_url)
        if len(full_text) > len(caption) + 80:
            self.send_message(full_text)
        return PublishResult(
            platform=self.name, ok=True, url=f"https://t.me/{str(self.channel).lstrip('@')}",
            meta={"video": str(path), "card_file_id": card and None},
        )

    def send_video(self, path: str | Path, caption: str = "") -> bool:
        """Отправляет микро-видео (MP4/GIF) со звуком в канал."""
        if not self.available():
            return False
        path = Path(path)
        data: Dict[str, Any] = {
            "chat_id": self.channel,
            "caption": caption[:1020],
            "parse_mode": "HTML",
            "supports_streaming": "true",
        }
        if self.thread_id:
            data["message_thread_id"] = self.thread_id
        try:
            with open(path, "rb") as handle:
                response = requests.post(
                    self._api("sendVideo"), data=data,
                    files={"video": (path.name, handle, "video/mp4")}, timeout=120,
                )
            payload = response.json()
            if not payload.get("ok"):
                LOGGER.warning("Telegram sendVideo: %s", str(payload)[:200])
            return bool(payload.get("ok"))
        except Exception as exc:
            LOGGER.warning("Telegram sendVideo: %s", exc)
            return False

    def _maybe_send_voice(self, post: Post, reply_to: Optional[int], rules: Any = None) -> Dict[str, Any]:
        """Звук по режиму площадки: auto | voice | audio | mp4 | link | off."""
        from ..platforms_info import PlatformRules
        from ..voice import audiogram_for_post, voice_for_post, voice_settings

        settings = voice_settings(self.config)
        if not settings["enabled"]:  # глобальный выключатель озвучки
            return {}
        rules = rules or PlatformRules.load(None, self.config)
        mode = rules.audio_mode(self.name)
        if mode == "off":
            return {}
        if mode == "link":
            link = f"{self.config.site_base_url}/post/{post.id}.html" if self.config.site_base_url else ""
            if link and self.send_message(f"<a href=\"{link}\">Аудиоразбор на сайте</a>", reply_to=reply_to):
                return {"voice": "link"}
            return {"voice": "skipped"}
        if mode == "mp4":
            audiogram = audiogram_for_post(post, self.config)
            if audiogram and self.send_video(audiogram, post.title[:60]):
                return {"voice": "mp4"}
            return {"voice": "failed"}

        artifact = voice_for_post(post, self.config)
        if artifact is None:
            return {"voice": "failed"}
        if mode == "audio":
            sent = self.send_audio(artifact.mp3_path, title=post.title, reply_to=reply_to)
        elif mode == "voice":
            sent = bool(artifact.ogg_path) and self.send_voice(artifact.ogg_path, reply_to=reply_to)
        else:  # auto: голосовое до 60 с, длинное — подкастом
            if artifact.ogg_path and (not artifact.duration_s or artifact.duration_s <= 60.0):
                sent = self.send_voice(artifact.ogg_path, reply_to=reply_to)
            else:
                sent = self.send_audio(artifact.mp3_path, title=post.title, reply_to=reply_to)
        return {
            "voice": "sent" if sent else "failed",
            "voice_engine": artifact.engine,
            "voice_duration": round(artifact.duration_s, 1),
            "voice_mode": mode,
        }

    def send_voice(self, path: str | Path, reply_to: Optional[int] = None) -> bool:
        """Голосовое сообщение (OGG/OPUS) ответом на карточку."""
        if not self.available():
            return False
        data: Dict[str, Any] = {"chat_id": self.channel}
        if self.thread_id:
            data["message_thread_id"] = self.thread_id
        if reply_to is not None:
            data["reply_to_message_id"] = reply_to
        try:
            with open(path, "rb") as handle:
                response = requests.post(
                    self._api("sendVoice"), data=data,
                    files={"voice": ("voice.ogg", handle, "audio/ogg")}, timeout=60,
                )
            payload = response.json()
            if not payload.get("ok"):
                LOGGER.warning("Telegram sendVoice: %s", str(payload)[:200])
            return bool(payload.get("ok"))
        except Exception as exc:
            LOGGER.warning("Telegram sendVoice: %s", exc)
            return False

    def send_audio(self, path: str | Path, title: str = "", reply_to: Optional[int] = None) -> bool:
        """Аудио-подкаст (MP3) с обложкой-карточкой в метаданных."""
        if not self.available():
            return False
        data: Dict[str, Any] = {
            "chat_id": self.channel,
            "title": (title or "Science Pulse")[:64],
            "performer": "Science Pulse",
        }
        if self.thread_id:
            data["message_thread_id"] = self.thread_id
        if reply_to is not None:
            data["reply_to_message_id"] = reply_to
        try:
            with open(path, "rb") as handle:
                response = requests.post(
                    self._api("sendAudio"), data=data,
                    files={"audio": ("podcast.mp3", handle, "audio/mpeg")}, timeout=120,
                )
            payload = response.json()
            if not payload.get("ok"):
                LOGGER.warning("Telegram sendAudio: %s", str(payload)[:200])
            return bool(payload.get("ok"))
        except Exception as exc:
            LOGGER.warning("Telegram sendAudio: %s", exc)
            return False

    def _publish_text_fallback(self, post: Post, context: PublishContext, error: str) -> PublishResult:
        text = build_telegram_text(post, limit=3900, site_url=context.site_url)
        response = self.send_message(text)
        if response:
            return PublishResult(
                platform=self.name,
                ok=True,
                external_id=str((response.get("result") or {}).get("message_id")),
                url=f"https://t.me/{str(self.channel).lstrip('@')}",
                meta={"fallback": "text", "photo_error": error},
            )
        return PublishResult(platform=self.name, ok=False, error=error)

    def send_poll(
        self,
        post: Post,
        challenge: Optional[Dict[str, Any]] = None,
        reply_to: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """Нативная викторина канала (`sendPoll`) по просветительской задаче.

        Вопрос — задача выпуска, варианты — правильный ответ и три числовых
        дистрактора (см. `challenge.quiz_options`). Если в ответе нет числа
        (качественная задача), викторина не отправляется: выдумывать варианты
        мы не будем.
        """
        if not self.available():
            return None
        from ..challenge import build_challenge, quiz_options

        quiz = quiz_options(challenge or build_challenge(post))
        if not quiz:
            return None
        data: Dict[str, Any] = {
            "chat_id": self.channel,
            "question": truncate(str(quiz["question"]), 290),
            "options": json.dumps(quiz["options"], ensure_ascii=False),
            "type": "quiz",
            "correct_option_id": str(quiz["correct_index"]),
            "is_anonymous": "true",
            "explanation": truncate(str(quiz.get("explanation") or ""), 190),
        }
        if reply_to:
            data["reply_to_message_id"] = str(reply_to)
        if self.thread_id:
            data["message_thread_id"] = str(self.thread_id)
        try:
            response = requests.post(self._api("sendPoll"), data=data, timeout=20)
            payload = response.json()
        except Exception as exc:  # pragma: no cover - сеть
            LOGGER.warning("Telegram sendPoll: %s", exc)
            return None
        if not payload.get("ok"):
            LOGGER.warning("Telegram sendPoll: %s", str(payload)[:200])
            return None
        return payload.get("result") or {}

    def send_message(self, text: str, reply_to: Optional[int] = None) -> Optional[Dict[str, Any]]:
        if not self.available():
            return None
        data: Dict[str, Any] = {
            "chat_id": self.channel,
            "text": truncate(text, 4000),
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        }
        if self.thread_id:
            data["message_thread_id"] = self.thread_id
        if reply_to is not None:
            data["reply_to_message_id"] = reply_to
        try:
            response = requests.post(self._api("sendMessage"), data=data, timeout=20)
            payload = response.json()
            return payload if payload.get("ok") else None
        except Exception as exc:
            LOGGER.warning("Telegram sendMessage: %s", exc)
            return None

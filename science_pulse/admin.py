from __future__ import annotations

import html
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from .config import Config
from .pipeline import Pipeline
from .storage import Storage
from .text import truncate
LOGGER = logging.getLogger(__name__)

HELP = """🎛 <b>Science Pulse — пульт</b>

/status — состояние очереди и площадок
/queue [math|physics|cs] — очередь
/next — какой пост выйдет следующим
/force [math|physics|cs] — опубликовать сейчас
/harvest [N] — добрать материалы (N на источник)
/add math | Заголовок | Текст | формула — добавить свой пост
/render ID — перерисовать карточку
/sources — здоровье источников
/pause — пауза автопостинга
/resume — снять паузу
/stats — статистика
/metrics — метрики площадок
/invariants — инварианты состояния
/doctor — 🚦 светофор автономности (готовность к автопилоту)
/preview — прислать карточку следующего поста в личку (без публикации)
/skip — отложить следующий пост в конец очереди
/trending [math|physics|cs] — 🔥 радар мировых новостей (лайки/комментарии)
/pick N [now] — взять хит №N в очередь или опубликовать сейчас
/platforms [ru|en] — площадки: возможности и лимиты
/platform имя [ru|en] — детали площадки (telegram, threads, bluesky, discord, mastodon, vk)
/lang ru|en — язык описаний площадок
/about — как работает пульт, где Mini App и где хранится состояние
/app — ссылка и кнопка Mini App «Пульт»
/menu — добавить кнопку «Пульт» в меню чата (нужен HTTPS-адрес сайта)
/book — 📕 собрать PDF-книгу проекта и прислать файл
/voice — 🔊 озвучить следующий пост и прислать голосовое (edge-tts)
/standards — 📏 пороги качества (и /standards set KEY VALUE)
/quarantine — 🚫 посты в карантине (rejected)
/reject ID — отправить пост в карантин вручную
/preflight — 🛫 предполётная проверка следующего поста
/verify — 🧪 инварианты + Lean + фаззинг
/quiz [math|physics|cs] — 🧠 викторина из постов (нативный опрос Telegram)
/foundation — 🏛 ступени фундамента: с каких постов начинаем
/limits — 📐 правила площадок (и /limits set площадка параметр значение)
/site — адрес сайта
/help — эта справка

Кнопки не используются специально: команды живут в getUpdates
и не протухают через 10 секунд, как callback_query."""


class TelegramAdmin:
    def __init__(self, config: Config, pipeline: Pipeline, token: str | None = None, chat_id: str | None = None):
        self.config = config
        self.pipeline = pipeline
        self.storage: Storage = pipeline.storage
        self.token = token if token is not None else config.telegram_token
        self.chat_id = str(chat_id if chat_id is not None else config.telegram_admin_chat)
        self.offset = self.storage.kv_int("tg_offset", 0)
        self.running = False
        from .trending import TrendingRadar

        self.radar_factory = TrendingRadar

    def available(self) -> bool:
        return bool(self.token and self.chat_id)

    def _api(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self.token}/{method}"

    def api_call(self, method: str, data: Optional[Dict[str, Any]] = None, timeout: int = 35) -> Dict[str, Any]:
        try:
            response = requests.post(self._api(method), data=data or {}, timeout=timeout)
            payload = response.json()
            if not payload.get("ok"):
                LOGGER.warning("Telegram admin API %s: %s", method, payload)
            return payload
        except Exception as exc:
            LOGGER.warning("Telegram admin API %s: %s", method, exc)
            return {"ok": False, "error": str(exc)}

    def send(self, text: str) -> None:
        if not self.available():
            return
        chunks = [text[index : index + 3900] for index in range(0, len(text), 3900)] or [""]
        for chunk in chunks:
            payload = self.api_call(
                "sendMessage",
                {
                    "chat_id": self.chat_id,
                    "text": chunk,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": "true",
                },
            )
            # Страховка: если разметка «поехала» (например, сообщение разрезано на
            # границе тега), повторяем тот же текст без parse_mode — смысл важнее вида.
            description = str((payload or {}).get("description") or "")
            if not (payload or {}).get("ok") and ("parse entities" in description or "Unclosed" in description):
                self.api_call(
                    "sendMessage",
                    {"chat_id": self.chat_id, "text": chunk, "disable_web_page_preview": "true"},
                )

    def poll_once(self, timeout: int = 25) -> int:
        if not self.available():
            return 0
        payload = self.api_call(
            "getUpdates",
            {
                "offset": self.offset,
                "timeout": timeout,
                "allowed_updates": '["message","edited_message","callback_query"]',
            },
            timeout=timeout + 10,
        )
        if not payload.get("ok"):
            return 0
        updates = payload.get("result") or []
        for update in updates:
            update_id = int(update.get("update_id", 0))
            if update_id >= self.offset:
                self.offset = update_id + 1
            self.handle_update(update)
        if updates:
            self.storage.kv_set("tg_offset", self.offset)
        return len(updates)

    def handle_update(self, update: Dict[str, Any]) -> Optional[str]:
        if "callback_query" in update:
            callback = update["callback_query"]
            self.api_call(
                "answerCallbackQuery",
                {"callback_query_id": callback.get("id"), "text": "Команда принята"},
                timeout=10,
            )
            return None

        message = update.get("message") or update.get("edited_message")
        if not message:
            return None
        chat_id = str((message.get("chat") or {}).get("id", ""))
        if self.chat_id and chat_id != self.chat_id:
            LOGGER.warning("Пульт: чужой chat_id %s", chat_id)
            return None
        text = (message.get("text") or "").strip()
        if not text.startswith("/"):
            return None

        parts = text.split()
        command = parts[0].split("@", 1)[0].lower()
        args = parts[1:]
        response = self.handle_command(command, args)
        if response:
            self.send(response)
        return response

    def handle_command(self, command: str, args: List[str]) -> str:
        try:
            if command in ("/start", "/help"):
                return HELP
            if command == "/status":
                return self._status_text()
            if command == "/queue":
                domain = args[0] if args else None
                return self._queue_text(domain)
            if command == "/next":
                post = self.pipeline.choose_next(args[0] if args else None)
                if not post:
                    return "Очередь пуста. Запустите /harvest."
                return (
                    f"Следующий: <b>{html.escape(post.title)}</b>\n"
                    f"{post.emoji} {post.label} · {post.source_name}\n"
                    f"id: <code>{post.id}</code>"
                )
            if command == "/force":
                domain, video = self._media_args(args)
                result = self.pipeline.publish_next(domain=domain, force=True, video=video)
                if result.get("ok"):
                    post = result["post"]
                    lines = [f"🚀 Опубликовано: <b>{html.escape(post.title)}</b>"]
                    for item in result.get("results", []):
                        if item.get("skipped"):
                            lines.append(f"• {item['platform']}: пропущено ({html.escape(str(item.get('error') or ''))})")
                        else:
                            lines.append(f"• {item['platform']}: {'ok' if item.get('ok') else 'ошибка'}")
                    return "\n".join(lines)
                return f"Не удалось: {html.escape(str(result.get('error')))}"
            if command == "/add":
                raw = " ".join(args)
                chunks = [chunk.strip() for chunk in raw.split("|")]
                if len(chunks) < 3 or chunks[0] not in ("math", "physics", "cs"):
                    return "Формат: /add math | Заголовок | Текст | формула | код"
                domain, title = chunks[0], chunks[1]
                body = chunks[2]
                formula = chunks[3] if len(chunks) > 3 else ""
                code = chunks[4] if len(chunks) > 4 else ""
                post, errors = self.pipeline.add_manual_post(domain, title, body, formula=formula, code=code)
                if errors:
                    return "Не добавлено: " + html.escape("; ".join(errors))
                return f"Добавлено в очередь: <b>{html.escape(post.title)}</b> <code>{post.id}</code>"
            if command == "/render":
                if not args:
                    return "Формат: /render ID"
                post = self.storage.get_post(args[0])
                if not post:
                    return "Пост не найден."
                from .cards import render_card

                card = render_card(post, out_path=self.config.cards_dir / f"{post.id}.png")
                return f"Карточка: <code>{html.escape(card.path)}</code>"
            if command == "/harvest":
                count = 2
                if args:
                    try:
                        count = max(1, min(10, int(args[0])))
                    except ValueError:
                        pass
                added = self.pipeline.harvest(limit_per_source=count)
                return f"📥 Добавлено постов: {added}. Очередь: {self.storage.count('ready')}"
            if command == "/sources":
                return self._sources_text()
            if command == "/pause":
                self.storage.kv_set("paused", "1")
                return "⏸ Автопостинг на паузе. /resume — продолжить."
            if command == "/resume":
                self.storage.kv_set("paused", "0")
                return "▶️ Автопостинг возобновлён."
            if command == "/stats":
                return self._stats_text()
            if command == "/metrics":
                return self._metrics_text()
            if command == "/invariants":
                return self._invariants_text()
            if command == "/doctor":
                return self._doctor_text()
            if command == "/preview":
                domain, video = self._media_args(args)
                return self._preview_next(domain, video)
            if command == "/skip":
                return self._skip_next()
            if command == "/trending":
                return self._trending_text(args[0] if args else None)
            if command == "/pick":
                return self._pick_trend(args)
            if command == "/about":
                return self._about_text()
            if command == "/platforms":
                return self._platforms_text(args[0] if args else None)
            if command == "/platform":
                if not args:
                    return "Формат: /platform telegram|threads|bluesky|discord|mastodon|vk [ru|en]"
                return self._platform_text(args[0], args[1] if len(args) > 1 else None)
            if command == "/lang":
                return self._lang_text(args[0] if args else None)
            if command in ("/app", "/miniapp"):
                return self._send_app()
            if command == "/menu":
                return self._menu_text()
            if command == "/site":
                return self.config.site_base_url or "SP_SITE_BASE_URL не задан."
            if command in ("/book", "/pdf"):
                return self._book_text()
            if command in ("/voice", "/audio"):
                return self._voice_next()
            if command == "/standards":
                return self._standards_text(args)
            if command == "/quarantine":
                return self._quarantine_text()
            if command == "/reject":
                return self._reject_post(args)
            if command == "/preflight":
                from .preflight import format_preflight, preflight

                return format_preflight(preflight(self.pipeline, with_media=False))
            if command == "/verify":
                from .verify import format_verify, run_verify

                return format_verify(run_verify(self.pipeline, include_media=False))
            if command == "/limits":
                return self._limits_text(args)
            if command == "/foundation":
                return self._foundation_text(args)
            if command == "/quiz":
                return self._quiz_next(args)
            return HELP
        except Exception as exc:
            LOGGER.exception("Ошибка команды %s", command)
            return f"Ошибка: {html.escape(str(exc))}"

    def _quiz_next(self, args: Optional[List[str]] = None) -> str:
        """/quiz — викторина из постов: вопрос + варианты (нативный опрос Telegram).

        Правильный ответ — заголовок поста; дистракторы — заголовки других
        постов той же дисциплины (если их мало — из остальных).
        """
        domain = args[0] if args and args[0] in ("math", "physics", "cs") else None
        post = self.pipeline.choose_next(domain=domain)
        if post is None:
            return "🧠 Нет постов для викторины — сначала /harvest."
        question = post.hook or f"Что описывает формула {post.formula_plain}?"
        correct = post.title
        pool = [
            item.title
            for item in self.pipeline.storage.list_posts(domain=post.domain, limit=12)
            if item.id != post.id and item.title and item.title != correct
        ]
        if len(pool) < 3:
            for item in self.pipeline.storage.list_posts(limit=20):
                if item.id != post.id and item.title and item.title != correct and item.title not in pool:
                    pool.append(item.title)
        options = [correct] + pool[:3]
        if len(options) < 2:
            return "🧠 Недостаточно постов для вариантов ответа."
        payload = self.api_call(
            "sendPoll",
            {
                "chat_id": self.chat_id,
                "question": f"🧠 {question}"[:300],
                "options": json.dumps(options, ensure_ascii=False),
                "type": "quiz",
                "correct_option_id": 0,
                "is_anonymous": "true",
                "explanation": f"Правильный ответ: {correct}"[:200],
            },
        )
        if not payload.get("ok"):
            return f"🧠 Не удалось отправить викторину: {payload.get('description') or payload.get('error')}"
        return "🧠 Викторина отправлена в чат."

    def _status_text(self) -> str:
        status = self.pipeline.status()
        last = status.get("last") or {}
        lines = [
            "📊 <b>Статус</b>",
            f"Очередь: {status['ready']} · Опубликовано: {status['published']} · Ошибок: {status['failed']}",
            f"Пауза: {'да' if status['paused'] else 'нет'}",
        ]
        if last:
            lines.append(f"Последний: {html.escape(str(last.get('title')))} ({last.get('domain')})")
        by_domain = status.get("by_domain") or {}
        lines.append("Очередь по дисциплинам: " + ", ".join(f"{k}={v}" for k, v in by_domain.items()))
        platforms = [f"{item['name']}={'✓' if item['available'] else '—'}" for item in status.get("platforms", [])]
        lines.append("Площадки: " + " ".join(platforms))
        return "\n".join(lines)

    def _queue_text(self, domain: str | None = None) -> str:
        posts = self.storage.list_posts(status="ready", domain=domain, limit=8, order="created_at ASC")
        if not posts:
            return "Очередь пуста."
        lines = [f"📦 <b>Очередь{' / ' + domain if domain else ''}</b>"]
        for post in posts:
            lines.append(f"• {post.emoji} {html.escape(truncate(post.title, 90))} <code>{post.id}</code>")
        counts = self.storage.queue_counts()
        lines.append("Всего: " + ", ".join(f"{k}={v}" for k, v in counts.items()))
        return "\n".join(lines)

    def _sources_text(self) -> str:
        lines = ["🛰 <b>Источники</b>"]
        for item in self.pipeline.sources.status():
            state = "OPEN" if item["open"] else "ok"
            lines.append(
                f"• {item['name']}: {state}, ошибок {item['failures']}, tier {item['tier']}"
            )
        return "\n".join(lines)

    def _stats_text(self) -> str:
        status = self.pipeline.status()
        lines = [
            "📈 <b>Статистика</b>",
            f"Готово: {status['ready']}",
            f"Опубликовано: {status['published']}",
            f"Ошибок: {status['failed']}",
        ]
        for domain, count in (status.get("by_domain") or {}).items():
            lines.append(f"• {domain}: {count}")
        return "\n".join(lines)

    def _metrics_text(self) -> str:
        from .metrics import format_metrics_summary

        return format_metrics_summary(self.storage.metrics_summary(), html=True)

    def _lang(self) -> str:
        from .platforms_info import normalize_lang

        return normalize_lang(self.storage.kv_get("admin_lang", "ru"))

    def _miniapp_url(self) -> str:
        base = self.config.site_base_url.rstrip("/")
        return f"{base}/pult.html" if base else ""

    def _availability(self) -> Dict[str, bool]:
        return {item["name"]: bool(item["available"]) for item in self.pipeline.publishers.status()}

    def _about_text(self) -> str:
        from .platforms_info import format_about

        return format_about(self._lang(), self._miniapp_url(), self.config.site_base_url)

    def _platforms_text(self, lang: Optional[str] = None) -> str:
        from .platforms_info import format_platforms

        return format_platforms(lang or self._lang(), self._availability())

    def _platform_text(self, name: str, lang: Optional[str] = None) -> str:
        from .platforms_info import format_platform

        available = self._availability().get(str(name).lower())
        return format_platform(name, lang or self._lang(), available)

    def _lang_text(self, value: Optional[str]) -> str:
        from .platforms_info import LANGUAGES

        if not value:
            return f"Текущий язык описаний: {self._lang()}. Формат: /lang ru|en"
        code = str(value).strip().lower()
        if code not in LANGUAGES:
            return "Формат: /lang ru|en"
        self.storage.kv_set("admin_lang", code)
        return "🇷🇺 Язык описаний площадок: русский." if code == "ru" else "🇬🇧 Platform descriptions language: English."

    def _miniapp_https(self) -> str:
        url = self._miniapp_url()
        return url if url.startswith("https://") else ""

    def _app_text(self) -> str:
        url = self._miniapp_url()
        if not url:
            return (
                "🖥 <b>Mini App не настроен</b>\n"
                "Задайте <code>SP_SITE_BASE_URL</code> (например, "
                "<code>https://&lt;user&gt;.github.io/&lt;repo&gt;</code>), соберите сайт "
                "(<code>cli site</code>) и опубликуйте <code>dist/</code> (GitHub Pages). "
                "После этого <code>/menu</code> включит кнопку «Пульт»."
            )
        if not url.startswith("https://"):
            return (
                f"🖥 Mini App: {html.escape(url)}\n"
                "Telegram принимает <code>web_app</code> только по HTTPS — опубликуйте сайт "
                "(GitHub Pages) и укажите HTTPS-адрес."
            )
        return f"🖥 Mini App: {html.escape(url)}\nОткройте кнопкой ниже или выполните /menu — кнопка появится рядом с полем ввода."

    def _send_app(self) -> str:
        url = self._miniapp_https()
        if not url:
            return self._app_text()
        self.api_call(
            "sendMessage",
            {
                "chat_id": self.chat_id,
                "text": "🖥 Mini App «Пульт»",
                "reply_markup": json.dumps(
                    {"inline_keyboard": [[{"text": "Открыть Пульт", "web_app": {"url": url}}]]}
                ),
            },
        )
        return ""

    def _menu_text(self) -> str:
        url = self._miniapp_https()
        if not url:
            return (
                "Нужен HTTPS-адрес сайта: задайте <code>SP_SITE_BASE_URL</code> "
                "(GitHub Pages) и опубликуйте <code>dist/</code>."
            )
        result = self.api_call(
            "setChatMenuButton",
            {
                "chat_id": self.chat_id,
                "menu_button": json.dumps(
                    {"type": "web_app", "text": "Пульт", "web_app": {"url": url}}
                ),
            },
        )
        if result.get("ok"):
            self.set_my_commands()
            return (
                "✅ Кнопка «Пульт» добавлена в меню чата (слева от поля ввода).\n"
                "Меню команд «/» также обновлено."
            )
        return f"Не удалось: {html.escape(str(result.get('description') or result)[:200])}"

    def _invariants_text(self) -> str:
        from .invariants import InvariantChecker

        report = InvariantChecker(self.storage).check()
        if report.ok:
            return f"✅ <b>Инварианты</b>: OK ({report.checked} проверок)"
        lines = [f"⛔ <b>Инварианты нарушены</b>: {len(report.violations)}"]
        for item in report.violations[:20]:
            lines.append(f"• {item.code}: {html.escape(item.message)} {html.escape(str(item.detail))}")
        return "\n".join(lines)

    _MY_COMMANDS = [
        ("status", "Статус и очередь", "Status & queue"),
        ("doctor", "Светофор автономности", "Autonomy doctor"),
        ("queue", "Очередь постов", "Post queue"),
        ("next", "Следующий пост", "Next post"),
        ("preview", "Предпросмотр карточки", "Card preview"),
        ("skip", "Отложить следующий", "Skip next"),
        ("force", "Опубликовать сейчас", "Publish now"),
        ("harvest", "Собрать свежие посты", "Harvest fresh"),
        ("trending", "Радар мировых новостей", "World trending"),
        ("pick", "Взять хит в очередь", "Pick a trend"),
        ("platforms", "Площадки и ключи", "Platforms & keys"),
        ("lang", "Язык RU/EN", "Language RU/EN"),
        ("menu", "Кнопка «Пульт» в чате", "Pult button in chat"),
    ]

    def send_photo(self, path: str | Path, caption: str = "") -> bool:
        """Отправляет картинку в админ-чат (для /preview и /render)."""
        if not self.available():
            return False
        try:
            with open(path, "rb") as handle:
                response = requests.post(
                    self._api("sendPhoto"),
                    data={"chat_id": self.chat_id, "caption": caption[:1000], "parse_mode": "HTML"},
                    files={"photo": handle},
                    timeout=90,
                )
            payload = response.json()
            if not payload.get("ok"):
                LOGGER.warning("sendPhoto: %s", payload)
            return bool(payload.get("ok"))
        except Exception as exc:
            LOGGER.warning("sendPhoto: %s", exc)
            return False

    def send_voice(self, path: str | Path, caption: str = "") -> bool:
        """Отправляет голосовое сообщение (OGG/OPUS) в админ-чат (для /voice)."""
        if not self.available():
            return False
        try:
            with open(path, "rb") as handle:
                response = requests.post(
                    self._api("sendVoice"),
                    data={"chat_id": self.chat_id, "caption": caption[:1000]},
                    files={"voice": ("voice.ogg", handle, "audio/ogg")},
                    timeout=90,
                )
            payload = response.json()
            if not payload.get("ok"):
                LOGGER.warning("sendVoice: %s", payload)
            return bool(payload.get("ok"))
        except Exception as exc:
            LOGGER.warning("sendVoice: %s", exc)
            return False

    def send_audio(self, path: str | Path, caption: str = "", title: str = "") -> bool:
        """Отправляет аудио-подкаст (MP3) в админ-чат (для /voice)."""
        if not self.available():
            return False
        try:
            with open(path, "rb") as handle:
                response = requests.post(
                    self._api("sendAudio"),
                    data={"chat_id": self.chat_id, "caption": caption[:1000],
                          "title": (title or "Science Pulse")[:64], "performer": "Science Pulse"},
                    files={"audio": ("podcast.mp3", handle, "audio/mpeg")},
                    timeout=120,
                )
            payload = response.json()
            if not payload.get("ok"):
                LOGGER.warning("sendAudio: %s", payload)
            return bool(payload.get("ok"))
        except Exception as exc:
            LOGGER.warning("sendAudio: %s", exc)
            return False

    def send_video(self, path: str | Path, caption: str = "") -> bool:
        """Отправляет микро-видео (MP4/GIF) в админ-чат (для /preview video)."""
        if not self.available():
            return False
        try:
            with open(path, "rb") as handle:
                response = requests.post(
                    self._api("sendVideo"),
                    data={"chat_id": self.chat_id, "caption": caption[:1000], "parse_mode": "HTML",
                          "supports_streaming": "true"},
                    files={"video": (Path(path).name, handle, "video/mp4")},
                    timeout=120,
                )
            payload = response.json()
            if not payload.get("ok"):
                LOGGER.warning("sendVideo: %s", payload)
            return bool(payload.get("ok"))
        except Exception as exc:
            LOGGER.warning("sendVideo: %s", exc)
            return False

    def send_document(self, path: str | Path, caption: str = "") -> bool:
        """Отправляет файл (PDF-книгу) в админ-чат (для /book)."""
        if not self.available():
            return False
        try:
            with open(path, "rb") as handle:
                response = requests.post(
                    self._api("sendDocument"),
                    data={"chat_id": self.chat_id, "caption": caption[: 1000], "parse_mode": "HTML"},
                    files={"document": handle},
                    timeout=120,
                )
            payload = response.json()
            if not payload.get("ok"):
                LOGGER.warning("sendDocument: %s", payload)
            return bool(payload.get("ok"))
        except Exception as exc:
            LOGGER.warning("sendDocument: %s", exc)
            return False

    def set_my_commands(self) -> bool:
        """Ставит нативное меню команд Telegram (кнопка «/») на языке оператора."""
        lang = self.storage.kv_get("admin_lang", "ru")
        index = 1 if lang == "en" else 2
        commands = [{"command": row[0], "description": row[index]} for row in self._MY_COMMANDS]
        payload = self.api_call("setMyCommands", {"commands": json.dumps(commands, ensure_ascii=False)})
        return bool(payload.get("ok"))

    @staticmethod
    def _light(state: str, title: str, detail: str) -> str:
        icon = {"ok": "🟢", "warn": "🟡", "off": "⚪", "bad": "🔴"}.get(state, "⚪")
        return f"{icon} <b>{title}</b>: {detail}"

    def _doctor_text(self) -> str:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from .invariants import InvariantChecker
        from .scheduler import next_run, parse_schedule
        from .text import _looks_russian

        status = self.pipeline.status()
        ready = int(status.get("ready") or 0)
        by_domain = status.get("by_domain") or {}
        cfg = dict(self.config.raw.get("doctor") or {})
        per_day = float(cfg.get("posts_per_day", 3) or 3)
        days = (ready / per_day) if per_day else 0.0

        posts = self.storage.list_posts(status="ready", limit=500)
        english = sum(1 for post in posts if not _looks_russian(post.title or ""))

        lines = ["🚦 <b>Светофор автономности</b>", ""]

        tg_ok = bool(self.config.telegram_token and self.config.telegram_channel)
        lines.append(
            self._light(
                "ok" if tg_ok else "bad",
                "Telegram-канал",
                f"{self.config.telegram_channel or '—'} · токен "
                f"{'задан' if self.config.telegram_token else 'НЕ задан'} · пульт "
                f"{'готов' if self.available() else 'нет chat_id'}",
            )
        )

        if ready >= 6 and not english:
            queue_state = "ok"
        elif ready > 0:
            queue_state = "warn"
        else:
            queue_state = "bad"
        domains = ", ".join(f"{key}={value}" for key, value in by_domain.items()) or "нет"
        lines.append(
            self._light(
                queue_state,
                "Запас очереди",
                f"{ready} готовых ≈ {days:.1f} дн. (при {per_day:g}/сутки) · {domains}",
            )
        )
        if english:
            lines.append(f"🟡 <b>Перевод</b>: непереведённых заголовков: {english} → <code>retranslate</code>")

        lines.append(
            self._light(
                "ok" if self.config.translate else "off",
                "Переводчик (RU)",
                "gtx → MyMemory → deep-translator (формулы сохраняются)"
                if self.config.translate
                else "SP_TRANSLATE выключен",
            )
        )

        from .voice import voice_available, voice_settings

        vsettings = voice_settings(self.config)
        if not vsettings["enabled"]:
            voice_state, voice_detail = "off", "voice.enabled выключен в config.yaml"
        elif voice_available(self.config):
            voice_state = "ok"
            voice_detail = f"{vsettings['engine']} · {vsettings['voice']} · {vsettings['publish']}"
        else:
            voice_state, voice_detail = "warn", "движок не установлен: pip install edge-tts (или piper)"
        lines.append(self._light(voice_state, "Озвучка постов", voice_detail))

        site = self.config.site_base_url or ""
        site_state = "ok" if site.startswith("https://") else ("warn" if site else "off")
        lines.append(
            self._light(
                site_state,
                "Сайт и Mini App",
                site
                if site
                else "SP_SITE_BASE_URL пуст (нужен HTTPS для картинок Threads и Mini App)",
            )
        )

        platforms = status.get("platforms") or []
        ready_names = [item["name"] for item in platforms if item.get("available")]
        missing_names = [item["name"] for item in platforms if not item.get("available")]
        lines.append(
            self._light(
                "ok" if ready_names else "off",
                "Площадки",
                ("активны: " + ", ".join(ready_names) if ready_names else "нет активных")
                + (" · ждут ключей: " + ", ".join(missing_names) if missing_names else ""),
            )
        )

        try:
            timezone = ZoneInfo(self.config.timezone)
            upcoming = next_run(datetime.now(timezone), parse_schedule(self.config.schedule))
            schedule_detail = (
                f"{', '.join(self.config.schedule)} ({self.config.timezone}); "
                f"следующий: {upcoming.strftime('%d.%m %H:%M')}"
            )
        except Exception as exc:  # неверная таймзона не должна ронять отчёт
            schedule_detail = f"{', '.join(self.config.schedule)}; ошибка таймзоны: {exc}"
        paused = self.storage.kv_get("paused", "0") == "1"
        lines.append(self._light("warn" if paused else "ok", "Расписание", schedule_detail))
        if paused:
            lines.append("⏸ Автопостинг на паузе → <code>/resume</code>")

        report = InvariantChecker(self.storage).check()
        lines.append(
            self._light(
                "ok" if report.ok else "bad",
                "Инварианты",
                f"OK ({report.checked} проверок)" if report.ok else f"нарушено {len(report.violations)}",
            )
        )
        return "\n".join(lines)

    @staticmethod
    def _media_args(args: List[str]) -> tuple:
        """Разбирает аргументы вида `<domain>|video`: домен и запрос видео."""
        domain = None
        video = None
        for item in args or []:
            token = str(item).strip().lower()
            if token in ("math", "physics", "cs"):
                domain = token
            elif token in ("video", "mp4"):
                video = True
            elif token in ("photo", "png"):
                video = False
        return domain, video

    def _preview_next(self, domain: str | None = None, video: bool | None = None) -> str:
        post = self.pipeline.choose_next(domain)
        if not post:
            return "Очередь пуста. Запустите /harvest."
        if video:
            from .video import video_for_post

            path = video_for_post(post, self.config)
            if path is None:
                return "🎬 Видео не собралось (проверьте ffmpeg)."
            caption = f"🎬 <b>Видео-превью</b>: {html.escape(post.title)}\n{post.emoji} {post.label} · оживший чертёж + звук формулы"
            if self.send_video(path, caption):
                return f"Видео-превью отправлено: <code>{post.id}</code>"
            return f"Видео готово: <code>{html.escape(str(path))}</code>"
        from .cards import render_card

        card = render_card(post, out_path=self.config.cards_dir / f"{post.id}.png")
        caption = f"👁 <b>Предпросмотр</b>: {html.escape(post.title)}\n{post.emoji} {post.label} · {post.source_name}"
        if self.send_photo(card.path, caption):
            return f"Предпросмотр отправлен в личку: <code>{post.id}</code>"
        return f"Карточка готова: <code>{html.escape(str(card.path))}</code>"

    def _standards_text(self, args: List[str]) -> str:
        """Пороги качества: показать или изменить (`set KEY VALUE`)."""
        from .standards import Standards, StandardsChecker

        checker = StandardsChecker.load(self.storage)
        if args and args[0] == "set":
            if len(args) < 3 or args[1] not in Standards.DEFAULTS:
                return f"Формат: /standards set KEY VALUE. Ключи: {', '.join(Standards.DEFAULTS)}"
            key, value = args[1], args[2]
            try:
                setattr(checker.standards, key, Standards.parse_value(key, value))
            except Exception as exc:
                return f"Ошибка значения: {html.escape(str(exc))}"
            checker.save(self.storage)
            return f"📏 {key} = {getattr(checker.standards, key)}"
        rows = "".join(f"• <code>{key}</code> = {value}\n" for key, value in checker.standards.as_dict().items())
        rejected = self.storage.count("rejected")
        return f"📏 <b>Пороги качества</b>\n{rows}\n🚫 в карантине: {rejected}\nИзменить: <code>/standards set min_letters 240</code>"

    def _quarantine_text(self) -> str:
        """Список постов в карантине."""
        from .standards import StandardsChecker

        posts = StandardsChecker.list_quarantine(self.storage, limit=10)
        if not posts:
            return "🚫 Карантин пуст."
        lines = ["🚫 <b>Карантин (rejected)</b>", ""]
        for post in posts:
            reason = str(post.meta.get("rejected_reason") or "—")[:120]
            lines.append(f"• <b>{html.escape(post.title)}</b> <code>{post.id}</code>\n   {html.escape(reason)}")
        lines.append("")
        lines.append(f"Всего: {self.storage.count('rejected')}")
        return "\n".join(lines)

    def _reject_post(self, args: List[str]) -> str:
        """Отправка поста в карантин вручную."""
        if not args:
            return "Формат: /reject ID"
        post = self.storage.get_post(args[0])
        if not post:
            return "Пост не найден."
        self.storage.update_post_fields(post.id, {"status": "rejected"})
        self.storage.set_post_meta(post.id, "rejected_reason", "вручную оператором из пульта")
        return f"🚫 В карантине: <b>{html.escape(post.title)}</b>"

    def _limits_text(self, args: List[str]) -> str:
        """Правила площадок: показать, изменить (`set`) или сбросить (`reset`)."""
        from .platforms_info import PlatformRules, format_limits

        rules = PlatformRules.load(self.storage, self.config)
        if args and args[0] == "reset":
            rules.reset()
            rules.save(self.storage)
            return "📐 Правила площадок сброшены к значениям по умолчанию."
        if args and args[0] == "set":
            if len(args) < 4:
                return ("Формат: <code>/limits set &lt;площадка&gt; &lt;параметр&gt; &lt;значение&gt;</code>\n"
                        "Например: <code>/limits set threads max_caption_chars 600</code>")
            try:
                value = rules.set(args[1], args[2], args[3])
            except (KeyError, ValueError) as exc:
                return f"Ошибка: {html.escape(str(exc))}"
            rules.save(self.storage)
            return f"📐 {html.escape(args[1])}.{html.escape(args[2])} = <b>{html.escape(str(value))}</b>"
        availability = {item["name"]: bool(item.get("available")) for item in self.pipeline.status().get("platforms", [])}
        return format_limits(rules, availability or None)

    def _foundation_text(self, args: List[str]) -> str:
        """Ступени фундамента: с каких постов начинаем публикацию."""
        from .evolve import EvolutionEngine

        limit = 9
        if args:
            try:
                limit = max(1, min(20, int(args[0])))
            except ValueError:
                pass
        rows = EvolutionEngine(self.pipeline).foundation_status(limit=limit)
        lines = ["🏛 <b>Фундамент: порядок старта</b>", ""]
        current = None
        for row in rows:
            if row["step"] != current:
                current = row["step"]
                lines.append(f"<b>Ступень {row['step']}</b> — {html.escape(row['step_title'])}")
            lines.append(f"  [{row['domain']}] {html.escape(row['title'])} — <i>{row['status']}</i>")
        return "\n".join(lines)

    def _book_text(self) -> str:
        """Собрать PDF-книгу проекта и прислать файл в админ-чат."""
        from .book import BookBuilder

        try:
            path = BookBuilder(self.config, self.storage).build()
        except Exception as exc:
            return f"📕 Книга не собралась: {html.escape(str(exc))}"
        size_kb = path.stat().st_size // 1024
        caption = f"📕 <b>Научная книга Science Pulse</b>\n{size_kb} КБ · собрана из постов канона и очереди."
        if self.send_document(path, caption):
            return f"📕 Книга отправлена: <code>{html.escape(str(path))}</code> ({size_kb} КБ)"
        return f"📕 Книга собрана: <code>{html.escape(str(path))}</code> ({size_kb} КБ)"

    def _voice_next(self, domain: str | None = None) -> str:
        """Озвучить следующий пост и прислать голосовое (или аудио, если длинное)."""
        from .voice import voice_available, voice_for_post, voice_settings

        if not voice_available(self.config):
            return "🔇 Движок озвучки недоступен: <code>pip install edge-tts</code> (или piper + модель)"
        post = self.pipeline.choose_next(domain)
        if not post:
            return "Очередь пуста. Запустите /harvest."
        settings = voice_settings(self.config)
        artifact = voice_for_post(post, self.config)
        if artifact is None:
            return "🔇 Озвучка не удалась (проверьте сеть/движок)."
        caption = f"🔊 <b>{html.escape(post.title)}</b>\n{post.emoji} {post.label} · {artifact.duration_s:.0f} с · {artifact.voice}"
        if settings["publish"] == "voice" and artifact.ogg_path and artifact.duration_s <= 60.0:
            sent = self.send_voice(artifact.ogg_path, caption)
        else:
            sent = self.send_audio(artifact.mp3_path, caption, title=post.title)
        if sent:
            return f"🔊 Голосовое отправлено: <code>{post.id}</code> ({artifact.duration_s:.0f} с)"
        return f"Аудио готово: <code>{html.escape(artifact.mp3_path)}</code>"

    def _skip_next(self, domain: str | None = None) -> str:
        post = self.pipeline.choose_next(domain)
        if not post:
            return "Очередь пуста."
        # 0.01 (а не 0): ноль в БД трактуется как «не задано» и читается как 0.5.
        self.storage.update_post_fields(post.id, {"quality": 0.01})
        return f"⏭ Отложен: <b>{html.escape(post.title)}</b> (уйдёт в конец очереди)"

    def _trending_text(self, domain: str | None = None) -> str:
        from .trending import format_trending

        if domain not in (None, "math", "physics", "cs"):
            return "Формат: /trending [math|physics|cs]"
        radar = self.radar_factory(self.config, self.storage)
        items = radar.scan(domain=domain, top=5)
        lang = self.storage.kv_get("admin_lang", "ru")
        return format_trending(items, lang)

    def _pick_trend(self, args: List[str]) -> str:
        if not args:
            return "Формат: /pick N [now] — N это номер из /trending"
        try:
            index = int(args[0])
        except ValueError:
            return "Формат: /pick N [now]"
        radar = self.radar_factory(self.config, self.storage)
        items = radar.load()
        if not items:
            return "Нет сохранённых хитов. Сначала /trending."
        if not 1 <= index <= len(items):
            return f"Номер вне диапазона 1..{len(items)}"
        item = items[index - 1]
        publish_now = len(args) > 1 and args[1].lower() in ("now", "сейчас")
        post = radar.to_post(item)
        errors = post.validate()
        if errors:
            return "Хит не прошёл quality gate: " + html.escape("; ".join(errors))
        post.quality = 100.0  # максимальный приоритет → выйдет первым
        if not self.storage.add_post(post):
            return "Этот хит уже в очереди."
        if publish_now:
            result = self.pipeline.publish_next(post_id=post.id, force=True)
            if result.get("ok"):
                return f"🚀 Опубликован хит: <b>{html.escape(post.title)}</b>"
            return f"Не удалось опубликовать: {html.escape(str(result.get('error')))}"
        return f"📥 В очередь (приоритет 100): <b>{html.escape(post.title)}</b> <code>{post.id}</code>"

    def run_forever(self) -> None:
        if not self.available():
            raise RuntimeError("Пульт недоступен: нужны TG_BOT_TOKEN и TG_ADMIN_CHAT_ID")
        self.running = True
        LOGGER.info("Пульт запущен, chat_id=%s", self.chat_id)
        if (self.config.raw.get("admin") or {}).get("set_commands", True):
            self.set_my_commands()
        while self.running:
            try:
                self.poll_once(timeout=int((self.config.raw.get("admin") or {}).get("poll_timeout", 25)))
            except KeyboardInterrupt:
                self.running = False
            except Exception:
                LOGGER.exception("Ошибка пульта")
                time.sleep(3)

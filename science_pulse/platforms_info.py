from __future__ import annotations

from typing import Any, Dict, List, Optional

# Языки описаний площадок (выбор в пульте: /lang ru|en).
LANGUAGES = ("ru", "en")
DEFAULT_LANG = "ru"

LABELS: Dict[str, Dict[str, str]] = {
    "ru": {
        "what": "Что умеет",
        "limits": "Лимиты",
        "image": "Картинка",
        "metrics": "Метрики",
        "notes": "Нюансы",
        "env": "Переменные",
        "available": "готов",
        "missing": "нет токенов",
    },
    "en": {
        "what": "Capabilities",
        "limits": "Limits",
        "image": "Image",
        "metrics": "Metrics",
        "notes": "Notes",
        "env": "Environment",
        "available": "ready",
        "missing": "no tokens",
    },
}

# Каталог площадок: описание на русском и английском.
PLATFORMS: Dict[str, Dict[str, Any]] = {
    "telegram": {
        "emoji": "✈️",
        "env": ["TG_BOT_TOKEN", "TG_CHANNEL_ID", "TG_ADMIN_CHAT_ID"],
        "ru": {
            "title": "Telegram",
            "what": "Публикует карточку 1080×1080 с подписью и возвращает file_id для остальных площадок.",
            "limits": "Подпись ≤ 1024, сообщение ≤ 4096; длинный текст уходит вторым сообщением-ответом.",
            "image": "Картинка из RAM (multipart, sendPhoto).",
            "metrics": "Bot API просмотры не отдаёт — метрики недоступны (skipped).",
            "notes": "Бот должен быть администратором канала; топики — через TG_MESSAGE_THREAD_ID.",
        },
        "en": {
            "title": "Telegram",
            "what": "Posts a 1080×1080 card with a caption and returns the file_id used by other platforms.",
            "limits": "Caption ≤ 1024, message ≤ 4096; long text is sent as a second reply message.",
            "image": "Image from RAM (multipart, sendPhoto).",
            "metrics": "Bot API does not expose views — metrics unavailable (skipped).",
            "notes": "The bot must be a channel admin; forum topics via TG_MESSAGE_THREAD_ID.",
        },
    },
    "threads": {
        "emoji": "🧵",
        "env": ["TH_USER_ID", "TH_ACCESS_TOKEN"],
        "ru": {
            "title": "Threads (Meta)",
            "what": "Двухшаговая публикация (контейнер → publish) с цепочкой ответов.",
            "limits": "500 символов; режем 495 и нарезаем по 490, до 3 постов в цепочке.",
            "image": "Только по публичному URL (карточка с сайта или прокси CF Worker по file_id).",
            "metrics": "GET /{id}/insights — views, likes, replies.",
            "notes": "Токен живёт ~60 дней (нужно продление); текст нельзя редактировать — только удалить и опубликовать заново.",
        },
        "en": {
            "title": "Threads (Meta)",
            "what": "Two-step publishing (container → publish) with a reply chain.",
            "limits": "500 characters; we trim to 495 and split at 490, up to 3 posts in a chain.",
            "image": "Public URL only (site card or CF Worker proxy by file_id).",
            "metrics": "GET /{id}/insights — views, likes, replies.",
            "notes": "Token lives ~60 days (needs refresh); published text cannot be edited — delete and repost instead.",
        },
    },
    "bluesky": {
        "emoji": "🦋",
        "env": ["BLUESKY_HANDLE", "BLUESKY_APP_PASSWORD"],
        "ru": {
            "title": "Bluesky",
            "what": "AT Protocol: createSession → uploadBlob → createRecord.",
            "limits": "300 символов (grapheme); режем до 298.",
            "image": "Из RAM через uploadBlob (embed app.bsky.embed.images, alt = заголовок).",
            "metrics": "getPostThread — views, likes, replies (публично, без авторизации).",
            "notes": "Нужен app password (не основной пароль). Лимит считается по grapheme-кластерам.",
        },
        "en": {
            "title": "Bluesky",
            "what": "AT Protocol: createSession → uploadBlob → createRecord.",
            "limits": "300 characters (graphemes); we trim to 298.",
            "image": "From RAM via uploadBlob (app.bsky.embed.images, alt = title).",
            "metrics": "getPostThread — views, likes, replies (public, no auth).",
            "notes": "Use an app password (not the main one). The limit counts grapheme clusters.",
        },
    },
    "discord": {
        "emoji": "🎮",
        "env": ["DISCORD_WEBHOOK_URL"],
        "ru": {
            "title": "Discord",
            "what": "Публикация через webhook в embed-формате с цветом по дисциплине.",
            "limits": "Содержимое ≤ 2000, embed ≤ 4096; описание режем до 3900.",
            "image": "Из RAM файлом card.png (attachment://card.png).",
            "metrics": "Webhook статистику не отдаёт — метрики недоступны (skipped).",
            "notes": "Webhook не возвращает id сообщения; идемпотентность — через таблицу publications.",
        },
        "en": {
            "title": "Discord",
            "what": "Publishing via webhook as an embed, coloured by discipline.",
            "limits": "Content ≤ 2000, embed ≤ 4096; we trim the description to 3900.",
            "image": "From RAM as card.png (attachment://card.png).",
            "metrics": "Webhooks expose no stats — metrics unavailable (skipped).",
            "notes": "The webhook returns no message id; idempotency is kept via the publications table.",
        },
    },
    "mastodon": {
        "emoji": "🐘",
        "env": ["MASTODON_INSTANCE", "MASTODON_ACCESS_TOKEN"],
        "ru": {
            "title": "Mastodon / Mathstodon",
            "what": "Публикация статуса с медиа; формулы рендерятся нативно.",
            "limits": "Типовой лимит инстанса 500; режем до 495.",
            "image": "Из RAM через POST /api/v2/media (описание = заголовок).",
            "metrics": "GET /api/v1/statuses/{id} — избранное и ответы.",
            "notes": "Лимит длины зависит от инстанса; LaTeX оборачивается в \\[ ... \\].",
        },
        "en": {
            "title": "Mastodon / Mathstodon",
            "what": "Posts a status with media; formulas render natively.",
            "limits": "Typical instance limit 500; we trim to 495.",
            "image": "From RAM via POST /api/v2/media (description = title).",
            "metrics": "GET /api/v1/statuses/{id} — favourites and replies.",
            "notes": "The length limit depends on the instance; LaTeX is wrapped in \\[ ... \\].",
        },
    },
    "vk": {
        "emoji": "🅥",
        "env": ["VK_GROUP_ID", "VK_ACCESS_TOKEN"],
        "ru": {
            "title": "ВКонтакте (VK)",
            "what": "Публикация на стене сообщества с фото (wall upload).",
            "limits": "16384 символа; режем до 15000.",
            "image": "Из RAM: getWallUploadServer → загрузка → saveWallPhoto.",
            "metrics": "wall.getById — просмотры, лайки, комментарии.",
            "notes": "Нужен токен с правами wall/photos/groups; публикация от имени сообщества (from_group=1).",
        },
        "en": {
            "title": "VK",
            "what": "Posts to the community wall with a photo (wall upload).",
            "limits": "16384 characters; we trim to 15000.",
            "image": "From RAM: getWallUploadServer → upload → saveWallPhoto.",
            "metrics": "wall.getById — views, likes, comments.",
            "notes": "Token needs wall/photos/groups rights; posts as the community (from_group=1).",
        },
    },
}

# ── Машиночитаемый реестр правил площадок (единый источник лимитов и звука) ──
#
# Лимиты и режим доставки звука НЕ хардкодятся в адаптерах: все публикаторы
# читают их отсюда. Переопределение на лету: config.yaml → `platform_rules:`
# и таблица kv (`platform_rules_override`) через команду `/limits set`.
#
# audio_mode:
#   auto  — telegram: voice (.ogg) до 60 с, иначе audio (.mp3);
#   voice — только голосовое .ogg;  audio — только .mp3;
#   mp4   — авто-склейка карточки и голоса в видеоролик (видео-сети);
#   file  — прикрепить .mp3/.ogg вложением (Discord, Mastodon);
#   link  — ссылка «🎧 Аудио-разбор на сайте» (Threads, Bluesky, VK);
#   off   — звук не отправляется.
DEFAULT_PLATFORM_RULES: Dict[str, Dict[str, Any]] = {
    "telegram": {
        "max_caption_chars": 1024,
        "max_message_chars": 4096,
        "max_chain_parts": 2,
        "audio_mode": "auto",
        "image": "file",
    },
    "threads": {
        "max_caption_chars": 500,
        "max_message_chars": 500,
        "max_chain_parts": 2,
        "audio_mode": "link",
        "image": "url",
    },
    "bluesky": {
        "max_caption_chars": 300,
        "max_message_chars": 300,
        "max_chain_parts": 1,
        "audio_mode": "link",
        "image": "file",
    },
    "discord": {
        "max_caption_chars": 2000,
        "max_message_chars": 2000,
        "max_embed_chars": 4096,
        "max_chain_parts": 1,
        "audio_mode": "file",
        "image": "file",
    },
    "mastodon": {
        "max_caption_chars": 500,
        "max_message_chars": 500,
        "max_chain_parts": 1,
        "audio_mode": "file",
        "image": "file",
    },
    "vk": {
        "max_caption_chars": 16384,
        "max_message_chars": 16384,
        "max_chain_parts": 1,
        "audio_mode": "link",
        "image": "file",
    },
}

AUDIO_MODES = ("auto", "voice", "audio", "mp4", "file", "link", "off")
RULE_KEYS = ("max_caption_chars", "max_message_chars", "max_embed_chars", "max_chain_parts", "audio_mode")


def format_limits(rules: Any, availability: Optional[Dict[str, bool]] = None) -> str:
    """Таблица текущих правил площадок для `/limits`."""
    lines = ["📐 <b>Правила площадок (лимиты и звук)</b>", ""]
    for name, emoji in (("telegram", "✈️"), ("threads", "🧵"), ("bluesky", "🦋"),
                        ("discord", "🎮"), ("mastodon", "🐘"), ("vk", "🅥")):
        data = rules.for_platform(name)
        mark = ""
        if availability is not None:
            mark = " ✓" if availability.get(name) else " —"
        lines.append(
            f"{emoji} <b>{_esc(name)}</b>{mark}: текст ≤ {data['max_caption_chars']}, "
            f"цепочка ≤ {data['max_chain_parts']}, звук: <code>{_esc(str(data['audio_mode']))}</code>"
        )
    lines.append("")
    lines.append("Изменить: <code>/limits set threads max_caption_chars 600</code>")
    lines.append("Звук: <code>/limits set telegram audio_mode audio</code> · сброс: <code>/limits reset</code>")
    return "\n".join(lines)


def normalize_lang(lang: Optional[str] = None) -> str:
    value = str(lang or "").strip().lower()
    return value if value in LANGUAGES else DEFAULT_LANG


def platform_names() -> List[str]:
    return list(PLATFORMS.keys())


def _esc(text: Any) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def format_platform(name: str, lang: str = DEFAULT_LANG, available: Optional[bool] = None) -> str:
    """Карточка одной площадки (HTML) на выбранном языке."""
    key = str(name or "").strip().lower()
    code = normalize_lang(lang)
    if key not in PLATFORMS:
        return f"Площадка не найдена: {_esc(key)}" if code == "ru" else f"Unknown platform: {_esc(key)}"
    data = PLATFORMS[key]
    labels = LABELS[code]
    text = data[code]
    lines = [f"{data['emoji']} <b>{_esc(text['title'])}</b>"]
    if available is not None:
        lines.append(f"<i>{labels['available'] if available else labels['missing']}</i>")
    for field in ("what", "limits", "image", "metrics", "notes"):
        lines.append(f"• <b>{labels[field]}:</b> {_esc(text[field])}")
    lines.append(f"• <b>{labels['env']}:</b> <code>{_esc(', '.join(data['env']))}</code>")
    return "\n".join(lines)


def format_platforms(lang: str = DEFAULT_LANG, availability: Optional[Dict[str, bool]] = None) -> str:
    """Список площадок (HTML) на выбранном языке."""
    code = normalize_lang(lang)
    labels = LABELS[code]
    header = "🌐 <b>Площадки</b>" if code == "ru" else "🌐 <b>Platforms</b>"
    lines = [header]
    for name, data in PLATFORMS.items():
        text = data[code]
        mark = ""
        if availability is not None:
            mark = " ✓" if availability.get(name) else f" — ({labels['missing']})"
        lines.append(f"{data['emoji']} <b>{_esc(text['title'])}</b>{mark} — {_esc(text['what'])}")
    hint = (
        "Подробнее: /platform имя · язык: /lang ru|en"
        if code == "ru"
        else "Details: /platform name · language: /lang ru|en"
    )
    lines.append(hint)
    return "\n".join(lines)


class PlatformRules:
    """Единый реестр правил площадок: лимиты символов, цепочки и режим звука.

    Приоритет значений: kv-переопределение (`platform_rules_override`, команда
    `/limits set`) → `config.yaml` (`platform_rules:`) → `DEFAULT_PLATFORM_RULES`.
    Публикаторы обязаны читать лимиты только отсюда.
    """

    KV_KEY = "platform_rules_override"

    def __init__(self, overrides: Optional[Dict[str, Dict[str, Any]]] = None, config_raw: Optional[Dict[str, Any]] = None):
        self.overrides = {name: dict(values) for name, values in (overrides or {}).items()}
        self.config_raw = dict(config_raw or {})

    @classmethod
    def load(cls, storage: Any = None, config: Any = None) -> "PlatformRules":
        """Собирает правила: config.yaml, затем поверх — kv-переопределения."""
        import json

        overrides: Dict[str, Dict[str, Any]] = {}
        config_raw = dict(getattr(config, "raw", {}) or {}) if config is not None else {}
        for name, values in (config_raw.get("platform_rules") or {}).items():
            if isinstance(values, dict):
                overrides.setdefault(name, {}).update(values)
        if storage is not None and hasattr(storage, "kv_get"):
            raw = storage.kv_get(cls.KV_KEY, "")
            if raw:
                try:
                    for name, values in (json.loads(raw) or {}).items():
                        if isinstance(values, dict):
                            overrides.setdefault(name, {}).update(values)
                except ValueError:
                    pass
        return cls(overrides=overrides, config_raw=config_raw)

    def for_platform(self, name: str) -> Dict[str, Any]:
        """Итоговые правила площадки (дефолт + переопределения)."""
        base = dict(DEFAULT_PLATFORM_RULES.get(name) or DEFAULT_PLATFORM_RULES["telegram"])
        for key, value in (self.overrides.get(name) or {}).items():
            if key in RULE_KEYS or key == "image":
                base[key] = value
        return base

    def limit(self, name: str, key: str = "max_caption_chars", default: int = 1024) -> int:
        """Числовой лимит площадки (безопасно приводится к int)."""
        try:
            return int(self.for_platform(name).get(key, default))
        except (TypeError, ValueError):
            return default

    def audio_mode(self, name: str) -> str:
        """Режим доставки звука: auto | voice | audio | mp4 | file | link | off."""
        mode = str(self.for_platform(name).get("audio_mode", "off")).strip().lower()
        return mode if mode in AUDIO_MODES else "off"

    def set(self, name: str, key: str, value: Any) -> Any:
        """Меняет правило (используется командой `/limits set`)."""
        if name not in DEFAULT_PLATFORM_RULES:
            raise KeyError(f"неизвестная площадка: {name}")
        if key not in RULE_KEYS:
            raise KeyError(f"неизвестный параметр: {key}")
        if key == "audio_mode":
            parsed = str(value).strip().lower()
            if parsed not in AUDIO_MODES:
                raise ValueError(f"режим звука должен быть одним из: {', '.join(AUDIO_MODES)}")
        else:
            parsed = int(value)
            if parsed <= 0:
                raise ValueError("значение должно быть положительным")
        self.overrides.setdefault(name, {})[key] = parsed
        return parsed

    def reset(self) -> None:
        self.overrides = {}

    def as_dict(self) -> Dict[str, Dict[str, Any]]:
        return {name: self.for_platform(name) for name in DEFAULT_PLATFORM_RULES}

    def save(self, storage: Any) -> None:
        import json

        storage.kv_set(self.KV_KEY, json.dumps(self.overrides, ensure_ascii=False))


def format_about(lang: str = DEFAULT_LANG, miniapp_url: str = "", site_url: str = "") -> str:
    """Справка о пульте: как работает, где Mini App, где хранится состояние."""
    code = normalize_lang(lang)
    commands = (
        "/status /queue /next /force /harvest /add /render /sources "
        "/pause /resume /stats /metrics /invariants /platforms /platform /lang /site /about"
    )
    if code == "ru":
        return "\n".join(
            [
                "🎛 <b>Как работает пульт</b>",
                "Пульт читает команды из getUpdates (long polling): кнопки не нужны, команды не протухают.",
                f"Команды: <code>{_esc(commands)}</code>",
                "",
                "🖥 <b>Mini App «Пульт»</b>",
                f"Веб-страница: <code>{_esc(miniapp_url)}</code>"
                if miniapp_url
                else "Задайте SP_SITE_BASE_URL и соберите сайт (<code>cli site</code>) — появится pult.html.",
                "Показывает снимок состояния и кнопки команд (шлют POST на Cloudflare Worker).",
                "",
                "💾 <b>Где хранится</b>",
                "• Состояние: <code>data/science.db</code> (SQLite, WAL) — посты, публикации, метрики, источники.",
                "• Карточки: <code>data/cards/*.png</code>",
                "• Сайт: <code>dist/</code> (pult.html, graph.json, search.json, sitemap.xml)",
                "• Секреты: <code>.env</code> / GitHub Secrets / Cloudflare Secrets (в Git не попадают).",
                "• Edge-реплика (опционально): Cloudflare D1 через <code>cli state --push/--sync</code>.",
            ]
        )
    return "\n".join(
        [
            "🎛 <b>How the pult works</b>",
            "The pult reads commands via getUpdates (long polling): no buttons needed, commands do not expire.",
            f"Commands: <code>{_esc(commands)}</code>",
            "",
            "🖥 <b>Mini App “Pult”</b>",
            f"Web page: <code>{_esc(miniapp_url)}</code>"
            if miniapp_url
            else "Set SP_SITE_BASE_URL and build the site (<code>cli site</code>) — pult.html will appear.",
            "It shows a state snapshot and action buttons (POST to the Cloudflare Worker).",
            "",
            "💾 <b>Where state is stored</b>",
            "• State: <code>data/science.db</code> (SQLite, WAL) — posts, publications, metrics, sources.",
            "• Cards: <code>data/cards/*.png</code>",
            "• Site: <code>dist/</code> (pult.html, graph.json, search.json, sitemap.xml)",
            "• Secrets: <code>.env</code> / GitHub Secrets / Cloudflare Secrets (never committed).",
            "• Edge replica (optional): Cloudflare D1 via <code>cli state --push/--sync</code>.",
        ]
    )


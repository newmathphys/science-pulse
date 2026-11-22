"""Герметичность тестов: секреты из ``.env`` и окружения не протекают внутрь.

Раньше ``load_config()`` подгружал проектный ``.env`` в общий ``os.environ``.
Из-за этого на машине оператора (где ``.env`` заполнен) падали 4 теста:

* ``test_metrics`` — Telegram неожиданно становился «поддерживаемой» площадкой;
* ``test_recovery.test_requires_username`` — у канала появлялся ``@username``.

Здесь отключаем автозагрузку ``.env`` и убираем креды площадок из окружения.
Тесты обязаны опираться только на явно переданные значения.
"""
import os

import science_pulse.config as _config

# 1. Проектный `.env` в тестах не читаем — конфиг берём из аргументов/фикстур.
_config._load_dotenv = lambda path: None  # noqa: E731 - намеренная подмена

# 2. Если shell экспортировал реальные креды — снимаем их на время прогона.
_CREDENTIAL_KEYS = (
    "TG_BOT_TOKEN", "TG_CHANNEL_ID", "TG_ADMIN_CHAT_ID", "TG_MESSAGE_THREAD_ID",
    "TELEGRAM_BOT_TOKEN", "TH_USER_ID", "TH_ACCESS_TOKEN", "THREADS_ACCESS_TOKEN",
    "THREADS_USER_ID", "BLUESKY_HANDLE", "BLUESKY_APP_PASSWORD",
    "DISCORD_WEBHOOK_URL", "MASTODON_INSTANCE", "MASTODON_ACCESS_TOKEN",
    "VK_GROUP_ID", "VK_ACCESS_TOKEN", "CF_WORKER_URL", "INGEST_SECRET", "GH_PAT",
    "SP_SITE_BASE_URL", "SP_DATA_DIR", "SP_DIST_DIR", "SP_SCHEDULE", "SP_TRANSLATE",
)
for _key in _CREDENTIAL_KEYS:
    os.environ.pop(_key, None)

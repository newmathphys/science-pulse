# Площадки: возможности, лимиты и нюансы

Справочник по всем площадкам публикации Science Pulse: что каждая умеет,
какие у неё ограничения, какие есть ловушки и как это отражено в коде.
Секреты и способ их получения — в `docs/TOKENS.md`; здесь — поведение и
нюансы адаптеров.

Главный принцип: **адаптер площадки не генерирует контент.** Он берёт готовый
пост из очереди, режет его под лимиты площадки, прикладывает карточку
(если площадка умеет) и пишет результат в SQLite.

## Матрица возможностей

| Площадка | Текст (лимит → что режем) | Картинка | Метрики | Статус проверки |
|:--|:--|:--|:--|:--|
| **Telegram** | caption 1024 / сообщение 4096 | из RAM (multipart) | ✗ Bot API не отдаёт просмотры | ✅ проверено на живом канале |
| **Threads** | 500 → режем 495, нарезка по 490, ≤3 поста | только по публичному URL | ✓ insights | ⏳ нет токенов |
| **Bluesky** | 300 → режем 298 | из RAM (blob upload) | ✓ getPostThread | ⏳ нет токенов |
| **Discord** | 2000 / embed 4096 → режем 3900 | из RAM (attachment) | ✗ нет API статистики | ⏳ нет токенов |
| **Mastodon** | 500 → режем 495 | из RAM (v2/media) | ✓ statuses | ⏳ нет токенов |
| **VK** | 16384 → режем 15000 | из RAM (wall upload) | ✓ wall.getById | ⏳ нет токенов |

«Из RAM» — картинка уходит бинарём из памяти процесса (никакого временного
файла и никакого публичного URL). «По URL» — площадка сама скачивает картинку
по ссылке, поэтому нужен публичный адрес.

Порядок публикации фиксирован: **Telegram → Threads → Bluesky → Discord →
Mastodon → VK** (`ORDER` в `publishers/manager.py`). Telegram идёт первым,
потому что возвращает `file_id`, который затем используется как публичный
URL картинки для Threads и сайта.

## Telegram (обязательный минимум)

- **Адаптер:** `science_pulse/publishers/telegram.py`.
- **Переменные:** `TG_BOT_TOKEN`, `TG_CHANNEL_ID`, `TG_ADMIN_CHAT_ID`,
  `TG_MESSAGE_THREAD_ID` (для топиков в группе).
- **Текст:** подпись к фото ≤ 1024 символов, отдельное сообщение ≤ 4096.
  Код режет подпись до 1020. Если полный текст заметно длиннее подписи,
  адаптер досылает второе сообщение (`sendMessage`, до 4000) **ответом** на
  пост с картинкой — так длинные разборы не теряются.
- **Картинка:** `sendPhoto` с `multipart/form-data` (из RAM). При ошибке фото
  адаптер падает в текстовый режим (`_publish_text_fallback`) — пост всё
  равно выходит.
- **Формат:** `parse_mode=HTML`; в подписи уже нет сырого LaTeX — формулы
  переведены в Unicode (`10⁻⁶ s`, `ℏω`). HTML экранируется (`escape_html`).
- **`file_id`:** из ответа `sendPhoto` берётся `photo[-1].file_id`. Он
  сохраняется в `posts.card_file_id` и в `meta["card_file_id"]`. Это ключ для
  прокси Cloudflare (`/tg-cdn/{file_id}.png`) и для картинки Threads.
- **Метрики:** Bot API **не отдаёт** просмотры и реакции. Просмотры канала
  доступны только через MTProto/статистику, которых у бота нет, поэтому
  Telegram в сборщике метрик помечается `skipped`.

Нюансы:

- Бот должен быть администратором канала с правом публикации; для публичного
  канала можно указать `@username` вместо числового id.
- `message_thread_id` нужен только для форумных групп с топиками.
- Токен бота наружу не отдаётся: Threads получает картинку через прокси
  Worker'а по `file_id`, а не по прямой ссылке `api.telegram.org/file/...`.

## Threads (Meta)

- **Адаптер:** `science_pulse/publishers/threads.py`.
- **Переменные:** `TH_USER_ID`, `TH_ACCESS_TOKEN` (long-lived, ~60 дней).
- **Текст:** жёсткий лимит **500 символов**. Адаптер собирает короткий текст
  (≤495), режет на чанки по 490 и публикует **цепочкой reply** (до 3 постов),
  связывая их через `reply_to_id`. Ссылка на сайт добавляется в последний чанк.
- **Картинка:** только по **публичному URL**. Threads не принимает бинарь.
  Источники URL по приоритету:
  1. `CF_WORKER_URL/tg-cdn/{file_id}.png` — если задан Worker и Telegram дал
     `file_id` (токен бота не раскрывается);
  2. `{site_base_url}/cards/{id}.png` — картинка с сайта.
  Если URL нет — выходит текстовый пост.
- **Поток публикации (двухшаговый):** `POST /{user}/threads` создаёт
  **контейнер**, затем `POST /{user}/threads_publish` публикует его. Контейнер
  живёт 24 часа. Между шагами адаптер ждёт 1.2 с, публикацию повторяет до 2 раз.
- **Метрики:** `GET /{media_id}/insights?metric=views,likes,replies` (скоуп
  `threads_manage_insights`). Именно эти три метрики читает наш сборщик.

Нюансы:

- Токен протухает через ~60 дней; продление — отдельный вызов
  `refresh_access_token` (пока вручную/кроном).
- Опубликованный текст **нельзя отредактировать** — только удалить и
  опубликовать заново.
- Суточные квоты Meta: порядка 250 публикаций и 1000 ответов; наш лимит в
  3 чанка на пост с большим запасом укладывается.
- Ошибка публикации контейнера может сообщать `is_transient: false`, но быть
  временной — повтор с тем же `creation_id` часто проходит (учтено retry).

## Bluesky

- **Адаптер:** `science_pulse/publishers/bluesky.py`.
- **Переменные:** `BLUESKY_HANDLE` (напр. `sciencepulse.bsky.social`),
  `BLUESKY_APP_PASSWORD` (`xxxx-xxxx-xxxx-xxxx`).
- **Текст:** лимит **300 символов** (grapheme). Адаптер режет до 298.
- **Картинка:** `com.atproto.repo.uploadBlob` (из RAM, `image/png`), затем в
  запись вкладывается `embed` типа `app.bsky.embed.images` с `alt` = заголовок.
- **Поток:** `com.atproto.server.createSession` (app password → JWT + `did`) →
  `uploadBlob` → `com.atproto.repo.createRecord`. Возвращается `uri` записи,
  из него строится публичная ссылка `bsky.app/profile/{handle}/post/{rkey}`.
- **Метрики:** `app.bsky.feed.getPostThread?uri=...` — публичный вызов без
  авторизации. Отдаёт `likeCount`, `replyCount`, `repostCount`, `quoteCount`,
  `viewCount`. Наш сборщик берёт likes/replies/views.

Нюансы:

- App password создаётся в Settings → Privacy and security → App Passwords;
  основной пароль использовать нельзя.
- Лимит 300 считается по grapheme-кластерам (эмодзи/флаги — это важно),
  поэтому режем с запасом.
- Ссылка на сайт добавляется отдельной строкой; Bluesky сам делает её кликабельной.

## Discord

- **Адаптер:** `science_pulse/publishers/discord.py`.
- **Переменные:** `DISCORD_WEBHOOK_URL` (канал → Integrations → Webhooks).
- **Текст:** содержимое ≤ 2000, embed-описание ≤ 4096. Адаптер собирает
  **embed**: заголовок, описание (≤3900), формула в код-блоке, ссылка на сайт.
- **Картинка:** прикладывается файлом `card.png` (`multipart`) и подключается
  как `attachment://card.png` в embed.
- **Цвет:** по дисциплине (`math` — бирюза, `physics` — маджента, `cs` — жёлтый).
- **Метрики:** webhook статистику не отдаёт — Discord в сборщике помечается
  `skipped`.

Нюансы:

- Webhook не даёт id сообщения, поэтому `external_id` пустой; идемпотентность
  обеспечивается записью в `publications` (по `post_id + platform`).
- Лимит на размер файла у Discord — десятки МБ, наши карточки 1080×1080 PNG
  всегда в пределах.

## Mastodon / Mathstodon

- **Адаптер:** `science_pulse/publishers/mastodon.py`.
- **Переменные:** `MASTODON_INSTANCE` (напр. `https://mathstodon.xyz`),
  `MASTODON_ACCESS_TOKEN` (права `read`, `write`).
- **Текст:** типовой лимит инстанса **500 символов**; адаптер режет до 495.
  Формулы рендерятся **нативно** — обёрнуты в `\[ ... \]`.
- **Картинка:** `POST /api/v2/media` (из RAM, `image/png`, `description` =
  заголовок), затем `POST /api/v1/statuses` с `media_ids`.
- **Метрики:** `GET /api/v1/statuses/{id}` отдаёт `favourites_count`,
  `replies_count`, `reblogs_count`. Наш сборщик берёт likes = избранное,
  replies = ответы.

Нюансы:

- Лимит длины зависит от инстанса (обычно 500, бывает больше) — мы держим
  безопасные 495.
- Media v2 асинхронный: у больших медиа может быть `processing`; карточки
  маленькие и проходят сразу.
- `MASTODON_INSTANCE` обязателен — без него адаптер недоступен.

## ВКонтакте (VK)

- **Адаптер:** `science_pulse/publishers/vk.py`.
- **Переменные:** `VK_GROUP_ID` (номер сообщества без минуса),
  `VK_ACCESS_TOKEN` (права `wall`, `photos`, `groups`, `offline`).
- **Текст:** лимит 16384; адаптер режет до 15000. Включены заголовок, хук,
  тело (в Unicode), формула и хэштеги.
- **Картинка:** трёхшаговый wall-upload: `photos.getWallUploadServer` →
  загрузка файла на `upload_url` → `photos.saveWallPhoto`, затем `wall.post`
  с `attachments=photo{owner}_{id}`.
- **Метрики:** `wall.getById?posts={owner}_{post_id}&extended=1` отдаёт
  `views.count`, `likes.count`, `comments.count`. Сборщик достаёт `owner` и
  номер поста из URL `wall-{group}_{id}`.

Нюансы:

- Токен сообщества должен иметь право на публикацию на стене; для стен
  сообществ нужен `from_group=1` (в адаптере есть).
- VK возвращает `post_id` и строит ссылку `vk.com/wall-{group}_{post_id}`.
- Просмотры набираются со временем — первый замер сразу после публикации
  обычно маленький.

## Cloudflare Edge (CDN картинок и OG-теги)

Не площадка публикации, но критичный спутник: Worker в `cloudflare/worker.js`.

| Маршрут | Назначение |
|:--|:--|
| `GET /tg-cdn/{file_id}.png` | Безопасный прокси картинки из Telegram CDN (токен бота не раскрывается) |
| `GET /cards/*` | Карточки из R2 |
| `GET /api/graph` | Граф знаний из D1 |
| `POST /api/ingest` | Загрузка карточки и узла (Bearer `INGEST_SECRET`) |
| `POST /telegram-webhook` | Пульт: `answerCallbackQuery` + запуск GitHub Actions |
| `GET /node/{id}` | Тот же `index.html`, но с `og:image` для соцсетей |

Нюансы:

- `/tg-cdn` кешируется на год (`Cache-Control: immutable`) в edge-кеше.
- `/node/{id}` подставляет `og:title/og:description/og:image` — нужен для
  красивых превью ссылок на сайт в соцсетях.
- `/telegram-webhook` принимает `POST {command}` — этим пользуется Mini App
  «Пульт» (`dist/pult.html`, см. `docs/MINIAPP.md`).
- Секреты Worker'а: `TG_BOT_TOKEN`, `GH_PAT`, `GH_REPO`, `INGEST_SECRET`.

## Метрики площадок: кто что отдаёт

Сборщик `science_pulse/metrics.py` читает **только публичную статистику**;
платных API и LLM не использует.

| Площадка | Источник метрик | Что берём |
|:--|:--|:--|
| Mastodon | `GET /api/v1/statuses/{id}` | likes = `favourites_count`, replies = `replies_count` |
| Bluesky | `getPostThread` | views, likes, replies |
| VK | `wall.getById` | views, likes, replies |
| Threads | `GET /{id}/insights` | views, likes, replies |
| Telegram | — | Bot API не отдаёт просмотры → `skipped` |
| Discord | — | webhook не отдаёт статистику → `skipped` |

```bash
python -m science_pulse.cli metrics --collect   # опросить и сохранить
python -m science_pulse.cli metrics             # агрегат
python -m science_pulse.cli metrics --json
```

Нюансы:

- Собираются только успешные публикации с внешним id (`publications.status='ok'`).
- Ошибка одной площадки не роняет сбор: замер помечается `error`, остальные
  сохраняются.
- Каждый запуск **добавляет** снимок; `metrics_for(post_id)` возвращает
  последний замер по каждой площадке, `metrics_summary()` — агрегат.
- В пульте — команда `/metrics`.

## Порядок публикации и идемпотентность

1. Telegram публикует карточку и возвращает `file_id`.
2. Менеджер сразу пишет `card_file_id` в объект поста, `meta` и SQLite.
3. Формируется `CF_WORKER_URL/tg-cdn/{file_id}.png`.
4. Только после этого вызываются остальные площадки с готовым контекстом.

Повторный запуск **не дублирует** пост: перед публикацией проверяется
`publication_exists(post_id, platform)`. Если площадка уже опубликована,
результат помечается `skipped: уже опубликовано`. Параллельной отправки нет —
порядок строго последовательный.

## Сводка ловушек

| Ловушка | Площадка | Как закрыто |
|:--|:--|:--|
| Нет просмотров через Bot API | Telegram | Сборщик метрик помечает `skipped` |
| Картинка только по URL | Threads | Прокси Worker'а по `file_id` или карточка с сайта |
| Токен живёт ~60 дней | Threads | Продление `refresh_access_token` (вручную/кроном) |
| Текст нельзя редактировать | Threads | Только удалить и опубликовать заново |
| Контейнер живёт 24 часа | Threads | Публикуем сразу, retry до 2 раз |
| Жёсткий лимит 300 | Bluesky | Режем до 298 с запасом |
| Лимит зависит от инстанса | Mastodon | Держим безопасные 495 |
| Нет id сообщения | Discord | Идемпотентность через таблицу `publications` |
| Просмотры растут со временем | VK | Повторные замеры `metrics --collect` |
| Сырой LaTeX ломает текст | все | Формулы → Unicode/нативный LaTeX, HTML экранируется |

## Как добавить новую площадку

1. Создать `science_pulse/publishers/<name>.py` с классом-наследником
   `Publisher`: `name`, `available()`, `publish(post, card, context)`.
2. Зарегистрировать класс в `PUBLISHER_CLASSES` и `ORDER`
   (`publishers/manager.py`) — порядок задаёт последовательность отправки.
3. Добавить блок `platforms: {<name>: {enabled: true}}` в `config.yaml`.
4. Если у площадки есть API статистики — добавить сборщик в
   `science_pulse/metrics.py` (метод `_collect_<name>`) и в карту `handler`.
5. Добавить тест с фейковым адаптером (см. `tests/test_publishers.py`) и
   фейковым HTTP для метрик (см. `tests/test_metrics.py`).


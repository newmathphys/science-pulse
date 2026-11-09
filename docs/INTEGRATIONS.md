# Интеграции SCM: API, ключи, лимиты и куда что добавлять

**Дата проверки:** 2026-11-09.  
Этот документ — карта всех внешних систем, с которыми работает SCM. Он
отвечает на три вопроса:

1. **Что за API и зачем он нужен.**
2. **Какие ключи/переменные нужны и куда их класть.**
3. **Где официальная документация и какие лимиты/ловушки учитывать.**

Секреты **никогда** не пишутся в этот файл, `config.yaml`, Git или чат.
Только `.env` локально и GitHub/Cloudflare Secrets для автопилота.

## 0. Быстрая карта

| Система | Зачем SCM | Переменные | Статус |
|:--|:--|:--|:--|
| Telegram Bot API | публикация постов, пульт, `file_id` картинки | `TG_BOT_TOKEN`, `TG_CHANNEL_ID`, `TG_ADMIN_CHAT_ID` | 🟢 работает |
| Meta Threads API | публикация в Threads | `TH_USER_ID`, `TH_ACCESS_TOKEN` | ⚪ нет токена |
| Cloudflare Workers | публичный HTTPS-прокси `/tg-cdn/{file_id}.png` | `CF_WORKER_URL`, Worker secret `TG_BOT_TOKEN` | 🟢 задеплоен |
| Cloudflare D1 | edge-состояние, граф знаний | `DB` binding, `INGEST_SECRET` | 🟢 схема применена |
| Cloudflare R2 | карточки на edge | `R2_BUCKET` binding | ⚪ не включён |
| GitHub Actions | автопилот 4 раза в день | Secrets репозитория | 🟢 работает |
| GitHub Pages | сайт и карточки | встроенный `GITHUB_TOKEN` | 🟢 работает |
| Bluesky | опциональная площадка | `BLUESKY_HANDLE`, `BLUESKY_APP_PASSWORD` | ⚪ нет ключей |
| Discord | опциональная площадка | `DISCORD_WEBHOOK_URL` | ⚪ нет ключей |
| Mastodon | опциональная площадка | `MASTODON_INSTANCE`, `MASTODON_ACCESS_TOKEN` | ⚪ нет ключей |
| VK | опциональная площадка | `VK_GROUP_ID`, `VK_ACCESS_TOKEN` | ⚪ нет ключей |
| Источники | контент | ключи не нужны (кроме опционального StackExchange) | 🟢 работают |
| TTS | озвучка | ключи не нужны | 🟢 edge/google; espeak в CI |
| LLM | **не используется** | — | ⛔ выключено |

## 1. Куда добавлять ключи

| Место | Что туда | Кто читает |
|:--|:--|:--|
| `.env` в корне | все локальные секреты | `science_pulse/config.py` |
| GitHub → Settings → Secrets and variables → Actions | те же ключи для CI | `.github/workflows/science_pulse.yml` |
| Cloudflare Worker secrets | `TG_BOT_TOKEN`, `INGEST_SECRET`, при необходимости `GH_PAT`, `GH_REPO` | `cloudflare/worker.js` |
| `config.yaml` | только несекретные настройки | весь проект |

Правила:

- `.env` уже в `.gitignore`; не коммитить.
- В чат и скриншоты токены не попадают.
- При утечке токен отзывается и заменяется, а не «прячется».
- Threads-токен живёт ~60 дней; Cloudflare API-токен — по политике аккаунта.

## 2. Telegram Bot API

- **Официальная документация:** https://core.telegram.org/bots/api
- **Код:** `science_pulse/publishers/telegram.py`, `science_pulse/admin.py`
- **Переменные:**
  - `TG_BOT_TOKEN` — @BotFather → `/newbot`
  - `TG_CHANNEL_ID` — `@newmathphys` или числовой id
  - `TG_ADMIN_CHAT_ID` — id оператора для пульта
  - `TG_MESSAGE_THREAD_ID` — только для топиков в группе
- **Права:** бот должен быть администратором канала с правом публикации.
- **Основные методы:** `getMe`, `getChat`, `getChatMember`, `sendPhoto`,
  `sendMediaGroup`, `sendMessage`, `sendVoice`, `sendAudio`, `sendVideo`,
  `getFile`, `setMyCommands`, `sendPoll`.
- **Лимиты (проверять по документации):** текст 4096, подпись к медиа 1024,
  фото/видео/аудио — свои ограничения по размеру.
- **`file_id`:** после `sendPhoto` SCM сохраняет `photo[-1].file_id`; это ключ
  для Cloudflare `/tg-cdn/{file_id}.png` и картинки Threads.
- **Проверка:**

```bash
./sp launch
python -m science_pulse.cli publish --dry-run
```

## 3. Meta Threads API

### 3.1. Создание приложения

Страница создания: https://developers.facebook.com/apps/creation/

Что выбрать:

1. **App name** — например `Science Pulse`.
2. **Contact email** — рабочий email.
3. **Use case** — **Access the Threads API**.
4. Создать приложение.
5. В левом меню: **Use cases → Customize**.
6. В **Settings** взять **Threads App ID** и **Threads App Secret**.
   Это **отдельные** ID/Secret, не обычные Meta App ID/Secret.
7. Добавить **Threads Tester**: App roles → Roles → Add People →
   Threads Tester.
8. В приложении Threads: Account Settings → Website permissions → принять
   приглашение.
9. Сгенерировать **Access Token** и взять **Threads User ID**.
10. Для OAuth-потока добавить **Client OAuth Settings → Valid OAuth Redirect
    URIs** (HTTPS, не localhost).

Официальные документы:

- Get started: https://developers.facebook.com/documentation/threads/get-started
- Use case: https://developers.facebook.com/documentation/development/create-an-app/threads-use-case
- Posts: https://developers.facebook.com/documentation/threads/posts
- Overview/limits: https://developers.facebook.com/documentation/threads/overview
- Long-lived tokens: https://developers.facebook.com/documentation/threads/get-started/long-lived-tokens
- Publishing reference: https://developers.facebook.com/documentation/threads/reference/publishing
- Sample app: https://github.com/fbsamples/threads_api

### 3.2. Переменные SCM

```env
TH_USER_ID=...
TH_ACCESS_TOKEN=...
```

Для OAuth через официальный sample дополнительно (не нужны для публикации):

```env
THREADS_APP_ID=...
THREADS_APP_SECRET=...
```

### 3.3. API

- **Хост:** `https://graph.threads.com/v1.0/...`
  (документация допускает и `graph.threads.net`, но SCM использует `.com`).
- **Публикация:**
  1. `POST /v1.0/{user_id}/threads` — создать контейнер.
  2. `POST /v1.0/{user_id}/threads_publish` — опубликовать контейнер.
- **Статус контейнера:** `GET /v1.0/{container_id}?fields=status,error_message`.
  SCM ждёт `FINISHED`/`PUBLISHED` до ~30 секунд.
- **Текст:** до 500 символов.
- **Картинка:** только публичный URL (JPEG/PNG, до 8 МБ, aspect ratio до 10:1).
- **Видео:** MOV/MP4, H.264/HEVC, AAC, до 5 минут/1 ГБ.
- **Лимиты профиля:** 250 публикаций/24 ч, 1000 ответов/24 ч, 100 удалений,
  500 поисков локаций.
- **Токен:** long-lived ~60 дней; refresh:
  `GET https://graph.threads.com/refresh_access_token?grant_type=th_refresh_token&access_token=...`
- **Ошибки:** `is_transient` может быть `false`, но повтор контейнера иногда
  проходит; SCM делает retry и fallback IMAGE → TEXT.

### 3.4. Картинка Threads

Threads не принимает бинарь. SCM использует:

```text
Telegram sendPhoto → file_id
  → https://<CF_WORKER_URL>/tg-cdn/<file_id>.png
  → Threads image_url
```

Токен бота в URL не попадает. Если Worker недоступен — fallback на карточку
сайта или TEXT.

## 4. Cloudflare Workers / D1 / R2

- **Workers:** https://developers.cloudflare.com/workers/
- **Wrangler:** https://developers.cloudflare.com/workers/wrangler/
- **D1:** https://developers.cloudflare.com/d1/
- **R2:** https://developers.cloudflare.com/r2/
- **Secrets:** https://developers.cloudflare.com/workers/configuration/secrets/
- **API tokens:** https://developers.cloudflare.com/fundamentals/api/get-started/create-token/
- **Код:** `cloudflare/worker.js`, `cloudflare/wrangler.toml`, `cloudflare/schema.sql`

### 4.1. Что уже сделано

```text
Worker:  https://science-pulse-edge.newmathphys.workers.dev
D1:      science-pulse, схема применена
Secrets: TG_BOT_TOKEN, INGEST_SECRET
R2:      не включён (для /tg-cdn не нужен)
```

### 4.2. Переменные SCM

```env
CF_WORKER_URL=https://science-pulse-edge.<account>.workers.dev
INGEST_SECRET=<тот же, что в Worker>
```

`CF_WORKER_URL` — не секрет. `INGEST_SECRET` — секрет, нужен для
`/api/ingest` и D1/R2-синхронизации.

### 4.3. Секреты Worker

```bash
cd cloudflare
wrangler secret put TG_BOT_TOKEN
wrangler secret put INGEST_SECRET
# опционально, для кнопок/крона Worker:
wrangler secret put GH_PAT
wrangler secret put GH_REPO
```

### 4.4. Маршруты Worker

| Маршрут | Назначение | Нужны биндинги |
|:--|:--|:--|
| `GET /tg-cdn/{file_id}.png` | прокси картинки Telegram | `TG_BOT_TOKEN` |
| `GET /cards/*` | карточки из R2 | `R2_BUCKET` |
| `POST /api/ingest` | карточка + узел в R2/D1 | `R2_BUCKET`, `DB`, `INGEST_SECRET` |
| `GET/POST /api/state` | реплика SQLite ↔ D1 | `DB`, `INGEST_SECRET` |
| `POST /telegram-webhook` | кнопки пульта → GitHub Actions | `TG_BOT_TOKEN`, `GH_PAT`, `GH_REPO` |
| `GET /node/{id}` | OG-страница узла | `DB`, `SITE_ORIGIN` |

### 4.5. R2

R2 включается отдельно в Cloudflare Dashboard → R2 → Enable. После включения:

```bash
wrangler r2 bucket create science-pulse-cards
```

и раскомментировать `[[r2_buckets]]` в `wrangler.toml`. Для Threads-картинки
R2 не нужен.

## 5. GitHub Actions и Pages

- **Actions:** https://docs.github.com/en/actions
- **Secrets:** https://docs.github.com/en/actions/security-guides/using-secrets-in-github-actions
- **Pages:** https://docs.github.com/en/pages
- **Код:** `.github/workflows/science_pulse.yml`

Что добавить в **Settings → Secrets and variables → Actions**:

```text
TG_BOT_TOKEN
TG_CHANNEL_ID
TG_ADMIN_CHAT_ID
TH_USER_ID
TH_ACCESS_TOKEN
CF_WORKER_URL
INGEST_SECRET
```

Опционально: `BLUESKY_HANDLE`, `BLUESKY_APP_PASSWORD`, `DISCORD_WEBHOOK_URL`,
`MASTODON_INSTANCE`, `MASTODON_ACCESS_TOKEN`, `VK_GROUP_ID`,
`VK_ACCESS_TOKEN`, `STACKEXCHANGE_API_KEY`.

`GITHUB_TOKEN` выдаётся Actions автоматически, вручную его добавлять не нужно.
`GH_PAT` нужен только Worker'у для `workflow_dispatch`, не для самого Actions.

## 6. Опциональные площадки

| Площадка | Переменные | Где взять | Документация |
|:--|:--|:--|:--|
| Bluesky | `BLUESKY_HANDLE`, `BLUESKY_APP_PASSWORD` | bsky.app → Settings → App Passwords | https://docs.bsky.app/docs/get-started |
| Discord | `DISCORD_WEBHOOK_URL` | канал → Integrations → Webhooks | https://discord.com/developers/docs/resources/webhook |
| Mastodon | `MASTODON_INSTANCE`, `MASTODON_ACCESS_TOKEN` | Preferences → Development → New Application | https://docs.joinmastodon.org/api/ |
| VK | `VK_GROUP_ID`, `VK_ACCESS_TOKEN` | vkhost.github.io → права `wall`, `photos`, `groups` | https://dev.vk.com/ru/method/wall.post |

Лимиты и поведение адаптеров — `docs/PLATFORMS.md`.

## 7. Источники контента

| Источник | Ключ | Документация | Код |
|:--|:--|:--|:--|
| Wikipedia (ru) | нет | https://www.mediawiki.org/wiki/API:Main_page | `sources/wikipedia.py` |
| Stack Exchange | опционально `STACKEXCHANGE_API_KEY` | https://api.stackexchange.com/docs | `sources/stackexchange.py` |
| arXiv | нет | https://info.arxiv.org/help/api/index.html | `sources/arxiv.py` |
| OEIS | нет | https://oeis.org/wiki/JSON_Format | `sources/oeis.py` |
| Rosetta Code | нет | https://rosettacode.org/wiki/Rosetta_Code | `sources/rosetta.py` |
| GitHub raw | нет | https://raw.githubusercontent.com/ | `sources/github_raw.py` |
| SymPy/CODATA offline | нет | https://www.sympy.org/, https://codata.org/ | `sources/offline.py` |

Ключи не обязательны. StackExchange без ключа имеет меньшую квоту. Если
источник недоступен — работает офлайн-бункер SymPy + SciPy CODATA.

## 8. TTS и медиа

| Движок | Сеть | Ключ | Документация |
|:--|:--|:--|:--|
| edge-tts (`ru-RU-SvetlanaNeural`) | да | нет | https://github.com/rany2/edge-tts |
| Piper (ONNX) | нет | нет | https://github.com/rhasspy/piper |
| Google TTS (резерв) | да | нет | неофициальный endpoint, без SLA |
| espeak-ng | нет | нет | https://github.com/espeak-ng/espeak-ng |
| Сонификация `sound.py` | нет | нет | код проекта |

Порядок: `edge → piper → google_tts → espeak → sonification`. Лимиты и
cooldown — `docs/VOICE.md`.

Медиа-сборка: `ffmpeg`, `Pillow`, `matplotlib`, `NumPy/SciPy`, `Typst`
(https://typst.app/docs/). Всё бесплатно.

## 9. LLM и перевод

- **LLM сейчас не используется.** `./sp check` содержит гейты `no_llm` и
  `no_ai_translation`.
- Перевод (`gtx`/MyMemory/deep-translator) выключен: `translate: false`.
- Будущий LLM — только отдельный плагин, выключенный по умолчанию; ядро
  остаётся без LLM.

## 10. Порядок подключения с нуля

1. **Telegram:** BotFather → токен → бот админ канала → `.env`.
2. **Cloudflare:** `wrangler login` → D1 → schema → secrets →
   `wrangler deploy` → `CF_WORKER_URL` в `.env`.
3. **Threads:** Meta app → Threads use case → tester → токен → `.env`.
4. **GitHub Secrets:** повторить ключи для CI.
5. **Проверка:**

```bash
./sp next
./sp launch
./sp check
```

6. **Первый пост:**

```bash
./sp publish --target telegram
./sp publish --target threads
```

## 11. Частые ошибки

| Симптом | Причина | Что делать |
|:--|:--|:--|
| Threads `401` | токен истёк/не тот | новый `TH_ACCESS_TOKEN` |
| Threads `403` | аккаунт не Threads Tester | добавить тестера и принять приглашение |
| Threads `image_url` rejected | URL не публичный/HTTP/404 | проверить `CF_WORKER_URL/tg-cdn/...` |
| Threads `container not ready` | не дождались обработки | SCM ждёт до 30 с; повторить |
| Cloudflare `workers.dev` TLS error | субдомен не зарегистрирован/сеть | зарегистрировать workers.dev, повторить |
| `CF_WORKER_URL` не задан | нет `.env`/Secret | добавить URL |
| R2 error 10042 | R2 не включён | Dashboard → R2 → Enable |
| Telegram `chat not found` | бот не админ/неверный id | добавить бота в канал |

## 12. Мониторинг изменений API

Раз в неделю GitHub Actions запускает `./sp watch` и присылает отчёт:
что изменилось в Telegram Bot API, Threads API, Cloudflare Workers,
Telegram WebK и GitHub Actions. Снимок — `data/platform_watch.json`.

```bash
./sp watch
./sp watch --send
./sp watch --json
```

Подробно: `docs/PLATFORM_WATCH.md`.

## 13. Официальные индексы документации

- Meta Threads: https://developers.facebook.com/documentation/threads
- Cloudflare Workers: https://developers.cloudflare.com/workers/
- Telegram Bot API: https://core.telegram.org/bots/api
- GitHub Actions: https://docs.github.com/en/actions
- Bluesky: https://docs.bsky.app/
- Mastodon: https://docs.joinmastodon.org/
- Discord: https://discord.com/developers/docs
- VK: https://dev.vk.com/

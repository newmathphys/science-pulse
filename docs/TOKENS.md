# Токены и площадки

Все секреты — только в `.env` (локально) или GitHub Secrets / Cloudflare
Secrets. В `config.yaml` и Git они не попадают.

> Как каждая площадка ведёт себя на практике (возможности, лимиты, ловушки,
> метрики, порядок публикации) — в `docs/PLATFORMS.md`. Здесь — только
> получение токенов и подключение.

## 1. Telegram (обязательный минимум)

| Переменная | Как получить |
|:--|:--|
| `TG_BOT_TOKEN` | @BotFather → `/newbot` → токен `7123456789:AAH...` |
| `TG_CHANNEL_ID` | канал → Администраторы → добавить бота с правом публикации; для публичного канала можно `@username` |
| `TG_ADMIN_CHAT_ID` | написать @userinfobot → числовой id |
| `TG_MESSAGE_THREAD_ID` | id ветки/топика, если публикуем в тему группы |

Проверка:

```bash
python -m science_pulse.cli status
python -m science_pulse.cli publish --target telegram
```

## 2. Meta Threads

1. developers.facebook.com/apps → Create App → use case **Access the Threads API**.
2. Threads API → Settings → Add or Remove Threads Testers → добавить свой аккаунт.
3. В приложении Threads принять приглашение.
4. Generate Access Token → `TH_ACCESS_TOKEN` (long-lived, 60 дней) и `TH_USER_ID`.

Картинка в Threads передаётся только по публичному URL. Наш Telegram-адаптер
возвращает `file_id`; Cloudflare Worker (`CF_WORKER_URL`) отдаёт его как
`/tg-cdn/{file_id}.png`, не раскрывая токен бота. Без Worker'а Threads
получит текстовый пост.

Продление токена: раз в 30 дней вызвать
`GET https://graph.threads.net/refresh_access_token?grant_type=th_refresh_token&access_token=...`
(в текущей версии — вручную/кроном; модуль бессмертия — следующий этап).

## 3. Bluesky

1. bsky.app → Settings → Privacy and security → App Passwords → Add.
2. `BLUESKY_HANDLE` — например `sciencepulse.bsky.social`.
3. `BLUESKY_APP_PASSWORD` — `xxxx-xxxx-xxxx-xxxx`.

Лимит 300 символов; картинка грузится из RAM через `uploadBlob`.

## 4. Discord

Канал → шестерёнка → Integrations → Webhooks → New Webhook → Copy URL
→ `DISCORD_WEBHOOK_URL`. Лимит 2000 символов (embed — 4096).

## 5. Mastodon / Mathstodon

Preferences → Development → New Application → права `read`, `write` →
`MASTODON_ACCESS_TOKEN`. `MASTODON_INSTANCE=https://mathstodon.xyz`.
Формулы рендерятся нативно в `\[ ... \]`.

## 6. ВКонтакте

1. `VK_GROUP_ID` — номер сообщества без минуса.
2. `VK_ACCESS_TOKEN` — vkhost.github.io → VK Admin → права `wall`, `photos`,
   `groups`, `offline`.
3. Бот должен иметь право публиковать на стене сообщества.

## 7. Cloudflare (опционально, но рекомендуется для Threads)

```bash
cd cloudflare
wrangler d1 create science-pulse
wrangler d1 execute science-pulse --file=schema.sql
wrangler r2 bucket create science-pulse-cards
wrangler secret put TG_BOT_TOKEN
wrangler secret put GH_PAT
wrangler secret put GH_REPO        # owner/repo
wrangler secret put INGEST_SECRET
wrangler deploy
```

Затем `CF_WORKER_URL=https://science-pulse-edge.<account>.workers.dev`.

## 8. GitHub Actions

Secrets репозитория: все переменные выше + `STACKEXCHANGE_API_KEY`
(необязательно). Workflow `.github/workflows/science_pulse.yml` запускается
в 06:00 и 17:00 UTC (09:00/18:00 MSK), умеет `workflow_dispatch` и
публикует сайт на GitHub Pages.

`GH_PAT` нужен только Cloudflare Worker'у для кнопок/крона, который дергает
`workflow_dispatch`. Для самого Actions достаточно встроенного токена.

## 9. Проверка без сети и токенов

```bash
python -m science_pulse.cli run --dry-run
python -m science_pulse.cli site
```

Если онлайн-источники недоступны, включится офлайн-бункер SymPy + CODATA.

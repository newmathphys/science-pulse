# Запуск продукта: Telegram + Threads

Цель этого релиза: SCM работает как продукт в Telegram и Threads. Всё
остальное (Cloudflare, Bluesky, VK, коммерческая ветка, Mini App) — после.

## 1. Что нужно вставить

`.env`:

```env
# Telegram (уже есть)
TG_BOT_TOKEN=...
TG_CHANNEL_ID=@newmathphys
TG_ADMIN_CHAT_ID=...

# Threads (нужно вставить)
TH_USER_ID=...
TH_ACCESS_TOKEN=...
```

Больше для запуска Telegram+Threads ничего не требуется.

## 2. Проверка

```bash
./sp launch
```

Проверяет:

- `TG_BOT_TOKEN`, `TG_CHANNEL_ID`, права бота в канале;
- `TH_USER_ID`, `TH_ACCESS_TOKEN` через `GET /v1.0/me`;
- preflight следующего поста;
- doctor/инварианты.

Ожидаемо:

```text
Telegram: Готово к работе
Threads:  Готово к работе
Итог preflight: ✅ готов к публикации
```

## 3. Threads: важное ограничение

Threads принимает картинку **только по публичному URL**. Без Cloudflare Worker
или уже развёрнутого сайта картинка недоступна, поэтому SCM автоматически
публикует **текстовый пост** с Unicode-рамкой формулы. Это рабочий режим
«только ключи».

Если нужен именно IMAGE:

- задайте `CF_WORKER_URL` (Cloudflare Worker из `cloudflare/`), либо
- задайте `SP_SITE_BASE_URL` и убедитесь, что карточка уже лежит на сайте
  (`/cards/<id>.png`).

Без этого Threads не падает: он честно уходит в TEXT.

## 4. Первый пост

```bash
# только Telegram
./sp publish --target telegram

# только Threads
./sp publish --target threads

# обе площадки
./sp publish
```

Проверить идемпотентность: повторный запуск не должен создать дубликат.

```sql
SELECT platform, status, external_id, url
FROM publications
ORDER BY id DESC LIMIT 10;
```

## 5. Автопилот

- Telegram + Threads включаются автоматически, когда заданы их токены;
- GitHub Actions: `TG_*` и `TH_*` в Secrets; cron 09/13/17/21 МСК;
- локально: `./sp daemon`;
- пульт: `./sp admin`.

## 6. Критерий готовности релиза

1. `./sp launch` — Telegram и Threads «Готово».
2. `./sp publish --target telegram` — пост в канале.
3. `./sp publish --target threads` — пост в Threads (TEXT допустим).
4. Повторный запуск — `skipped`, без дубля.
5. `./sp check` — 602+ тестов, verify, preflight, knowledge integrity зелёные.

После этого SCM считается закрытым для продукта Telegram+Threads.

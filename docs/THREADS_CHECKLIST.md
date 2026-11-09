# Threads: что сделать оператору

Цель: получить `TH_USER_ID` и `TH_ACCESS_TOKEN` для публикации в Threads.
Cloudflare Worker уже готов: `https://science-pulse-edge.newmathphys.workers.dev`.

## 1. Создать приложение

Открыть:

```text
https://developers.facebook.com/apps/creation/
```

Заполнить:

1. **Название приложения** — `Science Pulse`.
2. **Контактный email** — рабочий email.
3. **Вариант использования** — **Доступ к Threads API**
   (Access the Threads API).
4. Нажать **Создать приложение**.

## 2. Настроить приложение

В dashboard приложения:

1. **Варианты использования → Настроить**.
2. Добавить разрешения:
   ```text
   threads_basic
   threads_content_publish
   threads_manage_insights
   threads_read_replies
   threads_manage_replies
   ```
3. Открыть **Настройки**.
4. Взять:
   ```text
   Threads App ID
   Threads App Secret
   ```
   Это **отдельные** значения, не обычные Meta App ID/Secret.
5. Для OAuth (если понадобится) добавить **Valid OAuth Redirect URIs** —
   только HTTPS, не localhost.

## 3. Добавить тестировщика

1. **Роли приложения → Роли → Добавить людей**.
2. Выбрать **Тестировщики Threads / Threads Testers**.
3. Добавить свой Threads-аккаунт `@newmathphys`.
4. В приложении Threads:
   **Настройки аккаунта → Разрешения сайта → принять приглашение**.

Без тестировщика токен не будет работать на вашем аккаунте.

## 4. Получить токен

В dashboard:

```text
Threads API → Настройки / Инструменты → Generate Access Token
```

Если кнопки нет — открыть Graph API Explorer:

```text
https://developers.facebook.com/tools/explorer/1437293284596085/
```

Выбрать приложение `Science Pulse`, права `threads_basic`,
`threads_content_publish`, `threads_manage_insights`, нажать
**Сгенерировать токен доступа**.

`TH_USER_ID` — из ответа `GET /me` или из отладки токена.

Токен из Graph Explorer часто **short-lived** (~1 час). Для автопилота нужен
long-lived (~60 дней). Проверить срок:

```bash
./sp threads-token --status
```

Обменять short-lived на long-lived (нужен `THREADS_APP_SECRET` в `.env`):

```bash
./sp threads-token --exchange
```

## 5. Положить в `.env`

```env
TH_USER_ID=...
TH_ACCESS_TOKEN=...
```

Не присылать в чат, не коммитить.

## 6. Проверить

```bash
./sp next
./sp launch
```

Ожидаемо:

```text
🟢 Threads: @newmathphys
   картинка: cloudflare
🟢 Cloudflare: Worker отвечает
```

Затем:

```bash
./sp publish --target threads
```

Повторный запуск должен дать `skipped`, без дубля.

## 7. GitHub Secrets для автопилота

Добавить в GitHub → Settings → Secrets and variables → Actions:

```text
TH_USER_ID
TH_ACCESS_TOKEN
CF_WORKER_URL
INGEST_SECRET
```

## 8. Если токен не работает

| Ошибка | Причина | Что делать |
|:--|:--|:--|
| `401` | токен истёк/не тот | новый `TH_ACCESS_TOKEN` |
| `403` | аккаунт не Threads Tester | добавить тестера и принять приглашение |
| `image_url` rejected | URL не публичный/404 | проверить `CF_WORKER_URL/tg-cdn/<file_id>.png` |
| `container not ready` | не дождались обработки | SCM ждёт до 30 с; повторить |
| `TH_USER_ID` пуст | не взяли id | `GET /me` или debug token |

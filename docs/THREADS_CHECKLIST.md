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

## 8. Видео со звуком в треде

С 2026-11-12 включён режим `threads.video_first: true`: первый пост в треде —
**VIDEO-аудиограмма** (охват), карточка уходит ответом. Видео загружается в
месячный GitHub Release `media-YYYY-MM`, поэтому публичный URL существует до
публикации. Если загрузка/видео не удались, publisher деградирует к прежнему
IMAGE-first и `attach-media` досылает видео ответом.

Threads не принимает «голый» MP3/OGG. SCM публикует карточку, затем отдельным
ответом — **VIDEO-аудиограмму** (карточка + голос + осциллограмма):

```bash
# 1) собрать MP4 до сборки сайта (чтобы он попал в gh-pages)
./sp attach-media --platform threads --prepare --latest 1

# 2) после деплоя сайта прикрепить видео-ответ к последнему посту
./sp attach-media --platform threads --latest 1
```

В GitHub Actions это делают шаги `Prepare audiogram` и `Attach Threads video`
после `Publish site to gh-pages`. Повторный запуск не дублирует ответ:
id хранится в `post.meta["threads_video_reply_id"]`.

Проверить, что в MP4 есть звук:

```bash
ffprobe -v error -show_entries stream=codec_type,codec_name -of csv=p=0 data/audiogram/<id>.mp4
# video,h264
# audio,aac
```

## 9. Если токен не работает

| Ошибка | Причина | Что делать |
|:--|:--|:--|
| `401` | токен истёк/не тот | новый `TH_ACCESS_TOKEN` |
| `403` | аккаунт не Threads Tester | добавить тестера и принять приглашение |
| `image_url` rejected | URL не публичный/404 | проверить `CF_WORKER_URL/tg-cdn/<file_id>.png` |
| `container not ready` | не дождались обработки | SCM ждёт до 30 с (видео — до 3 мин); повторить |
| `TH_USER_ID` пуст | не взяли id | `GET /me` или debug token |

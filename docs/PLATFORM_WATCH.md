# Мониторинг изменений API площадок

**Зачем:** Telegram, Threads, Cloudflare и GitHub меняют API, лимиты и поля.
Если не заметить изменение, пост может уйти в TEXT вместо IMAGE, обрезаться
или не опубликоваться. SCM раз в неделю проверяет официальные changelog'и и
присылает отчёт оператору.

Это не LLM и не генерация текста: только чтение официальных страниц, разбор
последних записей и сравнение с сохранённым снимком.

## Как запускается

### Автоматически

GitHub Actions → `.github/workflows/platform_watch.yml`:

```text
каждый понедельник 10:00 МСК (07:00 UTC)
```

Workflow:

1. ставит зависимости;
2. запускает `python -m science_pulse.cli watch --send`;
3. отправляет отчёт в `TG_ADMIN_CHAT_ID`;
4. коммитит `data/platform_watch.json` обратно в `main`.

Нужны Secrets:

```text
TG_BOT_TOKEN
TG_ADMIN_CHAT_ID
```

### Вручную

```bash
./sp watch                 # отчёт в консоль
./sp watch --send          # отчёт в админ-чат
./sp watch --json          # машиночитаемый отчёт
./sp watch --force         # считать всё изменённым
```

## Что проверяется

| Источник | URL | Код, который может потребовать правок |
|:--|:--|:--|
| Telegram Bot API | https://core.telegram.org/bots/api | `publishers/telegram.py`, `models.py` |
| Meta Threads API | https://developers.facebook.com/docs/threads/changelog | `publishers/threads.py`, `config.yaml` |
| Cloudflare Workers | https://developers.cloudflare.com/workers/platform/changelog/ | `cloudflare/worker.js`, `wrangler.toml` |
| GitHub Actions | https://github.blog/changelog/label/actions/feed/ | `.github/workflows/*.yml` |

Снимок хранится в `data/platform_watch.json`: хеш разобранного содержимого,
последняя запись и дата проверки. Хешируется **разобранный** результат, а не
вся HTML-страница, поэтому случайные баннеры и локализация не дают ложных
«изменений».

## Что делать, если пришло «изменено»

Отчёт показывает источник, последние записи и файл, который за них отвечает.
Порядок:

1. Открыть официальную ссылку из отчёта.
2. Понять, что изменилось: лимит, поле, endpoint, формат медиа, scope.
3. Обновить соответствующий код:
   - Telegram: `PLATFORM_LIMITS` в `science_pulse/models.py`,
     `science_pulse/platforms_info.py`, тесты, `docs/PLATFORMS.md`;
   - Threads: `science_pulse/publishers/threads.py`, лимиты в
     `config.yaml`, тесты, `docs/INTEGRATIONS.md`;
   - Cloudflare: `cloudflare/worker.js`, `cloudflare/wrangler.toml`,
     `docs/EDGE.md`;
   - GitHub Actions: `.github/workflows/science_pulse.yml`,
     `docs/INTEGRATIONS.md`.
4. Прогнать:

```bash
./sp check
```

5. Обновить `docs/INTEGRATIONS.md` и `docs/PLATFORMS.md` тем же коммитом.

Автоматически посты не переписываются: отчёт только показывает, где менять.
Решение и правка — за оператором.

## Как это связано с постами

- **Telegram:** если изменился лимит подписи/медиа — обновить лимиты и тесты,
  иначе посты начнут резаться или падать.
- **Threads:** если изменился лимит 500 символов, формат картинки или endpoint
  контейнера — обновить `ThreadsPublisher`; иначе IMAGE/TEXT-цепочка сломается.
- **Cloudflare:** если изменился Workers/D1/R2 API — обновить Worker и
  `wrangler.toml`; иначе `/tg-cdn/{file_id}.png` перестанет отдавать картинку
  для Threads.
- **GitHub Actions:** если изменился синтаксис workflow/секреты — обновить
  `.github/workflows/`; иначе автопилот остановится.

## Проверка

```bash
python -m unittest tests.test_platform_watch -v
./sp watch --json
```

Ожидаемо:

```text
sources: 4
changed: []            # после baseline
errors: []
```

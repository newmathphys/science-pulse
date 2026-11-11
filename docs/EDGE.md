# Edge-синхронизация: Cloudflare R2 (картинки) и D1 (состояние)

Документ описывает перенос карточек и узлов знаний на edge: картинки — в R2,
узлы — в D1, через Cloudflare Worker.

Код: `science_pulse/edge.py` (`EdgeSync`).
CLI: `python -m science_pulse.cli edge [--limit N] [--json]`.
Тесты: `tests/test_edge.py`.

## Зачем

Локальный сайт (GitHub Pages) держит картинки в репозитории и состояние в
SQLite. На edge это даёт: CDN картинок без коммитов в Git, «живой» граф знаний
из D1 и стабильные ссылки `og:image` для соцсетей. Edge — это «эшелон 2»:
сайт читает данные из D1, а не из Git.

## Что синхронизируется

Для каждого **опубликованного** поста отправляется:

- карточка `cards/{id}.png` → **R2** (`card_r2_url`);
- узел знаний → **D1** (`knowledge_nodes`): `id`, `domain`, `title`, `hook`,
  `body`, `formula`, `js_fn`, `merkle_hash`, `pagerank`, `poincare_x`,
  `poincare_y`, `source_url`.

`pagerank` и координаты Пуанкаре считаются тем же кодом, что и для сайта
(`science_pulse/graph.py`), поэтому граф на edge и локально совпадает.

## Как работает

`EdgeSync.sync(limit)` шлёт на каждый пост:

```
POST {CF_WORKER_URL}/api/ingest
Authorization: Bearer {INGEST_SECRET}
multipart/form-data: meta=<JSON>, png=<файл>
```

Worker (`cloudflare/worker.js`) кладёт `png` в R2 по ключу `cards/{id}.png`,
а `meta` — в D1 (`INSERT OR REPLACE INTO knowledge_nodes …`). Ответ `200/201/204`
считается успехом.

## D1-Primary и lease-lock

С версии 2026-11-11 CI работает в режиме **D1-Primary**:

- D1 — источник истины для записи;
- локальный `data/science.db` — рабочая копия/кэш, в Git не коммитится;
- каждая мутирующая операция (`harvest`, `publish_next`, `run`, `attach-media`)
  захватывает lease-lock `POST /api/state/lock`;
- второй раннер получает `409` и уходит в `deferred`, не публикуя;
- lock освобождается в `finally` через `POST /api/state/unlock`;
- TTL по умолчанию 900 секунд (`edge.lock_ttl_seconds`);
- до деплоя Worker с `/api/state/lock` включён `edge.lock_required: false`:
  lock работает в режиме `degraded` и не блокирует конвейер. После деплоя
  поставьте `lock_required: true`, чтобы второй раннер уходил в `deferred`.

Перед сменой режима примените схему:

```bash
cd cloudflare
wrangler d1 execute science-pulse --file=schema.sql
```

Проверка:

```bash
python -m science_pulse.cli state --pull
python -m science_pulse.cli state --push
```

`data/science.db` удалён из индекса Git; снимок состояния хранится в
GitHub Release `state-backup` как `state_backup.sqlite.gz`.

## Включение

1. Разверните Worker и хранилища (см. `docs/TOKENS.md`):

```bash
cd cloudflare
wrangler d1 create science-pulse
wrangler d1 execute science-pulse --file=schema.sql
wrangler r2 bucket create science-pulse-cards
wrangler secret put INGEST_SECRET
wrangler deploy
```

2. Задайте в `.env` / GitHub Secrets:

```env
CF_WORKER_URL=https://science-pulse-edge.<account>.workers.dev
INGEST_SECRET=<тот же секрет, что в Worker>
```

3. Отправьте опубликованные посты:

```bash
python -m science_pulse.cli edge --limit 50
python -m science_pulse.cli edge --json
```

## Нюансы

- **Идемпотентность:** Worker делает `INSERT OR REPLACE` — повторная отправка
  не создаёт дублей; картинка перезаписывается тем же ключом.
- **Нет карточки — не отправляем:** пост без файла карточки пропускается с
  пометкой `нет карточки` (не ошибка синхронизации данных).
- **Без секретов команда честно отказывается** (`CF_WORKER_URL/INGEST_SECRET
  не заданы`, код возврата 1).
- **Токен бота не участвует:** картинка уходит бинарём из нашего процесса, а не
  через Telegram CDN.
- **Ошибка одной площадки не мешает другим:** результат по каждому посту
  возвращается отдельно (`results[]`).

## Проверка

```bash
python -m unittest tests.test_edge -v
python -m science_pulse.cli edge --json   # при заданных CF_WORKER_URL/INGEST_SECRET
```

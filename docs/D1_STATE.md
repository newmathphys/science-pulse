# Состояние в D1: CRDT-репликация, pull/push и режим D1-Primary

Документ описывает синхронизацию состояния Science Pulse с Cloudflare D1:
монотонное CRDT-слияние (Join-Semilattice), экспорт в SQL, двусторонний
pull/push и режим «D1 как основной источник» (Hybrid D1-Primary).

Код: `science_pulse/state_export.py` (`StateSync`), `Storage.snapshot` /
`Storage.import_rows` / `Storage.merge_snapshot`. Edge: `cloudflare/worker.js`
(`/api/state`), `cloudflare/schema.sql`. CLI: `python -m science_pulse.cli state`.
Законы слияния доказаны в `formal/Invariants.lean` (см. `docs/FORMAL.md`).
Тесты: `tests/test_state.py`, `tests/test_merge.py`, `tests/test_d1_primary.py`.

## Зачем

Локальный SQLite — источник истины, но он живёт в репозитории (GitHub Actions
коммитит `data/science.db`). Реплика в D1 даёт:

- «живое» состояние на edge (сайт/граф читают D1, а не Git);
- резервную копию и перенос между окружениями;
- основу для перехода «D1 как источник» (см. ниже).

## Что реплицируется

Таблицы состояния (совпадают с локальной схемой):

`posts`, `publications`, `metrics`, `sources`, `kv`, `seen`.

Edge-таблицы (`knowledge_nodes`, `saga_transactions`, `bandit_arms`) —
отдельная группа, заполняется через `/api/ingest` (см. `docs/EDGE.md`).

## CRDT-слияние (Join-Semilattice)

Параллельные писатели (GitHub Actions и edge) могут прислать разные версии
одной строки. `Storage.merge_snapshot(snapshot)` сливает их **монотонно** —
по правилам решётки (идемпотентно, коммутативно, ассоциативно):

| Таблица | Правило слияния |
|:--|:--|
| `posts` | статус: `ready < publishing < failed < published` (побеждает старший); текстовые поля (`card_file_id`, `published_at`, `card_path`, …) — «непустое побеждает пустое»; `quality` — максимум |
| `publications` | по `(post_id, platform)`: `ok` побеждает `failed`/`skipped`/`error` |
| `sources` | свежее `last_ok`/`open_until` побеждает; `failures`/`last_error` — от более свежей записи |
| `seen` | объединение множеств (`INSERT OR IGNORE` по `hash`) |
| `metrics` | объединение по `(post_id, platform, collected_at)` |
| `kv` | ключи-флаги (`paused`, `tg_offset`) не реплицируются; счётчики (`harvest_cursor`, `cycle:*`) — максимум; прочие заполняются, если отсутствуют |

Гарантия: **старый снимок никогда не откатит `published` в `ready`** и не
сотрёт `card_file_id`. Законы слияния статусов доказаны в Lean 4:
`mergeStatus_comm`, `mergeStatus_assoc`, `mergeStatus_idempotent`,
`mergeStatus_preserves_published` (см. `docs/FORMAL.md`).

## API

### Python

- `Storage.snapshot()` → `{таблица: [строки]}` — снимок всех таблиц.
- `Storage.import_rows(snapshot)` → число строк — восстановление
  (`INSERT OR REPLACE`), идемпотентно.
- `Storage.merge_snapshot(snapshot)` → `{таблица: число строк}` — монотонное
  CRDT-слияние снимка с локальным состоянием.
- `StateSync.export_sql()` → текст SQL (схема + `INSERT OR REPLACE`).
- `StateSync.push(batch_size=200)` → отправка снимка пачками по N строк.
- `StateSync.pull()` → скачивание полного снимка D1 и `merge_snapshot`.
- `StateSync.sync(batch_size=200)` → pull → push.

### Worker (`/api/state`)

| Метод | Назначение | Авторизация |
|:--|:--|:--|
| `POST /api/state` | применить снимок `{tables: {…}}` с монотонным слиянием | `Bearer INGEST_SECRET` |
| `GET /api/state` | счётчики строк по таблицам | нет |
| `GET /api/state?full=1` | полный снимок `{ok, tables}` для pull | `Bearer INGEST_SECRET` |

`POST` пишет построчно `INSERT OR REPLACE` (белый список `STATE_TABLES`) и
**монотонно** сливает статусы (`applyMonotonic`): старый `ready` не затирает
`published`, непустые `card_file_id`/`published_at`/`card_path` сохраняются.

## Использование

```bash
# посмотреть счётчики снимка
python -m science_pulse.cli state

# выгрузить SQL-дамп (для wrangler d1 execute / резервной копии)
python -m science_pulse.cli state --export dump.sql
python -m science_pulse.cli state --export -        # в stdout

# отправить состояние в D1 через Worker (пачками по 200)
python -m science_pulse.cli state --push --batch-size 200

# забрать снимок D1 и слить его (CRDT) в локальный SQLite
python -m science_pulse.cli state --pull

# двусторонняя синхронизация: pull → push
python -m science_pulse.cli state --sync
```

Импорт дампа в D1:

```bash
cd cloudflare
wrangler d1 execute science-pulse --file=../dump.sql
```

Требуются `CF_WORKER_URL` и `INGEST_SECRET` (те же, что для `/api/ingest`).

## Нюансы

- **Идемпотентность:** `INSERT OR REPLACE` + монотонный merge — повторный
  push/pull/импорт не создаёт дублей и не откатывает состояние.
- **Белый список таблиц:** Worker применяет только `STATE_TABLES`; прочие
  таблицы из тела игнорируются (защита от случайной записи).
- **Секреты не утекают:** снимок уходит по HTTPS с `Authorization: Bearer`,
  страница/клиент секрет не печатают.
- **Двусторонность:** `pull` тянет состояние из D1 в SQLite, `push` — обратно;
  конфликты решает CRDT-слияние, поэтому параллельные писатели безопасны.
- **Пакетная отправка:** большие таблицы режутся на пачки по `--batch-size`
  (по умолчанию 200), чтобы не превысить лимит размера запроса Worker.
- **Мягкий fallback:** при сетевой ошибке pull/push логируется и не роняет
  пайплайн — работа продолжается на локальном SQLite.

## Режим D1-Primary (Hybrid)

`config.yaml`:

```yaml
edge:
  d1_primary: true    # + CF_WORKER_URL и INGEST_SECRET в окружении
```

При включении пайплайн автоматически:

1. **перед работой** (`harvest`/`publish`) делает `pull_state()` — тянет
   снимок D1 и сливает (CRDT), получая свежую картину со всех воркеров;
2. **работает** на быстром локальном SQLite (офлайн-режим сохраняется);
3. **после работы** делает `push_state()` — отправляет обновлённые статусы в D1.

Логика в `pipeline.py` (`d1_primary_enabled`, `pull_state`, `push_state`).
Если секреты не заданы или сеть недоступна — режим молча выключается
(мягкий fallback), пайплайн продолжает работать локально.

## Статус

Реализовано полностью: репликация, экспорт, двусторонний pull/push,
CRDT-разрешение конфликтов параллельных писателей и режим D1-Primary.
Машинная проверка законов слияния — `formal/Invariants.lean`.

## Проверка

```bash
python -m unittest tests.test_state -v
node --check cloudflare/worker.js
python -c "import sqlite3;sqlite3.connect(':memory:').executescript(open('cloudflare/schema.sql').read());print('schema ok')"
```

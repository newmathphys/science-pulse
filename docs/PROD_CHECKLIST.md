# Боевой запуск: 5 шагов и три ловушки

## Три ловушки (закрыты в коде)

### А. WAL и `git commit`

SQLite работает в `journal_mode=WAL`: свежие записи могут лежать в
`science.db-wal`, а не в `science.db`. Если закоммитить только основной файл,
состояние публикации потеряется и следующий запуск создаст дубликат.

Закрыто:

- `Storage.checkpoint()` выполняет `PRAGMA wal_checkpoint(TRUNCATE);`.
- CLI вызывает checkpoint после `harvest/publish/run/add/site/daemon/admin`.
- Отдельная команда: `python -m science_pulse.cli checkpoint`.
- В GitHub Actions шаг **Checkpoint WAL** стоит до **Save state** и `git add`.

### Б. SimHash64 и знаковый SQLite INTEGER

Python SimHash64 — беззнаковое 64-битное число, SQLite INTEGER — знаковое.
Старший бит даёт `OverflowError`.

Закрыто:

- в `seen.simhash` хранится hex-строка вида `0xffffffffffffffff`;
- старые десятичные значения читаются обратно совместимо;
- расстояние Хэмминга считается через `int(hex, 16)`;
- есть тест на `2**64 - 1`.

### В. `file_id` Telegram → Threads

Порядок публикации строго последовательный:

1. `TelegramPublisher` публикует карточку и получает `file_id`;
2. `PublisherManager` сразу пишет `post.card_file_id`, `meta["card_file_id"]`
   и `posts.card_file_id` в SQLite;
3. формируется `CF_WORKER_URL/tg-cdn/{file_id}.png`;
4. только после этого вызывается `ThreadsPublisher` с обновлённым контекстом.

Параллельной отправки нет. Есть тест: после публикации `card_file_id`
совпадает и в объекте, и в БД.

---

## Шаг 1. Живая добыча без токенов соцсетей

```bash
python -m science_pulse.cli harvest --limit 3
python -m science_pulse.cli status
```

Критерий: очередь пополнилась постами math/physics/cs, у источников обновился `last_ok`.
`numbersapi.com` отключён в `config.yaml`: публичный эндпоинт отдаёт 404/401.
Если сеть недоступна — сработает офлайн-бункер, это не ошибка.

## Шаг 2. Рендер и сайт на реальных данных

```bash
python -m science_pulse.cli publish --dry-run
python -m science_pulse.cli site
```

Критерий: в `data/cards/` появился PNG 1080×1080, в `dist/` есть
`index.html`, `graph.json`, `search.json`, `sitemap.xml`, `llms.txt`.

## Шаг 3. Первый Telegram-пост

```env
TG_BOT_TOKEN=...
TG_CHANNEL_ID=@test_channel
TG_ADMIN_CHAT_ID=...
```

```bash
python -m science_pulse.cli publish
```

Критерий: пост с карточкой в канале; `posts.card_file_id` заполнен;
повторный запуск не создаёт дубликат.

## Шаг 4. Пульт

```bash
python -m science_pulse.cli admin
```

Проверить: `/status`, `/queue`, `/sources`, `/force`, `/add`, `/render`,
`/platforms`, `/platform <имя>`, `/lang ru|en`, `/about`.
Команды живут в `getUpdates` и не протухают, как `callback_query`.
Полный справочник — `docs/PULT.md`.

## Шаг 5. Автопилот

1. Запушить репозиторий.
2. Settings → Pages → Source: GitHub Actions.
3. Добавить Secrets: Telegram, затем Threads/Bluesky/Discord/Mastodon/VK.
4. Actions → `science_pulse.yml` → Run workflow.
5. Проверить, что шаг `Checkpoint WAL` прошёл до `Save state`.

---

## Шаг 6. Метрики площадок

```bash
python -m science_pulse.cli metrics --collect
python -m science_pulse.cli metrics --json
```

Критерий: в таблице `metrics` появились замеры Mastodon/Bluesky/VK/Threads;
Telegram и Discord помечаются `skipped` — их API не отдаёт просмотры/реакции.
В пульте доступна команда `/metrics`. Сборщик читает только публичную
статистику: платных API и LLM не использует.

---

## Шаг 7. Граф, A/B и Пульт

```bash
python -m science_pulse.cli site
```

Критерий: в `dist/` есть `graph.json` с полями `pagerank`, `x`, `y`. На главной —
блок «Топ по PageRank». `pult.html` (Mini App-пульт) появляется только при
`miniapp.public: true` — по умолчанию страница не публикуется (приватность).

A/B стилей включается в `config.yaml` (`abtest.enabled: true`); вариант
пишется в `meta` поста, результат виден в `metrics` (`by_style`).
Подробности — `docs/GRAPH.md`, `docs/ABTEST.md`, `docs/MINIAPP.md`.

---

## Шаг 8. Инварианты и edge

```bash
python -m science_pulse.cli invariants --json
python -m science_pulse.cli edge --limit 50
```

Критерий: `invariants` возвращает `"ok": true` (нет нарушений INV-1…INV-6);
`edge` при заданных `CF_WORKER_URL` и `INGEST_SECRET` кладёт карточки в R2 и
узлы в D1 (`pushed` > 0). Подробности — `docs/INVARIANTS.md`, `docs/EDGE.md`.

---

## Шаг 9. Формальные доказательства

```bash
lean formal/Invariants.lean
python -m science_pulse.cli formal
```

Критерий: доказательства компилируются без ошибок и без `sorry` (`cli formal`
возвращает 0 и печатает «доказаны»). Если Lean не установлен, шаг мягко
пропускается. Подробности — `docs/FORMAL.md`.

---

## Шаг 10. Реплика состояния в D1

```bash
python -m science_pulse.cli state                     # счётчики снимка
python -m science_pulse.cli state --export dump.sql   # SQL-дамп
python -m science_pulse.cli state --sync              # pull → push (CRDT)
python -m science_pulse.cli state --push --batch-size 200
```

Критерий: снимок содержит 6 таблиц (posts/publications/metrics/sources/kv/seen);
`--sync` при заданных `CF_WORKER_URL` и `INGEST_SECRET` возвращает `ok: true`;
старый снимок не откатывает `published` (CRDT-слияние). Режим `edge.d1_primary`
включает pull/push вокруг работы пайплайна. Подробности — `docs/D1_STATE.md`.

---

## Шаг 11. Пульт оператора и автономность

```bash
python -m science_pulse.cli doctor            # 🚦 светофор автономности
python -m science_pulse.cli doctor --send     # отчёт в админ-чат
python -m science_pulse.cli trending --top 5  # 🔥 радар мировых новостей
python -m science_pulse.cli admin --once      # обработка команд из getUpdates (CI)
```

Критерий: `/doctor` показывает 🟢 по Telegram, площадкам и расписанию; очередь
≥ `low_water` (9) и без непереведённых заголовков; `SP_SITE_BASE_URL` начинается
с `https://`. В Пульте работают `/preview` (карточка в личку), `/skip`,
`/trending`, `/pick N [now]`; меню команд ставится через `setMyCommands`.

---

## Шаг 12. Резервное копирование и восстановление

```bash
python -m science_pulse.cli checkpoint            # WAL-чекпоинт: слить журнал в science.db
python -m science_pulse.cli backup                # снимок science.db документом в админ-чат
python -m science_pulse.cli recover-from-channel  # восстановить базу из ленты канала
```

Критерий: `checkpoint` сливает журнал (`science.db-wal` пуст), поэтому `git` и
обычное копирование файла больше не видят «пустую» базу (ловушка А). `backup`
требует `TG_BOT_TOKEN` и `TG_ADMIN_CHAT_ID`: он делает чекпоинт и отправляет
цельный `science.db` документом в админ-чат — то же самое делает `/backup` в
Пульте. Если база потеряна целиком, `recover-from-channel --limit N` читает
историю канала и восстанавливает `posts`/`publications` по `file_id` карточек,
не обращаясь к внешним источникам.

---

## Дополнительно: алгоритмы «после MVP»

`science_pulse/sota.py` работает поверх `kv` без изменения схемы:

- бандит Томпсона (`selection: "thompson"`, `bandit.enabled: true`);
- Hawkes O(1) (`hawkes.enabled: true`);
- FSRS v4.5 (`SOTAKVExtensions.fsrs_retrievability`);
- координаты Диска Пуанкаре (`SOTAKVExtensions.poincare_xy`).

В `config.yaml` по умолчанию включены **Thompson + Hawkes**: дисциплина
выбирается бандитом (награда выдаётся после каждой публикации), а гейт Хоукса
не даёт «перегреть» ленту. Нужна строгая предсказуемость — верните
`selection: "round_robin"` и `hawkes.enabled: false`.

> Отказ гейта Хоукса — это **отложение**, а не ошибка: `cli run`/`cli publish`
> печатают «Публикация отложена (hawkes): …» и возвращают код 0, поэтому
> расписание в CI не падает и не шлёт ложный алерт оператору. Принудительная
> публикация (`--force`, кнопка «🚀» в пульте) гейт обходит.

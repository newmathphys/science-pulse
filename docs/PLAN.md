# Science Pulse — план разработки

Документ-основание: `2-2026-10-31.md` (экспорт диалога, 56 сообщений).
Ниже — выжимка требований, целевая архитектура и поэтапный план. План
рассчитан на то, что проект можно запускать локально без токенов и без сети
(офлайн-режим), а затем постепенно включать источники и площадки.

---

## 1. Что требует заказчик (сводка по документу)

1. Бот публикует **2 раза в сутки** научные посты по трём дисциплинам:
   **математика, физика, информатика**.
2. Контент берётся из **готовых легальных источников** (Wikipedia/Wikimedia,
   Stack Exchange, OEIS, arXiv, Rosetta Code, GitHub raw, Numbers API), а не
   генерируется нейросетью. ИИ минимизируется: максимум — перевод.
3. Картинка **рисуется кодом** (1080×1080): тёмная карточка, формула, график,
   код, рубрика. Никакого Midjourney.
4. Публикация — **отдельными постами** в **Telegram** и **Threads**, далее
   Bluesky, Discord, Mastodon/Mathstodon, VK (включаются токенами).
5. Управление — **Пульт в Telegram**: статус, очередь, принудительный пост,
   пауза, источники, статистика, ссылка на сайт.
6. Сайт **растёт вместе с постами**: страницы постов, поиск, формулы KaTeX,
   граф связей, калькуляторы/симуляции, `sitemap.xml`, `llms.txt`.
7. Отказоустойчивость: несколько источников, кэш/очередь, офлайн-бункер,
   circuit breaker, защита от дублей, fallback рендера и площадок.
8. Экономия: бесплатные API и хостинги, отсутствие платных LLM, минимум
   хранения (картинки не коммитятся в Git; в перспективе — Telegram CDN /
   Cloudflare R2).
9. Модульность: новый источник или соцсеть добавляется адаптером, без
   переписывания ядра.

### Ограничения площадок (из документа)

| Площадка | Текст | Картинка | Особенность |
|:--|--:|:--|:--|
| Telegram | 1024 caption / 4096 сообщение | да | `message_thread_id` для топиков |
| Threads | 500 | по URL | контейнер → публикация, цепочка reply |
| Bluesky | 300 | из RAM | AT Protocol, app password |
| Discord | 2000 / 4096 embed | файл | webhook |
| Mastodon | 500 | из RAM | нативный LaTeX |
| VK | 16384 | из RAM | `photos.getWallUploadServer` |

---

## 2. Целевая архитектура

### Три контура

```
КОНТУР 1 — ДОБЫЧА                 КОНТУР 2 — ПРОИЗВОДСТВО        КОНТУР 3 — ПУБЛИКАЦИЯ
┌─────────────────────────┐      ┌──────────────────────────┐    ┌─────────────────────────┐
│ источники (API/raw)     │      │ нормализация текста      │    │ Telegram / Threads      │
│ quality gate            │ ───> │ защита LaTeX при переводе│───>│ Bluesky / Discord       │
│ dedup (SimHash64)       │      │ рендер карточки 1080×1080│    │ Mastodon / VK           │
│ очередь в SQLite        │      │ график / код / формула   │    │ идемпотентность + WAL   │
└─────────────────────────┘      └──────────────────────────┘    └─────────────────────────┘
             │                              │                               │
             └──────────────┬───────────────┴───────────────┬───────────────┘
                            ▼                               ▼
                   ПУЛЬТ В TELEGRAM                 САМОРАСТУЩИЙ САЙТ
                   (команды, статус, очередь)       (HTML, поиск, граф, KaTeX)
```

### Три эшелона отказоустойчивости

1. **Эшелон 1 — онлайн-источники.** Stack Exchange, OEIS, Wikipedia, arXiv,
   Rosetta Code, GitHub raw, Numbers API. Каждый — с таймаутом, лимитом,
   circuit breaker и записью ошибок.
2. **Эшелон 2 — очередь.** Всё, что успешно собрано, лежит в SQLite. Публикация
   не зависит от доступности источника в момент выхода поста.
3. **Эшелон 3 — офлайн-бункер.** Детерминированный генератор на SymPy +
   SciPy CODATA: ортогональные полиномы, формулы, константы. Работает без
   сети и без повторов за счёт индекса эпохи.

### Принципы

- **Никакого LLM в контенте.** Только детерминированные преобразования.
- **Перевод опционален.** Если `deep-translator` не установлен — текст
  сохраняется в оригинале, пост всё равно выходит.
- **Формулы неприкосновенны.** LaTeX/код маскируются перед переводом и
  восстанавливаются после.
- **Идемпотентность.** Уникальный ключ `(post_id, platform)`; повторный запуск
  не создаёт второй пост.
- **Ноль тяжёлых файлов в Git.** Карточки — в `data/cards/`, сайт — в `dist/`;
  в репозиторий коммитится только код и SQLite-состояние (маленькое).

---

## 3. Что реализуется в этой версии (MVP+)

### 3.1. Ядро

- `science_pulse/config.py` — YAML + `.env` + переменные окружения.
- `science_pulse/models.py` — `Post`, `PublishResult`, валидация, лимиты.
- `science_pulse/storage.py` — SQLite (WAL, FK): посты, публикации, метрики,
  источники, KV, дедупликация.
- `science_pulse/text.py` — очистка HTML, маскировка LaTeX/кода, перевод,
  SimHash64, нарезка под лимиты площадок, Unicode-fallback формул.

### 3.2. Источники (Контур 1)

- `sources/stackexchange.py` — вопросы с `accepted_answer_id`, пакетный запрос
  ответов, извлечение LaTeX, `quota_remaining`/`backoff`.
- `sources/oeis.py` — последовательность, формула, Python-код, `xref`-связи.
- `sources/wikipedia.py` — случайная статья из научной категории + summary.
- `sources/arxiv.py` — Atom API, свежие статьи.
- `sources/rosetta.py` — MediaWiki API, intro + Python-код.
- `sources/github_raw.py` — raw Markdown/JSON из списка URL.
- `sources/numbers.py` — Numbers API (математический факт).
- `sources/history_canon.py` — хронологический канон науки: Пифагор, Евклид,
  Архимед, Ньютон, Эйлер, Фурье, Максвелл, Тьюринг, Шеннон, Нётер.
- `sources/offline.py` — детерминированный бункер (полиномы + CODATA).
- `sources/manager.py` — реестр, приоритеты, circuit breaker, fallback.

### 3.3. Производство (Контур 2)

- `cards.py` — рендер 1080×1080: SSAA 2160→1080, тёмная тема, сетка,
  график функции (SymPy/NumPy), формула, код, источник; безопасные отступы;
  fallback без Matplotlib.
- `plotting.py` — безопасный разбор выражения, комплексная плоскость,
  Re/Im, защита от NaN/∞.

### 3.4. Публикация (Контур 3)

- `publishers/telegram.py` — `sendPhoto`, caption ≤1024, продолжение текстом,
  топики, возврат `file_id`.
- `publishers/threads.py` — контейнер + публикация, текст ≤500, цепочка
  ответов, image по URL или текстовый fallback.
- `publishers/bluesky.py`, `discord.py`, `mastodon.py`, `vk.py`.
- `publishers/manager.py` — включение по наличию токенов, сбор результатов,
  запись в БД, повтор только неуспешных площадок.

### 3.5. Оркестрация и управление

- `pipeline.py` — `harvest()`, `publish_next()`, `run()`, выбор дисциплины
  «маятником» (math → physics → cs), качество, дедуп, fallback.
- `scheduler.py` — ежедневные слоты (09:00/18:00) без внешних зависимостей.
- `admin.py` — Telegram-пульт на long polling: `/status`, `/queue`, `/next`,
  `/force`, `/harvest`, `/sources`, `/pause`, `/resume`, `/stats`, `/site`.
- `cli.py` — `init`, `harvest`, `publish`, `run`, `site`, `admin`, `daemon`,
  `status`, `sources`, `reset`.

### 3.6. Сайт

- `site.py` — `dist/index.html`, `dist/post/<id>.html`, `search.json`,
  `graph.json`, `sitemap.xml`, `llms.txt`, `assets/style.css`.
- Книжный светлый стиль (бумага `#FAF8F4`, тушь `#111827`, Georgia/Source Serif),
  **Карта Ступеней канона** на главной (`§ 1.1 … § N.k`, статусы узлов),
  флешкарты, BibTeX, PWA, поиск по формулам; KaTeX с CDN, ссылки на первоисточники.

### 3.7. Инфраструктура

- `cloudflare/worker.js` + `schema.sql` — заготовка edge-слоя: Telegram CDN
  proxy, R2-картинки, D1-граф, вебхук пульта (опционально).
- `.github/workflows/science_pulse.yml` — cron 2 раза в сутки, запуск,
  сохранение состояния, публикация сайта на Pages.
- `tests/` — unittest без сети: текст, БД, карточки, офлайн-источник,
  сайт, конвейер с фейковыми адаптерами.

---

## 4. Модель данных (SQLite)

```
posts(id TEXT PK, domain, title, hook, body, formula_latex, formula_plain,
      code, source_name, source_url, tier, quality, status, created_at,
      scheduled_for, published_at, card_path, card_file_id, meta_json)
publications(id PK, post_id FK, platform, external_id, url, status, error,
             created_at, UNIQUE(post_id, platform))
metrics(id PK, post_id, platform, views, likes, replies, collected_at)
sources(name PK, enabled, last_ok, last_error, failures, open_until)
kv(key PK, value)
seen(hash PK, post_id, created_at)
```

Статусы поста: `ready` → `publishing` → `published` / `failed`.
Выбор следующего поста: сначала `ready` с наименьшим `created_at`, но с
чередованием дисциплин; если очередь пуста — офлайн-бункер.

---

## 5. Алгоритмы

1. **Дедупликация.** Нормализация заголовка + SimHash64 по шинглам.
   Хэш хранится в `seen`; при совпадении пост отбрасывается.
2. **Quality gate.** Минимальная длина заголовка/тела, наличие формулы или
   кода, отсутствие мусорных HTML-остатков, score источника.
3. **Маятник дисциплин.** Если прошлый пост был `math`, следующий —
   `physics`, затем `cs`. Внутри дисциплины — FIFO.
4. **Circuit breaker.** 3 ошибки подряд → источник `OPEN` на 30–60 минут.
   Успех сбрасывает счётчик.
5. **Перевод с защитой.** Маскируются `$...$`, `$$...$$`, `\(...\)`,
   `\[...\]`, fenced code, inline code; после перевода возвращаются.
6. **Рендер.** 2160×2160 → LANCZOS → 1080×1080; проверка безопасной рамки;
   при переполнении — уменьшение шрифта и повтор.
7. **Публикация.** Сначала Telegram (даёт `file_id` и CDN-идентификатор),
   затем остальные площадки; ошибка одной площадки не отменяет остальные.

---

## 6. Этапы и критерии приёмки

### Этап 0. Каркас (сделано в этой версии)
- [x] Структура пакета, конфиг, `.env.example`, README.
- [x] SQLite-хранилище с миграцией.
- [x] CLI `init/status`.

### Этап 1. Контент без сети
- [x] Офлайн-бункер: полиномы + CODATA, детерминированный индекс.
- [x] Рендер карточки 1080×1080.
- [x] Тест: карточка создаётся, размер 1080×1080, файл > 10 КБ.

### Этап 2. Онлайн-источники
- [x] Stack Exchange (принятые ответы, LaTeX).
- [x] OEIS, Wikipedia, arXiv, Rosetta Code, GitHub raw, Numbers API.
- [x] Circuit breaker, таймауты, лимиты.
- [x] Тест: парсеры на фикстурах (без сети).

### Этап 3. Публикация
- [x] Telegram + Threads + Bluesky + Discord + Mastodon + VK.
- [x] Идемпотентность, запись результатов.
- [x] Тест: фейковый публикатор, повторный запуск не дублирует.

### Этап 4. Пульт и расписание
- [x] Long polling команды.
- [x] Планировщик 2 раза в сутки.
- [x] Тест: команды `/status`, `/force` на фейковом Telegram API.

### Этап 5. Сайт
- [x] Генерация страниц, поиска, графа, sitemap, llms.txt.
- [x] Тест: файлы создаются, пост присутствует в индексе.

### Этап 6. Инфраструктура
- [x] GitHub Actions (cron + ручной запуск).
- [x] Cloudflare Worker/D1/R2 заготовки.
- [x] Документация по токенам и запуску.

### Дальше (после MVP)
- [x] Перевод через deep-translator (опционально, `SP_TRANSLATE=1`) — см. `docs/TRANSLATION.md`.
- [x] Telegram Mini App «Пульт»: статическая `dist/pult.html` — см. `docs/MINIAPP.md`.
- [x] Cloudflare R2/D1: edge-синхронизация `science_pulse/edge.py` — см. `docs/EDGE.md`.
- [x] Репликация состояния в D1: `science_pulse/state_export.py`, `/api/state` —
      см. `docs/D1_STATE.md`.
- [x] D1 как основной источник: CRDT-слияние (`Storage.merge_snapshot`),
      `state --pull/--sync/--batch-size`, режим `edge.d1_primary`, монотонный
      merge в Worker; законы слияния доказаны в Lean (`docs/FORMAL.md`).
- [x] `science_pulse/sota.py`: бандит Томпсона, Hawkes O(1), FSRS v4.5,
      координаты Диска Пуанкаре (включаются флагами).
- [x] `sources/history_canon.py`: хронологический канон от Пифагора до Нётер.
- [x] PageRank/Пуанкаре-граф в сайте: `science_pulse/graph.py` — см. `docs/GRAPH.md`.
- [x] Инварианты состояния (INV-1…INV-6): `science_pulse/invariants.py` — см. `docs/INVARIANTS.md`.
- [x] Lean-доказательства инвариантов (машинная проверка): `formal/Invariants.lean`,
      `cli formal` — см. `docs/FORMAL.md`.
- [x] Метрики площадок: `science_pulse/metrics.py`, `cli metrics --collect`,
      `/metrics` в пульте (Mastodon/Bluesky/VK/Threads; Telegram/Discord — `skipped`).
- [x] A/B стилей карточки: `science_pulse/abtest.py` — см. `docs/ABTEST.md`.
- [x] Светофор автономности `/doctor` + `cli doctor` — см. `docs/PULT.md`.
- [x] Радар мировых новостей: `science_pulse/trending.py`, `/trending`, `/pick`,
      `cli trending` — см. `docs/TRENDING.md`.
- [x] Операторские команды: `/preview` (карточка в личку), `/skip` (приоритет
      очереди), меню `setMyCommands`, `cli admin --once` для CI.
- [x] Авто-пополнение очереди: `low_water` (по умолчанию 9) в `Pipeline.run()`.
- [x] Карточки 3Blue1Brown + Typst: 3 архетипа, цветовой ключ, формула
      математическим движком — см. `docs/CARDS.md`.
- [x] Автономный контур GitHub Actions: `admin --once`, `doctor`, деплой Pages,
      сохранение состояния `if: always()`, алерт оператору `if: failure()`.
- [x] Книжная серия карточек: `science_pulse/cards_academic.py` (бумага
      `#FAF8F4`, тушь `#111827`, DejaVu Serif, формулы Computer Modern,
      `y_cursor`-вёрстка), 5 архетипов (`standard_plot`, `code_booktabs`,
      `diptych_insar`, `cheatsheet_table`, `timeline_evolution`) — см. README.
- [x] Детерминированные симуляции `science_pulse/simulate.py` (NumPy/SciPy):
      InSAR/NDVI, геодезические Шварцшильда, туннелирование (split-step FFT),
      Леннард-Джонс, аттрактор Лоренца.
- [x] Междисциплиналярные узлы канона: `schrodinger`, `insar_ndvi`,
      `schwarzschild_light`, `quantum_tunneling`, `lj_lorenz` — «Тройная связь
      времени» (`scientist`/`era` → формула/`constants_used` →
      `modern_application`), `prereq_ids` к учёным-основателям, `visual_type`.
- [x] Словарь констант (CODATA из `scipy.constants`): `science_pulse/constants.py`,
      страница `constants.html`, связка «константа → посты».
- [x] Страницы знаний: Досье учёных (`scientists.html`), Темы и маршруты
      изучения (`topics.html`, хабы при ≥2 постах с общей концепцией).
- [x] PDF-книга проекта: `science_pulse/book.py` (Typst: титул, `#outline()`,
      главы по дисциплинам, формулы CM, предметный указатель учёных),
      `cli book`, `/book` в пульте.
- [x] Расписание 4 слота в сутки: 09:00/13:00/17:00/21:00 МСК (cron `0 6,10,14,18 * * *`).
- [x] Озвучка постов: `science_pulse/voice.py` (edge-tts онлайн / piper офлайн,
      голос `ru-RU-SvetlanaNeural`), голосовое OGG/OPUS + аудио-подкаст MP3,
      кэш `data/audio/`, плеер на сайте, `/voice` в пульте — см. `docs/VOICE.md`.
- [x] Полная подпись под карточкой: разбор до ~620 символов (вместо обрезка в
      380) и конкретное «Где работает сегодня» из `meta["modern_application"]`
      вместо шаблонной врезки дисциплины.
- [x] Озвученные микро-видео: `sound.py` (сонификация: Фурье/волновой пакет/
      шаги сортировки) + `video.py` (30 кадров книжной страницы + ffmpeg →
      MP4 H.264+AAC, fallback GIF), режим `video.every_nth_post`, `sendVideo`,
      `--video` / `/force video` / `/preview video` — см. `docs/VIDEO.md`.
- [x] Контур качества: `standards.py` (7 рубежей, авто-лечение, карантин
      `rejected`) + `preflight.py` (предполётная проверка), команды
      `standards`/`quarantine`/`reject`/`preflight` — см. `docs/QUALITY.md`.
- [x] Старт от фундамента: `sources/foundation.py` (ступени 1–6) + `evolve.py`
      (порядок выхода, паспорт 🏛/🔬/🔗, обратные ссылки `used_in`),
      `cli foundation`.
- [x] Единая верификация `cli verify`: инварианты + Lean (INV-7:
      `published_implies_gate`, `gate_blocks_published`, `round_robin_no_deadlock`,
      `reject_monotone`) + фаззинг подписей + медиа-smoke, `tests/test_fuzz.py`.
- [x] Единый движок правил площадок: `platforms_info.DEFAULT_PLATFORM_RULES` +
      `PlatformRules` (kv → config.yaml → дефолт), все 6 адаптеров читают лимиты
      и режим звука оттуда; `audio_mode` = auto/voice/audio/mp4/file/link/off;
      видео-аудиограмма (`voice.build_audiogram_mp4`) для видео-сетей;
      команды `/limits`, `/limits set`, `/limits reset` — см. `docs/LIMITS.md`.
- [x] Фонетический нормализатор формул `math_to_spoken_russian` (диктор
      произносит `O(N log N)`, `Δφ`, `ℏ`, `c²`, `≥` как лектор).
- [x] Живая осциллограмма в аудиограмме: `ffmpeg showwaves` + overlay над
      колонтитулом (цвет чернил дисциплины), fallback на статичную картинку.
- [x] Прямая загрузка `.mp4` без сайта: Bluesky (`uploadBlob` video/mp4 →
      `app.bsky.embed.video`), VK (`video.save` → upload_url).
- [x] Авто-определение `SP_SITE_BASE_URL` из `git remote` (GitHub Pages) с
      защитой от чужого репозитория `kern`.
- [x] Аудит программы: 55 модулей импортируются, заглушек/TODO нет; тест
      поймал и исправлен баг `preflight.video_available`; добавлены тесты
      `test_cli.py`, `test_preflight.py`, `test_speech.py` (273 теста OK).
- [x] Детальное описание поста: `build_full_description` — второе сообщение
      до 4096 знаков (рубрика → эпоха/учёный → вопрос → полный разбор без
      обрезки → код → формула → где работает → константы → тема → фундамент →
      источник → сайт → теги); подпись к карточке остаётся ≤1024.
- [x] Экскурсия `cli demo`: 5 карточек (по архетипу) + детальные описания +
      варианты для 6 соцсетей + звук/видео + служебные таблицы + PDF-книга;
      сообщения не разрезаются по HTML-тегам (fallback без разметки).
- [x] Улучшена логика архетипов: алгоритмические посты с кодом получают
      книжный листинг `code_booktabs` даже при наличии формулы.
- [x] Лестница сложности: канон расширен до **30 узлов** (10 ступеней ×
      3 дисциплины), `curriculum.complexity_tier` (1..100), приоритет
      `foundation → tier → created_at` в `choose_next`, команда
      `cli reorder-from-foundation`, источник `foundation` (weight 70).
- [x] Лекционный сценарий диктора `build_lecture_script` (без URL/тегов/эмодзи)
      + синхронные субтитры `.vtt`/`.srt` (SentenceBoundary edge-tts, при кэше —
      приблизительные).
- [x] Живой чертёж в видео-аудиограмме: 36 кадров анимации + голос +
      осциллограмма (`audiogram_for_post(animate=True)`).
- [x] 100% прямые тесты ядра: `tests/test_core_direct.py` (models/config/
      state_export), `tests/test_curriculum.py`; тесты нашли 2 недоработки
      в `config` (неизвестная площадка, отсутствие `low_water`) — исправлены.
      Итого 301 тест OK.
- [x] Фаззинг сделан герметичным (регресс-фикс): `verify.fuzz_captions` больше
      не ходит в сеть — на время прогона `translate_preserving_latex`
      подменяется тождеством, поэтому `heal()` не дёргает gtx/MyMemory.
      Раньше прогон зависал на HTTP 429 (тесты `test_fuzz_many_iterations`,
      `test_fuzz_deterministic` не завершались / были недетерминированы);
      теперь `python -m unittest discover` проходит за ~50 с. Регресс-тесты —
      `tests/test_fuzz.py::FuzzHermeticityTests`.
- [x] Приватность ПУЛЬТА: Telegram-пульт принимает команды только из админ-чата
      (`admin.py`), а Mini App (`pult.html`) по умолчанию **не публикуется** на
      сайте (`miniapp.public: false`); устаревший файл удаляется при сборке.
      Тесты — `tests/test_site.py::test_miniapp_hidden_by_default`.
- [x] Сайт: **PWA** (`manifest.webmanifest` + `sw.js` + иконки 192/512),
      **флешкарты** (`flashcards.html`), **BibTeX-экспорт** (`bibtex.bib`),
      **поиск по формулам и символам** (в индекс поиска попадают `formula_latex`
      и теги). Тесты — `tests/test_site.py` (pwa/bibtex/flashcards/symbol search).
- [x] Единый предпросмотр `cli post [--id|--domain] [--preview|--send]`:
      карточка + подпись + детальное описание без публикации; `--send` шлёт
      эталонный пост в админ-чат. Викторина `/quiz [math|physics|cs]` в пульте
      (нативный опрос Telegram). `cli clean-start --yes`: сброс состояния +
      `VACUUM` + пересборка сайта.

---

## 7. Команды

```bash
python -m science_pulse.cli init
python -m science_pulse.cli status
python -m science_pulse.cli harvest --limit 3
python -m science_pulse.cli publish --dry-run
python -m science_pulse.cli run
python -m science_pulse.cli site
python -m science_pulse.cli metrics --collect
python -m science_pulse.cli trending
python -m science_pulse.cli doctor --send
python -m science_pulse.cli invariants
python -m science_pulse.cli formal
python -m science_pulse.cli edge
python -m science_pulse.cli state
python -m science_pulse.cli state --sync
python -m science_pulse.cli admin
python -m science_pulse.cli admin --once
python -m science_pulse.cli daemon
python -m unittest discover -v
```

`--dry-run` рендерит карточку и пишет её в `data/cards/`, но не отправляет
в сеть. Это основной режим проверки без токенов.

---

## 8. Безопасность

- Токены только в `.env` / GitHub Secrets / Cloudflare Secrets; в Git не
  попадают.
- Ссылка на файл Telegram не отдаётся наружу: для Threads/сайта используется
  прокси Cloudflare Worker по `file_id`, иначе текст без картинки.
- В HTML сайта всё экранируется; формулы рендерит KaTeX, а не `eval`.
- Пользовательские выражения в калькуляторах — только через безопасный
  парсер SymPy с белым списком.

---

## 9. Фактический статус этой итерации

Проверено командами (без сети и без токенов):

```text
$ python -m unittest discover -v
Ran 153 tests
OK
```

```text
$ python -m science_pulse.cli init
$ python -m science_pulse.cli status
Очередь: 0 · Опубликовано: 0 · Ошибок: 0
```

```text
$ python -m science_pulse.cli publish --dry-run --domain math
Пост: Минимаксная аппроксимация и полином Чебышёва T_3(x) [math]
Карточка: data/cards/<id>.png
Режим dry-run: в сеть не отправлялось.
```

```text
$ python -m science_pulse.cli metrics
📊 Метрики площадок
Просмотры: 0 · Реакции: 0 · Ответы: 0 · Замеров: 0
Данных нет: запустите `metrics --collect` после публикации.
```

Сборщик метрик `science_pulse/metrics.py` проверен юнит-тестами на фейковом
HTTP: Mastodon, Bluesky, VK и Threads сохраняют замеры, Telegram/Discord
помечаются `skipped`, ошибка одной площадки не роняет сбор. Живой сбор
требует токенов площадок и не выполнялся.

Онлайн-добыча проверена 2026-11-01 на реальной сети: Stack Exchange, OEIS,
Wikipedia, arXiv, Rosetta Code и GitHub raw вернули карточки; источники
`math/physics/cs` смешиваются. `numbersapi.com` отдаёт 404/401 и по умолчанию
отключён. Telegram-публикация проверена на живом канале; Threads, Bluesky,
Discord, Mastodon и VK **не проверялись**: в среде нет их токенов. Перед
продакшеном нужны тестовые аккаунты и проверка квот площадок.

Тестовый Telegram-пост опубликован 2026-11-01:
`https://t.me/newmathphys/24` и `https://t.me/newmathphys/26` (message_id 24 и 26).
Повторный запуск без `--force` отклонён, с `--force` — `skipped: уже опубликовано`;
дубликата нет.
---

## 10. Честный аудит: что НЕ реализовано и что не работает (2026-11-04)

Проверено не по описаниям, а по коду, базе, `dist/` и живым запросам.
Ниже — **реальные пробелы**, а не «плюсы».

### 10.1. Код есть, но в рантайме не подключён

> **Обновление после аудита:** три пункта из этого списка уже закрыты —
> см. 10.1.1.

| Что | Состояние | Детали |
|:--|:--|:--|
| `hawkes_matrix`, `effective_stability` (S_eff), `review_interval_days` (FSRS) | **не используются** | формулы и тесты есть в `sota.py`; пайплайн зовёт только `check_hawkes_ready`/`record_hawkes_fire` (гейт включён, см. ниже) |
| Бандит Томпсона `select_domain_thompson` | **включён** | `selection: thompson` + `bandit.enabled: true`; награда (`sota.reward_domain`) выдаётся после каждой публикации, поэтому бандит обучается, а не «шумит» |
| Гейт Хоукса `check_hawkes_ready` | **включён** | `hawkes.enabled: true`; отказ гейта — **отложение** (`ok=True`, `deferred=True`), а не сбой: `cli run`/`cli publish` возвращают 0, CI не падает и не шлёт ложный алерт; `--force` гейт обходит |
| A/B стилей карточки | **выключен** | `abtest.enabled: false` |
| Cloudflare `edge` (R2/D1) | **не работает** | нет `CF_WORKER_URL`/`INGEST_SECRET`, `edge.d1_primary: false`; команда `cli edge` только отработает вхолостую |
| RTMP-эфир (Telegram Live / YouTube Live) | **не запускался** | `rtmp_argv()` формирует корректную команду, но ключа нет → `cli radio --rtmp … --run` не выполнялся |
| Омниканальная аналитика | **частично работает** | **Telegram — работает вживую** (публичный виджет `?embed=1`, без токена: 3 замера, 5 просмотров). Остальные площадки — 0 замеров: нет токенов |
| Публикация в Threads / Bluesky / Discord / Mastodon / VK | **не проверена на живых аккаунтах** | код есть, тесты на фейковом HTTP есть, реальных постов нет (кроме Telegram) |

### 10.1.1. Закрыто в этом аудите

| Что | Как закрыто |
|:--|:--|
| `RecursiveMetaCrawler` («источники источников») | подключён к фазе 1 ядра: `kernel.expand_deep(count, depth)` + `cli expand --deep --depth N` + `cli kernel --tick --deep`. Живой прогон: обход нашёл **821 тему** в категориях, в очередь добавлены новые посты с `meta.deep_origin` и `complexity_tier` |
| Нативные викторины Telegram (`sendPoll`) | `challenge.quiz_options()` строит 4 варианта (правильный + три числовых дистрактора ≤100 знаков), `TelegramPublisher.send_poll()` отправляет `type=quiz` в реплай к посту, пайплайн делает это сам при `telegram.quiz_poll: true`; отдельная команда `cli quiz [--send]` |
| Мобильная рамка формулы для Threads | `base.formula_frame()` рисует `┌─── 📐 ФОРМУЛА ─── / │ … / └───…` и подставляется в режиме `TEXT` (LaTeX на телефоне не рендерится) |

### 10.1.2. Проверено ВЖИВУЮ на реальном Telegram (ключи в `.env`)

| Проверка | Результат |
|:--|:--|
| `getMe` | ✓ бот `@socialcontentmanagernmpbot` («SCM») |
| `getChat @newmathphys` | ✓ канал «newmathphys.com», `type=channel`, `id=-1002600042943` |
| **Нативная викторина `sendPoll`** | ✓ админ-чат: `message_id 200`, `type=quiz`, `correct_option_id=1`, 4 варианта, `explanation` приложен |
| **Викторина в канал** | ✓ [`t.me/newmathphys/36`](https://t.me/newmathphys/36) |
| **Полная публикация поста** | ✓ § 2.2 Лейбниц → `t.me/newmathphys/37` (карточка + подпись), голосовое и полный разбор (38, 39), викторина-опрос в реплай (40); в базе `publications: telegram / 37` |
| **N+1 warm staging** | ✓ после публикации автоматически подготовлен § 2.3 (`f3ba0a10118b66cd`) |
| **Метрики Telegram** (публичный виджет, без токена) | ✓ `cli metrics --collect` → 3 замера, 5 просмотров, 2 поста |
| **Восстановление из ленты** `t.me/s/newmathphys` | ✓ § 1.1 восстановлен как `telegram / 29` (по резервному пути — заголовок); новые посты находятся по `§ X.Y` |
| Прочие площадки | skipped: «нет токенов/настроек» (Threads, Bluesky, Discord, Mastodon, VK) |



| Инструмент | Локально | Проверка |
|:--|:--|:--|
| `edge-tts` (Python-пакет в venv) | **есть, 7.3.1** | `cli voice` реально озвучил пост: `62.4 с · ru-RU-SvetlanaNeural` |
| `typst` (Python-пакет в venv) | **есть, 0.15.0** | `cli book` собрал `dist/science_pulse_book.pdf` (815 КБ, 3 поста) |
| `ffmpeg` / `ffprobe` | **есть** | микс, аудиограммы, интерлюдии |
| `lean` (elan 4.34) | **есть** | `cli formal` компилирует `formal/Invariants.lean` |
| `piper` (офлайн-синтез) | **нет** | не нужен: работает edge-tts (онлайн, без ключей) |
| Cloudflare `edge` (R2/D1) | **нет ключей** | `cli edge` → «Edge недоступен: задайте CF_WORKER_URL и INGEST_SECRET» |
| Метрики площадок | **нет токенов** | `cli metrics --collect` → «Просмотров: 0 · Замеров: 0» |
| `numbersapi.com` | **отключён** | публичный эндпоинт отдаёт 404/401 |

### 10.2.1. Как соотносятся локальная сборка и CI-сборка gh-pages

Это важно понимать: **после каждого `push` workflow `Science Pulse` сам
пересобирает сайт и публикует его в `gh-pages`, перезаписывая локальный
деплой.** Что получается в каждой среде:

| Артефакт | Локальная сборка | CI-сборка |
|:--|:--|:--|
| 30 глав канона, Диск Пуанкаре, задачи, родословная | ✓ | ✓ |
| Карточки `cards/*.png` | ✓ | ✓ (сайт дорисовывает их сам — исправлено в этом аудите) |
| `audio/*.mp3`, `audiogram/*.mp4` | ✓ | **нет** (`data/audio` в `.gitignore`) → радио в CI-сборке работает через `speechSynthesis` в браузере |
| `radio_mix.mp4` + таймкоды | ✓ (`cli radio --mix`) | **нет** (нужны аудиограммы) → ссылка скрывается |
| `science_pulse_book.pdf` | ✓ (`cli book`) | **нет** (в CI книга не собирается) |
| `podcast.xml` | ✓ (4 выпуска с `enclosure`) | ✓ (заголовок/описание; без файлов аудио) |

Вывод: **полный** сайт собирается локально; CI-сборка — «лёгкая», но
самодостаточная (звук синтезируется в браузере, карточки дорисовываются).

### 10.3. Ограничения качества (не баги, но честно)

1. **Просветительская задача**: из 30 формул канона **15** дают числовой ответ
   (`steps`/`growth`/`ratio`/`substitute`/`solve`), **15** — вопрос из крючка
   выпуска с ответом из нашего текста и флагом `verified: False` (формулы с
   `∇`, `∫`, `∑`, `∮`, `mod`, `lim` не парсятся как арифметика — выдумывать
   числа я сознательно отказался).
2. **Полный текст Википедии** попадает в главу только при **сетевом** прогоне
   ядра (`kernel --tick`); сборка сайта офлайн и детерминирована. Сейчас
   `longread_body` у 30 узлов построен офлайн из канона.
3. `numbersapi.com` отключён (404/401), источник `github_raw` выключен по
   умолчанию.
4. **GitHub Secrets** (`TG_BOT_TOKEN`, `TG_CHANNEL_ID`, `TG_ADMIN_CHAT_ID` и
   токены остальных площадок) — **не добавлены**. Ключи есть локально в `.env`,
   но `gh` CLI в системе не установлен, поэтому добавить их в репозиторий может
   только владелец (пошаговая инструкция — `docs/PROD_CHECKLIST.md`, шаг «GitHub
   Secrets»). Без секретов расписание в CI не публикует (шаги `Run pipeline`
   пропускаются на push и падают в no-op на cron).
5. Два поста с непереведёнными заголовками ждут `cli retranslate`.
6. `dist/radio_parts/` больше не создаётся (исправлено в этом аудите), но
   **сам `dist/` собирается заново при каждом деплое** — PDF-книга и `data/`
   в него не пересобираются автоматически.
7. Уведомления об ошибках: шаг `Alert operator on failure` в CI **есть** и
   отправляет сообщение в админ-чат через Telegram API, но работает только при
   заданных секретах `TG_BOT_TOKEN`/`TG_ADMIN_CHAT_ID`; локально алертов нет
   (только `/doctor` и `cli doctor` вручную).
8. Публикация из CI идёт **только по расписанию** (cron `0 6,10,14,18 * * *` =
   09/13/17/21 МСК): при обычном `push` шаги «Process operator commands» и
   «Run pipeline» намеренно пропускаются (`if: github.event_name != 'push'`),
   поэтому push пересобирает сайт, но не публикует посты.



### 10.4. Что подтверждено фактами (а не словами)

| Проверка | Результат |
|:--|:--|
| `unittest discover` | **445 тестов OK** (skipped=1) |
| `cli verify` | 🟢 инварианты (7) · Lean · фуззинг · медиа — все зелёные |
| `cli invariants` | OK, 7 проверок, 0 нарушений |
| `cli formal` | Lean 4.34 установлен, `formal/Invariants.lean` компилируется без `sorry` |
| GitHub Actions (API) | **67+ запусков**, последние — `completed success`; workflow `Science Pulse` — 28 запусков, шаги `Unit tests`, `Build site`, `Check invariants`, `Publish site to gh-pages` — все `success` (run 41882205251) |
| Живой сайт | `index.html` / `radio.html` / `podcast.xml` / `radio_mix.mp4` / `post/*.html` → **HTTP 200**; 30 глав канона с блоками задачи и родословной |
| Карточки | 9 архетипов в `ARCHETYPES`; **30/30 формул канона рендерятся** (регрессионный тест) |
| Диск Пуанкаре | `poincare.json`: 30 узлов · 46 рёбер · 30 геодезических маршрутов |
| PWA и экспорт | `sw.js`, `manifest.webmanifest`, `bibtex.bib`, `llms.txt`, `search.json`, `sitemap.xml`, флешкарты/учёные/константы — на месте |
| Очередь | ready 39 (≈9.8 дня при 4/сутки) · published 4 · failed 0 |
| Telegram вживую | публикация § 2.2 → `t.me/newmathphys/37`, викторина → `/36` и `/40`, голосовое и полный разбор → 38, 39; метрики: 5 просмотров, 3 замера |

### 10.5. Дефекты, найденные и исправленные в этом аудите

1. **Три карточки канона выходили без формулы** (§ 2.2 Лейбниц, § 6.1 Гёдель,
   § 6.3 RSA): matplotlib mathtext не знает `\land`, `\lor`, `\lnot`, `\pmod`,
   `\implies`. Добавлены переводы в `cards3b1b._mathtext_normalize` и
   регрессионный тест «все 30 формул канона обязаны рендериться» (быстрый
   `MathTextParser`, без создания фигур).
2. **CI не запускал ни одного теста**: 445 тестов существовали, но в
   `.github/workflows/science_pulse.yml` не было шага тестирования — теперь
   шаг `Unit tests` стоит сразу после установки зависимостей (проверено: run
   41882205251, шаг 5 `Unit tests` → `success`).
3. **Авто-стейджинг мог отклонить следующий пост**: первая версия вызывала
   `stage_next()` с приёмкой → `verify_and_enforce` отправлял пост в карантин
   без участия оператора (это же сломало `test_publish_and_round_robin`).
   Теперь авто-режим неразрушающий (`enforce=False, render_card=False`),
   полная приёмка — только по явной команде.
4. **`dist/radio_parts/`** (промежуточные файлы микса) попадали в деплой —
   перенесены в `data/radio_parts`.
5. **`INV-4`** считал законный статус карантина `rejected` неизвестным —
   добавлен в `KNOWN_STATUSES` (иначе инвариант падал бы после первого же
   карантина).
6. **Задача считалась повторно на каждой странице** — добавлена мемоизация
   `build_challenge` (кэш по содержимому поста), иначе 30 глав сайта гоняли
   SymPy 30 раз за сборку.
7. **Сайт уезжал без карточек на чистой виртуальной машине**: CI-сборка
   (где `data/cards/` пуст) отдавала 30 глав без картинок, а карточка
   подготовленного узла § 2.2 давала 404. Теперь `cli site` сам дорисовывает
   отсутствующие карточки (`site.render_missing_cards: true`) — это и есть
   заявленная «бессерверная живучесть».
8. **Радио-страница ссылалась на несуществующий микс**: в CI-сборке
   `radio_mix.mp4` нет, а ссылка была — теперь ссылка показывается только при
   наличии файла, иначе честная подпись «микс собирается локально».
9. **Мои собственные ошибки в первой версии этого аудита** (исправлены):
   я записал в «не работает» `edge-tts` и `typst` (оба есть в venv — проверено
   запуском `cli voice` и `cli book`), а также «нет алерта оператору» (шаг
   `Alert operator on failure` в workflow есть).
10. **Подпись не содержала `§ X.Y`** — а именно по нему восстанавливается
    состояние из публичной ленты. Проверка живой ленты показала: символов «§»
    в подписях **ноль**, поэтому `recover-from-channel` не находил ничего.
    Теперь заголовок подписи — `§ X.Y · Название`, и новые посты в ленте
    опознаются сразу (в базе § 2.2 → `telegram / 37`).
11. **Восстановление не умело работать со старыми постами** (без `§`):
    добавлен резервный путь — сопоставление по заголовку поста. Проверено
    вживую: § 1.1 восстановлен как `telegram / 29`.
12. **Метрики Telegram не собирались** только из-за отсутствия `external_id`
    у вручную открытых постов: после восстановления § 1.1 сбор дал реальные
    просмотры (5 просмотров, 3 замера, 2 поста).

### 10.6. Что делать дальше (приоритет)

1. Добавить GitHub Secrets (`TG_*`) → включить реальный автопилот по расписанию
   (тогда же заработают викторины `quiz_poll` и алерт оператору).
2. ~~Включить `hawkes.enabled: true` и `selection: thompson`~~ — **сделано**
   (`selection: thompson` + `bandit.enabled: true` + `hawkes.enabled: true`).
   Заодно отказ гейта Хоукса сделан **мягким**: `Pipeline._deferred()` возвращает
   `ok=True`/`deferred=True`, `cmd_run`/`cmd_publish` печатают «Публикация
   отложена» и возвращают 0 — шаг `Run pipeline` в CI не падает и ложный алерт
   `if: failure()` не срабатывает. Покрыто `tests/test_pipeline.py` (отложение,
   мягкость в `run()`, обход `--force`).
3. Проверить Threads/Bluesky/Discord/Mastodon/VK на тестовых аккаунтах.
4. Решить судьбу Cloudflare-контура: дать ключи `CF_WORKER_URL`/`INGEST_SECRET`
   или убрать `cli edge` из документации.
5. Собирать `radio_mix.mp4` и PDF-книгу в CI (сейчас это локальные артефакты).

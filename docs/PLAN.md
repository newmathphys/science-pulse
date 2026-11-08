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
Ran 596 tests
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
| `unittest discover` | **566 тестов OK** (skipped=2: нет `typst`) |
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
13. **«Цирк смайликов» в публичных текстах** (по замечанию заказчика: стиль
    `mokujiro.com` — японско-швейцарский минимализм без эмодзи). Из подписей
    всех площадок, карточек, страниц сайта и радио убраны декоративные
    смайлики (`❓ 🏛 💡 🧮 🔢 🔬 🧠 🔗 👇 📐 ⚛️ 💻 🪐 🎧 📻 🎲 📡` и др.).
    Подпись переведена на типографику: паспортная строка `§ X.Y · ДИСЦИПЛИНА ·
    ЭПОХА`, выровненный блок `Field: Detail` (Инвариант / Верификация /
    Первоисточник / Применение), задача выпуска и строка связей
    `← § 1.1 Пифагор · Тренажёр`. На сайте бейджи дисциплин без смайликов,
    паспорт параграфа — таблица `Field / Detail`, кэш лонгридов
    (`meta["longread_body"]`) чистится при рендере (`_strip_marketing_emoji`).
    Проверка: тест `test_caption_has_no_marketing_emojis` + сквозной скан
    `dist/` (0 эмодзи в 36 публичных HTML).
14. **Неарифметические формулы рисовались случайной кривой**: 4 узла канона
    (Максвелл `∇`, Архимед `∮`, Фурье `∑`, Пифагор в форме нормы) уходили в
    `standard_plot` и получали дефолтную синусоиду. Теперь при наличии
    операторов `∇ ∫ ∮ ∑ ∏ lim mod` и невозможности разобрать формулу как
    `y = f(x)` архетип детерминированно переключается на `cheatsheet_table`.
15. **Дизайн выпуска был жёстко зашит** (`card.theme: "neon"`): добавлен реестр
    `themes.py` (academic / 3b1b / blueprint / moku3d), режим `auto` с бандитом
    Томпсона и правилом разнообразия, запись `meta["design_variant"]` и рейтинг
    `/theme` (`/ab`) в Пульта. Инженерный дизайн `blueprint` — перекраска
    книжной вёрстки в синюю миллиметровку со штампом ГОСТ/IEEE.
16. **Кинематографический движок `moku_film.py`** (референс Moku3D,
    `mokujiro.com`): 30-секундный фильм из 5 актов, ровно одна строка смысла на
    акт, вычисляемая геометрия (устойчивая «восьмёрка» трёх тел, 3D-кривая
    Фурье с переключением гармоник `n = 1 → 3`, решётка алгоритма), 3D-камера с
    облётом, HUD `STUDY § X.Y` и счётчик, сборка `ffmpeg` со звуком `sound.py`,
    команды `cli film` и `/film`, блок `<video>` на странице параграфа.
17. **Задачи канона: было 15/30 `verified`, стало 30/30.** Настоящая причина
    отказов — кэш задач (`_challenge_key`) **терял `meta`**: при восстановлении
    поста из ключа исчезали `canon_id`/`foundation_id`, поэтому реестр
    вычислимых законов не находил узел. Ключ и восстановление исправлены.
    Добавлены 12 точных вычислимых задач (`CANON_COMPUTABLE`: Архимед, Булева
    логика, Ньютон, Бернулли-Лавлейс, Фурье, Нётер, Тьюринг, Дейкстра, Гёдель,
    RSA, Максвелл, Леннард-Джонс) и стратегия `_numeric_proof_challenge`
    (числовая задача из эталонного `computed_example`). Ответы считает код.
18. **Психология ленты: `post_modes.py`** — задача больше не в каждом посте.
    Пять режимов (`pure_knowledge` 6 · `satellite_lab` 2 · `cheatsheet_save` 1 ·
    `moku3d_film` 1 · `interactive_challenge` 1), `challenge_every_nth: 5`
    (сейчас 4 — см. п. 24),
    детерминированная ротация без случайности; режим пишется в
    `meta["post_mode"]`.
19. **Спойлер самопроверки и инструменты подключения соцсетей.** В Telegram
    ответ на задачу спрятан под `<tg-spoiler>`, в Threads уходит отдельным
    сообщением цепочки, в Bluesky/Mastodon — строкой в конце. Добавлены
    `authcheck.py` (`/auth`, `cli auth-check` — read-only пинг 6 площадок) и
    `sync.py` (`/sync`, `cli sync-platform` — догоняющая синхронизация строго с
    § 1.1). Проверено вживую: Telegram 🟢 (права админа канала), для Threads/VK
    найдено 4 пропущенных параграфа, начиная с § 1.1.
20. **Живые датчики Планеты и Космоса без ключей (`live_sensors.py`).** Четыре
    открытых JSON-API (USGS Earthquakes, NOAA SWPC Kp, LIGO GWOSC, WhereTheISS.at)
    с таймаутом 2.5 с, кэшем 10 минут и детерминированным офлайн-фоллбэком.
    Реальное сегодняшнее число подставляется в формулу выпуска
    (`lg E = 4.8 + 1.5M`, `F = q(v×B)`, `E = Δm·c²`, `g(h) = GM⊕/(R⊕+h)²`) и
    выводится отдельным полем `Живой датчик:`. Команды `cli sensors` и
    `cli sensors --json`; датчики включаются конфигом (`live_sensors.enabled`) и
    выключены по умолчанию в коде, чтобы тесты не ходили в сеть.
21. **Шесть лабораторных стендов (`simulate.py` + `sound.py` + `live_sensors.py`).**
    `cern_dimuon` (инвариантная масса и Брейт — Вигнер: пик 90.6 ГэВ при 91.19),
    `ligo_chirp` (чирп 35→250 Гц, фильтр Баттерворта, спектрограмма и
    **акустический чирп в `sound.py`** — проверено БПФ: 36→164 Гц),
    `voronoi_laplacian` (Вороной/Делоне и число Фидлера λ₂ = 1.042),
    `sat_tsp` (фазовый переход 3-SAT при α ≈ 4.26 и маршрут 2-opt),
    `sparse_cg` (CSR 1.49 % плотности, невязка CG → 0 против градиентного спуска),
    `seismic_ps` (триангуляция P/S: Δt = 10 с → 84 км). Каждый стенд получил
    диптих в `cards_academic` (6 новых архетипов чертежа) и численные тесты
    (`tests/test_labs.py`, 16 проверок). Живые данные дополнены P/S-задержкой и
    вектором Bz (NOAA magnetometer, деградирует без сети).

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
22. **4-уровневый календарь (`rituals.py`).** Суточные слоты (`schedule_slots`:
    09:00 math · 13:00 cs · 17:00 physics · 21:00 satellite_lab) передаются
    пайплайну как дисциплина выпуска; событийный слой — «Молния науки» по порогу
    `trending.auto_publish_min_likes: 350`; недельные ритуалы — пятничная викторина
    `sendPoll`, субботняя шпаргалка + `radio_mix.mp4`, воскресная PDF-книга +
    бэкап + сводка `/ab`; месячная профилактика 1-го числа — продление токена
    Threads, `VACUUM` + очистка медиа (`media.keep_last`), паспорт Атласа.
    Идемпотентность через `kv`-метки (неделя `YYYY-Www`, месяц `YYYY-MM`):
    повторный запуск ничего не дублирует. Команды `cli rituals [--dry-run]`,
    фоновый демон вызывает ритуалы после каждого слота. Тесты
    `tests/test_multi_horizon_schedule.py` (15 проверок).
23. **Проверка трёх противоречий расписания (найдены заказчиком, подтверждены
    фактами).** (1) Закон причинности: `curriculum.prereqs_open` + гейт в
    `Pipeline.choose_next` — пост выходит только после публикации родителей
    (`prereq_ids`); на боевой базе из 39 готовых постов проходят 6, стенды
    (§ 6.4 InSAR, § 6.5 Шварцшильд) больше не обгоняют фундамент. (2) Наложение
    постов в 21:00: `rituals.evening_kind`/`publishes_post` — Пн–Чт вечер даёт
    стенд/фильм, Пт — викторину, Сб — шпаргалку, Вс — книгу; обычный пост в
    эти вечера не публикуется, двух сообщений в одну минуту нет. (3) Ссылки:
    `SP_SITE_BASE_URL` по умолчанию `https://newmathphys.github.io/science-pulse`,
    ссылка в посте и QR-код 68×68 ведут на `post/<id>.html` (уже работало).
    Тесты: `tests/test_multi_horizon_schedule.py` (24 проверки, включая
    причинность и вечернюю ротацию).
24. **Закрытие остатков: частота задач, вертикальный формат, спутниковые стенды.**
    (1) `challenge_every_nth` снижен `5 → 4` (в `config.yaml` и в дефолте
    `post_modes.settings`) — задача выпуска выходит чаще, но по-прежнему не в
    каждом посте; синхронизированы `docs/POST_MODES.md`.
    (2) Формат кадра фильма: `frame_size(size, aspect)` + `moku3d.aspect`
    (`1:1` | `9:16`) и `cli film --aspect 9:16`. Проекция, штамп и линия акта
    переведены с квадратного `size` на `width`/`height`, кегли и отступы — от
    `min(width, height)`; обе стороны чётные (требование `yuv420p`). Проверено
    живьём: `480×854` (h264) из `size: 480`, вертикальный PNG `144×256` в тесте.
    (3) Четыре спутниковые лаборатории в `simulate.py` + 4 диптиха в
    `cards_academic` (+4 имени в `SIMULATIONS`): `ocean_altimetry` (модель
    Брауна, размах топографии 39.6 м), `grace_geoid` (сферические гармоники
    Лежандра, амплитуда нормирована к реальным ±100 м), `wind_field`
    (оптический поток GOES/Meteosat: `∇·v = 0` с точностью до машинной,
    `ζmax = 35.5`), `mercury_precession` (Верле + ОТО: **43.0″/век** против
    наблюдаемых 43″; в ньютоновском поле перигелий не дрейфует — `−0.12″` за
    оборот остаточного шума). Тесты `tests/test_labs.py` (25 проверок),
    `tests/test_moku_film.py` (12 проверок).
25. **Сквозной аудит: статика, логика, функциональный прогон, ресурсы.** Проверено
    без допущений. Статика: 76 модулей импортируются, AST-заглушек нет, все 48
    CLI-команд отвечают на `--help`, 151 ключ конфига читается кодом, 24
    env-переменные описаны, 31 документ в таблице README, 104 ссылки на файлы
    живые, 46 команд Пульта имеют обработчики (4 алиаса — отдельной строкой
    «Алиасы»). Функционально: 47 команд отработали вживую, единственный «отказ» —
    `preflight` честно сообщает про отсутствующий `edge-tts`; сайт и радио
    собираются, `book` корректно деградирует без `typst`. Логика на живой базе:
    все 30 задач канона `verified` (12 — через реестр `canon_computable`),
    причинность пускает 6 постов из 39 (режет 33), режимы дают задачу не реже
    каждого 4-го выпуска, вечера Пт/Сб/Вс отданы ритуалам, в 36 страницах
    публичного HTML 0 эмодзи, ответ под `<tg-spoiler>`, опросы собираются для
    27 узлов из 30 (три качественные задачи вариантов не выдумывают). Ресурсы:
    **утечек нет** — фигуры matplotlib закрываются (`plt.get_fignums()` = 0 после
    каждого рендера), RSS выходит на плато (+8 КБ на рендер), 12 fd — это разово
    открытый font-cache matplotlib, `Storage` держит соединение только на время
    операции (закрывается в `finally`), демон переиспользует один `Pipeline`.
    48 предупреждений `unclosed database` в логе — внутренний кэш шрифтов
    matplotlib (`transforms.py` → `pyparsing`), не наш код.
    Найдено и закрыто: удалять `Post.emoji` было нельзя (используется в чате
    оператора — регрессия поймана тестами и откачена), добавлены тесты для
    `arxiv` и `cards_blueprint` (12 новых), описаны `cli backup` и служебные
    `SP_*`/алиасы, синхронизированы устаревшие числа тестов в docs.

26. **Почему «пропал голос»: диагноз и защита от залипания кэша.** Голос не
    ломался в коде — из окружения пропал пакет `edge-tts`: он объявлен в
    `requirements.txt` (CI его ставит), но в песочнице Python 3.14 остался без
    `pip` и user-site, хотя реальные озвучки от 03–04.11 лежат в `data/audio/`
    (48 кбит/с, до 123 с). Восстановлено через `uv pip install --python python3
    --target <user-site>`; живой синтез подтверждён: `ru-RU-SvetlanaNeural`,
    54.9 с, 48 кбит/с, `cli preflight` → 🟢 «edge-tts/piper готов» и «✅ готов к
    публикации» (было 🔴 и «⛔ есть блокеры»). Заодно найден и закрыт реальный
    дефект: фоллбэк-сонификация писала `<id>.key`, то есть «неправильный» звук
    маскировался под кэш настоящей речи — на посте «Ньютон: закон всемирного
    тяготения» лежало 3 с сонификации вместо 57.5 с голоса. Теперь фоллбэк ключ
    не пишет и снимает старый, поэтому возвращение движка само возвращает голос.
    Тесты `tests/test_voice.py` (15 проверок, включая «фоллбэк не отравляет
    кэш»), диагностика и чистка описаны в `docs/VOICE.md`.

27. **Живая доставка ботом и симуляция 40 дней (строгая проверка).** Бот
    `@socialcontentmanagernmpbot` — администратор канала `@newmathphys`: проверено
    `getMe`/`getChat`/`getChatMember`. В админ-чат доставлен полный пакет выпуска:
    карточка + подпись 839 знаков, голос 54.9 с (`ru-RU-SvetlanaNeural`),
    видео-аудиограмма 628 КБ, нативный опрос — задача `canon_computable`,
    ответ проверен кодом. В канал опубликован пост «Аль-Хорезми» (викторина 44,
    авто-стейджинг N+1). Симуляция 40 дней (160 тиков, изолированная база,
    подменённый публикатор, часы симуляции): 111 публикаций, 0 дублей, причинность
    держится, ритуалы 7/6/6 + месячная профилактика ровно 1, в подписях 0 эмодзи,
    максимум 1020 знаков, 43 опроса, 0 сбоев публикации. Симуляция вскрыла и
    заставила исправить: (а) `StandardsChecker` держал `card_size = 1080` отдельно
    от `config.card.size` — смена размера в конфиге отправляла в карантин КАЖДЫЙ
    пост; теперь размер берётся из конфига; (б) подпись показывала сырой sympy
    (`x**6*besselj(0, x)`) — добавлена человекочитаемая математика (`x⁶·J₀(x)`);
    (в) «точный расчёт» печатал `x(0) = nan`, а `_numeric_proof_challenge`
    помечал такой ответ `verified: True` — теперь неопределённые точки
    пропускаются, а `nan/inf` не могут стать проверяемой задачей; (г) Бернулли и
    Шрёдингер получили настоящие вычисляемые следствия (152 кПа; 3.31·10⁻¹⁹ Дж ≈
    2.07 эВ) вместо `nan`; (д) из тела офлайн-постов убран нерелевантный
    «Эталон CODATA» (константа выбиралась по индексу эпохи) и убрана слепая
    обрезка производной на 110 знаках, из-за которой пост уходил в карантин;
    (е) счётчик режимов растёт на каждом выпуске, поэтому обещанный интервал
    «задача не реже 4-го» больше не растягивается до 7. Тесты: 578 OK
    (skipped=2 — нет `typst`). Ограничения среды, найденные симуляцией:
    `edge-tts` и `deep-translator` объявлены в `requirements.txt`, но в песочнице
    их не было (голос восстановлен, перевод из среды недоступен) — из-за этого
    англоязычные посты из сети уходят в карантин по кириллице (<42%).



## 10. Signal Engine и Book Film (2026-11)

Добавлены:

- `science_pulse/signal_engine.py` — 5 законов книги Зюко–Кловского–Финка:
  объём сигнала, энтропия/избыточность, РОС/УОС, Нейман–Пирсон + Калман,
  ортогональные интервалы;
- интеграции: `preflight`, `pipeline`, `kernel`, `metrics`, `trending`,
  `scheduler`, `themes`, `admin`, `cli`, `voice`;
- `science_pulse/book_film.py` — светлый книжный фильм с подсветкой слов;
- `simulate.kotelnikov_sampling`, `simulate.shannon_capacity`,
  `simulate.hamming_7_4`;
- Lean-теоремы `hamming_7_4_orthogonal`, `sample_count`, `capacity_monotone`;
- страница «Основные обозначения» в `book.py`.

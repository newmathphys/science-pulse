# Архитектура SCM / Science Pulse

**Версия:** 2026-11-09.  
Документ описывает, как устроен проект целиком: слои, модули, потоки данных,
публикацию, медиа, проверки, деплой и точки расширения. Это карта для оператора
и разработчика: где что лежит и что менять, не ломая остальное.

## 1. Что такое SCM

SCM (Scientific Content Machine) — детерминированная машина научного контента:

```text
открытые источники
  → проверяемое знание
  → пост + карточка + видео + голос
  → Telegram / Threads / сайт
  → метрики
  → обратная связь
```

Главный принцип: **контент не генерируется LLM**. Текст берётся из источников
и канона, формулы проверяются, картинки/видео рисуются кодом. LLM может быть
подключён только отдельным выключенным плагином в будущем.

## 2. Слои

```text
┌──────────────────────────────────────────────────────────────┐
│ 0. Вход оператора: ./sp, CLI, Telegram-пульт, Mini App       │
├──────────────────────────────────────────────────────────────┤
│ 1. Добыча: sources/, enricher, canon_gate, standards         │
├──────────────────────────────────────────────────────────────┤
│ 2. Состояние: storage.py, SQLite, knowledge.py, D1/R2         │
├──────────────────────────────────────────────────────────────┤
│ 3. Производство: text, cards, video, voice, explainer_film    │
├──────────────────────────────────────────────────────────────┤
│ 4. Публикация: publishers/, manager, sync, metrics           │
├──────────────────────────────────────────────────────────────┤
│ 5. Сайт: site.py, graph, radio, miniapp                      │
├──────────────────────────────────────────────────────────────┤
│ 6. Управление: pipeline, scheduler, rituals, kernel, admin   │
├──────────────────────────────────────────────────────────────┤
│ 7. Контроль: invariants, formal, verify, no_llm, watch       │
└──────────────────────────────────────────────────────────────┘
```

## 3. Полный поток одного поста

```text
sources/*.fetch()
  → Post (models.py)
  → storage.add_post() + seen (дедупликация)
  → canon_gate / standards (7 рубежей)
  → preflight (карточка, сигнал, готовность)
  → pipeline.choose_next()
  → themes / post_modes / signal_engine
  → render_card / video / voice / explainer
  → publishers/manager.publish()
       Telegram → file_id
       Threads  → image_url = CF_WORKER_URL/tg-cdn/<file_id>.png
       Bluesky / Discord / Mastodon / VK
  → storage.record_publication()
  → site.build()
  → metrics.collect()
  → growth / audience / watch
```

Порядок площадок фиксирован: **Telegram → Threads → Bluesky → Discord →
Mastodon → VK**. Telegram идёт первым, потому что отдаёт `file_id` картинки.

## 4. Модули: что за что отвечает

### 4.1. Вход и управление

| Модуль | Роль |
|:--|:--|
| `cli.py` | все команды `python -m science_pulse.cli ...` |
| `sp` | короткий вход оператора: `enter/check/next/watch/videos/...` |
| `admin.py` | Telegram-пульт: команды, кнопки, doctor, film, voice |
| `pipeline.py` | сборка одного выпуска: harvest → выбор → медиа → publish |
| `scheduler.py` | локальный daemon по расписанию |
| `rituals.py` | Пт/Сб/Вс и 1-е число: квиз, шпаргалка, книга, обслуживание |
| `kernel.py` | 6-фазное ядро: паспорт, цикл, расширение курса |
| `config.py` | `config.yaml` + `.env`, пути, платформы, голос |
| `demo.py` | экскурсия по системе в админ-чат |

### 4.2. Источники и качество

| Модуль | Роль |
|:--|:--|
| `sources/history_canon.py` | 30 узлов канона: текст, формула, эпоха, первоисточник |
| `sources/foundation.py` | ступени фундамента, порядок публикации |
| `sources/wikipedia.py` | ru-wikipedia |
| `sources/stackexchange.py` | Stack Exchange |
| `sources/arxiv.py` | arXiv |
| `sources/oeis.py` | OEIS |
| `sources/rosetta.py` | Rosetta Code |
| `sources/github_raw.py` | проверенные raw-README |
| `sources/numbers.py` | Numbers API (отключён) |
| `sources/offline.py` | офлайн-бункер SymPy + SciPy CODATA |
| `sources/curriculum_crawler.py` | учебный курс |
| `sources/manager.py` | порядок источников, circuit breaker |
| `enricher.py` | длинный разбор из данных поста |
| `canon_gate.py` | двухпроходная приёмка канона |
| `standards.py` | 7 рубежей качества, heal, quarantine |
| `preflight.py` | предполётная проверка следующего поста |

### 4.3. Состояние

| Модуль | Роль |
|:--|:--|
| `storage.py` | SQLite: posts/publications/metrics/sources/kv/seen |
| `models.py` | Post, CardArtifact, PublishResult, лимиты |
| `knowledge.py` | `data/knowledge.db`: документы, FTS, утверждения, решения |
| `state_export.py` | SQL-дамп и реплика состояния |
| `edge.py` | R2/D1 через Cloudflare Worker |
| `sync.py` | догоняющая публикация пропущенной летописи |
| `recovery.py` | восстановление из публичной ленты Telegram |

### 4.4. Текст и формулы

| Модуль | Роль |
|:--|:--|
| `text.py` | очистка, LaTeX→Unicode, нарезка, перевод gtx/MyMemory |
| `plotting.py` | кривые и графики для карточек |
| `challenge.py` | задача выпуска, ответ, самопроверка |
| `post_proof.py` | вычислительный паспорт |
| `constants.py` | CODATA-константы |

### 4.5. Медиа

| Модуль | Роль |
|:--|:--|
| `cards.py` | диспетчер карточек |
| `cards_academic.py` | книжная академическая карточка |
| `cards3b1b.py` | тёмный чертёж 3Blue1Brown |
| `cards_blueprint.py` | инженерный blueprint |
| `video.py` | 3.6-секундное микро-видео + сонификация |
| `sound.py` | детерминированный звук формул (NumPy/wave) |
| `voice.py` | адаптивная озвучка: edge → piper → google → espeak → sonification |
| `book_film.py` | светлый книжный 5-актовый фильм |
| `moku_film.py` | тёмный 5-актовый Moku3D |
| `explainer_film.py` | инфографический explainer в стиле «Закон Амдала» |
| `video_registry.py` | реестр сгенерированных видео |
| `book.py` | PDF-книга через Typst |

### 4.6. Публикация

| Модуль | Роль |
|:--|:--|
| `publishers/base.py` | общий текст, формулы, рамки, PublishContext |
| `publishers/manager.py` | порядок площадок, идемпотентность, file_id → CF |
| `publishers/telegram.py` | фото/видео/голос/аудио, опросы, file_id |
| `publishers/threads.py` | контейнер → publish, IMAGE/TEXT, growth-цепочка |
| `publishers/bluesky.py` | blob upload + createRecord |
| `publishers/discord.py` | webhook/embed |
| `publishers/mastodon.py` | media + status |
| `publishers/vk.py` | wall.post + upload |
| `metrics.py` | сбор просмотров/реакций/ответов |
| `audience.py` | подписчики Telegram/Threads |
| `growth.py` | Threads-форматы, UTM, реестр каналов |
| `authcheck.py` | read-only проверка ключей |
| `release_check.py` | `./sp next`: Threads + Cloudflare |

### 4.7. Сайт и знания

| Модуль | Роль |
|:--|:--|
| `site.py` | статический сайт: посты, карточки, поиск, sitemap, llms.txt |
| `graph.py` | PageRank и диск Пуанкаре |
| `radio.py` | научное радио/подкаст |
| `curriculum.py` | порядок курса |
| `syllabus_tree.py` | дерево тем |
| `themes.py` | реестр дизайнов и бандит Томпсона |
| `abtest.py` | A/B-варианты |
| `post_modes.py` | режимы подачи |
| `live_sensors.py` | живые датчики без ключей |

### 4.8. Контроль и наблюдаемость

| Модуль | Роль |
|:--|:--|
| `invariants.py` | INV-1…INV-7 |
| `formal.py` | Lean 4 |
| `verify.py` | `cli verify`: no_llm, инварианты, Lean, фуззинг, медиа |
| `no_llm.py` | AST-аудит: нет LLM-импортов/API |
| `platform_watch.py` | еженедельный changelog-мониторинг |
| `signal_engine.py` | 5 законов: объём, энтропия, УОС/РОС, Нейман—Пирсон, Котельников |
| `sota.py` | алгоритмы после MVP |
| `platforms_info.py` | лимиты и правила площадок |

## 5. Данные

### 5.1. SQLite `data/science.db`

```text
posts            — очередь и опубликованные посты
publications     — идемпотентность (post_id, platform)
metrics          — просмотры/реакции/ответы
sources          — здоровье источников, circuit breaker
kv               — состояние: темы, токены-метки, ритуалы
seen             — дедупликация (hash, simhash, title/body)
```

### 5.2. `data/knowledge.db`

```text
documents        — docs/*.md и другие документы
documents_fts    — FTS5-поиск
claims           — утверждения
notes            — заметки
decisions        — решения
concepts/links   — граф понятий
metrics          — метрики знаний
```

### 5.3. Файлы состояния

```text
data/science.db             — основная очередь
data/knowledge.db           — база знаний
data/growth.db              — аудитория/каналы
data/platform_watch.json    — снимок changelog'ов
data/video_registry.json    — реестр видео
data/audio/voice_health.json — cooldown TTS
data/cards/                 — PNG-карточки
data/audio/                 — MP3/OGG/VTT/SRT
data/explainer_films/       — explainer MP4
data/book_films/            — book MP4
data/films/                 — Moku3D MP4
```

## 6. Публикация: точная последовательность

```text
1. pipeline.choose_next()
2. render_card(post)
3. preflight / canon_gate / standards
4. PublisherManager.publish()
   for platform in ORDER:
     Telegram:
       sendPhoto → file_id
       storage.set_card_file_id()
       context.public_card_url = CF_WORKER_URL/tg-cdn/<file_id>.png
     Threads:
       image_mode = cloudflare | site | text
       POST /v1.0/{user}/threads
       wait status FINISHED/PUBLISHED
       POST /v1.0/{user}/threads_publish
     Bluesky / Discord / Mastodon / VK
5. storage.record_publication()
6. checkpoint WAL
7. site.build()
8. metrics.collect()
```

Идемпотентность: `publications UNIQUE(post_id, platform)`. Повторный запуск
даёт `skipped`, а не дубль.

## 7. Медиа-конвейер

### Карточки

```text
Post → cards.py (theme)
  → cards_academic / cards3b1b / cards_blueprint
  → PNG 1080×1080
```

### Микро-видео

```text
Post → video.py: 30 кадров matplotlib + sound.py
  → ffmpeg H.264/AAC MP4
  → Telegram sendVideo
```

### Голос

```text
Post → voice.py
  edge (Светлана) → piper (офлайн ONNX) → google_tts → espeak → sonification
  cooldown в data/audio/voice_health.json
  кэш по движку: <id>.<engine>.mp3
  субтитры: VTT/SRT
```

### Book-фильм

```text
Post → book_film.py: 5 актов, книжная страница
  → voice.film_voice_for_post() или sonify
  → ffmpeg MP4 1:1 / 9:16
```

### Explainer-фильм

```text
Post → explainer_film.py
  5 сцен: парадокс → паспорт → формула → waffle 5×8 → вывод
  HUD: прогресс, сцена, множитель
  бегущий счётчик формулы
  караоке-субтитры с плашкой
  → ffmpeg MP4 1:1 / 9:16
```

## 8. Текст, перевод и языки

- Контент берётся из источников/канона.
- `translate: true` включает перевод англоязычных источников на русский через
  `gtx → MyMemory → deep-translator`. Это **не LLM**.
- Формулы и код защищены от перевода (`mask_protected`).
- LLM не используется; `no_llm` проверяет AST пакета.
- RU/EN-раздел сайта — отдельная задача: пары `ru/en` без машинного перевода
  или с явно включённым переводчиком.

## 9. Сигнальный движок

`signal_engine.py`:

1. объём сигнала `Vc = Tc · Fc · Hc ≤ Vk`;
2. энтропия/избыточность Шеннона;
3. УОС/РОС (адаптивная мощность);
4. Нейман—Пирсон + Калман (фильтр трендов);
5. защитные интервалы и шаг Котельникова.

Используется в `preflight`, `pipeline`, `kernel`, `trending`, `metrics`,
`themes`, `voice`, `book_film`, `explainer_film`.

## 10. Сайт

`site.py` собирает `dist/`:

```text
index.html, post/<id>.html, cards/, audio/, graph.json,
search.json, sitemap.xml, llms.txt, llms-full.txt,
radio.html, pult.html (Mini App), book.pdf
```

Деплой: GitHub Actions → ветка `gh-pages` → GitHub Pages.

## 11. Расписание и автономность

```text
09:00 math
13:00 cs
17:00 physics
21:00 satellite_lab / ритуал
```

- GitHub Actions: cron 4 раза в день, публикация + сайт.
- Локально: `./sp daemon` / systemd timer.
- Ритуалы: Пт — квиз, Сб — шпаргалка, Вс — книга, 1-е — обслуживание.
- Неделя: `platform_watch.yml` — changelog'и API.

## 12. Контроль качества

```text
./sp check
  → unittest discover
  → cli verify
      no_llm
      invariants
      Lean
      fuzz
      media smoke
  → preflight
  → knowledge index
  → knowledge integrity
```

7 рубежей `standards.py`: кириллица, длина, LaTeX, скобки, AST кода,
карточка, HTML. Плохой пост → `rejected`, не публикуется.

## 13. Конфигурация и секреты

| Где | Что |
|:--|:--|
| `config.yaml` | несекретные настройки: расписание, лимиты, голос, темы |
| `.env` | локальные секреты |
| GitHub Secrets | секреты CI |
| Cloudflare Worker secrets | `TG_BOT_TOKEN`, `INGEST_SECRET` |
| `data/` | состояние, медиа, реестры |

Секреты не коммитятся. `.env` в `.gitignore`.

## 14. Деплой

```text
git push main
  → GitHub Actions
  → tests / verify
  → publish pipeline (если не push)
  → site build
  → gh-pages
  → GitHub Pages
```

Cloudflare Worker деплоится отдельно:

```bash
cd cloudflare
wrangler deploy
```

## 15. Что менять при изменениях

| Изменение | Файлы |
|:--|:--|
| Новый источник | `sources/`, `sources/manager.py`, `config.yaml`, тесты |
| Новый дизайн карточки | `cards*.py`, `themes.py`, `pipeline.py` |
| Новый видео-стиль | `*_film.py`, `cli.py`, `admin.py`, `themes.py` |
| Новый TTS | `voice.py`, `config.yaml`, `docs/VOICE.md` |
| Новая площадка | `publishers/`, `manager.py`, `authcheck.py`, `metrics.py` |
| Новый API-ключ | `.env.example`, `docs/INTEGRATIONS.md`, CI secrets |
| Новый инвариант | `invariants.py`, `formal/Invariants.lean`, `verify.py` |
| Новый changelog | `platform_watch.py`, `docs/PLATFORM_WATCH.md` |

## 16. Ограничения текущей версии

- Threads: нет токена; код и Cloudflare готовы.
- R2 не включён; `/tg-cdn` работает без него.
- Bluesky/Discord/Mastodon/VK: нет ключей.
- LLM: не подключён; только будущий плагин.
- RU/EN-пары: не сделаны; переводчик включён для источников.
- Коммерческая ветка: после релиза.
- Mini App: статическая страница.
- RTMP/радио: не запущено в эфир.

## 17. Связанные документы

- `docs/SCM.md` — парадигма.
- `docs/INTEGRATIONS.md` — API и ключи.
- `docs/PLATFORMS.md` — площадки и лимиты.
- `docs/VOICE.md` — голос.
- `docs/VIDEO.md` — видео.
- `docs/PLATFORM_WATCH.md` — мониторинг API.
- `docs/RUNBOOKS.md` — эксплуатация.
- `docs/SECURITY.md` — секреты.

# Science Pulse

**SCM — Scientific Content Machine** — детерминированная машина научного
контента: источники → проверяемое знание → публикация → сайт → метрики →
коммерческая ветка. SCM — ветка экосистемы; RII, AI Connector, KERN, NYUUI и
Эмбрион-Симбиот используются как оракулы и поставщики знаний, но их код здесь
не меняется.

Вход оператора: `./sp enter` · карта документации: `docs/INDEX.md` ·
парадигма: `docs/SCM.md` · база знаний: `docs/KNOWLEDGE_BASE.md`.

Детерминированная фабрика научного контента по мотивам документа
`2-2026-10-31.md`: математика, физика и информатика — 4 публикации в сутки
(09:00, 13:00, 17:00 и 21:00 МСК) в Telegram, Threads и другие сети, с карточками 1080×1080, формулами,
графиками и растущим сайтом.

**Главный принцип: в контенте нет LLM.** Текст берётся из открытых
источников, перевод по умолчанию выключен, картинка рисуется кодом, публикация
идемпотентна. Это не декларация: `cli verify` сканирует пакет и падает, если
появится LLM-импорт, адрес генеративного API или включённый перевод. Если сеть
и API недоступны, работает офлайн-бункер на SymPy + SciPy CODATA.

## Быстрый старт (без токенов)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env      # можно оставить пустым для dry-run
python -m science_pulse.cli init
python -m science_pulse.cli run --dry-run
python -m science_pulse.cli site
```

`run --dry-run`:
1. пробует онлайн-источники (если сети нет — падает в офлайн-бункер);
2. кладёт пост в SQLite;
3. рисует карточку в `data/cards/`;
4. **не отправляет** ничего в сеть;
5. собирает сайт в `dist/`.

Откройте `dist/index.html` в браузере.

## Подключение площадок

Подробная пошаговая инструкция — `docs/TOKENS.md`. Заполните `.env` (или GitHub Secrets). Площадки включаются автоматически,
когда появляются их переменные.

Возможности, лимиты и нюансы каждой площадки (что умеет, что режем, где
какие ловушки, кто отдаёт метрики) — в `docs/PLATFORMS.md`.

| Площадка | Переменные | Где взять |
|:--|:--|:--|
| Telegram | `TG_BOT_TOKEN`, `TG_CHANNEL_ID`, `TG_ADMIN_CHAT_ID` | @BotFather; канал → администраторы → бот |
| Threads | `TH_USER_ID`, `TH_ACCESS_TOKEN` | developers.facebook.com → Threads API |
| Bluesky | `BLUESKY_HANDLE`, `BLUESKY_APP_PASSWORD` | bsky.app → Settings → App Passwords |
| Discord | `DISCORD_WEBHOOK_URL` | канал → Integrations → Webhooks |
| Mastodon | `MASTODON_INSTANCE`, `MASTODON_ACCESS_TOKEN` | Preferences → Development |
| VK | `VK_GROUP_ID`, `VK_ACCESS_TOKEN` | vkhost.github.io (права wall/photos/groups) |
| Cloudflare CDN | `CF_WORKER_URL` | `cloudflare/worker.js` + Secrets |

Переменные-алиасы (если так удобнее): `TELEGRAM_BOT_TOKEN` = `TG_BOT_TOKEN`,
`THREADS_ACCESS_TOKEN` = `TH_ACCESS_TOKEN`, `THREADS_USER_ID` = `TH_USER_ID`.

Служебные переопределения (не секреты, полезны в CI и в контейнерах):

| Переменная | Что меняет | По умолчанию |
|:--|:--|:--|
| `SP_DATA_DIR` | каталог данных (база, карточки, медиа) | `data` |
| `SP_DIST_DIR` | каталог собранного сайта | `dist` |
| `SP_SITE_BASE_URL` | базовый адрес сайта в ссылках и QR | определяется из `git remote` |
| `SP_SITE_TITLE` | заголовок сайта | `Science Pulse` |
| `SP_SCHEDULE` | список слотов расписания через запятую | из `config.yaml` |
| `SP_TRANSLATE` | `1` — перевод англоязычных источников | включён |

Threads принимает картинку только по публичному URL. Если `CF_WORKER_URL`
задан, используется безопасный прокси Telegram CDN по `file_id` (токен бота
наружу не попадает). Если прокси нет — Threads получает текстовый пост.

## Команды

```bash
python -m science_pulse.cli init
python -m science_pulse.cli knowledge index
python -m science_pulse.cli knowledge search "SCM"
python -m science_pulse.cli knowledge stats
python -m science_pulse.cli knowledge integrity
python -m science_pulse.cli status [--json]
python -m science_pulse.cli harvest --limit 3 [--domain physics] [--offline]
python -m science_pulse.cli publish [--dry-run] [--domain math] [--target telegram]
python -m science_pulse.cli retranslate     # перевод очереди на русский (gtx)
python -m science_pulse.cli drop --english  # удалить непереведённые/мусорные посты
python -m science_pulse.cli recard          # перерисовать карточки вышедших постов в канале
python -m science_pulse.cli run [--dry-run]
python -m science_pulse.cli site
python -m science_pulse.cli sources
python -m science_pulse.cli metrics --collect  # метрики площадок
python -m science_pulse.cli trending    # 🔥 радар мировых новостей (HN + GitHub)
python -m science_pulse.cli doctor      # 🚦 светофор автономности (--send в чат)
python -m science_pulse.cli theme       # дизайн выпуска: A/B-рейтинг (auto|academic|3b1b|blueprint|moku3d)
python -m science_pulse.cli film        # 5-актовый фильм Moku3D (--post-id ID --domain math --aspect 1:1 --send)
python -m science_pulse.cli auth-check  # живой тестер ключей всех 6 площадок (read-only)
python -m science_pulse.cli sync-platform threads --limit 5   # довыгрузить летопись с § 1.1
python -m science_pulse.cli sensors     # живые датчики Планеты и Космоса (USGS, NOAA, LIGO, МКС)
python -m science_pulse.cli rituals --dry-run   # 4-уровневый календарь: слоты, Пт/Сб/Вс, 1-е число
python -m science_pulse.cli add --domain math --title "…" --body "…"   # свой пост в очередь
python -m science_pulse.cli staged      # показать подготовленный N+1 выпуск
python -m science_pulse.cli reject <id> # отправить пост в карантин вручную
python -m science_pulse.cli backup      # снимок science.db документом в админ-чат
python -m science_pulse.cli recover-from-channel   # восстановить состояние из t.me/s/<канал>
python -m science_pulse.cli checkpoint  # сбросить WAL в основной файл БД
python -m science_pulse.cli invariants  # проверка инвариантов состояния
python -m science_pulse.cli formal      # машинная проверка Lean-доказательств
python -m science_pulse.cli edge        # синхронизация R2/D1 (Cloudflare)
python -m science_pulse.cli state       # снимок: --export / --pull / --push / --sync
python -m science_pulse.cli admin       # Telegram-пульт (long polling)
python -m science_pulse.cli admin --once  # один проход опроса команд (для CI/cron)
python -m science_pulse.cli daemon      # 09:00, 13:00, 17:00 и 21:00 по config.yaml
python -m science_pulse.cli book       # 📕 PDF-книга проекта (Typst)
python -m science_pulse.cli voice      # 🔊 озвучка постов (edge-tts / piper)
python -m science_pulse.cli publish --video  # 🎬 озвученное микро-видео
python -m science_pulse.cli preflight  # 🛫 предполётная проверка следующего поста
python -m science_pulse.cli standards  # 📏 пороги качества и прогон очереди
python -m science_pulse.cli quarantine # 🚫 посты в карантине
python -m science_pulse.cli verify     # 🧪 no_llm + инварианты + Lean + фаззинг + медиа
python -m science_pulse.cli foundation # 🏛 ступени фундамента: с каких постов старт
python -m science_pulse.cli limits     # 📐 правила площадок: лимиты и режим звука
python -m science_pulse.cli limits --set threads max_caption_chars 600
python -m science_pulse.cli demo       # 🎓 экскурсия по системе в админ-чат
python -m science_pulse.cli post --preview  # 👁 предпросмотр: карточка + подпись + описание
python -m science_pulse.cli post --send     # отправить предпросмотр в админ-чат
python -m science_pulse.cli reset --yes # очистить состояние (опасно)
python -m science_pulse.cli clean-start --yes # чистый старт: сброс + VACUUM + пересборка сайта
python -m science_pulse.cli kernel      # 🧠 паспорт ядра: канон, курс, очередь, радио, инварианты
python -m science_pulse.cli kernel --tick  # полный 6-фазный цикл ядра (--publish --voice --formal)
python -m science_pulse.cli expand --count 30  # ♾️ добрать темы университетского курса в очередь
python -m science_pulse.cli expand --deep --depth 2  # 🌐 плюс обход мета-каталогов Википедии
python -m science_pulse.cli quiz        # 🧠 викторина по задаче выпуска (--send отправит в канал)
python -m science_pulse.cli radio       # 📻 радио 24/7: страница + подкаст + сводка эфира
python -m science_pulse.cli radio --mix # сквозной радио-микс (ffmpeg) + файл таймкодов
python -m science_pulse.cli radio --rtmp rtmps://dc4.rtmp.t.me/s/KEY --run  # прямой эфир
```

## Пульт в Telegram

`python -m science_pulse.cli admin` запускает long polling. Команды:

```
/status              состояние очереди и площадок
/queue [domain]      очередь
/next                следующий пост
/force [domain]      опубликовать сейчас
/harvest [N]         добрать материалы
/add domain | Заголовок | Текст | формула — добавить свой пост
/render ID           перерисовать карточку
/sources             здоровье источников
/pause /resume       пауза автопостинга
/stats               статистика
/metrics             метрики площадок
/invariants          инварианты состояния
/doctor              🚦 светофор автономности
/preview             карточка следующего поста в личку (без публикации)
/skip                отложить следующий пост в конец очереди
/trending [domain]   🔥 радар мировых новостей (лайки/комментарии)
/pick N [now]        взять хит №N в очередь или опубликовать сейчас
/platforms [ru|en]   площадки: возможности и лимиты
/platform <имя>      детали площадки (telegram/threads/bluesky/discord/mastodon/vk)
/lang ru|en          язык описаний площадок
/about               как работает пульт, где Mini App и где хранится состояние
/theme [стиль]       дизайн выпуска; без аргумента — рейтинг A/B (алиас /ab)
/film [ID] [1:1]    5-актовый фильм Moku3D в этот чат
/auth                живой тестер ключей всех 6 площадок (read-only)
/sync platform [N]   довыгрузить пропущенное начало летописи на площадку
/book                📕 собрать PDF-книгу проекта и прислать файл
/voice               🔊 озвучить следующий пост и прислать голосовое
/standards           📏 пороги качества (/standards set KEY VALUE)
/quarantine          🚫 посты в карантине
/reject ID           🚫 отправить пост в карантин
/preflight           🛫 предполётная проверка
/verify              🧪 инварианты + Lean + фаззинг
/foundation          🏛 ступени фундамента и порядок старта
/limits              📐 правила площадок (/limits set площадка параметр значение)
/site                адрес сайта
```

Описания площадок двуязычные (RU/EN) — переключаются командой `/lang` или
разово (`/platforms en`, `/platform vk ru`). Полный справочник пульта —
`docs/PULT.md`.

Кнопки `callback_query` намеренно не используются: по документации Telegram
ждёт `answerCallbackQuery` 10–30 секунд, а крон-скрипт может спать. Текстовые
команды живут в `getUpdates` до 24 часов и не протухают.

## Архитектура

```
science_pulse/
├── config.py            YAML + .env + переменные окружения
├── models.py            Post, PublishResult, лимиты площадок
├── storage.py           SQLite: посты, публикации, метрики, источники, KV
├── text.py              очистка, маскировка LaTeX/кода, SimHash64, нарезка
├── plotting.py          безопасный разбор выражений, Re/Im, графики
├── cards.py             карточка 1080×1080 (SSAA, Pillow + mathtext)
├── pipeline.py          добыча → качество → дедуп → рендер → публикация
├── scheduler.py         09:00/14:00/19:00 без внешних зависимостей
├── admin.py             Telegram-пульт
├── metrics.py           сбор метрик площадок (Mastodon/Bluesky/VK/Threads)
├── graph.py             PageRank + диск Пуанкаре (граф знаний)
├── abtest.py            A/B стилей карточки (детерминированный выбор)
├── invariants.py        исполняемые инварианты состояния (INV-1…INV-6)
├── trending.py          радар мировых новостей (HN + GitHub + Reddit)
├── formal.py            машинная проверка Lean-доказательств
├── edge.py              синхронизация карточек/узлов с Cloudflare R2/D1
├── state_export.py      CRDT-репликация состояния: pull/push/экспорт в D1
├── site.py              сайт: поиск, граф, KaTeX, sitemap, Mini App «Пульт»
├── sources/             StackExchange, OEIS, Wikipedia, arXiv, Rosetta,
│                        GitHub raw, Numbers API, history_canon, offline
└── publishers/          Telegram, Threads, Bluesky, Discord, Mastodon, VK
formal/
└── Invariants.lean      Lean 4: доказанные инварианты (без sorry)
```

### Три контура

1. **Добыча.** Онлайн-источники → quality gate → SimHash64 → SQLite.
2. **Производство.** Нормализация, защита формул, карточка, график, код.
3. **Публикация.** Telegram первым (даёт `file_id`), затем остальные сети;
   результат каждой площадки пишется в БД, повтор не дублирует пост.

### Три эшелона

1. Онлайн-API с таймаутами и circuit breaker.
2. Очередь в SQLite — публикация не зависит от источника в момент выхода.
3. Офлайн-бункер: полиномы Эрмита/Чебышёва/Лаграндра/Лежандра,
   Fourier-сумма и константы CODATA по индексу эпохи.

## Расписание

Локально: `daemon` читает `schedule` из `config.yaml` (по умолчанию
`09:00`, `14:00` и `19:00` Europe/Moscow).

GitHub Actions: `.github/workflows/science_pulse.yml` запускается по крону
`06:00` и `17:00` UTC, поддерживает ручной `workflow_dispatch`, сохраняет
`data/science.db` в репозиторий, а `dist/` — на GitHub Pages. Для продакшена лучше вынести
состояние в Cloudflare D1/Turso и картинки в R2 — заготовки в `cloudflare/`.

## Тесты

```bash
python -m unittest discover -v
```

Тесты не ходят в сеть: используются фикстуры, временные БД и фейковые
публикаторы. Проверяются:
- маскировка LaTeX и нарезка под лимиты;
- дедупликация и идемпотентность публикаций;
- офлайн-источник и уникальность циклов;
- рендер карточки 1080×1080 и A/B-варианты;
- генерация сайта, Mini App-пульт, PageRank/Пуанкаре-граф;
- сбор метрик площадок (на фейковом HTTP);
- конвейер с фейковыми адаптерами;
- команды Telegram-пульта.

## Ограничения текущей версии

- Онлайн-источники требуют сети; без неё остаётся офлайн-бункер.
- `numbersapi.com` в 2026 отдаёт 404/401, поэтому источник отключён в `config.yaml`.
- `github_raw` по умолчанию отключён: README-списки дают мусорные посты; включайте проверенные raw-URL.
- Перевод включён (`SP_TRANSLATE=1`) для англоязычных источников; это
  бесплатный машинный перевод, не LLM. При отсутствии сети/пакета посты
  выходят в оригинале — см. `docs/TRANSLATION.md`.
- Threads-картинка требует `CF_WORKER_URL`; иначе текст.
- Метрики площадок: сборщик `metrics --collect` читает статистику Mastodon,
  Bluesky, VK и Threads (Telegram Bot API и Discord webhook просмотры/реакции
  не отдают — они помечаются `skipped`).
- Озвучка (`voice.enabled: true`) использует адаптивную цепочку
  edge → piper → google_tts → espeak → сонификация. Облачные движки при
  лимите уходят в cooldown; офлайн-резерв — piper + ONNX-модель
  (`data/piper/`, `bash scripts/install_piper_models.sh`) или `espeak-ng`
  (`docs/VOICE.md`).
- GitHub Actions коммитит SQLite; для нескольких параллельных писателей
  нужен внешний стейт (D1/Turso).

## Математический движок сигналов

`signal_engine.py` реализует пять механизмов книги «Теория передачи сигналов»
(Зюко, Кловский, Назаров, Финк): объём сигнала `Vc ≤ Vk`, энтропию и
избыточность Шеннона, контуры РОС/УОС, критерий Неймана—Пирсона с фильтром
Калмана и ортогональные защитные интервалы. Метрики видны в `/doctor`,
`/ab` и `python -m science_pulse.cli signal`.

## Book-фильм

`book_film.py` — отдельный светлый видео-движок: страница `#FAF8F4`,
DejaVu Serif, формулы Computer Modern, реальный график/код/фазовая диаграмма
и подсветка произносимых слов по таймкодам голоса. Тёмный `moku3d` сохранён.

## Рост аудитории

`docs/GROWTH.md` — стратегия сбора аудитории: уникальные форматы Threads
(теорема/явление/алгоритм дня), воронка Threads → сайт → Telegram, UTM,
реестр каналов и 30-дневный ритм. Команды: `./sp growth plan`,
`./sp growth targets`, `./sp growth report`.

## Хронологический канон

`sources/history_canon.py` — приоритетный офлайн-источник фундаментальных
узлов: Пифагор, Евклид, Архимед, Ньютон, Эйлер, Фурье, Максвелл, Тьюринг,
Шеннон, Нётер. Он идёт от древности к современности и не повторяется:
после исчерпания канона источник возвращает пустой список.

## Типографика и карточки

Подписи выдержаны в стиле `mokujiro.com` (японско-швейцарский минимализм):
**ни одного декоративного смайлика** — только типографика, точки `·` и
выровненный блок `Field: Detail`:

    § 2.3 · ФИЗИКА · 1687 г.
    Ньютон: закон всемирного тяготения

    Как одна формула объяснила и падение яблока, и орбиту Луны?

    Инвариант:      F = G · (m₁ · m₂) / r²
    Верификация:    Эталон CODATA: G = 6.6743·10⁻¹¹ м³/(кг·с²)
    Первоисточник:  Исаак Ньютон
    Применение:     механика полётов, орбиты спутников, GPS

    Задача. Проверьте интуицию: если увеличить r в 3 раза, во сколько раз ослабнет F?

    ← § 1.0 Пифагор · Тренажёр

LaTeX очищается в Unicode (`10⁻⁶ s`, `ℏω`, `ℝ`), текст режется по границам
предложений (450–850 символов). Тот же стиль на сайте: бейджи дисциплин без
смайликов, паспорт параграфа — таблица `Field / Detail` (Параграф,
Дисциплина, Автор/эпоха, Первоисточник, Инвариант, Верификация, Связи).

Карточки 1080×1080 верстаются книжным движком (`cards_academic.py`): бумага
`#FAF8F4`, тушь `#111827`, формулы Computer Modern. Архетип чертежа выбирается
детерминированно; формулы с неарифметическими операторами (`∇`, `∫`, `∮`,
`∑`, `mod`, `lim`), которые не парсятся как `y = f(x)`, **не** рисуются
случайной кривой — вместо неё выводится сводная карточка `cheatsheet_table`.

## Книжная серия (академические карточки) и PDF-книга

`science_pulse/cards_academic.py` — книжный движок карточек: бумага `#FAF8F4`,
тушь `#111827`, DejaVu Serif, формулы Computer Modern, потоковая верстка.
Архетип чертежа выбирается по `post.meta["visual_type"]`:

- `standard_plot` — график f(x) и f'(x);
- `code_booktabs` — листинг «Алгоритм 1.» между линиями booktabs;
- `diptych_insar` — двухпанельный диптих: 2D-поле (интерферограмма InSAR,
  NDVI, геодезические Шварцшильда, туннелирование, Лоренц, Леннард-Джонс)
  и 1D-разрез;
- `cheatsheet_table` — шпаргалка-таблица формул;
- `timeline_evolution` — «Эволюция идеи»: шкала времени с вехами и Δ-годами.

Все физические поля генерируются детерминированно в `science_pulse/simulate.py`
(NumPy/SciPy, без гигабайтных сырых архивов). Переключение движка:
`card.engine: auto | typst | academic | pillow` в `config.yaml`.

Междисциплиналярные узлы канона (`sources/history_canon.py`) несут «Тройную
связь времени»: учёный и эпоха → формула и константы (`constants_used`) →
где работает сегодня (`modern_application`), плюс `prereq_ids` к
учёным-основателям. На сайте появляются **Досье учёных** (`scientists.html`),
**Словарь констант** (`constants.html`, значения из `scipy.constants`) и
**Темы и маршруты изучения** (`topics.html`, хабы при ≥2 постах с общей
концепцией).

PDF-книга проекта собирается в `dist/science_pulse_book.pdf` через Typst:
титульный лист, `#outline()`, главы по дисциплинам, формулы Computer Modern,
карточки-иллюстрации и предметный указатель учёных:

```bash
python -m science_pulse.cli book        # или /book в пульте
```

## Озвучка постов (звук)

`science_pulse/voice.py` озвучивает пост и публикует речь рядом с карточкой:
голосовым сообщением (OGG/OPUS, `sendVoice`) или аудио-подкастом (MP3,
`sendAudio`). На сайте появляется плеер «Слушать» (`dist/audio/<id>.mp3`),
в пульте — команда `/voice`.

- адаптивная цепочка: `edge` (Светлана) → `piper` (офлайн) →
  `google_tts` → `espeak-ng` → сонификация; все движки бесплатные;
- если облачный движок упёрся в лимит, он уходит в cooldown и возвращается
  автоматически; остальные продолжают работу;
- текст для диктора: заголовок → крючок → полный разбор → «Где работает
  сегодня» (LaTeX, код и эмодзи вырезаются, обрезка по границе предложения);
- кэш `data/audio/<id>.mp3|.ogg` — повтор не переозвучивает пост;
- если все TTS недоступны — включается сонификация, пост не падает.

Подробности, конфиг и проверка — `docs/VOICE.md`.

## Видео, качество и старт от фундамента

- **Озвученные микро-видео** (`sound.py` + `video.py`): 30 кадров ожившего
  чертежа на книжной странице + сонификация формулы → MP4 (H.264+AAC,
  `sendVideo`). Выходят каждый 3-й пост автоматически, вручную — `--video`,
  `/force video`, `/preview video`. Карточка `.png` создаётся всегда (сайт, книга).
- **Контур качества** (`standards.py` + `preflight.py`): 8 рубежей (кириллица,
  длина, запрет сырого LaTeX, скобки, AST кода, карточка, HTML), авто-лечение
  и карантин `rejected`. Предполётная проверка — `cli preflight` / `/preflight`.
- **Единая верификация** `cli verify` / `/verify`: аудит `no_llm` (нет
  LLM-импортов/API, перевод выключен), инварианты, Lean 4 (INV-7: гейт и
  карантин), фаззинг подписей, медиа-smoke.
- **Старт от фундамента** (`sources/foundation.py` + `evolve.py`): публикация
  начинается со Ступени 1 (Пифагор → Евклид → Архимед) и идёт по ступеням;
  в подпись добавляется паспорт 🏛 эпоха/учёный и 🔗 ссылки на фундамент,
  на сайте — обратные ссылки «Используется в новых темах».

Подробности — `docs/VIDEO.md`, `docs/QUALITY.md`.

## Лестница сложности: от 1-го поста к миллионному

Канал идёт **строго от фундамента к сложному**, а не вразнобой:

- канон — **38 узлов** (10 ступеней × 3 дисциплины + 8 опорных мостов): Пифагор, Евклид, Архимед →
  Аль-Хорезми, Лейбниц/Буль, Галилей, Ньютон → Ньютон-анализ, Лавлейс, Бернулли →
  Гаусс, Хоар, Больцман → Риман, Дейкстра, Планк → Гёдель, RSA, Эйнштейн + InSAR,
  Шварцшильд, Лоренц;
- каждому посту присваивается `complexity_tier` (1..100): узлы канона получают
  номер ступени (1..10) и выходят первыми по порядку, остальные — по сложности
  формулы и понятий (`curriculum.py`);
- порядок очереди: `foundation → tier → created_at`; проверка и пересортировка —
  `python -m science_pulse.cli reorder-from-foundation`.

## Звук: лекционный сценарий, субтитры и живой чертёж

- **Диктор читает лекцию, а не подпись**: `build_lecture_script` собирает
  «Эрвин Шрёдингер. 1926 год, Цюрих. …» — без URL, хэштегов, @упоминаний,
  эмодзи и казённых меток; отдельная формула голосом не читается, она остаётся
  на карточке;
- **субтитры `.vtt`/`.srt`** синхронны с голосом (таймкоды edge-tts);
- **живой чертёж**: в видео-аудиограмме чертёж постепенно оживает (36 кадров),
  внизу пульсирует осциллограмма голоса.

## Звук: фонетика формул и живая осциллограмма

- **Диктор говорит формулы словами**: `math_to_spoken_russian` превращает
  `O(N log N)` в «о большое от эн логарифм эн», `Δφ` — в «дельта фи»,
  `ℏ` — в «аш с чертой», `c²` — в «це в квадрате». Печатный текст поста не меняется.
- **Видео-аудиограмма оживает**: `ffmpeg showwaves` рисует бегущую звуковую волну
  голоса над колонтитулом книжной страницы (цвет чернил дисциплины).
- **Прямая загрузка без сайта**: Bluesky (`uploadBlob` video/mp4 → `app.bsky.embed.video`)
  и VK (`video.save` → upload_url) принимают `.mp4` прямо с диска.
- **`SP_SITE_BASE_URL` определяется сам** из `git remote get-url origin`
  (GitHub Pages), чужой репозиторий `kern` игнорируется.

## Правила площадок (единый реестр)

Лимиты символов, длина цепочки ответов и **режим доставки звука** для всех
6 соцсетей живут в одном реестре `platforms_info.DEFAULT_PLATFORM_RULES` —
адаптеры читают их оттуда, а не из захардкоженных констант.

| Площадка | Текст ≤ | Цепочка ≤ | Звук |
|:--|--:|--:|:--|
| telegram | 1024 | 2 | `auto` (voice/audio) |
| threads | 500 | 2 | `link` или `mp4` |
| bluesky | 300 | 1 | `link` |
| discord | 2000 | 1 | `file` (mp3-вложение) |
| mastodon | 500 | 1 | `file` (аудио-медиа) |
| vk | 16384 | 1 | `link` |

Threads, Bluesky и VK **не принимают** `.ogg`/`.mp3`: звук доставляется либо
ссылкой на аудио-разбор на сайте, либо **видео-аудиограммой** — карточка
1080×1080 + голос Светланы, склеенные `ffmpeg` в MP4 за секунду.

Правила меняются на ходу, без правок кода:

```bash
python -m science_pulse.cli limits --set threads max_caption_chars 600
python -m science_pulse.cli limits --set telegram audio_mode audio
```

Пульт: `/limits`, `/limits set площадка параметр значение`, `/limits reset`.
Подробности — `docs/LIMITS.md`.

## Анатомия поста (из чего состоит публикация)

Один пост — это **не только картинка**: в Telegram уходят до четырёх частей.

| Часть | Что это | Где формируется |
|:--|:--|:--|
| 1️⃣ **Карточка** | PNG 1080×1080 (книжный архетип) + подпись ≤1024 | `cards_academic.py` + `build_rich_telegram_caption` |
| 2️⃣ **Детальное описание** | второе сообщение до 4096: рубрика → эпоха/учёный → вопрос → **полный разбор** → код → формула → где работает сегодня → константы → тема → фундамент → источник → сайт → теги | `build_full_description` |
| 3️⃣ **Звук** | голосовое `.ogg` (или подкаст `.mp3` >60 с) — диктор Светлана, формулы словами | `voice.py` |
| 4️⃣ **Видео** | аудиограмма: карточка + голос + живая осциллограмма (каждый 3-й пост / по флагу) | `voice.build_audiogram_mp4` |

Подпись под карточкой отвечает на «о чём пост» (975–1000 знаков), а детальное
описание — на «что именно и зачем»: тело поста идёт **целиком**, без обрезки до
абзаца. Второе сообщение уходит ответом на карточку, поэтому пост читается
сверху вниз как мини-статья.

Проверить текст без публикации:

```bash
python -m science_pulse.cli demo --chat <админ-чат>   # полная экскурсия
```

## Экскурсия по системе (`cli demo`)

```bash
python -m science_pulse.cli demo --chat <админ-чат>
```

Отправляет в Telegram полный тур: 5 карточек (по одной на каждый архетип) и для
каждого поста — **как он выглядит в каждой из 6 соцсетей** (тексты берутся теми
же билдерами, что и публикация), затем озвучку, видео-аудиограмму, оживший
чертёж, служебные таблицы (`/limits`, фундамент, preflight, verify, doctor) и
PDF-книгу. Удобно, чтобы показать проект целиком одной командой.

## Просветительская задача (в комментарии)

Каждый выпуск заканчивается задачей, которую читатель решает **в уме прямо в
ленте**, а ядро заранее считает точный ответ:

* подпись: `🧠 Задача на смекалку: … Напишите ответ в комментариях 👇` +
  `🧭 Тренажёр: покрутить формулу и проверить себя`;
* глава на сайте (слой `z = 3`): раскрывающийся блок
  «🧠 Просветительская задача для самопроверки» с подсказкой и ответом;
* радио и подкаст: при включённой задаче — естественная фраза «Попробуйте
  сами: …» (без метки «Задача слушателю»);
* Telegram: **нативная викторина** `sendPoll` в реплай к посту (при
  `telegram.quiz_poll: true` и числовом ответе) — читатель отвечает в один тап;
* Threads/VK/Bluesky (режим `TEXT`): формула уходит в мобильной рамке
  `┌─── 📐 ФОРМУЛА ─── │ … └───`;
* `post.meta["challenge"]` и вычислительный паспорт хранят задачу целиком.

Стратегии детерминированы и **проверяются вычислением** (не «на глаз»):
`steps`/`growth` (сложность алгоритма), `ratio` (доказанный степенной закон
`k·xⁿ`), `substitute` (подстановка), `solve` (решение уравнения), `concept`
(формула непарсируема — вопрос из крючка выпуска). Подробности —
`docs/CHALLENGE.md`.

## Документация

| Документ | О чём |
|:--|:--|
| `docs/PLAN.md` | план развития и фактический статус |
| `docs/PLATFORMS.md` | все площадки: возможности, лимиты, нюансы, метрики |
| `docs/ARCHITECTURE.md` | полная архитектура проекта: слои, модули, потоки |
| `docs/EXPLAINER.md` | инфографический explainer-фильм |
| `docs/CARDS.md` | карточки: студийный движок 3Blue1Brown + Typst |
| `docs/PULT.md` | пульт: команды, Mini App, где что хранится, язык RU/EN |
| `docs/TRENDING.md` | радар мировых новостей: источники, индекс горячести, `/pick` |
| `docs/INTEGRATIONS.md` | карта всех API: ключи, лимиты, куда добавлять |
| `docs/PLATFORM_WATCH.md` | еженедельный мониторинг изменений API |
| `docs/SITE_BRANCHES.md` | личные ветки, форки, академические плашки |
| `docs/TOKENS.md` | получение токенов и подключение площадок |
| `docs/GRAPH.md` | граф знаний: PageRank и диск Пуанкаре |
| `docs/ABTEST.md` | A/B: 4 дизайна, бандит Томпсона, `/theme`, `/ab` |
| `docs/MOKU3D.md` | Moku3D: 5-актовый фильм из одного уравнения |
| `docs/POST_MODES.md` | пять режимов подачи: задача выходит дозированно |
| `docs/LIVE_SENSORS.md` | живые датчики Планеты и Космоса без ключей |
| `docs/LABS.md` | десять лабораторных стендов: ЦЕРН, LIGO, Вороной, 3-SAT, CG, P/S, альтиметрия, GRACE-FO, ветер, Меркурий |
| `docs/SCHEDULE.md` | 4-уровневый календарь: слоты, Пт/Сб/Вс, 1-е число |
| `docs/CANON_GATE.md` | двухпроходный шлюз канона (Pass 1 и Pass 2) |
| `docs/FOUNDATION_TOPOLOGY.md` | топология фундамента: диск Пуанкаре и геодезические |
| `docs/PROOF.md` | вычислительный паспорт выпуска и проверка кода |
| `docs/MINIAPP.md` | Mini App «Пульт» (статическая страница) |
| `docs/TRANSLATION.md` | перевод без LLM (формулы и код не трогаются) |
| `docs/INVARIANTS.md` | инварианты состояния (Lean-спецификация + проверки) |
| `docs/FORMAL.md` | машинная проверка инвариантов на Lean 4 |
| `docs/EDGE.md` | синхронизация R2/D1 через Cloudflare Worker |
| `docs/D1_STATE.md` | репликация состояния в D1 (снимок, SQL-дамп, push) |
| `docs/VOICE.md` | озвучка постов: движки, форматы, конфиг |
| `docs/VIDEO.md` | озвученные микро-видео: звук формулы, кадры, ffmpeg |
| `docs/QUALITY.md` | контур качества: 8 рубежей, карантин, preflight, verify |
| `docs/LIMITS.md` | правила площадок: лимиты, цепочки, режимы звука |
| `docs/PROD_CHECKLIST.md` | боевой запуск по шагам |
| `docs/KERNEL.md` | центральное ядро: 6 фаз, часы эпохи, паспорт состояния |
| `docs/RADIO.md` | научное радио 24/7: WebAudio, подкаст, микс, RTMP |
| `docs/SYLLABUS.md` | бесконечный поток: матрица курса, краулер, родословная первоисточников |
| `docs/CHALLENGE.md` | просветительская задача выпуска: стратегии, самопроверка ответа |

## Дальше по плану

См. `docs/PLAN.md` и `docs/PROD_CHECKLIST.md`. Алгоритмы «после MVP» лежат в
`science_pulse/sota.py` (Томпсон, Hawkes O(1), FSRS, Диск Пуанкаре) и
управляются флагами в `config.yaml`. **Thompson и гейт Hawkes включены по
умолчанию**; отказ гейта — это отложение (`deferred`), а не сбой, поэтому CI
не падает и не шлёт ложный алерт оператору. Реализованы PageRank/Пуанкаре-граф
(`graph.py`), A/B стилей (`abtest.py`), Mini App-пульт (`pult.html`, приватный — `miniapp.public`),
PWA (манифест + service worker + иконки), флешкарты (`flashcards.html`), BibTeX-экспорт
(`bibtex.bib`), поиск по формулам и символам, единый предпросмотр `cli post --preview`,
викторина `/quiz` в пульте и `cli clean-start`,
инварианты состояния (`invariants.py`), машинно проверяемые Lean-доказательства
(`formal/Invariants.lean`) и edge-синхронизация R2/D1 (`edge.py`,
`state_export.py`) с CRDT-разрешением конфликтов параллельных писателей и
режимом D1-Primary. Открытых пунктов в плане нет.

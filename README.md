# Science Pulse

Детерминированная фабрика научного контента по мотивам документа
`2-2026-10-31.md`: математика, физика и информатика — 3 публикации в сутки
(09:00, 14:00 и 19:00 МСК) в Telegram, Threads и другие сети, с карточками 1080×1080, формулами,
графиками и растущим сайтом.

**Главный принцип: в контенте нет LLM.** Текст берётся из открытых
источников, перевод — опциональный, картинка рисуется кодом, публикация
идемпотентна. Если сеть и API недоступны, работает офлайн-бункер на
SymPy + SciPy CODATA.

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

Threads принимает картинку только по публичному URL. Если `CF_WORKER_URL`
задан, используется безопасный прокси Telegram CDN по `file_id` (токен бота
наружу не попадает). Если прокси нет — Threads получает текстовый пост.

## Команды

```bash
python -m science_pulse.cli init
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
python -m science_pulse.cli invariants  # проверка инвариантов состояния
python -m science_pulse.cli formal      # машинная проверка Lean-доказательств
python -m science_pulse.cli edge        # синхронизация R2/D1 (Cloudflare)
python -m science_pulse.cli state       # снимок: --export / --pull / --push / --sync
python -m science_pulse.cli admin       # Telegram-пульт (long polling)
python -m science_pulse.cli admin --once  # один проход опроса команд (для CI/cron)
python -m science_pulse.cli daemon      # 09:00, 14:00 и 19:00 по config.yaml
python -m science_pulse.cli book       # 📕 PDF-книга проекта (Typst)
python -m science_pulse.cli voice      # 🔊 озвучка постов (edge-tts / piper)
python -m science_pulse.cli publish --video  # 🎬 озвученное микро-видео
python -m science_pulse.cli preflight  # 🛫 предполётная проверка следующего поста
python -m science_pulse.cli standards  # 📏 пороги качества и прогон очереди
python -m science_pulse.cli quarantine # 🚫 посты в карантине
python -m science_pulse.cli verify     # 🧪 инварианты + Lean + фаззинг + медиа
python -m science_pulse.cli foundation # 🏛 ступени фундамента: с каких постов старт
python -m science_pulse.cli limits     # 📐 правила площадок: лимиты и режим звука
python -m science_pulse.cli limits --set threads max_caption_chars 600
python -m science_pulse.cli demo       # 🎓 экскурсия по системе в админ-чат
python -m science_pulse.cli reset --yes # очистить состояние (опасно)
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
- Перевод включается `SP_TRANSLATE=1` и требует `deep-translator`
  (при отсутствии пакета/сети посты выходят в оригинале) — см. `docs/TRANSLATION.md`.
- Threads-картинка требует `CF_WORKER_URL`; иначе текст.
- Метрики площадок: сборщик `metrics --collect` читает статистику Mastodon,
  Bluesky, VK и Threads (Telegram Bot API и Discord webhook просмотры/реакции
  не отдают — они помечаются `skipped`).
- Озвучка (`voice.enabled: true`) по умолчанию использует онлайн-движок
  edge-tts и требует сети; без сети/движка озвучка пропускается, пост выходит
  текстом. Офлайн-вариант — piper + ONNX-модель (`docs/VOICE.md`).
- GitHub Actions коммитит SQLite; для нескольких параллельных писателей
  нужен внешний стейт (D1/Turso).

## Хронологический канон

`sources/history_canon.py` — приоритетный офлайн-источник фундаментальных
узлов: Пифагор, Евклид, Архимед, Ньютон, Эйлер, Фурье, Максвелл, Тьюринг,
Шеннон, Нётер. Он идёт от древности к современности и не повторяется:
после исчерпания канона источник возвращает пустой список.

## Типографика и карточки

Telegram-подписи очищаются от LaTeX в Unicode (`10⁻⁶ s`, `ℏω`, `ℝ`),
режутся по границам предложений и дополняются научным контекстом до
450–850 символов. Карточки 1080×1080 верстаются крупным заголовком в 2–3
строки и lead-абзацем. Режим выбирается по данным поста: для OEIS — реальный
stem plot членов a(n), для функций — f(x) и производная f'(x), для CS — окно
IDE с нумерацией строк и Big-O, для законов без данных — theorem sheet без
декоративной волны.

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

- движок по умолчанию — `edge` (edge-tts: онлайн, бесплатно, без ключей,
  голос `ru-RU-SvetlanaNeural`); офлайн-режим — `piper` + ONNX-модель;
- текст для диктора: заголовок → крючок → полный разбор → «Где работает
  сегодня» (LaTeX, код и эмодзи вырезаются, обрезка по границе предложения);
- кэш `data/audio/<id>.mp3|.ogg` — повтор не переозвучивает пост;
- если движка/сети нет — озвучка мягко пропускается, пост выходит текстом.

Подробности, конфиг и проверка — `docs/VOICE.md`.

## Видео, качество и старт от фундамента

- **Озвученные микро-видео** (`sound.py` + `video.py`): 30 кадров ожившего
  чертежа на книжной странице + сонификация формулы → MP4 (H.264+AAC,
  `sendVideo`). Выходят каждый 3-й пост автоматически, вручную — `--video`,
  `/force video`, `/preview video`. Карточка `.png` создаётся всегда (сайт, книга).
- **Контур качества** (`standards.py` + `preflight.py`): 7 рубежей (кириллица,
  длина, запрет сырого LaTeX, скобки, AST кода, карточка, HTML), авто-лечение
  и карантин `rejected`. Предполётная проверка — `cli preflight` / `/preflight`.
- **Единая верификация** `cli verify` / `/verify`: инварианты, Lean 4 (INV-7:
  гейт и карантин), фаззинг подписей, медиа-smoke.
- **Старт от фундамента** (`sources/foundation.py` + `evolve.py`): публикация
  начинается со Ступени 1 (Пифагор → Евклид → Архимед) и идёт по ступеням;
  в подпись добавляется паспорт 🏛 эпоха/учёный и 🔗 ссылки на фундамент,
  на сайте — обратные ссылки «Используется в новых темах».

Подробности — `docs/VIDEO.md`, `docs/QUALITY.md`.

## Лестница сложности: от 1-го поста к миллионному

Канал идёт **строго от фундамента к сложному**, а не вразнобой:

- канон — **30 узлов** (10 ступеней × 3 дисциплины): Пифагор, Евклид, Архимед →
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
  «Раздел Физика. 1926 год, Цюрих. Эрвин Шрёдингер. …» — без URL, хэштегов,
  @упоминаний и эмодзи, формулы произносятся словами;
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

## Документация

| Документ | О чём |
|:--|:--|
| `docs/PLAN.md` | план развития и фактический статус |
| `docs/PLATFORMS.md` | все площадки: возможности, лимиты, нюансы, метрики |
| `docs/CARDS.md` | карточки: студийный движок 3Blue1Brown + Typst |
| `docs/PULT.md` | пульт: команды, Mini App, где что хранится, язык RU/EN |
| `docs/TRENDING.md` | радар мировых новостей: источники, индекс горячести, `/pick` |
| `docs/TOKENS.md` | получение токенов и подключение площадок |
| `docs/GRAPH.md` | граф знаний: PageRank и диск Пуанкаре |
| `docs/ABTEST.md` | A/B стилей карточки |
| `docs/MINIAPP.md` | Mini App «Пульт» (статическая страница) |
| `docs/TRANSLATION.md` | перевод без LLM (формулы и код не трогаются) |
| `docs/INVARIANTS.md` | инварианты состояния (Lean-спецификация + проверки) |
| `docs/FORMAL.md` | машинная проверка инвариантов на Lean 4 |
| `docs/EDGE.md` | синхронизация R2/D1 через Cloudflare Worker |
| `docs/D1_STATE.md` | репликация состояния в D1 (снимок, SQL-дамп, push) |
| `docs/VOICE.md` | озвучка постов: движки, форматы, конфиг |
| `docs/VIDEO.md` | озвученные микро-видео: звук формулы, кадры, ffmpeg |
| `docs/QUALITY.md` | контур качества: 7 рубежей, карантин, preflight, verify |
| `docs/LIMITS.md` | правила площадок: лимиты, цепочки, режимы звука |
| `docs/PROD_CHECKLIST.md` | боевой запуск по шагам |

## Дальше по плану

См. `docs/PLAN.md` и `docs/PROD_CHECKLIST.md`. Алгоритмы «после MVP» уже
лежат в `science_pulse/sota.py` (Томпсон, Hawkes O(1), FSRS, Диск Пуанкаре)
и включаются флагами в `config.yaml`. Реализованы PageRank/Пуанкаре-граф
(`graph.py`), A/B стилей (`abtest.py`), Mini App-пульт (`pult.html`, приватный — `miniapp.public`),
инварианты состояния (`invariants.py`), машинно проверяемые Lean-доказательства
(`formal/Invariants.lean`) и edge-синхронизация R2/D1 (`edge.py`,
`state_export.py`) с CRDT-разрешением конфликтов параллельных писателей и
режимом D1-Primary. Открытых пунктов в плане нет.

# Пульт: команды, Mini App и где что хранится

Справочник по пульту Science Pulse: как он работает, где живёт Mini App,
где хранится состояние и как выбрать язык описаний площадок (RU/EN).

Код: `science_pulse/admin.py` (Telegram-пульт), `science_pulse/platforms_info.py`
(двуязычный каталог площадок), `science_pulse/site.py` (`_write_miniapp`).
Тесты: `tests/test_admin.py`, `tests/test_platforms_info.py`, `tests/test_site.py`.

## Как работает

Пульт — это Telegram-бот, который читает команды из `getUpdates`
(**long polling**, `python -m science_pulse.cli admin`). Кнопки
`callback_query` намеренно не используются: Telegram ждёт `answerCallbackQuery`
10–30 секунд, а команды в `getUpdates` живут до 24 часов и не протухают.

## Команды

| Команда | Что делает |
|:--|:--|
| `/status` | состояние очереди и площадок |
| `/queue [math\|physics\|cs]` | очередь постов |
| `/next` | какой пост выйдет следующим |
| `/force [domain]` | опубликовать сейчас |
| `/harvest [N]` | добрать материалы (N на источник) |
| `/add domain \| Заголовок \| Текст \| формула \| код` | добавить свой пост |
| `/render ID` | перерисовать карточку |
| `/sources` | здоровье источников |
| `/pause` / `/resume` | пауза/возобновление автопостинга |
| `/stats` | статистика |
| `/metrics` | метрики площадок |
| `/invariants` | инварианты состояния (INV-1…INV-6) |
| **`/doctor`** | 🚦 светофор автономности (готовность к автопилоту) |
| **`/preview`** | прислать карточку следующего поста в личку (без публикации) |
| **`/skip`** | отложить следующий пост в конец очереди |
| **`/trending [domain]`** | 🔥 радар мировых новостей (лайки/комментарии) |
| **`/pick N [now]`** | взять хит №N в очередь или опубликовать сейчас |
| **`/platforms [ru\|en]`** | площадки: возможности и лимиты |
| **`/platform <имя> [ru\|en]`** | детали площадки |
| **`/lang ru\|en`** | язык описаний площадок |
| **`/about`** | как работает пульт, где Mini App и где хранится состояние |
| `/site` | адрес сайта |
| `/help` | справка |

## Язык описаний (RU / EN)

Описания площадок двуязычные (`science_pulse/platforms_info.py`), язык
выбирается командой:

```
/lang ru      → русский (по умолчанию)
/lang en      → English
```

Выбор хранится в состоянии (`kv: admin_lang`) и применяется к `/platforms`,
`/platform` и `/about`. Можно задать язык и разово:

```
/platforms en
/platform vk ru
```

Для каждой площадки выводится: **что умеет, лимиты, картинка, метрики, нюансы**
и переменные окружения. Состав каталога: `telegram`, `threads`, `bluesky`,
`discord`, `mastodon`, `vk`.

## Что показывает `/about`

- как работает пульт (long polling, список команд);
- **где Mini App** — `{SP_SITE_BASE_URL}/pult.html`, но страница публикуется
  только при `miniapp.public: true` (по умолчанию — приватно; если база не
  задана, выводится подсказка собрать сайт: `cli site`);
- **где хранится**: `data/science.db` (SQLite, WAL), `data/cards/*.png`,
  `dist/` (сайт), секреты в `.env`/Secrets, edge-реплика в Cloudflare D1.

## Mini App «Пульт»

Веб-страница `dist/pult.html` (по умолчанию **не публикуется** — `miniapp.public: false`):

- снимок состояния (очередь, публикации, площадки, источники);
- кнопки команд (шлют `POST {command}` на `CF_WORKER_URL/telegram-webhook`);
- **раздел «Площадки / Platforms»** с переключателем 🇷🇺/🇬🇧 и описаниями
  каждой площадки на выбранном языке;
- блок «Как это работает / How it works» (тоже двуязычный).

Подробнее — `docs/MINIAPP.md`.

## Светофор автономности `/doctor`

Один экран отвечает на вопрос «можно ли уходить в автопилот»:

| Узел | Что показывает |
|:--|:--|
| Telegram-канал | канал, наличие токена, готовность пульта |
| Запас очереди | сколько `ready`, разбивка по дисциплинам, на сколько дней хватит, есть ли непереведённые |
| Переводчик (RU) | включён ли `SP_TRANSLATE` и какая цепочка провайдеров |
| Сайт и Mini App | задан ли HTTPS-адрес `SP_SITE_BASE_URL` |
| Площадки | кто активен, кто ждёт ключей |
| Расписание | слоты, таймзона и время следующего запуска, пауза |
| Инварианты | INV-1…INV-6 |

Метки: 🟢 норма, 🟡 внимание, ⚪ не настроено, 🔴 проблема.

```bash
python -m science_pulse.cli doctor          # в консоль
python -m science_pulse.cli doctor --send   # отправить в админ-чат
```

Ожидаемый темп публикаций для расчёта «дней запаса» задаётся в `config.yaml`
(`doctor.posts_per_day`, по умолчанию 2).

## Меню команд Telegram

Пульт ставит нативное меню (кнопка «/») через `setMyCommands` на языке оператора
(`kv: admin_lang`). Отключается флагом `admin.set_commands: false`.
При включённом HTTPS-адресе сайта `/menu` добавляет кнопку **«Пульт»** рядом с
полем ввода (`setChatMenuButton`).

## Где что хранится

| Что | Где |
|:--|:--|
| Состояние (посты, публикации, метрики, источники, kv) | `data/science.db` (SQLite, WAL) |
| Карточки 1080×1080 | `data/cards/*.png` |
| Сайт (`graph.json`, `search.json`; `pult.html` — только при `miniapp.public`) | `dist/` |
| Секреты | `.env` (локально) / GitHub Secrets / Cloudflare Secrets |
| Edge-реплика (опционально) | Cloudflare D1 (`cli state --push/--sync`) |

## Как добавить площадку в каталог

1. Добавьте запись в `PLATFORMS` (`science_pulse/platforms_info.py`) с полями
   `emoji`, `env` и блоками `ru`/`en` (`title`, `what`, `limits`, `image`,
   `metrics`, `notes`).
2. Если у площадки есть адаптер публикации — зарегистрируйте его в
   `publishers/manager.py` (см. `docs/PLATFORMS.md`).
3. Проверьте: `python -m unittest tests.test_platforms_info -v`.

## Проверка

```bash
python -m unittest tests.test_admin tests.test_platforms_info tests.test_site -v
SP_MINIAPP_PUBLIC=1 python -m science_pulse.cli site && grep -c 'data-lang' dist/pult.html
```

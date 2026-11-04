# Mini App «Пульт» (статическая страница)

Документ описывает встроенный «Пульт» — статическую страницу `dist/pult.html`,
которая публикуется вместе с сайтом (GitHub Pages / Cloudflare Pages) и даёт
снимок состояния плюс кнопки команд.

Код: `science_pulse/site.py` (`_write_miniapp`).
Тесты: `tests/test_site.py` (`test_miniapp_page`).

## Что это

`pult.html` собирается при `python -m science_pulse.cli site` и содержит:

- **снимок состояния** на момент сборки: очередь по дисциплинам, число
  опубликованных/ошибочных постов, доступность площадок, здоровье источников
  (с пометкой `OPEN` для сработавшего circuit breaker);
- **кнопки команд**: «Опубликовать сейчас», «Добрать материалы», «Пересобрать
  сайт», «Статус»;
- **раздел «Площадки / Platforms»** с переключателем 🇷🇺/🇬🇧 — описания всех
  площадок (что умеет, лимиты, картинка, метрики, нюансы, переменные);
- блок **«Как это работает / How it works»** (двуязычный): long polling, где
  Mini App, где хранится состояние;
- ссылку на страницу с главной («Пульт» в блоке ссылок).

## Как работают кнопки

Кнопки шлют `POST {"command": "<run|harvest|site|status>"}` на
`CF_WORKER_URL/telegram-webhook`. Ответ показывается строкой статуса
(`command: HTTP <код>`).

Секретов на странице **нет**: токены бота и GitHub PAT живут в Cloudflare
Worker'е (`wrangler secret`). Поэтому `pult.html` можно публиковать публично.

Если `CF_WORKER_URL` не задан:

- кнопки отключены (`disabled`);
- выводится подсказка «настройте Cloudflare Worker (см. docs/PLATFORMS.md)».

## Язык описаний (RU/EN)

Раздел площадок и блок «как это работает» двуязычные. Переключатель 🇷🇺/🇬🇧
на странице перерисовывает список без перезагрузки; данные обоих языков
встроены в `pult.html` из `science_pulse/platforms_info.py`. Тот же каталог
использует Telegram-пульт (`/platforms`, `/platform`, `/lang`) — см. `docs/PULT.md`.

## Требования к endpoint

Обработчик на стороне Worker'а должен принимать `POST` с JSON `{command}` и
инициировать соответствующее действие (например, `workflow_dispatch` GitHub
Actions или прямой запуск). Базовый маршрут `/telegram-webhook` в
`cloudflare/worker.js` уже вызывает GitHub Actions; при необходимости
расширьте его обработкой поля `command`.

## Включение

1. Разверните Cloudflare Worker (см. `docs/PLATFORMS.md` и `docs/TOKENS.md`).
2. Задайте `CF_WORKER_URL` в `.env` / GitHub Secrets.
3. Пересоберите сайт: `python -m science_pulse.cli site`.

## Почему не Telegram WebApp API

Полноценный Telegram Mini App (`Telegram.WebApp.sendData`) требует, чтобы бот
обрабатывал `web_app_data`/`answerWebAppQuery`. Текущий пульт работает на
`getUpdates` (long polling), поэтому выбран простой и переносимый вариант:
статическая страница + HTTPS-endpoint. Так «Пульт» открывается и как обычная
веб-страница, и как ссылка внутри Telegram.

## Ограничения

- Кнопки без настроенного endpoint неактивны (страница всё равно полезна как
  дашборд).
- Снимок состояния — на момент сборки сайта, а не «живой»; для актуальных
  данных нажмите «Статус» или пересоберите сайт.

## Проверка

```bash
python -m science_pulse.cli site
grep -c mini-action dist/pult.html
python -m unittest tests.test_site -v
```

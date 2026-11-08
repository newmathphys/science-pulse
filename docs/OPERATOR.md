# Оператор SCM

Ты — **главный оператор**. SCM — твоя машина научного контента. Агент — ИИ-инструмент:
он готовит, проверяет и документирует, но решение и подпись остаются за тобой.

## 1. Вход за одну команду

```bash
cd "/home/mrbritneyxxx/Рабочий стол/ПРОЕКТТ SCM"
./sp enter
```

`./sp enter` показывает:

- очередь, опубликованные посты, ошибки;
- активные площадки и чего не хватает;
- следующий пост и результат preflight;
- статус Knowledge Base;
- ссылку на сайт;
- что делать дальше.

## 2. Ежедневный цикл

```bash
./sp enter          # вход и статус
./sp launch         # проверка ключей Telegram + Threads
./sp publish        # опубликовать следующий пост
./sp check          # тесты, verify, preflight, knowledge integrity
./sp knowledge search "формула"   # поиск по документам
./sp site           # пересобрать сайт
```

## 3. Пульт в Telegram

```bash
./sp admin
```

Команды:

```text
/status /queue /next /force /harvest /sources
/preview /film book /voice /book /metrics
/doctor /ab /preflight /verify /kernel
/theme /standards /quarantine /pause /resume
```

## 4. Что считается «всё работает»

```bash
./sp check
```

Должно быть зелёным:

1. `python -m unittest discover`;
2. `python -m science_pulse.cli verify`;
3. `python -m science_pulse.cli preflight --no-media`;
4. `python -m science_pulse.cli knowledge integrity`;
5. `python -m science_pulse.cli doctor` (без красных блоков);
6. сайт отвечает `200`.

## 5. Аварийные действия

| Ситуация | Команда |
|:--|:--|
| остановить пульт | `./sp stop` |
| пауза автопостинга | `/pause` или `python -m science_pulse.cli` + `pause` |
| убрать пост | `/reject <id>` |
| пересобрать сайт | `./sp site` |
| проверить целостность знаний | `./sp knowledge integrity` |
| backup базы | `python -m science_pulse.cli backup` |
| восстановить из канала | `python -m science_pulse.cli recover-from-channel` |

## 6. Что не делает агент

- не ставит `PROVEN` без оракула/подписи;
- не публикует без твоего решения, если ты не дал явную команду;
- не меняет чужие проекты (`RII`, `KERN`, `NYUUI`, `АССИСТЕНТ`);
- не печатает и не коммитит секреты.

## 7. Документация

Начинай с `docs/INDEX.md`. Все изменения поведения должны попадать в docs тем же
коммитом. Числа в документах берутся из команд, а не из памяти.

# Режимы подачи: почему задача не в каждом посте

Психология внимания (habituation): если **каждый** выпуск заканчивать требованием
«решите задачу», читатель привыкает и перестаёт читать низ поста. Поэтому задача
выходит **дозированно**, а основную массу ленты составляет чистое знание.

Модуль `science_pulse/post_modes.py` назначает каждому выпуску один из пяти
режимов и записывает его в `post.meta["post_mode"]`.

| Режим | Доля (вес) | Что в подписи |
|:--|:--:|:--|
| `pure_knowledge` | 6 | чистое знание: паспорт, разбор, `Инвариант / Верификация / Первоисточник / Применение`. **Без задачи** |
| `satellite_lab` | 2 | спутниковый спецвыпуск (диптих InSAR/NDVI/…) |
| `cheatsheet_save` | 1 | карточка-шпаргалка для «Избранного» (`cheatsheet_table`) |
| `moku3d_film` | 1 | 5-актовый фильм Moku3D (дизайн `moku3d`) |
| `interactive_challenge` | 1 | **задача выпуска** + скрытый ответ |

## Как выбирается режим

1. Явный `post.meta["post_mode"]` — высший приоритет (ручной выпуск).
2. Дизайн `moku3d` → `moku3d_film`.
3. `meta["simulation"]` или архетип `diptych_insar` → `satellite_lab`.
4. Архетип `cheatsheet_table` → `cheatsheet_save`.
5. Каждый `challenge_every_nth`-й выпуск (по умолчанию 5) → `interactive_challenge`.
6. Иначе — детерминированная взвешенная ротация (`WEIGHTS`, без случайности).

## Ответ на задачу

- **Telegram**: `<b>Ответ:</b> <tg-spoiler>…</tg-spoiler>` — читатель думает сам,
  затем нажимает мерцающую плашку и видит ответ ядра.
- **Threads**: ответ уходит **отдельным сообщением цепочки** (спойлеров нет).
- **Bluesky / Mastodon**: строка `Ответ: …` в конце поста.

## Настройка

```yaml
post_modes:
  enabled: true
  challenge_every_nth: 5
  weights:
    pure_knowledge: 6
    satellite_lab: 2
    cheatsheet_save: 1
    moku3d_film: 1
    interactive_challenge: 1
```

## Проверка

```bash
python -m unittest tests.test_connection_tools -v   # режимы, /auth и /sync
python -m unittest tests.test_challenge -v          # задача, спойлер, 30/30 verified
```

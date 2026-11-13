# Контур качества: стандарты, предполётная проверка, верификация

## Зачем

Публикация — необратимое действие: пост уходит в канал и в другие сети.
Поэтому перед каждым выходом пост проходит **9 рубежей** проверки, а проект —
единый `cli verify`.

## 1. `standards.py` — 9 рубежей (`StandardsChecker`)

| Рубеж | Что проверяется | Порог по умолчанию |
|:--|:--|:--|
| `cyrillic` | доля кириллицы в подписи (пост переведён) | ≥ `0.42` |
| `length` | букв в описании | ≥ `200` |
| `raw_latex` | нет сырых `\frac`, `\sqrt`, `$$` в подписи | — |
| `brackets` | баланс `()`, `[]`, `{}` и долларов | — |
| `code_ast` | код поста разбирается `ast.parse` | — |
| `card` | карточка ровно 1080×1080 и > 15 КБ | `1080`, `15000` |
| `html` | баланс HTML-тегов Telegram | — |
| `translation_seam` | технические следы машинного перевода: маски, пробелы перед знаками, пустые скобки | ≤ `3` |
| `cross_modal` | неизвестные LaTeX-команды и потеря оператора `A B` | — |

Пороги настраиваются: `/standards set min_letters 240` в пульте или
`python -m science_pulse.cli standards --set min_letters 240` (хранятся в `kv`).

**Авто-лечение (`heal`)**: LaTeX → Unicode, перевод (если кириллицы мало),
обрезка строго по предложению, закрытие незакрытых HTML-тегов.

**Карантин**: если после лечения пост всё ещё не проходит — статус
`rejected`, причина в `meta.rejected_reason`, счётчик в `kv`. Такой пост
никогда не выйдет, пока оператор не разберётся.

## 2. `preflight.py` — предполётный чек-лист

```bash
python -m science_pulse.cli preflight        # или /preflight в пульте
```

Проверяет: очередь, рендер карточки в память, стандарты подписи, объём сигнала
`Vc ≤ Vk` и энтропию/избыточность Шеннона, доступность озвучки и видео.
Ничего не публикует и не меняет состояние.

## 3. `cli verify` — единая верификация

```bash
python -m science_pulse.cli verify           # или /verify в пульте
```

- **инварианты состояния** (INV-1…INV-6) — `invariants.py`;
- **Lean 4** — формальные доказательства, включая INV-7 (гейт и карантин):
  `published_implies_gate`, `gate_blocks_published`, `round_robin_no_deadlock`,
  `reject_monotone`;
- **фаззинг подписей** — детерминированный генератор «плохих» текстов:
  `check()` и `heal()` не должны падать, а `heal()` — ухудшать результат.
  Прогон **полностью офлайн**: на время фаззинга сетевой перевод
  (`translate_preserving_latex`) подменяется тождеством, поэтому результат
  зависит только от `seed` и числа итераций, а не от сети;
- **медиа-smoke** — синтез звука, сборка микро-видео, рендер карточки.

## Команды

```bash
python -m science_pulse.cli standards                 # пороги + прогон очереди
python -m science_pulse.cli standards --set min_letters 240
python -m science_pulse.cli quarantine                # посты в карантине
python -m science_pulse.cli reject --id <id> --yes     # вручную в карантин
python -m science_pulse.cli preflight                 # предполётная проверка
python -m science_pulse.cli verify                    # инварианты + Lean + фаззинг + медиа
```

Пульт: `/standards`, `/standards set KEY VALUE`, `/quarantine`, `/reject ID`,
`/preflight`, `/verify`.

## Проверка

```bash
python -m unittest tests.test_standards tests.test_fuzz -v
lean formal/Invariants.lean
```
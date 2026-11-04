# Приёмочная комиссия канона (`canon_gate.py`)

Двухпроходная приёмка поста перед публикацией + N+1 warm staging.
Модуль: `science_pulse/canon_gate.py`. Тесты: `tests/test_canon_gate.py`.

## Сигнатура

```python
CanonGate(storage, config).verify_and_enforce(post, card_path="", caption="") -> dict
```

## Pass 1 — канон контента и раздела

| Проверка | Что делает |
|:--|:--|
| Кириллица | если `config.translate`, доля кириллицы в `title+body ≥ 0.42`; иначе авто-перевод (`translate_preserving_latex`) |
| Длина | `len(body) ≥ 200` |
| Сырой LaTeX | в подписи нет `\frac{`, `\begin{`, `$$` |
| Паспорт канона | пустые `era`, `scientist`, `modern_application`, `formula_vars` **авто-заполняются** дефолтами дисциплины (`DEFAULT_FILLERS`) и сохраняются в meta |
| Правило раздела | `math` — баланс скобок формулы; `physics` — непустая формула **и** `constants_used`/`modern_application`; `cs` — валидный `ast.parse(code)` **или** `O(...)` |

## Pass 2 — канон медиа и подписи

- карточка существует, **1080×1080**, вес **≥ 15 КБ**, `std(pixels) ≥ 5.0`;
- внешнее поле (15 px) не залито тёмным (доля тёмных пикселей ≤ 0.5);
- длина подписи ≤ 1024, HTML-теги Telegram сбалансированы.

**При отказе** (после авто-доводки) пост переводится в `status = "rejected"`,
причины пишутся в `meta["reject_reasons"]`, и пайплайн берёт следующий пост.

## N+1 warm staging

```python
CanonGate(...).stage_next(pipeline) -> dict
```

Берёт следующий `ready`-пост, прогоняет `build_post_proof` + `enrich_post_longread`
+ рендер карточки + приёмку и кладёт его id в `kv["staged_next_post_id"]`.
Показ: `python -m science_pulse.cli staged [--next]` и `/staged` в пульте.

## Формальные гарантии (Lean 4, `formal/Invariants.lean`)

- `reject_monotone` — повторный гейт не меняет отклонение;
- `rejected_stays_rejected` — отклонённый не возвращается в принятые;
- `published_requires_canon_gate` — публикация возможна только для принятого
  воротами канона поста.

## Проверка

```bash
python -m unittest tests.test_canon_gate -v
python -m science_pulse.cli formal
```

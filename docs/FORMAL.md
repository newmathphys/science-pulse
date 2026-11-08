# Формальные инварианты (Lean 4, машинная проверка)

Документ описывает машинно-проверяемые доказательства safety-инвариантов
Science Pulse на Lean 4.

Файл доказательств: `formal/Invariants.lean` (ядро Lean, без mathlib, без `sorry`).
Код-обёртка: `science_pulse/formal.py` (`check_lean`).
CLI: `python -m science_pulse.cli formal [--json]`.
Тесты: `tests/test_formal.py`.

## Зачем

Инварианты из `docs/INVARIANTS.md` проверяются на данных (`invariants.py`), но
это проверка *наблюдаемого состояния*. Формальные теоремы доказывают свойства
*алгоритмов* для **всех** входов сразу — не только для того, что лежит в БД.
Вместе они дают две линии защиты: доказательство (Lean) + проверка (Python).

## Инструмент

- **Lean 4** (ядро). Проверено на Lean `4.34.0`.
- mathlib **не требуется**: используются только `cases`, `rfl`, `simp`,
  `omega`, `decide`, `by_cases`, `split`.
- Установка: [elan](https://github.com/leanprover/elan) → `lean --version`.

## Доказанные теоремы

| Теорема | Инвариант | Утверждение |
|:--|:--|:--|
| `status_total` | INV-4 | статус всегда один из `ready/publishing/published/failed` |
| `publishStep_idempotent` | INV-1 | повторная публикация не меняет статус |
| `publishStep_not_ready` | INV-4 | после публикации статус ≠ `ready` |
| `publish_requires_ready` | INV-4 | публикация возможна только из `ready` |
| `insertOnce_idempotent` | INV-1 | повторная вставка записи не создаёт дубликат |
| `insertOnce_contains` | INV-2 | после вставки запись присутствует |
| `publish_reduces_ready` | INV-4 | публикация не увеличивает число готовых постов |
| `hamming_7_4_orthogonal` | SIGNAL-1 | `G·Hᵀ ≡ 0 (mod 2)` для кода (7,4) |
| `sample_count` | SIGNAL-2 | счётчик отсчётов `2·B·T` |
| `capacity_monotone` | SIGNAL-3 | табличная ёмкость монотонна по S/N |

Модель:

- `Status` — индуктивный тип (неизвестных статусов нет по построению);
- `publishStep` — `ready → published`, остальные статусы неизменны;
- `insertOnce` / `contains` — модель идемпотентной записи публикации;
- `readyCount` — учёт очереди.

## CRDT-слияние статусов (Join-Semilattice)

Для режима D1-Primary (см. `docs/D1_STATE.md`) законы слияния статусов
доказаны в Lean 4 (без `sorry`):

| Теорема | Закон |
|:--|:--|
| `mergeStatus_idempotent` | `mergeStatus a a = a` |
| `mergeStatus_comm` | `mergeStatus a b = mergeStatus b a` |
| `mergeStatus_assoc` | `mergeStatus (mergeStatus a b) c = mergeStatus a (mergeStatus b c)` |
| `mergeStatus_preserves_published` | `mergeStatus a b = published → a = published ∨ b = published` |

`mergeStatus` выбирает статус с большим `rank`
(`ready 1 < publishing 2 < failed 3 < published 4`), поэтому параллельный
писатель со старым `ready` не может откатить `published`. Это формальная
основа `Storage.merge_snapshot` (Python) и `applyMonotonic` (Worker).

## Запуск

```bash
lean formal/Invariants.lean            # 0 = доказано
python -m science_pulse.cli formal     # обёртка: компилирует и проверяет
python -m science_pulse.cli formal --json
```

`formal` возвращает:

- `0` — доказательства скомпилированы, `sorry` отсутствует;
- `1` — ошибка компиляции (в `--json` — `ok: false`, `stderr`);
- `0` с пометкой в stderr — Lean не установлен (проверка пропущена, это не
  сбой проекта).

## CI

В `.github/workflows/science_pulse.yml`:

- шаг **Lean toolchain (elan)** ставит Lean (`continue-on-error: true`);
- шаг **Verify formal invariants** запускает `cli formal`;
- шаг **Check invariants** запускает `cli invariants` (проверка на данных).

Если Lean в CI не установился, `formal` мягко пропускается и пайплайн не
падает; проверка на данных (`invariants`) остаётся жёстким гейтом.

## Как добавить теорему

1. Добавьте определение и `theorem … := by …` в `formal/Invariants.lean`
   **без `sorry`**.
2. Проверьте: `lean formal/Invariants.lean`.
3. Добавьте строку в таблицу выше и, при необходимости, парную проверку в
   `science_pulse/invariants.py`.
4. `python -m unittest tests.test_formal -v` — тест компилирует файл.

## Ограничения

- Модель абстрактная (типы статусов и списки записей), а не сам SQLite;
  соответствие «модель ↔ БД» обеспечивает `invariants.py` на реальных данных.
- mathlib не подключён: доступны только ядровые тактики.
- В CI версия Lean берётся `stable`; локально проверено на `4.34.0`.


## Стенды теории сигналов

Полные аналитические теоремы Котельникова и Шеннона требуют mathlib, поэтому
в чистом ядре Lean 4 доказаны их **конечные алгебраические ядра**:

- `hamming_7_4_orthogonal` — все 12 пар строк `G` и `H` ортогональны mod 2;
- `sample_count` — число отсчётов при Найквисте `2·B·T`;
- `capacity_monotone` — дискретная модель `C = B·S` монотонна по S/N.

Исполняемые аналоги — `simulate.hamming_7_4`, `kotelnikov_sampling`,
`shannon_capacity`.

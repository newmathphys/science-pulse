# Инварианты состояния (Lean-спецификация + исполняемые проверки)

Документ описывает safety-инварианты Science Pulse: формальную спецификацию и
её исполняемый эквивалент, который проверяет состояние SQLite.

Код: `science_pulse/invariants.py` (`InvariantChecker`).
CLI: `python -m science_pulse.cli invariants [--json]`. Пульт: `/invariants`.
Тесты: `tests/test_invariants.py`.

## Зачем

Публикация идемпотентна, а состояние должно оставаться согласованным при
сбоях (падение сети, повторный запуск крона, ошибка площадки). Инварианты —
это проверяемые утверждения, которые обязаны быть истинны **в любой момент
после завершения команды**. Их нарушение — сигнал, что где-то есть баг.

## Инварианты

| Код | Утверждение | Проверка |
|:--|:--|:--|
| **INV-1** | Для пары `(post_id, platform)` не более одной **успешной** публикации | `GROUP BY … HAVING count > 1` |
| **INV-2** | Любой пост со статусом `published` имеет ≥ 1 успешную публикацию | `NOT EXISTS (… status='ok')` |
| **INV-3** | `card_file_id` не «висит» без успешной Telegram-публикации | `file_id ≠ '' AND NOT EXISTS(telegram ok)` |
| **INV-4** | Статус любого поста принадлежит известному множеству | `status NOT IN (ready, publishing, published, failed)` |
| **INV-5** | `seen.simhash` в формате `0x…` (16 hex) или legacy-десятичном | регулярное выражение |
| **INV-6** | Нет «сирот»: `metrics`/`publications` всегда ссылаются на существующий пост | `NOT EXISTS (… posts)` |

## Замечание о INV-3 (реальный случай)

На боевой базе нашёлся пост, опубликованный в Telegram (`message_id` есть,
`status='ok'`), но **без** `card_file_id` — это самый первый тестовый пост
(и/или текстовый fallback, когда `sendPhoto` не сработал и пост ушёл текстом).
Это **легитимное** состояние: Telegram может вернуть `ok` без фото, поэтому
требовать `file_id` для любой Telegram-публикации неверно. INV-3 проверяет
обратное, всегда истинное свойство — «висячего» `file_id` быть не должно.

## Формальная спецификация (Lean 4)

Инварианты, сводимые к свойствам **алгоритмов** (статусная машина, идемпотентная
вставка, учёт очереди), доказаны формально в `formal/Invariants.lean`
(ядро Lean, без `mathlib`, **без `sorry`**). Подробности и запуск — `docs/FORMAL.md`.

Доказанные теоремы и их соответствие кодам:

| Теорема Lean | Инвариант |
|:--|:--|
| `status_total` | INV-4 |
| `publishStep_idempotent` | INV-1 |
| `publishStep_not_ready` | INV-4 |
| `publish_requires_ready` | INV-4 |
| `insertOnce_idempotent` | INV-1 |
| `insertOnce_contains` | INV-2 |
| `publish_reduces_ready` | INV-4 |
| `mergeStatus_idempotent` | CRDT (D1-Primary) |
| `mergeStatus_comm` | CRDT (D1-Primary) |
| `mergeStatus_assoc` | CRDT (D1-Primary) |
| `mergeStatus_preserves_published` | INV-1 / CRDT |

Модель в Lean — абстрактная (типы `Status`, списки записей), а соответствие
«модель ↔ реальная БД» обеспечивает `InvariantChecker` на данных. То есть:

- **Lean** доказывает свойства алгоритмов для всех входов;
- **`invariants.py`** проверяет фактическое состояние SQLite.

Вместе — две линии защиты. Машинная проверка:

```bash
lean formal/Invariants.lean
python -m science_pulse.cli formal
```

## Запуск

```bash
python -m science_pulse.cli invariants
python -m science_pulse.cli invariants --json
```

- Код возврата `0` — все инварианты держатся; `1` — есть нарушения (печатаются
  в stderr с кодом и деталями).
- В пульте — `/invariants` (показывает `✅` или список нарушений).

## Как добавить инвариант

1. Добавьте метод `_invN_…` в `InvariantChecker` и зарегистрируйте его в
   списке `checks`.
2. Добавьте проверку в таблицу выше и, при желании, утверждение в Lean-эскиз.
3. Добавьте тест в `tests/test_invariants.py` (успешный и «ломающий» кейс).

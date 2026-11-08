# SCM Knowledge Base

`data/knowledge.db` — документальная память SCM. Это **не** замена NYUUI и не
второй индекс корпуса: только документы SCM, утверждения, заметки, решения,
метрики и связи.

## 1. Команды

```bash
python -m science_pulse.cli knowledge index
python -m science_pulse.cli knowledge search "формула"
python -m science_pulse.cli knowledge stats
python -m science_pulse.cli knowledge integrity
python -m science_pulse.cli knowledge claim "Текст" --source "docs/..." --status HYPOTHESIS
python -m science_pulse.cli knowledge note "Заметка" --source "run/..."
python -m science_pulse.cli knowledge decisions
python -m science_pulse.cli knowledge export
```

`./sp knowledge ...` — то же через вход оператора.

## 2. Схема

| Таблица | Что хранит |
|:--|:--|
| `documents` | путь, заголовок, тип, текст, sha256, дата |
| `documents_fts` | FTS5-поиск по заголовку и тексту |
| `claims` | утверждения: `PROVEN/EMPIRIC/HYPOTHESIS/REFUTED/UNPROVEN`, источник, подпись |
| `notes` | заметки агента/оператора, по умолчанию `UNPROVEN` |
| `decisions` | принятые решения (ADR) |
| `concepts` | термины/концепты |
| `links` | связи между узлами |
| `metrics` | измерения (подписчики, охват, конверсия) |

## 3. Правило истины

```text
текст агента            → UNPROVEN
источник + проверка     → EMPIRIC
оракул/подпись владельца → PROVEN
```

`owner_signed=1` ставит только владелец. Агент не имеет права объявлять
`PROVEN` без оракула.

## 4. Индексация

`knowledge index` обходит:

- `README.md`, `AGENTS.md`, `SCM.md`;
- `docs/**/*.md`;
- `config.yaml`.

Повторная индексация обновляет только изменённые файлы по `sha256`.

## 5. Integrity

`knowledge integrity` проверяет:

- число документов = число FTS-строк;
- все пути документов существуют;
- нет `PROVEN/EMPIRIC` без подписи владельца.

Ненулевой код возврата — сигнал оператору, а не «мелкое предупреждение».

## 6. Что не кладём в базу

- секреты, токены, пароли;
- чужие корпуса и персональные данные;
- «факты» без источника;
- непроверенные утверждения со статусом `PROVEN`.

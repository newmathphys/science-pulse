# Runbooks SCM

## 1. Первый запуск

```bash
cd "/home/mrbritneyxxx/Рабочий стол/ПРОЕКТТ SCM"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m science_pulse.cli init
python -m science_pulse.cli run --dry-run
python -m science_pulse.cli site
```

## 2. Ежедневный запуск

```bash
./sp enter
./sp publish
./sp check
```

Автопилот: GitHub Actions (`science_pulse.yml`) и/или `./sp daemon`.

## 3. Пульт

```bash
./sp admin
```

Остановка:

```bash
./sp stop
```

## 4. Публикация

```bash
python -m science_pulse.cli preflight --no-media
python -m science_pulse.cli publish
```

Проверить:

```sql
SELECT status, COUNT(*) FROM posts GROUP BY status;
SELECT platform, status, external_id, url FROM publications ORDER BY id DESC LIMIT 5;
```

## 5. Backup

D1-Primary: состояние живёт в Cloudflare D1, локальный SQLite — кэш.

```bash
python -m science_pulse.cli checkpoint
python -m science_pulse.cli state --push
python -m science_pulse.cli knowledge export
```

CI дополнительно кладёт `state_backup.sqlite.gz` в GitHub Release
`state-backup`. R2-бэкап — опционально, если включён на аккаунте.

Восстановление кэша из D1:

```bash
python -m science_pulse.cli state --pull
```

Если D1 недоступен, используйте последний `state_backup.sqlite.gz` из
Releases и `python -m science_pulse.cli state --export`.

## 6. Восстановление

```bash
cp backups/science-YYYY...db data/science.db
python -m science_pulse.cli checkpoint
python -m science_pulse.cli status
python -m science_pulse.cli verify
```

Если база потеряна, но канал жив:

```bash
python -m science_pulse.cli recover-from-channel
```

## 7. Сайт

```bash
python -m science_pulse.cli site
```

GitHub Pages обновляется пушем в `main` через Actions → `gh-pages`.

## 8. Knowledge Base

```bash
python -m science_pulse.cli knowledge index
python -m science_pulse.cli knowledge stats
python -m science_pulse.cli knowledge integrity
```

Если integrity красный:

1. `index` — переиндексировать;
2. проверить удалённые документы;
3. снять/подписать утверждения без источника.

## 9. Откат

```bash
git log --oneline -5
git revert <commit>
# или
git reset --hard <green-commit>   # только с явного разрешения владельца
```

Правило: сначала тест, потом откат. «Зелёный» коммит — тот, где `./sp check`
прошёл.

## 10. Аварийные сигналы

| Симптом | Действие |
|:--|:--|
| `failed` растёт | `preflight`, `doctor`, `quarantine` |
| сайт 404 | `site`, проверить `gh-pages` |
| пульт молчит | проверить `data/admin.pid`, перезапустить |
| голос не тот | проверить `voice.engine`, `google_fallback=false` |
| knowledge integrity красный | `knowledge index` + разобрать issues |

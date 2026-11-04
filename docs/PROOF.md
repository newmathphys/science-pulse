# Вычислительный паспорт поста (`post_proof.py`)

Три независимых доказательства того, что пост не «выдуман». Модуль:
`science_pulse/post_proof.py`. Тесты: `tests/test_post_proof.py`.

## Что считает

```python
build_post_proof(post: Post, prev_merkle: str = "0" * 64) -> dict
```

1. **`computed_example`** (`str`) — точный расчёт:
   - **CODATA**: если в `meta["constants_used"]` есть `c`, `G`, `h`, `hbar`, `k_B`
     или `e`, берутся эталонные значения из `scipy.constants` (через реестр
     `science_pulse/constants.py`): `"Эталон CODATA: c = 299792458 м/с"`;
   - **формула**: если выражение парсится безопасным `plotting.parse_expression`,
     считаются значения в точках `x = 0, 1, 2`: `"Точный расчёт: x(0) = 1, …"`.
   Части объединяются через `"; "`.
2. **`code_proof`** (`{ok: bool, summary: str}`) — песочница кода поста:
   - `ast.parse` (синтаксис);
   - запрет `Import`/`ImportFrom` вне белого списка (`math`, `typing`,
     `itertools`, `functools`, `decimal`, `fractions`, `statistics`, `random`);
   - запрет вызовов `open`, `eval`, `exec`, `compile`, `__import__`, `input`,
     `globals`, `locals`, `vars`, `exit`, `quit`, `breakpoint`;
   - запуск в изолированном интерпретаторе
     `subprocess.run([sys.executable, "-I", "-c", code], timeout=1.5)`
     с замером времени: `"AST & Run OK (1234 мкс)"`.
3. **`merkle_hash`** (`str`, 64 hex) — каноническая печать версии:
   `sha256(f"v1|{prev_merkle}|{post.id}|{post.domain}|{formula_plain}")`.

Результат пишется в `post.meta["proof"]`.

## Где показывается

- **Подпись Telegram** (`build_rich_telegram_caption`): строка
  `🔢 <computed_example>` (в пределах лимита 1024).
- **Страница поста** (`site.py::_proof_html`): блок «Вычислительный паспорт» —
  точный расчёт, вердикт по коду (`✓`/`✗`), первые 32 hex merkle-печати.

## Проверка

```bash
python -m unittest tests.test_post_proof -v
```

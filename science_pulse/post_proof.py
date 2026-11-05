"""Вычислительный паспорт поста: CODATA-расчёт, песочница кода и merkle-цепь.

Три независимых доказательства того, что пост не «выдуман»:

1. **`computed_example`** — точный расчёт: эталонные значения констант из
   `scipy.constants` (CODATA) и/или значения формулы в точках ``x = 0, 1, 2``
   (через безопасный SymPy-парсер `plotting.parse_expression`);
2. **`code_proof`** — проверка кода поста: `ast.parse` + запуск в изолированном
   интерпретаторе (`python -I -c …`, таймаут 1.5 с) с замером времени;
3. **`merkle_hash`** — детерминированная печать (64 hex) для цепи версий.

Результат пишется в ``post.meta["proof"]`` и попадает строкой в подпись.
"""
from __future__ import annotations

import ast
import hashlib
import subprocess
import sys
import time
from typing import Any, Dict, List

from .models import Post

# Импорты, которые не дают доступа к файловой системе и сети.
ALLOWED_IMPORTS = {"math", "typing", "itertools", "functools", "decimal", "fractions", "statistics", "random"}
# Вызовы, недопустимые в песочнице.
FORBIDDEN_CALLS = {
    "open", "eval", "exec", "compile", "__import__", "input",
    "globals", "locals", "vars", "exit", "quit", "breakpoint",
}
# Константы CODATA, которые упоминаются в `meta["constants_used"]`.
CODATA_SYMBOLS = ("c", "G", "h", "hbar", "k_B", "e")


def merkle_hash(post: Post, prev_merkle: str = "0" * 64) -> str:
    """Печать поста (64 hex): ``sha256("v1|prev|id|domain|formula_plain")``."""
    formula = (getattr(post, "formula_plain", "") or "").strip()
    payload = f"v1|{prev_merkle}|{post.id}|{post.domain}|{formula}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _codata_line(post: Post) -> str:
    """Строка с точными значениями использованных констант (scipy CODATA)."""
    meta = getattr(post, "meta", {}) or {}
    used = [str(symbol) for symbol in (meta.get("constants_used") or [])]
    picked = [symbol for symbol in used if symbol in CODATA_SYMBOLS]
    if not picked:
        return ""
    from .constants import _BY_SYMBOL, format_value

    parts: List[str] = []
    for symbol in picked[:3]:
        entry = _BY_SYMBOL.get(symbol)
        if entry:
            parts.append(f"{symbol} = {format_value(float(entry['value']))} {entry['unit']}")
    return "Эталон CODATA: " + "; ".join(parts) if parts else ""


def _formula_line(post: Post) -> str:
    """Строка с точными значениями формулы в точках ``x = 0, 1, 2``."""
    from .plotting import parse_expression

    expression = (getattr(post, "formula_plain", "") or getattr(post, "formula_latex", "") or "").strip()
    if not expression:
        return ""
    try:
        import sympy as sp

        parsed = parse_expression(expression)
    except Exception:
        return ""
    names = sorted(str(symbol) for symbol in parsed.free_symbols)
    primary = "x" if "x" in names else (names[0] if names else "")
    if not primary:
        return ""
    substitutions = {sp.Symbol(name, real=True): 1.0 for name in names if name != primary}
    variable = sp.Symbol(primary, real=True)
    values: List[str] = []
    for point in (0, 1, 2):
        try:
            value = float(parsed.subs(substitutions).subs(variable, point))
        except Exception:
            value = float("nan")
        values.append(f"{primary}({point}) = {value:.6g}")
    return "Точный расчёт: " + ", ".join(values)


def _code_proof(code: str) -> Dict[str, Any]:
    """AST-проверка и запуск кода в изолированном интерпретаторе."""
    source = (code or "").strip()
    if not source:
        return {"ok": True, "summary": "кода нет"}
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return {"ok": False, "summary": f"AST: {exc.msg}"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name.split(".")[0] for alias in node.names]
            if any(name not in ALLOWED_IMPORTS for name in names):
                return {"ok": False, "summary": f"запрещённый импорт: {', '.join(names)}"}
        if isinstance(node, ast.ImportFrom):
            module = str(node.module or "").split(".")[0]
            if module and module not in ALLOWED_IMPORTS:
                return {"ok": False, "summary": f"запрещённый импорт: {module}"}
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in FORBIDDEN_CALLS:
                return {"ok": False, "summary": f"запрещённый вызов: {func.id}()"}
            if isinstance(func, ast.Attribute) and func.attr in FORBIDDEN_CALLS:
                return {"ok": False, "summary": f"запрещённый вызов: .{func.attr}()"}
    started = time.perf_counter()
    try:
        result = subprocess.run(
            [sys.executable, "-I", "-c", source],
            timeout=1.5, capture_output=True, text=True,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "summary": "таймаут 1.5 с"}
    except Exception as exc:  # pragma: no cover - защитный контур
        return {"ok": False, "summary": f"не запустилось: {exc}"}
    elapsed_us = int((time.perf_counter() - started) * 1_000_000)
    if result.returncode != 0:
        tail = (result.stderr or "").strip().splitlines()
        return {"ok": False, "summary": f"ошибка исполнения: {tail[-1][:80] if tail else 'код возврата 1'}"}
    return {"ok": True, "summary": f"AST & Run OK ({elapsed_us} мкс)"}


def build_post_proof(post: Post, prev_merkle: str = "0" * 64) -> Dict[str, Any]:
    """Собирает вычислительный паспорт и пишет его в ``post.meta["proof"]``."""
    from .challenge import build_challenge

    parts = [part for part in (_codata_line(post), _formula_line(post)) if part]
    proof: Dict[str, Any] = {
        "computed_example": "; ".join(parts),
        "code_proof": _code_proof(getattr(post, "code", "") or ""),
        "merkle_hash": merkle_hash(post, prev_merkle),
        "challenge": build_challenge(post),
    }
    meta = getattr(post, "meta", None)
    if isinstance(meta, dict):
        meta["proof"] = proof
        meta["challenge"] = proof["challenge"]
    return proof


def format_proof_line(proof: Dict[str, Any]) -> str:
    """Строка для подписи: ``Верификация: <computed_example>`` (если расчёт есть)."""
    example = str((proof or {}).get("computed_example") or "").strip()
    return f"Верификация: {example}" if example else ""


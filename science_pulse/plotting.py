from __future__ import annotations

import io
import math
import re
from typing import Any, Dict, Optional

import numpy as np

try:
    import sympy as sp
    from sympy.parsing.sympy_parser import (
        implicit_multiplication_application,
        parse_expr,
        standard_transformations,
    )
    from sympy.printing.jscode import jscode

    _HAS_SYMPY = True
except Exception:  # pragma: no cover
    sp = None  # type: ignore
    _HAS_SYMPY = False
    jscode = None  # type: ignore

SAFE_LOCALS: Dict[str, Any] = {}
if _HAS_SYMPY:
    SAFE_LOCALS = {
        "x": sp.Symbol("x", real=True),
        "t": sp.Symbol("t", real=True),
        "n": sp.Symbol("n", real=True),
        "a": sp.Symbol("a", real=True),
        "b": sp.Symbol("b", real=True),
        "omega": sp.Symbol("omega", real=True),
        "gamma": sp.Symbol("gamma", real=True),
        "sin": sp.sin,
        "cos": sp.cos,
        "tan": sp.tan,
        "exp": sp.exp,
        "log": sp.log,
        "ln": sp.log,
        "sqrt": sp.sqrt,
        "Abs": sp.Abs,
        "sinh": sp.sinh,
        "cosh": sp.cosh,
        "tanh": sp.tanh,
        "pi": sp.pi,
        "E": sp.E,
        "I": sp.I,
    }

BLOCKED = ("__", "import", "lambda", "eval", "exec", "open", "os.", "sys.", "subprocess")


class ExpressionError(ValueError):
    pass


def parse_expression(expression: str, extra_locals: Optional[Dict[str, Any]] = None):
    if not _HAS_SYMPY:
        raise ExpressionError("SymPy не установлен")
    clean = (expression or "").replace("^", "**").strip()
    clean = clean.replace("\\left", "").replace("\\right", "")
    clean = re.sub(r"\\frac\{([^{}]+)\}\{([^{}]+)\}", r"((\1)/(\2))", clean)
    clean = re.sub(r"\\sqrt\{([^{}]+)\}", r"sqrt(\1)", clean)
    for command in ("sin", "cos", "tan", "exp", "log", "ln", "sqrt", "sinh", "cosh", "tanh"):
        clean = clean.replace("\\" + command, command)
    clean = clean.replace("\\pi", "pi").replace("\\cdot", "*").replace("\\times", "*")
    clean = re.sub(r"^\s*[a-zA-Z]\s*\([^)]*\)\s*=", "", clean)
    if "=" in clean:
        left, right = clean.split("=", 1)
        left, right = left.strip(), right.strip()
        has_left = bool(re.search(r"\b[xt]\b", left))
        has_right = bool(re.search(r"\b[xt]\b", right))
        if has_left and not has_right:
            clean = left
        elif has_right and not has_left:
            clean = right
        elif has_left and has_right:
            clean = f"({left}) - ({right})"
        else:
            clean = right or left
    if any(token in clean for token in BLOCKED):
        raise ExpressionError("выражение содержит запрещённый токен")
    if len(clean) > 300:
        raise ExpressionError("выражение слишком длинное")
    transformations = standard_transformations + (implicit_multiplication_application,)
    locals_map = dict(SAFE_LOCALS)
    if extra_locals:
        locals_map.update(extra_locals)
    try:
        return parse_expr(clean, local_dict=locals_map, transformations=transformations, evaluate=True)
    except Exception as exc:
        raise ExpressionError(f"не удалось разобрать выражение: {exc}") from exc


def evaluate_curve(
    expression: str,
    x_min: float = -6.0,
    x_max: float = 6.0,
    points: int = 700,
    include_derivative: bool = True,
) -> Dict[str, Any]:
    expr = parse_expression(expression)
    x_symbol = SAFE_LOCALS["x"]
    substitutions = {symbol: 1.0 for symbol in expr.free_symbols if symbol != x_symbol}
    sliced = expr.subs(substitutions)
    try:
        function = sp.lambdify(x_symbol, sliced, modules=["numpy"])
    except Exception as exc:
        raise ExpressionError(f"не удалось скомпилировать выражение: {exc}") from exc

    grid = np.linspace(x_min, x_max, points, dtype=np.complex128) + 1e-9j
    try:
        values = function(grid)
    except Exception:
        values = np.array([function(value) for value in grid], dtype=np.complex128)
    if np.ndim(values) == 0:
        values = np.full(points, complex(values), dtype=np.complex128)

    re_values = np.clip(np.nan_to_num(np.real(values), nan=0.0, posinf=40.0, neginf=-40.0), -40.0, 40.0)
    im_values = np.clip(np.nan_to_num(np.imag(values), nan=0.0, posinf=40.0, neginf=-40.0), -40.0, 40.0)
    derivative_values = None
    if include_derivative:
        try:
            derivative = sp.diff(sliced, x_symbol)
            derivative_fn = sp.lambdify(x_symbol, derivative, modules=["numpy"])
            derivative_raw = derivative_fn(grid)
            if np.ndim(derivative_raw) == 0:
                derivative_raw = np.full(points, complex(derivative_raw), dtype=np.complex128)
            derivative_values = np.clip(
                np.nan_to_num(np.real(derivative_raw), nan=0.0, posinf=40.0, neginf=-40.0),
                -40.0,
                40.0,
            )
        except Exception:
            derivative_values = None

    index = int(np.argmax(np.abs(re_values))) if len(re_values) else 0
    return {
        "x": np.real(grid),
        "re_y": re_values,
        "im_y": im_values,
        "der_y": derivative_values,
        "has_imaginary": bool(np.max(np.abs(im_values)) > 1e-3),
        "poi": (round(float(np.real(grid[index])), 3), round(float(re_values[index]), 3)),
        "latex": sp.latex(expr),
        "plain": str(expr),
        "js_fn": _js_function(expr),
    }


def _js_function(expr) -> str:
    try:
        symbols = sorted(str(symbol) for symbol in expr.free_symbols)
        primary = "x" if "x" in symbols else (symbols[0] if symbols else "x")
        sliders = [symbol for symbol in symbols if symbol != primary]
        body = jscode(sp.simplify(expr)) if jscode else "0"
        return f"({', '.join([primary] + sliders)}) => ({body})"
    except Exception:
        return "(x) => (0)"


def plot_png(
    expression: str,
    width: int = 1200,
    height: int = 620,
    background: str = "#07090F",
    accent: str = "#00F5D4",
    imaginary: str = "#7B2CBF",
) -> bytes:
    """График Re/Im в PNG. Используется как резервный визуал."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    curve = evaluate_curve(expression)
    fig, axis = plt.subplots(figsize=(width / 100, height / 100), dpi=100)
    fig.patch.set_facecolor(background)
    axis.set_facecolor(background)
    axis.plot(curve["x"], curve["re_y"], color=accent, linewidth=2.8, label="Re f(x)")
    if curve["has_imaginary"]:
        axis.plot(curve["x"], curve["im_y"], color=imaginary, linewidth=2.0, linestyle="--", label="Im f(x)")
        axis.legend(facecolor="#111622", edgecolor="#222834", labelcolor="#FFFFFF")
    axis.grid(True, linestyle="--", alpha=0.15, color="#FFFFFF")
    for spine in axis.spines.values():
        spine.set_edgecolor("#222834")
    axis.tick_params(colors="#8A94A6")
    fig.tight_layout()
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", facecolor=background, transparent=False)
    plt.close(fig)
    return buffer.getvalue()


def decorative_curve(seed: int, points: int = 240) -> tuple[np.ndarray, np.ndarray]:
    """Детерминированная декоративная кривая для карточек без формулы."""
    x = np.linspace(-6.0, 6.0, points)
    phase = (seed % 360) * math.pi / 180.0
    y = np.sin(1.7 * x + phase) * np.exp(-(x**2) / 18.0) + 0.35 * np.sin(4.1 * x + phase / 2)
    return x, y

from __future__ import annotations

import logging
import math
from typing import Any, Dict, List

from ..models import Post, make_id
from ..text import formula_to_unicode, truncate
from .base import Source

LOGGER = logging.getLogger(__name__)

try:
    import sympy as sp

    _X = sp.Symbol("x", real=True)
except Exception:  # pragma: no cover - SymPy обязателен в requirements
    sp = None  # type: ignore
    _X = None

try:
    from scipy import constants as scipy_constants

    CODATA_KEYS = sorted(scipy_constants.physical_constants.keys())
except Exception:  # pragma: no cover
    scipy_constants = None  # type: ignore
    CODATA_KEYS = [
        "speed of light in vacuum",
        "Planck constant",
        "Boltzmann constant",
        "elementary charge",
        "electron mass",
        "Avogadro constant",
        "fine-structure constant",
    ]


class OfflineBunkerSource(Source):
    """Детерминированный генератор без сети (Эшелон 3).

    Комбинирует ортогональные полиномы математической физики и константы
    CODATA по индексу эпохи. Одинаковый cycle даёт одинаковый пост, разные
    циклы — разные комбинации.
    """

    name = "offline"
    domains = ("math", "physics", "cs")
    tier = "offline"

    def fetch(self, limit: int = 1, cycle: int = 0) -> List[Post]:
        posts: List[Post] = []
        for offset in range(max(1, limit)):
            posts.append(self.synthesize(cycle + offset))
        return posts

    def synthesize(self, cycle_index: int) -> Post:
        domain = ("math", "physics", "cs")[cycle_index % 3]
        n = (cycle_index % 6) + 2
        constant_key = CODATA_KEYS[(cycle_index * 37) % len(CODATA_KEYS)]
        constant_value, constant_unit, constant_uncertainty = self._constant(constant_key)

        if sp is None:
            return self._static_fallback(cycle_index, domain, constant_key, constant_value, constant_unit)

        catalog = [
            {
                "domain": "physics",
                "title": f"Квантовый осциллятор и полином Эрмита H_{n}(x)",
                "hook": "Почему даже при абсолютном нуле квантовая частица не может замереть?",
                "expr": sp.hermite(n, _X) * sp.exp(-(_X**2) / 2),
                "insight": "Нулевые колебания вакуума запрещают частице иметь одновременно точный импульс и координату.",
            },
            {
                "domain": "math",
                "title": f"Минимаксная аппроксимация и полином Чебышёва T_{n}(x)",
                "hook": "Как вычислить сложную функцию в процессоре с минимальной ошибкой?",
                "expr": sp.chebyshevt(n, _X),
                "insight": "Экстремумы полинома Чебышёва распределяют погрешность равномерно на отрезке [-1, 1].",
            },
            {
                "domain": "physics",
                "title": f"Радиальная орбиталь атома и полином Лагерра L_{n}(x)",
                "hook": "В каких сферических зонах вокруг ядра вероятность встретить электрон равна нулю?",
                "expr": sp.laguerre(n, _X) * sp.exp(-_X / 2) * (_X**2),
                "insight": "Корни полинома Лагерра задают узловые сферы квантового облака электрона.",
            },
            {
                "domain": "physics",
                "title": f"Мультипольный потенциал и полином Лежандра P_{n}(x)",
                "hook": "Как описать форму гравитационного поля несферической планеты?",
                "expr": sp.legendre(n, _X),
                "insight": "Полиномы Лежандра образуют ортогональный базис разложения потенциала в сферических координатах.",
            },
            {
                "domain": "cs",
                "title": f"Спектральный синтез Фурье и феномен Гиббса ({n} гармоник)",
                "hook": "Почему на резких скачках сигнала возникает неустранимый выброс около 9%?",
                "expr": sum(sp.sin((2 * k - 1) * _X) / (2 * k - 1) for k in range(1, n + 2)),
                "insight": "Конечная сумма гладких гармоник даёт перерегулирование Гиббса у точки разрыва.",
            },
            {
                "domain": "physics",
                "title": f"Цилиндрические волны и функция Бесселя J_{n}(x)",
                "hook": "Почему круглая мембрана барабана звучит не так, как прямоугольная?",
                "expr": sp.besselj(n, _X),
                "insight": "Функции Бесселя задают радиальные моды круглых мембран и волноводов.",
            },
            {
                "domain": "math",
                "title": f"Ортогональные полиномы Якоби P_{n}(x)",
                "hook": "Как единая формула описывает сразу Лежандра, Чебышёва и Гегенбауэра?",
                "expr": sp.jacobi(n, 0, 0, _X),
                "insight": "Семейство Якоби обобщает классические ортогональные полиномы через два параметра веса.",
            },
            {
                "domain": "physics",
                "title": f"Полиномы Гегенбауэра и многомерные гармоники C_{n}(x)",
                "hook": "Что меняется в ортогональном базисе при переходе к четырём измерениям?",
                "expr": sp.gegenbauer(n, 1, _X),
                "insight": "Полиномы Гегенбауэра возникают при разложении по сферическим гармоникам в размерности d.",
            },
            {
                "domain": "physics",
                "title": f"Присоединённые полиномы Лагерра L_{n}(x)",
                "hook": "Как квантовое число орбитального момента меняет форму электронного облака?",
                "expr": sp.assoc_laguerre(n, 0, _X) * sp.exp(-_X / 2),
                "insight": "Присоединённые полиномы Лагерра описывают радиальную часть водородоподобных орбиталей.",
            },
            {
                "domain": "math",
                "title": f"Полиномы Чебышёва второго рода U_{n}(x)",
                "hook": "Почему аппроксимация Чебышёва устойчивее обычного разложения Тейлора?",
                "expr": sp.chebyshevu(n, _X),
                "insight": "Полиномы U_n минимизируют осцилляции остатка и связаны с ядром Дирихле.",
            },
        ]

        item = catalog[cycle_index % len(catalog)]
        if item["domain"] != domain:
            # Сохраняем обе оси: дисциплину поста и физический смысл формулы.
            domain = item["domain"]
        expr = sp.simplify(item["expr"])
        derivative = sp.diff(expr, _X)
        latex = sp.latex(expr)
        plain = str(expr)
        pretty = sp.pretty(expr, use_unicode=True)
        constant_text = f"{constant_key} = {constant_value:.6e} {constant_unit}".strip()
        # Производная: без слепой обрезки посреди выражения (иначе читатель видит
        # «не закрыта скобка» и контур качества заворачивает пост в карантин).
        derivative_text = formula_to_unicode(sp.sstr(derivative), 120)
        derivative_line = (
            f"Производная: d/dx f(x) = {derivative_text}.\n" if len(derivative_text) <= 120
            else "Производная вычисляется символьным ядром SymPy — запускаемый код ниже.\n"
        )
        readable = formula_to_unicode(plain, 90)
        readable_short = readable if len(readable) <= 90 else ""
        # Тело поста должно оставаться содержательным: смысл + производная + честная
        # рамка проверки. Случайную константу CODATA в тело не подставляем — она не
        # связана с формулой (раньше выбиралась по индексу эпохи).
        closing = (
            f"Формула {readable_short} проверяется точным расчётом: значения считает SymPy, "
            "эталонные константы берутся из CODATA. Обращения к языковой модели нет — "
            "всё, что видит читатель, воспроизводится запуском кода ниже."
            if readable_short else
            "Формула проверяется точным расчётом: значения считает SymPy, эталонные "
            "константы берутся из CODATA. Обращения к языковой модели нет — всё, что "
            "видит читатель, воспроизводится запуском кода ниже."
        )
        explanation = f"{item['insight']}\n{derivative_line}{closing}"

        post = Post(
            id=make_id(self.name, f"{cycle_index}:{item['title']}"),
            domain=domain,
            title=item["title"],
            hook=item["hook"],
            body=explanation,
            formula_latex=latex,
            formula_plain=plain,
            code=(
                "import sympy as sp\n"
                "x = sp.Symbol('x', real=True)\n"
                f"f = {plain}\n"
                f"print(sp.diff(f, x))\n"
            ),
            source_name="Offline Bunker / SymPy + CODATA",
            source_url="",
            tier=self.tier,
            meta={
                "cycle": cycle_index,
                "codata_key": constant_key,
                "codata_value": constant_value,
                "codata_unit": constant_unit,
                "plot_expr": plain,
                "pretty": pretty,
            },
        )
        post.quality = post.quality_score()
        return post

    @staticmethod
    def _constant(key: str) -> tuple[float, str, float]:
        if scipy_constants is not None:
            try:
                value, unit, uncertainty = scipy_constants.physical_constants[key]
                return float(value), str(unit), float(uncertainty)
            except Exception as exc:
                LOGGER.debug("CODATA ключ %s недоступен: %s", key, exc)
        return 1.0, "", 0.0

    @staticmethod
    def _static_fallback(cycle: int, domain: str, key: str, value: float, unit: str) -> Post:
        n = (cycle % 6) + 2
        formula = f"f(x) = sin({n}*x) * exp(-x^2/2)"
        post = Post(
            id=make_id("offline", f"fallback:{cycle}"),
            domain=domain,
            title=f"Волновой пакет и гармоника {n}",
            hook="Как локализовать частицу в пространстве, не потеряв её импульс?",
            body=(
                "Гауссов волновой пакет минимизирует произведение неопределённостей "
                f"координаты и импульса. Эталон CODATA: {key} = {value:.6e} {unit}."
            ),
            formula_latex=formula,
            formula_plain=formula,
            code=f"import numpy as np\nx=np.linspace(-6,6,600)\ny=np.sin({n}*x)*np.exp(-x**2/2)\n",
            source_name="Offline Bunker / static",
            tier="offline",
            meta={"cycle": cycle, "plot_expr": formula.split("=", 1)[-1].strip()},
        )
        post.quality = post.quality_score()
        return post

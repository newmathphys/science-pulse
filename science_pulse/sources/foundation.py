"""Фундаментальный источник: канон, выстроенный по ступеням старта.

Публикация начинается не со случайных постов, а со **Ступени 1** —
корневых законов, на которые потом ссылаются все остальные:

| Ступень | Тема | Узлы канона |
|:--|:--|:--|
| 1 | Зарождение аксиом, алгоритмов и статики | pythagoras, euclid_gcd, archimedes |
| 2 | Координаты, анализ и динамика | newton_gravity, euler_identity |
| 3 | Классика полей и симметрий | fourier_series, maxwell, noether_symmetry |
| 4 | Рождение вычислений | turing_machine, shannon_entropy |
| 5 | Квантовый мир | schrodinger, quantum_tunneling |
| 6 | Прикладные гиганты | insar_ndvi, schwarzschild_light, lj_lorenz |

`FoundationSource` отдаёт узлы в порядке ступеней и добавляет в `meta`
поля `step` и `step_title` — по ним работают `/foundation status` и подпись.
"""
from __future__ import annotations

from typing import Any, Dict, List

from ..models import Post, make_id
from .base import Source
from .history_canon import CANON, HistoryCanonSource

STEP_TITLES: Dict[int, str] = {
    1: "Зарождение аксиом, алгоритмов и статики",
    2: "Координаты, анализ и динамика",
    3: "Классика полей и симметрий",
    4: "Рождение вычислений",
    5: "Квантовый мир",
    6: "Прикладные гиганты",
}

STEP_BY_ID: Dict[str, int] = {
    # Ступень 1 — Зарождение
    "pythagoras": 1,
    "euclid_gcd": 1,
    "archimedes": 1,
    # Ступень 2 — Координаты, алгебра и эксперимент
    "al_khwarizmi": 2,
    "leibniz_boolean": 2,
    "galileo_fall": 2,
    "newton_gravity": 2,
    "trigonometry": 2,
    "binary_memory": 2,
    "harmonic_oscillator": 2,
    # Ступень 3 — Анализ и первые машины
    "newton_calculus": 3,
    "lovelace": 3,
    "bernoulli_flow": 3,
    "euler_identity": 3,
    "logarithm": 3,
    "vectors": 3,
    "matrices": 3,
    "wave_phase": 3,
    # Ступень 4 — Классика полей, статистика и алгоритмы
    "gauss_normal": 4,
    "hoare_sort": 4,
    "boltzmann_entropy": 4,
    "fourier_series": 4,
    "maxwell": 4,
    "noether_symmetry": 4,
    # Ступень 5 — Вычисления и кванты
    "riemann_integral": 5,
    "dijkstra_shortest": 5,
    "planck_quantum": 5,
    "turing_machine": 5,
    "mcculloch_pitts": 4,
    "shannon_entropy": 5,
    "schrodinger": 5,
    "quantum_tunneling": 5,
    # Ступень 6 — Границы знания и прикладные гиганты
    "godel_incompleteness": 6,
    "rsa_crypto": 6,
    "einstein_relativity": 6,
    "insar_ndvi": 6,
    "schwarzschild_light": 6,
    "lj_lorenz": 6,
    # P1.1: опорные мосты
    "trigonometry": 2,
    "binary_memory": 2,
    "harmonic_oscillator": 2,
    "dimensional_analysis": 2,
    "logarithm": 3,
    "vectors": 3,
    "matrices": 3,
    "wave_phase": 3,
    "complex_numbers": 3,
    "derivative": 3,
    "conservation_energy": 3,
    "boolean_logic": 2,
    "finite_automata": 3,
    "recursion": 3,
    "mcculloch_pitts": 4,
    "probability": 4,
    "bayes": 4,
    "number_theory": 4,
    "thermodynamics": 4,
    "electromagnetic_wave": 4,
    "hash_table": 4,
    "graph_algorithms": 4,
    "feedback_control": 4,
    "differential_equations": 5,
    "quantum_uncertainty": 5,
    "information_theory": 5,
    "homeostasis": 5,
    "hadamard_matrices": 5,
    "gravitational_waves": 6,
    "machine_learning": 6,
}


def step_of(canon_id: str) -> int:
    return STEP_BY_ID.get(canon_id, 9)


DOMAIN_ORDER = ("math", "cs", "physics")


def section_of(canon_id: str) -> str:
    """§-номер узла канона: ``<ступень>.<номер внутри ступени>`` (напр. ``1.1``)."""
    node = next((item for item in CANON if item["id"] == canon_id), None)
    if node is None:
        return ""
    step = step_of(canon_id)
    same = sorted(
        [item for item in CANON if step_of(item["id"]) == step],
        key=lambda item: (
            DOMAIN_ORDER.index(item["domain"]) if item["domain"] in DOMAIN_ORDER else 9,
            CANON.index(item),
        ),
    )
    return f"{step}.{same.index(node) + 1}"


def default_prereqs(canon_id: str) -> List[str]:
    """Пререквизиты узла: узлы предыдущей ступени той же дисциплины.

    Гарантирует причинную связность (INV-8): у любого узла ступени > 1 есть
    родитель со строго меньшей ступенью, поэтому в графе нет изолированных
    сирот вне корней Ступени I.
    """
    node = next((item for item in CANON if item["id"] == canon_id), None)
    if node is None:
        return []
    step = step_of(canon_id)
    if step <= 1:
        return []
    same_domain = [
        item["id"] for item in CANON
        if step_of(item["id"]) == step - 1 and item["domain"] == node["domain"]
    ]
    if same_domain:
        return same_domain
    fallback = [item["id"] for item in CANON if step_of(item["id"]) == step - 1]
    return fallback[:1]


def ordered_nodes() -> List[Dict[str, Any]]:
    """Узлы канона, отсортированные по ступеням (внутри ступени — по эпохе)."""
    return sorted(CANON, key=lambda item: (step_of(item["id"]), CANON.index(item)))


class FoundationSource(Source):
    name = "foundation"
    domains = ("math", "physics", "cs")
    tier = "foundation"

    def __init__(self, config: Any = None, http: Any = None):
        super().__init__(config, http)
        self._history = HistoryCanonSource(config, http)

    def fetch(self, limit: int = 2, cycle: int = 0) -> List[Post]:
        nodes = ordered_nodes()
        posts: List[Post] = []
        for offset in range(max(1, limit)):
            index = cycle + offset
            if index >= len(nodes):
                break
            item = nodes[index]
            original_index = CANON.index(item)
            post = self._history._build(item, original_index)
            post.tier = self.tier
            post.source_name = f"Фундамент Науки · {item['scientist']}"
            step = step_of(item["id"])
            post.meta["step"] = step
            post.meta["step_title"] = STEP_TITLES.get(step, "Дополнительно")
            post.meta["section_num"] = section_of(item["id"])
            explicit = [str(value) for value in (item.get("prereq_ids") or []) if str(value).strip()]
            post.meta["prereq_ids"] = explicit or default_prereqs(item["id"])
            post.meta["foundation_id"] = item["id"]
            posts.append(post)
        return posts

    @staticmethod
    def post_id_for(canon_id: str) -> str:
        return make_id("history_canon", canon_id)
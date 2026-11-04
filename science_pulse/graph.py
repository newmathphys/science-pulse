from __future__ import annotations

import heapq
import math
from typing import Any, Dict, List, Sequence, Tuple

from .models import Post
from .sota import SOTAKVExtensions
from .text import keywords

Link = Dict[str, object]

# --- Аналитическая топология диска Пуанкаре D = {w ∈ C : |w| < 1} -------------

# Секторы симметрии Z3: центр угла для каждой дисциплины (радианы).
SECTOR_CENTERS: Dict[str, float] = {
    "math": math.pi / 2,          # 90°
    "cs": 7 * math.pi / 6,        # 210°
    "physics": 11 * math.pi / 6,  # 330°
}
SECTOR_WIDTH = math.pi / 3        # 60° на дисциплину


def poincare_radius(tier: int) -> float:
    """Радиус ступени ``k`` в диске: ``tanh((k − 0.82)/2.8)``.

    Сдвиг 0.82 даёт ``r(1) ≈ 0.064 > 0`` — три аксиомы Ступени I образуют
    правильный треугольник вокруг центра, не слипаясь в точку (0, 0).
    """
    return math.tanh((float(tier) - 0.82) / 2.8)


def poincare_angle(domain: str, index: int, total: int) -> float:
    """Угол узла внутри сектора дисциплины (регулярный квант ``π/3M``)."""
    center = SECTOR_CENTERS.get(domain, math.pi / 2)
    if total <= 0:
        return center
    return center + (index - (total - 1) / 2.0) * (SECTOR_WIDTH / total)


def conformal_factor(radius: float) -> float:
    """Конформный фактор метрики: ``Λ(r) = 4 / (1 − r²)²``."""
    r = min(abs(float(radius)), 0.999999)
    return 4.0 / ((1.0 - r * r) ** 2)


def hyperbolic_distance(u: Tuple[float, float], v: Tuple[float, float]) -> float:
    """Точное расстояние Лобачевского (кросс-соотношение) в диске Пуанкаре."""
    dx, dy = u[0] - v[0], u[1] - v[1]
    numerator = 2.0 * (dx * dx + dy * dy)
    denominator = (1.0 - (u[0] ** 2 + u[1] ** 2)) * (1.0 - (v[0] ** 2 + v[1] ** 2))
    if denominator <= 0:
        return float("inf")
    return math.acosh(max(1.0, 1.0 + numerator / denominator))


def max_hyperbolic_jump(tier: int) -> float:
    """Верхняя граница когнитивного скачка между ступенями ``tier−1`` и ``tier``.

    Это расстояние между двумя точками радиусов ``r(tier−1)`` и ``r(tier)``,
    разнесёнными в противоположные стороны диска (наихудший случай).
    """
    inner = poincare_radius(max(1, int(tier) - 1))
    outer = poincare_radius(int(tier))
    numerator = 2.0 * (inner + outer) ** 2
    denominator = (1.0 - inner ** 2) * (1.0 - outer ** 2)
    return math.acosh(max(1.0, 1.0 + numerator / denominator))


def canon_coordinates(nodes: Sequence[Dict[str, Any]]) -> Dict[str, Tuple[float, float]]:
    """Координаты узлов канона: радиус по ступени, угол по сектору дисциплины."""
    grouped: Dict[Tuple[int, str], List[str]] = {}
    for node in nodes:
        grouped.setdefault((int(node.get("tier") or 1), str(node.get("domain") or "math")), []).append(
            str(node.get("id"))
        )
    coords: Dict[str, Tuple[float, float]] = {}
    for (tier, domain), ids in grouped.items():
        ordered = sorted(ids)
        radius = poincare_radius(tier)
        total = len(ordered)
        for index, node_id in enumerate(ordered):
            angle = poincare_angle(domain, index, total)
            coords[node_id] = (radius * math.cos(angle), radius * math.sin(angle))
    return coords


def canon_edges(nodes: Sequence[Dict[str, Any]]) -> List[Tuple[str, str]]:
    """Рёбра DAG канона: ``prereq_ids`` → узел (родитель → потомок)."""
    edges: List[Tuple[str, str]] = []
    for node in nodes:
        target = str(node.get("id"))
        for parent in node.get("prereq_ids") or []:
            edges.append((str(parent), target))
    return edges


def find_geodesic_path(
    edges: Sequence[Tuple[str, str]],
    coords: Dict[str, Tuple[float, float]],
    roots: Sequence[str],
    target: str,
) -> List[str]:
    """Маршрут наименьшего когнитивного сопротивления (Дейкстра по d_ℍ).

    Ищет кратчайшую по сумме гиперболических длин цепочку пререквизитов
    от корней Ступени I до целевого узла. Возвращает ``[]``, если пути нет.
    """
    adjacency: Dict[str, List[str]] = {}
    for source, destination in edges:
        adjacency.setdefault(source, []).append(destination)
    best: Dict[str, float] = {}
    previous: Dict[str, str] = {}
    heap: List[Tuple[float, str]] = []
    for root in roots:
        if root in coords:
            best[root] = 0.0
            heapq.heappush(heap, (0.0, root))
    while heap:
        distance, node = heapq.heappop(heap)
        if distance > best.get(node, float("inf")):
            continue
        if node == target:
            break
        for neighbour in adjacency.get(node, []):
            if neighbour not in coords:
                continue
            step = hyperbolic_distance(coords[node], coords[neighbour])
            candidate = distance + step
            if candidate < best.get(neighbour, float("inf")):
                best[neighbour] = candidate
                previous[neighbour] = node
                heapq.heappush(heap, (candidate, neighbour))
    if target not in best:
        return []
    path = [target]
    while path[-1] in previous:
        path.append(previous[path[-1]])
    return list(reversed(path))



def build_links(
    posts: Sequence[Post],
    min_weight: int = 2,
    max_links: int = 400,
) -> List[Link]:
    """Рёбра графа знаний: посты связываются по общим научным понятиям.

    Вес ребра — число общих ключевых слов. Детерминированно: порядок постов
    задаёт порядок перебора, сортировка по весу и id стабильна.
    """
    word_sets = {post.id: set(keywords(post.title + " " + post.body, 10)) for post in posts}
    ids = [post.id for post in posts]
    links: List[Link] = []
    for index, left in enumerate(ids):
        for right in ids[index + 1 :]:
            weight = len(word_sets[left] & word_sets[right])
            if weight >= min_weight:
                links.append({"source": left, "target": right, "weight": weight})
    links.sort(key=lambda item: (-int(item["weight"]), str(item["source"]), str(item["target"])))
    return links[:max_links]


def pagerank(
    node_ids: Sequence[str],
    links: Sequence[Link],
    damping: float = 0.85,
    iterations: int = 40,
) -> Dict[str, float]:
    """Взвешенный PageRank по неориентированному графу (чистый Python).

    Возвращает нормированные ранги (сумма = 1). Висячие узлы распределяют
    массу равномерно, поэтому сумма сохраняется на каждой итерации.
    """
    ids = list(node_ids)
    total = len(ids)
    if total == 0:
        return {}
    weights: Dict[str, float] = {node: 0.0 for node in ids}
    neighbors: Dict[str, List[Tuple[str, float]]] = {node: [] for node in ids}
    for link in links:
        source, target = str(link["source"]), str(link["target"])
        if source not in neighbors or target not in neighbors:
            continue
        weight = float(link.get("weight", 1) or 1)
        neighbors[source].append((target, weight))
        neighbors[target].append((source, weight))
        weights[source] += weight
        weights[target] += weight

    rank = {node: 1.0 / total for node in ids}
    for _ in range(iterations):
        dangling = sum(rank[node] for node in ids if weights[node] <= 0)
        base = (1.0 - damping) / total + damping * dangling / total
        updated: Dict[str, float] = {}
        for node in ids:
            incoming = 0.0
            for neighbor, weight in neighbors[node]:
                if weights[neighbor] > 0:
                    incoming += rank[neighbor] * weight / weights[neighbor]
            updated[node] = base + damping * incoming
        norm = sum(updated.values()) or 1.0
        rank = {node: value / norm for node, value in updated.items()}
    return rank


def poincare_layout(
    node_ids: Sequence[str],
    domains: Dict[str, str],
    rank: Dict[str, float],
) -> Dict[str, Tuple[float, float]]:
    """Координаты узлов в единичном диске Пуанкаре.

    Важные узлы (высокий PageRank) — ближе к центру; дисциплина задаёт сектор
    (math/physics/cs). Формула переиспользуется из `SOTAKVExtensions`.
    """
    ordered = sorted(node_ids, key=lambda node: (-rank.get(node, 0.0), node))
    total = max(1, len(ordered))
    return {
        node: SOTAKVExtensions.poincare_xy(index, total, domains.get(node, "math"))
        for index, node in enumerate(ordered)
    }


def top_by_pagerank(
    node_ids: Sequence[str],
    rank: Dict[str, float],
    limit: int = 5,
) -> List[str]:
    ordered = sorted(node_ids, key=lambda node: (-rank.get(node, 0.0), node))
    return ordered[:limit]

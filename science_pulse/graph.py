from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

from .models import Post
from .sota import SOTAKVExtensions
from .text import keywords

Link = Dict[str, object]


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
